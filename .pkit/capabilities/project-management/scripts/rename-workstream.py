#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — rename-workstream (verb-subject per DEC-020 + DEC-018).

Renames a workstream's slug. Per DEC-018, this is a label-rename
operation: the workstreams.yaml entry's mapping key changes, the
GitHub `workstream:<old>` label is renamed to `workstream:<new>`,
issues using the old label are re-tagged automatically by gh's
rename behaviour.

Per-change confirmation: the script narrates the plan and prompts
unless `--yes` is set.

Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/rename-workstream.py <old> <new>

Or via the dispatcher (per COR-021):
  pkit project-management rename-workstream <old> <new>

Exit codes:
  0  renamed (or dry-run reported)
  1  membership refusal / validation refusal
  2  usage error
  3  gh failure
"""

from __future__ import annotations

import argparse
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
    parser = argparse.ArgumentParser(description="Rename a workstream slug.")
    parser.add_argument("old", help="Current slug.")
    parser.add_argument("new", help="Target slug.")
    parser.add_argument(
        "--skip-label",
        action="store_true",
        help="Skip the `gh label edit workstream:<old> --name workstream:<new>` step.",
    )
    parser.add_argument("--capability-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if not SLUG_PATTERN.match(args.new):
        print(
            f"[refused] new slug {args.new!r} does not match the slug pattern.",
            file=sys.stderr,
        )
        return 1
    if args.old == args.new:
        print("[noop] new slug equals old slug.")
        return 0

    capability_root = resolve_capability_root(args.capability_root)
    if capability_root is None:
        print(f"error: {CAPABILITY_NAME} capability not found.", file=sys.stderr)
        return 2

    yaml_loader = YAML(typ="safe")
    config = load_adopter_config(capability_root)
    members = _read_members(capability_root, yaml_loader)
    invoker = resolve_invoker_identity(config=config)
    membership = check_membership(members, invoker)
    if not membership.allowed:
        print(membership.refusal_message, file=sys.stderr)
        return 1

    path = workstreams_path(capability_root)
    if not path.is_file():
        print(
            f"error: {path} does not exist. Run `add-workstream` or the "
            "v0.5.0 migration first.",
            file=sys.stderr,
        )
        return 2

    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.load(f) or {}
    except (OSError, YAMLError) as exc:
        print(f"error: failed to parse {path}: {exc}", file=sys.stderr)
        return 2

    parsed = parse_workstreams(data)
    existing = {w.slug for w in parsed.entries}
    if args.old not in existing:
        print(f"error: workstream {args.old!r} not found.", file=sys.stderr)
        return 2
    if args.new in existing:
        print(
            f"[refused] workstream {args.new!r} already exists. Use "
            "merge-workstream if you want to consolidate.",
            file=sys.stderr,
        )
        return 1

    config = _read_yaml(capability_root / "project" / "config.yaml", yaml_loader)
    has_board = bool(config.get("has_projects_v2_board", False))

    print(f"rename-workstream: {args.old} → {args.new}")
    print(f"  file:        {path}")
    if not has_board and not args.skip_label:
        print(f"  label:       rename `workstream:{args.old}` → `workstream:{args.new}`")

    if args.dry_run:
        print("\n[dry-run] nothing written; no gh invocation.")
        return 0
    if not args.yes and sys.stdin.isatty():
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    if not _rename_in_file(yaml, data, args.old, args.new, path):
        return 2

    if not has_board and not args.skip_label:
        ok = _gh_label_rename(args.old, args.new, config)
        if not ok:
            print(
                "[warn] workstreams.yaml updated but gh label rename failed.",
                file=sys.stderr,
            )

    print(f"\n[ok] renamed workstream {args.old!r} → {args.new!r}.")
    return 0


def _rename_in_file(
    yaml: YAML, data: dict, old: str, new: str, path: Path
) -> bool:
    ws = data.get("workstreams")
    if isinstance(ws, list):
        new_list = [new if item == old else item for item in ws]
        data["workstreams"] = new_list
    elif isinstance(ws, dict):
        # Rebuild preserving insertion order.
        new_map = {}
        for k, v in ws.items():
            if k == old:
                new_map[new] = v
            else:
                new_map[k] = v
        data["workstreams"] = new_map
    else:
        print(f"error: {path} `workstreams:` is malformed.", file=sys.stderr)
        return False

    try:
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f)
    except OSError as exc:
        print(f"error: failed to write {path}: {exc}", file=sys.stderr)
        return False
    return True


def _gh_label_rename(old: str, new: str, config: dict) -> bool:
    """Rename `workstream:<old>` to `workstream:<new>` via gh label edit."""
    try:
        proc = gh_run(
            [
                "gh",
                "label",
                "edit",
                f"workstream:{old}",
                "--name",
                f"workstream:{new}",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        return False
    if proc.returncode == 0:
        return True
    if "not found" in proc.stderr:
        print(
            f"[info] label `workstream:{old}` not present; nothing to rename.",
            file=sys.stderr,
        )
        return True
    print(
        f"error: gh label edit failed (exit {proc.returncode}).\n"
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
