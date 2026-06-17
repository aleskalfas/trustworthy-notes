#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — review-pr (DEC-028 local-agent invocation).

Invokes every locally-registered review agent against the PR's diff and
posts each verdict as a comment under the developer's gh identity. The
verdict format is per DEC-028:

    Reviewer agent (local, <name>): APPROVED
    Reviewer agent (local, <name>): CHANGES_REQUESTED

followed by free-form commentary the agent produces.

    review-pr <N>

Gates:
  - Membership (closed-mode refuses non-members).
  - PR must exist for the issue's branch.
  - `review.agents.local_registered:` must list at least one agent.

Side-effects:
  - For each locally-registered agent: invoke (via the harness's agent
    runtime), capture verdict + body, post as comment.
  - Idempotent at the PR level: post-dating-latest-commit handles
    staleness automatically per DEC-028. Re-running invokes the agent(s)
    again and posts fresh verdicts; prior verdicts remain in the
    comment history (the gate-checker selects latest-per-agent).

Agent invocation:
  At v1, the kit invokes Claude Code agents via the `claude` CLI when
  available. Adopters with non-Claude-Code harnesses or custom invocation
  flows can subclass / override by editing this script's `_invoke_agent`
  function. Per DEC-028, this capability ships a default `reviewer` agent
  at `.pkit/capabilities/project-management/agents/reviewer.md` that emits
  the local-path verdict format and applies pm conventions; adopters may
  configure `local_registered: name: reviewer` to use it, register their
  own agent under `.claude/agents/`, or replace the default entirely.

Exit codes:
  0  all configured agents invoked + comments posted
  1  membership refusal
  2  usage error / no agents configured / gh failure
  3  one or more agent invocations failed (verdicts not posted)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from ruamel.yaml import YAML

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
from _lib.gh import gh_run, load_adopter_config  # noqa: E402
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    check_membership,
    resolve_capability_root,
    resolve_invoker_identity,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Invoke every locally-registered review agent against the PR's "
            "diff; post each verdict as a comment. Per DEC-028."
        ),
    )
    parser.add_argument("issue_number", type=int)
    parser.add_argument(
        "--capability-root", type=Path, default=None,
        help=f"Default: <repo-root>/.pkit/capabilities/{CAPABILITY_NAME}/.",
    )
    parser.add_argument("--dry-run", action="store_true")
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

    # Resolve registered local agents.
    local_agents = _get_local_registered(config)
    if not local_agents:
        print(
            "error: no agents configured in `review.agents.local_registered:`. "
            "Add an entry pointing at a deployed agent in .claude/agents/.",
            file=sys.stderr,
        )
        return 2

    # Find the issue's branch + PR.
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
    print(f"review-pr: #{args.issue_number}")
    print(f"  PR:     #{pr_number}")
    print(f"  agents: {', '.join(a['name'] for a in local_agents)}")

    # Resolve repo-root for the agent invocation (walk up from capability_root).
    repo_root = capability_root.parent.parent.parent

    # For each agent, invoke and post verdict.
    failures = 0
    for agent_entry in local_agents:
        name = agent_entry["name"]
        agent_file = repo_root / ".claude" / "agents" / f"{name}.md"
        if not agent_file.is_file():
            print(
                f"  [{name}] error: agent file not found at {agent_file}",
                file=sys.stderr,
            )
            failures += 1
            continue

        if args.dry_run:
            print(f"  [{name}] (dry-run) would invoke against PR #{pr_number}")
            continue

        verdict, body = _invoke_agent(name, pr_number, config)
        if verdict is None:
            print(f"  [{name}] invocation failed; no verdict to post.", file=sys.stderr)
            failures += 1
            continue

        comment = _format_verdict_comment(name, verdict, body)
        if not _post_comment(pr_number, comment, config):
            print(f"  [{name}] could not post verdict comment.", file=sys.stderr)
            failures += 1
            continue

        print(f"  [{name}] posted {verdict}")

    if failures > 0:
        return 3
    return 0


