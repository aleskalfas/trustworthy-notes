#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "ruamel.yaml>=0.18",
# ]
# ///
"""Project-management capability — pre-check.

Read-only diagnostic that verifies every prerequisite the methodology
depends on is in place before any pm operation runs. Compares the
adopter's GitHub state and project-side configuration against the
capability's schemas; reports every gap with a remediation hint.

Contract per the capability's DEC-017-prerequisites-bootstrap-migrate-
discipline. Programmatic, not AI-mediated; exit code is the contract.

Self-contained via PEP 723 inline metadata: run via
  uv run --script .pkit/capabilities/project-management/scripts/pre-check.py

Exit codes:
  0  every check passed or was legitimately skipped
  1  one or more checks failed
  2  usage error (script invoked outside an adopter; capability not
     installed at the expected path; config file unparseable in a way
     that blocks the script from running at all)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


CAPABILITY_NAME = "project-management"
ADOPTER_CONFIG_PATH = "project/config.yaml"
REQUIRED_ADOPTER_CONFIG_FIELDS = ("schema_version", "default_branch", "workstreams")


@dataclass(frozen=True)
class CheckResult:
    """One check's outcome."""

    label: str
    status: str  # "ok" | "fail" | "skip"
    detail: str
    remediation: str | None = None


# ----- script entry --------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify project-management capability prerequisites are in place. "
            "Exit 0 if every check passes or is legitimately skipped; "
            "non-zero on any failure."
        ),
    )
    parser.add_argument(
        "--capability-root",
        type=Path,
        default=None,
        help=(
            "Path to the installed capability's directory "
            "(default: <repo-root>/.pkit/capabilities/project-management/)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable text.",
    )
    args = parser.parse_args()

    capability_root = _resolve_capability_root(args.capability_root)
    if capability_root is None:
        print(
            "error: project-management capability not found. "
            "Run this script from within an adopter project that has the "
            "capability installed at .pkit/capabilities/project-management/.",
            file=sys.stderr,
        )
        return 2

    if not args.json:
        _print_context_header(capability_root)

    results = _run_all_checks(capability_root)

    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=2))
    else:
        _print_human(results)

    return 0 if all(r.status != "fail" for r in results) else 1


def _print_context_header(capability_root: Path) -> None:
    """Print the target repo + capability + config paths before any checks.

    Surfaces *which* repo and *which* capability install the script is
    operating on. Defensive against running the script in the wrong
    project tree (multiple checkouts open, wrong cwd, etc.).
    """
    repo = _resolve_repo_name_with_owner()
    version = _read_capability_version(capability_root)
    config_path = capability_root / ADOPTER_CONFIG_PATH

    print("pre-check: project-management capability")
    print(f"  target repo: {repo}")
    print(f"  capability:  {capability_root} (v{version})")
    print(f"  config:      {config_path}")
    print()


def _resolve_repo_name_with_owner() -> str:
    """Best-effort `<owner>/<repo>` for the current working tree.

    Returns `<unresolved>` when `gh repo view` fails — the relevant
    check downstream will surface the same failure with proper detail.
    """
    proc = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return "<unresolved>"
    try:
        return json.loads(proc.stdout).get("nameWithOwner", "<unresolved>")
    except json.JSONDecodeError:
        return "<unresolved>"


def _read_capability_version(capability_root: Path) -> str:
    """Read the capability's installed version from its package.yaml."""
    pkg = capability_root / "package.yaml"
    if not pkg.is_file():
        return "<unknown>"
    try:
        data = YAML(typ="safe").load(pkg.read_text(encoding="utf-8")) or {}
        return str(data.get("component", {}).get("version", "<unknown>"))
    except (OSError, YAMLError):
        return "<unknown>"


# ----- check orchestration -------------------------------------------


def _run_all_checks(capability_root: Path) -> list[CheckResult]:
    """Run every check in fixed order. Each check is independent."""
    results: list[CheckResult] = []

    # 1+2. Tooling on PATH (git, gh) — every other check depends on these.
    results.append(_check_command_on_path("git"))
    gh_result = _check_command_on_path("gh")
    results.append(gh_result)

    if gh_result.status == "fail":
        # Without gh, the remaining checks can't run — short-circuit.
        results.append(
            CheckResult(
                "remaining checks",
                "skip",
                "skipped — `gh` not on PATH",
            )
        )
        return results

    # 3. gh authentication.
    results.append(_check_gh_auth())

    # Adopter config — read once; needed by checks 4, 6, 7.
    config_path = capability_root / ADOPTER_CONFIG_PATH
    config, config_result = _check_adopter_config(config_path)
    results.append(config_result)

    # 3b. gh: block validation + host-pinned auth (per DEC-023).
    if config is not None:
        results.append(_check_gh_block(config))
        results.append(_check_gh_host_auth(config))

    # 4. Repo accessibility.
    results.append(_check_repo_accessible())

    # 5. Board id resolves (conditional).
    has_board = bool(config and config.get("has_projects_v2_board"))
    if has_board:
        board_id = config.get("projects_v2_board_id") if config else None
        results.append(_check_board(board_id))
    else:
        results.append(
            CheckResult(
                "Projects v2 board",
                "skip",
                "no board configured (label-fallback mode)",
            )
        )

    # 6. Required labels (classification axes + state labels in label-fallback).
    results.extend(_check_labels(capability_root, config, has_board))

    # 6b. State labels presence (label-fallback mode only).
    if not has_board:
        results.append(_check_state_labels(capability_root))

    # 7. Default branch matches config.
    results.append(_check_default_branch(config))

    # 8. workstreams.yaml parses cleanly (DEC-018; check applies even when
    #    the file is absent — that's the legitimate pre-migration state).
    results.append(_check_workstreams_file(capability_root))

    # 9. mandatory-issue-state.yaml parses cleanly (DEC-019).
    results.append(_check_mandatory_state_schema(capability_root))

    # 10. mesh_peers / mesh_source URI validation (DEC-022).
    results.append(_check_mesh_config(config))

    # 11. hooks.yaml shape + per-kind validation (DEC-024).
    results.extend(_check_hooks_file(capability_root))

    # 12. review: block validation (DEC-027 + DEC-028).
    if config is not None:
        results.extend(_check_review_block(config, capability_root))

    # 13. Title-prefix alignment (sample of open issues cross-validated
    #     against issue-types.yaml + classification.yaml prefixes).
    results.extend(_check_title_prefix_alignment(capability_root))

    return results


