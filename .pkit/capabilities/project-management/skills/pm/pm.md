---
name: pm
description: Work with the project-management capability — file a new issue against the methodology's body shape, validate an existing issue body, or transition an issue through the lifecycle state machine. Composite skill per COR-020; dispatches to per-operation sub-procedures.
composes:
  - create-issue.md
  - validate-body.md
  - transition-state.md
  - batch-plan.md
gates:
  - COR-008
  - COR-017
  - COR-018
  - COR-019
  - COR-020
reads:
  records:
    - COR-016
    - COR-021
  paths:
    - .pkit/capabilities/project-management/README.md
    - .pkit/capabilities/project-management/schemas/issue-types.yaml
    - .pkit/capabilities/project-management/schemas/workflow.yaml
    - .pkit/capabilities/project-management/schemas/body-format.yaml
    - .pkit/capabilities/project-management/schemas/titles.yaml
    - .pkit/capabilities/project-management/schemas/classification.yaml
    - .pkit/capabilities/project-management/schemas/git-conventions.yaml
    - .pkit/capabilities/project-management/schemas/validation-severity.yaml
    - .pkit/capabilities/project-management/schemas/time-containers.yaml
    - .pkit/capabilities/project-management/scripts/pre-check.py
    - .pkit/capabilities/project-management/scripts/bootstrap.py
    - .pkit/capabilities/project-management/scripts/migrate.py
    - .pkit/capabilities/project-management/scripts/move-issue.py
    - .pkit/capabilities/project-management/skills/pm/create-issue.md
    - .pkit/capabilities/project-management/skills/pm/validate-body.md
    - .pkit/capabilities/project-management/skills/pm/transition-state.md
    - .pkit/capabilities/project-management/skills/pm/batch-plan.md
    - .pkit/capabilities/project-management/agents/project-manager/storyboard.md
    - .pkit/capabilities/project-management/project/workstreams.yaml
---

# Working with the project-management capability

This is the **project-management capability** engine skill. It composes the three operations the project-manager (and any human operator invoking the skill directly) runs against the methodology — filing, validating, and transitioning issues — all of them reading the same eight schemas at runtime and tagging every check with the severity vocabulary from the validation-severity schema.

## Acceptance gate

The records in `gates:` must be `accepted`:

- **COR-008** — git workflow conventions. The capability's branch and PR conventions inherit the conventional-commits + one-logical-unit-per-commit rules from this record.
- **COR-017** — capability pattern. This skill operates inside an installed capability per the kit's pattern.
- **COR-018** — capabilities adopt the schemas mechanism. This skill reads the capability's eight schemas at runtime; the mechanism is the substrate.
- **COR-019** — schema reference form. Cross-schema typed-token references in schema content (e.g., severity tokens, issue-type tokens) are resolved per this convention.
- **COR-020** — composite-skill folder form. This skill itself follows the convention.

Halt if any is `proposed` or `superseded`.

## Step 0 — run pre-check before any operation

Before dispatching to any of the three operations below, **invoke the capability's pre-check script** and refuse to proceed on any failure. Per [project-management:DEC-017-prerequisites-bootstrap-migrate-discipline], pre-check is the **hard gate**: a missing prerequisite stops the operation cleanly, with a remediation hint, rather than failing mid-mutation with a confusing partial state.

```
.pkit/capabilities/project-management/scripts/pre-check.py
```

The script is read-only and self-contained (PEP 723; runs via `uv run --script`). Exit code is the contract — zero means every check passed or was legitimately skipped; non-zero means at least one prerequisite is missing. **The project-manager's behaviour on non-zero exit: refuse the requested operation, surface the pre-check's report verbatim to the user, and end.** Don't paraphrase the report; the script's output is already in the right shape.

If pre-check reports missing initial state (no `type:*` labels, no adopter config, etc.), the remediation is to run the **bootstrap** script:

```
.pkit/capabilities/project-management/scripts/bootstrap.py
```

After capability upgrades that ship migration manifests under `migrations/`, the remediation includes **migrate**:

```
.pkit/capabilities/project-management/scripts/migrate.py
```

Bootstrap is additive and idempotent; migrate is destructive on per-change confirmation. Both are programmatic — the project-manager **does not perform their work itself**, it invokes the script and surfaces the output. See [project-management:DEC-017-prerequisites-bootstrap-migrate-discipline] for the full discipline.

## Pick the operation

The three operations don't overlap — they answer different questions. Pick by intent:

| Operation | When to use it | Sub-procedure |
|---|---|---|
| **Create a new issue** | A new EPIC, Feature, Umbrella, Task, or Milestone needs to be filed. Stamps the title, the body skeleton per the type's required sections, the classification axes, and the native sub-issue parent link. | create-issue |
| **Validate an existing issue body** | An existing issue's body is being edited, or the project-manager is checking an inherited issue at first interaction. Walks every body rule the methodology mandates and surfaces issues by severity. Used as a pre-check before any transition. | validate-body |
| **Transition an issue's state** | Move an issue forward (Todo → Backlog → In Progress → Review) or close it (Review → Done via PR merge; any-state → Done via won't-do; cascade-eligibility close for parents). Runs the cascade after every state change. | transition-state |

The project-manager typically invokes them in sequence: create-issue (file) → validate-body (after any edit) → transition-state (advance/close). For one-off operator use, pick the single relevant one. After picking, open the matching sub-procedure file in this folder and follow its walkthrough.

