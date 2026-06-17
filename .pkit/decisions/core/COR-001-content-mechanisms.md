---
id: COR-001
title: Content mechanisms
status: accepted
date: 2026-05-01
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

The no-shared-files invariant (in `.pkit/decisions/README.md`) settles ownership: every file in a project has exactly one owner — core or project — and they never share a path. The invariant tells us *who* owns each file; it does not describe the operational mechanisms by which canonical core content reaches projects, by which projects add their own content alongside, or by which projects override core content where it is allowed.

Different artifact types (decisions, agents, hard rules, workflow scripts, methodology docs) will need different combinations of these mechanisms. Some artifacts are strictly core-owned with no override allowed (decisions). Others may need to be replaced or augmented by adopters (agents, scripts). Some need to live at fixed paths the project will extend (root `CLAUDE.md`).

Before we can specify how each artifact type works, we need a fixed set of operational mechanisms that all artifact types draw from. This record establishes that set.

## Decision

Core content reaches and interacts with adopting projects through exactly three mechanisms — **propagation**, **extension**, and **suspension**. Each describes a steady-state relationship: a defined ownership, cadence, and contract that holds over the file's lifetime. Every artifact uses one of these three — there is no fourth.

In addition to the three mechanisms, the core layer performs an **install-time seeding** operation at first install. Seeding is a one-time delivery event, not a steady-state mechanism — described after the three mechanisms below.

### Propagation (synced core content)

A canonical file lives at a core-owned path (e.g. inside `core/`). The project receives a verbatim copy at the same relative path. Every subsequent sync overwrites the project's copy with the current canonical version. The project must not edit synced files; if it does, the edits are lost on the next sync.

- **Ownership:** core, forever.
- **Cadence:** written on first install, rewritten on every sync.
- **Contract:** the path will only contain the canonical version of the content; the project guarantees not to edit it.

### Extension (project-side content)

The project owns content in project-owned paths (e.g. inside `project/`). The names do not collide with anything in core. The core layer never reads from or writes to these paths.

- **Ownership:** project, forever.
- **Cadence:** written and updated entirely by the project, on the project's schedule.
- **Contract:** project-owned paths are not touched by sync; the project may add, edit, or remove its own content freely.

Extension content can be **seeded at first install** by the core layer (see *Install-time seeding* below). Once seeded, the file is just regular project-owned content — sync never touches it again, and the project owns it.

### Suspension (project overrides core)

The project creates content at a path that the **consumer** — the runtime, tooling, or framework that loads these files at execution time — recognises as a *replacement for* a corresponding core-owned artifact. The consumer applies a defined precedence rule and uses the project's version instead of the core canonical version. The core canonical version remains in place at its own path; the project's override lives in a project-owned path.

- **Ownership:** the project's override file is project-owned; the original core canonical file remains core-owned.
- **Cadence:** the override is created and updated by the project, on the project's schedule.
- **Contract:** suspension is allowed only for artifact types that are explicitly declared as suspendable. Some artifact types (e.g. decision records) are not suspendable — for those, suspension is unavailable. Each artifact type's record declares whether suspension is supported, the precedence rule, and whether disabling (a suspension that erases rather than replaces) is supported.

### Install-time seeding (one-time delivery into project-owned paths)

At first install, the core layer can deliver initial content to designated project-owned paths. The content is rendered from a template (parameterised or empty stub) and written once. After install, the path is a regular extension — the core layer never touches it again, and the project owns it.

- **Cadence:** written exactly once, at first install. Subsequent syncs do not touch this path.
- **Ownership after install:** project, forever (same as any extension).
- **Contract:** the core layer guarantees a one-time write at first install for each declared seed path; after that, the path is project-owned and behaves like any other extension.

Seeding is a *delivery operation*, not a steady-state mechanism: the steady-state relationship for a seeded path is just **extension** once install completes. Seeding describes how the path's initial content gets there, not how the path is owned over its lifetime.

Seeding is required for paths that *must exist before the project has a chance to write anything* — root `CLAUDE.md` is the canonical example: Claude Code expects it at exactly that location, so it has to be present from install onward. Seeding is optional for paths where the project could write its own initial content but the core layer offers a useful starting point.

### Application: the fixed-path two-file pattern

Some files must live at fixed paths the project will want to extend — root `CLAUDE.md` is the canonical example. The project owns the file (because it will extend it), but the file must already exist with delegation content at install. This is solved by combining **propagation** for the canonical content with **extension + install-time seeding** for the fixed path:

- A short **extension** at the fixed path. Project-owned. Seeded at first install with a delegation reference to the core canonical content using the platform's include mechanism (e.g. Claude Code's `@`-include syntax for `CLAUDE.md`). After install, the project owns it and may add project-specific content freely.
- A **propagation** target at a separate core-owned path holding the canonical content. Updated on every sync.

The fixed-path file is small (a delegation header plus any project-specific content) and is owned by the project. The canonical content evolves through sync without ever touching the fixed-path file. This is not a separate mechanism — it is a way to combine propagation and extension (with install-time seeding) to handle a specific class of file.

## Rationale

**Why exactly three mechanisms.**
The no-shared-files invariant rules out any "merged" or "shared" mechanism — the third class some scaffolding tools provide is ruled out here. The remaining steady-state options are core-owned, project-owned-without-collision, and project-owned-with-collision. These are the three:

- **Propagation** is required so improvements to canonical content (rules, base content, methodology) reach adopters. Without it, the long-term value of the core layer collapses to "scaffold once."
- **Extension** is required because adopters need to add their own content (decisions, agents, scripts) without coordinating with or fighting the core layer.
- **Suspension** is required for artifact types where adopters legitimately need to replace canonical behaviour (e.g. swap an agent's prompt entirely, disable a workflow script). Without it, the only escape valve is forking the core layer, which is too heavy.

Two mechanisms aren't enough — drop any one and an adopter use case becomes unserviceable. Four aren't needed — every alternative considered (composition, aggregation, plugin/hook, versioning, disabling-as-its-own-thing) reduces to one of these three plus a runtime detail or a delivery operation.

**Why install-time seeding is not a fourth mechanism.**
Seeding describes a one-time event — the core layer writes initial content to a project-owned path at install. After that event, the path is operationally indistinguishable from any other extension: project-owned, untouched by sync, the project may edit freely. Seeding does not establish an ongoing ownership relationship; it is a *delivery operation* that produces an extension-ready file at install and then steps out of the picture.

A "mechanism" in this record describes a steady-state relationship — a contract that holds over the file's lifetime. Seeding does not meet that bar. It belongs in the description of the install-time workflow alongside running propagation; it is not a peer of propagation/extension/suspension.

**Why suspension is a contractual peer of extension despite sharing the same filesystem primitive.**
Mechanically, both extension and suspension involve the project creating a file under a project-owned path. The difference is whether the path/name collides with a core artifact and whether the consumer applies a precedence rule. Filesystem-wise, only extension is needed; suspension emerges as a particular *use* of extension when names collide. But treating suspension as a separate mechanism keeps three contractual concerns visible:

- Not every artifact should be suspendable. Decisions, methodology, and the system spec must not be — suspending them would defeat the methodology. Agents and scripts may be. Each artifact type must declare whether suspension is supported.
- The consumer needs a defined precedence rule so it can decide what to load.
- Adopters need to know they're overriding rather than adding. It is a stronger commitment than extension.

**Why the fixed-path two-file pattern is an application, not a mechanism.**
The pattern combines propagation, extension, and install-time seeding — all already named. There is no new file-system semantics introduced. Every file in the pattern uses one of the existing mechanisms. Naming it a "pattern" rather than a mechanism keeps the mechanism set minimal; treating it as a fourth mechanism would invite further proliferation of sub-cases that don't earn their keep.

### Alternatives considered

- **Four mechanisms with stamping (or scaffolding) as a peer.** Earlier draft of this record. Rejected: stamping describes a one-time event, not a steady-state ownership relationship. After the event, a stamped file is operationally indistinguishable from any extension. Treating it as a peer mechanism conflates "delivery operation" with "ongoing ownership contract." Reframing it as install-time seeding under the extension mechanism is cleaner.
- **Two mechanisms, folding suspension into extension.** Rejected for the contractual reasons in the rationale above. The filesystem primitive is shared, but the contracts and adopter expectations differ enough to deserve named separation.
- **Four mechanisms, with disabling as its own slot.** Rejected: disabling is a sub-case of suspension (a suspension that erases rather than replaces). Adding a fourth slot for it would invite further cuts that don't earn their keep.
- **A single unified mechanism with metadata flags.** ("synced: true", "seed-once: true", etc., per file or per directory.) Rejected: metadata-driven dispatch creates a second authority (the metadata) competing with the file's location for the source of truth about its lifecycle. Cleaner to give each mechanism a distinct positional or naming convention so the file's location *is* the declaration of its mechanism.

## Implications

- Every file in a project under this methodology is in one of three steady-state mechanisms: propagation (core-owned), extension (project-owned, no name collision with core), suspension (project-owned, name collides with core, consumer precedence applies).
- The core layer maintains two manifests:
  - **Synced manifest** — paths under propagation, mirrored on every sync.
  - **Seed manifest** — extension paths the core layer writes once at first install with initial content.
- These two manifests are disjoint. The synced manifest lists paths the core layer owns forever; the seed manifest lists paths the core layer writes once and then releases.
- First-install runs both: propagation for the synced manifest, then seeding for the seed manifest. Subsequent syncs run propagation only.
- Each artifact type declares whether extension and suspension are supported. For example: decisions support extension (project-side records) but not suspension (no overrides of methodology decisions); agents likely support both extension (new agents) and suspension (overriding base agents); the methodology spec doc itself supports neither (core-owned, no project content). Per-artifact-type mapping is a separate decision and will be recorded separately.
- **Synced (propagation) artifacts** are core-owned forever. Adopter edits to them are not preserved. The contract holds because the sync operation guarantees not to touch project-owned paths in return.
- **Seeded extension artifacts** are project-owned after first install. Core makes no further claim on them.
- For artifact types where suspension is supported, the precedence rule must be specified (e.g. "the consumer prefers `project/<name>` over `core/<name>` for matching names") and whether disabling is supported (typically yes — an empty file or a `disabled: true` marker would do it). The precedence and disabling rules can vary per artifact type; they are part of each type's own record.
- The set of placeholder values adopters must provide at first install for parameterised seed templates (project name, repo slug, etc.) is a separate decision and will be recorded in its own future record.
