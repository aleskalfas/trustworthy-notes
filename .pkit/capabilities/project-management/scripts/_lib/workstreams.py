"""Workstreams parsing + validation library (per DEC-018).

Supports both storage shapes from DEC-018:

  * **File-canonical** — `<capability_root>/project/workstreams.yaml`
    in mapping form or list-shorthand form. File is the source of
    truth once it exists.
  * **Legacy fallback** — `<capability_root>/project/config.yaml`'s
    `workstreams:` list. Read for backward compatibility before the
    v0.5.0 migration completes.

Naming rules (DEC-018 + workstreams.schema.json):
  * slug matches `^[a-z][a-z0-9-]*[a-z0-9]$`; 2–40 chars.
  * No consecutive hyphens.
  * Attribute fields: name (≤64), description (≤200), status
    (active/deprecated), deprecated_reason (≤200).

The library is dependency-free at import time so it can be imported
from any PEP 723 script regardless of its declared dependencies.
YAML loading is the caller's responsibility — scripts load the file
themselves and pass the parsed dict to `parse_workstreams()`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")
WORKSTREAMS_RELATIVE = "project/workstreams.yaml"
CONFIG_RELATIVE = "project/config.yaml"


@dataclass(frozen=True)
class Workstream:
    """One workstream entry per DEC-018."""

    slug: str
    name: str
    description: str = ""
    status: str = "active"  # "active" | "deprecated"
    deprecated_reason: str = ""


@dataclass(frozen=True)
class WorkstreamsParse:
    """Outcome of parsing a workstreams.yaml file."""

    entries: tuple[Workstream, ...]
    form: str  # "mapping" | "list" | "empty"
    errors: tuple[str, ...] = ()


def workstreams_path(capability_root: Path) -> Path:
    return capability_root / WORKSTREAMS_RELATIVE


def config_path(capability_root: Path) -> Path:
    return capability_root / CONFIG_RELATIVE


def has_workstreams_file(capability_root: Path) -> bool:
    return workstreams_path(capability_root).is_file()


def parse_workstreams(data: dict | list | None) -> WorkstreamsParse:
    """Parse a parsed-YAML workstreams entry into a normalised structure.

    Accepts either:
      * A top-level dict shaped `{schema_version: ..., workstreams: ...}`
        (canonical workstreams.yaml shape), OR
      * A bare list of slug strings (legacy config.yaml `workstreams:`
        field).
    """
    if data is None:
        return WorkstreamsParse(entries=(), form="empty")

    # Legacy: bare list.
    if isinstance(data, list):
        return _parse_list_form(data)

    if not isinstance(data, dict):
        return WorkstreamsParse(
            entries=(),
            form="empty",
            errors=(f"workstreams data must be a mapping or list, got {type(data).__name__}",),
        )

    inner = data.get("workstreams")
    if inner is None:
        return WorkstreamsParse(
            entries=(),
            form="empty",
            errors=("missing `workstreams:` key in file root",),
        )
    if isinstance(inner, list):
        return _parse_list_form(inner)
    if isinstance(inner, dict):
        return _parse_mapping_form(inner)
    return WorkstreamsParse(
        entries=(),
        form="empty",
        errors=(f"`workstreams:` must be a list or mapping, got {type(inner).__name__}",),
    )


def _parse_list_form(lst: list) -> WorkstreamsParse:
    entries: list[Workstream] = []
    errors: list[str] = []
    for i, item in enumerate(lst):
        if not isinstance(item, str):
            errors.append(f"list item #{i} is not a string: {item!r}")
            continue
        if not SLUG_PATTERN.match(item):
            errors.append(
                f"list item #{i}={item!r} does not match slug pattern "
                "`^[a-z][a-z0-9-]*[a-z0-9]$`"
            )
            continue
        if "--" in item:
            errors.append(f"slug {item!r} contains consecutive hyphens")
            continue
        if not (2 <= len(item) <= 40):
            errors.append(f"slug {item!r} is not 2–40 chars long")
            continue
        entries.append(Workstream(slug=item, name=item))
    return WorkstreamsParse(
        entries=tuple(entries), form="list", errors=tuple(errors)
    )


def _parse_mapping_form(mapping: dict) -> WorkstreamsParse:
    entries: list[Workstream] = []
    errors: list[str] = []
    for slug, attrs in mapping.items():
        if not isinstance(slug, str):
            errors.append(f"slug {slug!r} must be a string")
            continue
        if not SLUG_PATTERN.match(slug):
            errors.append(
                f"slug {slug!r} does not match `^[a-z][a-z0-9-]*[a-z0-9]$`"
            )
            continue
        if "--" in slug:
            errors.append(f"slug {slug!r} contains consecutive hyphens")
            continue
        if not (2 <= len(slug) <= 40):
            errors.append(f"slug {slug!r} is not 2–40 chars long")
            continue
        if attrs is None:
            entries.append(Workstream(slug=slug, name=slug))
            continue
        if not isinstance(attrs, dict):
            errors.append(f"{slug!r} attributes must be a mapping or null; got {type(attrs).__name__}")
            continue
        name = attrs.get("name") or slug
        if not isinstance(name, str) or len(name) > 64 or "\n" in name or "\r" in name:
            errors.append(f"{slug!r}: invalid `name` value")
            continue
        description = attrs.get("description") or ""
        if not isinstance(description, str) or len(description) > 200 or "\n" in description:
            errors.append(f"{slug!r}: invalid `description` value")
            continue
        status = attrs.get("status") or "active"
        if status not in ("active", "deprecated"):
            errors.append(f"{slug!r}: `status` must be `active` or `deprecated`")
            continue
        deprecated_reason = attrs.get("deprecated_reason") or ""
        if not isinstance(deprecated_reason, str) or len(deprecated_reason) > 200 or "\n" in deprecated_reason:
            errors.append(f"{slug!r}: invalid `deprecated_reason` value")
            continue
        entries.append(
            Workstream(
                slug=slug,
                name=name,
                description=description,
                status=status,
                deprecated_reason=deprecated_reason,
            )
        )
    return WorkstreamsParse(
        entries=tuple(entries), form="mapping", errors=tuple(errors)
    )


def find_active(parse: WorkstreamsParse) -> tuple[Workstream, ...]:
    return tuple(w for w in parse.entries if w.status == "active")


def slug_set(parse: WorkstreamsParse) -> set[str]:
    return {w.slug for w in parse.entries}


def duplicate_names(parse: WorkstreamsParse) -> list[str]:
    """Return name strings that appear more than once among ACTIVE entries."""
    counts: dict[str, int] = {}
    for w in find_active(parse):
        counts[w.name] = counts.get(w.name, 0) + 1
    return sorted(n for n, c in counts.items() if c > 1)
