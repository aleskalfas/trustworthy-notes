---
id: DEC-010
title: Minimum required body structure per issue type
status: accepted
date: 2026-05-21
author: Ales Kalfas
source:
  upstream: pm-workflow
  upstream_id: MET-009
  commit: 9d1f0237f5d5778ed9811c72f22ae8268e5faff3
  captured_at: 2026-05-21
---

## Context

Every other DEC in this capability references "the issue body" — its parent-ref first line, its checkboxes, its acceptance criteria, its doc-impact section. Those references work only if the body shape per issue type is fixed. The body shape also drives what the validate-body skill checks at filing and edit time. Without an explicit minimum, the agent has no validation surface and adopters produce inconsistent issues that are hard to scan.

## Decision

The minimum required body structure per issue type is fixed in [`schemas/body-format.yaml`](../schemas/body-format.yaml). The capability mandates the floor (what every body must contain); templates ship the recommended-section recommendations on top.

### Universal body rules

These apply to every issue type, encoded in the schema's `universal_body_rules`:

- **First line is the ancestry parent-ref** per the type's `parent_ref_form` in [`schemas/issue-types.yaml`](../schemas/issue-types.yaml). When an `Integration: integration/<slug>` pre-line is present it precedes the parent-ref with no blank line between; otherwise the body opens directly with the parent-ref. Blank line, then content.
- **No `# ...` h1 headings** — the issue title is the h1. Sections start at `## Title`.
- **No `file:line` references** — line numbers go stale. Name the file and the identifier separately.
- **No `## Implementation` / `## How` recipes** — bodies describe outcomes, not how to build them. Implementation belongs in the PR or a separate design doc.
- **No predicted decision IDs** — reference only IDs that already exist.
- **Checkboxes follow [project-management:DEC-007-checkbox-validation] and [project-management:DEC-009-living-documents]** — close-gate, ticks sticky, wording-free / scope-gated.

### Per-type minimum required sections

| Type | First line | Required sections |
|---|---|---|
| EPIC | `Milestone: #<N>` (optional if unscheduled) | `## Outcome`, `## Success criteria` (checkboxes) |
| Feature | `EPIC: #<N>` | `## What`, `## Acceptance criteria` (checkboxes) |
| Umbrella | `EPIC: #<N>` or `Umbrella: #<N>` | `## Purpose` |
| Task | `Feature: #<N>` / `Umbrella: #<N>` / `EPIC: #<N>` | `## What`, `## Acceptance criteria` (checkboxes), `## Doc impact` (per [project-management:DEC-015-doc-update-obligations]) |

Each required section's heading, purpose, checkbox flag, and missing-section severity (`[validation-severity:hard-reject]`) are encoded in the schema's `bodies` mapping, keyed by issue-type id.

### Notes per type

- **EPIC.** Outcome describes the thesis or de-risking goal. Success criteria describe what proves the thesis.
- **Feature.** What describes the capability claim. Acceptance criteria describe how the capability is verified.
- **Umbrella.** Purpose describes what holds these Tasks together. No acceptance criteria — Umbrellas don't claim a capability.
- **Task.** What describes the concrete change. Acceptance criteria are concrete claims tied to code. Doc impact captures which docs change.

### Optional sections (templates recommend)

Per-type templates may add recommended sections beyond the minimum — `## Why`, `## Out of scope`, `## Related`, `## Dependencies`, `## Approach`, `## Implementation notes`. Encoded as the schema's `optional_section_recommendations` per type. The capability mandates the structure floor; teams customise content within it.

### Sub-task promotion

When a markdown sub-task grows up — needs its own PR, owner, discussion, or labels — the project-manager promotes it to a standalone Task per the procedure encoded in [`schemas/body-format.yaml`](../schemas/body-format.yaml)'s `sub_task_promotion` block. The new Task's parent is the *original Task's parent* (Feature, Umbrella, or EPIC) — not the original Task itself, per the containment rule in [project-management:DEC-005-linking-and-containment]. The original Task's body has the plain checkbox replaced with a task-list reference (`- [ ] foo` → `- [ ] #<N> foo`) so GitHub auto-ticks when the promoted Task closes.

## Rationale

A fixed minimum gives the validate-body skill a precise validation surface and gives readers a predictable structure to skim. Different issue types serve different purposes (EPIC = thesis, Feature = capability, Umbrella = bucket, Task = change), and their minimum content reflects that.

Leaving optional sections to templates rather than mandating them avoids the body-is-design-doc failure mode — too many mandatory sections make every Task feel like an architectural document. The capability mandates structure; teams customise within it.

### Alternatives considered

- **Single uniform body shape across all types.** Rejected — EPICs and Tasks need different sections; uniformity would force one of them into a misfitting shape.
- **Free-form bodies (no minimum).** Rejected — loses the validation surface; produces inconsistent issues hard to scan.
- **Maximal mandatory sections per type.** Rejected as over-prescriptive — optional sections live in templates.

## Implications

- The validate-body skill rejects filings whose body doesn't match the per-type minimum, surfacing the missing-section severity from the schema (hard-reject).
- The Doc impact section is mandatory on Tasks; non-Task types may include it but aren't required to — see [project-management:DEC-015-doc-update-obligations].
- The templates under `templates/` instantiate this decision — one file per issue type (`templates/epic.md`, `templates/feature.md`, `templates/umbrella.md`, `templates/task.md`), each carrying the minimum required structure and inline reminders of the universal rules. Templates don't ship the `Integration:` pre-line — the project-manager stamps it when an owner designates an integration scope per [project-management:DEC-013-branch-and-pr-conventions].
- The optional `Integration:` pre-line is parsed by the project-manager at PR-open time to determine the PR's base branch — see [project-management:DEC-013-branch-and-pr-conventions].
- The capability validates bodies against the schema-defined minimum, not against the template (which is recommendation, not contract).
