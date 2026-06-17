---
id: DEC-008
title: Two human roles (PM, Implementer), both executed by the project-manager on the human's direction
status: accepted
date: 2026-05-21
author: Ales Kalfas
source:
  upstream: pm-workflow
  upstream_id: MET-007
  commit: 9d1f0237f5d5778ed9811c72f22ae8268e5faff3
  captured_at: 2026-05-21
---

## Context

This capability is built on the assumption that the primary actor interacting with GitHub issues is the **project-manager** acting on a human's direction — not a human typing into the GitHub UI. The human supplies intent and authorisation; the agent files, validates, maintains references, opens PRs, runs cascade checks, ticks checkboxes (with validation), records audit comments, and closes issues. Even in that agent-mediated reality, humans play distinct organisational roles — some plan at the level of milestones and outcomes, others plan and execute at the level of Tasks. The capability needs role definitions sharp enough for the project-manager to dispatch on, without over-specifying agent deployment patterns.

## Decision

Two human roles, both executed by the project-manager on the human's direction. The same agent infrastructure serves either, switching mode based on which human is directing it.

### Project Manager (PM)

**Scope:** Milestones, EPICs, sometimes Features.

**Approach:** high-level plan and supervision. Frames outcomes, schedules waves, decomposes EPICs into Features when capability boundaries crystallise.

**Filing authority:** Milestones, EPICs. Optional Features.

**PRs:** rare. Only when the work is PM-domain (issue templates, methodology config, project-side classification values).

### Implementer (developer)

**Scope:** Tasks, Umbrellas, Features.

**Approach:** low-level plan and supervision. Files Tasks under existing EPICs, groups related Tasks with Umbrellas, promotes Umbrellas to Features when a capability claim emerges, opens PRs.

**Filing authority:** Tasks, Umbrellas, Features (when discovered mid-work).

**PRs:** the primary work product. Implementer is the one opening branches and shipping code.

### Authority table

| Item | Filed by |
|---|---|
| Milestone | PM |
| EPIC | PM |
| Feature | PM **or** Implementer (overlap zone) |
| Umbrella | Implementer (typical); PM possible |
| Task | Implementer |
| Sub-task (markdown) | Implementer |

### Cross-role allowances

- **PM can do Implementer work** — one-line doc fixes, etc. Same rules apply (templates, validation, gates).
- **Implementer cannot do PM work** without PM involvement. Filing an EPIC requires PM authority; Implementers may propose an EPIC but the PM signs it off and files.
- **Features sit in the overlap.** PM files at planning time (decomposing an EPIC); Implementer files at discovery time (capability emerges during work). Either path is valid.

### Reviewer (optional, when distinct)

When a different human reviews the PR, their `APPROVED` review or `Approved` comment is the authorisation signal for Review → Done per [project-management:DEC-006-state-machine-and-cascade]. In a single-Implementer team, the PM often plays Reviewer for Implementer PRs and vice versa. The methodology doesn't constrain who reviews what — only that the approval signal comes from a human other than the agent.

## Rationale

The two-role split mirrors the two natural scopes of planning: outcome-shaping (PM) and execution-decomposition (Implementer). Conflating them ("everyone files everything") loses the planning-authority signal that determines who decides what gets committed to.

Keeping both roles agent-backed avoids forcing humans to specialise as "the one who types" — anyone can direct the project-manager in either mode. The agent contract (gates from [project-management:DEC-006-state-machine-and-cascade] and severities from [project-management:DEC-014-validation-severity-model]) is the same regardless of which human is directing it.

### Alternatives considered

- **Single "user" role (no PM/Implementer split).** Rejected — loses the planning-authority distinction; allows Implementers to file EPICs unilaterally, which removes a useful guard rail.
- **More than two roles (PM, Tech Lead, Implementer, Reviewer, etc.).** Rejected as overhead — small-team contexts don't observe enough distinctions to justify finer roles, and finer roles tend to ossify when teams change shape.
- **Roles tied to GitHub identities.** Rejected — identities change; roles persist. The capability talks about responsibilities, not who currently holds them.

## Implications

- The project-manager's filing flow asks which role is directing it (or infers from context) and dispatches on the authority table — refuses an Implementer filing an EPIC without PM authorisation.
- Authorisation gates from [project-management:DEC-006-state-machine-and-cascade] apply to human authority regardless of role; PMs and Implementers both authorise transitions on the work they own.
- A PM filing an Implementer-scope Task is allowed but unusual — same flow, same gates.
- Multi-person teams may have multiple distinct Reviewers; the capability doesn't constrain who reviews what.
- "User" in singular phrasing across other DECs refers to whichever human is directing the agent in the current operation — PM or Implementer depending on context.
- The project-manager may be deployed as one general-purpose agent that switches mode, or as specialised agents (one for PM, one for Implementer). This DEC defines what each role does; the deployment shape is the adopter's choice.
