#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — add-workstream (verb-subject per DEC-020 + DEC-018).

Adds a workstream to `project/workstreams.yaml`. Validates the slug
against `schemas/workstreams.schema.json`'s pattern; refuses
duplicates; defaults `name` to the slug; defaults `status` to active.

For label-substrate adopters, additionally creates the
`workstream:<slug>` label via `gh label create` (idempotent — skips
if it already exists).

Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/add-workstream.py <slug> [--name "..."] [--description "..."]

Or via the dispatcher (per COR-021):
  pkit project-management add-workstream <slug>

Exit codes:
  0  added (or dry-run reported)
  1  membership refusal / validation refusal / duplicate slug
  2  usage error (capability not found; bad slug)
  3  gh failure (label creation)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
from _lib.gh import gh_run, load_adopter_config  # noqa: E402
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    check_membership,
    resolve_capability_root,
    resolve_invoker_identity,
)
from _lib.workstreams import (  # noqa: E402
    SLUG_PATTERN,
    parse_workstreams,
    workstreams_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Add a workstream to project/workstreams.yaml per DEC-018."
        ),
    )
    parser.add_argument(
        "slug",
        help="Kebab-case slug. Must match `^[a-z][a-z0-9-]*[a-z0-9]$`, 2–40 chars.",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Human-readable name. Defaults to the slug.",
    )
    parser.add_argument(
        "--description",
        default=None,
        help="One-line description, ≤200 chars.",
    )
    parser.add_argument(
        "--status",
        choices=["active", "deprecated"],
        default="active",
        help="Lifecycle status. Default: active.",
    )
    parser.add_argument(
        "--deprecated-reason",
        default=None,
        help="Required when --status=deprecated.",
    )
    parser.add_argument(
        "--skip-label",
        action="store_true",
        help=(
            "Skip the `gh label create workstream:<slug>` step "
            "(label-substrate adopters only)."
        ),
    )
    parser.add_argument(
        "--capability-root",
        type=Path,
        default=None,
        help=(
            "Path to the installed capability's directory "
            f"(default: <repo-root>/.pkit/capabilities/{CAPABILITY_NAME}/)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan; do not write.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    args = parser.parse_args()

    capability_root = resolve_capability_root(args.capability_root)
    if capability_root is None:
        print(
            f"error: {CAPABILITY_NAME} capability not found.",
            file=sys.stderr,
        )
        return 2

    yaml_loader = YAML(typ="safe")
    config = load_adopter_config(capability_root)
    members = _read_members(capability_root, yaml_loader)
    invoker = resolve_invoker_identity(config=config)
    membership = check_membership(members, invoker)
    if not membership.allowed:
        print(membership.refusal_message, file=sys.stderr)
        return 1

    # Slug validation.
    err = validate_slug(args.slug)
    if err:
        print(f"[refused] {err}", file=sys.stderr)
        return 1

    if args.status == "deprecated" and not args.deprecated_reason:
        print(
            "[refused] --deprecated-reason is required when --status=deprecated.",
            file=sys.stderr,
        )
        return 1

    # Read current state.
    config = _read_yaml(capability_root / "project" / "config.yaml", yaml_loader)
    has_board = bool(config.get("has_projects_v2_board", False))

    current = _read_workstreams_file_or_legacy(capability_root, yaml_loader)
    parsed = parse_workstreams(current if current else None)

    existing_slugs = {w.slug for w in parsed.entries}
    if args.slug in existing_slugs:
        print(
            f"[refused] workstream {args.slug!r} already exists.",
            file=sys.stderr,
        )
        return 1

    new_entry = {
        "name": args.name or args.slug,
    }
    if args.description:
        new_entry["description"] = args.description
    new_entry["status"] = args.status
    if args.deprecated_reason:
        new_entry["deprecated_reason"] = args.deprecated_reason

    print(f"add-workstream: {args.slug}")
    print(f"  name:        {new_entry['name']}")
    if "description" in new_entry:
        print(f"  description: {new_entry['description']}")
    print(f"  status:      {new_entry['status']}")
    if "deprecated_reason" in new_entry:
        print(f"  reason:      {new_entry['deprecated_reason']}")
    print(f"  target file: {workstreams_path(capability_root)}")
    if not has_board and not args.skip_label:
        print(f"  label:       create `workstream:{args.slug}` (label-substrate)")

    if args.dry_run:
        print("\n[dry-run] nothing written; no gh invocation.")
        return 0
    if not args.yes and sys.stdin.isatty():
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    # Write the file.
    if not _add_to_file(capability_root, args.slug, new_entry):
        return 2

    # Create the label for label-substrate adopters.
    if not has_board and not args.skip_label:
        if not _gh_label_create(args.slug, config):
            print(
                "[warn] workstreams.yaml updated but gh label create failed; "
                "re-run bootstrap to reconcile.",
                file=sys.stderr,
            )

    print(f"\n[ok] added workstream {args.slug!r}.")
    return 0


# ---- slug validation ------------------------------------------------


def validate_slug(slug: str) -> str | None:
    """Return an error message string if invalid, None if valid."""
    if not isinstance(slug, str) or not slug:
        return "slug must be a non-empty string"
    if not SLUG_PATTERN.match(slug):
        return (
            f"slug {slug!r} does not match `^[a-z][a-z0-9-]*[a-z0-9]$`. "
            "Kebab-case, lowercase, no leading or trailing hyphen, no underscores."
        )
    if "--" in slug:
        return f"slug {slug!r} contains consecutive hyphens (forbidden)."
    if not (2 <= len(slug) <= 40):
        return f"slug {slug!r} length must be 2–40 chars; got {len(slug)}."
    return None


# ---- file I/O -------------------------------------------------------


def _read_workstreams_file_or_legacy(
    capability_root: Path, yaml_loader: YAML
) -> dict | list | None:
    """Read workstreams from the dedicated file, falling back to config.yaml."""
    path = workstreams_path(capability_root)
    if path.is_file():
        return _read_yaml(path, yaml_loader)
    config = _read_yaml(capability_root / "project" / "config.yaml", yaml_loader)
    return config.get("workstreams")


def _add_to_file(
    capability_root: Path, slug: str, entry: dict
) -> bool:
    """Append the entry to workstreams.yaml (round-trip preserving)."""
    path = workstreams_path(capability_root)
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True

    if not path.is_file():
        # Bootstrap the file with mapping form.
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"schema_version": 1, "workstreams": {slug: entry}}
        try:
            with path.open("w", encoding="utf-8") as f:
                yaml.dump(data, f)
            return True
        except OSError as exc:
            print(f"error: failed to write {path}: {exc}", file=sys.stderr)
            return False

    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.load(f) or {}
    except (OSError, YAMLError) as exc:
        print(f"error: failed to parse {path}: {exc}", file=sys.stderr)
        return False
    if not isinstance(data, dict):
        print(f"error: {path} top-level is not a mapping", file=sys.stderr)
        return False

    ws = data.get("workstreams")
    if isinstance(ws, list):
        # Upgrade to mapping form before adding the attributed entry.
        upgraded: dict = {}
        for item in ws:
            if isinstance(item, str):
                upgraded[item] = {"name": item, "status": "active"}
        upgraded[slug] = entry
        data["workstreams"] = upgraded
    elif isinstance(ws, dict):
        ws[slug] = entry
    else:
        data["workstreams"] = {slug: entry}

    data.setdefault("schema_version", 1)

    try:
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f)
    except OSError as exc:
        print(f"error: failed to write {path}: {exc}", file=sys.stderr)
        return False
    return True


# ---- gh wrapper -----------------------------------------------------


def _gh_label_create(slug: str, config: dict) -> bool:
    try:
        proc = gh_run(
            [
                "gh",
                "label",
                "create",
                f"workstream:{slug}",
                "--color",
                "0e8a16",
                "--description",
                f"Workstream `{slug}` (per project-management:DEC-018).",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        return False
    if proc.returncode == 0:
        return True
    # `gh label create` exits non-zero on already-exists.
    if "already exists" in proc.stderr or "already exists" in proc.stdout:
        return True
    print(
        f"error: gh label create failed (exit {proc.returncode}).\n"
        f"stderr: {proc.stderr.strip()}",
        file=sys.stderr,
    )
    return False


def _read_yaml(path: Path, yaml_loader: YAML) -> dict:
    if not path.is_file():
        return {}
    try:
        data = yaml_loader.load(path.read_text(encoding="utf-8"))
    except (OSError, YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_members(capability_root: Path, yaml_loader: YAML) -> list[dict]:
    data = _read_yaml(capability_root / "project" / "members.yaml", yaml_loader)
    members = data.get("members") or []
    return members if isinstance(members, list) else []


if __name__ == "__main__":
    sys.exit(main())
