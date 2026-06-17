---
id: COR-008
title: Git workflow conventions
status: accepted
date: 2026-05-05
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

The methodology uses git as its source-control substrate. Adopting projects do source-control work — author commits, organise branches, link to issues. Without explicit conventions, every author and every project picks its own format and discipline; the resulting history is harder to read, machine-parse, and review.

This record adopts two universal conventions that apply regardless of the platform (GitHub, GitLab, etc.) the project's git remote lives on. Platform-specific conventions (PR workflow, merge style, branch lifecycle around PRs) are a separate concern and live with the capability that ships them (e.g., the project-management capability per [COR-009](COR-009-pr-workflow.md)).

## Decision

The methodology adopts two git-level conventions, applied to every commit under core governance and recommended for every adopting project.

### 1. Conventional commits as the message format

All commits follow the [Conventional Commits](https://www.conventionalcommits.org) specification:

```
<type>(<scope>): <description>

<body — motivation, context, rationale>

<footer — Closes #N, BREAKING CHANGE: ..., Co-Authored-By: ...>
```

Adopters may extend the standard type vocabulary with project-specific types where the standard set doesn't cover a recurring kind of change (e.g., the methodology's own `decision:` type for decision-record commits). The specific type list and scopes used by a project live in that project's workflow doc, not in this COR.

### 2. Commit-per-logical-unit

Each commit represents one logical change — a single bug fix, a single feature, a single refactor, a single decision record, etc. Multiple unrelated changes split into multiple commits. Closely related changes that genuinely belong together (e.g., a code change and its corresponding test, or a decision and its accompanying doc cross-reference) stay in one commit.

The discipline is to *notice* before committing whether the staged change blends multiple concerns, and to split if it does. Running `git diff --staged` before committing is the simplest practice.

### Operational reference — project-kit's adopted vocabulary

The project-kit corpus uses the following type vocabulary and branch-naming convention. Adopters inherit this by default and may extend it.

**Conventional-commit types in use:**

| Type | When |
|---|---|
| `feat` | new capability or enhancement |
| `fix` | bug fix |
| `docs` | docs-only change |
| `decision` | decision-record added or amended (methodology extension) |
| `chore` | tooling, build, repo housekeeping |
| `refactor` | internal restructuring with no behaviour change |
| `test` | tests added or updated |

**Scope** is optional and matches the kit area / capability when applicable: `decisions`, `agents`, `skills`, `cli`, `rules`, `project-management`, etc. Use scope when the change is contained to one area.

**Body** carries motivation and context — *why* this change, what it depends on. Free-form prose, wrapped at a sensible column.

**Footer** carries:
- `Closes #N` for issue links.
- `BREAKING CHANGE: ...` for breakage notes.
- `Co-Authored-By: ...` trailers.

**Default branch.** The methodology's default branch is **`main`**. New repositories initialise with `main`; existing projects with `master` rename to `main` as part of first-install reconciliation.

**Branch naming.** Feature branches follow `<type>/<issue-number>-<slug>`:

- **`<type>`** matches the conventional-commits type list above. Pick the type that matches the *primary* nature of the work — the dominant commit's type, when the branch carries a mix.
- **`<issue-number>`** is the related GitHub issue. **The branch must have a related issue.** If work surfaces during a session and no issue exists, file one before creating the branch. The PR template's `Closes #<issue-number>` line then matches the branch name automatically.
- **`<slug>`** is kebab-case shorthand of the work — 2–4 words, short enough to keep `git branch` and `gh pr list` listings self-documenting, long enough to identify the change without opening the PR.

**Examples:**

- `feat/28-pr-a-python-scaffold`
- `fix/26-accept-prj-004`
- `decision/5-implementation-language`

For multi-PR initiatives, every PR's branch references the same umbrella issue (`feat/28-pr-a-...`, `feat/28-pr-b-...`); the slug distinguishes the slice.

## Rationale

**Why conventional commits.** It's the de-facto industry standard, well-documented, and machine-parseable — tooling for changelogs, release automation, and history navigation can rely on the format. The format is also self-disciplining: writing the type forces the author to name *what kind* of change this is, which often surfaces commits that should be split because they're more than one type.

**Why commit-per-logical-unit.** Atomic commits are easier to review, easier to revert, easier to bisect, and produce a more useful history. A kitchen-sink commit conflating multiple concerns loses these properties. The discipline also tends to produce smaller, more focused PRs downstream.

**Why a project-extensible type vocabulary.** The standard conventional-commits type list (`feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`) doesn't cover everything a methodology project does — `decision:` is the obvious example. Allowing project extensions keeps the standard's discipline while accommodating real domain variation.

### Alternatives considered

- **No commit-message convention at all.** Rejected — leaves every author free to pick a format, producing inconsistent history that resists automation.
- **A custom format invented by the methodology.** Rejected — pays the cost of a non-standard format with none of the existing tooling benefits.
- **Strict conventional commits with no project extensions.** Rejected — `decision:` (and any future project-specific kinds) would have to squeeze into `docs:` or similar, losing its category signal in commit logs.
- **Allowing multi-purpose commits when "they're really related."** Rejected — every multi-purpose commit feels related to its author. The discipline depends on a clean default; exceptions erode it.

## Implications

- **Going forward, all commits in the methodology corpus follow this format.** Existing history is not rewritten.
- **The operational reference** (type list, scope vocabulary, branch naming) lives in this COR's Decision section. The single source of truth for git conventions is here.
- **`CLAUDE.md` cross-references this COR** so the disposition is loaded every session.
- **Platform-specific conventions** — PR template, merge style, branch lifecycle around PRs — live in the capability that ships them (per [COR-009](COR-009-pr-workflow.md), the project-management capability ships these). This COR covers only git-level rules.
- **Adopters inherit the conventions** via propagation. Project-specific type extensions go in the adopter's own project-side rules doc rather than amending this COR.
