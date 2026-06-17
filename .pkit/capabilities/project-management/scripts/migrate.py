#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — migrate.

Adopter-state reconciliation after a capability upgrade. Reads versioned
migration manifests from `../migrations/<version>.yaml`, compares against
the adopter's per-capability applied-migrations state, presents the
pending plan, and executes confirmed changes with per-change hard gates.

Contract per the capability's DEC-017-prerequisites-bootstrap-migrate-
discipline. Programmatic, not AI-mediated. Never auto-chained from
`pkit capabilities upgrade` — explicit invocation only.

Self-contained via PEP 723 inline metadata: run via
  uv run --script .pkit/capabilities/project-management/scripts/migrate.py

Exit codes:
  0  success (including "no pending migrations")
  1  one or more change executions failed
  2  usage error (capability not found; refused due to pre-check failure;
     malformed manifest)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


CAPABILITY_NAME = "project-management"
MIGRATIONS_SUBDIR = "migrations"
APPLIED_STATE_PATH = "project/migrations-applied.yaml"
PRE_CHECK_SCRIPT = "scripts/pre-check.py"

RECOGNISED_KINDS = frozenset({"label-rename", "label-delete", "label-create"})


@dataclass
class Migration:
    """One migration manifest entry."""

    target_version: str
    description: str
    changes: list[dict[str, Any]]
    path: Path


@dataclass
class ChangeResult:
    """Outcome of one change within a migration."""

    summary: str
    status: str  # "applied" | "skipped" | "failed"
    detail: str = ""


@dataclass
class AppliedRecord:
    """One entry in the adopter-side applied-migrations file."""

    version: str
    applied_at: str
    by: str
    changes_summary: list[str] = field(default_factory=list)


# ----- script entry --------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate adopter GitHub state to match the current capability "
            "version's expectations. Reads migration manifests; per-change "
            "confirmation by default."
        ),
    )
    parser.add_argument(
        "--capability-root",
        type=Path,
        default=None,
        help=(
            "Path to the installed capability's directory "
            "(default: <repo-root>/.pkit/capabilities/project-management/)."
        ),
    )
    parser.add_argument(
        "--skip-pre-check",
        action="store_true",
        help=(
            "Run migrate without first running pre-check. Use only when "
            "pre-check is known to fail for reasons unrelated to migration "
            "safety. Otherwise: fix the pre-check failure first."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Walk the plan and confirmation flow but skip the actual gh "
            "mutations. State file is not updated."
        ),
    )
    args = parser.parse_args()

    capability_root = _resolve_capability_root(args.capability_root)
    if capability_root is None:
        print(
            "error: project-management capability not found.",
            file=sys.stderr,
        )
        return 2

    repo = _resolve_repo_name_with_owner()
    _print_context_header(repo, capability_root)

    # Run pre-check first unless explicitly skipped.
    if not args.skip_pre_check:
        pre_check_path = capability_root / PRE_CHECK_SCRIPT
        if pre_check_path.is_file():
            print("Running pre-check before migration...")
            result = subprocess.run(
                [str(pre_check_path)], check=False
            )
            if result.returncode != 0:
                print(
                    "\nerror: pre-check failed. migrate refuses to run on a "
                    "project with unmet prerequisites (drift in basic state "
                    "breaks migration plan computation). Fix pre-check "
                    "failures first, then re-run migrate. To override (rarely "
                    "appropriate), pass --skip-pre-check.",
                    file=sys.stderr,
                )
                return 2
            print()

    # Load every manifest in migrations/.
    migrations, manifest_err = _load_migrations(capability_root)
    if migrations is None:
        print(f"error: {manifest_err}", file=sys.stderr)
        return 2

    # Load the adopter's applied-state file.
    applied_versions = _load_applied_versions(capability_root)

    # Compute pending: manifests whose target_version isn't already applied.
    pending = [m for m in migrations if m.target_version not in applied_versions]
    pending.sort(key=lambda m: _version_tuple(m.target_version))

    if not pending:
        print(
            f"No pending migrations. "
            f"({len(migrations)} manifest(s) total; {len(applied_versions)} already applied)."
        )
        return 0

    print(f"{len(pending)} pending migration(s):")
    for m in pending:
        print(f"  - {m.target_version} ({m.path.name})")
    print()

    overall_status = 0
    for m in pending:
        rc = _apply_migration(m, capability_root, dry_run=args.dry_run)
        if rc != 0:
            overall_status = rc
            print(
                f"\nMigration {m.target_version} did not complete. "
                f"Subsequent migrations not attempted.",
                file=sys.stderr,
            )
            break

    return overall_status


