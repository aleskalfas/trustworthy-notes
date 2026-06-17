<!--
PR title format (per [project-management:DEC-011-title-formats]):
  <type>(<scope>): <summary>

<type> matches the closing Task's `type:*` label
(per [project-management:DEC-012-classification-axes]):
  type:feature     → feat(<scope>): ...
  type:bug         → fix(<scope>): ...
  type:docs        → docs(<scope>): ...
  type:test        → test(<scope>): ...
  type:refactor    → refactor(<scope>): ...
  type:maintenance → chore(<scope>): ...  (or ci(<scope>) for CI-specific)

<scope> is recommended but not required. Omit for cross-cutting changes.
<summary> is short (~50 chars), imperative mood, lowercase, no trailing period.
-->

Closes #

## Summary

<!-- 1–3 paragraphs: the why and how. The what is in the closing Task's body — no duplication. -->

## Test plan

<!--
Recommended per [project-management:DEC-013-branch-and-pr-conventions]. Use checkboxes when the testing strategy isn't obvious.
Standard close-gate rules apply: validate at tick, all ticked before merge
(per [project-management:DEC-007-checkbox-validation]).
Omit this section entirely if the change is trivial (typo fix, etc.).
-->

- [ ]

## Doc impact

<!--
Required per [project-management:DEC-015-doc-update-obligations]. Mirror what this PR actually changed.

Shape A — list the doc updates this PR made:
  - Updated README.md "Install" section (commit 4a3b2c1).
  - Updated CONTRIBUTING.md to document the --workspace flag (commit 5e8f3a2).
  - No CHANGELOG.md entry needed — already covered in unreleased.

Shape B — no doc impact (one-line justification REQUIRED):
  No doc impact: internal refactor only; no behavioural change observable.

Pick one shape and edit this section to match.
-->

-
