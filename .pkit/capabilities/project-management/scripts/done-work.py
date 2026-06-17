#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — done-work (DEC-026 workflow wrapper).

Transitions Review → Done by squash-merging the PR. Per DEC-026:

    done-work <N> [--bypass "<reason>"]

Approval gate (human-mode three-way OR per DEC-026):
  1. Latest review on the PR is APPROVED, OR
  2. The PR's last non-author comment starts with `Approved`, OR
  3. `--bypass "<reason>"` is supplied (writes an audit comment).

Phase D (DEC-027 mode resolution) wires the per-PR mode lookup that
chooses between this human-mode gate and DEC-028's agent-verdict gate.
v1 ships with the human-mode gate as the default.

Side-effects:
  - `gh pr merge --squash --delete-branch`.
  - `git pull` (main) after the merge.
  - Audit comment "Approved by bypass: <reason>" if --bypass is used
    (stamped + idempotent per DEC-024).
  - Composes over `move-issue.py --to done`.
  - `done-work` does NOT roll back the merge if a downstream step
    fails — merge irreversibility is the architectural constraint per
    DEC-026 failure semantics.

Exit codes:
  0  merged + done
  1  membership refusal / approval gate fails
  2  usage error / gh failure
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from ruamel.yaml import YAML

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
from _lib.gh import gh_get_issue, gh_run, load_adopter_config  # noqa: E402
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
from _lib.review_mode import resolve_mode  # noqa: E402


def _gh_get_issue(issue_number: int, config: dict) -> dict | None:
    """Fetch issue labels for review-mode resolution (DEC-027)."""
    return gh_get_issue(issue_number, config, fields="labels")