# ----- individual checks ---------------------------------------------


def _check_command_on_path(cmd: str) -> CheckResult:
    if shutil.which(cmd) is None:
        return CheckResult(
            f"`{cmd}` on PATH",
            "fail",
            f"`{cmd}` not found on PATH",
            remediation=(
                f"Install `{cmd}` and ensure it is invocable from the shell. "
                f"This script (and the project-manager) require it for all operations."
            ),
        )
    # Capture version for diagnostics; not part of the gate.
    try:
        proc = subprocess.run(
            [cmd, "--version"], capture_output=True, text=True, check=False
        )
        version_line = proc.stdout.strip().split("\n", maxsplit=1)[0] if proc.stdout else ""
    except OSError:
        version_line = ""
    detail = f"present" + (f" ({version_line})" if version_line else "")
    return CheckResult(f"`{cmd}` on PATH", "ok", detail)


def _check_gh_auth() -> CheckResult:
    """Verify `gh auth status` reports an authenticated host (ambient)."""
    proc = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        return CheckResult(
            "`gh` authenticated",
            "fail",
            "`gh auth status` reports no active authentication",
            remediation="Run `gh auth login` and follow the prompts.",
        )
    # First line of `gh auth status` typically names the host.
    first_line = (proc.stderr or proc.stdout).strip().split("\n", maxsplit=1)[0]
    return CheckResult("`gh` authenticated", "ok", first_line)


def _check_gh_block(config: dict[str, Any]) -> CheckResult:
    """Validate the optional `gh:` block per DEC-023.

    Shape rules:
    - The block is optional; if absent or `null`, the check passes (skipped).
    - When present, it must be a YAML mapping.
    - Allowed keys: `host`, `default_owner`. Both optional.
    - Each declared value must be a non-empty string.
    - Extra keys are flagged (`additionalProperties: false` per DEC-023).
    """
    raw = config.get("gh")
    if raw is None:
        return CheckResult(
            "`gh:` config block",
            "skip",
            "no `gh:` block configured (using ambient `gh` state)",
        )
    if not isinstance(raw, dict):
        return CheckResult(
            "`gh:` config block valid",
            "fail",
            "`gh:` is present but not a mapping",
            remediation=(
                "Make `gh:` a YAML mapping with optional `host:` and "
                "`default_owner:` string fields, or remove it entirely "
                "to delegate to ambient state. See DEC-023."
            ),
        )

    allowed = {"host", "default_owner"}
    extras = sorted(set(raw.keys()) - allowed)
    if extras:
        return CheckResult(
            "`gh:` config block valid",
            "fail",
            f"unknown key(s) under `gh:`: {', '.join(extras)}",
            remediation=(
                "Remove the unknown keys. DEC-023 allows only `host:` and "
                "`default_owner:` under `gh:` at v1; per-resource granularity "
                "is deferred to a future record."
            ),
        )

    for field in ("host", "default_owner"):
        value = raw.get(field)
        if value is None:
            continue  # absent is fine
        if not isinstance(value, str) or not value:
            return CheckResult(
                "`gh:` config block valid",
                "fail",
                f"`gh.{field}` must be a non-empty string when set; got {value!r}",
                remediation=(
                    f"Either remove `{field}:` from `gh:` or set it to a "
                    "non-empty string."
                ),
            )

    summary_parts: list[str] = []
    if raw.get("host"):
        summary_parts.append(f"host={raw['host']}")
    if raw.get("default_owner"):
        summary_parts.append(f"default_owner={raw['default_owner']}")
    summary = ", ".join(summary_parts) if summary_parts else "empty block (no overrides)"
    return CheckResult("`gh:` config block valid", "ok", summary)


