---
name: Task
about: One PR-sized unit of implementation work. See [project-management:DEC-004-six-level-hierarchy].
title: '[Task] '
labels: ['type:feature']
---

<!--
First line below must be the ancestry ref per [project-management:DEC-005-linking-and-containment].
For a Task: `Feature: #X` or `Umbrella: #X` or `EPIC: #X` — whichever is direct parent.
-->

Feature: #

## What

The concrete change being made. Outcome-focused, not implementation-focused.

## Acceptance criteria

<!--
Checkboxes — validated when ticked; all must be ticked before the Task can close
(per [project-management:DEC-007-checkbox-validation]).
Concrete claims tied to code. Reviewer should be able to verify each one.
-->

- [ ]
- [ ]

## Doc impact

<!--
Per [project-management:DEC-015-doc-update-obligations]. One of two shapes:

Shape A — docs need updating (checkboxes; same close-gate rules apply):
  - [ ] Update README.md "Install" section
  - [ ] Update CONTRIBUTING.md to document the --workspace flag

Shape B — no doc impact (one-line justification REQUIRED — "no doc impact" alone is not accepted):
  No doc impact: internal refactor only; no behavioural change observable from any user-facing surface.

Pick one shape. Edit this section to match.
-->

- [ ]

<!--
Optional sections you may add:
  ## Sub-tasks            — markdown checkboxes inside the Task (sub-task promotion rules apply per body-format.yaml)
  ## Implementation notes — hints, gotchas — but no recipe (per [project-management:DEC-010-issue-body-minimum-structure])
  ## Related              — links to prior Tasks, design docs

Forbidden in this body (per [project-management:DEC-010-issue-body-minimum-structure]):
  - file:line references
  - implementation recipes (use a PR or design doc)
  - predicted decision IDs
-->
