---
id: DEC-016
title: Time-bound containers — Milestone semantics project-defined; Iteration optional; rollforward cascade for date-based close
status: accepted
date: 2026-05-21
author: Ales Kalfas
source:
  upstream: pm-workflow
  upstream_id: MET-015
  commit: 9d1f0237f5d5778ed9811c72f22ae8268e5faff3
  captured_at: 2026-05-21
---

## Context

The hierarchy from [project-management:DEC-004-six-level-hierarchy] places Milestone at the top as the time-bound container. The methodology has to accommodate Milestone usage across different planning cadences — sprint (typically 2 weeks), release wave (multi-week), quarter — without prescribing one. GitHub's Projects v2 also offers an *Iteration* field designed for sprint timeboxes, which the capability has to recognise as an optional secondary tier.

Date-based Milestones present a specific cascade question: when the Milestone closes on its due date with open children, those children mustn't close (their work isn't done; they're just scheduled into a later container). The capability needs a rollforward rule that's different from the normal closure cascade in [project-management:DEC-006-state-machine-and-cascade].

## Decision

### Project-shape applicability — when Milestones apply

Milestones in this methodology serve two distinct roles depending on project shape: a **time-bound container** (sprint / quarter / release window) or an **outcome bundle** (a group of related EPICs that close together). EPICs (per [project-management:DEC-004-six-level-hierarchy]) are always outcome-bound; Milestones flex by close-trigger mode.

| Project shape | What fits | Close trigger | Indicators |
|---|---|---|---|
| **Time-driven** | Milestones (*when*) + EPICs (*what within the window*). Rollforward cascade applies. | `date-based` | Sprint cadence; quarterly OKRs with deliverable targets; scheduled releases (`Q2 2026 GA`, `v3.0 by year-end`); board-level expectations of "shipped by X date". |
| **Feature-driven with theme grouping** | Milestones (*outcome bundle*) wrapping related EPICs (*one outcome each*). Milestone closes when all child EPICs close. | `content-based` | Release-when-ready; no calendar; but related outcomes group naturally under a single closable bigger-deliverable name. |
| **Feature-driven, flat** | EPICs alone. No Milestones. | n/a | Each EPIC IS the deliverable; no need for a wrapping bundle. |
| **Hybrid** | A Milestone wraps related EPICs; closes on either the date or all children — whichever fires first. | `either` | Outcome bundle with a target date (e.g., a v1.0 GA targeting a specific quarter). |

The choice is per-project — set at adoption time and revisited only when the project's shape changes (a flat feature-driven project starts theming work into bundles; a time-driven team drops sprints in favour of release-when-ready). Multiple shapes can also coexist in one repo via the categories mechanism below.

**Closability is the test** — every Milestone, whatever its shape, must have a definable "done" state. A milestone titled `Methodology hardening` or `Adopter onboarding` that could "live forever" is a category not a deliverable; the right shape there is workstream-level grouping (`workstream:methodology-hardening`) rather than a Milestone.

### Milestone categories — mandatory declaration before use

A project that uses Milestones **must declare at least one category** in `project/config.yaml`'s `milestone_categories:` block before any Milestone is created. The methodology does not ship an implicit default — *if you use the primitive, you declare what it means in this project first*. Filing a Milestone whose title doesn't match a declared category's `title_format` is a refusal.

Each category has a title format with optional numbering, a default close-trigger, and a one-line semantic description:

```yaml
milestone_categories:
  phase:
    title_format: "Phase {n}: {name}"
    close_trigger_default: date-based
    description: "Time-bound sprint or planning window."
  milestone:
    title_format: "Milestone {n}: {name}"
    close_trigger_default: content-based
    description: "Outcome bundle; closes when all child EPICs close."
  release:
    title_format: "v{n} GA"
    close_trigger_default: either
    description: "Versioned release window."
```

Projects with a single purpose declare a single category (often named `milestone`). Projects with mixed purposes declare multiple. Either way, the declaration exists before the first Milestone is filed — adopters get to see exactly which categories their methodology supports without having to read the methodology DEC.

Each instance's explicit `Close trigger:` body line still applies and overrides the category's default; the category sets the *intent* signal at the title level, the body line is the authoritative per-instance declaration.

