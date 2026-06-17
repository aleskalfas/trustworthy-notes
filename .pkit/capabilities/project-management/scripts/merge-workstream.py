#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — merge-workstream (verb-subject per DEC-020 + DEC-018).

Merges one or more "loser" workstreams into a "survivor". Per
DEC-018's lifecycle table:

  * Survivor must exist as an active workstream.
  * Losers' issue counts are surfaced before proceeding.
  * Issues using each loser's `workstream:<loser>` label are re-tagged
    to `workstream:<survivor>` (label-substrate adopters).
  * Each loser is removed from workstreams.yaml.
  * The loser label is deleted from the repo.

Per-change confirmation; --yes opts into batch.

Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/merge-workstream.py --survivor cli loser-1 loser-2

Or via the dispatcher (per COR-021):
  pkit project-management merge-workstream --survivor cli loser

Exit codes:
  0  merged
  1  membership refusal / validation refusal
  2  usage error
  3  gh failure
"""

from __future__ import annotations

import argparse
import json
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
    parse_workstreams,
    workstreams_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge one or more workstreams into a survivor.",
    )
    parser.add_argument(
        "--survivor",
        required=True,
        help="The slug that survives. Must exist as an active workstream.",
    )
    parser.add_argument(
        "losers",
        nargs="+",
        help="One or more loser slugs to merge into the survivor.",
    )
    parser.add_argument(
        "--skip-labels",
        action="store_true",
        help="Skip the gh label rename + delete operations.",
    )
    parser.add_argument("--capability-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

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

    if args.survivor in args.losers:
        print(
            "[refused] survivor cannot also be a loser.",
            file=sys.stderr,
        )
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
    if args.survivor not in existing:
        print(
            f"[refused] survivor {args.survivor!r} not found in workstreams.yaml.",
            file=sys.stderr,
        )
        return 1
    missing_losers = [l for l in args.losers if l not in existing]
    if missing_losers:
        print(
            f"[refused] losers not in workstreams.yaml: {', '.join(missing_losers)}.",
            file=sys.stderr,
        )
        return 1

    config = _read_yaml(capability_root / "project" / "config.yaml", yaml_loader)
    has_board = bool(config.get("has_projects_v2_board", False))

    # Per-loser issue counts (best-effort).
    print(f"merge-workstream: survivor={args.survivor}")
    impact: dict[str, int] = {}
    if not has_board and not args.skip_labels:
        for loser in args.losers:
            n = _gh_count_label_uses(f"workstream:{loser}", config)
            impact[loser] = n
            print(f"  loser {loser!r}: {n if n is not None else '?'} issue(s) tagged workstream:{loser}")
    else:
        for loser in args.losers:
            print(f"  loser {loser!r}: (board-substrate or --skip-labels; gh label ops skipped)")

    if args.dry_run:
        print("\n[dry-run] nothing written; no gh invocation.")
        return 0
    if not args.yes and sys.stdin.isatty():
        reply = input(
            f"Merge {len(args.losers)} loser(s) into {args.survivor!r}? [y/N] "
        ).strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    # File mutation.
    ws = data.get("workstreams")
    if isinstance(ws, list):
        new_list = [item for item in ws if item not in args.losers]
        data["workstreams"] = new_list
    elif isinstance(ws, dict):
        for loser in args.losers:
            ws.pop(loser, None)
    try:
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f)
    except OSError as exc:
        print(f"error: failed to write {path}: {exc}", file=sys.stderr)
        return 2

    # Label mutations.
    if not has_board and not args.skip_labels:
        for loser in args.losers:
            ok = _gh_merge_label(loser, args.survivor, config)
            if not ok:
                print(
                    f"[warn] gh label merge for {loser!r} failed.",
                    file=sys.stderr,
                )

    print(
        f"\n[ok] merged {len(args.losers)} loser(s) into {args.survivor!r}."
    )
    return 0


def _gh_count_label_uses(label: str, config: dict) -> int | None:
    """Count open + closed issues with the given label."""
    try:
        proc = gh_run(
            [
                "gh",
                "issue",
                "list",
                "--label",
                label,
                "--state",
                "all",
                "--limit",
                "1000",
                "--json",
                "number",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    try:
        return len(json.loads(proc.stdout))
    except json.JSONDecodeError:
        return None


def _gh_merge_label(loser: str, survivor: str, config: dict) -> bool:
    """Re-tag issues from loser → survivor, then delete the loser label."""
    # 1. Fetch issues with the loser label.
    try:
        proc = gh_run(
            [
                "gh",
                "issue",
                "list",
                "--label",
                f"workstream:{loser}",
                "--state",
                "all",
                "--limit",
                "1000",
                "--json",
                "number",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        return False
    if proc.returncode != 0:
        return False
    try:
        numbers = [item["number"] for item in json.loads(proc.stdout)]
    except (json.JSONDecodeError, KeyError, TypeError):
        return False

    # 2. Re-tag each issue.
    for n in numbers:
        try:
            edit = gh_run(
                [
                    "gh",
                    "issue",
                    "edit",
                    str(n),
                    "--add-label",
                    f"workstream:{survivor}",
                    "--remove-label",
                    f"workstream:{loser}",
                ],
                config,
                check=False,
            )
        except FileNotFoundError:
            return False
        if edit.returncode != 0:
            print(
                f"[warn] failed to retag #{n}: {edit.stderr.strip()}",
                file=sys.stderr,
            )

    # 3. Delete the loser label.
    try:
        delete = gh_run(
            ["gh", "label", "delete", f"workstream:{loser}", "--yes"],
            config,
            check=False,
        )
    except FileNotFoundError:
        return False
    if delete.returncode != 0 and "not found" not in delete.stderr:
        print(
            f"[warn] failed to delete `workstream:{loser}`: {delete.stderr.strip()}",
            file=sys.stderr,
        )
    return True


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
