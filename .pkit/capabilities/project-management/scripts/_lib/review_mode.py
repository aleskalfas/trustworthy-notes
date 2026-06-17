"""Review-mode resolution per [project-management:DEC-027-review-modes].

Resolves the effective review mode for a given PR by walking the three
override layers (highest wins):

  1. Project default — `review.mode:` in `project/config.yaml`.
  2. Per-issue label — `review:human` or `review:agent` on the issue.
  3. Per-invocation flag — `--require-human` on `review-work`.

Also exposes the role-based reviewer query for the human path.

Exports:

    ReviewMode (Literal["agent", "human"])
    ModeResolution — dataclass: mode + source (which layer won)
    resolve_mode(config, issue_labels, require_human) -> ModeResolution
    role_based_reviewers(members, role, exclude_login) -> list[str]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


ReviewMode = Literal["agent", "human"]
DEFAULT_MODE: ReviewMode = "agent"


@dataclass(frozen=True)
class ModeResolution:
    """Resolved review mode + the layer that produced it."""

    mode: ReviewMode
    source: str  # human-readable: "project default" | "label review:<mode>" | "--require-human flag"


def resolve_mode(
    config: dict[str, Any],
    issue_labels: list[str] | None = None,
    require_human: bool = False,
) -> ModeResolution:
    """Walk DEC-027's three layers; return the effective mode + its source.

    Layer 3 (--require-human flag) wins over Layer 2 (label) wins over
    Layer 1 (project default). Per DEC-027: if Layer 2 says agent but
    Layer 3 says human, the flag wins because it represents the
    operator's most recent intent.
    """
    # Layer 3: explicit flag (highest precedence).
    if require_human:
        return ModeResolution(mode="human", source="--require-human flag")

    # Layer 2: per-issue label.
    labels = issue_labels or []
    for label in labels:
        if label == "review:human":
            return ModeResolution(mode="human", source="label `review:human`")
        if label == "review:agent":
            return ModeResolution(mode="agent", source="label `review:agent`")

    # Layer 1: project default.
    review_block = config.get("review") if isinstance(config, dict) else None
    if isinstance(review_block, dict):
        mode = review_block.get("mode")
        if mode in ("agent", "human"):
            return ModeResolution(mode=mode, source="project default")

    # No explicit setting — kit default.
    return ModeResolution(mode=DEFAULT_MODE, source="kit default (no config)")


def role_based_reviewers(
    members: list[dict[str, Any]],
    role: str,
    exclude_login: str | None = None,
) -> list[str]:
    """Return github_login values for members whose `role:` matches `role`.

    Excludes `exclude_login` (typically the PR author per DEC-027).
    Empty role returns []. Empty members list returns [].
    Per DEC-027's v1 enum (PM | Implementer), the match is exact-string.
    """
    if not role or not members:
        return []
    out: list[str] = []
    for member in members:
        if not isinstance(member, dict):
            continue
        member_role = member.get("role")
        member_login = member.get("github_login")
        if member_role != role:
            continue
        if not isinstance(member_login, str) or not member_login:
            continue
        if exclude_login and member_login == exclude_login:
            continue
        out.append(member_login)
    return out


def reviewer_role_from_config(config: dict[str, Any]) -> str | None:
    """Extract `review.human_review.reviewer_role:` from config; None if absent."""
    review = config.get("review") if isinstance(config, dict) else None
    if not isinstance(review, dict):
        return None
    human_review = review.get("human_review")
    if not isinstance(human_review, dict):
        return None
    role = human_review.get("reviewer_role")
    return role if isinstance(role, str) and role else None
