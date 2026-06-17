#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — bootstrap.

First-time adoption setup. Creates the methodology's required initial
GitHub state (labels for the three classification axes; optionally a
starter EPIC) so the capability is operational on a fresh project.

Additive idempotent: skips state that already exists. Never modifies
or deletes — that's the migrate script's job. Re-running on a
fully-bootstrapped project is a clean no-op.

Label-fallback mode: when `has_projects_v2_board` is false (the
adopter is not using a Projects v2 board), bootstrap also creates the
five lifecycle state labels (`state:todo`, `state:backlog`,
`state:in-progress`, `state:review`, `state:done`) derived from
`workflow.yaml`'s `states[].id` list. These labels are the substrate
for the `move-issue` state machine on label-fallback adopters.

Contract per the capability's DEC-017-prerequisites-bootstrap-migrate-
discipline. Programmatic, not AI-mediated.

Self-contained via PEP 723 inline metadata: run via
  uv run --script .pkit/capabilities/project-management/scripts/bootstrap.py

Exit codes:
  0  success (including "everything already exists")
  1  one or more creation operations failed
  2  usage error (capability not found; config unparseable; no PM
     authorisation for --with-starter-epic)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


CAPABILITY_NAME = "project-management"
ADOPTER_CONFIG_PATH = "project/config.yaml"

# Default label colors. Adopters may override post-creation via gh label edit;
# bootstrap doesn't track or migrate color choices.
LABEL_COLORS = {
    "type": "1d76db",       # blue
    "priority": "d93f0b",   # red-orange
    "workstream": "0e8a16", # green
    "state": "fbca04",      # yellow — lifecycle state substrate for label-fallback adopters
}

LABEL_DESCRIPTIONS = {
    "type": "Classification axis: structural kind of work (per project-management:DEC-012-classification-axes).",
    "priority": "Classification axis: triage signal (per project-management:DEC-012-classification-axes).",
    "workstream": "Classification axis: cross-repo workstream (per project-management:DEC-012-classification-axes).",
    "state": "Lifecycle state (label-fallback substrate, per project-management workflow.yaml states).",
}


@dataclass(frozen=True)
class Action:
    """One bootstrap action taken (or skipped)."""

    label: str
    status: str  # "created" | "exists" | "skipped" | "failed"
    detail: str = ""


# ----- script entry --------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap a fresh project for the project-management capability. "
            "Creates labels and (optionally) a starter EPIC. Additive only."
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
        "--with-starter-epic",
        action="store_true",
        help=(
            "Also file a starter EPIC titled '[EPIC] Methodology adoption — "
            "initial hierarchy'. EPICs are PM-authority filing per DEC-008; "
            "passing this flag IS the PM authorisation."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without actually creating it.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Skip the 'apply this plan to <repo>?' confirmation prompt. "
            "Use only after you have read the plan in --dry-run output. "
            "Defaults off so accidental cwd-mismatched runs are caught."
        ),
    )
    args = parser.parse_args()

    capability_root = _resolve_capability_root(args.capability_root)
    if capability_root is None:
        print(
            "error: project-management capability not found. "
            "Run this script from within an adopter project with the "
            "capability installed at .pkit/capabilities/project-management/.",
            file=sys.stderr,
        )
        return 2

    config, config_err = _load_adopter_config(capability_root)
    if config is None:
        print(f"error: {config_err}", file=sys.stderr)
        return 2

    # gh: block validation + host-pinned auth check (per DEC-023).
    gh_err = _check_gh_block_and_auth(config)
    if gh_err is not None:
        print(f"error: {gh_err}", file=sys.stderr)
        return 2

    # Read classification.yaml for the canonical label vocabularies.
    classification, class_err = _load_classification(capability_root)
    if classification is None:
        print(f"error: {class_err}", file=sys.stderr)
        return 2

    repo = _resolve_repo_name_with_owner()
    _print_context_header(repo, capability_root)

    has_board = bool(config.get("has_projects_v2_board"))

    # ---- compute the plan (read-only) ----
    plan = _compute_plan(
        config, classification, has_board, args.with_starter_epic, capability_root
    )
    _print_plan(plan)

    # ---- confirm before mutating ----
    if not plan.has_creates():
        print("Nothing to create — repo already in the methodology's expected initial state.")
        return 0

    if args.dry_run:
        print("(dry-run: skipping confirmation and execution; no GitHub mutations.)")
        return 0

    if not args.yes and not _confirm_apply(repo):
        print("Aborted by user. No GitHub mutations were performed.")
        return 0

    # ---- execute the plan ----
    actions = _execute_plan(plan)
    _print_report(actions)

    failures = sum(1 for a in actions if a.status == "failed")
    return 0 if failures == 0 else 1


