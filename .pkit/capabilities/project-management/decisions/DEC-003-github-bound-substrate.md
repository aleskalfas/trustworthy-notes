---
id: DEC-003
title: GitHub-bound substrate — Issues, sub-issues, Milestones, Projects v2, GraphQL
status: accepted
date: 2026-05-21
author: Ales Kalfas
source:
  upstream: pm-workflow
  upstream_id: MET-002
  commit: 9d1f0237f5d5778ed9811c72f22ae8268e5faff3
  captured_at: 2026-05-21
---

## Context

A project-management capability has to commit to a substrate. Either it names a specific tracker's primitives directly (Issues, Milestones, Projects v2 fields, GraphQL mutations), or it abstracts the tracker behind a generic vocabulary (work-item, parent-ref, status-field, classification-field) and leaves binding to adopter configuration. The substrate choice ripples through every schema (do field names match GitHub's API surface?), every skill (does the agent target a tracker abstraction or a specific tracker's CLI?), and every adopter's install (is the capability ready to run, or does it need a tracker adapter first?).

## Decision

This capability is **GitHub-bound**. The schemas, skills, and project-manager name GitHub primitives directly:

- **Issues** as the work-item substrate (EPIC, Feature, Umbrella, Task all live as GitHub issues).
- **Native sub-issues** (the parent/subIssues GraphQL fields) as the canonical containment mechanism — see [project-management:DEC-005-linking-and-containment].
- **Milestone** field for time-bound scheduling — see [project-management:DEC-016-time-bound-containers].
- **Projects v2 boards and fields** for Priority, Workstream, and Status as projected single-select fields when configured — see [project-management:DEC-012-classification-axes].
- **Labels** for the always-as-label `type:*` axis, plus fallback `priority:*` / `workstream:*` labels when no Projects v2 board is configured.
- **PR auto-close keywords** (`Closes #N`, `Fixes #N`, `Resolves #N`) as the closure trigger — see [project-management:DEC-006-state-machine-and-cascade].
- **Branch protection** as a secondary safety net on shared branches (`main`, `integration/*`).
- The **GraphQL API** (`gh api graphql`) as the read/mutate surface the project-manager and skills target; REST (`gh api`) where the GraphQL surface doesn't yet cover a primitive.

An adopter installing this capability must have a GitHub repository (on `github.com` or GitHub Enterprise Server 3.15+ for Projects v2 support) and a `gh` CLI authenticated against the target organization.

## Rationale

Every project the methodology targets today lives on GitHub. An abstracted substrate would impose abstraction overhead — the agent translating between tracker-neutral and tracker-specific concepts at every mutation — for a payoff that only materialises if a project migrates to a different tracker, which is a low-probability event. Concrete GitHub naming is sharper, easier to read, easier to validate against, and unambiguous for the agent.

GitHub's Issues evolution — sub-issues, Projects v2, advanced search, GraphQL mutations — gives a lot of free machinery this capability would otherwise need to specify in tracker-neutral terms. Native sub-issues populate the "Sub-issues progress" field on Projects v2 boards automatically; PR auto-close keywords drive the workflow's closure trigger without per-tracker logic; Projects v2 single-select fields give the Priority/Workstream/Status classification axes the right substrate.

### Alternatives considered

- **Tracker-agnostic substrate.** Rejected — no concrete adopter on Linear/Jira motivates the abstraction; the cost (every adapter, every schema, every skill carrying a translation layer) is real and the benefit is hypothetical.
- **GitHub-bound with mapping notes for Linear/Jira.** Rejected pre-emptively. The mapping notes would have to track three tracker surfaces' evolutions; without a real second-tracker adopter, the mapping decays. Revisitable when a non-GitHub adopter shows up — at that point the capability either ships a tracker-bridging companion or splits into multiple capabilities (`project-management-github`, `project-management-linear`, etc.).

## Implications

- Migrating an adopting project to a non-GitHub tracker would require either replacing this capability entirely or substantially extending it; an accepted cost of the binding.
- The project-manager shells out to `gh api` and `gh api graphql` for all mutations. Adopters who can't authenticate `gh` against their organisation can't use this capability operationally — the README's `Dependencies` section flags this.
- The capability's schemas explicitly name GitHub primitives (`native sub-issues`, `Milestone field`, `Projects v2 single-select field`, `branch protection`). Schema descriptions read as concrete GitHub-API documentation, not as tracker-neutral specifications.
- Future capability evolutions add new GitHub primitives as they become available (new GraphQL fields, new board features) — these are schema and skill changes, not architecture changes. The substrate binding stays put.