**Validation severity** for filing a Milestone outside the declared categories: `[validation-severity:hard-reject]`. The methodology refuses with a structured error naming the declared categories and pointing the author at `project/config.yaml`'s `milestone_categories:` block.

**Feature-driven flat projects** (no theme grouping; EPICs alone) do not declare categories because they do not use Milestones at all. The declaration requirement applies only when Milestones are in use.

### Numbering as sort prefix

Numbers in milestone titles (`Milestone 1: ...`, `Phase 5: ...`, `M1 — ...`) are **optional** and serve **planned-order surfacing** for human PMs scanning the milestone list. Conventions:

- **Optional**: a milestone with no number (`Self-host project-kit pm capability cleanly`) is still valid.
- **Paired with semantic content**: pure-numeric names (`M1`, `Milestone 5`) without descriptive content are discouraged — readers can't tell what the milestone covers.
- **Sort, not strict sequence**: gaps are fine (skipping `Milestone 4`); renumbering on insertion is not required. The number says "this is roughly #N in planning order," not "this is mandatory step N."
- **Per category**: each category numbers independently (Phase 5 + Milestone 1 coexist; the category prefix disambiguates).

### Two time concepts, one mandatory

Encoded in [`schemas/time-containers.yaml`](../schemas/time-containers.yaml)'s `containers` mapping:

| Concept | Substrate | Required | Typical duration |
|---|---|---|---|
| **Milestone** | Native GitHub Milestone | Yes for time-driven and hybrid projects (per the project-shape table above); skipped entirely for feature-driven | Project-specific (sprint, release wave, quarter) |
| **Iteration** | Projects v2 Iteration field | No — optional secondary | Project-specific |

Milestone structural facts (encoded in `structural_facts`):

- Every Milestone has a name, an optional due date, and a close condition.
- An issue is assigned to **at most one Milestone** at a time.
- Milestone field is part of every issue's classification per [project-management:DEC-012-classification-axes].
- Milestones do not nest — flat, one-level.

Milestone title format is project-flexible per [project-management:DEC-011-title-formats]; the schema's `milestone.title_format_ref` carries the typed token `[titles:milestone]`.

Semantics (sprint vs. release vs. quarter) is per-project, declared on the Milestone itself via the close-trigger marker.

### Close triggers — declared on the Milestone first line

The Milestone description opens with a `Close trigger:` line. Three valid values, encoded as the schema's `milestone.close_triggers` list:

| Value | Behaviour | Rollforward? |
|---|---|---|
| `date-based` | Closes when due date passes (or manual early close). Open children roll forward to the next Milestone. | Yes |
| `content-based` | Closes only when every child is closed. No rollforward (by definition no open children). | No |
| `either` | Closes on whichever fires first. Rollforward only when the date trigger fired. | Conditional |

Marker pattern: `^Close trigger: (date-based|content-based|either)$`. Severity for a new Milestone filing missing or malformed marker: `[validation-severity:hard-reject]`. Severity for an existing Milestone read without the marker: `[validation-severity:warning]` — the agent infers (has due date → date-based; no due date → content-based) and offers to write the marker into the description.

Optional `Rollforward target: <Milestone>` second line on date-based Milestones declares an explicit rollforward destination. Default (when absent) is the next-numbered open Milestone; ambiguous candidates prompt the user at rollforward time.

### Rollforward cascade for date-based Milestone close

Encoded in the schema's `milestone.rollforward_behaviour`:

1. The Milestone closes regardless of how many children are still open. Date is the trigger; no exception.
2. Open children are reassigned to the rollforward-target Milestone — not closed. State is preserved (a Task in `In Progress` stays `In Progress`; an EPIC in `Backlog` stays `Backlog`).
3. Closed children stay assigned to the closing Milestone as a historical record of what shipped.
4. Cascade propagates upward — parents (Features, Umbrellas, EPICs) of rolled-forward open children move with the open children if the parent was also assigned to the closing Milestone. If a parent has both open and closed children, the parent moves with the open ones; the closed ones stay tagged to the old Milestone as a record of partial delivery.

### Pre-close triage

