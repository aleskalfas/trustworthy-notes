"""Permission decision core (per COR-028 / ADR-003).

Harness-neutral, propagated, standalone module — imported by BOTH the
claude-code PreToolUse hook (which runs in the adopter tree at decision
time, where the global `pkit` is not importable) AND the `pkit permissions`
CLI. ADR-002's same-code invariant requires they decide identically, so the
logic lives here once and both call it.

Dependency direction (ADR-003): CLI and hook import this; this imports neither
`src/project_kit` nor any adapter. Recognizers arrive as catalog *data*
(privilege-catalog.yaml), never as adapter code.

Pure logic operates on plain dicts (a loaded grant model + privilege catalog);
the loaders are thin helpers. No third-party deps beyond PyYAML for the loaders
(the pure `decide()` path needs none).
"""
from __future__ import annotations

import fnmatch
import re
from typing import Any

# A grant's privilege value is the COR-019 token `[privilege-catalog:<id>]`
# (or a list of them); strip to the bare id for matching against the catalog.
_TOKEN = re.compile(r"^\[privilege-catalog:([a-z][a-z0-9-]*)\]$")
_SEP = re.compile(r"\s*(?:&&|\|\||\||;)\s*")
_ENVVAR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


# ---- command segmentation + recognizer matcher ----------------------------

def segments(command: str) -> list[list[str]]:
    """Split a compound command into segments, each tokenized, with env-var
    prefixes (and a leading `export`) stripped. Fixes the `export X=1 && gh …`
    false-prompt that the flat settings matcher couldn't catch."""
    out: list[list[str]] = []
    for raw in _SEP.split(command.strip()):
        toks = raw.split()
        while toks and (toks[0] == "export" or _ENVVAR.match(toks[0])):
            toks = toks[1:]
        if toks:
            out.append(toks)
    return out


def _matches_bash(rule: dict[str, Any], toks: list[str]) -> bool:
    if "pattern" in rule:
        if re.search(rule["pattern"], " ".join(toks)):
            return True
        if "cmd" not in rule:
            return False
    if "cmd" in rule:
        if not toks or toks[0] != rule["cmd"]:
            return False
        if "subcommand" in rule:
            rest = [t for t in toks[1:] if not t.startswith("-")]
            if not rest or rest[0] not in rule["subcommand"]:
                return False
        if "flag_any" in rule:
            if not any(f in toks for f in rule["flag_any"]):
                return False
        return True
    return False


def recognized_privileges(catalog: dict[str, Any], request: dict[str, Any]) -> set[str]:
    """Which privilege ids does this request match?"""
    privileges = catalog.get("privileges", {})
    hits: set[str] = set()
    if request.get("type") == "tool":
        tool = request.get("tool")
        for name, spec in privileges.items():
            if tool in spec.get("recognize", {}).get("tool", []):
                hits.add(name)
    elif request.get("type") == "bash":
        segs = segments(request.get("command", ""))
        for name, spec in privileges.items():
            for rule in spec.get("recognize", {}).get("bash", []):
                if any(_matches_bash(rule, toks) for toks in segs):
                    hits.add(name)
                    break
    return hits


# ---- subjects, scope, decision ---------------------------------------------

def _privilege_ids(value: Any) -> set[str]:
    """Normalise a grant's `privilege` (token or list of tokens) to bare ids."""
    vals = value if isinstance(value, list) else [value]
    out: set[str] = set()
    for v in vals:
        m = _TOKEN.match(v) if isinstance(v, str) else None
        out.add(m.group(1) if m else v)
    return out


def _extract_host(url: str) -> str:
    """Extract the hostname from a URL string.  Returns an empty string if the
    URL cannot be parsed (no scheme, malformed, etc.) — a host that can never
    match a well-formed glob, so the grant is denied rather than silently passed.

    stdlib-only: uses urllib.parse which ships with every Python ≥ 3.6 and is
    safe inside macOS Seatbelt (ADR-014).
    """
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        return parsed.hostname or ""
    except Exception:
        return ""


