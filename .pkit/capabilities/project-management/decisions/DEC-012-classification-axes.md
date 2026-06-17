---
id: DEC-012
title: Classification axes — `type:*` label, Priority and Workstream board fields with label fallback
status: accepted
date: 2026-05-21
author: Ales Kalfas
source:
  upstream: pm-workflow
  upstream_id: MET-011
  commit: 9d1f0237f5d5778ed9811c72f22ae8268e5faff3
  captured_at: 2026-05-21
---

## Context

Issues need classification beyond their structural type from [project-management:DEC-004-six-level-hierarchy]. Classification serves three jobs in agent-mediated work: (1) the project-manager classifies issues consistently at filing, (2) classification drives board filters and planning views, (3) the PR's Conventional Commits `<type>` from [project-management:DEC-011-title-formats] aligns to the closing Task's classification.

Adopters fall into two cohorts: those running a Projects v2 board (richer classification with single-select fields, atomic validation, cross-repo workstream alignment) and those without (degraded but functional classification via labels). The capability has to work in both modes without forking the discipline.

## Decision

Three classification axes — `type`, `priority`, `workstream` — each required on every issue. Substrate varies with whether a Projects v2 board exists. Encoded in [`schemas/classification.yaml`](../schemas/classification.yaml)'s `axes` mapping.

### Per-axis substrate

| Axis | Substrate (with board) | Substrate (without board) | Values |
|---|---|---|---|
| `type` | `type:*` label *(always a label)* | `type:*` label | `feature`, `bug`, `docs`, `test`, `refactor`, `maintenance` |
| `priority` | Projects v2 single-select field | `priority:*` label | `High`, `Medium`, `Low` |
| `workstream` | Projects v2 single-select field | `workstream:*` label | Project-specific (open set) |

### Rules

- **Type is always a label** regardless of board presence — it drives PR-title alignment from [project-management:DEC-011-title-formats] and lives on the issue everywhere it's referenced (PR links, issue cards, board cards).
- **Type is mutually exclusive within its axis** — no issue carries two `type:*` labels. An issue spanning multiple kinds picks the dominant kind.
- **Priority and Workstream prefer board fields** when a Projects v2 board exists; fall back to labels when not.
- **Workstream values are project-specific.** The capability mandates the axis; adopters declare the allowed value set in project-side configuration the project-manager reads at runtime. Cross-repo Workstream alignment uses org-level Projects v2 fields when adopters use them.
- **Sub-tasks and Milestones carry no classification axes** — sub-tasks are markdown; Milestones are a separate primitive with their own classification (the close-trigger marker from [project-management:DEC-016-time-bound-containers]).

### Title-prefix alignment + Task-shape restriction

The type axis also drives **the Task's title prefix** per [project-management:DEC-011-title-formats]'s kind-prefix mapping — bug/docs/test/refactor/chore Tasks each carry their own prefix at the title level. The schema's `type` axis declares the mapping under `title_prefix_by_value`:

| Kind value | Task title prefix | PR `<type>` |
|---|---|---|
| `feature` | `[Task]` | `feat` |
| `bug` | `[Bug]` | `fix` |
| `docs` | `[Docs]` | `docs` |
| `test` | `[Test]` | `test` |
| `refactor` | `[Refactor]` | `refactor` |
| `maintenance` | `[Chore]` | `chore` (alternate: `ci` for CI-specific maintenance) |

The Task's prefix matches its kind one-to-one. The closing PR's Conventional Commits `<type>` (the `pr_type_mapping`) also derives from the kind. Both signals stay aligned through the kind label.

**Non-feature kinds are restricted to Task structural shape.** A Feature / Umbrella / EPIC always carries kind `feature` implicitly — they deliver capability work by definition. Filing a Feature / Umbrella / EPIC with `type:bug` (or any non-feature kind) is a hard-reject per `wrong_value_severity`. Multi-PR bug work decomposes into one Task with sub-task checkboxes (per [project-management:DEC-007-checkbox-validation] and `body-format.yaml`'s `sub_task_promotion`) or into a kind=feature Feature whose Tasks happen to fix regressions — see DEC-011's Non-feature-kinds-are-Task-restricted section for the choice.

Multi-issue PRs pick the dominant kind and warn if the closing Tasks' kinds disagree.

### Agent enforcement at filing

The project-manager (via create-issue) refuses a filing if any of the three axes is missing in the project's substrate, if `type:*` or `priority:*` (when a label) is duplicated, or if a value isn't in the project's allowed set. Severities for both `missing_severity` and `wrong_value_severity` are `[validation-severity:hard-reject]`.

### Defaults at filing

When the user doesn't specify:

- `priority:Medium` is the default (encoded as `default_value` on the axis).
- `type:*` is inferred from filing intent (`'file a bug' → type:bug`; `'ship a new capability' → type:feature`). Encoded as `default_inference_strategy`. The agent asks if ambiguous.
- `workstream:*` is inferred from file paths or topic. The agent asks if ambiguous.

## Rationale

The mode-aware substrate gives the capability two adoption paths. Teams with a Projects v2 board get richer classification with native single-select fields and atomic validation; teams without get classification via labels — degraded but functional. The capability works in both modes without splitting into separate capabilities.

Keeping `type:*` always-as-a-label, regardless of mode, is the structural compromise that makes PR-title alignment work. The `type:*` label needs to be visible everywhere the issue is referenced (PR links, issue cards, board); board fields aren't visible from outside the board.

Workstream as a Projects v2 field reflects the team's existing reality — workstreams cut across repos at the org level, and labels can't be shared across repos cleanly. The field model is more natural for the cross-repo case; the label fallback handles the bootstrap case.

### Alternatives considered

- **All three axes as labels.** Rejected — mismatched with the team's actual usage; loses cross-repo Workstream alignment that org-level Projects v2 fields provide.
- **All three axes as board fields (no labels).** Rejected — PR-title alignment breaks (PR doesn't easily see the board field of its closing issue); no-board adopters lose all classification.
- **Workstream as a label with org-level convention.** Rejected — cross-repo label coordination is fragile; the field model is more natural for cross-repo workstreams.

## Implications

- The project-manager reads project-side configuration to know the allowed `type:*`, `priority:*`, and `workstream:*` values for the adopter. Config location is the adopter's project namespace; the agent prompts on first run if missing.
- When a board exists, the project-manager maintains parity between board fields and any legacy label fallbacks during transition.
- Status (the state machine from [project-management:DEC-006-state-machine-and-cascade]) is *also* a Projects v2 field when a board exists, and inferred from native primitives otherwise.
- Adoption work on a project landing this capability includes: rename existing workstream labels to Workstream-field values (when migrating); create the `type:*` and `priority:*` label sets; backfill unlabeled open issues; reconcile any Status board field to the canonical five states.
- The pr_type_mapping is the contract bridging issue-side and PR-side type vocabularies. Adding a new `type:*` value (rare; methodology-fixed set) requires adding a `pr_type_mapping` entry simultaneously.