# ----- plan computation + execution ----------------------------------


@dataclass
class Plan:
    """The bootstrap plan: what would be created vs already exists."""

    label_creates: list[tuple[str, str]]  # (axis, name)
    label_exists: list[str]                # names already in repo
    starter_epic: bool                     # whether to file the starter EPIC
    starter_epic_exists: bool              # whether it's already filed
    skipped_messages: list[str]            # explanatory skip notes (e.g., board mode)

    def has_creates(self) -> bool:
        return bool(self.label_creates) or (
            self.starter_epic and not self.starter_epic_exists
        )


def _compute_plan(
    config: dict[str, Any],
    classification: dict[str, Any],
    has_board: bool,
    with_starter_epic: bool,
    capability_root: Path,
) -> Plan:
    """Compare schemas+config against existing GitHub state; emit the plan."""
    existing_labels = _fetch_existing_labels() or set()

    label_creates: list[tuple[str, str]] = []
    label_exists: list[str] = []
    skipped: list[str] = []

    def _plan_axis(axis: str, values: list[str]) -> None:
        for v in values:
            name = f"{axis}:{v}"
            if name in existing_labels:
                label_exists.append(name)
            else:
                label_creates.append((axis, name))

    type_values = classification.get("axes", {}).get("type", {}).get("values", [])
    _plan_axis("type", type_values)

    if has_board:
        skipped.append(
            "priority:* / workstream:* labels — board configured; "
            "those axes live as board fields (not labels)."
        )
        skipped.append(
            "state:* labels — board configured; state lives as a Projects v2 Status field."
        )
    else:
        priority_values = (
            classification.get("axes", {}).get("priority", {}).get("values", [])
        )
        _plan_axis("priority", priority_values)
        workstreams = _resolve_workstream_slugs(capability_root, config)
        if workstreams:
            _plan_axis("workstream", workstreams)
        else:
            skipped.append(
                "workstream:* labels — no workstreams declared "
                "(in workstreams.yaml or config.yaml fallback)."
            )
        # Label-fallback mode: create state:* labels from workflow.yaml states.
        state_ids = _resolve_state_ids(capability_root)
        if state_ids:
            _plan_axis("state", state_ids)
        else:
            skipped.append(
                "state:* labels — workflow.yaml missing or no states declared "
                "(capability install may be corrupt)."
            )

    starter_epic_exists = False
    if with_starter_epic:
        starter_epic_exists = _starter_epic_already_filed()

    return Plan(
        label_creates=label_creates,
        label_exists=label_exists,
        starter_epic=with_starter_epic,
        starter_epic_exists=starter_epic_exists,
        skipped_messages=skipped,
    )


def _print_plan(plan: Plan) -> None:
    print("Plan:")
    if plan.label_creates:
        for _, name in plan.label_creates:
            print(f"  + create label `{name}`")
    if plan.label_exists:
        print(f"  ({len(plan.label_exists)} label(s) already exist; will be left untouched)")
    if plan.starter_epic:
        if plan.starter_epic_exists:
            print("  (starter EPIC already filed; will be left untouched)")
        else:
            print("  + file starter EPIC `[EPIC] Methodology adoption — initial hierarchy`")
    for msg in plan.skipped_messages:
        print(f"  · {msg}")
    print()


def _confirm_apply(repo: str) -> bool:
    """Single confirmation prompt naming the target repo."""
    if not sys.stdin.isatty():
        print(
            f"  ! Non-interactive shell; refusing to apply without explicit confirmation.\n"
            f"    Re-run from an interactive shell, or pass --yes after reviewing the plan."
        )
        return False
    while True:
        try:
            response = input(f"Apply this plan to `{repo}`? [y/N]: ").strip().lower()
        except EOFError:
            return False
        if response in ("y", "yes"):
            return True
        if response in ("", "n", "no"):
            return False
        print("  Please answer y or n.")


def _execute_plan(plan: Plan) -> list[Action]:
    """Run the gh mutations declared in the plan."""
    actions: list[Action] = []
    # Group creates by axis so we apply consistent color/description.
    by_axis: dict[str, list[str]] = {}
    for axis, name in plan.label_creates:
        by_axis.setdefault(axis, []).append(name)
    for axis, names in by_axis.items():
        actions.extend(_apply_label_creates(axis, names))
    for name in plan.label_exists:
        actions.append(Action(f"label `{name}`", "exists", "no-op"))
    if plan.starter_epic and not plan.starter_epic_exists:
        actions.append(_file_starter_epic(dry_run=False))
    elif plan.starter_epic and plan.starter_epic_exists:
        actions.append(
            Action(
                "starter EPIC",
                "exists",
                "already filed; no-op",
            )
        )
    return actions


