---
id: DEC-031
title: Reject unauthored template-placeholder bodies in issue and PR validation
status: accepted
date: 2026-06-14
author: Ales Kalfas
---

## Context

`create-issue` composes an issue body verbatim from the per-type template (`templates/<Type>.md`) — placeholder prose ("The thesis or outcome being de-risked..."), instructional HTML comments, and empty `- [ ]` checkboxes — substituting only the parent-ref line. The skeleton is meant as scaffold for the author to fill.

Nothing forces the fill. Validation (`validate-issue.py`, `validate-pr.py`) checks that the required *sections* are present and that checkbox semantics hold, but never that the placeholder *content* was replaced. So a body still carrying the raw skeleton passes clean. This was not hypothetical: an EPIC was filed and run through its entire lifecycle — children filed, work done — while its body was still the stamped placeholder, because no rule and no human caught it.

PR bodies share the identical hole: `validate-pr.py` + `templates/PR.md` check section presence, not authorship, so a PR can be opened and merged carrying the raw `## Summary` skeleton.

The required-section rules live in [project-management:DEC-010-issue-body-minimum-structure]; the severity vocabulary this rule draws from is [project-management:DEC-014-validation-severity-model]; checkbox semantics are [project-management:DEC-007-checkbox-validation].

## Decision

### Principle

A body that still carries the stamped template skeleton is **unauthored** and must be rejected. The rule covers both surfaces — issue bodies and PR bodies — since they share the failure mode.

### Detection — structural, derived from the live template at runtime

Detection is **structural** and reads the matching shipped template at validation time. It introduces **no new sentinel or marker in the templates**, so it changes no shipped template shape and therefore ships **no migration** (per [pkit:COR-010]).

Two signals:

- **Empty required checkbox section → `[validation-severity:hard-reject]` at the first transition (a `warning` at create — see Trigger).** A required checkbox section (per [project-management:DEC-010-issue-body-minimum-structure]) with **zero authored items** is the unambiguous "unauthored" signal — and the one that catches the motivating incident's class (a body filed with no real criteria at all). An *authored item* is a checkbox line with non-whitespace content after the `]`, regardless of checked state — `- [ ] Real criterion` and `- [x] Real criterion` are both authored; a bare `- [ ]` (nothing after) is a skeleton item. This is **lenient**: a trailing bare `- [ ]` *alongside* real authored items is fine — only a section with no authored items at all triggers. This avoids punishing a legitimately partial criteria list while catching the genuinely empty skeleton. The prose signal below is a softer, secondary catch.
- **Surviving template placeholder prose → `[validation-severity:warning]`.** If the template's placeholder prose still appears in the body, emit a warning. The placeholder strings are **derived at runtime from the live `templates/<Type>.md`**, not enumerated in a schema — so the check stays in sync automatically when a template is edited.

### Trigger — warn at create, hard-reject at the first transition

The hard gate fires at the **first lifecycle transition** (Todo → Backlog onward), not at filing. The harm the motivating incident exposed was an unauthored issue *advancing through its whole lifecycle* — not its transient existence right after filing. A just-filed skeleton that cannot move is harmless; blocking it at the transition closes the actual harm.

At **create**, the same detection runs but emits a `[validation-severity:warning]` — visible, never silent. This preserves the stamp-then-fill workflow (`create-issue` keeps stamping the template skeleton for the author to fill) while signalling the unfinished body from the first moment. So the empty-required-checkbox signal is a *warning* at create and a *hard-reject* from the first transition onward.

This is deliberately *not* the rejected quiet-at-create carve-out: the warning makes the unauthored body visible at filing; only the **block** is deferred to the transition, where the harm actually lives.

### Implementation contract — declared in schema, enforced in code