BYPASS_AUDIT_STAMP = "<!-- pkit-hook: done-work-bypass -->"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Squash-merge the PR for an issue + transition Review → Done. "
            "Per DEC-026 with the human-mode three-way OR approval gate."
        ),
    )
    parser.add_argument("issue_number", type=int)
    parser.add_argument(
        "--bypass", default=None,
        help=(
            "Bypass the approval gate with a reason. Writes an audit "
            "comment 'Approved by bypass: <reason>' before merging."
        ),
    )
    parser.add_argument(
        "--admin", action="store_true",
        help="Pass --admin to `gh pr merge` (bypass branch protection).",
    )
    parser.add_argument(
        "--capability-root", type=Path, default=None,
        help=f"Default: <repo-root>/.pkit/capabilities/{CAPABILITY_NAME}/.",
    )
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

    branch = _find_issue_branch(args.issue_number)
    if branch is None:
        print(
            f"error: no local branch matching `*/{args.issue_number}-*` found.",
            file=sys.stderr,
        )
        return 2

    pr = _find_pr_for_branch(branch, config)
    if pr is None:
        print(
            f"error: no OPEN PR found for branch {branch!r}. "
            "Run `review-work` first.",
            file=sys.stderr,
        )
        return 2

    pr_number = pr.get("number")
    pr_title = pr.get("title") or ""
    if pr.get("isDraft"):
        print(
            f"error: PR #{pr_number} is still draft. Run `review-work` "
            "to flip it ready before `done-work`.",
            file=sys.stderr,
        )
        return 2

    # Resolve review mode per DEC-027 (issue labels read from the PR view above).
    issue = _gh_get_issue(args.issue_number, config)
    issue_labels = []
    if issue:
        issue_labels = [
            lbl.get("name", "") if isinstance(lbl, dict) else str(lbl)
            for lbl in (issue.get("labels") or [])
        ]
    mode_resolution = resolve_mode(config, issue_labels=issue_labels)
    print(f"  mode: {mode_resolution.mode} ({mode_resolution.source})")

    # Mode-conditional gate per DEC-026 + DEC-027 + DEC-028.
    if args.bypass:
        # --bypass overrides any mode; same audit-comment shape applies.
        gate_result = _GateResult(passed=True, passed_via=f"--bypass: {args.bypass}")
    elif mode_resolution.mode == "human":
        gate_result = _check_approval_gate(pr_number, pr, args.bypass, config)
    else:
        # agent mode — DEC-028 gate.
        gate_result = _check_agent_gate(pr_number, pr, config, mode_resolution.source)

    if not gate_result.passed:
        print(gate_result.refusal_message, file=sys.stderr)
        return 1

    # Residual-placeholder check per DEC-031 — hard-reject at the merge gate.
    # Fetch the PR body (not fetched earlier; _find_pr_for_branch only
    # retrieves number/isDraft/headRefName).
    pr_body = _gh_get_pr_body(pr_number, config)
    if pr_body is not None:
        pr_placeholder_findings = _check_pr_placeholder(
            pr_body, pr_number, capability_root
        )
        hard_reject = [f for f in pr_placeholder_findings if f[0] == "hard-reject"]
        if hard_reject:
            print(
                f"[hard-reject] merge of PR #{pr_number} blocked: "
                "PR body has not been authored (DEC-031).",
                file=sys.stderr,
            )
            for sev, label, detail in hard_reject:
                print(f"  [{sev}] {label}: {detail}", file=sys.stderr)
            print(
                "  → Fill in the required sections of the PR body before merging.",
                file=sys.stderr,
            )
            return 1

    print(f"done-work: #{args.issue_number}")
    print(f"  PR:      #{pr_number}")
    print(f"  gate:    {gate_result.passed_via}")

    if args.dry_run:
        print(f"(dry-run: would post bypass audit (if any), squash-merge --subject {pr_title!r}, pull main, call move-issue.)")
        return 0

    if not args.yes and sys.stdin.isatty():
        reply = input("Squash-merge + close? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.", file=sys.stderr)
            return 0

    # Post bypass audit comment if applicable.
    if args.bypass:
        if not _post_bypass_audit_idempotent(
            args.issue_number, args.bypass, config
        ):
            print(
                "[warn] could not post bypass audit comment; aborting before merge.",
                file=sys.stderr,
            )
            return 2

    # Squash-merge with an explicit subject so the landed commit subject
    # equals the gate-validated PR title regardless of commit count
    # (DEC-013: squash-commit subject = PR title; fixes #33).
    if not _gh_pr_merge(pr_number, pr_title=pr_title, admin=args.admin, config=config):
        return 3

    print(f"  merged PR #{pr_number}")

    # Pull main locally (best-effort; merge irreversibility means we don't
    # roll back on pull failure — the merge is durable).
    _git_pull_main()

    # Compose over move-issue for the state transition + cascade.
    rc = _invoke_move_issue(args.issue_number, "done", args.capability_root)
    if rc != 0:
        print(
            f"[warn] PR merged but move-issue exited {rc}. The merge is "
            "durable; re-run `move-issue --to done` to complete the "
            "lifecycle transition.",
            file=sys.stderr,
        )
        return rc

    print(f"\n[ok] merged + closed #{args.issue_number}")
    return 0


# ---- approval gate ---------------------------------------------------


class _GateResult:
    def __init__(self, passed: bool, passed_via: str = "", refusal_message: str = ""):
        self.passed = passed
        self.passed_via = passed_via
        self.refusal_message = refusal_message


