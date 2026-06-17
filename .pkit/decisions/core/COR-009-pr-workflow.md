---
id: COR-009
title: Pull-request workflow conventions
status: accepted
date: 2026-05-05
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

COR-008 established universal git-level conventions (conventional commits, commit-per-logical-unit). Those apply regardless of remote-hosting platform. This record captures the platform-specific layer for projects whose remote lives on a platform with pull-request semantics (GitHub, GitLab, Bitbucket, etc.) — primarily, how a feature branch becomes a change on the default branch.

The github-issues bundle's templates already imply some of these conventions (`Closes #N` in the PR template, `kind:*` labels matching commit types). This record makes them explicit and adds the choices the templates can't carry on their own.

## Decision

Adopting projects using PR-based platforms follow the conventions below. The convention is the recommended default; adopters with strong reasons may diverge, but each divergence is its own decision worth recording.

### 1. Squash-merge as the default merge style

Pull requests are merged into the default branch using **squash-merge**. Each PR becomes one commit on the default branch.

- Within the feature branch, developers commit naturally per COR-008 (one logical unit per commit).
- At merge time, multiple commits collapse into one squashed commit whose message is taken from the PR's title and body.
- The default branch's history is therefore linear, with one commit per merged PR.

### 2. PR title follows conventional commits

Because the squash commit's subject is the PR title, **the PR title must follow conventional commits** (`<type>(<scope>): <description>`, per COR-008). The PR body becomes the squash commit's body.

### 3. PR body cites the issue and any decisions

The PR body, per the github-issues bundle's `PULL_REQUEST_TEMPLATE.md`, opens with `Closes #<issue-number>` and includes What / Why / How sections. Decision references (COR-NNN, PRJ-NNN) belong in Why, or in the closing checklist when the PR introduces or amends a record.

### 4. Feature branches are short-lived and deleted after merge

A feature branch lives only as long as its PR. After squash-merge, the branch is deleted on the remote and locally. Long-lived feature branches accumulate drift; treating branches as ephemeral keeps integration friction low.

### 5. PRs are recommended, not enforced

Solo work may go directly to the default branch; collaborative work uses PRs for review and discussion. The methodology ships PR workflow as the recommended default but does not enforce it via tooling at this scale. Multi-author projects typically configure platform-level branch protection to require PRs.

## Rationale

**Why squash-merge.** Squash collapses the branch's commits into one commit on the default branch. Pros: linear history (every commit on the default branch is a complete logical change), trivial revert (revert the squash commit), reliable bisect. Cons: individual within-branch commits are not preserved on the default branch. The trade-off is right because (a) within-branch commits are valuable for review but not for long-term history, and (b) COR-008's per-logical-unit discipline operates at branch level — squash carries that discipline forward to the PR level.

**Why merge-commit and rebase-merge are not the default.** Merge commits preserve full branch history but produce noisy default-branch history (every PR adds N commits plus a merge node). Rebase-merge avoids the merge node but still inflates the default branch with within-branch commits. Both fight the "clean linear history, one commit per PR" goal that squash provides. Adopters with strong reasons (e.g. preserving per-commit attribution for compliance) can override at branch-protection level.

**Why PR title is load-bearing.** Because squash derives its commit subject from the PR title, an inconsistent or non-conventional title produces non-conventional history. The COR-008 format requirement transfers from individual commits to PR titles when squash is the merge style.

**Why short-lived branches.** Long-lived branches drift from the default branch, accumulate merge conflicts, and obscure ownership. The discipline is "open the PR early, merge as soon as ready, delete the branch."

**Why PRs are not enforced at this scale.** Tooling mandating PRs (branch protection, required reviews) makes sense for multi-author projects; for solo work it adds friction without payoff. Recommending without requiring keeps the methodology useful at every team size.

### Alternatives considered

- **Default to merge-commit style.** Rejected — see rationale.
- **Default to rebase-merge.** Rejected — preserves within-branch commits on the default branch, fighting the linear-PR-history goal.
- **Allow merge style to be per-PR.** Rejected — mixed merge styles produce inconsistent history that defeats the point of picking a style.
- **Mandate PRs always.** Rejected — adds friction for solo work. Adopters needing enforcement use platform branch protection.

## Implications

- The **github-issues bundle's README** documents the squash convention, the PR title format expectation, and the branch-deletion practice. Adopters configure GitHub's merge-style settings to allow squash merging only.
- Future bundles for other PR-platforms (gitlab-mrs, bitbucket-prs) inherit the same convention by default; their READMEs note the equivalent platform setting.
- The **PR template** (`PULL_REQUEST_TEMPLATE.md` in the bundle) already carries Closes-syntax and What/Why/How. No template change needed for this COR.
- **Adopters** with strong reasons to diverge (preserving per-commit attribution for licensing/compliance, etc.) record a project-side PRJ that overrides the default for that project.
