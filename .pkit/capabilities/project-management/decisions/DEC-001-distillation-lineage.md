---
id: DEC-001
title: Carry upstream lineage on every distilled DEC and schema via a `source:` block
status: accepted
date: 2026-05-21
author: Ales Kalfas
---

## Context

This capability does not invent its rules; it distills them from the [pm-workflow](https://github.com/aleskalfas/pm-workflow) methodology. pm-workflow is the *spec*, iterated and ratified upstream; this capability is the *realization*, packaged for `pkit install`. The two repositories evolve on separate timelines: pm-workflow's METs (methodology decisions) move when the team revises a rule and the review-agent ceremony ratifies the change; this capability's DECs and schemas move when an author re-syncs from pm-workflow's `main` and updates the operational artifacts.

The relationship is therefore lineage-bearing — every distilled artifact has an upstream parent — but not a 1:1 copy. A DEC may re-frame the MET in operational terms; a schema may encode multiple METs in one data file. Three problems arise without an explicit lineage convention:

1. **No drift signal.** A reader of a distilled DEC cannot tell whether the upstream MET has moved since this DEC was authored. The two documents look authoritative in isolation; only the upstream-bound reader knows the spec changed.
2. **No re-distillation trigger.** A re-sync author has no machine-checkable way to find which DECs and schemas pre-date a given upstream commit and therefore need review.
3. **Ambiguous attribution for capability-internal decisions.** Some DECs in this capability are not distilled — they are implementation choices the capability author made (this DEC is one such). A reader cannot distinguish "distilled, has upstream parent" from "capability-internal, no upstream parent" without a marker.

Schemas already inherit a `source:` block convention from the schemas-area envelope (see `.pkit/schemas/README.md`); the question is whether DECs should adopt the same shape and whether the convention should be made explicit as the capability's lineage contract.

## Decision

Every artifact in this capability that distills from pm-workflow carries a `source:` block pointing at the upstream parent. Capability-internal artifacts omit the block; their absence is itself a signal.

### Form for DECs

In the YAML frontmatter, after the existing metadata fields:

```yaml
---
id: DEC-NNN
title: <short title>
status: accepted
date: YYYY-MM-DD
author: <name>
source:
  upstream: pm-workflow
  upstream_id: MET-NNN
  commit: <40-character SHA of the upstream snapshot>
  captured_at: YYYY-MM-DD
---
```

Field semantics:

- **`upstream`** — kebab-case name of the upstream project (always `pm-workflow` at v0.1.0; the field exists so the convention generalizes if other capabilities adopt it).
- **`upstream_id`** — the upstream's own identifier for the parent decision (always `MET-NNN` for pm-workflow). A DEC has exactly one `upstream_id`; one MET maps to at most one DEC.
- **`commit`** — full 40-character SHA of the upstream commit the distillation was performed against. Not a tag, not a branch reference — pinning to a SHA preserves auditability when upstream history rewrites or branches move.
- **`captured_at`** — ISO date the author performed the distillation. The pair (`commit`, `captured_at`) together let a re-sync author compute drift: list METs whose upstream history advanced since `commit`, prioritize by `captured_at`.

### Form for schemas

Schemas use the `source:` envelope block already defined by the schemas mechanism (see `.pkit/schemas/README.md` "YAML conventions"), with the same field names. The difference from DECs is the `decisions:` field is a *list* — a schema may distill multiple METs (e.g., `body-format.yaml` distills both MET-006 and MET-009):

```yaml
schema_version: 1
source:
  upstream: pm-workflow
  commit: <40-character SHA>
  decisions: [MET-NNN, MET-MMM]
  captured_at: YYYY-MM-DD
# ...domain-specific fields...
```

### Granularity rule (DECs only)

DEC ↔ MET is 1:1. A DEC distills exactly one MET; no folding of two METs into one DEC. Folding loses the lineage breadcrumb — a reader of the folded DEC cannot tell which of the two METs a given principle came from, and a re-sync author cannot detect that only one of the two has drifted upstream.

Schemas do not have this constraint because their lineage list is explicit (`decisions: [...]`); a schema-level drift check walks each entry independently.

### Authority signal

The authority signal for distillation is pm-workflow's `main` branch. A MET on `main` is in scope regardless of whether its internal `status:` is `accepted` or `proposed` — the capability tracks `main` because the methodology must be operational *now*, not after the upstream review ceremony completes for every individual decision.

If pm-workflow's `main` later rewrites or reverts a MET, the next re-sync brings the change in; the previous `commit` SHA in the distilled artifact's `source:` block remains the audit record of what was distilled before.

### Capability-internal artifacts omit `source:`

DECs and schemas authored by the capability without an upstream parent omit the `source:` block. The absence marks the artifact as a capability-internal design choice, not a distillation. This DEC is such an artifact — its frontmatter has no `source:` block because no MET fixes the lineage discipline upstream.

## Rationale

**Why a per-artifact frontmatter block, not a separate registry.** A registry file (`lineage.yaml` mapping DEC IDs to MET IDs) would centralize the lineage but separate it from the artifact. Readers of a DEC would have to consult a second file to see the parent; the registry would need its own validator to stay in sync. Per-artifact frontmatter keeps the lineage local — every reader of a DEC sees the upstream pointer on the same page — and reuses the artifact's existing parser. The validator extension is small (read frontmatter, check `source.commit` is a valid SHA, optionally verify the upstream MET exists at that commit).

**Why mirror the schemas-area envelope shape.** Schemas already define `source:` with field names `upstream`, `commit`, `decisions`, `captured_at`. Reusing the same field names for DEC frontmatter (singular `upstream_id` in place of plural `decisions`) avoids inventing a parallel vocabulary. Readers and tools that handle the schemas envelope handle the DEC frontmatter the same way.

**Why pin to a 40-char commit SHA, not a tag or branch.** SHAs are immutable; tags and branches move. A `commit: main` reference would lose the audit trail the first time `main` advances. A `commit: v0.3.0` tag could be deleted or moved. The SHA is the only reference that lets a future reader reproduce the exact upstream state the distillation was performed against.

**Why 1:1 for DECs.** Folding loses the lineage breadcrumb. A DEC that claims `upstream_id: [MET-005, MET-006]` (a list) creates the ambiguity this DEC exists to prevent: a re-sync author seeing MET-005 drift cannot tell whether the folded DEC needs revision because of MET-005 or MET-006. Schemas escape this trap because their list is over *fields*, not over *principles* — a schema's `decisions:` list names the METs it encodes data for, but the data itself is structured per-MET (e.g., one regex per title type from MET-010).

**Why track upstream `main`, not upstream `accepted` status.** pm-workflow's review-agent ceremony is rigorous — every MET requires Quorum sign-off and zero open questions to land in `accepted`. That cadence is appropriate for the spec but too slow to gate operational distribution. Tracking `main` lets adopters get value from a MET as soon as the upstream team merges it, with the understanding that subsequent revisions will flow through re-sync.

### Alternatives considered

- **Central `lineage.yaml` registry.** Rejected. Separates lineage from the artifact; needs its own validator; readers must consult two files.
- **Title-encoded lineage (`DEC-005 (from MET-005)`).** Rejected. Not machine-checkable; conflates title and metadata; cannot carry the commit SHA.
- **Embed upstream MET text in the DEC body.** Rejected. Couples the operational realization to the upstream wording; defeats the point of distillation (re-framing in operational terms); makes drift detection harder, not easier.
- **Track upstream by tag/release, not commit SHA.** Rejected. Tags move and can be deleted; pre-1.0 upstream projects often don't tag at all. The SHA is the only stable reference.
- **Allow folding of multiple METs into one DEC.** Rejected. Loses the lineage breadcrumb the convention exists to preserve.

## Implications

- **The capability's validator extension checks `source:` blocks for shape.** A `pkit refs validate` run over the capability subtree verifies every DEC frontmatter parses, every `source.commit` is a 40-char hex string, and every `source.upstream_id` matches the expected upstream-ID pattern (`MET-NNN`). Cross-repo verification (does the SHA exist? does the MET exist at that SHA?) is deferred — runs as a separate `pkit refs check-lineage` invocation that consults the upstream repository, not as part of the always-on validator.
- **Re-distillation is mechanical.** A re-sync author runs `git log` between the capability's recorded `commit` and pm-workflow's current `main`, lists METs touched, and revisits the corresponding DECs and schemas. The convention turns re-sync from a memory exercise into a script.
- **Capability-internal DECs are visibly distinct.** Readers can tell a distilled DEC from a capability-internal one at frontmatter glance. The discipline applies recursively — a future capability-internal DEC about, e.g., the agent's orchestration logic, omits `source:` and that absence is the signal.
- **The convention generalizes.** If a future capability distills from another upstream project (e.g., a security-review capability distilling from a vendor's specification), the same `source:` block shape applies; only the `upstream` value changes. This DEC is the contract; other capabilities adopt it by reference.
- **Adopter-facing visibility.** The lineage is visible in the installed capability's source — adopters reading a distilled DEC see exactly which MET it came from and at which commit. This makes the relationship to pm-workflow auditable from the adopter's side, not just the capability author's.
