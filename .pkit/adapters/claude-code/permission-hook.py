#!/usr/bin/env python3
"""Claude Code PreToolUse permission hook (per COR-028 / ADR-002 / ADR-003).

A propagated adapter script registered by `pkit permissions enable` via the
top-level `hooks` key in `.claude/settings.json`. On every matched tool call
Claude Code pipes a PreToolUse payload to this script's stdin; the script
decides via the shared, harness-neutral decision core
(`.pkit/permissions/decide.py`) and prints a `permissionDecision`, or abstains.

Runtime: bare system `python3` — NO uv, no PEP-723 metadata, no third-party
deps at startup. Running under bare python3 is required so the hook can start
inside macOS Seatbelt, where uv panics on the fixed SCDynamicStore denial
(ADR-014). The shared `decide.py` loader handles ruamel.yaml when available,
falling back to a stdlib-only YAML-subset parser when not (ADR-014 pt.1).

Same-code invariant (ADR-002): this hook and the `pkit permissions` CLI must
decide identically. The mechanism is ADR-003's code-home + dependency direction
— both import the *same* in-tree `decide.py` and build the model via the *same*
`load_model` / `load_yaml`, so they can never diverge. The stdlib fallback lives
in the SHARED loader (decide.py), not here, for exactly this reason.

Fail-OPEN (ADR-002): any *decision* fault — unreadable model, malformed payload
— yields a silent abstain (exit 0, no stdout), never a silent block. The
non-negotiable guardrail denies are double-locked in the harness's fail-closed
native `settings.json` denies, so failing open here can never bypass them.

Enforcement-runtime faults (hook can't start at all) are a DISTINCT fault class
(ADR-002 amendment): they surface loudly via the startup self-check wired into
`pkit permissions enable` and `pkit permissions sandbox enable` — not via this
hook itself, which never runs when its runtime is dead.

Set PKIT_PERMISSIONS_DEBUG=1 to surface decision fault reasons on stderr
(otherwise a broken config degrades to a silent no-op).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _debug(msg: str) -> None:
    if os.environ.get("PKIT_PERMISSIONS_DEBUG"):
        print(f"pkit-permissions-hook: {msg}", file=sys.stderr)


def _target_root() -> Path:
    # Prefer the harness's own contract for the project location; fall back to
    # this script's known position at <root>/.pkit/adapters/claude-code/.
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:  # malformed/empty stdin → fail open
        _debug(f"unreadable payload → abstain: {exc!r}")
        return 0

    try:
        root = _target_root()
        sys.path.insert(0, str(root / ".pkit" / "permissions"))
        import decide  # the shared decision core

        catalog = decide.load_catalog(str(root))
        model = decide.load_model(str(root), catalog)
        decision, reason = decide.hook_decide(model, catalog, payload, project_root=str(root))
    except Exception as exc:  # any load/decision fault → fail open
        _debug(f"decision fault → abstain: {exc!r}")
        return 0

    if decision in ("allow", "deny"):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": decision,
                        "permissionDecisionReason": reason,
                    }
                }
            )
        )
    # abstain → exit 0 with no stdout: defer to the harness's normal flow.
    return 0


if __name__ == "__main__":
    sys.exit(main())
