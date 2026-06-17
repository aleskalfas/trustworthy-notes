"""Realized-state projection (per COR-028 / ADR-002 / ADR-003 / #249).

The counterpart of `decide.py`: where `decide()` answers "should this request be
allowed?", `project()` answers "what native harness config does this model
*expect*?". `apply` writes that expected config; `diff` compares it to live —
both call this one function, so they can never disagree (ADR-002 same-code).

Harness-neutral and propagated like `decide.py` (ADR-003): imports neither
`src/project_kit` nor any adapter. "Neutral" here means *propagated, no
src/adapter import* — the emitted patterns are Claude-Code-shaped because the
catalog recognizers and tool names are; a second harness would render its own.

Scope (per the #249 critic pass):
  - Projects the **allow** side only. Guardrail *denies* are owned canonically by
    the adapter's core settings + the hook's catalog-derived model denies (the
    ADR-002 double-lock). Re-deriving the flag/subcommand recognizers as
    positional settings prefixes would *weaken* them, so denies are not projected.
  - Only `cmd`-only bash recognizers render to a faithful `Bash(<cmd>:*)`. A
    recognizer using `subcommand`/`flag_any`/`pattern` cannot be faithfully
    expressed as a positional settings prefix → `unprojectable`.
  - Settings are session-wide: only `subject: all` *bash* grants project to
    settings; per-agent / `operator` bash is hook-enforced (`runtime`). *Tool*
    privileges for `all`/`operator` do project to settings (session-wide tool
    allows); per-agent tool grants are `runtime` (frontmatter projection cut).
  - Scoped grants are confinement — sandbox-delegated (ADR-004), not settings →
    `unprojectable`.
  - Per-agent tool-gating is frontmatter-owned and has no consumer yet (#249
    cut it); per-agent tool grants are reported as `runtime`.
"""
from __future__ import annotations

import re
from typing import Any

# Deliberately a second copy of decide.py's token regex (not an import): keeps
# project() free of decide.py's PyYAML-touching loaders. A COR-019 token-format
# change has two edit sites here and in decide.py — kept in sync intentionally.
_TOKEN = re.compile(r"^\[privilege-catalog:([a-z][a-z0-9-]*)\]$")


def _bare_ids(value: Any) -> list[str]:
    vals = value if isinstance(value, list) else [value]
    out: list[str] = []
    for v in vals:
        m = _TOKEN.match(v) if isinstance(v, str) else None
        out.append(m.group(1) if m else v)
    return out


def project(model: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    """Render a model into its expected native config + the residual buckets.

    Returns {
      "settings":      {"allow": [pattern...], "deny": []},  # session-wide native
      "runtime":       [{subject, privilege, reason}...],    # hook-enforced, not native
      "unprojectable": [{subject, privilege, reason}...],    # no native layer expresses it
    }
    `settings.deny` is always empty by design (see module docstring).
    """
    privileges = catalog.get("privileges", {})
    allow: list[str] = []
    runtime: list[dict[str, str]] = []
    unprojectable: list[dict[str, str]] = []

    def note(bucket: list, subject: str, pid: str, reason: str) -> None:
        bucket.append({"subject": subject, "privilege": pid, "reason": reason})

    for g in model.get("grants", []):
        if g.get("effect", "allow") != "allow":
            continue  # denies are canonically owned (double-lock), not projected
        subject = g.get("subject", "?")
        scoped = bool(g.get("scope"))
        for pid in _bare_ids(g.get("privilege")):
            spec = privileges.get(pid, {})
            recog = spec.get("recognize", {})
            if scoped:
                note(unprojectable, subject, pid,
                     "scoped grant — confinement is sandbox-delegated (ADR-004), "
                     "not expressible in session-wide settings")
                continue
            tools = recog.get("tool", []) or []
            bash = recog.get("bash", []) or []
            if tools:
                if subject in ("all", "operator"):
                    allow.extend(tools)  # session-wide tool allow
                else:
                    note(runtime, subject, pid,
                         "per-agent tool grant — enforced live by the hook "
                         "(type:tool); native frontmatter projection deferred (#249)")
            if bash:
                if subject != "all":
                    note(runtime, subject, pid,
                         "per-agent/operator command rules can't be expressed "
                         "session-wide; hook-enforced (ADR-004)")
                else:
                    for rule in bash:
                        if set(rule) - {"cmd"}:  # subcommand / flag_any / pattern
                            note(unprojectable, subject, pid,
                                 "recognizer uses subcommand/flag_any/pattern — not "
                                 "faithfully renderable as a positional settings prefix")
                        elif "cmd" in rule:
                            allow.append(f"Bash({rule['cmd']}:*)")

    return {
        "settings": {"allow": sorted(set(allow)), "deny": []},
        "runtime": runtime,
        "unprojectable": unprojectable,
    }