def _check_approval_gate(
    pr_number: int | None, pr: dict, bypass_reason: str | None, config: dict
) -> _GateResult:
    """Human-mode three-way OR: APPROVED review OR `Approved`-prefix
    non-author comment OR --bypass."""
    if bypass_reason:
        if not bypass_reason.strip():
            return _GateResult(
                passed=False,
                refusal_message="error: --bypass requires a non-empty reason.",
            )
        return _GateResult(passed=True, passed_via=f"--bypass: {bypass_reason}")

    if pr_number is None:
        return _GateResult(
            passed=False, refusal_message="error: cannot resolve PR number.",
        )

    # Fetch the PR's reviews + comments + author.
    proc = gh_run(
        ["gh", "pr", "view", str(pr_number),
         "--json", "author,reviews,comments"],
        config, check=False,
    )
    if proc.returncode != 0:
        return _GateResult(
            passed=False,
            refusal_message=(
                f"error: gh pr view failed: {proc.stderr.strip()}"
            ),
        )
    try:
        data = json.loads(proc.stdout)
    except (ValueError, json.JSONDecodeError):
        return _GateResult(
            passed=False, refusal_message="error: gh pr view returned malformed JSON.",
        )
    author_login = (data.get("author") or {}).get("login") or ""

    # Path 1: latest APPROVED review (latest non-COMMENTED state).
    reviews = data.get("reviews") or []
    latest_states = [
        r.get("state") for r in reviews
        if isinstance(r, dict) and r.get("state") in (
            "APPROVED", "CHANGES_REQUESTED", "DISMISSED"
        )
    ]
    if latest_states and latest_states[-1] == "APPROVED":
        return _GateResult(passed=True, passed_via="APPROVED review")

    # Path 2: last non-author comment starts with `Approved` (case-sensitive).
    comments = data.get("comments") or []
    for c in reversed(comments):
        if not isinstance(c, dict):
            continue
        author = (c.get("author") or {}).get("login") or ""
        body = (c.get("body") or "").strip()
        if author and author != author_login and body.startswith("Approved"):
            return _GateResult(
                passed=True, passed_via=f"`Approved` comment from @{author}",
            )

    # Refused.
    return _GateResult(
        passed=False,
        refusal_message=(
            f"[refused] approval gate not satisfied for PR #{pr_number}.\n"
            "          → No APPROVED review present (latest state: "
            f"{latest_states[-1] if latest_states else 'none'}).\n"
            "          → No `Approved`-prefix comment from a non-author.\n"
            "          → No --bypass supplied.\n"
            "          Remediations:\n"
            "            - Request a review and have it approved.\n"
            "            - Have a non-author commenter post a comment "
            "starting with `Approved`.\n"
            "            - Re-run with `--bypass \"<reason>\"`."
        ),
    )


# ---- agent-mode gate (DEC-028) ---------------------------------------


