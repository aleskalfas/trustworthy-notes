---
id: DEC-007
title: Checkboxes validated at tick; aggregate check at close; never re-validated
status: accepted
date: 2026-05-21
author: Ales Kalfas
source:
  upstream: pm-workflow
  upstream_id: MET-006
  commit: 9d1f0237f5d5778ed9811c72f22ae8268e5faff3
  captured_at: 2026-05-21
---

## Context

Issue bodies commonly carry markdown checkboxes — acceptance criteria, sub-tasks, success criteria on EPICs, doc-impact items, close conditions on Umbrellas. The capability has to decide whether those checkboxes are decoration or whether they gate the issue's lifecycle, and if they gate, when validation happens (at tick or at close). The choice has ergonomic and trust consequences and ripples through the close-gate the transition-state skill enforces.

## Decision

Markdown checkboxes are **lifecycle-gating**. A tick is an audit record that the claim behind the box was validated **at the moment the box was ticked**. At closure time the agent does an aggregate check — every box must be ticked — and does **not** re-validate.

The rule is encoded in [`schemas/body-format.yaml`](../schemas/body-format.yaml)'s `checkbox_rules` block:

- **`validation_timing`** — at tick, by the actor doing the ticking; never re-validated at close.
- **`close_gate_severity`** — `[validation-severity:hard-reject]`. An issue with unticked boxes cannot transition to Done. The methodology's hard stop.
- **`ticked_boxes_sticky: true`** — un-ticking a previously ticked box requires an explicit comment explaining what regressed and why.
- **`two_kinds`** — the schema recognises two ticked-states with identical close-gate treatment:
  - **Inline claim** (`- [ ] All endpoints respond <100ms p95`) — ticked by the actor (human or agent) validating it.
  - **Issue reference** (`- [ ] #99 — Install Claude Code CLI`) — auto-ticked by GitHub when the referenced issue closes.

### Closure paths the hard stop applies on

- **Won't-do close.** Refuse; list the unticked boxes; ask the user to validate-and-tick or remove boxes that are no longer relevant, then retry.
- **Cascade-eligible close (parent's last child closed).** The parent's checkboxes are part of the eligibility check; if any are unticked, the parent isn't eligible — the agent prompts the user to address them first.
- **Task close via PR merge.** The agent verifies all checkboxes are ticked **before authorising the merge** — GitHub's auto-close on `Closes #N` would otherwise bypass the gate.

### Trust model

A tick is a tick. The actor that ticks is responsible for the validation behind it. The agent doesn't re-validate user-driven ticks at close time; the user trusts the agent to validate before its own ticks. When the agent ticks an inline box, it records evidence (a one-line comment, an inline note, a reference to a test run) for non-obvious claims; trivially verifiable claims don't require evidence. The tick itself is the audit record; evidence is a courtesy.

## Rationale

Re-validating every box at close is expensive and reopens questions that should already be settled. By the time an issue is closing, the work is done; re-walking every acceptance criterion is friction for its own sake. Anchoring validation at the moment of ticking aligns the audit moment with the actor doing the validation.

The hard stop on closure with unticked boxes converts the convention into mechanical enforcement: the methodology's checkbox lists become real gates, not decoration. Soft warnings drift into decoration in practice — the team has lived through that mode. Hard rejection is what makes the checkbox sets carry weight.

### Alternatives considered

- **Re-validate every box at close.** Rejected — expensive, friction-heavy, duplicates work already done.
- **Soft warning at close (close anyway if user confirms).** Rejected — soft warnings get ignored; checkboxes drift into decoration.
- **No closure gate (checkboxes informational).** Rejected — the team has lived through the failure mode of Tasks closing with partially-ticked acceptance criteria.

## Implications

- The validate-body skill emits an error listing every unticked box when the user attempts a close transition (won't-do, PR merge, cascade-eligibility).
- The project-manager's PR-merge flow runs a checkbox-completeness check before authorising the squash-merge — GitHub's `Closes #N` auto-close would otherwise bypass the gate.
- Bodies that genuinely have no checkboxes (some Tasks may not) are unaffected — the rule applies only when boxes exist.
- The mutability of the checkbox set itself (adding boxes, removing boxes, rewording them) is governed by [project-management:DEC-009-living-documents] — wording free; scope changes gated by original author.
- Doc-impact checkboxes from [project-management:DEC-015-doc-update-obligations] count toward the close-gate the same way acceptance criteria do.
- Sub-task promotion replaces the markdown checkbox with a task-list reference (`- [ ] foo` → `- [ ] #<N> foo`) so GitHub auto-ticks when the promoted Task closes — see [`schemas/body-format.yaml`](../schemas/body-format.yaml)'s `sub_task_promotion` block.
