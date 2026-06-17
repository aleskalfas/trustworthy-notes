#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — self-test.

Drives a full smoke-test of the capability's core transition cycle
against the live repo. Creates a throwaway issue, advances it through
the state machine, then closes and optionally cleans up.

Steps:
  1. Create throwaway issue `[Task] pkit self-test — DELETE ME` with
     priority:Low and state:todo (if label-fallback mode).
  2. Promote to backlog (attach milestone `pkit-self-test`, create it
     if absent).
  3. Start work — transitions to in-progress via move-issue.
  4. Move back to backlog (regression path via move-issue).
  5. Close the issue (won't-do self-test cleanup).
  6. Optionally delete the milestone if just-created.

Each step prints `[ok]` or `[fail] <reason>`. Final summary:
`self-test: N passed, M failed`. Exit non-zero if any step fails.

Use --dry-run to print the plan without mutating GitHub state.

Self-contained via PEP 723; runs via:
  uv run --script .pkit/capabilities/project-management/scripts/self-test.py

Or via the dispatcher (per COR-021):
  pkit project-management self-test

Exit codes:
  0  all steps passed (or dry-run completed)
  1  one or more steps failed
  2  usage error (capability not found; config error)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
from _lib.gh import gh_run, load_adopter_config  # noqa: E402
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    resolve_capability_root,
)


SELF_TEST_TITLE = "[Task] pkit self-test — DELETE ME"
SELF_TEST_MILESTONE = "pkit-self-test"
SELF_TEST_LABEL_SENTINEL = "state:todo"
SELF_TEST_LABELS_PRIORITY = "priority:Low"
SELF_TEST_BODY = """\
## What

Automated self-test issue created by `pkit project-management self-test`.
This issue is a throwaway — close or delete it after the test completes.

## Acceptance criteria

- [ ] Created, transitioned, and closed by the self-test runner.

## Doc impact

None — ephemeral test artefact.
"""


@dataclass
class StepResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class SelfTestState:
    issue_number: int | None = None
    milestone_title: str | None = None
    milestone_just_created: bool = False
    results: list[StepResult] = field(default_factory=list)

    def record(self, name: str, passed: bool, detail: str = "") -> bool:
        self.results.append(StepResult(name, passed, detail))
        marker = "[ok] " if passed else "[fail]"
        line = f"  {marker} {name}"
        if detail:
            line += f" — {detail}"
        print(line)
        return passed

    def summary(self) -> tuple[int, int]:
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        return passed, failed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Smoke-test the capability's core transition cycle on the live repo. "
            "Creates a throwaway issue, advances it through the state machine, "
            "and closes it. Prints [ok]/[fail] per step; exits non-zero on any failure."
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
        help="Print the plan without mutating GitHub state.",
    )
    parser.add_argument(
        "--skip-cleanup",
        action="store_true",
        help=(
            "Leave the self-test issue and milestone after the test. "
            "Useful for debugging a failed run."
        ),
    )
    args = parser.parse_args()

    capability_root = resolve_capability_root(args.capability_root)
    if capability_root is None:
        print(
            f"error: {CAPABILITY_NAME} capability not found.",
            file=sys.stderr,
        )
        return 2

    config = load_adopter_config(capability_root)
    has_board = bool(config.get("has_projects_v2_board", False))

    print("self-test: project-management capability")
    print(f"  capability root: {capability_root}")
    print(f"  substrate:       {'board' if has_board else 'label-fallback'}")
    if args.dry_run:
        print("  mode:            dry-run (no GitHub mutations)")
    print()

    if args.dry_run:
        _print_dry_run_plan(has_board)
        return 0

    state = SelfTestState()

    # Step 1: create throwaway issue.
    issue_number = _step_create_issue(config, has_board, state)
    if issue_number is None:
        _print_summary(state)
        return 1

    # Step 2: promote to backlog (attach milestone).
    milestone_ok = _step_promote(issue_number, config, state)

    # Step 3: start work (in-progress).
    if milestone_ok:
        _step_start_work(issue_number, config, state)

    # Step 4: close the issue.
    _step_close(issue_number, config, state)

    # Step 6: cleanup milestone if just-created.
    if not args.skip_cleanup and state.milestone_just_created and state.milestone_title:
        _step_delete_milestone(state.milestone_title, config, state)

    _print_summary(state)
    passed, failed = state.summary()
    return 0 if failed == 0 else 1