def _scope_ok(
    scope: list[str] | None,
    cwd: str,
    *,
    scope_type: str | None = None,
    url: str | None = None,
) -> tuple[bool, str | None]:
    """Check whether a grant's scope constraint is satisfied.

    Returns (ok, rejection_reason_or_None).

    For ``directory``-scoped privileges (default for absent ``scope_type``):
      the grant's scope globs are matched against ``cwd`` via fnmatch.

    For ``domain``-scoped privileges (``scope_type="domain"``):
      positive allow-list semantics — the grant's scope globs are matched
      against the hostname extracted from ``url``.  Only matching hosts are
      allowed; non-matching hosts are blocked.

      Deny/negation scopes (any glob starting with ``!``) are explicitly
      unsupported and rejected with a clear reason rather than silently
      accepted.  Rationale: a tool-layer denylist is a false boundary — an
      agent's raw ``bash curl`` bypasses it at the agent-blind sandbox layer
      (ADR-004 §61).  Only positive allow-lists are honest at this layer.

    When ``scope`` is absent or empty the grant is unconstrained (anywhere).
    """
    if not scope:
        return True, None

    # Deny/negation scopes are explicitly unsupported for domain privileges.
    # Check upfront so the error message is clear regardless of scope_type.
    negation_globs = [pat for pat in scope if pat.startswith("!")]
    if negation_globs:
        return False, (
            f"deny/negation scopes are unsupported for domain-scoped privileges "
            f"({negation_globs!r}): a tool-layer denylist is a false boundary "
            f"(ADR-004 §61); use positive allow-list globs only"
        )

    if scope_type == "domain":
        host = _extract_host(url or "")
        if not host:
            return False, (
                f"domain-scope check failed: could not extract a hostname from "
                f"request URL {url!r}"
            )
        matched = any(fnmatch.fnmatch(host, pat) for pat in scope)
        if matched:
            return True, None
        return False, (
            f"domain-scope: host {host!r} does not match any allowed glob in "
            f"{scope!r}"
        )

    # directory scope (default)
    matched = any(
        fnmatch.fnmatch(cwd, pat) or fnmatch.fnmatch(cwd, pat.rstrip("*") + "*")
        for pat in scope
    )
    return matched, None


def _effective_grants(model: dict[str, Any], subject: str) -> list[dict[str, Any]]:
    keep = {"all", subject}
    return [g for g in model.get("grants", []) if g.get("subject") in keep]


def decide(
    model: dict[str, Any],
    catalog: dict[str, Any],
    request: dict[str, Any],
    posture: str | None = None,
) -> tuple[str, str]:
    """Decide a request: returns (decision, reason), decision in
    {allow, deny, abstain}. `abstain` defers to the harness's normal flow
    (lenient); strict maps an unmodeled request to deny.

    `request` = {type: "bash"|"tool", command|tool, cwd, subject[, url]}.
    The optional `url` field carries the request URL for ``domain``-scoped
    privilege checks (web-fetch).  Effective grants = baseline (`all`) ∪ the
    subject's own grants; deny wins; a scoped allow denies the privilege
    outside its scope.

    Scope semantics by privilege ``scope_type`` (from the catalog):
      - ``directory`` (default): grant scope globs are matched against ``cwd``.
      - ``domain``: grant scope globs are matched against the URL hostname
        (positive allow-list; deny/negation globs are explicitly rejected).
    """
    posture = posture or model.get("posture", "lenient")
    subject = request["subject"]
    hits = recognized_privileges(catalog, request)
    privileges_catalog = catalog.get("privileges", {})
    matched_allow = False
    for g in _effective_grants(model, subject):
        privs = _privilege_ids(g.get("privilege"))
        overlap = hits & privs
        if not overlap:
            continue
        if g.get("effect", "allow") == "deny":
            return "deny", f"deny grant for {subject} on {sorted(overlap)}"
        # Determine scope_type from the catalog for the overlapping privileges.
        # When the overlap spans multiple privileges, use the most restrictive
        # scope_type: prefer "domain" > "directory" > None.  In practice a
        # single grant rarely covers privileges of mixed scope_type.
        scope_type: str | None = None
        for pid in overlap:
            pspec = privileges_catalog.get(pid, {})
            st = pspec.get("scope_type")
            if st == "domain":
                scope_type = "domain"
                break
            if st == "directory":
                scope_type = "directory"
        ok, reason = _scope_ok(
            g.get("scope"),
            request.get("cwd", ""),
            scope_type=scope_type,
            url=request.get("url"),
        )
        if ok:
            matched_allow = True
        else:
            deny_msg = reason or (
                f"{sorted(overlap)} allowed for {subject} only in "
                f"{g.get('scope')}, not {request.get('cwd')!r}"
            )
            return "deny", deny_msg
    if matched_allow:
        return "allow", f"allow grant for {subject} on {sorted(hits)}"
    if posture == "strict":
        return "deny", "strict posture: nothing grants this request"
    return "abstain", "lenient posture: defer to the harness's normal flow"