def _check_gh_host_auth(config: dict[str, Any]) -> CheckResult:
    """When `gh.host` is set, verify `gh auth status -h <host>` succeeds.

    Per DEC-023's adopter-portability discipline: a correct `config.yaml`
    should be enough for any team member or agent to reach the configured
    host. If `gh` isn't authenticated against the configured host, the
    pre-check fails early with a remediation pointing at `gh auth login`.
    """
    host = (config.get("gh") or {}).get("host") if isinstance(config.get("gh"), dict) else None
    if not isinstance(host, str) or not host:
        return CheckResult(
            "`gh` authenticated against configured host",
            "skip",
            "no `gh.host` configured",
        )
    proc = subprocess.run(
        ["gh", "auth", "status", "-h", host],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return CheckResult(
            "`gh` authenticated against configured host",
            "fail",
            f"`gh auth status -h {host}` reports no active authentication",
            remediation=(
                f"Run `gh auth login -h {host}` and follow the prompts. "
                "DEC-023 requires the adopter's configured host to be "
                "authenticated locally."
            ),
        )
    return CheckResult(
        "`gh` authenticated against configured host", "ok", f"host={host}"
    )


def _check_adopter_config(
    path: Path,
) -> tuple[dict[str, Any] | None, CheckResult]:
    if not path.is_file():
        return None, CheckResult(
            "adopter config present",
            "fail",
            f"missing at {path}",
            remediation=(
                "Author a project-side config at "
                "`.pkit/capabilities/project-management/project/config.yaml` "
                "declaring at minimum: schema_version, default_branch, "
                "workstreams, has_projects_v2_board. See the capability "
                "README's 'Adopter setup' section."
            ),
        )
    try:
        text = path.read_text(encoding="utf-8")
        data = YAML(typ="safe").load(text) or {}
    except (OSError, YAMLError) as exc:
        return None, CheckResult(
            "adopter config parses",
            "fail",
            f"failed to read/parse {path}: {exc}",
            remediation="Fix YAML syntax; re-run.",
        )
    if not isinstance(data, dict):
        return None, CheckResult(
            "adopter config parses",
            "fail",
            f"{path} top-level is not a mapping",
            remediation="The config must be a YAML mapping at the top level.",
        )
    missing = [f for f in REQUIRED_ADOPTER_CONFIG_FIELDS if f not in data]
    if missing:
        return data, CheckResult(
            "adopter config has required fields",
            "fail",
            f"missing fields in {path}: {', '.join(missing)}",
            remediation=(
                "Add the missing fields. See DEC-017 for the expected shape; "
                "the capability README documents each field."
            ),
        )
    return data, CheckResult(
        "adopter config present + valid",
        "ok",
        f"{path} parses; required fields present",
    )


def _check_repo_accessible() -> CheckResult:
    proc = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return CheckResult(
            "repo accessible",
            "fail",
            "`gh repo view` failed",
            remediation=(
                "Run the script from within a GitHub repo checkout, and "
                "ensure `gh` is authenticated against the host that owns it."
            ),
        )
    try:
        data = json.loads(proc.stdout)
        name = data.get("nameWithOwner", "<unknown>")
    except json.JSONDecodeError:
        name = "<unknown>"
    return CheckResult("repo accessible", "ok", name)


def _check_board(board_id: int | str | None) -> CheckResult:
    if board_id is None:
        return CheckResult(
            "Projects v2 board id",
            "fail",
            "config declares has_projects_v2_board: true but no projects_v2_board_id",
            remediation=(
                "Set `projects_v2_board_id: <N>` in the config, where <N> is "
                "the board number from `gh project list`."
            ),
        )
    # `gh project view` accepts the board number and a --owner.
    # We don't know the owner here without additional config; rely on
    # `gh project view <id>` working with the default org.
    proc = subprocess.run(
        ["gh", "project", "view", str(board_id), "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return CheckResult(
            "Projects v2 board",
            "fail",
            f"`gh project view {board_id}` failed",
            remediation=(
                "Verify the board id with `gh project list --owner <org>`. "
                "Update `projects_v2_board_id` in the config if it has moved."
            ),
        )
    return CheckResult("Projects v2 board", "ok", f"board #{board_id} resolves")


def _check_labels(
    capability_root: Path,
    config: dict[str, Any] | None,
    has_board: bool,
) -> list[CheckResult]:
    """Verify the methodology's required labels exist on the repo."""
    results: list[CheckResult] = []

    # Read classification.yaml for the type / priority axes.
    classification_path = capability_root / "schemas" / "classification.yaml"
    try:
        classification = YAML(typ="safe").load(classification_path.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError) as exc:
        results.append(
            CheckResult(
                "classification.yaml readable",
                "fail",
                f"failed to read {classification_path}: {exc}",
                remediation="The capability install may be corrupt; re-install.",
            )
        )
        return results

    # Fetch existing labels once.
    proc = subprocess.run(
        ["gh", "label", "list", "--limit", "500", "--json", "name"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        results.append(
            CheckResult(
                "label list accessible",
                "fail",
                "`gh label list` failed",
                remediation="Ensure `gh` is authenticated and the repo is accessible.",
            )
        )
        return results
    try:
        existing = {label["name"] for label in json.loads(proc.stdout)}
    except (json.JSONDecodeError, KeyError, TypeError):
        existing = set()

    # Required labels: type:* always (type is always-as-label).
    type_values = (
        classification.get("axes", {}).get("type", {}).get("values", [])
    )
    missing_type = [v for v in type_values if f"type:{v}" not in existing]
    if missing_type:
        results.append(
            CheckResult(
                "required `type:*` labels exist",
                "fail",
                f"missing: {', '.join('type:' + v for v in missing_type)}",
                remediation="Run `bootstrap` to create the missing labels.",
            )
        )
    else:
        results.append(
            CheckResult(
                "required `type:*` labels exist",
                "ok",
                f"all {len(type_values)} labels present",
            )
        )

    # In label-fallback mode, also check priority:* and workstream:*.
    if has_board:
        results.append(
            CheckResult(
                "`priority:*` / `workstream:*` labels",
                "skip",
                "board configured — priority/workstream live as board fields",
            )
        )
    else:
        priority_values = (
            classification.get("axes", {}).get("priority", {}).get("values", [])
        )
        missing_priority = [
            v for v in priority_values if f"priority:{v}" not in existing
        ]
        if missing_priority:
            results.append(
                CheckResult(
                    "required `priority:*` labels exist",
                    "fail",
                    f"missing: {', '.join('priority:' + v for v in missing_priority)}",
                    remediation="Run `bootstrap` to create the missing labels.",
                )
            )
        else:
            results.append(
                CheckResult(
                    "required `priority:*` labels exist",
                    "ok",
                    f"all {len(priority_values)} labels present",
                )
            )

        workstreams = _resolve_workstream_slugs_for_check(capability_root, config or {})
        missing_workstream = [
            w for w in workstreams if f"workstream:{w}" not in existing
        ]
        if missing_workstream:
            results.append(
                CheckResult(
                    "required `workstream:*` labels exist",
                    "fail",
                    f"missing: {', '.join('workstream:' + w for w in missing_workstream)}",
                    remediation="Run `bootstrap` to create the missing labels.",
                )
            )
        elif workstreams:
            results.append(
                CheckResult(
                    "required `workstream:*` labels exist",
                    "ok",
                    f"all {len(workstreams)} labels present",
                )
            )
        else:
            results.append(
                CheckResult(
                    "`workstream:*` labels",
                    "skip",
                    "no workstreams declared in adopter config",
                )
            )

    return results


def _resolve_workstream_slugs_for_check(
    capability_root: Path, config: dict[str, Any]
) -> list[str]:
    """Read workstream slugs from workstreams.yaml or config legacy fallback."""
    ws_path = capability_root / "project" / "workstreams.yaml"
    if ws_path.is_file():
        try:
            data = YAML(typ="safe").load(ws_path.read_text(encoding="utf-8")) or {}
        except (OSError, YAMLError):
            data = {}
        ws = data.get("workstreams") if isinstance(data, dict) else None
        if isinstance(ws, list):
            return [s for s in ws if isinstance(s, str)]
        if isinstance(ws, dict):
            return [
                s
                for s, attrs in ws.items()
                if isinstance(s, str)
                and (not isinstance(attrs, dict) or attrs.get("status", "active") == "active")
            ]
        return []
    legacy = config.get("workstreams") or []
    if isinstance(legacy, list):
        return [s for s in legacy if isinstance(s, str)]
    return []


def _check_mesh_config(config: dict[str, Any] | None) -> CheckResult:
    """Validate `mesh_peers` / `mesh_source` URI shapes per DEC-022.

    Both fields are optional; absence is a clean skip. When set, each
    URI must match `github://owner/repo[/path]`.
    """
    import re as _re

    if config is None:
        return CheckResult(
            "mesh config", "skip", "adopter config not loaded"
        )
    mp = config.get("mesh_peers")
    ms = config.get("mesh_source")
    if mp is None and ms is None:
        return CheckResult(
            "mesh config",
            "skip",
            "no mesh_peers / mesh_source set (single-repo adopter)",
        )
    pattern = _re.compile(r"^github://[^/]+/[^/]+(/.*)?$")
    invalid: list[str] = []
    if mp is not None:
        if not isinstance(mp, list):
            return CheckResult(
                "mesh_peers shape",
                "fail",
                f"`mesh_peers` must be a list of github:// URIs; got {type(mp).__name__}",
                remediation="See DEC-022 for the expected shape.",
            )
        for uri in mp:
            if not isinstance(uri, str) or not pattern.match(uri):
                invalid.append(str(uri))
    if ms is not None:
        if not isinstance(ms, str) or not pattern.match(ms):
            invalid.append(str(ms))
    if invalid:
        return CheckResult(
            "mesh config URIs",
            "fail",
            f"invalid URI(s): {', '.join(invalid)}",
            remediation="URIs must match `github://<owner>/<repo>[/path]`.",
        )
    count = (len(mp) if isinstance(mp, list) else 0) + (1 if ms is not None else 0)
    return CheckResult("mesh config URIs", "ok", f"{count} URI(s) valid")


def _check_mandatory_state_schema(capability_root: Path) -> CheckResult:
    """Validate `schemas/mandatory-issue-state.yaml` parses cleanly (per DEC-019)."""
    path = capability_root / "schemas" / "mandatory-issue-state.yaml"
    if not path.is_file():
        return CheckResult(
            "mandatory-issue-state.yaml",
            "fail",
            f"missing at {path}",
            remediation="The capability install may be corrupt; re-install.",
        )
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError) as exc:
        return CheckResult(
            "mandatory-issue-state.yaml parses",
            "fail",
            f"failed to read {path}: {exc}",
            remediation="The capability install may be corrupt; re-install.",
        )
    if not isinstance(data, dict) or "required_fields" not in data:
        return CheckResult(
            "mandatory-issue-state.yaml shape",
            "fail",
            f"{path} missing `required_fields` map",
            remediation="The capability install may be corrupt; re-install.",
        )
    n = len(data.get("required_fields") or {})
    return CheckResult(
        "mandatory-issue-state.yaml present + valid",
        "ok",
        f"{path} parses; {n} required field(s) declared",
    )


def _check_workstreams_file(capability_root: Path) -> CheckResult:
    """Validate `project/workstreams.yaml` parses cleanly (per DEC-018).

    Absence is OK during the transition — the legacy `config.yaml`
    fallback covers that case. When present, the file must parse to a
    mapping with `schema_version` + `workstreams:` (list or mapping).
    """
    path = capability_root / "project" / "workstreams.yaml"
    if not path.is_file():
        return CheckResult(
            "workstreams.yaml",
            "skip",
            f"absent at {path} — legacy config.yaml fallback in effect",
        )
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError) as exc:
        return CheckResult(
            "workstreams.yaml parses",
            "fail",
            f"failed to read/parse {path}: {exc}",
            remediation="Fix YAML syntax; re-run.",
        )
    if not isinstance(data, dict):
        return CheckResult(
            "workstreams.yaml parses",
            "fail",
            f"{path} top-level is not a mapping",
            remediation="The file must be a YAML mapping at the top level.",
        )
    if "schema_version" not in data:
        return CheckResult(
            "workstreams.yaml has schema_version",
            "fail",
            f"{path} missing `schema_version` field",
            remediation="Add `schema_version: 1` at the top of the file.",
        )
    if "workstreams" not in data:
        return CheckResult(
            "workstreams.yaml has workstreams field",
            "fail",
            f"{path} missing `workstreams` field",
            remediation="Add `workstreams: ...` (list or mapping) per DEC-018.",
        )
    ws = data["workstreams"]
    if not isinstance(ws, (list, dict)):
        return CheckResult(
            "workstreams.yaml shape",
            "fail",
            f"`workstreams` must be a list or mapping; got {type(ws).__name__}",
            remediation="See DEC-018 for the two accepted forms.",
        )
    count = len(ws)
    return CheckResult(
        "workstreams.yaml present + valid",
        "ok",
        f"{path} parses; {count} entry(ies)",
    )


def _check_default_branch(config: dict[str, Any] | None) -> CheckResult:
    if config is None:
        return CheckResult(
            "default branch matches config",
            "skip",
            "adopter config not loaded",
        )
    declared = config.get("default_branch")
    if not declared:
        return CheckResult(
            "default branch matches config",
            "fail",
            "config does not declare `default_branch`",
            remediation="Add `default_branch: main` (or your project's default) to the config.",
        )
    proc = subprocess.run(
        ["gh", "repo", "view", "--json", "defaultBranchRef"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return CheckResult(
            "default branch matches config",
            "fail",
            "`gh repo view` failed",
        )
    try:
        actual = json.loads(proc.stdout).get("defaultBranchRef", {}).get("name", "")
    except json.JSONDecodeError:
        actual = ""
    if actual != declared:
        return CheckResult(
            "default branch matches config",
            "fail",
            f"config declares `{declared}`; repo's default is `{actual}`",
            remediation=(
                "Update the config's `default_branch` to match the repo's "
                "default, or update the repo settings."
            ),
        )
    return CheckResult("default branch matches config", "ok", f"`{declared}`")


# ----- output --------------------------------------------------------


def _print_human(results: list[CheckResult]) -> None:
    for r in results:
        marker = {"ok": "[ok]  ", "fail": "[fail]", "skip": "[skip]"}[r.status]
        print(f"  {marker} {r.label}")
        if r.status == "fail":
            print(f"         → {r.detail}")
            if r.remediation:
                print(f"         → {r.remediation}")
        elif r.status == "skip":
            print(f"         {r.detail}")
        else:
            print(f"         {r.detail}")
    print()
    fails = sum(1 for r in results if r.status == "fail")
    oks = sum(1 for r in results if r.status == "ok")
    skips = sum(1 for r in results if r.status == "skip")
    summary = f"{fails} fail(s), {skips} skip, {oks} ok"
    if fails:
        print(f"{summary} — pre-check FAILED. Refusing to proceed.")
    else:
        print(f"{summary} — pre-check passed.")


# ----- state labels check (label-fallback mode) -----------------------


def _check_state_labels(capability_root: Path) -> CheckResult:
    """Verify all lifecycle state:* labels exist on the repo.

    Only relevant in label-fallback mode (has_projects_v2_board: false).
    Reads the canonical state IDs from workflow.yaml and checks each
    state:<id> label is present on the remote. Reports [fail] with a
    remediation pointer to `bootstrap` when any are missing.
    """
    workflow_path = capability_root / "schemas" / "workflow.yaml"
    try:
        wf_data = YAML(typ="safe").load(workflow_path.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError) as exc:
        return CheckResult(
            "workflow.yaml readable for state-label check",
            "fail",
            f"failed to read {workflow_path}: {exc}",
            remediation="The capability install may be corrupt; re-install.",
        )

    states = wf_data.get("states") or []
    state_ids = [
        str(s["id"])
        for s in states
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    ]
    if not state_ids:
        return CheckResult(
            "state:* labels check",
            "skip",
            "workflow.yaml declares no states (unexpected; capability may be corrupt)",
        )

    # Fetch existing labels.
    proc = subprocess.run(
        ["gh", "label", "list", "--limit", "500", "--json", "name"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return CheckResult(
            "state:* labels (label-fallback)",
            "fail",
            "`gh label list` failed",
            remediation="Ensure `gh` is authenticated and the repo is accessible.",
        )
    try:
        existing = {label["name"] for label in json.loads(proc.stdout)}
    except (json.JSONDecodeError, KeyError, TypeError):
        existing = set()

    missing = [sid for sid in state_ids if f"state:{sid}" not in existing]
    if missing:
        return CheckResult(
            "required `state:*` labels exist (label-fallback)",
            "fail",
            f"missing: {', '.join('state:' + s for s in missing)}",
            remediation=(
                "Run `pkit project-management bootstrap` to create the missing "
                "state labels. These are the substrate for the move-issue state "
                "machine in label-fallback mode."
            ),
        )
    return CheckResult(
        "required `state:*` labels exist (label-fallback)",
        "ok",
        f"all {len(state_ids)} state labels present",
    )


# ----- title-prefix alignment check ----------------------------------

# Sample limit: scanning too many issues in pre-check is slow and noisy.
_TITLE_PREFIX_SAMPLE_LIMIT = 50


def _check_title_prefix_alignment(capability_root: Path) -> list[CheckResult]:
    """Cross-validate open issue titles against known prefix vocabularies.

    Reads issue-types.yaml and classification.yaml to build the full set
    of recognised prefixes, then samples up to _TITLE_PREFIX_SAMPLE_LIMIT
    open issues and flags any whose title prefix is unrecognised. Surfaces
    mismatches as warnings (not hard-rejects) since historical drift is
    expected.
    """
    # Build the known-prefix set.
    issue_types_path = capability_root / "schemas" / "issue-types.yaml"
    classification_path = capability_root / "schemas" / "classification.yaml"

    known_prefixes: set[str] = set()
    try:
        it_data = YAML(typ="safe").load(issue_types_path.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError):
        it_data = {}

    types = it_data.get("types") or {}
    for entry in types.values():
        if not isinstance(entry, dict):
            continue
        prefix = entry.get("title_prefix", "")
        case = entry.get("title_case", "title")
        rendered = str(prefix).upper() if case == "upper" else str(prefix)
        if rendered:
            known_prefixes.add(rendered)

    try:
        cls_data = YAML(typ="safe").load(classification_path.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError):
        cls_data = {}

    prefix_by_value = (
        cls_data.get("axes", {}).get("type", {}).get("title_prefix_by_value", {})
    )
    for kind_prefix in prefix_by_value.values():
        if isinstance(kind_prefix, str) and kind_prefix:
            known_prefixes.add(kind_prefix)

    if not known_prefixes:
        return [CheckResult(
            "title-prefix alignment",
            "skip",
            "could not load schemas (issue-types.yaml / classification.yaml)",
        )]

    # Fetch a sample of open issues.
    proc = subprocess.run(
        [
            "gh", "issue", "list",
            "--state", "open",
            "--limit", str(_TITLE_PREFIX_SAMPLE_LIMIT),
            "--json", "number,title",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return [CheckResult(
            "title-prefix alignment",
            "skip",
            "`gh issue list` failed; skipping alignment check",
        )]

    try:
        issues = json.loads(proc.stdout)
    except json.JSONDecodeError:
        issues = []

    if not issues:
        return [CheckResult(
            "title-prefix alignment",
            "skip",
            "no open issues to sample",
        )]

    import re as _re
    bracket_re = _re.compile(r"^\[([^\]]+)\] ")
    mismatches: list[str] = []
    no_prefix: list[int] = []
    for issue in issues:
        title = str(issue.get("title", ""))
        number = issue.get("number", "?")
        m = bracket_re.match(title)
        if not m:
            no_prefix.append(number)
            continue
        prefix = m.group(1)
        if prefix not in known_prefixes:
            mismatches.append(f"#{number} [{prefix}]")

    results: list[CheckResult] = []
    sampled = len(issues)

    if mismatches:
        results.append(CheckResult(
            "title-prefix alignment",
            "fail",
            (
                f"{len(mismatches)} issue(s) in sample of {sampled} have unrecognised "
                f"prefix: {', '.join(mismatches)}"
            ),
            remediation=(
                "Update the issue titles or the prefix vocabulary in "
                "issue-types.yaml / classification.yaml. Known prefixes: "
                + ", ".join(f"[{p}]" for p in sorted(known_prefixes)) + "."
            ),
        ))
    else:
        results.append(CheckResult(
            "title-prefix alignment",
            "ok",
            f"all {sampled} sampled open issue(s) have recognised prefixes",
        ))

    if no_prefix:
        results.append(CheckResult(
            "title-prefix: issues without bracket prefix",
            "fail",
            (
                f"{len(no_prefix)} issue(s) in sample have no `[Prefix] ` title: "
                f"{', '.join(f'#{n}' for n in no_prefix[:10])}"
                + (" ..." if len(no_prefix) > 10 else "")
            ),
            remediation=(
                "Issue titles must start with a `[Prefix] ` bracket per the "
                "methodology's title format rules. Use edit-issue or the "
                "project-manager to fix the titles."
            ),
        ))

    return results


# ----- hooks.yaml validation (DEC-024) --------------------------------


HOOKS_FILE_PATH = "project/hooks.yaml"
HOOK_KIT_KINDS: tuple[str, ...] = (
    "set-board-field",
    "post-comment",
    "assign-milestone",
    "custom-script",
)
HOOK_LIFECYCLE_EVENTS: tuple[str, ...] = (
    "after_create_issue",
    "after_close_issue",
    "after_open_pr",
    "after_merge_pr",
    "after_move_issue",
)


def _check_hooks_file(capability_root: Path) -> list[CheckResult]:
    """Validate `project/hooks.yaml` per DEC-024.

    Returns a list (always at least one entry) so missing / parse-only
    cases get a clear skip line, and shape errors get one finding per
    failed check.
    """
    path = capability_root / HOOKS_FILE_PATH
    if not path.is_file():
        return [CheckResult(
            "hooks.yaml present",
            "skip",
            "no hooks.yaml configured (no lifecycle hooks declared)",
        )]
    try:
        text = path.read_text(encoding="utf-8")
        data = YAML(typ="safe").load(text) or {}
    except (OSError, YAMLError) as exc:
        return [CheckResult(
            "hooks.yaml parses",
            "fail",
            f"failed to read/parse {path}: {exc}",
            remediation="Fix YAML syntax; re-run.",
        )]
    if not isinstance(data, dict):
        return [CheckResult(
            "hooks.yaml shape",
            "fail",
            f"{path} top-level is not a mapping",
            remediation="The file must be a YAML mapping at the top level.",
        )]
    if data.get("schema_version") != 1:
        return [CheckResult(
            "hooks.yaml schema_version",
            "fail",
            f"{path} missing or unexpected `schema_version` (need 1)",
            remediation="Add `schema_version: 1` at the top of the file.",
        )]
    hooks = data.get("hooks")
    if hooks is None:
        return [CheckResult(
            "hooks.yaml present + valid",
            "ok",
            f"{path} parses; no hooks declared",
        )]
    if not isinstance(hooks, dict):
        return [CheckResult(
            "hooks.yaml shape",
            "fail",
            f"`hooks:` must be a mapping; got {type(hooks).__name__}",
            remediation="Use `hooks:` as a mapping of event-name → list of hook entries.",
        )]

    results: list[CheckResult] = []
    total_entries = 0
    for event, entries in hooks.items():
        if event not in HOOK_LIFECYCLE_EVENTS:
            results.append(CheckResult(
                f"hooks.{event}",
                "fail",
                f"unknown lifecycle event {event!r}",
                remediation=f"Allowed events: {', '.join(HOOK_LIFECYCLE_EVENTS)}.",
            ))
            continue
        if not isinstance(entries, list):
            results.append(CheckResult(
                f"hooks.{event}",
                "fail",
                f"`{event}` must be a list; got {type(entries).__name__}",
                remediation="Each event maps to a YAML list of hook entries.",
            ))
            continue
        for idx, entry in enumerate(entries):
            entry_result = _validate_hook_entry(event, idx, entry)
            results.append(entry_result)
            if entry_result.status != "fail":
                total_entries += 1

    if not results:
        results.append(CheckResult(
            "hooks.yaml present + valid",
            "ok",
            f"{path} parses; no hook entries declared",
        ))
    else:
        # If every result is ok, prepend a summary line.
        if all(r.status == "ok" for r in results):
            results.insert(0, CheckResult(
                "hooks.yaml present + valid",
                "ok",
                f"{total_entries} hook entry(ies) across {len(hooks)} event(s)",
            ))
    return results


def _validate_hook_entry(event: str, idx: int, entry: Any) -> CheckResult:
    label = f"hooks.{event}[{idx}]"
    if not isinstance(entry, dict):
        return CheckResult(
            label,
            "fail",
            f"entry must be a mapping; got {type(entry).__name__}",
            remediation="Each hook entry is a YAML mapping with at minimum `kind:`.",
        )
    kind = entry.get("kind")
    if not isinstance(kind, str) or not kind:
        return CheckResult(
            label,
            "fail",
            "entry missing or empty `kind`",
            remediation=f"Set `kind:` to one of: {', '.join(HOOK_KIT_KINDS)}.",
        )
    if kind not in HOOK_KIT_KINDS:
        return CheckResult(
            label,
            "fail",
            f"unknown kind {kind!r}",
            remediation=(
                f"Known kinds at v1: {', '.join(HOOK_KIT_KINDS)}. "
                "Custom behaviour goes through `kind: custom-script` per DEC-024."
            ),
        )
    # Per-kind required-fields check (lightweight; full JSON-schema
    # validation lives in the engine at fire-time as a safety net).
    if kind == "set-board-field":
        if not entry.get("field_id"):
            return CheckResult(label, "fail", "missing `field_id`")
        if not (entry.get("single_select_option_id") or entry.get("text_value")):
            return CheckResult(
                label, "fail",
                "set-board-field requires `single_select_option_id` or `text_value`"
            )
    elif kind == "post-comment":
        tp = entry.get("template_path")
        if not isinstance(tp, str) or not tp.startswith("project/"):
            return CheckResult(
                label, "fail",
                "post-comment `template_path` must be a path under `project/`",
            )
    elif kind == "assign-milestone":
        if not entry.get("title"):
            return CheckResult(label, "fail", "assign-milestone missing `title`")
    elif kind == "custom-script":
        sp = entry.get("script_path")
        if not isinstance(sp, str) or not sp.startswith("project/"):
            return CheckResult(
                label, "fail",
                "custom-script `script_path` must be a path under `project/`",
            )
    return CheckResult(label, "ok", f"kind={kind}")


# ----- path resolution -----------------------------------------------


def _resolve_capability_root(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_dir() else None
    # Walk up from CWD looking for .pkit/capabilities/project-management.
    cur = Path.cwd()
    while cur != cur.parent:
        candidate = cur / ".pkit" / "capabilities" / CAPABILITY_NAME
        if candidate.is_dir():
            return candidate
        cur = cur.parent
    return None


# ----- review: block validation (DEC-027 + DEC-028) ------------------


def _check_review_block(
    config: dict[str, Any], capability_root: Path
) -> list[CheckResult]:
    """Validate the optional `review:` block.

    DEC-027 fields: review.mode (agent|human), review.human_review.reviewer_role.
    DEC-028 fields: review.agents.remote_registered, review.agents.local_registered.
    """
    review = config.get("review")
    if review is None:
        return [CheckResult(
            "review: block",
            "skip",
            "no `review:` block configured (defaults: mode=agent, no agents registered)",
        )]
    if not isinstance(review, dict):
        return [CheckResult(
            "review: block valid",
            "fail",
            "`review:` is present but not a mapping",
            remediation="Make `review:` a YAML mapping. See DEC-027 / DEC-028.",
        )]

    results: list[CheckResult] = []

    # DEC-027: mode + human_review.reviewer_role.
    mode = review.get("mode")
    if mode is not None and mode not in ("agent", "human"):
        results.append(CheckResult(
            "review.mode valid",
            "fail",
            f"`review.mode` must be 'agent' or 'human'; got {mode!r}",
        ))
    elif mode in ("agent", "human"):
        results.append(CheckResult("review.mode", "ok", f"mode={mode}"))

    human_review = review.get("human_review")
    if human_review is not None:
        if not isinstance(human_review, dict):
            results.append(CheckResult(
                "review.human_review valid",
                "fail",
                "`review.human_review` must be a mapping",
            ))
        else:
            role = human_review.get("reviewer_role")
            if role is not None and (not isinstance(role, str) or not role):
                results.append(CheckResult(
                    "review.human_review.reviewer_role valid",
                    "fail",
                    "`reviewer_role` must be a non-empty string when set",
                ))

    # DEC-028: agents block.
    agents = review.get("agents")
    if agents is not None:
        if not isinstance(agents, dict):
            results.append(CheckResult(
                "review.agents valid",
                "fail",
                "`review.agents` must be a mapping",
            ))
        else:
            for path in ("remote_registered", "local_registered"):
                entries = agents.get(path)
                if entries is None:
                    continue
                if not isinstance(entries, list):
                    results.append(CheckResult(
                        f"review.agents.{path} valid",
                        "fail",
                        f"`review.agents.{path}` must be a list",
                    ))
                    continue
                # Singleton-per-path at v1.
                if len(entries) > 1:
                    results.append(CheckResult(
                        f"review.agents.{path} singleton",
                        "fail",
                        f"v1 supports at most one entry per path; got {len(entries)}",
                        remediation=(
                            "Multi-agent pipelines defer per COR-007; "
                            f"keep at most one entry in `{path}` at v1."
                        ),
                    ))
                    continue
                if not entries:
                    continue
                entry = entries[0]
                if not isinstance(entry, dict):
                    results.append(CheckResult(
                        f"review.agents.{path}[0] shape",
                        "fail",
                        "entry must be a mapping",
                    ))
                    continue
                # Per-path field check.
                if path == "remote_registered":
                    login = entry.get("github_login")
                    if not isinstance(login, str) or not login:
                        results.append(CheckResult(
                            f"review.agents.{path}[0].github_login",
                            "fail",
                            "`github_login` must be a non-empty string",
                        ))
                    else:
                        results.append(CheckResult(
                            f"review.agents.{path}", "ok",
                            f"github_login={login}",
                        ))
                else:  # local_registered
                    name = entry.get("name")
                    if not isinstance(name, str) or not name:
                        results.append(CheckResult(
                            f"review.agents.{path}[0].name",
                            "fail",
                            "`name` must be a non-empty string",
                        ))
                    else:
                        # Verify the agent file exists in .claude/agents/.
                        # Walk up from capability_root to find the repo root.
                        repo_root = capability_root.parent.parent.parent
                        agent_file = repo_root / ".claude" / "agents" / f"{name}.md"
                        if agent_file.is_file():
                            results.append(CheckResult(
                                f"review.agents.{path}", "ok",
                                f"name={name} (agent file found)",
                            ))
                        else:
                            results.append(CheckResult(
                                f"review.agents.{path}.{name} file present",
                                "fail",
                                f"agent file not found at {agent_file}",
                                remediation=(
                                    f"Either remove `{name}` from `{path}` or "
                                    f"deploy the agent at `.claude/agents/{name}.md`."
                                ),
                            ))

    if not results:
        results.append(CheckResult(
            "review: block valid", "ok", "review block parses cleanly (empty)",
        ))
    return results


if __name__ == "__main__":
    sys.exit(main())
