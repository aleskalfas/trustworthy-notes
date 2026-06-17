"""Shared `gh` CLI shell-out helper per [project-management:DEC-023-gh-host-and-owner].

Every pm script that shells out to `gh` routes through this module so the
adopter's `project/config.yaml` `gh:` block — not ambient shell state —
determines which host and owner the call lands on. The public surface:
`gh_env`, `gh_owner_flag`, `gh_run`, `gh_get_issue`, `load_adopter_config`.

Adopter config shape (both fields optional; absence = delegate to ambient):

    gh:
      host: github.com                  # threaded as GH_HOST env var
      default_owner: ai-platform-incubation # spliced as `--owner` where applicable

Precedence: config wins over ambient. When `GH_HOST` is set in the shell
AND `gh.host` is set in config, the config value is what reaches `gh`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.error import YAMLError
except ImportError:  # ruamel is in the kit's pyproject; this is defensive.
    YAML = None  # type: ignore[assignment, misc]
    YAMLError = Exception  # type: ignore[assignment, misc]


def gh_env(config: dict[str, Any]) -> dict[str, str]:
    """Build the `env=` dict to pass to subprocess.run for a `gh` invocation.

    Always starts from os.environ (so adopter PATH, HOME, etc. propagate).
    When the adopter config declares `gh.host`, override `GH_HOST` to that
    value — this is the config-wins-over-ambient rule per DEC-023.

    A caller that wants strict-no-ambient (test isolation) can pass the
    returned dict to subprocess.run(env=...); the kit's normal callers
    use it directly without thinking about it.
    """
    env = dict(os.environ)
    gh_block = _gh_block(config)
    host = gh_block.get("host")
    if isinstance(host, str) and host:
        env["GH_HOST"] = host
    return env


def gh_owner_flag(config: dict[str, Any]) -> list[str]:
    """Return `['--owner', '<default_owner>']` when configured, else `[]`.

    Callers splice the result into the `gh` argv where the operation
    accepts `--owner` (project / org / cross-owner label operations).
    For operations that don't accept `--owner`, callers don't call this
    function — the helper does not auto-detect operation shape.
    """
    gh_block = _gh_block(config)
    owner = gh_block.get("default_owner")
    if isinstance(owner, str) and owner:
        return ["--owner", owner]
    return []


def gh_run(
    args: list[str],
    config: dict[str, Any],
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Run a `gh` command with the adopter's pinned environment.

    Equivalent to `subprocess.run(args, env=gh_env(config), ...)` with the
    caller's kwargs forwarded. Defaults `text=True` and `capture_output=True`
    so callers don't repeat the same boilerplate; passing those explicitly
    overrides the default. Callers must include any `gh_owner_flag(config)`
    elements in `args` themselves — the helper does not splice them.

    Returns the CompletedProcess unchanged; callers interpret exit code
    and stdout/stderr per the operation's contract.
    """
    kwargs.setdefault("text", True)
    kwargs.setdefault("capture_output", True)
    # Always set env unless the caller explicitly passed env=None or env=...
    if "env" not in kwargs:
        kwargs["env"] = gh_env(config)
    return subprocess.run(args, **kwargs)  # noqa: S603 — args composed from validated config + kit-controlled strings


def gh_get_issue(
    issue_number: int,
    config: dict[str, Any],
    *,
    fields: str,
) -> dict[str, Any] | None:
    """Fetch issue data via `gh issue view --json <fields>`.

    Returns the parsed JSON dict on success, or None on any failure
    (gh not on PATH, non-zero exit, or non-JSON stdout). Each caller
    passes only the `--json` fields it actually needs so the GitHub API
    round-trip is minimal.

    Canonical error-handling pattern shared across all pm scripts:
      - FileNotFoundError → gh is not on PATH; prints an error and returns None.
      - Non-zero exit → prints gh's stderr and returns None.
      - JSONDecodeError → prints a note and returns None.

    Callers must not rely on keys beyond those they requested in `fields`.
    """
    try:
        proc = gh_run(
            ["gh", "issue", "view", str(issue_number), "--json", fields],
            config,
            check=False,
        )
    except FileNotFoundError:
        print("error: `gh` not on PATH. Install GitHub CLI.", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(
            f"error: gh issue view {issue_number} failed.\n"
            f"stderr: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(
            f"error: gh returned non-JSON for issue {issue_number}.",
            file=sys.stderr,
        )
        return None


def _gh_block(config: dict[str, Any]) -> dict[str, Any]:
    """Extract the `gh:` mapping from adopter config; empty dict if absent.

    Robust to both an absent `gh` key and a `gh: null` YAML value (which
    PyYAML parses as None). Anything that isn't a mapping is treated as
    absent — the validator in pre-check.py flags the shape error
    separately.
    """
    block = config.get("gh") if isinstance(config, dict) else None
    return block if isinstance(block, dict) else {}


def load_adopter_config(capability_root: Path) -> dict[str, Any]:
    """Load the adopter's `project/config.yaml` and return it as a dict.

    Returns an empty dict if the file is missing, empty, unparseable, or
    not a mapping at the top level — every pm script's `gh` calls
    continue to function with ambient state in that case. The `pre-check`
    script is the gating layer that surfaces config-shape problems with
    actionable diagnostics; this helper just gives every other script a
    one-liner to get the adopter's config and thread it through `gh_run`.
    """
    if YAML is None:  # pragma: no cover — ruamel is in the kit's pyproject
        return {}
    path = capability_root / "project" / "config.yaml"
    if not path.is_file():
        return {}
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError):
        return {}
    return data if isinstance(data, dict) else {}