The rule is **declared** — name + severity token — as an entry in [`schemas/body-format.yaml`](../schemas/body-format.yaml) (issue side) and [`schemas/git-conventions.yaml`](../schemas/git-conventions.yaml) (PR side), but its **detection logic is enforced in the validator's code** (`validate-issue.py`, `validate-pr.py`), not driven declaratively from the schema entry. The entry documents and tags the rule with its severity; the validator enforces it. This declare-in-schema / enforce-in-code split is the placement decision; the exact in-code structure is left to the implementation.

## Rationale

- **Warn at create, block at the transition.** The motivating incident's harm was an unauthored body *advancing*, not existing for a moment in Todo. Gating at the first transition closes that harm while preserving the stamp-then-fill ergonomics — no `create-issue` rework. A warning at create keeps the signal visible from filing, so this is *not* the silent carve-out rejected below; it just puts the **block** where the harm is.
- **Structural over a sentinel marker.** A "delete this line" sentinel gives a zero-false-positive signal but changes every shipped template, forcing a migration and touching every adopter's templates. Structural detection reads the existing template at runtime: lighter, migration-free, and the false-positive risk is closed by the lenient checkbox rule.
- **Lenient over strict checkboxes.** Flagging *any* bare `- [ ]` would punish an author who legitimately files three of four template boxes. Keying the hard-reject to a section with *zero authored items* targets only the genuinely unauthored case. Checked state is irrelevant — an unchecked criterion with real text is authored; only a bare `- [ ]` (nothing after `]`) counts as a skeleton item.
- **Runtime-derived fingerprints over schema-enumerated.** Listing placeholder phrases in a schema means every template edit needs a matching schema update or the check silently drifts. Deriving from the live template keeps the two in lockstep; the validator and templates ship together in the same capability, so the coupling is acceptable.

### Alternatives considered

- **Sentinel marker token in every template.** Rejected — zero false positives, but a shipped-template-shape change that forces a migration and rewrites every adopter's templates. The structural approach achieves the goal without that cost.
- **Quiet at create (silent), enforce only from the first transition.** Rejected — a *silent* admit at filing hides the unfinished body. The chosen design keeps the transition gate but adds a visible warning at create, so the body is never silently accepted.
- **Block at create outright (no skeleton may ever be filed).** Rejected — it forces a `create-issue` rework that demands an authored body up front and discards the stamp-then-fill flow, for the marginal benefit of preventing a transient, immovable Todo skeleton. The harm is in advancing, not in transient existence, so gating the first transition is sufficient.
- **Strict: any empty checkbox rejects.** Rejected — false-positives on legitimately partial criteria lists; nags half-filled drafts.
- **Schema-enumerated placeholder fingerprints.** Rejected — drifts out of sync on any template edit; the runtime-derived form cannot drift.

## Implications

- **`create-issue` is unchanged** — it keeps stamping the template skeleton for the author to fill; it additionally emits the warning when the body it would file is still unauthored. No contract change, no workflow disruption. The hard gate lives in the transition path (`move-issue` / the workflow wrappers), which already run body validation.
- **`validate-issue.py` and `validate-pr.py`** each gain the detection: the empty-required-checkbox-section hard-reject and the surviving-placeholder-prose warning.
- **[`schemas/body-format.yaml`](../schemas/body-format.yaml) and [`schemas/git-conventions.yaml`](../schemas/git-conventions.yaml)** each gain a declaration entry for the rule, tagged with its severity token; the entry documents the rule, the validator enforces it.
- **No migration** — detection changes no shipped template shape, so the migration discipline ([pkit:COR-010]) does not fire; the only versioned surface change is the new validation convention itself, shipping with the implementation Tasks. (project-kit confirms migration-coverage through its own `pkit migrations check-diff` check.)
- The rule is realised in two implementation Tasks: the issue-side build and the PR-side build, each blocked on this record being accepted.
- Doc-impact checkboxes and required-section rules from [project-management:DEC-007-checkbox-validation] and [project-management:DEC-010-issue-body-minimum-structure] are unaffected; this rule sits alongside them as a new universal body rule.
