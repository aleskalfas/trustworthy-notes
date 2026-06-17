---
id: COR-014
title: Universal applicability as the core / project split test
status: accepted
date: 2026-05-14
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

CONTRIBUTING.md establishes the test for COR vs PRJ records:

> Would this record make sense, and feel applicable, when read in an arbitrary adopting project's repo? If yes → COR. If it leaks project-kit's internals → PRJ.

The same question, asked implicitly, governs every other artifact kind that has a core / project split: rules (`.pkit/rules/core.md` vs a project-side equivalent), skills (`.pkit/skills/core/` vs `.pkit/skills/project/`), agents per COR-013 (`.pkit/agents/core/` vs `.pkit/agents/project/`), and hook providers (per COR-013's precedence rule). The test has held up well for COR vs PRJ records; for the other artifact kinds it has drifted because the test was never named at the principle level.

An audit of the existing `.pkit/rules/core.md` (recorded in the project's tracker, the work that motivated this record) surfaced three failure modes that an explicit principle would have prevented:

- Operational guidance specific to one project's CLI behaviour, shipped in `core` (where it cannot apply to an arbitrary adopter).
- Bundle-specific tails (an instruction that names one workflow bundle's specific commands) shipped in `core` alongside otherwise-universal rules.
- Harness-specific syntax shipped in `core` without a qualifier, implicitly assuming every adopter is on the same harness.

Implicit principles drift. Generalising the test from CONTRIBUTING.md's COR/PRJ wording into a cross-artifact principle named at the methodology level catches these failures at their root.

## Decision

The **universal applicability** test governs the core / project split across every artifact kind in the methodology:

> An artifact (record, rule, skill, agent, hook provider, or future kind) ships in the **core** layer if and only if its role or content makes sense — and is useful — to any adopting project. Project-specific content lives in the **project** namespace.

Concretely, the test asks: *"Would this artifact, read or invoked in an arbitrary adopting project, do useful work or convey useful knowledge?"*

The same question is asked uniformly per artifact kind:

- **Decision records.** COR (universal) vs PRJ (project-specific). The existing COR/PRJ test in CONTRIBUTING.md is one instance of this principle.
- **Rules.** `.pkit/rules/core.md` (universal operational rules) vs `.pkit/rules/project.md` (project-specific operational rules).
- **Skills.** `.pkit/skills/core/<name>/` (universal procedures) vs `.pkit/skills/project/<name>/` (project-specific procedures).
- **Agents.** Per COR-013, `.pkit/agents/core/<name>/` (universal roles) vs `.pkit/agents/project/<name>/` (project-specific roles).
- **Hook providers.** Per COR-013's precedence rule, `project > bundle > adapter > core`; only providers that pass the universal-applicability test ship as core providers.

### Scoping content that fails the test

When an artifact in `core` fails the test, the resolution depends on what kind of specificity it carries:

- **Project-specific content** moves to the **project namespace** for that artifact kind (PRJ, `project.md`, `project/<skill>/`, etc.).
- **Bundle-specific content** moves to the **bundle's own documentation** within that bundle's directory.
- **Adapter / harness-specific content** moves to the **adapter's own documentation** within that adapter's directory, or stays in core with an explicit qualifier naming the harness it applies to (until adapter-side documentation becomes a structural convention of its own).

### Cross-reference from CONTRIBUTING.md

CONTRIBUTING.md's existing COR vs PRJ wording cross-references this record. The principle named here is the same one CONTRIBUTING.md applies to records; this record promotes it from contributor-doc-only to cross-artifact methodology principle.

## Rationale

**Why generalise the test.** The test was already in use across artifact kinds, just implicit for kinds other than records. Implicit principles drift — the audit that motivated this record found three concrete drift instances in `.pkit/rules/core.md`. Naming the test prevents further drift and makes it teachable as one rule, not as a separate convention per artifact kind.

**Why one principle across all artifact kinds.** The alternative — each artifact kind defines its own "core" test — multiplies design surface and encourages inconsistency. Skills could end up with a different definition of "universal" than rules. Future artifact kinds (composition primitives, area variants beyond those in COR-005, etc.) would each re-litigate the question. One principle keeps the methodology coherent.

**Why "applicability to any adopting project" rather than another framing.** Two equivalent framings work: *"useful to any adopter"* or *"fits naturally in an arbitrary adopter's tree."* Both make the test concrete by inviting the author to mentally substitute a real adopter and ask whether the artifact serves them. The principle is intentionally a question, not a yes/no rule — judgement is part of the test, with the framing constraining where the judgement lands.

**Why the project namespace is symmetric across adopters.** Every adopter has a project side — including the methodology framework itself, when it self-hosts. The split is universal-vs-specific, not "what's universal vs what's specific to the framework source." A framework that self-hosts maintains its own non-universal rules in its own project namespace alongside any other adopter's; those rules carry no privilege from being authored at the source.

**Why this records the principle rather than amending CONTRIBUTING.md alone.** CONTRIBUTING.md is the methodology's maintainer guidance, not a synced artifact; an adopter reading their own copy of the methodology does not see CONTRIBUTING.md. The principle needs a citable home that *every* artifact in any installation can reference by record ID. A core record is that home.

### Alternatives considered

- **Status quo (implicit test, repeated per artifact kind).** Rejected — drift in `.pkit/rules/core.md` is the evidence that the implicit version doesn't scale.
- **Per-artifact-kind core tests defined separately.** Rejected — multiplies design surface; encourages inconsistency between artifact kinds; future kinds would have to invent their own test.
- **Restrict the principle to decisions only (leave other kinds with implicit tests).** Rejected — same denial that produced the drift this record fixes.
- **Make the test a Boolean rule rather than a judgement question.** Rejected — adopter-applicability is not always crisp (an artifact may be useful to *most* adopters but not all). A question that invites judgement is more honest than a Boolean that pretends crispness.

## Implications

- **`.pkit/rules/core.md` is refactored** to remove content that fails the universal-applicability test. The refactor is per the audit recorded in the tracker work that motivated this record: brand-name references are generalised, project-specific operational rules move out, bundle-specific tails point at the relevant bundle's documentation, harness-specific qualifiers are added or relocated.
- **`.pkit/rules/project.md` is materialised** as the project-side slot for adopter-specific operational rules. Symmetric to the existing project namespaces in decisions and skills. Each adopter authors their own; the methodology framework's own version (when it self-hosts) starts with the operational rule about running its CLI from the project root.
- **CLAUDE.md includes both layers** — `@.pkit/rules/core.md` and `@.pkit/rules/project.md` — so the host file picks up the universal rules and the project's own rules naturally.
- **CONTRIBUTING.md's COR vs PRJ wording cross-references this record.** The prose-only test becomes a pointer to the cross-artifact principle.
- **Future artifact kinds inherit the test.** New kinds (composition primitives per COR-013's deferred work; new area variants; etc.) apply the same test to determine their core / project split; no per-kind re-litigation.
- **The sync wiring for `.pkit/rules/`** is a pre-existing gap unrelated to this record. The current install / sync code does not propagate the rules area at all; the gap is tracked separately and does not block the refactor.
