---
id: DEC-011
title: Issue titles use `[Type]` prefix and plain English; PR titles use Conventional Commits
status: accepted
date: 2026-05-21
author: Ales Kalfas
source:
  upstream: pm-workflow
  upstream_id: MET-010
  commit: 9d1f0237f5d5778ed9811c72f22ae8268e5faff3
  captured_at: 2026-05-21
---

## Context

Issue titles and PR titles are read in different contexts and serve different readers. Issue titles appear on project boards, in issue lists, in PR-issue linkbacks — places where humans browse and skim. PR titles appear in `git log` after squash-merge, on the PR detail page, and feed tooling that parses commit history. The two need different shapes: trying to make one format fit both produces awkward compromises (issue titles polluted with Conventional Commits' `type(scope):` prefix; PR titles becoming verbose `[Type]`-bracketed phrases that don't parse cleanly).

The capability has to pin each surface to its appropriate format and give the project-manager the regexes needed to enforce both at filing/opening time.

## Decision

### Issue title format

```
[Type-or-Kind] <plain English sentence>
```

- **For Features / Umbrellas / EPICs** — the prefix matches the structural role: `[EPIC]` (all-caps), `[Feature]` / `[Umbrella]` (title-case). These structural types are reserved for clusters of work that deliver a capability (Feature), bucket related tasks (Umbrella), or scope a multi-quarter outcome (EPIC). Their kind is always `feature` implicitly.
- **For Tasks** — the prefix matches the *kind* value from [project-management:DEC-012-classification-axes]'s type axis, not the literal word "Task." The mapping:

  | Kind (`type:*` label) | Title prefix | Conventional Commits |
  |---|---|---|
  | `feature` | `[Task]` | `feat` |
  | `bug` | `[Bug]` | `fix` |
  | `docs` | `[Docs]` | `docs` |
  | `test` | `[Test]` | `test` |
  | `refactor` | `[Refactor]` | `refactor` |
  | `maintenance` | `[Chore]` | `chore` |

  The Task's kind drives the prefix at the title level (visible on the board at a glance) AND drives the closing PR's Conventional Commits `<type>` per the `pr_type_mapping`. The two are kept in sync by the agent at filing time.

- **Sentence** is plain English, imperative or descriptive. Written for a human browsing the board, not for git history.
- No `scope:` colon prefixes (reserved for PRs).
- No em-dashes as separators.
- No Conventional Commits formatting.
- Soft length guideline: ~30+ chars after the prefix; the validator warns below that.

Per-issue-type patterns are encoded in [`schemas/titles.yaml`](../schemas/titles.yaml)'s `formats` mapping (`issue-epic`, `issue-feature`, `issue-umbrella`, `issue-task` entries — the latter accepts any of the six kind-driven prefixes via alternation, with the kind-prefix match enforced by `validate-issue` cross-checking against the issue's `type:*` label).

### Non-feature kinds are Task-restricted

A Feature / Umbrella / EPIC always has kind `feature` — they deliver capability work by definition. Bugs, docs work, tests, refactors, and chores live as Tasks, with the kind determining the title prefix per the mapping above.