# ----- migration application -----------------------------------------


def _apply_migration(
    migration: Migration, capability_root: Path, *, dry_run: bool
) -> int:
    print(f"=== Migration {migration.target_version} ===")
    if migration.description:
        for line in migration.description.strip().split("\n"):
            print(f"  {line}")
        print()

    print(f"  Plan ({len(migration.changes)} change(s)):")
    for i, change in enumerate(migration.changes, start=1):
        print(f"    {i}. {_describe_change(change)}")
    print()

    results: list[ChangeResult] = []
    fetched_labels: set[str] | None = None
    for change in migration.changes:
        kind = change.get("kind")
        if kind not in RECOGNISED_KINDS:
            results.append(
                ChangeResult(
                    summary=_describe_change(change),
                    status="failed",
                    detail=f"unknown kind '{kind}' (recognised: {sorted(RECOGNISED_KINDS)})",
                )
            )
            continue

        if not _confirm_change(change, dry_run=dry_run):
            results.append(
                ChangeResult(
                    summary=_describe_change(change),
                    status="skipped",
                    detail="user declined",
                )
            )
            continue

        if dry_run:
            results.append(
                ChangeResult(
                    summary=_describe_change(change),
                    status="applied",
                    detail="(dry-run) would apply",
                )
            )
            continue

        if kind == "label-rename":
            results.append(_execute_label_rename(change))
        elif kind == "label-delete":
            results.append(_execute_label_delete(change))
        elif kind == "label-create":
            results.append(_execute_label_create(change))

    _print_migration_summary(results)

    failed = sum(1 for r in results if r.status == "failed")
    if failed:
        return 1

    # All changes either applied or skipped (no failures) — record the migration as applied.
    if not dry_run:
        _record_applied(migration, results, capability_root)

    return 0


# ----- change descriptors --------------------------------------------


def _describe_change(change: dict[str, Any]) -> str:
    kind = change.get("kind", "<unknown>")
    if kind == "label-rename":
        re_tag = " + re-tag issues" if change.get("re_tag_issues") else ""
        return f"label-rename `{change.get('from')}` -> `{change.get('to')}`{re_tag}"
    if kind == "label-delete":
        guard = " (refuse if used)" if change.get("refuse_if_used", True) else ""
        return f"label-delete `{change.get('label')}`{guard}"
    if kind == "label-create":
        return f"label-create `{change.get('name')}`"
    return f"<{kind}> {change}"


# ----- confirmation --------------------------------------------------


def _confirm_change(change: dict[str, Any], *, dry_run: bool) -> bool:
    """Per-change confirmation prompt.

    Returns True to apply, False to skip. In non-interactive environments
    (no TTY), defaults to False (skip) — opt-in to non-interactive via
    a future --config file declaring pre-approvals (deferred; see DEC-017).
    """
    prompt_suffix = " [dry-run]" if dry_run else ""
    summary = _describe_change(change)
    if not sys.stdin.isatty():
        print(f"  ! Non-interactive shell; skipping change: {summary}")
        print(f"    To apply, re-run from an interactive shell.")
        return False
    while True:
        try:
            response = input(f"  Apply: {summary}{prompt_suffix} ? [y/N]: ").strip().lower()
        except EOFError:
            return False
        if response in ("y", "yes"):
            return True
        if response in ("", "n", "no"):
            return False
        print("  Please answer y or n.")


