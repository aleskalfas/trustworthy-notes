---
id: DEC-020
title: Methodology as executable commands — verb-subject scripts thin skills to routers; schemas + commands carry the rules
status: accepted
date: 2026-05-24
author: Ales Kalfas
---

## Context

The capability today (v0.2.0, per [project-management:DEC-017-prerequisites-bootstrap-migrate-discipline]) ships eight schemas, the `pm` composite skill, three prerequisite/setup/migrate scripts, and the `project-manager`. Every operation runs as **skill prose the LLM interprets**: the dispatcher loads schemas, the sub-procedure (create-issue / validate-body / transition-state) walks the operation in Markdown, and the LLM produces `gh` calls from the walkthrough. Three forces pull this apart:

1. **Interpretation is the gap.** Every methodology rule the skill states is a rule the LLM may paraphrase, misread, or skip. The schemas are deterministic; the LLM's reading of them isn't. Each operation re-derives the rules from prose every time it runs.
2. **Three scripts already exist that don't have this property.** `pre-check.py`, `bootstrap.py`, and `migrate.py` (per DEC-017) read schemas, execute deterministically, exit with structured codes, and are line-by-line auditable. They are the proof-of-concept for "methodology in commands, not in prose."
3. **The operation set is growing.** The four sibling design walks (workstream-management, mandatory-issue-state, methodology-mesh, team-membership) all add operations that mutate external state. Encoding each new operation as a new sub-procedure of the composite skill compounds the interpretation gap; encoding them as new commands containerises it.

The discriminator from COR-006 (artifact roles) cleanly separates *deterministic-and-auditable* (script) from *interpretation-required* (skill / prose). Filing an issue against the body shape, transitioning a state through the cascade, adding a member to `members.yaml`, checking a peer repo's labels — all are deterministic. Picking which of those to run for the user's free-text intent ("file a bug under the auth EPIC") is interpretation. The shift this DEC pins is **commands carry deterministic enforcement; skills thin to intent-to-command routers; schemas remain the source of truth both read**.

## Decision

The capability ships its methodology as a set of **verb-subject scripts** under `scripts/`, one per CLI operation. Skills under `skills/pm/` thin to routers — each sub-procedure recognises a user intent, picks a script, invokes it, and surfaces its output. The schemas remain authoritative; both layers read them.

### Naming: verb-subject

Every CLI operation is named **`<verb> <subject>`** — verb-first, the subject describes what's affected. The verb is the user-facing action; the subject is the methodology entity the action targets. The form is self-descriptive to a non-methodology-expert: `create issue`, `move issue`, `open pr`, `add workstream`, `add member`, `check mesh`.

### One script per CLI operation; filename is the canonical invocation

For each `<verb> <subject>` operation, the capability ships `scripts/<verb>-<subject>.py`. No dispatcher reordering; no entity-vs-verb confusion at the filesystem level; the filename IS the canonical CLI form.

```
create issue        →   scripts/create-issue.py
move issue          →   scripts/move-issue.py
open pr             →   scripts/open-pr.py
add workstream      →   scripts/add-workstream.py
add member          →   scripts/add-member.py
check mesh          →   scripts/check-mesh.py
```

All scripts inherit the DEC-017 discipline: PEP 723 self-contained Python, schema-driven, deterministic, auditable, exit codes are the contract, `--dry-run` + `--yes` flags per the safety convention, context header at startup naming target repo + capability + version + config paths.

### Operations the capability commits to

The verb-subject set the capability ships across its versioned rollout:

| Domain | Verbs (subject = `issue`, `pr`, `workstream`, `member`, `mesh`) |
|---|---|
| Issue ops | `create`, `move`, `close`, `reopen`, `validate`, `edit`, `assign`, `show` |
| PR ops | `open`, `merge`, `close`, `reopen`, `validate`, `edit`, `show` |
| Workstream ops | `add`, `rename`, `edit`, `merge`, `split`, `remove`, `show`, `list` (per the workstream-management refinement of [project-management:DEC-012-classification-axes]) |
| Member ops | `add`, `remove`, `show` (per the team-membership refinement of [project-management:DEC-008-pm-and-implementer-roles]) |
| Mesh ops | `check` (per the methodology-mesh refinement) |
| Diagnostics | `show-tree` (PM-operational issue/PR hierarchy + orphans) |

PRs do not get an `assign` verb — PRs have reviewers, not assignees; a future `request-review-pr.py` is a separate enhancement when needed per COR-007. The DEC-017 trio (`pre-check.py`, `bootstrap.py`, `migrate.py`) sits alongside the verb-subject set; they are environment-scoped operations rather than methodology entities, so the noun-only form is retained.

The set is the commitment; specific scripts land in the versioned rollout below.

### Skills thin to routers

Each sub-procedure file under `skills/pm/` is reduced to **intent → command invocation**: recognise the user's intent in plain language, pick the script, invoke it with the inferred arguments, surface the script's output verbatim. Sub-procedures do not re-state methodology rules — the schemas + commands hold them. A sub-procedure that today walks "fill the body skeleton from body-format.yaml, check every required section, validate the title against titles.yaml, classify by classification.yaml, link the parent" becomes a routing note that invokes `create-issue.py` with the parsed arguments.

