---
id: DEC-014
title: Validation severity model — hard reject, bypassable with audit, warning
status: accepted
date: 2026-05-21
author: Ales Kalfas
source:
  upstream: pm-workflow
  upstream_id: MET-013
  commit: 9d1f0237f5d5778ed9811c72f22ae8268e5faff3
  captured_at: 2026-05-21
---

## Context

The other DECs in this capability name *what* the project-manager checks at filing, editing, opening PRs, merging, and closing. They don't fix *how strictly* the agent enforces each rule. A uniform "reject anything wrong" policy is too coarse — it gets in the way of legitimate exceptions. A uniform "warn but proceed" policy is too soft — convention-only rules drift in practice.

The capability needs a small, explicit severity vocabulary so each validation rule can be tagged with the response it deserves, and so the project-manager's behaviour is predictable to humans.

## Decision

Three severity classes, encoded in [`schemas/validation-severity.yaml`](../schemas/validation-severity.yaml)'s `severities` mapping. Other schemas typed-token reference them as `[validation-severity:<id>]` per COR-019.

### `hard-reject`

The project-manager refuses the operation. No override path. Operation never proceeds.

Used for rules where allowing through would corrupt downstream logic. Examples in the schema's entry:

- Title doesn't start with `[Type]` (per [project-management:DEC-011-title-formats]).
- PR body has no `Closes #N` (per [project-management:DEC-013-branch-and-pr-conventions]).
- Closing an issue with unticked checkboxes (per [project-management:DEC-007-checkbox-validation] — *the* hard stop).
- Filing a Feature inside a Feature (containment violation per [project-management:DEC-005-linking-and-containment]).
- Issue body missing required sections per its type (per [project-management:DEC-010-issue-body-minimum-structure]).
- New Milestone filing has no `Close trigger:` line (per [project-management:DEC-016-time-bound-containers]).

### `bypassable-with-audit`

The project-manager refuses by default; user may override with an explicit reason. **Before** the mutation runs, the agent posts a comment on the affected issue or PR using the audit-comment template:

```
Bypassed by <name> <<email>>: <reason>
```

The mutation then proceeds. The comment preserves the why even if subsequent steps fail.

Override syntax: `--bypass "<reason>"` (or the configured equivalent), with a non-empty reason required.

Examples encoded in the schema's entry:

- Merging without an `APPROVED` review or `Approved` comment (per [project-management:DEC-006-state-machine-and-cascade]).
- Force-pushing a feature branch after a review has landed (per [project-management:DEC-013-branch-and-pr-conventions]).
- Opening a PR targeting `main` while the closing issue carries an `Integration:` marker (per [project-management:DEC-013-branch-and-pr-conventions]).
- Promoting Todo → Backlog on verbal authorisation without the user touching the Milestone field directly.

### `warning`

The project-manager proceeds but emits a one-line warning the user can react to. No audit comment required.

Examples:

- Issue title shorter than ~30 chars after `[Type]` prefix (per [project-management:DEC-011-title-formats]).
- Multi-issue PR with mixed `type:*` labels — agent picks dominant and warns (per [project-management:DEC-013-branch-and-pr-conventions]).
- Existing Milestone read without a `Close trigger:` marker — infer and prompt to write one (per [project-management:DEC-016-time-bound-containers]).
- Code-path / doc-path mapping mismatch in a PR (per [project-management:DEC-015-doc-update-obligations]).

### Agent general behaviour

- **Validation runs on every interaction** — filing, editing, opening PR, merging, closing. Not a one-shot at filing time.
- **Hard rejects abort early.** The agent never partially executes a multi-step operation that fails validation. No half-filed issues.
- **Bypasses post their audit comment *before* the mutation runs**, so the trail survives even if the mutation fails later.
- **Warnings are non-fatal.** The agent emits the warning, completes the operation, and moves on. Warnings aggregate in the agent's status line; the user can review at any time.

## Rationale

Three classes is the smallest vocabulary that distinguishes "must not happen" (hard reject), "may happen with explicit justification" (bypassable), and "should be flagged but isn't worth blocking" (warning). Two classes would force soft conventions to choose between always-blocking and never-enforced; four or more is overhead without proportionate clarity.

Bypassable rules need the audit comment posted *before* the mutation to survive partial failure. If a mutation fails after the comment is posted, the audit trail still records intent. If the comment posts but the mutation fails, the user can re-attempt without re-posting.

Hard rejects protect the methodology's invariants — things downstream logic depends on. Bypassable gates protect the methodology's discipline — things humans should pause for but sometimes have legitimate reason to skip. Warnings flag what looks unusual without blocking work.

### Alternatives considered

- **Two classes (hard / soft).** Rejected — forces every gate to choose between blocking and ignorable; loses the "bypass with audit trail" middle ground that's actually the right answer for many gates.
- **Four classes (hard / blocking-but-bypassable / soft-but-required / advisory).** Rejected — overhead without clear behavioural distinctions; collapses to three in practice.
- **No severity model (case-by-case).** Rejected — produces inconsistent agent behaviour across deployments; humans can't predict whether a given rule blocks.

## Implications

- Every validation rule in this capability is tagged with one of the three severity tokens in its schema entry. The project-manager dispatches on the token at validation time without per-rule logic.
- The schema's `severity_ref` `$def` (a narrowed cross-schema reference token per COR-019) is referenced from every consuming schema's validations field, so the wiring is machine-checkable.
- The `--bypass "<reason>"` syntax is the uniform override across the project-manager's surface; the audit-comment template (`Bypassed by <name> <<email>>: <reason>`) is the canonical form posted before any bypassable mutation.
- The agent's status line aggregates warnings the user can review at any time without blocking the current operation.
- Future validation rules added to this capability inherit this severity vocabulary — there's no path for new severities outside these three without revising this DEC and the corresponding schema.
