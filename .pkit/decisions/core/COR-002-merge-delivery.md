---
id: COR-002
title: Merge delivery operation for adopter config files
status: accepted
date: 2026-05-04
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

COR-001 established three steady-state content mechanisms (propagation, extension, suspension) plus install-time seeding as a delivery operation. Seeding is one-shot: a file is written once at install and then belongs to the project; the core layer never revisits it.

Several adopter-side fixed-path config files need a more structured delivery than seeding alone. These files share a profile:

- They live at fixed paths the adopter owns (e.g., a tool's expected config location).
- The core layer has baseline content it wants present (e.g., safety-critical entries, default capabilities).
- The baseline grows or evolves over time (new safe-add patterns, new entries from newly-shipped content).
- The adopter has their own entries and customisations that must not be lost.
- Pure propagation is wrong — overwriting destroys adopter content.
- Pure seeding is insufficient — later baseline updates never reach the adopter.

Examples in this profile include agent-tooling permissions, dev-task definitions, pre-commit hook configs, and gitignore patterns. Each shares the structural pattern even if file format and per-entry semantics differ.

The three steady-state mechanisms cover ownership; seeding covers the simple one-shot delivery case. The structured-delivery case needs its own contract.

## Decision

Establish a second delivery operation alongside seeding: **merge**. Like seeding, it is not a steady-state mechanism — it is an operation the core layer performs against a project-owned file. Unlike seeding, merge is **repeatable**: it runs at first install AND can be re-run later (manually, or as part of an upgrade flow) to deliver new core-baseline content without losing adopter additions.

### The merge operation

A merge operation takes:

- **Core baseline source** — core-owned content at a known path, propagated under the canonical layer.
- **Adopter target** — a fixed-path file the adopter owns.

And performs:

1. **Read the adopter's current file.** Parse if structured (JSON, YAML, TOML); read raw if text.
2. **Compute the diff** between baseline and adopter content, classified into two tiers:
   - **Tier 1 — auto-add:** narrowly-scoped entries the core layer adds silently (e.g., scoped permissions, runtime-state gitignore lines).
   - **Tier 2 — prompt-once:** broader entries presented in a single confirmation panel; the user accepts or declines the whole tier.
3. **Apply.** Auto-add entries are appended if missing. Prompt-once entries are appended on user accept.
4. **Baseline-enforce safety entries.** A small set of safety-critical entries (e.g., explicit denies for destructive operations) are core-mandated. If the adopter has removed one, the merge re-adds it. Safety > preference.
5. **Append-only for additive lists.** The merge never removes adopter entries. Adopters' own additions to allow-lists, gitignore patterns, task lists, etc. persist across merges. The core layer only contributes — never subtracts.
6. **Idempotent.** Re-running with no missing entries reports "exists" (or equivalent) and makes no changes.

### File ownership and lifecycle

- The adopter's file is **project-owned**. Sync never silently overwrites it.
- The core baseline source is **propagated** (core-owned, synced) — the merge source stays current as the methodology evolves.
- Merge runs at three points:
  - First install, as part of the install flow alongside seeding and propagation.
  - Manually on demand, via a CLI gesture (name TBD with the rest of the CLI surface).
  - During upgrade flows, when the baseline source has grown.

### Per-format adapters

A merge operation reads and writes structured files. The file format determines parsing and serialization:

- **Structured config** (JSON, YAML, TOML) — parse, diff at the structured-key level, re-serialize. Comments preserved where the format allows.
- **Line-based text** (gitignore patterns and similar) — append missing lines; never reorder; never remove adopter lines.
- **Document templates** (Markdown templates with adopter content embedded) — typically closer to seeding (one-shot stamp); merge applies only when explicitly opted in.

Each merge target declares its file type and per-tier classification in the core layer's manifest.

### Where merge sits relative to other operations

| Operation | Cadence | Adopter content preserved | Source revisited? |
|---|---|---|---|
| **Propagation** (mechanism) | Every sync overwrites | N/A — file is core-owned | Yes |
| **Seeding** (delivery operation) | Once at install | Yes (core never re-touches) | No |
| **Merge** (delivery operation) | Install + repeatable | Yes (append-only / baseline-enforce) | Yes |
| **Authoritative region** (delivery operation) | Install + repeatable | Yes outside the region; the region itself is realizer-owned and replaced | Yes |
| **Extension** (mechanism) | Adopter-driven only | N/A — file is project-owned, never core-touched | No |
| **Suspension** (mechanism) | Adopter-driven only | N/A — file is project-owned override | No |

Merge fills the gap between propagation (no adopter customisation possible) and seeding (no later updates).

### Authoritative-region delivery (refinement per COR-028)

A later refinement adds a third delivery behaviour for adopter-owned config files: an **authoritative region**. Where merge contributes append-only into a file the adopter otherwise owns, an authoritative region is a delimited portion of such a file that a core-layer *realizer* (per COR-028) owns outright and **regenerates wholesale** on each run — replacing its prior content rather than unioning with it — while leaving everything outside the region untouched and adopter-owned.

This narrows ownership from whole-file to within-file: exactly one owner per region (the realizer for its region, the adopter for the rest), which preserves the no-shared-files invariant at finer granularity. It applies only when a realizer operates in its managed mode (per COR-028); the append-only merge above remains the default and is unchanged. Because the region is regenerated wholesale, removing the realizer's source causes the region to disappear on the next run — there is no stale-content reconciliation to perform, and no in-file markers are introduced.

**Why merge as a delivery operation, not a steady-state mechanism.**
The file's ownership does not change between merges — it is project-owned the whole time. What changes is its content. That is an operation, not an ownership class. Treating merge as a sixth steady-state mechanism would conflate "what owns this file" with "how content gets into it" — the same conflation seeding avoided in COR-001.

**Why repeatable, unlike seeding.**
Some core baseline content evolves over time: new safe-add patterns are identified; new entries from newly-shipped methodology surface; safety-critical entries are added. Seeding is one-shot — once stamped, the core layer never revisits. Merge re-runs let baseline updates land later, with user confirmation for non-trivial changes.

**Why two-tier (auto-add vs prompt-once).**
Narrowly-scoped, low-risk entries should not interrupt the user; broader entries that grant significant capability should be confirmed once. The two-tier split balances "useful out of the box" against "explicit consent for things that matter."

**Why append-only for adopter content.**
The no-shared-files invariant requires project-owned paths to be safe from core interference. Merge preserves that promise: it never removes adopter entries. The core layer only contributes; it never subtracts.

**Why baseline-enforce for safety entries.**
Some core-shipped content is safety-critical, not preference. An explicit deny for a destructive operation is not optional; if removed by an adopter, the next merge restores it. Safety entries are a small, explicitly declared subset — most entries are append-only.

### Alternatives considered

- **Make merge a steady-state mechanism (sixth ownership class).** Rejected: ownership does not change between merges. Merge is an operation against project-owned content, not an ownership class of its own.
- **Use seeding for everything; require adopters to manually re-stamp on baseline updates.** Rejected: loses adopter customisations on every re-stamp. Hostile to adopters who customise.
- **Propagate everything; require adopters to extend in a separate file.** Rejected: most relevant tools read a single file at a fixed path. Splitting into a separate adopter file would either require a complex include syntax (mostly unsupported) or a build step (ruled out for synced content).
- **Use markers inside the adopter's file** to delineate core content. Rejected by the no-shared-files invariant — same reasoning that ruled markers out for fixed-path content like root `CLAUDE.md`.

## Implications

- The core layer's manifest now distinguishes three categories of paths: **synced** (propagation), **seed** (one-shot delivery), and **merge** (structured-delivery, repeatable). The three are disjoint.
- Each merge target is declared with: a baseline source path (core-owned, propagated), a fixed-path adopter target, file-type metadata, per-tier classification of entries (auto-add vs prompt-once), and an explicit safety-enforce list.
- A merge command is added to the CLI. The same gesture runs at first install (across all declared merge targets) and as a re-run for individual files. Both single-file and full-tree forms are useful; naming TBD with the rest of the CLI surface.
- Future content that introduces new core-shipped baselines for adopter-owned config files declares its own merge targets, following this contract.
- The first concrete merge targets, when content authoring begins, will include adopter-side files for agent-tool permissions, dev-task definitions, pre-commit hooks, and gitignore patterns. Per-target details live in their respective per-artifact-type records.