The composite-skill folder shape from COR-020 is preserved; the dispatcher (`pm.md`) still picks among sub-procedures by intent. What thins is each sub-procedure's body.

### CLI dispatch: direct-path now, `pkit pm <verb> <subject>` after

At v1 (this DEC's landing version, v0.3.0), invocation is direct-path:

```
.pkit/capabilities/project-management/scripts/create-issue.py --type=task --parent=#42
.pkit/capabilities/project-management/scripts/add-workstream.py cli
```

When kit issue #112 (capability-command CLI dispatch) lands, the same scripts surface via `pkit pm <verb> <subject>`. The dispatcher maps the CLI form to the filename mechanically; **no script changes**. The verb-subject filename convention is what makes the future mapping deterministic.

### Per-layer invocation discipline

The verb-subject script set splits at the operational layer into **workflow wrappers** and **substrate primitives**, with `gh` as the GitHub substrate below both:

| Layer | What lives here | Indicative examples |
|---|---|---|
| **Workflow wrappers** | Verb-subject scripts that orchestrate a multi-step work-flow. Each composes substrate primitives + composite gates + audit-trail comments + workflow side-effects (branch creation, PR creation, merge). | The lifecycle palette is the v1 instance (a forthcoming DEC defines it); wrapper-shaped scripts orchestrate over substrate primitives. |
| **Substrate primitives** | Verb-subject scripts that own a single substrate operation. Each handles the substrate-specific mechanics (board vs label-fallback per [project-management:DEC-006-state-machine-and-cascade], cascade walks, membership gates) and exposes a clean contract. | `move-issue` (state transitions), `create-issue` (issue creation), `close-issue` (won't-do closure), `assign-issue` (assignee mutation), `add-workstream`. |
| **GitHub substrate** | The raw `gh` CLI. Used for issue/PR mutations outside any methodology flow (label edits, body edits, comment edits, etc.). | `gh issue edit`, `gh pr comment`. |

The principle: **invoke at the appropriate layer; don't reach past the layer you're at without reason.** For the standard work-flow, use the workflow wrapper — it owns the gates and audit trail. For arbitrary substrate operations outside the standard flow, use the substrate primitive. For non-methodology mutations, `gh` is fine. The wrapper isn't a *requirement* for every substrate call (substrate primitives are reachable directly); it's the *standard* path for the operations the methodology defines as standard.

Reaching past a layer without reason — invoking `gh issue edit` to flip a Status field when `move-issue` exists, calling `move-issue` directly in the middle of a standard work-flow when `start-work` would compose it correctly — defeats the gate-consistency and audit-trail benefits the layer above provides. The constraint is per-layer, not "never `gh`".

**Verb-subject scripts that don't fit the layer model.** Some verb-subject scripts compose neither over `move-issue` nor over `gh` directly — they dispatch to external tooling (LLM agents, linters, formatters). The kit's first instance is the agent-invocation script introduced by [project-management:DEC-028-agent-as-approver-paths]'s `review-pr`. These scripts are validated by their verb-subject naming convention alone (they join the verb-subject set without sitting in the wrapper-substrate layering). If a second instance of this shape appears (linter, formatter, external-tool wrapper), a future COR may name an explicit third category; at v1 the verb-subject convention covers them as out-of-layer additions.

**Enforcement at v1.** Convention + code review. The [convention-compliance-reviewer](../../../decisions/core/COR-024-critic-and-architect-agents.md) agent reviews diffs against this discipline; the project-manager's instructions favour the wrapper layer for standard-flow operations. If routing-around the wrapper layer recurs in adopter or kit-source code, escalate to a tighter enforcement seam (e.g., a lint rule banning substrate-primitive imports from non-wrapper paths). For now, the wrappers are easier to use than the substrate primitives for the standard flow, and that ergonomic edge does most of the enforcement work.

### Three-layer defence model

Three layers of methodology enforcement; each has a single distinct purpose:

| Layer | When it runs | Catches | Purpose |
|---|---|---|---|
| **Methodology-mediated commands** | Per-operation; invoked by human or agent | Inputs validated; no invalid issue/PR/transition reaches GitHub via this path | Primary enforcement |
| **Post-check workflow** (kit-shipped GitHub Action template) | `issues.opened` / `issues.edited` events | Issues created outside the methodology (UI / raw `gh issue create`) | Bypass detection; comment / status check; optional auto-remediation |
| **General pre-check** (environment scope, per DEC-017) | On demand, before pm operations, or scheduled | Environment drift (labels missing, config invalid, gh auth lapsed) — **not** per-issue scanning | Health monitor |

Per-pm-operation pre-check on every issue's state is explicitly out of scope — too expensive, and drift detection is the post-check workflow's job. The three layers do not overlap.

### Versioned rollout

The shift lands incrementally; each version ships a coherent unit of behaviour change rather than a single big switch:

| Version | What ships |
|---|---|
| **v0.3.0** | This DEC + thinned `skills/pm/` sub-procedures + `create-issue.py` + `validate-issue.py` |
| **v0.4.0** | Remaining issue + PR commands + `show-tree.py` |
| **v0.5.0** | Workstream lifecycle commands (per the workstream-management refinement) |
| **v0.6.0** | Mandatory-issue-state enforcement + post-check workflow template |
| **v0.7.0+** | Methodology-mesh + `check-mesh.py` |

Each version bump is a surface change of the capability per the per-component bump policy; each version that lands a script also lands the same-PR-as-surface-change discipline from DEC-017 (the schema entry the script enforces is updated in the same PR).

## Rationale

**Why thin skills rather than removing them.** A skill that picks the right command for a free-text intent ("file a bug for the auth flow under EPIC #42") is doing interpretation. That work is appropriate for an LLM and inappropriate for a deterministic script — `gh issue create` doesn't parse English. Removing the skill layer would force the user to know the script names and arguments; keeping it as a router preserves the natural-language entry point while moving the rules into deterministic territory.

**Why verb-subject and not subject-verb.** Verb-first matches how a user states intent ("create an issue") and matches conventional CLI shapes for action verbs (`git commit`, `gh pr create` — though `gh` uses subject-verb, the verb-subject form reads more naturally aloud). Subject-verb (e.g., `scripts/issue-create.py`) groups by entity in directory listings but loses the natural-language ordering at the script invocation surface; verb-subject loses the entity grouping but gains operational readability. The future `pkit pm <verb> <subject>` dispatcher form makes verb-first canonical; aligning the filename removes one layer of indirection.

**Why one script per operation rather than a polymorphic entry-point.** Two reasons. The DEC-017 rationale applies — separate safety profiles deserve separate file names ("a read-only `show` script and a destructive `remove` script differ in blast radius; one file with a `--mode` flag conflates them"). And the verb-subject set is open over time (new domains add new verbs); a single-file dispatcher needs amendment with every addition, while filesystem entries scale naturally.

**Why the schemas remain the source of truth.** The shift is not "rules move from schemas to commands"; it is "rule *enforcement* moves from prose interpretation to deterministic execution while the rules themselves stay in schemas." Both commands and skills continue to read the same schemas. The methodology evolves by editing the schemas; the commands pick up new rules automatically.

**Why versioned rollout rather than a single big shift.** Re-encoding every operation as a verb-subject script in one PR is too large for safe review and too risky for adopter migration. Sequencing the shift across v0.3.0 → v0.7.0+ lets each version ship a reviewable surface and lets the discipline prove itself on `create-issue.py` + `validate-issue.py` before committing the full set.

### Alternatives considered

- **Keep the skill-prose model; tighten the prose.** Rejected — interpretation is the gap, and tighter prose doesn't close it. The DEC-017 scripts already exist as deterministic counter-evidence.
- **Remove skills entirely; expose only scripts.** Rejected — loses the natural-language intent layer; forces users to memorise script names and flags. The skills as thin routers are the cheap, high-value layer.
- **Subject-verb naming (`issue-create.py`, `pr-open.py`).** Rejected — natural-language entry point is verb-first; the future `pkit pm <verb> <subject>` dispatcher makes verb-first canonical.
- **One polymorphic dispatcher script (`pm-cli.py <verb> <subject>`).** Rejected — conflates safety profiles per DEC-017's reasoning; doesn't extend naturally to new domains.
- **Land all verb-subject scripts in one PR.** Rejected — too large for review; the versioned rollout sequences the work.

## Implications

- **The composite skill `pm.md` dispatcher** continues to pick among sub-procedures by intent per COR-020. Each sub-procedure thins to ~30 lines: intent → script invocation → output passthrough.
- **The capability ships a growing scripts surface**; new scripts land per the versioned rollout. Each ships under PEP 723 with the DEC-017 discipline (deterministic, auditable, schema-driven, exit codes are the contract).
- **The project-manager** invokes commands rather than producing `gh` calls directly. The agent surfaces script output verbatim — it does not paraphrase or aggregate.
- **Membership-gating** (per the team-membership refinement of [project-management:DEC-008-pm-and-implementer-roles]) is the first startup check inside every verb-subject script. Open mode (no `members.yaml`) bypasses; closed mode refuses non-members with the standard refusal message.
- **The post-check workflow template** (kit-shipped under `templates/.github/workflows/`) ships in v0.6.0 alongside the mandatory-issue-state enforcement. It detects bypass paths (UI / raw `gh issue create`) and posts a comment + status check + optional auto-remediation.
- **The capability `version:`** bumps on every rollout milestone. Each milestone is a surface change per the per-component bump policy.
- **A future kit-level COR may generalise this pattern** — methodology-as-executable-commands plus thin-skills-as-routers — to other capabilities that mutate external state. Promotion follows COR-007 when a second capability needs the same shape.
- **CI integration** uses pre-check (per DEC-017) and `validate-issue.py` / `validate-pr.py` as gating checks. The mutating verbs are human-invoked or agent-invoked, not CI-driven.
- **Adopter migration across the rollout** is by the DEC-017 migrate primitives — when a verb-subject script subsumes or renames a prior surface, the migration manifest at the version that lands the new script records the change.