def _read_default_agent(project_root: str) -> str | None:
    """Read the configured default agent from .claude/settings.json.

    Returns the value of the top-level ``agent`` key if present and non-empty,
    otherwise ``None``.  Uses stdlib ``json`` only (the hook runs bare python3 —
    no third-party deps).  Any I/O or parse error silently returns ``None`` so
    the caller falls back to ``operator`` — never throw from subject resolution.
    """
    import json as _json
    import os.path as _osp

    path = _osp.join(project_root, ".claude", "settings.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = _json.load(fh)
        agent = data.get("agent")
        return str(agent) if agent and isinstance(agent, str) else None
    except Exception:
        return None


def hook_decide(
    model: dict[str, Any],
    catalog: dict[str, Any],
    payload: dict[str, Any],
    project_root: str | None = None,
) -> tuple[str, str]:
    """Decision-core entry point for a PreToolUse hook payload. Fails OPEN —
    any fault yields abstain (defer), never a silent block; non-negotiable
    denies are double-locked in the fail-closed native settings (ADR-002).

    Subject resolution (per issue #57):
      - ``agent_type`` present in payload → ``agent:<agent_type>`` (unchanged)
      - ``agent_type`` absent + ``project_root`` set + ``.claude/settings.json``
        has ``agent: X`` → ``agent:X`` (main session runs as the configured agent)
      - ``agent_type`` absent + no configured default → ``operator``

    Pass ``project_root`` (the adopter tree root) from the hook entry-point so
    main-session calls resolve to the configured agent.  The CLI synthesizes
    payloads with explicit ``agent_type`` and does not need to pass a root.
    """
    try:
        agent_type = payload.get("agent_type")
        if agent_type:
            subject = f"agent:{agent_type}"
        elif project_root:
            default_agent = _read_default_agent(project_root)
            subject = f"agent:{default_agent}" if default_agent else "operator"
        else:
            subject = "operator"
        tool = payload["tool_name"]
        if tool == "Bash":
            request = {
                "type": "bash",
                "command": payload["tool_input"]["command"],
                "cwd": payload.get("cwd", ""),
                "subject": subject,
            }
        else:
            request = {
                "type": "tool",
                "tool": tool,
                "cwd": payload.get("cwd", ""),
                "subject": subject,
                # Surface the URL for domain-scoped privilege checks (web-fetch).
                # WebFetch and WebSearch both supply `url` in tool_input; absent
                # for all other tools.  A missing key becomes None, which _scope_ok
                # treats as an unparseable host → deny for domain-scoped grants.
                "url": payload.get("tool_input", {}).get("url"),
            }
        return decide(model, catalog, request)
    except Exception as exc:  # fail-open
        return "abstain", f"hook fault → fail-open: {exc!r}"


# ---- thin loaders ----------------------------------------------------------

# ---- stdlib YAML-subset fallback -------------------------------------------
# Used by load_yaml() when ruamel.yaml is not importable (e.g. inside macOS
# Seatbelt where uv cannot run — ADR-014). Handles the subset the shipped files
# use: block mappings, block sequences, single-quoted and double-quoted scalars,
# flow sequences ([a, b, c]), block scalars (>-), booleans, integers, null,
# and # comments. No anchors, aliases, merge-keys, flow mappings, multi-doc,
# or custom tags — none appear in the shipped files.
#
# Invariant (ADR-002/ADR-003 same-code): the fallback parses the shipped files
# IDENTICALLY to ruamel.yaml safe-load. Covered by the conformance fixture
# tests/test_permission_decide.py::test_stdlib_fallback_parses_identically_to_ruamel.

def _stdlib_load_yaml(text: str) -> Any:
    """Minimal YAML-subset parser (stdlib-only, no third-party deps)."""
    import re as _re

    # ---- tokeniser helpers -------------------------------------------------

    def _parse_scalar(raw: str) -> Any:
        """Decode a YAML scalar string (already stripped) to a Python value."""
        s = raw.strip()
        if not s or s in ("~", "null", "Null", "NULL"):
            return None
        if s in ("true", "True", "TRUE"):
            return True
        if s in ("false", "False", "FALSE"):
            return False
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            pass
        return s

    def _unquote_single(s: str) -> str:
        """Strip surrounding single-quotes; handle '' → ' escape."""
        assert s.startswith("'") and s.endswith("'")
        return s[1:-1].replace("''", "'")

    def _unquote_double(s: str) -> str:
        """Strip surrounding double-quotes; handle \\n, \\t, \\\\ escapes."""
        assert s.startswith('"') and s.endswith('"')
        inner = s[1:-1]
        return inner.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")

    def _parse_value_token(token: str) -> Any:
        """Parse a single value token (scalar or simple unquoted string)."""
        t = token.strip()
        if t.startswith("'") and t.endswith("'") and len(t) >= 2:
            return _unquote_single(t)
        if t.startswith('"') and t.endswith('"') and len(t) >= 2:
            return _unquote_double(t)
        return _parse_scalar(t)

    def _split_flow_sequence(body: str) -> list:
        """Parse the interior of a flow sequence [...] into a Python list.
        Handles single- and double-quoted strings as atomic tokens."""
        items: list = []
        current = ""
        in_single = False
        in_double = False
        for ch in body:
            if ch == "'" and not in_double:
                in_single = not in_single
                current += ch
            elif ch == '"' and not in_single:
                in_double = not in_double
                current += ch
            elif ch == "," and not in_single and not in_double:
                s = current.strip()
                if s:
                    items.append(_parse_value_token(s))
                current = ""
            else:
                current += ch
        s = current.strip()
        if s:
            items.append(_parse_value_token(s))
        return items

    # ---- block-scalar collector (>- folded-strip, | literal-strip) ---------

    def _collect_block_scalar(lines: list, start_idx: int, indent: int) -> tuple[str, int]:
        """Collect lines for a block scalar starting at start_idx.
        Returns (scalar_value, next_line_index)."""
        # Determine the content indentation from the first non-empty content line.
        content_indent: int | None = None
        parts: list[str] = []
        i = start_idx
        while i < len(lines):
            raw = lines[i]
            stripped = raw.rstrip()
            if not stripped:
                parts.append("")
                i += 1
                continue
            col = len(stripped) - len(stripped.lstrip())
            if content_indent is None:
                content_indent = col
            if col < (content_indent if content_indent is not None else indent + 1):
                break
            parts.append(stripped[content_indent:] if content_indent else stripped)
            i += 1
        # Folded (>-): join non-empty runs with space, remove trailing newlines.
        result = " ".join(p for p in parts if p).rstrip()
        return result, i

    # ---- line preprocessor -------------------------------------------------

    def _strip_comment(line: str) -> str:
        """Remove inline # comments that are outside quotes."""
        out = ""
        in_single = False
        in_double = False
        for ch in line:
            if ch == "'" and not in_double:
                in_single = not in_single
            elif ch == '"' and not in_single:
                in_double = not in_double
            elif ch == "#" and not in_single and not in_double:
                break
            out += ch
        return out.rstrip()

    # ---- recursive block parser --------------------------------------------

    def _parse_block(lines: list, idx: int, base_indent: int) -> tuple[Any, int]:
        """Parse a block node (mapping or sequence) at the given base_indent.
        Returns (value, next_idx)."""
        if idx >= len(lines):
            return None, idx

        result_map: dict | None = None
        result_seq: list | None = None
        i = idx

        while i < len(lines):
            raw = lines[i]
            stripped_raw = raw.rstrip()
            if not stripped_raw or stripped_raw.lstrip().startswith("#"):
                i += 1
                continue

            line = _strip_comment(stripped_raw)
            if not line.strip():
                i += 1
                continue

            col = len(line) - len(line.lstrip())

            # Back up to parent block
            if col < base_indent:
                break

            # New sibling at a HIGHER-than-expected indent inside parent — skip
            # (shouldn't happen in valid YAML, but be defensive).
            if col > base_indent and result_map is None and result_seq is None:
                # We're establishing the indent from the first entry.
                base_indent = col

            content = line.lstrip()

            # ---- sequence entry: starts with "- " --------------------------
            if content.startswith("- "):
                if result_map is not None:
                    break  # type switch — back to parent
                if result_seq is None:
                    result_seq = []
                value_part = content[2:].strip()
                if value_part:
                    # Inline value after "- "
                    if value_part.startswith("{"):
                        # Inline flow mapping — not needed for shipped files; skip.
                        result_seq.append(_parse_value_token(value_part))
                        i += 1
                    elif value_part.startswith("["):
                        body = value_part[1:value_part.rfind("]")]
                        result_seq.append(_split_flow_sequence(body))
                        i += 1
                    elif value_part.startswith("'") or value_part.startswith('"'):
                        result_seq.append(_parse_value_token(value_part))
                        i += 1
                    elif ":" in value_part:
                        # Inline mapping key: value on same line as "- "
                        child_lines = []
                        # first key:value is on this line
                        child_indent = col + 2
                        child_lines.append(" " * child_indent + value_part)
                        j = i + 1
                        while j < len(lines):
                            r2 = lines[j].rstrip()
                            if not r2 or r2.lstrip().startswith("#"):
                                j += 1
                                continue
                            c2 = len(r2) - len(r2.lstrip())
                            if c2 <= col:
                                break
                            child_lines.append(r2)
                            j += 1
                        child_val, _ = _parse_block(child_lines, 0, child_indent)
                        result_seq.append(child_val)
                        i = j
                    else:
                        result_seq.append(_parse_scalar(value_part))
                        i += 1
                else:
                    # "- " alone — nested block
                    child_indent = col + 2
                    child_val, i = _parse_block(lines, i + 1, child_indent)
                    result_seq.append(child_val)
                continue

            # ---- bare "- " (dash alone on line) ----------------------------
            if content.strip() == "-":
                if result_seq is None:
                    result_seq = []
                result_seq.append(None)
                i += 1
                continue

            # ---- mapping key: value ----------------------------------------
            colon_pos = -1
            in_s = False
            in_d = False
            for ci, ch in enumerate(content):
                if ch == "'" and not in_d:
                    in_s = not in_s
                elif ch == '"' and not in_s:
                    in_d = not in_d
                elif ch == ":" and not in_s and not in_d:
                    colon_pos = ci
                    break

            if colon_pos == -1:
                # Plain scalar continuation — treat as bare value
                i += 1
                continue

            key_raw = content[:colon_pos].strip()
            key = _parse_value_token(key_raw) if key_raw else None
            val_raw = content[colon_pos + 1:].strip()

            if result_seq is not None:
                break  # type switch
            if result_map is None:
                result_map = {}

            if not val_raw:
                # Value on subsequent lines
                i += 1
                # Peek at next non-blank, non-comment line
                j = i
                while j < len(lines):
                    r2 = lines[j].rstrip()
                    if not r2 or r2.lstrip().startswith("#"):
                        j += 1
                        continue
                    break
                if j >= len(lines):
                    result_map[key] = None
                    i = j
                    continue
                r2 = lines[j]
                c2 = len(r2) - len(r2.lstrip())
                # A block sequence is a valid mapping value at the SAME indent
                # level as the key — the "- " indicator provides the structural
                # indent for the sequence entries' content.  Without this check
                # the grants.yaml shape (key at col 0, "- " entries at col 0)
                # parses to None, silently dropping all adopter grants and
                # causing the zero-dep hook to fail open (issue #55).
                _r2_content = r2.lstrip()
                _same_level_seq = (
                    c2 == col
                    and (_r2_content.startswith("- ") or _r2_content == "-")
                )
                if c2 > col or _same_level_seq:
                    # Child block (deeper indent, OR same-indent block sequence)
                    child_val, i = _parse_block(lines, j, c2)
                    result_map[key] = child_val
                else:
                    result_map[key] = None
                continue
            else:
                # Inline value
                v = val_raw
                if v.startswith(">-") or v.startswith("|"):
                    # Block scalar
                    scalar_val, i = _collect_block_scalar(lines, i + 1, col + 1)
                    result_map[key] = scalar_val
                elif v.startswith("["):
                    close = v.rfind("]")
                    if close != -1:
                        body = v[1:close]
                        result_map[key] = _split_flow_sequence(body)
                    else:
                        result_map[key] = v
                    i += 1
                elif v.startswith("'") or v.startswith('"'):
                    result_map[key] = _parse_value_token(v)
                    i += 1
                else:
                    result_map[key] = _parse_scalar(v)
                    i += 1
                continue

        if result_map is not None:
            return result_map, i
        if result_seq is not None:
            return result_seq, i
        return None, i

    # ---- entry point -------------------------------------------------------
    lines = text.splitlines()
    # Strip document-start marker
    clean: list[str] = []
    for ln in lines:
        s = ln.rstrip()
        if s.lstrip() in ("---", "..."):
            continue
        clean.append(ln)
    result, _ = _parse_block(clean, 0, 0)
    return result if result is not None else {}


def load_yaml(path: str) -> dict[str, Any]:
    """Load a YAML file, returning a dict. Uses ruamel.yaml when available
    (the kit-wide library); falls back to the stdlib-only subset parser
    when ruamel.yaml is not importable (e.g. inside macOS Seatbelt, ADR-014).

    The stdlib fallback is in this SHARED loader — not duplicated in the hook
    — so the hook and the `pkit permissions` CLI reach identical parse results
    through the same code path (ADR-002/ADR-003 same-code invariant).
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        from ruamel.yaml import YAML as _YAML
        _yaml = _YAML(typ="safe")
        import io as _io
        return _yaml.load(_io.StringIO(text)) or {}
    except ImportError:
        result = _stdlib_load_yaml(text)
        return result if isinstance(result, dict) else {}


def _exists(path: str) -> bool:
    import os.path

    return os.path.isfile(path)


def load_catalog(target_root: str) -> dict[str, Any]:
    """Load the privilege catalog from a target tree's standard location."""
    import os.path

    path = os.path.join(target_root, ".pkit", "schemas", "privilege-catalog.yaml")
    return load_yaml(path) if _exists(path) else {}


def guardrail_denies(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Synthesize baseline `{subject: all, effect: deny}` grants for every
    privilege the catalog flags `guardrail: true`. The catalog is the single
    source of truth for the guardrail deny set (ADR-002's double-lock): these
    are the fail-open hook half; the harness ships matching fail-closed native
    denies. Returns one deny grant per guardrail privilege, sorted by id."""
    out: list[dict[str, Any]] = []
    for pid in sorted(catalog.get("privileges", {})):
        if catalog["privileges"][pid].get("guardrail"):
            out.append(
                {"subject": "all", "privilege": f"[privilege-catalog:{pid}]", "effect": "deny"}
            )
    return out


def _active_profile_grants(target_root: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Grants contributed by the active permission profile (per ADR-005), if any.

    The profile is a LAYER, never an owner: its grants sit between the guardrail
    denies and the adopter's own grants.yaml, and the adopter's grants are
    unioned last so a manual `grant`/`revoke` is never overwritten by a profile.
    Resolves the active profile name (`config.active_profile`) project-first
    (`project/profiles/<name>.yaml`) then shipped (`profiles/<name>.yaml`)."""
    import os.path

    name = config.get("active_profile")
    if not name:
        return []
    for base in (
        os.path.join(target_root, ".pkit", "permissions", "project", "profiles"),
        os.path.join(target_root, ".pkit", "permissions", "profiles"),
    ):
        path = os.path.join(base, f"{name}.yaml")
        if _exists(path):
            return list(load_yaml(path).get("grants", []) or [])
    return []


def _capability_fragment_grants(target_root: str) -> list[dict[str, Any]]:
    """Grants contributed by installed capabilities (ADR-016).

    Walks the manifest ``components:`` list (NOT a glob of ``.pkit/capabilities/``)
    and for each component of kind ``capability`` reads its grants fragment at
    ``.pkit/capabilities/<name>/permissions/grants.yaml`` if present. An
    uninstalled or orphan capability directory contributes nothing — only
    manifest-registered components count.

    Each grant dict is annotated with a ``_capability`` key naming the source
    capability; ``load_model`` carries this through for the reporting layer
    (``pkit permissions overview`` / ``explain``). The ``_capability`` key is
    stripped before the model is passed to ``decide()`` — ``decide()`` only
    reads ``subject``, ``privilege``, ``effect``, and ``scope``.

    Stdlib-safe (ADR-002 / ADR-003 same-code invariant): reads files through
    the existing ``load_yaml`` / ``_stdlib_load_yaml`` fallback; no third-party
    dependency, no ``src/project_kit`` import.
    """
    import os.path

    manifest_path = os.path.join(target_root, ".pkit", "manifest.yaml")
    if not _exists(manifest_path):
        return []
    manifest = load_yaml(manifest_path)
    out: list[dict[str, Any]] = []
    for component in manifest.get("components", []) or []:
        if not isinstance(component, dict):
            continue
        if component.get("kind") != "capability":
            continue
        name = component.get("name")
        if not name:
            continue
        frag_path = os.path.join(
            target_root, ".pkit", "capabilities", name, "permissions", "grants.yaml"
        )
        if not _exists(frag_path):
            continue
        doc = load_yaml(frag_path)
        for grant in doc.get("grants", []) or []:
            if isinstance(grant, dict):
                annotated = dict(grant)
                annotated["_capability"] = name
                out.append(annotated)
    return out


def load_model(target_root: str, catalog: dict[str, Any]) -> dict[str, Any]:
    """Build the effective permission model for a target tree: the catalog-
    derived guardrail denies, then installed-capability fragments, then the
    active profile's grant-layer, then the adopter's authored grants — unioned
    in that order — plus posture/ownership_mode from project config.

    This is the SINGLE model loader (ADR-002's same-code invariant): the
    PreToolUse hook and the `pkit permissions` CLI both call it, so they decide
    and display from byte-identical models. Order is guardrails → capability
    fragments → profile → adopter (adopter last so manual grants are never
    clobbered, per ADR-005); `decide()` is deny-wins and order-independent
    regardless. Capability-fragment grants are annotated with ``_capability``
    for the reporting layer (ADR-016); ``decide()`` ignores the extra key.
    """
    import os.path

    perm_dir = os.path.join(target_root, ".pkit", "permissions", "project")
    grants_path = os.path.join(perm_dir, "grants.yaml")
    config_path = os.path.join(perm_dir, "config.yaml")
    grants_doc = load_yaml(grants_path) if _exists(grants_path) else {}
    config = load_yaml(config_path) if _exists(config_path) else {}
    return {
        "posture": config.get("posture", "lenient"),
        "ownership_mode": config.get("ownership_mode", "additive"),
        "active_profile": config.get("active_profile"),
        "grants": (
            guardrail_denies(catalog)
            + _capability_fragment_grants(target_root)
            + _active_profile_grants(target_root, config)
            + list(grants_doc.get("grants", []) or [])
        ),
    }
