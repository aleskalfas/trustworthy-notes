#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — check-mesh (verb-subject per DEC-020 + DEC-022).

Read-only methodology-mesh diagnostic. Compares the local repo's
methodology-shared state against configured peer repos. Surfaces drift
as warnings; never blocks.

Configuration in `project/config.yaml`:
  mesh_peers:
    - github://owner/repo
    - github://other-owner/other-repo
  # OR (single governance-repo pointer, mutually compatible):
  mesh_source: github://governance-owner/repo/path/to/mesh.yaml

Without either, the script exits 0 with `mesh check skipped`.

Scope compared (per DEC-022):
  * type:* labels (methodology-fixed; should be identical).
  * priority:* labels (label-substrate adopters only).
  * workstream:* labels (label-substrate adopters only).
  * project-management capability version.
  * members.yaml (closed-mode adopters only).
  * Milestone titles.

Membership gate per DEC-021 runs at startup.

Self-contained via PEP 723; runs via
  uv run --script .pkit/capabilities/project-management/scripts/check-mesh.py

Or via the dispatcher (per COR-021):
  pkit project-management check-mesh

Exit codes:
  0  rendered (any drift severity ≤ warning at v1)
  1  membership refusal
  2  usage error (peer config invalid)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
from _lib.gh import gh_run, load_adopter_config  # noqa: E402
from _lib.membership import (  # noqa: E402
    CAPABILITY_NAME,
    check_membership,
    resolve_capability_root,
    resolve_invoker_identity,
)


PEER_URI_RE = re.compile(r"^github://([^/]+)/([^/]+)(/.*)?$")


