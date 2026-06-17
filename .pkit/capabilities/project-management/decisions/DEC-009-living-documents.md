---
id: DEC-009
title: Issue bodies are living documents; scope edits gated by original author
status: accepted
date: 2026-05-21
author: Ales Kalfas
source:
  upstream: pm-workflow
  upstream_id: MET-008
  commit: 9d1f0237f5d5778ed9811c72f22ae8268e5faff3
  captured_at: 2026-05-21
---

## Context

The checkbox-validation rule from [project-management:DEC-007-checkbox-validation] treats a tick as an audit record. That rule alone leaves the question: can the *set* of checkboxes — or the body's narrative sections — change between filing and closing? In practice, yes: PM-authored Features have acceptance criteria that turn out to be unrealistic; Implementer work surfaces missing criteria; rewordings clarify intent. The capability has to specify how bodies evolve without dissolving the discipline that makes the close-gate meaningful.

## Decision

Issue bodies — including the checkbox lists in PM-authored EPICs and Features — are **living documents**. Their content evolves as understanding deepens, governed by three rules the project-manager enforces:

### Wording-only edits (free)

Clarifying language, fixing typos, rephrasing for readability without changing the meaning of any requirement — **anyone can edit at any time**. No authorisation needed.

The test for "wording-only": would a future reader's behaviour change as a result of the edit? If no, it's wording. If yes, it's scope.

### Scope-changing edits (gated by original author)

Adding a new checkbox, removing an existing unticked one, materially rewording one to change its meaning, splitting one into several — these are spec changes. They require **the original author's authorisation** (typically the PM for EPIC/Feature acceptance criteria per [project-management:DEC-008-pm-and-implementer-roles]). The project-manager records the change with a brief comment capturing the why:

> Updated acceptance criterion at PM's direction: original requirement X turned out to be unrealistic because Y; replaced with Z.

### Ticked checkboxes are sticky

A ticked check is an audit record from [project-management:DEC-007-checkbox-validation]. **Un-ticking or removing a ticked check implies regression** and is allowed only with an explicit comment explaining what regressed and why. Rare in practice. If common, something's wrong with how validation was done at tick time.

This rule is encoded in [`schemas/body-format.yaml`](../schemas/body-format.yaml)'s `checkbox_rules.ticked_boxes_sticky: true`.

### Implementer's continuous reconciliation

The Implementer's job during implementation isn't only "tick boxes as I meet them" — it's also "watch for drift between what the body says and what I'm actually building." When drift is found:

1. Raise it with the original author (typically the PM).
2. PM authorises the body edit (or pushes back and the Implementer adjusts the implementation instead).
3. Agent updates the body with the authorisation captured as an issue comment.
4. Implementation continues toward the updated spec.

This is a normal part of the workflow, not an exception path.

### Interaction with the close-gate

The aggregate close-gate from [project-management:DEC-007-checkbox-validation] still applies. The **set** of checkboxes at close time is whatever the body contains *at close time*, not at filing time. A box added during implementation must still be ticked before close — it's just a normal box that happened to be added later.

### Interaction with the integration-branch marker

The optional `Integration: integration/<slug>` pre-line on the issue body — see [project-management:DEC-013-branch-and-pr-conventions] — counts as **scope content**. Removing the marker from a descendant body without owner authorisation is a scope-changing edit at severity `[validation-severity:bypassable-with-audit]` per [`schemas/body-format.yaml`](../schemas/body-format.yaml)'s `integration_marker.removal_authorisation_severity`.

## Rationale

Treating issue bodies as frozen-at-filing produces drift in the other direction: implementations diverge from outdated specs, and reviewers don't catch it because the spec wasn't updated. Treating them as fully editable removes the discipline that makes the spec meaningful. The middle path — wording free, scope gated, ticks sticky — preserves the spec's authority while allowing genuine refinement.

The "scope edit needs original author's authorisation" rule mirrors the authority pattern from [project-management:DEC-008-pm-and-implementer-roles]: whoever authored the spec also decides when it changes meaning. This keeps spec authority traceable.

GitHub's edit history captures the diff automatically; the project-manager's audit comment captures the *why*, which the diff alone doesn't surface.

### Alternatives considered

- **Frozen-at-filing bodies.** Rejected — forces drift between spec and implementation; loses the Implementer's emerging insight.
- **Fully editable by anyone.** Rejected — erases the spec's authority; turns the body into a wiki page rather than a contract.
- **All edits gated regardless of substance.** Rejected — authorising wording fixes and typo corrections is overhead for its own sake.

## Implications

- The validate-body skill distinguishes wording-only edits (proceed silently) from scope-changing edits (require author authorisation, record audit comment) at edit time. The classification uses the "would a future reader's behaviour change" test; ambiguous cases default to gated.
- Acceptance criteria and other checkbox sets are *current best statements*, not contracts frozen at filing.
- Reviewers reading a body see the latest spec; GitHub's edit history shows how it got there; audit comments explain why.
- The Implementer's reconciliation responsibility extends across levels — when filing Features under an EPIC, the Implementer should sanity-check that the Feature's acceptance criteria collectively contribute to the EPIC's success criteria, and surface drift to the PM if not.
- This rule applies to all issue body content, not just checkboxes — narrative sections (`## Context`, `## Approach`) are also editable under the same wording-vs-scope distinction.
