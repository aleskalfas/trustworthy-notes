#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — move-issue (verb-subject per DEC-020).

Transitions a GitHub issue through the lifecycle state machine declared
in `workflow.yaml`. The substrate-specific mechanics differ per adopter
config:

  * Board-substrate adopters (`config.has_projects_v2_board == true`):
    the Projects v2 single-select `Status` field carries the state.
    State changes go through `gh project item-edit` (deferred at v1 —
    surfaces as a dry-run guidance message until kit issue #122 lands).
  * Label-fallback adopters: the state lives as a `state:*` label.
    State changes happen via `gh issue edit --add-label state:<new>
    --remove-label state:<old>`.

Cascade per DEC-006 fires upward on forward transitions; the script
walks the parent chain via the issue body's parent-ref line.

Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/move-issue.py 42 --to in-progress

Or via the dispatcher (per COR-021):
  pkit project-management move-issue 42 --to in-progress

Exit codes:
  0  transitioned (or dry-run reported)
  1  membership refusal / authorisation refusal
  2  usage error (unknown state, illegal transition, issue not found)
  3  gh failure
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
from _lib.gh import gh_get_issue, gh_run, load_adopter_config  # noqa: E402
from _lib.hooks import fire_hooks  # noqa: E402
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    check_membership,
    resolve_capability_root,
    resolve_invoker_identity,
)
from _lib.placeholder_detection import (  # noqa: E402
    PHASE_TRANSITION,
    detect_placeholder_residuals,
)