# ----- executors -----------------------------------------------------


def _execute_label_rename(change: dict[str, Any]) -> ChangeResult:
    from_name = change.get("from")
    to_name = change.get("to")
    if not from_name or not to_name:
        return ChangeResult(
            _describe_change(change),
            "failed",
            "missing `from` or `to` in label-rename",
        )

    proc = subprocess.run(
        ["gh", "label", "edit", from_name, "--name", to_name],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ChangeResult(
            _describe_change(change),
            "failed",
            f"`gh label edit` exit {proc.returncode}: {proc.stderr.strip()}",
        )
    # Re-tagging issues is automatic in `gh label edit --name` (the label
    # itself is renamed atomically on the server; all issues carrying the
    # old name now carry the new name). The re_tag_issues flag is
    # informational — included in the manifest for clarity.
    return ChangeResult(_describe_change(change), "applied")


def _execute_label_delete(change: dict[str, Any]) -> ChangeResult:
    label = change.get("label")
    if not label:
        return ChangeResult(
            _describe_change(change),
            "failed",
            "missing `label` in label-delete",
        )
    refuse_if_used = change.get("refuse_if_used", True)

    if refuse_if_used:
        # Check whether any issues use the label.
        proc = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--label",
                label,
                "--state",
                "all",
                "--json",
                "number",
                "--limit",
                "1",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip() not in ("", "[]"):
            return ChangeResult(
                _describe_change(change),
                "failed",
                f"label `{label}` still used by at least one issue; "
                f"refuse_if_used=true; un-label the issues first or set "
                f"refuse_if_used=false in the manifest.",
            )

    proc = subprocess.run(
        ["gh", "label", "delete", label, "--yes"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ChangeResult(
            _describe_change(change),
            "failed",
            f"`gh label delete` exit {proc.returncode}: {proc.stderr.strip()}",
        )
    return ChangeResult(_describe_change(change), "applied")


def _execute_label_create(change: dict[str, Any]) -> ChangeResult:
    name = change.get("name")
    if not name:
        return ChangeResult(
            _describe_change(change),
            "failed",
            "missing `name` in label-create",
        )
    color = change.get("color", "ededed")
    description = change.get("description", "")
    proc = subprocess.run(
        [
            "gh",
            "label",
            "create",
            name,
            "--color",
            color,
            "--description",
            description,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ChangeResult(
            _describe_change(change),
            "failed",
            f"`gh label create` exit {proc.returncode}: {proc.stderr.strip()}",
        )
    return ChangeResult(_describe_change(change), "applied")


# ----- state file ----------------------------------------------------


def _load_applied_versions(capability_root: Path) -> set[str]:
    path = capability_root / APPLIED_STATE_PATH
    if not path.is_file():
        return set()
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError):
        return set()
    if not isinstance(data, dict):
        return set()
    applied = data.get("applied", [])
    if not isinstance(applied, list):
        return set()
    return {
        entry.get("version")
        for entry in applied
        if isinstance(entry, dict) and entry.get("version")
    }


def _record_applied(
    migration: Migration,
    results: list[ChangeResult],
    capability_root: Path,
) -> None:
    """Append a new entry to migrations-applied.yaml. Auto-create the file."""
    path = capability_root / APPLIED_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)

    if path.is_file():
        try:
            data = yaml.load(path.read_text(encoding="utf-8")) or {}
        except YAMLError:
            data = {}
    else:
        data = {"schema_version": 1, "applied": []}

    if "applied" not in data or not isinstance(data["applied"], list):
        data["applied"] = []

    applied_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    by = _resolve_actor()
    changes_summary = [r.summary for r in results if r.status == "applied"]

    data["applied"].append(
        {
            "version": migration.target_version,
            "applied_at": applied_at,
            "by": by,
            "changes": changes_summary,
        }
    )

    with path.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh)

    print(f"\n  Recorded migration {migration.target_version} in {path}")


def _resolve_actor() -> str:
    """Capture name + email from `git config` for the audit trail."""
    try:
        name = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True, check=False
        ).stdout.strip()
        email = subprocess.run(
            ["git", "config", "user.email"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        name, email = "", ""
    if name and email:
        return f"{name} <{email}>"
    return os.environ.get("USER", "unknown")


def _print_context_header(repo: str, capability_root: Path) -> None:
    """Print the target repo + capability + state-file paths before any action.

    Surfaces *which* repo and *which* capability install the script is
    operating on. Defensive against running the script in the wrong
    project tree (multiple checkouts open, wrong cwd, etc.).
    """
    version = _read_capability_version(capability_root)
    applied_path = capability_root / APPLIED_STATE_PATH
    print("migrate: project-management capability")
    print(f"  target repo:   {repo}")
    print(f"  capability:    {capability_root} (v{version})")
    print(f"  applied state: {applied_path}")
    print()


def _resolve_repo_name_with_owner() -> str:
    """Best-effort `<owner>/<repo>` for the current working tree."""
    proc = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return "<unresolved>"
    try:
        return json.loads(proc.stdout).get("nameWithOwner", "<unresolved>")
    except json.JSONDecodeError:
        return "<unresolved>"


def _read_capability_version(capability_root: Path) -> str:
    pkg = capability_root / "package.yaml"
    if not pkg.is_file():
        return "<unknown>"
    try:
        data = YAML(typ="safe").load(pkg.read_text(encoding="utf-8")) or {}
        return str(data.get("component", {}).get("version", "<unknown>"))
    except (OSError, YAMLError):
        return "<unknown>"


# ----- manifest loading ----------------------------------------------


def _load_migrations(
    capability_root: Path,
) -> tuple[list[Migration] | None, str]:
    migrations_dir = capability_root / MIGRATIONS_SUBDIR
    if not migrations_dir.is_dir():
        return [], ""

    manifests: list[Migration] = []
    for path in sorted(migrations_dir.glob("*.yaml")):
        if path.name == "README.md":
            continue
        try:
            data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
        except (OSError, YAMLError) as exc:
            return None, f"failed to read {path}: {exc}"
        if not isinstance(data, dict):
            return None, f"{path} top-level is not a mapping"
        target = data.get("target_version")
        if not target:
            return None, f"{path} missing `target_version`"
        changes = data.get("changes", [])
        if not isinstance(changes, list):
            return None, f"{path} `changes` is not a list"
        manifests.append(
            Migration(
                target_version=str(target),
                description=str(data.get("description", "")),
                changes=changes,
                path=path,
            )
        )
    return manifests, ""


# ----- helpers -------------------------------------------------------


def _version_tuple(v: str) -> tuple[int, ...]:
    """Tuple form for sortable version comparison. Best-effort; falls back
    on a stringly comparison for non-semver shapes."""
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        # Non-numeric segment — fall back to lexical sort.
        return (0,)


def _resolve_capability_root(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_dir() else None
    cur = Path.cwd()
    while cur != cur.parent:
        candidate = cur / ".pkit" / "capabilities" / CAPABILITY_NAME
        if candidate.is_dir():
            return candidate
        cur = cur.parent
    return None


def _print_migration_summary(results: list[ChangeResult]) -> None:
    print()
    applied = sum(1 for r in results if r.status == "applied")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = sum(1 for r in results if r.status == "failed")
    for r in results:
        marker = {
            "applied": "[applied]",
            "skipped": "[skipped]",
            "failed": "[failed] ",
        }[r.status]
        line = f"  {marker} {r.summary}"
        if r.detail:
            line += f"\n            → {r.detail}"
        print(line)
    print()
    print(f"  Summary: {applied} applied, {skipped} skipped, {failed} failed.")


if __name__ == "__main__":
    sys.exit(main())
