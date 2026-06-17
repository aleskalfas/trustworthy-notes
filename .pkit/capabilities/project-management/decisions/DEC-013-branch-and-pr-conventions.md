---
id: DEC-013
title: Branch and PR conventions — naming, Conventional Commits, squash-merge, force-push policy, integration branches
status: accepted
date: 2026-05-21
author: Ales Kalfas
source:
  upstream: pm-workflow
  upstream_id: MET-012
  commit: 9d1f0237f5d5778ed9811c72f22ae8268e5faff3
  captured_at: 2026-05-21
---

## Context

Implementer work produces branches and PRs. The capability has to fix these conventions tightly enough that the project-manager can derive branch names, generate PR titles, and validate everything at PR-open time without ambiguity. Looser conventions push the validation burden onto humans and produce inconsistencies (commit type mismatches with `type:*` label, missing `Closes #N`, branch names that don't tie back to issue numbers).

This DEC also covers the **integration-branch** construct — an opt-in long-running shared branch rooted at a single owning issue, used when a multi-Task outcome needs to assemble before promoting to `main`.

## Decision

### Branch naming

```
<conv-type>/<issue-number>-<slug>
```

- **`<conv-type>`** — Conventional Commits prefix derived from the closing Task's `type:*` label per [project-management:DEC-012-classification-axes]' `pr_type_mapping`.
- **`<issue-number>`** — the GitHub issue number of the Task the branch closes.
- **`<slug>`** — kebab-case slug derived from the issue title via the schema's `branch_slug_derivation` procedure (drop `[Type]` prefix → lowercase → replace non-alphanumerics with hyphens → collapse → truncate at word boundary to ~50 chars → strip leading/trailing hyphens).

Pattern, slug-derivation steps, and worked examples are encoded in [`schemas/git-conventions.yaml`](../schemas/git-conventions.yaml). One branch per Task; EPIC/Feature/Umbrella/Milestone/sub-task do not get branches.

### Base branch

Default `main`; project-configurable. Tasks whose closing issue carries an `Integration:` marker target the named integration branch instead — see the integration-branches block below.

### PR title

Conventional Commits — handled in [project-management:DEC-011-title-formats] and encoded in [`schemas/titles.yaml`](../schemas/titles.yaml)'s `pr` entry. This DEC does not duplicate it.

### PR body

Required:

- At least one `Closes #N` / `Fixes #N` / `Resolves #N` reference. Recommended placement is the **first line** of the body, mirroring the issue-body parent-ref pattern from [project-management:DEC-005-linking-and-containment].
- A `## Doc impact` section per [project-management:DEC-015-doc-update-obligations].

Recommended (warning-level if absent):

- A short description (why and how, 1–3 paragraphs). The *what* is in the closing Task's body.
- A `## Test plan` section with checkboxes per [project-management:DEC-007-checkbox-validation].

Forbidden: pasted issue-body content; Conventional-Commits format duplicated in a body header.

### Multi-issue PRs (exception path)

Allowed when work is tightly coupled. Rules encoded as `multi_issue_pr_rules` in the schema:

- All closing issues share the same parent (hard-reject if not).
- All have compatible `type:*` labels — mixed types warn and the PR's `<type>` uses the dominant value.
- PR body explicitly lists every closure keyword (`Closes #42, closes #43`).

### Merge mechanics

**Squash-merge with `--delete-branch`** — one PR → one commit on the base branch. Equivalent to `gh pr merge --squash --delete-branch`. Squash-commit subject = PR title (Conventional Commits); squash-commit body = PR body (preserves context in `git log`). No merge-commits, no rebase-merge, no cherry-picks.

### Force-push policy

- Allowed on feature branches before first review (useful for tidying history).
- Forbidden after a human review lands — invalidates the reviewer's context. Bypassable with audit-trail comment for unusual cases.
- Forbidden on `main` and any shared branch (including integration branches) — hard reject, no exceptions.
- `--no-verify` not used unless the user explicitly authorises — bypassable with audit-trail.

### Integration branches (opt-in)

A long-running outcome that needs to assemble multiple Tasks (and sometimes Features) before promoting to `main` uses an **opt-in integration branch** rooted at a single owning issue (EPIC, Feature, or Umbrella). Encoded in the schema's `integration_branches` block:

- **Designation.** PM or Implementer designates the owning root explicitly by placing `Integration: integration/<slug>` as the first line of the owning issue's body — above the parent-ref, no blank line between. `<slug>` follows the same kebab-case derivation as Task slugs. Designation is never automatic.
- **Branch creation.** On designation, the project-manager creates `integration/<slug>` off `main` at HEAD. The branch is shared and long-running — same no-force-push rule as `main`.
- **Propagation to descendants.** On designation, the project-manager walks the owning issue's sub-issue tree and stamps the same `Integration:` line at the top of every descendant body. Descendants filed later inherit the line at creation while the owning issue remains designated. Removing the marker from a descendant is a scope-changing edit gated by author authorisation per [project-management:DEC-009-living-documents] — bypassable-with-audit severity.
- **PR target dictated by marker.** When the project-manager opens a PR for a marked issue, the PR targets `integration/<slug>`, not `main`. Targeting `main` while the marker is present is bypassable-with-audit — the clean off-ramp is to remove the marker first (author-authorised).
- **Cascade and closure.** Marked Tasks close on merge into `integration/<slug>` via the normal `Closes #N` keyword. The owning issue becomes eligible-to-close per [project-management:DEC-006-state-machine-and-cascade] when every marked descendant closes. Final closure is a separate `integration/<slug>` → `main` PR with `Closes #<owning>` — squash-merged with `--delete-branch`. The integration branch is deleted with that merge.
- **Squash invariant retained at both hops.** PRs into the integration branch and the final PR into `main` are both squash-merged with `--delete-branch`. One PR → one commit, applied uniformly.

## Rationale

Squash-merge with `--delete-branch` produces a clean linear history where each PR is one commit on the base branch. The squash subject (= PR title, Conventional Commits) feeds straight into changelog tooling. Intermediate commits on the feature branch are working-state that gets compacted away — no archaeology in `main`.

`<conv-type>/<issue-number>-<slug>` as a branch format gives the project-manager everything it needs: type alignment with the `type:*` label, issue linkage by number, human-readable hint by slug.

Force-push allowed before review and forbidden after is the standard reviewer-context-preservation discipline.

Integration branches are opt-in because most outcomes don't need them — a Feature with a handful of Tasks usually ships fine via direct-to-`main` Task PRs. The construct earns its complexity only when several Tasks (or Features) genuinely have to land together before promoting. Making it explicit and owner-designated (rather than inferred or always-on) keeps the default path simple and prevents accidental branching topologies. The body-marker propagation is what makes the construct safe under filing: a Task filed mid-flight inherits the marker automatically, so the project-manager never opens a stray direct-to-`main` PR from a marked scope.

### Alternatives considered

- **Merge-commits or rebase-merge instead of squash.** Rejected — both produce multi-commit `main` histories that don't map cleanly to PRs.
- **No mandatory `Closes #N`.** Rejected — auto-close on merge is the methodology's primary closure path; making it optional would break the cascade trigger.
- **Branch name without issue number.** Rejected — number makes branches findable by issue ID, which the agent relies on for `work:start` / `work:done` flows.
- **Allow force-push anytime.** Rejected — invalidates reviewer context post-review.
- **Always-on integration branch per parent.** Rejected — forces every multi-Task scope through a two-hop merge.
- **Label-based integration marker (`integration:<slug>` label).** Rejected — labels are a parallel projection that drifts from the body. The body-line marker mirrors the ancestry-ref pattern from [project-management:DEC-005-linking-and-containment] — one source of truth.

## Implications

- The project-manager generates branch names from the closing Task's title and `type:*` label per the schema's `branch_slug_derivation`. Branch-name mismatches at PR-open time are hard-reject.
- The project-manager validates the PR title and body against [`schemas/titles.yaml`](../schemas/titles.yaml)'s `pr` entry and [`schemas/git-conventions.yaml`](../schemas/git-conventions.yaml)'s `pr-body` entry at PR-open time.
- The merge step is gated by [project-management:DEC-006-state-machine-and-cascade]'s authorisation rule and [project-management:DEC-007-checkbox-validation]'s close-gate before the squash-merge fires.
- The integration-branch construct adds project-manager obligations on designation (create branch, stamp descendants), on filing (descendants inherit marker), on PR-open (target the integration branch), and on the final integration → main PR (close the owning root, trigger ancestor cascade).
- Integration branches inherit `main`'s no-force-push rule (shared branch).
- The pr-body shape is instantiated in `templates/pr.md`.