## Shared framing (applies to all three operations)

### The schemas are the source of truth

Every operation in this family reads the capability's eight schemas:

- `.pkit/capabilities/project-management/schemas/issue-types.yaml` — issue-type vocabulary, containment graph, parent-ref forms.
- `.pkit/capabilities/project-management/schemas/workflow.yaml` — state machine, transitions, cascade rules, closure triggers.
- `.pkit/capabilities/project-management/schemas/body-format.yaml` — per-type required sections, universal rules, checkbox semantics, integration marker, sub-task promotion.
- `.pkit/capabilities/project-management/schemas/titles.yaml` — title regexes per surface (issue per type, milestone, PR).
- `.pkit/capabilities/project-management/schemas/classification.yaml` — Type / Priority / Workstream axes plus the PR-type mapping.
- `.pkit/capabilities/project-management/schemas/git-conventions.yaml` — branch name, PR body, merge mechanics, force-push policy, integration branches.
- `.pkit/capabilities/project-management/schemas/validation-severity.yaml` — three-class severity vocabulary every other schema's validations tag against.
- `.pkit/capabilities/project-management/schemas/time-containers.yaml` — Milestone + Iteration, close-trigger marker, rollforward cascade.

The schemas are the source of truth. Don't paraphrase rules from prose; read them from the YAML and dispatch on the structured fields. When a schema field carries a typed token of the form `[<namespace>:<id>]`, resolve it against the target schema before acting.

### Severity dispatch

Every validation in every operation is tagged with a severity token read from the relevant schema entry. Three classes exist, defined by the validation-severity schema:

- **`hard-reject`** — refuse the operation; surface the failed rule and the failing input; end. No `--bypass` form.
- **`bypassable-with-audit`** — refuse by default. With `--bypass "<reason>"` carrying a non-empty reason, post the audit comment template from the validation-severity schema on the affected issue or PR (filled with name + email + reason) **before** the mutation runs, then run the mutation.
- **`warning`** — emit the one-line warning, complete the operation, move on.

Operations never aggregate severities silently — every triggered rule produces its own response. Hard rejects abort early; bypassable rules wait for the user; warnings emit but proceed.

### Reading the upstream lineage

Every schema entry's `source:` block points at the upstream MET (in pm-workflow) it distills from. When the engine surfaces a rule violation, the message cites the local capability DEC rather than the upstream MET — the operator reading the message sees the capability's view, not the pm-workflow view. The lineage stays auditable but isn't the primary surface.

### Adopter-side configuration the agent expects

Some axes carry project-specific values. The project-manager expects the following configuration in the adopter's project namespace (location depends on the harness — typically a project-side YAML the adopter fills in on first run):

- The list of allowed workstream values.
- The Priority default (defaults to Medium; only override if the project's policy differs).
- The default branch (defaults to `main`).
- Optional: code-path → doc-path mappings for the doc-impact convention.
- Optional: pre-close triage lead-time in days (defaults to 3).

When this config is missing on first interaction, the agent prompts the user to fill it in rather than guessing.

### Citation form in error messages

When surfacing a rule's source, cite the local capability DEC by stem (the `[project-management:DEC-NNN-slug]` form) and the schema entry by file + JSON-pointer path. The DEC gives the *why*; the schema pointer gives the *what*. Together they make the rejection auditable without forcing the operator to chase the rule across multiple files. See the per-operation sub-procedures for exact error-message templates.

## Conventions adopted from elsewhere

- **Conventional commits + one logical unit per commit** (per COR-008) — applies to the kit-level commits that author or evolve this capability; also applies to PR squash-merge subjects per the capability's own git-conventions schema, which is the project-management-specific instance of the same discipline.
- **Capability decision citations** use the form `[project-management:DEC-NNN-slug]` per COR-017.
- **Cross-schema references** use the typed-token form `[<namespace>:<id>]` per COR-019; the validator resolves them automatically.
- **Composite skill layout** (this folder, with dispatcher + sub-procedures) per COR-020. The dispatcher carries the shared framing; sub-procedures carry the per-operation walkthrough.

## Skill-thinning status — DEC-020 rollout

[project-management:DEC-020-methodology-as-executable-commands] specifies a shift from skill-prose-the-LLM-interprets to deterministic verb-subject scripts under `scripts/`. The thinning lands incrementally as each script ships:

| Sub-procedure | Status | Backing script |
|---|---|---|
| [create-issue](create-issue.md) | Thinned (v0.3.x) | `scripts/create-issue.py` |
| [validate-body](validate-body.md) | Thinned (v0.3.x) | `scripts/validate-issue.py` |
| [transition-state](transition-state.md) | v0.2.0 prose (script lands at v0.4.0) | `scripts/move-issue.py` (pending) |

For thinned sub-procedures, the file is an intent-to-command router: it recognises the user's intent in plain language, picks the right `pkit project-management <verb> <subject>` invocation, and surfaces the script's output verbatim. The methodology rules live in the schemas + the deterministic scripts; the sub-procedure's prose no longer carries them.

For sub-procedures whose backing script hasn't shipped yet, the v0.2.0 walkthrough stays authoritative. Each sub-procedure carries its own "implementation status" note so the reader knows which mode it's in.