SEVERITY_HARD_REJECT = "hard-reject"
SEVERITY_BYPASSABLE = "bypassable-with-audit"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True)
class Transition:
    """One transition entry from workflow.yaml's `transitions:` list."""

    from_state: str
    to_state: str
    authorisation: str  # "user" | "agent-autonomous"
    severity: str  # "hard-reject" | "bypassable-with-audit" | "warning"
    applies_to: tuple[str, ...]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Move a GitHub issue to a target lifecycle state. Reads "
            "workflow.yaml; refuses unknown transitions; cascades parents "
            "per DEC-006."
        ),
    )
    parser.add_argument(
        "issue_number",
        type=int,
        help="GitHub issue number to transition.",
    )
    parser.add_argument(
        "--to",
        required=True,
        help=(
            "Target state: one of todo, backlog, in-progress, review, done."
        ),
    )
    parser.add_argument(
        "--bypass",
        action="store_true",
        help=(
            "Bypass a bypassable-with-audit gate by posting an audit comment "
            "(per DEC-014). Required for transitions with that severity when "
            "authorisation = user."
        ),
    )
    parser.add_argument(
        "--bypass-reason",
        default=None,
        help="Free-text reason recorded in the audit comment when --bypass is set.",
    )
    parser.add_argument(
        "--no-cascade",
        action="store_true",
        help="Skip the forward-cascade walk on parent issues.",
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
        help="Print the plan; do not invoke gh.",
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

    workflow = _read_yaml(capability_root / "schemas" / "workflow.yaml", yaml_loader)
    issue_types = _read_yaml(
        capability_root / "schemas" / "issue-types.yaml", yaml_loader
    )
    classification = _read_yaml(
        capability_root / "schemas" / "classification.yaml", yaml_loader
    )
    body_format = _read_yaml(
        capability_root / "schemas" / "body-format.yaml", yaml_loader
    )
    config = _read_yaml(capability_root / "project" / "config.yaml", yaml_loader)

    # Validate the target state.
    state_ids = _known_states(workflow)
    if args.to not in state_ids:
        print(
            f"error: unknown target state {args.to!r}. "
            f"Known states: {', '.join(sorted(state_ids))}.",
            file=sys.stderr,
        )
        return 2

    # Fetch current issue + state inference.
    issue = _gh_get_issue(args.issue_number, config)
    if issue is None:
        return 2

    title = str(issue.get("title", ""))
    body = str(issue.get("body") or "")
    labels = [
        lbl.get("name", "") if isinstance(lbl, dict) else str(lbl)
        for lbl in (issue.get("labels") or [])
    ]
    state = str(issue.get("state", "")).lower()
    milestone = issue.get("milestone") or {}

    structural_type = _infer_structural_type(title, issue_types, classification)
    if structural_type is None:
        print(
            f"error: cannot determine structural type from issue title {title!r}; "
            "title does not match any known [Type] prefix.",
            file=sys.stderr,
        )
        return 2

    current_state = _infer_current_state(
        state=state, milestone=milestone, labels=labels
    )

    has_board = bool(config.get("has_projects_v2_board", False))

    # Idempotency check: issue is already at the requested state.
    #
    # Must run BEFORE the transition-table lookup so that callers (e.g.
    # done-work after a squash-merge whose `Closes #N` auto-closes the
    # issue) don't get a spurious "done → done" error. On the label
    # substrate the state:* label may be stale (e.g. state:review
    # lingering after a GitHub-native close), so we reconcile it here
    # rather than returning immediately without touching the label.
    if args.to == current_state:
        print(f"move-issue: #{args.issue_number}")
        print(f"  title:        {title}")
        print(f"  type:         {structural_type}")
        print(f"  current:      {current_state}")
        print(f"  target:       {args.to}")
        print("\n[noop] already at target state; reconciling labels if needed.")
        if not args.dry_run and not has_board:
            plan = _compute_plan(
                issue_number=args.issue_number,
                current_state=current_state,
                target_state=args.to,
                has_board=False,
                labels=labels,
            )
            # Only act when there is a stale label to remove (the add is
            # idempotent but skip the gh round-trip if nothing to fix).
            if plan.remove_label:
                print(f"  reconcile: removing stale label {plan.remove_label!r}")
                if not _gh_apply_state_label(args.issue_number, plan, config):
                    return 3
        return 0

    # Look up the transition.
    transition = _find_transition(
        workflow, current_state, args.to, structural_type
    )
    if transition is None:
        legal_targets = _legal_targets(workflow, current_state, structural_type)
        print(
            f"error: no transition {current_state!r} → {args.to!r} "
            f"declared in workflow.yaml for {structural_type!r}.\n"
            f"  legal targets from {current_state!r}: "
            f"{', '.join(legal_targets) if legal_targets else '<none>'}",
            file=sys.stderr,
        )
        return 2

    # Authorisation gate.
    if transition.authorisation == "user":
        if transition.severity == SEVERITY_HARD_REJECT:
            # User-gated hard-reject: requires --yes from the caller as the
            # explicit authorisation signal (no bypass possible).
            if not args.yes and sys.stdin.isatty():
                pass  # fall through to confirm prompt below
            elif not args.yes:
                print(
                    f"[refused] transition {current_state!r} → {args.to!r} is "
                    f"user-authorised (hard-reject on violation).\n"
                    "          → Pass --yes to confirm the authorisation, "
                    "or re-run from an interactive shell.",
                    file=sys.stderr,
                )
                return 1
        elif transition.severity == SEVERITY_BYPASSABLE:
            # Bypassable: caller must pass --bypass + --bypass-reason or
            # provide TTY confirmation.
            if not args.bypass and not (args.yes or sys.stdin.isatty()):
                print(
                    f"[refused] transition {current_state!r} → {args.to!r} is "
                    "bypassable-with-audit; pass --bypass --bypass-reason '...' "
                    "to record the audit comment, or run from a TTY.",
                    file=sys.stderr,
                )
                return 1

    # Residual-placeholder check per DEC-031 — hard-reject at transition.
    # Run before any mutation so an unauthored body blocks the transition.
    placeholder_findings = detect_placeholder_residuals(
        body=body,
        structural_type=structural_type,
        body_format=body_format,
        capability_root=capability_root,
        phase=PHASE_TRANSITION,
    )
    hard_reject_findings = [f for f in placeholder_findings if f[0] == "hard-reject"]
    if hard_reject_findings:
        print(
            f"[hard-reject] transition {current_state!r} → {args.to!r} blocked: "
            f"issue #{args.issue_number} body has not been authored.",
            file=sys.stderr,
        )
        for sev, label, detail in hard_reject_findings:
            print(f"  [{sev}] {label}: {detail}", file=sys.stderr)
        print(
            "  → Fill in the required sections of the issue body before advancing.",
            file=sys.stderr,
        )
        return 1

    print(f"move-issue: #{args.issue_number}")
    print(f"  title:        {title}")
    print(f"  type:         {structural_type}")
    print(f"  current:      {current_state}")
    print(f"  target:       {args.to}")
    print(f"  authorisation: {transition.authorisation}")
    print(f"  severity:      {transition.severity}")

    if has_board:
        print(
            f"\n[note] board substrate detected (projects_v2_board_id="
            f"{config.get('projects_v2_board_id')}). State lives on the "
            "Projects v2 Status field; bulk gh-project field-set is deferred "
            "(per DEC-019). This invocation will surface the planned move "
            "but not mutate the board field at v1."
        )

    plan = _compute_plan(
        issue_number=args.issue_number,
        current_state=current_state,
        target_state=args.to,
        has_board=has_board,
        labels=labels,
    )
    _print_plan(plan)

    # Cascade preview.
    cascade_targets: list[int] = []
    if not args.no_cascade and _is_forward(workflow, current_state, args.to):
        cascade_targets = _walk_parent_chain(body)
        if cascade_targets:
            print(
                f"\n[cascade] forward cascade will visit parents: "
                f"{', '.join(f'#{n}' for n in cascade_targets)}"
            )

    if args.dry_run:
        print("\n[dry-run] gh would be invoked; nothing written.")
        return 0

    if not args.yes and sys.stdin.isatty():
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    # Optional audit comment on bypassable transitions.
    if (
        transition.authorisation == "user"
        and transition.severity == SEVERITY_BYPASSABLE
        and args.bypass
    ):
        reason = (
            args.bypass_reason
            or "Authorised by caller via --bypass (no reason supplied)."
        )
        if not _gh_comment(
            args.issue_number,
            f"[audit] transition {current_state!r} → {args.to!r} "
            f"bypassed with audit. Reason: {reason}",
        config,
    ):
            return 3

    # Execute.
    if has_board:
        # Deferred: at v1 we only narrate the planned change for board
        # adopters. The label removal/add path is the operational one.
        print(
            "\n[ok] (board adopter) plan recorded; manual board edit may be "
            "required. Label substrate would be: see plan above."
        )
    else:
        ok = _gh_apply_state_label(args.issue_number, plan, config)
        if not ok:
            return 3

    # Forward cascade.
    if cascade_targets and not args.no_cascade:
        for parent_num in cascade_targets:
            ok = _cascade_parent(parent_num, args.to, config)
            if not ok:
                print(
                    f"[warn] cascade on #{parent_num} did not complete cleanly.",
                    file=sys.stderr,
                )

    print(
        f"\n[ok] transitioned #{args.issue_number}: "
        f"{current_state} → {args.to}"
    )

    # Fire after_move_issue hooks per DEC-024.
    fire_hooks(
        "after_move_issue",
        context={
            "issue": {
                "number": args.issue_number,
                "title": str(issue.get("title", "")) if issue else "",
            },
            "transition": {"from": current_state, "to": args.to},
        },
        config=config,
        capability_root=capability_root,
    )

    return 0


# ---- planning helpers ------------------------------------------------


@dataclass(frozen=True)
class Plan:
    issue_number: int
    add_label: str | None
    remove_label: str | None


def _compute_plan(
    *,
    issue_number: int,
    current_state: str,
    target_state: str,
    has_board: bool,
    labels: list[str],
) -> Plan:
    if has_board:
        return Plan(issue_number=issue_number, add_label=None, remove_label=None)
    # Label substrate.
    new_label = f"state:{target_state}"
    old_label = None
    for lbl in labels:
        if lbl.startswith("state:") and lbl != new_label:
            old_label = lbl
            break
    return Plan(
        issue_number=issue_number, add_label=new_label, remove_label=old_label
    )


def _print_plan(plan: Plan) -> None:
    print("\nplan:")
    if plan.add_label:
        print(f"  + add label {plan.add_label!r}")
    if plan.remove_label:
        print(f"  - remove label {plan.remove_label!r}")
    if not plan.add_label and not plan.remove_label:
        print("  · (substrate: board) — no label mutations.")


# ---- workflow-schema helpers ----------------------------------------


def _known_states(workflow: dict) -> set[str]:
    states = workflow.get("states") or []
    out = set()
    for s in states:
        if isinstance(s, dict) and isinstance(s.get("id"), str):
            out.add(s["id"])
    return out


def _find_transition(
    workflow: dict,
    current_state: str,
    target_state: str,
    structural_type: str,
) -> Transition | None:
    """Look up the (from→to) transition in workflow.yaml.

    Falls back to None if the transition isn't listed *or* if the
    transition does not `applies_to` the given structural type.
    """
    transitions = workflow.get("transitions") or []
    type_token = f"[issue-types:{structural_type}]"
    for t in transitions:
        if not isinstance(t, dict):
            continue
        if t.get("from") != current_state or t.get("to") != target_state:
            continue
        applies_to = t.get("applies_to") or []
        if type_token not in applies_to:
            continue
        severity_raw = str(t.get("severity", ""))
        return Transition(
            from_state=str(t.get("from")),
            to_state=str(t.get("to")),
            authorisation=str(t.get("authorisation", "")),
            severity=_severity_from_token(severity_raw),
            applies_to=tuple(applies_to),
        )
    return None


def _legal_targets(
    workflow: dict, current_state: str, structural_type: str
) -> list[str]:
    """Enumerate legal target states for diagnostic output."""
    transitions = workflow.get("transitions") or []
    type_token = f"[issue-types:{structural_type}]"
    out: list[str] = []
    for t in transitions:
        if not isinstance(t, dict):
            continue
        if t.get("from") != current_state:
            continue
        if type_token not in (t.get("applies_to") or []):
            continue
        target = t.get("to")
        if isinstance(target, str):
            out.append(target)
    return out


def _is_forward(workflow: dict, current: str, target: str) -> bool:
    """Forward = increasing position in the canonical state ordering."""
    order = ["todo", "backlog", "in-progress", "review", "done"]
    try:
        return order.index(target) > order.index(current)
    except ValueError:
        return False


def _severity_from_token(token: str) -> str:
    """Parse `[validation-severity:<sev>]` tokens to a string severity."""
    m = re.match(r"\[validation-severity:([a-z-]+)\]", token or "")
    if not m:
        return SEVERITY_WARNING
    return m.group(1)


def _infer_structural_type(
    title: str,
    issue_types: dict,
    classification: dict | None = None,
) -> str | None:
    """Infer the structural type from the title prefix.

    Checks two sources in order:
    1. issue-types.yaml `types[*].title_prefix` — the structural-type
       prefixes ([EPIC], [Feature], [Umbrella], [Task]).
    2. classification.yaml `axes.type.title_prefix_by_value` — the
       kind-driven prefixes ([Bug], [Docs], [Test], [Refactor], [Chore]).
       Kind-prefixes are restricted to the `task` structural type.
    """
    types = issue_types.get("types") or {}
    for type_name, entry in types.items():
        if not isinstance(entry, dict):
            continue
        prefix = entry.get("title_prefix", "")
        case = entry.get("title_case", "title")
        rendered = str(prefix)
        if case == "upper":
            rendered = rendered.upper()
        if title.startswith(f"[{rendered}] "):
            return str(type_name)

    # Check kind-driven prefixes from classification.yaml.
    # These only appear on Task-shape issues per the structural_restriction rule.
    if classification:
        prefix_by_value = (
            classification.get("axes", {})
            .get("type", {})
            .get("title_prefix_by_value", {})
        )
        for _kind_value, kind_prefix in prefix_by_value.items():
            if isinstance(kind_prefix, str) and title.startswith(f"[{kind_prefix}] "):
                return "task"

    return None


def _infer_current_state(
    *, state: str, milestone: dict | None, labels: list[str]
) -> str:
    """Best-effort state inference per workflow.yaml's inferred_from notes."""
    if state == "closed":
        return "done"
    # Look for explicit state:* label first (label-fallback substrate).
    for lbl in labels:
        if lbl.startswith("state:"):
            return lbl.removeprefix("state:")
    # No label → derive from milestone + state.
    if milestone:
        return "backlog"
    return "todo"


def _walk_parent_chain(body: str) -> list[int]:
    """Extract parent issue numbers from the body's first non-blank lines.

    Recognises forms like `EPIC: #42`, `Feature: #99`, `Umbrella: #5`.
    """
    if not body:
        return []
    out: list[int] = []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            if out:
                break
            continue
        m = re.match(r"^([A-Za-z]+):\s+#(\d+)", s)
        if not m:
            break
        out.append(int(m.group(2)))
        break  # parent-ref is one line by convention
    return out


# ---- gh wrappers ----------------------------------------------------


def _gh_get_issue(issue_number: int, config: dict) -> dict | None:
    return gh_get_issue(
        issue_number, config,
        fields="title,body,labels,assignees,state,milestone,url",
    )


def _gh_apply_state_label(issue_number: int, plan: Plan, config: dict) -> bool:
    cmd = ["gh", "issue", "edit", str(issue_number)]
    if plan.add_label:
        cmd.extend(["--add-label", plan.add_label])
    if plan.remove_label:
        cmd.extend(["--remove-label", plan.remove_label])
    if len(cmd) == 4:  # nothing to change
        return True
    try:
        proc = gh_run(cmd, config, check=False)
    except FileNotFoundError:
        return False
    if proc.returncode != 0:
        print(
            f"error: gh issue edit failed (exit {proc.returncode}).\n"
            f"stderr: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def _gh_comment(issue_number: int, body: str, config: dict) -> bool:
    try:
        proc = gh_run(
            ["gh", "issue", "comment", str(issue_number), "--body", body],
            config,
            check=False,
        )
    except FileNotFoundError:
        return False
    if proc.returncode != 0:
        print(
            f"error: gh issue comment failed (exit {proc.returncode}).\n"
            f"stderr: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def _cascade_forward_target(child_target: str) -> str:
    """Return the container-safe forward-cascade target for a given child state.

    The forward cascade is scoped to todo → backlog → in-progress (DEC-006,
    amendment #38). Containers do not enter Review — Review models an open PR
    for a leaf Task; a container has no PR of its own. When a child reaches
    review or done, ancestors are bumped to at most in-progress.
    """
    _FORWARD_CASCADE_CAP = "in-progress"
    order = ["todo", "backlog", "in-progress", "review", "done"]
    try:
        cap_idx = order.index(_FORWARD_CASCADE_CAP)
        child_idx = order.index(child_target)
    except ValueError:
        return child_target
    return order[min(child_idx, cap_idx)]


def _cascade_parent(parent_num: int, target_state: str, config: dict) -> bool:
    """Forward cascade — bump parent if it's behind.

    Conservative implementation: read parent state; if parent is behind
    the capped cascade target, label-edit it forward. Bypasses authorisation
    gates per DEC-006 ("forward cascade is automatic").

    The cascade target is capped at in-progress for containers: Review is a
    leaf/Task state and a container must never auto-enter it (DEC-006,
    amendment #38). A child moving to review or done bumps its ancestors to
    at most in-progress.
    """
    parent = _gh_get_issue(parent_num, config)
    if parent is None:
        return False
    parent_labels = [
        lbl.get("name", "") if isinstance(lbl, dict) else str(lbl)
        for lbl in (parent.get("labels") or [])
    ]
    parent_state = _infer_current_state(
        state=str(parent.get("state", "")).lower(),
        milestone=parent.get("milestone") or {},
        labels=parent_labels,
    )
    # Cap the cascade target: containers top out at in-progress.
    cascade_target = _cascade_forward_target(target_state)
    if not _state_is_behind(parent_state, cascade_target):
        return True  # already at or beyond the capped target.
    plan = _compute_plan(
        issue_number=parent_num,
        current_state=parent_state,
        target_state=cascade_target,
        has_board=False,  # cascade only fires for label substrate
        labels=parent_labels,
    )
    print(
        f"[cascade] bumping parent #{parent_num}: "
        f"{parent_state} → {cascade_target}"
    )
    return _gh_apply_state_label(parent_num, plan, config)


def _state_is_behind(current: str, target: str) -> bool:
    order = ["todo", "backlog", "in-progress", "review", "done"]
    try:
        return order.index(current) < order.index(target)
    except ValueError:
        return False


# ---- I/O helpers ----------------------------------------------------


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