@dataclass(frozen=True)
class PeerSpec:
    """A peer's owner + repo."""

    owner: str
    repo: str

    @property
    def full(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class PeerState:
    """Snapshot of one peer's mesh-relevant state."""

    peer: PeerSpec
    labels: list[str]
    capability_version: str | None
    members: list[dict]
    milestones: list[str]
    error: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the local repo's methodology state against configured "
            "mesh peers; surface drift as warnings."
        ),
    )
    parser.add_argument(
        "--capability-root",
        type=Path,
        default=None,
        help=(
            "Path to the installed capability's directory "
            f"(default: <repo-root>/.pkit/capabilities/{CAPABILITY_NAME}/)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    args = parser.parse_args()

    capability_root = resolve_capability_root(args.capability_root)
    if capability_root is None:
        print(
            f"error: {CAPABILITY_NAME} capability not found.",
            file=sys.stderr,
        )
        return 2

    yaml_loader = YAML(typ="safe")
    config = load_adopter_config(capability_root)
    members = _read_members(capability_root, yaml_loader)
    invoker = resolve_invoker_identity(config=config)
    membership = check_membership(members, invoker)
    if not membership.allowed:
        print(membership.refusal_message, file=sys.stderr)
        return 1

    config = _read_yaml(capability_root / "project" / "config.yaml", yaml_loader)
    peers_or_err = resolve_peer_specs(config)
    if isinstance(peers_or_err, str):
        print(f"error: {peers_or_err}", file=sys.stderr)
        return 2

    peers = peers_or_err
    if not peers:
        if args.json:
            print(json.dumps({"status": "skipped", "reason": "no mesh_peers / mesh_source configured"}, indent=2))
        else:
            print("[check-mesh] no peers configured; mesh check skipped.")
        return 0

    # Gather local state.
    local = _gather_local_state(capability_root, config)
    # Gather peer states.
    peer_states = [_gather_peer_state(p) for p in peers]

    # Compare.
    drift = _compare(local, peer_states, config)

    if args.json:
        out = {
            "target": local.peer.full if local.peer else "<local>",
            "peers": [p.peer.full for p in peer_states],
            "drift": drift,
            "summary": _summary(drift),
        }
        print(json.dumps(out, indent=2))
    else:
        _print_report(local, peer_states, drift)

    return 0


# ---- config resolution ----------------------------------------------


def resolve_peer_specs(config: dict) -> list[PeerSpec] | str:
    """Resolve `mesh_peers:` / `mesh_source:` to a list of PeerSpec.

    Returns a list (possibly empty if neither is set) or an error
    string on malformed config.
    """
    peers: list[PeerSpec] = []
    mp = config.get("mesh_peers")
    if mp is not None:
        if not isinstance(mp, list):
            return f"`mesh_peers` must be a list of github:// URIs; got {type(mp).__name__}"
        for uri in mp:
            spec = parse_peer_uri(uri)
            if spec is None:
                return f"invalid mesh_peers entry: {uri!r}"
            peers.append(spec)
    ms = config.get("mesh_source")
    if ms is not None:
        spec = parse_peer_uri(ms)
        if spec is None:
            return f"invalid mesh_source URI: {ms!r}"
        # mesh_source dereferencing is deferred at v1 — treat as a
        # single peer for now.
        peers.append(spec)
    return peers


def parse_peer_uri(uri) -> PeerSpec | None:
    if not isinstance(uri, str):
        return None
    m = PEER_URI_RE.match(uri.strip())
    if not m:
        return None
    owner, repo, _path = m.groups()
    return PeerSpec(owner=owner, repo=repo)


# ---- state gathering ------------------------------------------------


def _gather_local_state(capability_root: Path, config: dict) -> PeerState:
    """Snapshot local state. Owner/repo is best-effort via gh repo view."""
    owner = config.get("repo_owner") or ""
    repo = config.get("repo_name") or ""
    if not owner or not repo:
        # Fallback to gh repo view.
        info = _gh_repo_view(None, config)
        if info:
            owner, _, repo = info.partition("/")
    spec = PeerSpec(owner=owner or "<unknown>", repo=repo or "<unknown>")
    labels = _gh_label_list(None, config) or []
    members = _read_members(capability_root, YAML(typ="safe"))
    version = _read_local_capability_version(capability_root)
    milestones = _gh_milestones(None, config) or []
    return PeerState(
        peer=spec,
        labels=labels,
        capability_version=version,
        members=members,
        milestones=milestones,
    )


def _gather_peer_state(peer: PeerSpec) -> PeerState:
    """Fetch a peer's state via gh API. Falls back gracefully on error."""
    labels = _gh_label_list(peer, config) or []
    version = _gh_peer_capability_version(peer, config)
    members = _gh_peer_members(peer, config)
    milestones = _gh_milestones(peer, config) or []
    return PeerState(
        peer=peer,
        labels=labels,
        capability_version=version,
        members=members,
        milestones=milestones,
    )


# ---- comparison -----------------------------------------------------


def _compare(local: PeerState, peers: list[PeerState], config: dict) -> list[dict]:
    drift: list[dict] = []
    has_board = bool(config.get("has_projects_v2_board", False))

    for peer in peers:
        # Capability version drift.
        if local.capability_version and peer.capability_version:
            if local.capability_version != peer.capability_version:
                drift.append({
                    "kind": "capability-version",
                    "peer": peer.peer.full,
                    "local": local.capability_version,
                    "peer_value": peer.capability_version,
                    "severity": "warning",
                })

        # Label drift — only methodology-mandated classes.
        for axis in ("type", "priority", "workstream"):
            if axis in ("priority", "workstream") and has_board:
                continue  # board adopters don't use these labels
            local_set = {l for l in local.labels if l.startswith(f"{axis}:")}
            peer_set = {l for l in peer.labels if l.startswith(f"{axis}:")}
            if local_set != peer_set:
                drift.append({
                    "kind": f"{axis}-labels",
                    "peer": peer.peer.full,
                    "in_local_only": sorted(local_set - peer_set),
                    "in_peer_only": sorted(peer_set - local_set),
                    "severity": "warning",
                })

        # Members drift — only when both sides are in closed mode.
        if local.members and peer.members:
            local_logins = sorted(
                m.get("github_login") for m in local.members
                if isinstance(m, dict) and m.get("github_login")
            )
            peer_logins = sorted(
                m.get("github_login") for m in peer.members
                if isinstance(m, dict) and m.get("github_login")
            )
            if local_logins != peer_logins:
                drift.append({
                    "kind": "members",
                    "peer": peer.peer.full,
                    "in_local_only": sorted(set(local_logins) - set(peer_logins)),
                    "in_peer_only": sorted(set(peer_logins) - set(local_logins)),
                    "severity": "warning",
                })

        # Milestone drift — title comparison.
        local_ms = set(local.milestones)
        peer_ms = set(peer.milestones)
        if local_ms != peer_ms:
            drift.append({
                "kind": "milestones",
                "peer": peer.peer.full,
                "in_local_only": sorted(local_ms - peer_ms),
                "in_peer_only": sorted(peer_ms - local_ms),
                "severity": "warning",
            })

    return drift


def _summary(drift: list[dict]) -> str:
    n = len(drift)
    if n == 0:
        return "0 drift findings; mesh clean."
    return f"{n} drift finding(s). Severity: warning (per DEC-022 v1)."


# ---- gh wrappers ----------------------------------------------------


def _gh_repo_view(peer: PeerSpec | None, config: dict) -> str | None:
    """Resolve `<owner>/<repo>` for the current dir (peer=None) or remote."""
    if peer is None:
        try:
            proc = gh_run(
                ["gh", "repo", "view", "--json", "nameWithOwner"],
                config,
                check=False,
            )
        except FileNotFoundError:
            return None
        if proc.returncode != 0:
            return None
        try:
            return json.loads(proc.stdout).get("nameWithOwner")
        except json.JSONDecodeError:
            return None
    return peer.full


def _gh_label_list(peer: PeerSpec | None, config: dict) -> list[str] | None:
    cmd = [
        "gh",
        "label",
        "list",
        "--limit",
        "500",
        "--json",
        "name",
    ]
    if peer is not None:
        cmd.extend(["--repo", peer.full])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    try:
        return [lbl["name"] for lbl in json.loads(proc.stdout)]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _gh_milestones(peer: PeerSpec | None, config: dict) -> list[str] | None:
    """Fetch milestone titles via gh api."""
    if peer is None:
        owner_repo = _gh_repo_view(None, config)
        if not owner_repo:
            return None
    else:
        owner_repo = peer.full
    try:
        proc = gh_run(
            [
                "gh",
                "api",
                f"repos/{owner_repo}/milestones?state=all&per_page=100",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    try:
        return [m.get("title", "") for m in json.loads(proc.stdout)]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _gh_peer_capability_version(peer: PeerSpec, config: dict) -> str | None:
    """Fetch the peer's package.yaml `version:` via gh api raw."""
    path = ".pkit/capabilities/project-management/package.yaml"
    try:
        proc = gh_run(
            [
                "gh",
                "api",
                f"repos/{peer.full}/contents/{path}",
                "--header",
                "Accept: application/vnd.github.raw+json",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    return _extract_version(proc.stdout)


def _gh_peer_members(peer: PeerSpec, config: dict) -> list[dict]:
    """Fetch the peer's members.yaml via gh api raw."""
    path = ".pkit/capabilities/project-management/project/members.yaml"
    try:
        proc = gh_run(
            [
                "gh",
                "api",
                f"repos/{peer.full}/contents/{path}",
                "--header",
                "Accept: application/vnd.github.raw+json",
            ],
            config,
            check=False,
        )
    except FileNotFoundError:
        return []
    if proc.returncode != 0:
        return []
    try:
        data = YAML(typ="safe").load(proc.stdout) or {}
    except YAMLError:
        return []
    members = data.get("members") or [] if isinstance(data, dict) else []
    return members if isinstance(members, list) else []


def _extract_version(text: str) -> str | None:
    """Best-effort extraction of `version:` from a YAML stream."""
    try:
        data = YAML(typ="safe").load(text) or {}
    except YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    comp = data.get("component")
    if isinstance(comp, dict):
        v = comp.get("version")
        if isinstance(v, str):
            return v
    return None


def _read_local_capability_version(capability_root: Path) -> str | None:
    path = capability_root / "package.yaml"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return _extract_version(text)


# ---- reporting ------------------------------------------------------


def _print_report(local: PeerState, peers: list[PeerState], drift: list[dict]) -> None:
    print(f"[check-mesh] target: {local.peer.full}")
    print(f"             peers:  {', '.join(p.peer.full for p in peers)}")
    print()
    if not drift:
        print("[ok] no drift detected across the configured mesh.")
        return
    for d in drift:
        print(f"[drift] {d['kind']} (peer: {d.get('peer')})")
        if "in_local_only" in d:
            print(f"  in target only: {', '.join(d['in_local_only']) or '—'}")
        if "in_peer_only" in d:
            print(f"  in peer only:   {', '.join(d['in_peer_only']) or '—'}")
        if "local" in d:
            print(f"  local: {d['local']}    peer: {d['peer_value']}")
        print()
    print(_summary(drift))


def _read_yaml(path: Path, yaml_loader: YAML) -> dict:
    if not path.is_file():
        return {}
    try:
        data = yaml_loader.load(path.read_text(encoding="utf-8"))
    except (OSError, YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_members(capability_root: Path, yaml_loader: YAML) -> list[dict]:
    data = _read_yaml(capability_root / "project" / "members.yaml", yaml_loader)
    members = data.get("members") or []
    return members if isinstance(members, list) else []


if __name__ == "__main__":
    sys.exit(main())
