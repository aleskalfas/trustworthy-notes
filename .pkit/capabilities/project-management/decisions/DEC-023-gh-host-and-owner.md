---
id: DEC-023
title: Adopter-pinned `gh` context — host and default owner declared in adopter config; central helper resolves every shell-out
status: accepted
date: 2026-05-27
author: Ales Kalfas
---

## Context

Every pm script shells out to the `gh` CLI for GitHub operations (project view, issue create, label list, …). Today each `subprocess.run(["gh", ...])` invocation relies on **ambient** `gh` state — the host from a `GH_HOST` env var or `gh`'s own CLI default, the owner inferred from the active repo's remote. This works for single-org public-GitHub adopters whose board lives in the same owner as the repo. Three real adoption topologies break against it:

1. **Enterprise GHE adopters.** A team on `github.com` (or any non-`github.com` host) needs `GH_HOST=github.com` exported in the calling shell for every `gh` call to land on the right host. Adopters who forget it see "repo not accessible" failures with confusing remediation hints.
2. **Cross-owner boards.** When the Projects v2 board lives at an org-level governance owner (e.g., `ai-platform-incubation`) while the repo lives elsewhere, `gh project view <id>` exits with `"owner is required when not running interactively"`. `pre-check.py:357` even self-documents the gap: *"We don't know the owner here without additional config; rely on `gh project view <id>` working with the default org."* The fallback is unreliable in cross-org topologies.
3. **Multi-context developers.** Many maintainers carry multiple `gh` contexts (work + personal + multiple enterprise hosts). The adopter's project should pin which context it uses regardless of the shell's state at invocation.

The methodology has already accepted adopter-portable configuration as the substrate ([project-management:DEC-017-prerequisites-bootstrap-migrate-discipline]) — every operation should be reproducible from `project/config.yaml` without ambient state. Ambient `gh` state is the remaining gap. DEC-020 ([project-management:DEC-020-methodology-as-executable-commands]) treats each verb-subject script as atomic and self-sufficient; today the scripts depend on shell-level invisible setup to be atomic, which violates the contract.

## Decision

`project/config.yaml` grows an optional `gh:` block with two optional fields:

```yaml
gh:
  host: github.com                    # optional; defaults to ambient (github.com)
  default_owner: ai-platform-incubation   # optional; threaded as --owner where applicable
```

Both fields are optional. Single-org public-GitHub adopters keep working with no `gh:` block at all — the field's absence is equivalent to delegating to ambient state. The pm config schema bumps to record the addition; the new field carries an `additionalProperties: false` shape but its absence is valid.

A central helper at `scripts/_lib/gh.py` exposes three functions that every pm script uses for `gh` shell-outs:

```python
def gh_env(config: dict) -> dict[str, str]:
    """env= dict to pass to subprocess.run.
    Merges GH_HOST when gh.host is configured; falls through to os.environ otherwise."""

def gh_owner_flag(config: dict) -> list[str]:
    """Returns ['--owner', '<default_owner>'] when gh.default_owner is configured, else []."""

def gh_run(args: list[str], config: dict, **kwargs) -> subprocess.CompletedProcess:
    """Convenience wrapper: subprocess.run(args, env=gh_env(config), ...). Callers splice
    gh_owner_flag(config) into args where applicable (project / org / label-cross-owner ops)."""
```

Every existing `subprocess.run(["gh", ...])` in the capability's scripts gets refactored to use the helper; new scripts use it from the start. `pre-check.py` and `bootstrap.py` gain a sub-check: when `gh.host` is set, run `gh auth status -h <host>` and fail-fast with a remediation hint pointing at `gh auth login -h <host>` if unauthenticated.

### Precedence — config wins over ambient

When both `GH_HOST` is set in the shell *and* `gh.host` is set in config, **config wins**. Adopter-portable configuration beats ambient state; explicit beats implicit. The same rule applies to any future `gh:` field.

### Scope at v1

- **Single `host` per adopter.** No per-resource map (`board_owner`, `repo_owner`, `org`). The dominant case is one owner; COR-007 promotes per-resource granularity if recurrence forces it.
- **No per-script override flags** (`--gh-host`, `--gh-owner`). The right knob lives in config; per-call overrides are deferred until recurrence justifies the surface tax.
- **No fallback to `gh`'s own `~/.config/gh/hosts.yml`.** Adopter-portability means the config block is the source of truth; reading the user's gh CLI state re-introduces ambient drift.

