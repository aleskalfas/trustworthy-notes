"""Milestone resolution helper for pm scripts.

`--milestone` arguments in pm scripts accept either the milestone's
NUMBER (e.g. `6`) or its exact TITLE (e.g. `Milestone 1: Self-host
project-kit pm capability cleanly`). This matches `gh issue create
--milestone` and `gh issue edit --milestone` behaviour at the gh CLI
layer.

Per #217: prior to this lib, `create-issue.py` accepted only number
(argparse `type=int`) and `promote-issue.py` accepted only title.
Cross-script inconsistency surfaced repeatedly during the session.
This module exposes a single resolver each script calls; downstream
code receives a normalised `(number, title)` pair regardless of
input form.

The resolver lists OPEN milestones via `gh api` (paginated, robust
to concatenated-array output per `_parse_concatenated_arrays`) and
matches by number or title. If the arg is numeric and matches no
open milestone, the resolver returns None (the script reports the
error and exits). Closed milestones are out of scope — pm operations
attach to open milestones only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from _lib.gh import gh_run


@dataclass(frozen=True)
class Milestone:
    """Normalised representation of a GitHub milestone."""

    number: int
    title: str


def list_open_milestones(config: dict[str, Any]) -> list[dict] | None:
    """Fetch every open milestone in the current repo via `gh api`.

    Returns the parsed list of milestone dicts, or None if `gh` is
    missing or the API call fails. Each dict carries at minimum
    `number: int` and `title: str`.
    """
    try:
        proc = gh_run(
            [
                "gh", "api",
                "--paginate",
                "repos/{owner}/{repo}/milestones?state=open",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    try:
        text = proc.stdout.strip()
        if not text:
            return []
        return _parse_concatenated_arrays(text)
    except (ValueError, KeyError, TypeError):
        return None


def resolve_milestone(arg: str, config: dict[str, Any]) -> Milestone | None:
    """Resolve a `--milestone` argument to a `(number, title)` pair.

    Accepts the milestone number (string of digits, e.g. `"6"`) or its
    exact title (any other string, e.g. `"Milestone 1: ..."`).

    Returns the matched `Milestone` dataclass on success; `None` if no
    open milestone matches the input. Callers should print an error
    and exit when None is returned. Numeric args are matched against
    the milestone's `number` field; non-numeric args against `title`.
    """
    if not arg:
        return None
    milestones = list_open_milestones(config)
    if milestones is None:
        return None
    if arg.lstrip("-").isdigit():
        target_number = int(arg)
        for ms in milestones:
            if isinstance(ms, dict) and ms.get("number") == target_number:
                return Milestone(
                    number=int(ms["number"]),
                    title=str(ms.get("title", "")),
                )
        return None
    for ms in milestones:
        if isinstance(ms, dict) and ms.get("title") == arg:
            return Milestone(
                number=int(ms["number"]),
                title=str(ms["title"]),
            )
    return None


def _parse_concatenated_arrays(text: str) -> list:
    """gh --paginate may emit concatenated JSON arrays; merge them.

    Equivalent to promote-issue.py's `_parse_concatenated_json_arrays`
    — extracted here so create-issue.py can share the parser without
    a cross-script import. Future cleanup: promote-issue should
    re-export from this module instead of carrying its own copy.
    """
    decoder = json.JSONDecoder()
    out: list = []
    idx = 0
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except ValueError:
            break
        if isinstance(obj, list):
            out.extend(obj)
        idx = end
    return out
