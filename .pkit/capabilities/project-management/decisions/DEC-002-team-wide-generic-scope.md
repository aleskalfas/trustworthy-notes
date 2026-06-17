---
id: DEC-002
title: Methodology applies team-wide generically; values are project-side configuration
status: accepted
date: 2026-05-21
author: Ales Kalfas
source:
  upstream: pm-workflow
  upstream_id: MET-001
  commit: 9d1f0237f5d5778ed9811c72f22ae8268e5faff3
  captured_at: 2026-05-21
---

## Context

This capability is installed across multiple projects under one team. The methodology it realises was originally drafted inside a single project, and the question of scope — does the methodology apply to one project, to every project the team owns, or in layered fashion — shapes how every artifact in this capability behaves: whether schemas hold values or only field shapes, whether skills assume a known label set or read it from configuration, whether the agent prompts for project-specific input on first run or assumes baked-in values.

## Decision

The capability's kit-shipped content — decisions, schemas, skills, agent — is **team-wide generic**: it describes mechanisms (which classification axes exist, which states the workflow has, what shape a body must take) rather than instances (which specific labels, which specific values, which specific workstreams). Project-specific values wire in through adopter-side configuration at install time, not through edits to the capability's content.

Concretely:

- Schemas with closed value sets (e.g., the `type` axis in [project-management:DEC-012-classification-axes] — `feature`, `bug`, `docs`, `test`, `refactor`, `maintenance`) ship the values in the schema; these are methodology-fixed and the same in every adopter.
- Schemas with open value sets (e.g., the `workstream` axis) carry `values_project_specific: true` and leave the value list to adopter-side configuration the project-manager reads at runtime.
- Skills and the project-manager never hardcode adopter-specific values — they read schemas plus adopter configuration.
- The README and decisions speak in placeholder terms (`<the adopter>`, `<workstream values configured here>`) rather than naming specific projects.

## Rationale

Project-specific content forks the methodology the moment it lands. Once forked, improvements made in one project don't reach the others — the whole point of installing a shared capability evaporates. Team-wide generic content also forces the methodology to stay at the level of *mechanisms*, which transfer cleanly across projects, rather than *instances*, which don't.

The split between methodology-fixed and adopter-configurable values lives at the schema level — `values_project_specific: true` marks the axes the methodology mandates but doesn't pin. The choice is per-axis, not capability-wide, because some classifications (Type, Priority) carry methodology meaning that mustn't drift across adopters, while others (Workstream) only carry sense per-project.

### Alternatives considered

- **Project-specific content from the start.** Rejected — every adopter would re-author the capability's content, defeating the purpose of installing a shared discipline.
- **Layered (core capability + adopter addendum capability).** Rejected as premature abstraction. The variation between adopters isn't yet observed at a level that justifies an addendum layer. Revisitable when real divergence emerges.

## Implications

- The `description:` fields in this capability's schemas use generic prose; specific adopter examples (e.g., `Q2 2026 release` for a Milestone title) are illustrative, not prescriptive.
- The project-manager's first-run flow includes a prompt for the adopter's project-specific configuration (allowed workstreams, board IDs, label conventions where they diverge from defaults). This config lives in the adopter's project namespace, not in the kit-shipped capability tree.
- Future capability authors adding new schemas must decide explicitly whether each value set is methodology-fixed or project-specific, and mark it accordingly on the schema.