If "bug" work seems to need multi-PR Feature-scope, the right shape is either: (a) one Task with sub-task markdown checkboxes per sub-PR (per [project-management:DEC-007-checkbox-validation] and `body-format.yaml`'s `sub_task_promotion` block) — appropriate when the sub-changes share one acceptance criterion; or (b) a kind=feature Feature whose Tasks happen to fix regressions — appropriate when the cluster delivers a coherent capability beyond just "fix the bug." Filing a Feature with `type:bug` is a hard-reject — the methodology refuses the kind/structural mismatch at create-issue and at validate-issue.

### Milestone title format

Milestones are a separate GitHub primitive with **no `[Type]` prefix**. Recommended: short purpose-based name, optionally with an `M<n>` sort prefix (e.g., `M1 — CLI walkthrough complete`, `Q2 2026 release`, `v0.2 GA`). Pure-numeric names (`M1`, `M2`) without semantic content are discouraged — warning-level. Encoded as the schema's `milestone` entry with a null `pattern` (free-form by design).

### PR title format

```
<type>(<scope>): <summary>
```

Conventional Commits. The `<type>` matches the closing Task's `type:*` label per [project-management:DEC-012-classification-axes]' `pr_type_mapping`. `<scope>` is recommended but not mandated. `<summary>` is short (~50 chars), imperative mood, lowercase, no trailing period.

Multi-issue PRs pick the dominant type and surface a warning if the closing issues' types disagree — see [project-management:DEC-013-branch-and-pr-conventions]. Encoded as the schema's `pr` entry.

### Sub-tasks

No title format — sub-tasks are markdown checkboxes per [project-management:DEC-007-checkbox-validation], not issues.

### Agent enforcement at filing

The project-manager (via the create-issue skill) runs the per-surface validations encoded in each title-format entry's `validations` list:

- Issue titles: hard-reject if title doesn't start with the correct `[Type]`, contains a `scope:` colon prefix, or matches a Conventional Commits pattern. Warning if title length < ~30 chars after the prefix.
- PR titles: hard-reject if title doesn't match the Conventional Commits regex; hard-reject if `<type>` doesn't match the closing Task's `type:*` label (multi-issue PRs with mixed types warn instead); warning for non-lowercase summary or trailing period.

## Rationale

Pinning each surface to its appropriate format makes the board easier to scan and `git log` more parseable. The `[Type]` prefix on issues — visible in any list view — surfaces the structural role at a glance, which matters more for browsing than the title's exact wording. Conventional Commits on PRs feeds the team's git tooling and changelog generation without manual mapping.

Splitting the surfaces also keeps the title regexes simple. A single unified format would have to cover both readers and end up matching too loosely to be useful for either.

### Alternatives considered

- **Unified format (Conventional Commits everywhere).** Rejected — issue titles become noisy and unreadable for board browsing; structural type (`feat` vs `[Feature]`) gets conflated with the `type:*` classification axis.
- **Free-form issue titles (no `[Type]` prefix).** Rejected — loses the structural-role-at-a-glance affordance; produces inconsistent board views.
- **Title includes parent ref.** Rejected — ancestry lives in the body's first line per [project-management:DEC-005-linking-and-containment]; titles stay focused on the change being described.
- **Structural type as prefix for Tasks regardless of kind (`[Task]` always).** Rejected — buries the kind under a label that's invisible at title-list level. The board scan loses the bug/docs/test/refactor signal. Kind-driven prefixes for Tasks make the at-a-glance distinction first-class without compromising the structural role for clusters (Feature/Umbrella/EPIC keep their structural prefixes).
- **Kind-driven prefixes for Features/Umbrellas/EPICs too.** Rejected — Features/Umbrellas/EPICs deliver capability work by definition; surfacing a kind dimension on them obscures the structural-type signal that distinguishes clusters from PRs. Constraining non-feature kinds to Task shape keeps the model tight.

## Implications

- The create-issue skill scaffolds the title prefix per the type's `title_prefix` + `title_case` from [`schemas/issue-types.yaml`](../schemas/issue-types.yaml), and validates the full title against the corresponding `titles.yaml` entry.
- The validate-body skill re-runs title validation at edit time (titles edit through GitHub UI; agent catches drift on next interaction).
- The PR title's Conventional Commits `<type>` is derived from the closing Task's `type:*` label via [project-management:DEC-012-classification-axes]' `pr_type_mapping`. Multi-issue PRs with mixed types pick the dominant value and warn.
- Milestone titles are flexible by design — different adopter teams use different conventions (sprint numbers, release names, calendar dates) — see [project-management:DEC-016-time-bound-containers].
- The templates pre-fill the `[Type] ` prefix on each issue template (`templates/{epic,feature,umbrella,task}.md`) and document the PR-side Conventional Commits format in `templates/pr.md`.
