#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml"]
# ///
"""Resolve overlay placeholders in an agent file's frontmatter, write to stdout.

Invoked by `deploy-agents.sh` once per agent. Reads:

- arg 1: source agent file (`.pkit/agents/{core,project}/<name>/<name>.md`)
- arg 2: agent name (used for per-agent overrides lookup)
- arg 3: overlay file (`.pkit/agents/project/overlay.yaml`)

Writes the resolved agent file content to stdout (frontmatter with
placeholders substituted + original body). Exits non-zero with a clear
error message if a placeholder references a category the overlay does
not define.

Self-contained: PEP 723 inline metadata declares the `ruamel.yaml`
dependency, so `uv run --script` installs it transparently on first
invocation. No host pyproject.toml required.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

from ruamel.yaml import YAML


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(
            "usage: _resolve_agent.py <source_file> <agent_name> <overlay_file>",
            file=sys.stderr,
        )
        return 2

    source_file, agent_name, overlay_file = argv[1], argv[2], argv[3]

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)

    defaults: dict = {}
    agent_overrides: dict = {}
    overlay_path = Path(overlay_file)
    if overlay_path.is_file() and overlay_path.stat().st_size > 0:
        with overlay_path.open() as f:
            data = yaml.load(f) or {}
        overrides = data.pop("overrides", {}) or {}
        agent_overrides = overrides.get(agent_name, {}) or {}
        defaults = data

    def resolve(category: str):
        if category in agent_overrides:
            return agent_overrides[category]
        if category in defaults:
            return defaults[category]
        return None

    content = Path(source_file).read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?\n)---\n(.*)$", content, re.DOTALL)
    if not match:
        print(f"{source_file}: agent file has no frontmatter", file=sys.stderr)
        return 1
    fm_yaml = match.group(1)
    body = match.group(2)

    fm_data = yaml.load(io.StringIO(fm_yaml)) or {}

    def expand_list(items: list):
        out: list = []
        for item in items:
            if isinstance(item, str) and item.startswith("<") and item.endswith(">"):
                cat = item[1:-1]
                resolved = resolve(cat)
                if resolved is None:
                    print(
                        f"{agent_name}: category <{cat}> referenced but not defined "
                        f"in overlay ({overlay_file})",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                if isinstance(resolved, list):
                    out.extend(resolved)
                else:
                    out.append(resolved)
            else:
                out.append(item)
        return out

    for key in ("owns", "needs", "answers"):
        if key in fm_data and isinstance(fm_data[key], list):
            fm_data[key] = expand_list(fm_data[key])
    if "reads" in fm_data and isinstance(fm_data["reads"], dict):
        for k in ("paths", "records", "patterns"):
            if k in fm_data["reads"] and isinstance(fm_data["reads"][k], list):
                fm_data["reads"][k] = expand_list(fm_data["reads"][k])

    out = io.StringIO()
    yaml.dump(fm_data, out)
    sys.stdout.write(f"---\n{out.getvalue()}---\n{body}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