def _apply_label_creates(axis: str, names: list[str]) -> list[Action]:
    color = LABEL_COLORS.get(axis, "ededed")
    description = LABEL_DESCRIPTIONS.get(axis, "")
    out: list[Action] = []
    for name in names:
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
        if proc.returncode == 0:
            out.append(Action(f"label `{name}`", "created"))
        else:
            out.append(
                Action(
                    f"label `{name}`",
                    "failed",
                    f"`gh label create` exit {proc.returncode}: {proc.stderr.strip()}",
                )
            )
    return out


def _starter_epic_already_filed() -> bool:
    """Check whether the starter EPIC has already been filed."""
    title = "[EPIC] Methodology adoption — initial hierarchy"
    proc = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "--search",
            f'in:title "{title}"',
            "--state",
            "all",
            "--json",
            "number,title,state",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return False
    try:
        for issue in json.loads(proc.stdout):
            if issue.get("title") == title:
                return True
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return False


# ----- label fetching ------------------------------------------------


def _fetch_existing_labels() -> set[str] | None:
    proc = subprocess.run(
        ["gh", "label", "list", "--limit", "500", "--json", "name"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        return {label["name"] for label in json.loads(proc.stdout)}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


# ----- starter EPIC --------------------------------------------------


def _file_starter_epic(*, dry_run: bool) -> Action:
    """File the methodology-adoption starter EPIC.

    Per [project-management:DEC-008-pm-and-implementer-roles], EPICs are
    PM-authority filing. The `--with-starter-epic` flag is the PM's
    explicit gesture; the script does not re-prompt.
    """
    title = "[EPIC] Methodology adoption — initial hierarchy"
    body = _STARTER_EPIC_BODY

    # Refuse if an EPIC with the same title already exists.
    proc = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "--search",
            f'in:title "{title}"',
            "--state",
            "all",
            "--json",
            "number,title,state",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        try:
            for issue in json.loads(proc.stdout):
                if issue.get("title") == title:
                    return Action(
                        "starter EPIC",
                        "exists",
                        f"already filed as #{issue['number']} (state: {issue['state']})",
                    )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    if dry_run:
        return Action("starter EPIC", "created", "(dry-run) would file")

    proc = subprocess.run(
        [
            "gh",
            "issue",
            "create",
            "--title",
            title,
            "--body",
            body,
            "--label",
            "type:maintenance",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        url = proc.stdout.strip()
        return Action("starter EPIC", "created", url)
    return Action(
        "starter EPIC",
        "failed",
        f"`gh issue create` exit {proc.returncode}: {proc.stderr.strip()}",
    )


_STARTER_EPIC_BODY = """\
## Outcome

This EPIC scopes the bootstrap work needed to operationalise the
project-management methodology on this project. It exists as a default
parent for Tasks filed during the early adoption phase, before the
project's longer-term EPIC structure has crystallised.

## Success criteria

- [ ] Methodology operational end-to-end on this project (pre-check passes; bootstrap idempotent; project-manager runs)
- [ ] Successor EPICs filed covering this project's actual workstreams (each EPIC scoping a workstream's outcome)
- [ ] Tasks filed during bootstrap migrated under the appropriate successor EPIC once they exist
- [ ] This EPIC closes when its successors have absorbed all in-flight work
"""


# ----- helpers -------------------------------------------------------


def _load_adopter_config(capability_root: Path) -> tuple[dict[str, Any] | None, str]:
    path = capability_root / ADOPTER_CONFIG_PATH
    if not path.is_file():
        return None, (
            f"adopter config missing at {path}. "
            f"See the capability README's 'Adopter setup' section."
        )
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError) as exc:
        return None, f"failed to read/parse {path}: {exc}"
    if not isinstance(data, dict):
        return None, f"{path} top-level is not a mapping"
    return data, ""


def _check_gh_block_and_auth(config: dict[str, Any]) -> str | None:
    """Validate the optional `gh:` block and authenticate against `gh.host` if set.

    Per DEC-023, both `gh.host` and `gh.default_owner` are optional; their
    absence is equivalent to delegating to ambient state. When `gh.host`
    is configured, this function runs `gh auth status -h <host>` and
    fails fast with a `gh auth login -h <host>` remediation hint if the
    host isn't authenticated. Returns None on success, or an error
    message string on failure.
    """
    raw = config.get("gh")
    if raw is None:
        return None  # no override; delegate to ambient state
    if not isinstance(raw, dict):
        return (
            "`gh:` is present in config but not a mapping. "
            "Either remove it or set it to a YAML mapping with optional "
            "`host:` / `default_owner:` fields. See DEC-023."
        )

    allowed = {"host", "default_owner"}
    extras = sorted(set(raw.keys()) - allowed)
    if extras:
        return (
            f"unknown key(s) under `gh:`: {', '.join(extras)}. "
            "DEC-023 allows only `host:` and `default_owner:` under `gh:` at v1."
        )

    for field in ("host", "default_owner"):
        value = raw.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or not value:
            return (
                f"`gh.{field}` must be a non-empty string when set; "
                f"got {value!r}. Either remove the field or set it properly."
            )

    host = raw.get("host")
    if not isinstance(host, str) or not host:
        return None  # no host pinning; nothing further to verify

    proc = subprocess.run(
        ["gh", "auth", "status", "-h", host],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return (
            f"`gh auth status -h {host}` reports no active authentication. "
            f"Run `gh auth login -h {host}` and follow the prompts. "
            "DEC-023 requires the adopter's configured host to be authenticated locally."
        )
    return None


def _resolve_workstream_slugs(
    capability_root: Path, config: dict[str, Any]
) -> list[str]:
    """Read workstream slugs from workstreams.yaml (canonical) or config legacy.

    Implements DEC-018's source-of-truth precedence: dedicated file wins
    if it exists; otherwise fall back to `config.yaml.workstreams`.
    """
    ws_path = capability_root / "project" / "workstreams.yaml"
    if ws_path.is_file():
        try:
            data = YAML(typ="safe").load(ws_path.read_text(encoding="utf-8")) or {}
        except (OSError, YAMLError):
            data = {}
        ws = data.get("workstreams") if isinstance(data, dict) else None
        if isinstance(ws, list):
            return [s for s in ws if isinstance(s, str)]
        if isinstance(ws, dict):
            return [
                s
                for s, attrs in ws.items()
                if isinstance(s, str)
                and (
                    not isinstance(attrs, dict)
                    or attrs.get("status", "active") == "active"
                )
            ]
        return []
    # Legacy fallback.
    legacy = config.get("workstreams") or []
    if isinstance(legacy, list):
        return [s for s in legacy if isinstance(s, str)]
    return []


def _resolve_state_ids(capability_root: Path) -> list[str]:
    """Read lifecycle state IDs from workflow.yaml's `states[].id` list.

    Returns the IDs in declaration order (todo, backlog, in-progress,
    review, done per the canonical schema). Returns an empty list when
    the file is missing or unreadable.
    """
    path = capability_root / "schemas" / "workflow.yaml"
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError):
        return []
    states = data.get("states") or []
    return [
        str(s["id"])
        for s in states
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    ]


def _load_classification(
    capability_root: Path,
) -> tuple[dict[str, Any] | None, str]:
    path = capability_root / "schemas" / "classification.yaml"
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError) as exc:
        return None, f"failed to read {path}: {exc} (capability install may be corrupt)"
    if not isinstance(data, dict):
        return None, f"{path} top-level is not a mapping"
    return data, ""


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


def _print_context_header(repo: str, capability_root: Path) -> None:
    """Print the target repo + capability + config paths before any action.

    Surfaces *which* repo and *which* capability install the script is
    operating on. Defensive against running the script in the wrong
    project tree (multiple checkouts open, wrong cwd, etc.).
    """
    version = _read_capability_version(capability_root)
    config_path = capability_root / ADOPTER_CONFIG_PATH
    print("bootstrap: project-management capability")
    print(f"  target repo: {repo}")
    print(f"  capability:  {capability_root} (v{version})")
    print(f"  config:      {config_path}")
    print()


def _resolve_repo_name_with_owner() -> str:
    """Best-effort `<owner>/<repo>` for the current working tree.

    Returns `<unresolved>` when `gh repo view` fails — the calling code
    surfaces that to the user as part of the header so they can abort
    before any mutation.
    """
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


def _print_report(actions: list[Action]) -> None:
    print()
    print("Result:")
    created = sum(1 for a in actions if a.status == "created")
    exists = sum(1 for a in actions if a.status == "exists")
    skipped = sum(1 for a in actions if a.status == "skipped")
    failed = sum(1 for a in actions if a.status == "failed")
    for a in actions:
        marker = {
            "created": "[created]",
            "exists": "[exists] ",
            "skipped": "[skipped]",
            "failed": "[failed] ",
        }[a.status]
        line = f"  {marker} {a.label}"
        if a.detail:
            line += f"  {a.detail}"
        print(line)
    print()
    print(
        f"Bootstrap complete. Created {created}; skipped {exists} existing; "
        f"{skipped} by mode; {failed} failed."
    )


if __name__ == "__main__":
    sys.exit(main())