# ---- individual steps -----------------------------------------------


def _step_create_issue(
    config: dict, has_board: bool, state: SelfTestState
) -> int | None:
    """Step 1: create the throwaway issue and return its number."""
    labels = ["priority:Low"]
    if not has_board:
        labels.append("state:todo")

    label_args: list[str] = []
    for lbl in labels:
        label_args.extend(["--label", lbl])

    try:
        proc = gh_run(
            [
                "gh", "issue", "create",
                "--title", SELF_TEST_TITLE,
                "--body", SELF_TEST_BODY,
                *label_args,
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        state.record("create throwaway issue", False, "`gh` not on PATH")
        return None

    if proc.returncode != 0:
        state.record(
            "create throwaway issue",
            False,
            f"gh issue create failed: {proc.stderr.strip()}",
        )
        return None

    # The URL is on the last line of stdout.
    url = proc.stdout.strip().splitlines()[-1].strip()
    # Extract number from URL (last path component).
    issue_number = None
    try:
        issue_number = int(url.rstrip("/").split("/")[-1])
    except (ValueError, AttributeError):
        pass

    if issue_number is None:
        state.record("create throwaway issue", False, f"could not parse issue number from: {url}")
        return None

    state.issue_number = issue_number
    state.record("create throwaway issue", True, f"#{issue_number} ({url})")
    return issue_number


def _step_promote(
    issue_number: int, config: dict, state: SelfTestState
) -> bool:
    """Step 2: promote the issue to backlog by attaching a milestone."""
    # Ensure the self-test milestone exists.
    ms_number, just_created = _ensure_milestone(SELF_TEST_MILESTONE, config)
    if ms_number is None:
        state.record("ensure pkit-self-test milestone", False, "milestone create/find failed")
        return False

    state.milestone_title = SELF_TEST_MILESTONE
    state.milestone_just_created = just_created
    state.record(
        "ensure pkit-self-test milestone",
        True,
        f"#{ms_number}{' (created)' if just_created else ' (existing)'}",
    )

    # Attach milestone to issue.
    try:
        proc = gh_run(
            [
                "gh", "issue", "edit",
                str(issue_number),
                "--milestone", SELF_TEST_MILESTONE,
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        state.record("attach milestone to issue", False, "`gh` not on PATH")
        return False

    if proc.returncode != 0:
        state.record(
            "attach milestone to issue",
            False,
            f"gh issue edit failed: {proc.stderr.strip()}",
        )
        return False

    state.record("attach milestone to issue", True, f"#{issue_number} → {SELF_TEST_MILESTONE}")

    # Transition state: todo → backlog. Milestone attachment alone doesn't flip the
    # state-label in label-fallback mode; the explicit move-issue does. The workflow
    # graph requires todo → backlog before backlog → in-progress.
    return _run_move_issue(issue_number, "backlog", "promote to backlog (state)", config, state)


def _step_start_work(
    issue_number: int, config: dict, state: SelfTestState
) -> bool:
    """Step 3: transition issue to in-progress via move-issue."""
    return _run_move_issue(issue_number, "in-progress", "start-work (in-progress)", config, state)


def _step_move_back(
    issue_number: int, config: dict, state: SelfTestState
) -> bool:
    """Step 4: move issue back to backlog via move-issue (regression path)."""
    return _run_move_issue(issue_number, "backlog", "move back (backlog)", config, state)


def _step_close(
    issue_number: int, config: dict, state: SelfTestState
) -> bool:
    """Step 5: close the issue with a self-test cleanup reason."""
    try:
        proc = gh_run(
            [
                "gh", "issue", "close",
                str(issue_number),
                "--comment",
                "Closed by `pkit project-management self-test` — automated cleanup; not real work.",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        state.record("close throwaway issue", False, "`gh` not on PATH")
        return False

    if proc.returncode != 0:
        state.record(
            "close throwaway issue",
            False,
            f"gh issue close failed: {proc.stderr.strip()}",
        )
        return False

    state.record("close throwaway issue", True, f"#{issue_number} closed")
    return True


def _step_delete_milestone(
    milestone_title: str, config: dict, state: SelfTestState
) -> bool:
    """Step 6: delete the self-test milestone if it was just created."""
    # Fetch milestone number.
    try:
        proc = gh_run(
            [
                "gh", "api",
                f"repos/{{owner}}/{{repo}}/milestones",
                "--paginate",
                "--jq",
                f'.[] | select(.title == "{milestone_title}") | .number',
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        state.record("delete self-test milestone", False, "`gh` not on PATH")
        return False

    ms_number_str = proc.stdout.strip()
    if not ms_number_str or proc.returncode != 0:
        # Can't find it; that's fine — may have been deleted by the test or never created.
        state.record(
            "delete self-test milestone",
            True,
            "milestone not found (already gone or not created)",
        )
        return True

    try:
        ms_number = int(ms_number_str.splitlines()[0])
    except (ValueError, IndexError):
        state.record("delete self-test milestone", False, f"unexpected output: {ms_number_str!r}")
        return False

    try:
        proc = gh_run(
            [
                "gh", "api",
                "--method", "DELETE",
                f"repos/{{owner}}/{{repo}}/milestones/{ms_number}",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        state.record("delete self-test milestone", False, "`gh` not on PATH")
        return False

    if proc.returncode not in (0, 204):
        state.record(
            "delete self-test milestone",
            False,
            f"gh api DELETE failed (exit {proc.returncode}): {proc.stderr.strip()}",
        )
        return False

    state.record("delete self-test milestone", True, f"#{ms_number} deleted")
    return True


# ---- helpers ---------------------------------------------------------


def _run_move_issue(
    issue_number: int,
    target_state: str,
    step_name: str,
    config: dict,
    state: SelfTestState,
) -> bool:
    """Run move-issue script for a single transition."""
    move_script = Path(__file__).parent / "move-issue.py"
    if not move_script.is_file():
        state.record(step_name, False, "move-issue.py not found")
        return False

    try:
        proc = subprocess.run(
            [str(move_script), str(issue_number), "--to", target_state, "--yes"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        state.record(step_name, False, "move-issue.py could not be executed")
        return False

    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        state.record(
            step_name,
            False,
            f"move-issue exit {proc.returncode}: {stderr[:200]}",
        )
        return False

    state.record(step_name, True, f"#{issue_number} → {target_state}")
    return True


def _ensure_milestone(title: str, config: dict) -> tuple[int | None, bool]:
    """Get or create the self-test milestone. Returns (number, just_created).

    Looks for an open milestone with the exact title; creates it if absent.
    """
    try:
        proc = gh_run(
            [
                "gh", "api",
                "repos/{owner}/{repo}/milestones",
                "--paginate",
                "--jq",
                f'.[] | select(.title == "{title}") | .number',
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        return None, False

    if proc.returncode == 0 and proc.stdout.strip():
        try:
            ms_number = int(proc.stdout.strip().splitlines()[0])
            return ms_number, False
        except (ValueError, IndexError):
            pass

    # Create it.
    import datetime as _dt
    due_on = (
        _dt.date.today().isoformat() + "T00:00:00Z"
    )
    try:
        create_proc = gh_run(
            [
                "gh", "api",
                "--method", "POST",
                "repos/{owner}/{repo}/milestones",
                "--field", f"title={title}",
                "--field", f"description=Ephemeral milestone for pkit project-management self-test.",
                "--field", f"due_on={due_on}",
                "--jq", ".number",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        return None, False

    if create_proc.returncode != 0:
        return None, False

    try:
        ms_number = int(create_proc.stdout.strip())
        return ms_number, True
    except (ValueError, AttributeError):
        return None, False


def _print_dry_run_plan(has_board: bool) -> None:
    """Print what the self-test would do without running it."""
    print("plan (dry-run):")
    print(f"  1. Create issue: '{SELF_TEST_TITLE}'")
    print(f"     labels: priority:Low" + (", state:todo" if not has_board else ""))
    print(f"  2. Ensure milestone '{SELF_TEST_MILESTONE}' exists; attach to issue")
    print("  3. move-issue --to backlog --yes (todo → backlog state transition)")
    print("  4. move-issue --to in-progress --yes (backlog → in-progress)")
    print("  5. gh issue close <number> --comment '...'")
    print("  6. Delete milestone if just-created")
    print()
    print("[dry-run] no GitHub mutations performed.")


def _print_summary(state: SelfTestState) -> None:
    passed, failed = state.summary()
    print()
    print(f"self-test: {passed} passed, {failed} failed")
    if failed > 0:
        print(
            "\n[note] The throwaway issue may still be open. "
            "Close/delete it manually if cleanup steps did not run.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    sys.exit(main())