def _check_agent_gate(
    pr_number: int | None, pr: dict, config: dict, mode_source: str,
) -> _GateResult:
    """DEC-028's 7-step gate-checker.

    Resolves which paths are configured (remote / local), inspects PR
    comments for matching verdict lines post-dating the latest commit,
    and applies path-specific identity checks. Gate satisfies if any
    configured path has a fresh APPROVED verdict.
    """
    review = config.get("review") if isinstance(config, dict) else None
    agents_block = review.get("agents") if isinstance(review, dict) else None
    if not isinstance(agents_block, dict):
        agents_block = {}
    remote_registered = agents_block.get("remote_registered") or []
    local_registered = agents_block.get("local_registered") or []

    if not remote_registered and not local_registered:
        return _GateResult(
            passed=False,
            refusal_message=(
                f"[refused] agent-mode approval gate cannot be satisfied — "
                f"no agents configured.\n"
                f"            → resolved mode: agent (source: {mode_source})\n"
                f"            → review.agents.remote_registered: (none)\n"
                f"            → review.agents.local_registered: (none)\n"
                "            Remediation:\n"
                "              a) Configure a registered agent in "
                "`project/config.yaml` under `review.agents.*`.\n"
                "              b) Set `review.mode: human` if you want "
                "human review instead.\n"
                "              c) Merge with `done-work --bypass \"<reason>\"`."
            ),
        )

    if pr_number is None:
        return _GateResult(
            passed=False, refusal_message="error: cannot resolve PR number.",
        )

    # Fetch comments + author + the latest commit timestamp.
    proc = gh_run(
        ["gh", "pr", "view", str(pr_number),
         "--json", "author,comments,commits"],
        config, check=False,
    )
    if proc.returncode != 0:
        return _GateResult(
            passed=False,
            refusal_message=f"error: gh pr view failed: {proc.stderr.strip()}",
        )
    try:
        data = json.loads(proc.stdout)
    except (ValueError, json.JSONDecodeError):
        return _GateResult(
            passed=False, refusal_message="error: gh pr view returned malformed JSON.",
        )
    author_login = (data.get("author") or {}).get("login") or ""
    comments = data.get("comments") or []
    commits = data.get("commits") or []

    # Latest commit timestamp.
    latest_commit_ts = ""
    if commits:
        last = commits[-1]
        if isinstance(last, dict):
            # gh pr view returns commits with committedDate field
            latest_commit_ts = str(last.get("committedDate") or last.get("authoredDate") or "")

    # Per-path satisfaction.
    remote_satisfied = False
    local_satisfied = False
    remote_login = (remote_registered[0].get("github_login") if remote_registered else None)
    local_name = (local_registered[0].get("name") if local_registered else None)

    remote_latest_status: str | None = None  # "APPROVED" | "CHANGES_REQUESTED" | None
    local_latest_status: str | None = None

    for c in comments:
        if not isinstance(c, dict):
            continue
        comment_body = (c.get("body") or "")
        first_line = comment_body.split("\n", 1)[0].strip()
        comment_author = (c.get("author") or {}).get("login") or ""
        comment_ts = str(c.get("createdAt") or "")

        # Freshness: comment must post-date the latest commit.
        if latest_commit_ts and comment_ts <= latest_commit_ts:
            continue

        # Remote path: identity match + author exclusion.
        if remote_login:
            if first_line in ("Reviewer agent: APPROVED", "Reviewer agent: CHANGES_REQUESTED"):
                if comment_author == remote_login and comment_author != author_login:
                    verdict = "APPROVED" if first_line.endswith("APPROVED") else "CHANGES_REQUESTED"
                    remote_latest_status = verdict  # later iterations overwrite (latest wins)

        # Local path: name match in the body line; author-exclusion relaxed.
        if local_name:
            local_approved = f"Reviewer agent (local, {local_name}): APPROVED"
            local_changes = f"Reviewer agent (local, {local_name}): CHANGES_REQUESTED"
            if first_line == local_approved:
                local_latest_status = "APPROVED"
            elif first_line == local_changes:
                local_latest_status = "CHANGES_REQUESTED"

    if remote_login:
        remote_satisfied = remote_latest_status == "APPROVED"
    if local_name:
        local_satisfied = local_latest_status == "APPROVED"

    if (remote_login and remote_satisfied) or (local_name and local_satisfied):
        passed_via_parts: list[str] = []
        if remote_satisfied:
            passed_via_parts.append(f"remote agent (@{remote_login}) APPROVED")
        if local_satisfied:
            passed_via_parts.append(f"local agent ({local_name}) APPROVED")
        return _GateResult(
            passed=True,
            passed_via="; ".join(passed_via_parts),
        )

    remote_summary = (
        f"{remote_login}: {remote_latest_status or 'none'}"
        if remote_login else "(none)"
    )
    local_summary = (
        f"{local_name}: {local_latest_status or 'none'}"
        if local_name else "(none)"
    )
    return _GateResult(
        passed=False,
        refusal_message=(
            f"[refused] agent-mode approval required but no fresh APPROVED verdict.\n"
            f"            → resolved mode: agent (source: {mode_source})\n"
            f"            → remote registered: {remote_summary}\n"
            f"            → local registered:  {local_summary}\n"
            f"            → most recent verdicts (post-dating latest commit):\n"
            f"                  remote: {remote_latest_status or 'none'}\n"
            f"                  local:  {local_latest_status or 'none'}\n"
            "            Remediation:\n"
            "              a) Wait for / trigger the remote agent to post APPROVED.\n"
            "              b) Run `review-pr <N>` to re-invoke local agent(s).\n"
            "              c) Merge with `done-work --bypass \"<reason>\"`.\n"
            "              d) If no agent is configured, set `review.mode: human` "
            "or use --bypass."
        ),
    )


# ---- side-effects ----------------------------------------------------