# ---- agent invocation ------------------------------------------------


def _invoke_agent(
    name: str, pr_number: int | None, config: dict,
) -> tuple[str | None, str]:
    """Invoke a Claude Code agent against the PR diff.

    Returns (verdict, body) — verdict is "APPROVED" or "CHANGES_REQUESTED"
    or None on failure. Body is the agent's freeform commentary.

    At v1 this uses the `claude` CLI when available. Adopters with
    custom harnesses or invocation patterns override by editing this
    function. Per DEC-028's Implications, the methodology specifies
    the verdict-comment contract; the agent implementations are
    adopter / kit-side.
    """
    claude_bin = shutil.which("claude")
    if claude_bin is None:
        print(
            "  [warn] `claude` CLI not on PATH. The kit's review-pr.py at v1 "
            "invokes Claude Code agents via the `claude` CLI; for adopters "
            "with other harnesses, edit `_invoke_agent` in review-pr.py to "
            "call your invocation flow.",
            file=sys.stderr,
        )
        return None, ""

    # Build the prompt — the agent receives the PR diff + a clear
    # instruction to return one of the two verdicts as the first line.
    prompt = (
        f"Review the diff of PR #{pr_number} in this repository. "
        f"Apply your usual review criteria. Output your verdict on the "
        f"VERY FIRST LINE in one of these exact forms:\n\n"
        f"  Reviewer agent (local, {name}): APPROVED\n"
        f"  Reviewer agent (local, {name}): CHANGES_REQUESTED\n\n"
        "Then add any commentary, findings, or rationale below."
    )

    try:
        proc = subprocess.run(
            [claude_bin, "-p", prompt, "--agent", name],
            capture_output=True, text=True, check=False, timeout=300,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"  [{name}] invocation error: {exc}", file=sys.stderr)
        return None, ""

    if proc.returncode != 0:
        print(
            f"  [{name}] agent exited {proc.returncode}: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return None, ""

    # Parse the first line for the verdict.
    output = proc.stdout
    first_line = output.split("\n", 1)[0].strip()
    expected_approved = f"Reviewer agent (local, {name}): APPROVED"
    expected_changes = f"Reviewer agent (local, {name}): CHANGES_REQUESTED"
    if first_line == expected_approved:
        return "APPROVED", output.split("\n", 1)[1] if "\n" in output else ""
    if first_line == expected_changes:
        return "CHANGES_REQUESTED", output.split("\n", 1)[1] if "\n" in output else ""
    print(
        f"  [{name}] agent output did not start with expected verdict line. "
        f"Got: {first_line!r}",
        file=sys.stderr,
    )
    return None, ""


def _format_verdict_comment(name: str, verdict: str, body: str) -> str:
    """Compose the verdict comment in DEC-028's local-path format."""
    first_line = f"Reviewer agent (local, {name}): {verdict}"
    if body.strip():
        return f"{first_line}\n\n{body.strip()}"
    return first_line


# ---- helpers ---------------------------------------------------------


def _get_local_registered(config: dict) -> list[dict]:
    review = config.get("review") if isinstance(config, dict) else None
    agents = review.get("agents") if isinstance(review, dict) else None
    if not isinstance(agents, dict):
        return []
    local = agents.get("local_registered") or []
    return [e for e in local if isinstance(e, dict) and e.get("name")]


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
         "--json", "number,isDraft,headRefName"],
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


def _post_comment(pr_number: int | None, body: str, config: dict) -> bool:
    if pr_number is None:
        return False
    proc = gh_run(
        ["gh", "pr", "comment", str(pr_number), "--body", body],
        config, check=False,
    )
    if proc.returncode != 0:
        print(f"error: gh pr comment failed: {proc.stderr.strip()}", file=sys.stderr)
        return False
    return True


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