The project-manager is proactive as a date-based Milestone approaches its due date. At ~N days before the due date (project-configurable; default 3), the agent surfaces a triage prompt listing the Milestone's open children. The user can close items as won't-do (with reason), manually reassign to a different Milestone, or let automatic rollforward run at date-close. Triage is **courtesy, not a gate** — encoded as `is_gate: false` on the schema's `pre_close_triage` block.

### Iteration as optional secondary

Three usage patterns recognised in the schema's `iteration_usage_patterns`:

- **Pattern A** — Milestone = release wave; Iteration = sprint. Use when planning at two granularities.
- **Pattern B** — Milestone = sprint; no Iteration. The team's current setup.
- **Pattern C** — Milestone = sprint; Iteration = themed cluster within the sprint. Rare.

When Iteration carries the sprint semantic, the same rollforward cascade applies on its close.

### Interaction with closure cascade

Rolled-forward open children do **not** count as closed for the parent's closure-cascade eligibility from [project-management:DEC-006-state-machine-and-cascade]. The closure cascade only fires when actually-closed children cross the eligibility threshold. A parent with rolled-forward open children stays open and follows them forward; the closure-cascade prompt fires only when the last *closed* child crosses the threshold.

Encoded as `cascade_interaction.rolled_forward_descendants_skip_closure_cascade: true`.

## Rationale

Milestones serve different purposes in different teams. A team-wide methodology that hard-coded "Milestone = quarter" would mismatch the team's actual sprint usage; one that hard-coded "Milestone = sprint" would mismatch release-driven adopters. Letting projects declare semantics per-Milestone preserves both readings.

The `Close trigger:` marker on the Milestone's first line — mirroring the textual first-line ancestry ref from [project-management:DEC-005-linking-and-containment] — keeps the trigger declarative and machine-readable. The project-manager reads it; humans see it inline; no heuristic inference is needed when the marker is present.

The rollforward cascade reflects how sprints actually work: a sprint ends on its date regardless of completion; unfinished work continues in the next sprint; the sprint itself becomes the historical record of what shipped. Closing the open children when their parent Milestone closes would mis-model sprints as release-blockers.

### Alternatives considered

- **Hard-code Milestone semantics (always sprint, or always release wave).** Rejected — forces a single semantics on a team-wide methodology serving projects with different planning cadences.
- **Inferred close trigger from due-date presence only (no marker).** Rejected — loses explicit declaration; ambiguous for Milestones with dates that aren't strictly date-driven.
- **Close children when their date-based Milestone closes.** Rejected — mis-models sprints; would force every unfinished Task to be reopened in the next Milestone, losing state.
- **No rollforward (children become unassigned).** Rejected — surfaces all open children at `Todo` state, which is wrong — they're still in-flight, just shifted to a later Milestone.

## Implications

- **Project-shape applicability is the first gate** — adopters whose shape doesn't call for Milestones (feature-driven flat) skip every implication below and rely on EPICs (per [project-management:DEC-004-six-level-hierarchy]) alone.
- **Adopter config must declare `milestone_categories:`** before any Milestone is created. At least one category is required if Milestones are used at all. Filing a Milestone outside the declared categories is a hard-reject. Feature-driven flat projects (EPICs alone) don't declare categories because they don't use Milestones.
- **Numbering in titles is optional and not strict-sequence** — surfaces planned order for human PMs scanning; gaps fine; per-category independent.
- The validate-body skill checks new Milestone filings for the `Close trigger:` marker — hard reject if missing or malformed.
- The project-manager's pre-close triage routine fires N days before each date-based Milestone's due date.
- Rollforward is mechanical — the project-manager reads the Milestone's children, partitions into open/closed, reassigns the open ones (and their relevant ancestors) to the rollforward target, leaves the closed ones tagged historically.
- Iteration field is recognised when present on a Projects v2 board; the agent maintains it the same way it maintains Milestone where applicable. Capability doesn't mandate Iteration usage.
- This DEC interacts with [project-management:DEC-006-state-machine-and-cascade]'s closure cascade — date-based Milestone close does *not* trigger the "last open child closes → parent eligible" cascade for the children rolled forward; only closed children count.
- Adopting projects declare close-trigger semantics for every existing Milestone (or let the agent infer + warn on first interaction).
