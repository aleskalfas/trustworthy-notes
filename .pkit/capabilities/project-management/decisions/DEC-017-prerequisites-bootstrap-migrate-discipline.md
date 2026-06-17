---
id: DEC-017
title: Three programmatic operations for prerequisite verification, adoption setup, and adopter-state migration — pre-check, bootstrap, migrate
status: accepted
date: 2026-05-22
author: Ales Kalfas
---

## Context

The project-management capability mutates external state — GitHub issues, labels, milestones, PRs, branch protection, Projects v2 fields. Its operations depend on a chain of prerequisites the adopter must have in place (`gh` authenticated, labels created, default branch declared, adopter config present). When prerequisites are missing, today's failure mode is **failure mid-mutation**: the project-manager gets halfway through filing an issue and the underlying `gh` call errors out, leaving a partial state and an opaque message.

Three distinct concerns are interleaved in this picture, and each deserves its own programmatic operation:

1. **Reporting** — does the adopter's environment match what the methodology expects right now? A read-only diagnostic that surfaces every gap. Run before every pm operation and on demand.
2. **Setup** — for a fresh adopter, create the missing initial state (labels per the methodology's classification axes, optionally a starter EPIC so subsequent Task filings have a parent). One-shot operation; re-runs add nothing.
3. **Reconciliation after evolution** — when the capability upgrades and its expectations change (a `type:*` value renamed, a label vocabulary shifted, a marker format evolved), the adopter's GitHub state goes stale. The capability needs a mechanism to honestly sync state with new expectations, with hard gates against destructive changes.

The three concerns share infrastructure (schema-reading, `gh` CLI access, adopter-config parsing) but have **fundamentally different safety profiles**: reporting is read-only and free to run; setup is additive and free to re-run; reconciliation is destructive and must require explicit confirmation per change. Conflating them into one script would either over-warn on the safe operations or under-protect the destructive one.

A separate but adjacent failure mode this DEC also rules out: **AI-mediated checks**. An agent that says "I checked, all good" can hallucinate the result or skip parts, and the failure surfaces as the same mid-mutation crash. Deterministic Python scripts that run the same way every time, surface the same diagnostic on the same failure, and are line-by-line auditable are the right shape — both for reporting and for the mutations themselves.

## Decision

The capability ships **three programmatic scripts** under `scripts/`, each with a single responsibility and distinct safety discipline. All three are PEP 723 self-contained Python — runnable via `uv run --script` from any adopter without a project venv. None is AI-mediated; all are deterministic and auditable.

### `scripts/pre-check.py` — read-only diagnostic

**Discipline.** Read-only. Compares the adopter's GitHub state and project-side configuration against the capability's schemas and reports gaps. Exits non-zero on any failure; zero when every check passes or is legitimately skipped.

**Hard-gate role.** The pm composite skill's dispatcher makes "Step 0: run pre-check" the first step of every operation. The operation refuses to proceed on any failure. The gate is **programmatic**, not the agent's interpretation of the output — the script's exit code is the contract.

**Checks at v0.2.0** (the version this DEC lands in):

1. `git` and `gh` are invocable; versions captured for diagnostics.
2. `gh auth status` returns valid for the target host.
3. The repository (`gh repo view`) is accessible and matches the expected owner/name.
4. Projects v2 board (conditional on adopter config declaring one): `gh project view` resolves the declared board id.
5. Required labels exist: every value in [project-management:DEC-012-classification-axes]'s `type` axis as a `type:<value>` label. In label-fallback mode (no board): also `priority:<value>` and `workstream:<value>` per the configured value sets.
6. Default branch (`gh api repos/:owner/:repo`) matches the value declared in adopter config.
7. The project-side adopter config file is present, parses, and declares every required field.

The check list is data-driven from the capability's schemas plus the adopter config. Adding a check is the same-PR-as-methodology-change discipline below.

### `scripts/bootstrap.py` — additive idempotent setup

**Discipline.** Additive only. Creates state that the methodology expects but the adopter doesn't yet have. **Never** modifies or deletes existing state — that's migrate's job. Re-running on already-bootstrapped state creates nothing.

**Hard-gate role.** None directly. Bootstrap is safe to invoke because it can't break existing state. The project-manager's "Adopter setup" walks adopters to run bootstrap once after install; subsequent re-runs are no-ops.

**Operations at v0.2.0:**

- Create `type:<value>` labels from `classification.yaml#axes.type.values`. Skip labels that already exist.
- In label-fallback mode (no Projects v2 board configured): create `priority:<value>` and `workstream:<value>` labels from the relevant schema entries and adopter config. Skip existing.
- Optional `--with-starter-epic` flag files a starter EPIC titled `[EPIC] Methodology adoption — initial hierarchy` so subsequent Task filings have a default parent. The flag is the user's PM-authorisation gesture per [project-management:DEC-008-pm-and-implementer-roles] (EPICs are PM-authority filing; the flag opts in explicitly).

Adding a new bootstrap operation (e.g., creating board fields if a board configures one) is the same-PR-as-methodology-change discipline.

### `scripts/migrate.py` — adopter-state reconciliation

**Discipline.** Destructive on confirmation. Reconciles drifted adopter state with the new capability version's expectations after `pkit capabilities upgrade project-management`. **Never auto-chained from upgrade** — explicit invocation only, so the adopter reads the migration plan before authorising.

**Hard-gate role.** Per-change user confirmation by default. No batch `--yes` flag. CI-friendly via `--config <adopter-authored-pre-approval-file>` declaring pre-approved migration shapes. Refuses to run if pre-check fails — drift in basic prerequisites breaks migration assumptions.

**Mechanism.** Reads versioned migration entries from `migrations/<version>.yaml`. Each entry declares the changes the methodology evolution introduced (label rename, label delete, marker format change, etc.). The script auto-detects what the diff allows (does the old label exist? do issues use it?), presents the plan, and prompts per-change for confirmation. Confirmed changes execute via `gh` mutations.

**Idempotency.** Tracks applied migrations in an adopter-side state file (`<adopter>/.pkit/capabilities/project-management/project/migrations-applied.yaml`). Re-running on already-applied migrations is a no-op.

**v0.2.0 migration primitives** (recognized `kind:` values in the manifest):

- `label-rename` — rename a label; optionally re-tag issues using the old label.
- `label-delete` — delete a label; refuse if any issue still uses it (or force with confirmation).
- `label-create` — create a new label (overlaps with bootstrap, but ships as a migration when the *introduction* of a label is the surface change of a specific version).

More primitives land as actual migrations need them, per COR-007's pattern-extraction rule.

### Same-PR-as-surface-change discipline (all three scripts)

When a methodology change in this capability adds, drops, or rewords a prerequisite (pre-check), an initial-state requirement (bootstrap), or an adopter-observable state shape (migrate), the corresponding script — or `migrations/<version>.yaml` entry, for migrate — is updated in the **same PR** as the methodology change. The script is part of the capability's surface; modifying it bumps the capability's `version:` per the per-component bump policy.

This mirrors COR-010's mandate at the file-system level — *for adopter state, not just adopter files*. A capability that mutates external state without a corresponding adopter-state migration on surface change leaves adopters in a stale-and-broken position next time they `pkit capabilities upgrade`.

### Citation form on script-surfaced errors

The scripts cite local capability DECs and schema entries in their output messages — the operator reading a failure sees the capability's view, not the upstream pm-workflow lineage. Format:

```
[fail] `type:bug` label missing from repo
       → Required by classification.yaml#axes.type.values (per [project-management:DEC-012-classification-axes])
       → Fix: run `bootstrap` to create missing labels
```

## Rationale

**Why three separate operations rather than one polymorphic script.** A single script with `--mode={check,bootstrap,migrate}` would conflate three fundamentally different safety profiles. The CLI overhead of three entry points is trivial; the safety benefit of read-only / additive / destructive being three distinct file names with three distinct confirmation behaviours is large. An operator who runs the wrong mode and gets a destructive default is a failure mode the separation prevents.

**Why programmatic, not AI-mediated.** Diagnostic and mutation both. An AI agent claiming "I checked, all good" can hallucinate or skip; a Python script exit code is unambiguous. A line-by-line `gh label create` sequence is auditable; an agent prompt that "I created the labels" isn't. The methodology's hard-gate discipline (per [project-management:DEC-014-validation-severity-model]) is enforced by mechanical refusal, not by interpretation.

**Why explicit invocation of migrate (not auto-chained from upgrade).** `pkit capabilities upgrade project-management` swaps the file-system state of the capability. `migrate` mutates external GitHub state. The two are different surfaces with different blast radius. Auto-chaining means an `upgrade` could rename labels and re-tag issues without the adopter reading the migration plan; that's the opposite of the user's "honest sync with hard gates" requirement.

**Why migrate refuses on pre-check failure.** Drift in basic prerequisites — missing labels, wrong default branch, board configuration mismatch — breaks the assumptions migrate's plan computation relies on. A migration that "renames `type:maintenance` to `type:chore`" assumes `type:maintenance` exists and behaves like a `type:*` axis label; if the adopter is in a state where `type:maintenance` was manually deleted (and several issues are mislabelled), the migration is dangerous to attempt. Pre-check passing is the precondition for migrate's safety.

**Why label-only primitives at v0.2.0.** No actual migration has happened yet — v0.2.0 is the *first* version shipping the framework. Adding board-field, marker-format, or body-shape primitives speculatively violates COR-007's pattern-extraction discipline. Primitives crystallise when real migrations need them.

### Alternatives considered

- **One script with mode flags.** Rejected — conflates safety profiles; risks running destructive mode by accident.
- **AI-mediated pre-check.** Rejected — non-deterministic; hallucination risk; not auditable line-by-line.
- **Auto-chain migrate after upgrade.** Rejected per user direction — adopters must read the migration plan before authorising; chaining bypasses that.
- **Batch `--yes` flag on migrate.** Rejected for v0.2.0 — defeats the per-change confirmation gate. CI-friendly path is `--config` with adopter-authored pre-approvals, which is a deliberate gesture not an escape hatch.
- **Skip migrate entirely; let bootstrap re-create missing state on each version.** Rejected — bootstrap is additive only, so renamed/deleted-from-methodology state would never disappear from the adopter's repo, accumulating cruft. Migrate's destructive operations are necessary for honest reconciliation.

## Implications

- **The pm composite skill's dispatcher** adds Step 0 (run pre-check) above the operation dispatch. Every sub-procedure refuses to proceed on pre-check failure.
- **The capability README** documents three phases of the adopter lifecycle: install → bootstrap → pre-check → use (steady state) → upgrade → migrate (on each upgrade with surface change).
- **The project-manager** invokes pre-check via the dispatcher's Step 0; recommends bootstrap on first interaction when pre-check reports missing initial state; recommends migrate after the capability upgrades and `migrations/<version>.yaml` has unapplied entries.
- **Capability `version:`** bumps on any change to the three scripts or the migrations manifest. The v0.2.0 bump ships this discipline plus all three scripts.
- **A future COR may generalise this pattern** to all capabilities that mutate external state (a future `deployment` capability mutating infra state; a future `compliance` capability mutating audit logs). For v0.2.0 the discipline lives as DEC-017 in this capability; promotion to a COR follows COR-007 when a second capability needs the same shape.
- **The migrate state file** (`migrations-applied.yaml` in the adopter's project namespace) is adopter-owned and survives capability upgrades. The migrate script auto-creates it; no install-time stub needed.
- **CI integration** uses pre-check directly (read-only, safe to gate PRs on). Bootstrap and migrate are not CI operations — they're human-invoked at adoption / upgrade time.