def _post_bypass_audit_idempotent(
    issue_number: int, reason: str, config: dict
) -> bool:
    body = f"{BYPASS_AUDIT_STAMP}\n\nApproved by bypass: {reason.strip()}"
    proc = gh_run(
        ["gh", "issue", "view", str(issue_number), "--json", "comments"],
        config, check=False,
    )
    if proc.returncode == 0:
        try:
            data = json.loads(proc.stdout)
            for c in data.get("comments", []):
                if BYPASS_AUDIT_STAMP in (c.get("body") or ""):
                    print("  bypass audit comment already present; idempotent skip")
                    return True
        except (ValueError, KeyError, TypeError):
            pass
    proc = gh_run(
        ["gh", "issue", "comment", str(issue_number), "--body", body],
        config, check=False,
    )
    if proc.returncode != 0:
        print(
            f"error: gh issue comment failed: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def _gh_pr_merge(pr_number: int | None, *, pr_title: str, admin: bool, config: dict) -> bool:
    if pr_number is None:
        return False
    # Force --subject to the PR title so the squash-commit subject equals the
    # gate-validated title for both single- and multi-commit PRs.  GitHub's
    # default for a single-commit PR is the commit message, not the title —
    # the --subject flag overrides that (DEC-013; fixes #33).
    cmd = [
        "gh", "pr", "merge", str(pr_number),
        "--squash", "--delete-branch",
        "--subject", pr_title,
    ]
    if admin:
        cmd.append("--admin")
    proc = gh_run(cmd, config, check=False)
    if proc.returncode != 0:
        print(
            f"error: gh pr merge failed: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def _git_pull_main() -> None:
    # Switch to main + pull. Best-effort; failures are warnings.
    proc = subprocess.run(
        ["git", "checkout", "main"], capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        print(
            f"[warn] git checkout main failed: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return
    proc = subprocess.run(
        ["git", "pull", "--ff-only"], capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        print(
            f"[warn] git pull failed: {proc.stderr.strip()}",
            file=sys.stderr,
        )


# ---- PR-placeholder helpers ------------------------------------------

# Body-format descriptor for the PR placeholder check (mirrors the
# issue-side body-format.yaml structure).  ## Test plan is the only
# required checkbox section in PR.md.
_PR_BODY_FORMAT: dict = {
    "bodies": {
        "pr": {
            "required_sections": [
                {
                    "heading": "## Test plan",
                    "has_checkboxes": True,
                    "severity": "[validation-severity:hard-reject]",
                    "purpose": (
                        "Checkboxes describing the testing strategy. "
                        "Omit the section entirely for trivial changes; "
                        "when present, at least one authored item is required."
                    ),
                },
            ],
        },
    },
}


def _gh_get_pr_body(pr_number: int | None, config: dict) -> str | None:
    """Fetch the PR body via `gh pr view`.  Returns None on failure."""
    if pr_number is None:
        return None
    try:
        proc = gh_run(
            ["gh", "pr", "view", str(pr_number), "--json", "body"],
            config,
            check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
        body = data.get("body")
        return str(body) if body is not None else ""
    except (json.JSONDecodeError, KeyError):
        return None


def _check_pr_placeholder(
    pr_body: str,
    pr_number: int | None,
    capability_root: "Path",
) -> list[tuple[str, str, str]]:
    """Run residual-placeholder detection on *pr_body* at PHASE_TRANSITION.

    Returns a list of ``(severity, label, detail)`` tuples — empty when clean.
    """
    return detect_placeholder_residuals(
        body=pr_body,
        structural_type="pr",
        body_format=_PR_BODY_FORMAT,
        capability_root=capability_root,
        phase=PHASE_TRANSITION,
    )


# ---- helpers -----------------------------------------------------------


def _find_issue_branch(issue_number: int) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "branch", "--list", "--format=%(refname:short)"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    pattern = re.compile(rf"^[a-z]+/{issue_number}-[a-z0-9-]+$")
    for line in proc.stdout.splitlines():
        line = line.strip()
        if pattern.match(line):
            return line
    return None


def _find_pr_for_branch(branch: str, config: dict) -> dict | None:
    proc = gh_run(
        ["gh", "pr", "list", "--head", branch, "--state", "open",
         "--json", "number,isDraft,headRefName,title"],
        config, check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        prs = json.loads(proc.stdout)
        for pr in prs:
            if pr.get("headRefName") == branch:
                return pr
    except (ValueError, KeyError):
        pass
    return None


def _invoke_move_issue(
    issue_number: int, target: str, capability_root_arg: Path | None
) -> int:
    cmd = [
        sys.executable, str(_HERE / "move-issue.py"),
        str(issue_number), "--to", target, "--yes",
    ]
    if capability_root_arg is not None:
        cmd += ["--capability-root", str(capability_root_arg)]
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def _read_members(capability_root: Path, yaml_loader: YAML) -> list[dict]:
    path = capability_root / "project" / "members.yaml"
    if not path.is_file():
        return []
    try:
        data = yaml_loader.load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    members = data.get("members") if isinstance(data, dict) else None
    return members if isinstance(members, list) else []


if __name__ == "__main__":
    sys.exit(main())