## Rationale

Centralising `gh` routing in a helper consumed by every script is the structural fix for ambient-state failure. The per-script-flags alternative pushes the burden onto adopters and agents, who would re-pass identical values every command; that re-creates the wrapper-shell-glue problem the verb-subject contract is built to avoid (per [project-management:DEC-020-methodology-as-executable-commands]).

Config-as-source-of-truth over inheriting `gh`'s CLI state or env vars matches the broader adopter-portability discipline ([project-management:DEC-017-prerequisites-bootstrap-migrate-discipline]). A correct `config.yaml` checked into the adopter repo should be sufficient for any team member or agent to reproduce the methodology operations; ambient state is not checked in and is not portable.

The two optional fields cover the four concrete failures seen at IGW with zero overhead for single-org public-GitHub adopters. Both fields stay optional precisely because the existing happy path is the larger cohort.

### Alternatives considered

- **Per-script `--gh-host` / `--gh-owner` flags.** Rejected as v1. Adopters and agents re-pass identical values for every command; verb-subject scripts treat `gh` as an internal implementation detail (per DEC-020), so per-call flags leak that detail outward. Per-call flags may land later if the no-override pattern hurts (COR-007).
- **Inherit from `gh`'s CLI config (`~/.config/gh/hosts.yml`).** Rejected — fragile heuristics on `gh`'s own state; doesn't solve cross-owner boards (the active repo's owner is not the board's owner); re-introduces ambient drift.
- **Separate file `project/gh-context.yaml`.** Rejected — adds a file for one small block; gh-context lifecycle is tightly coupled to sibling config (`has_projects_v2_board`, `projects_v2_board_id`) and changes rarely. A sibling config block under `gh:` is the right granularity.
- **Per-resource map (`board_owner`, `repo_owner`, `org`).** Rejected at v1. Dominant case is one owner; COR-007 promotes per-resource granularity if a second instance surfaces.
- **Read board owner from the board's own metadata.** Rejected — `gh project view <id>` is the very call that needs `--owner` to begin with; circular dependency.

## Implications

- **Schema addition.** `config.yaml`'s schema gains an optional `gh:` block with two optional fields (`host`, `default_owner`). The `schema_version` bumps; the addition is **additive-only** — existing adopters' configs validate unchanged.
- **Helper introduction at `scripts/_lib/gh.py`.** New module; every pm script imports from it. Other capabilities that grow `gh` shell-outs follow the same pattern (helper at `_lib/gh.py` within that capability) until COR-007 forces a kit-level promotion.
- **Bootstrap- and pre-check-time validation.** Both scripts run `gh auth status -h <host>` when `gh.host` is set; fail-fast with a `gh auth login -h <host>` remediation hint. This catches the wrong-host auth failure at the earliest visible seam.
- **`#177` (gh hostname detection) collapses into this DEC.** The surgical fixes scoped there (membership lib, `create-issue --milestone`, `--parent-type`) are subsumed by the helper refactor. The issue closes with the implementation PR.
- **Mesh-peer interaction ([project-management:DEC-022-methodology-mesh]).** `mesh_peers:` entries already encode per-peer `<owner>/<repo>`; cross-host meshes (one peer on `github.com`, another on `github.com`) would need per-peer `host` overrides, deferred until that case appears. At v1, mesh-check uses the same `gh.host` for every peer.
- **Migration profile.** Schema addition is additive-only and behaviour-preserving for existing adopters — rule 7's "Pure additions don't trigger migration" applies. The implementation PR ships the schema bump + helper refactor without a migration script. If a strict-schema linter catches the bump as a surface change, the migration is a no-op idempotent stamp recording the version.
- **Adopter-doc impact.** The pm capability's adopter-facing README gains a brief subsection on the `gh:` block; the IGW adopter is the demonstrating example. Per DEC-015 ("Doc-update obligations"), the doc update ships in the same PR.
- **Versioning.** Per PRJ-002 + the pm capability's bump policy, the helper introduction + adopter-visible schema field is a surface change; the implementation PR bumps the capability's version accordingly.
