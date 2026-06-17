---
id: COR-021
title: Capability-command dispatch — installed capabilities expose CLI commands declared in `package.yaml`; the kit's CLI registers them dynamically as nested subcommands
status: accepted
date: 2026-05-24
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

Capabilities (per COR-017) ship scripts under `<capability>/scripts/` that adopters invoke today by **direct path** — `.pkit/capabilities/<name>/scripts/<script>.py`. The script files are deterministic, schema-driven, and self-contained; the file's *invocation surface*, however, has no kit-level shape:

- An adopter has to know the full filesystem path; the command isn't a discoverable verb.
- The kit's CLI `--help` does not surface what's installed.
- An unknown command produces a shell-level "file not found" error, not a friendly hint pointing at install / spelling.
- The same script invocation looks different in every adopter's docs depending on local paths.

With evidence (one capability shipping `validate.py` today) plus project-management (shipping `pre-check.py` / `bootstrap.py` / `migrate.py` per its own internal decisions, with a verb-subject script set in the rollout pipeline), the threshold from COR-007 is met: a second concrete consumer recurs the pattern. Extracting a kit-level dispatch mechanism is the right move.

Two open design questions force themselves on the decision:

1. **How does a capability declare its commands?** Implicitly (every file in `scripts/` matching a filename convention is a command) or explicitly (the capability's `package.yaml` carries a `commands:` block)?
2. **What CLI shape do subcommands take?** Flat single-token (kebab-case `pkit pm create-issue`) or nested tree (`pkit pm create issue` with `create` as a sub-group)?

A third concern — backwards compatibility for adopters who already invoke scripts by direct path — has to be preserved. The dispatch mechanism is additive, not replacing.

## Decision

The kit's CLI (named `pkit` per PRJ-001) dispatches installed capabilities' commands via the form **`pkit <capability> <verb> <subject>`** for entity-mediating commands and **`pkit <capability> <command>`** for noun-only commands, with subcommands declared explicitly in each capability's `package.yaml` under a `commands:` block and registered dynamically by the dispatcher at invocation time.

### The `commands:` block

Each capability's `package.yaml` may carry an optional `commands:` block. The block is a **tree** — keys are subcommand tokens; values are either:

- A **leaf** — a mapping carrying `script:` (relative path from the capability root) and `help:` (one-line user-facing description); or
- A **sub-group** — a mapping of further subcommand tokens following the same recursion.

A leaf is detected by the presence of `script:` at its level. Arbitrary nesting depth is permitted; two-level nesting is the expected common case.

The capability's `package.yaml` is the **only** source of declaration; adopters do not override the `commands:` block, and the dispatcher does not consult any other source. A capability that ships no `commands:` block surfaces no subcommands; the namespace itself remains visible for discoverability messaging.

### CLI shape

Subcommands surface as **nested groups** matching the `commands:` tree. Two shapes coexist within a single capability:

- **Verb-subject form** — the expected common case for entity-mediating commands. Shape: **`pkit <capability> <verb> <subject>`**. Examples: `pkit pm create issue`, `pkit pm move issue`, `pkit pm validate pr`. The verb is a sub-group under the capability namespace; the subject is a command within that sub-group. The verb describes the action; the subject describes the entity acted on.

- **Noun-only form** — for environment-scoped or single-target commands where verb-subject pairing would be artificial. Shape: **`pkit <capability> <command>`**. Examples: `pkit pm pre-check`, `pkit pm bootstrap`, `pkit evidence validate`. The command is a flat top-level subcommand within the capability namespace.

Both shapes coexist within a single capability — `pm` ships verb-subject commands (`create issue`, `move issue`) alongside noun-only commands (`pre-check`, `bootstrap`).

### Name resolution on conflict

If a capability's name matches a kit-internal command, the kit-internal command wins on resolution — the capability's namespace becomes unreachable. By convention, capability names are **domain nouns** (`evidence`, `project-management`, …) and kit-internal commands are **action verbs** (`init`, `sync`, `validate`), so collision is unusual. Capability authors who hit a collision rename via supersession; the kit does not enforce a reserved list at install time. If real conflicts surface, a follow-up record adds the refuse-at-install gate per COR-007.

### Dispatcher contract

The dispatcher reads the backbone manifest at CLI invocation, identifies every installed capability, parses each capability's `package.yaml`, and registers its namespace + commands with the underlying CLI framework before argument parsing. The dispatcher then proxies invocation to the named script — arguments after the resolved subcommand pass through verbatim; the script's exit code becomes the CLI's exit code; standard streams are inherited.

The dispatcher is **stateless across invocations** — it does not cache registration across runs. Every invocation walks the manifest fresh, so capability install / uninstall surfaces immediately without an explicit refresh step.

### Discoverability and error UX

- `pkit --help` lists installed capability namespaces alongside core kit commands.
- `pkit <capability>` (no subcommand) lists the capability's available subcommands with their one-line help.
- `pkit <capability> --help` shows the capability's command surface in the framework's standard help format.
- `pkit <capability> <verb> --help` (for a sub-group) lists subjects under that verb.
- An unknown capability namespace produces an error that names the install command: "`<name>` is not a kit command or an installed capability; run the kit's capability-install for `<name>` to install it."
- An unknown subcommand under a known capability lists the available subcommands: "`<name>` is not a subcommand of capability `<capability>`; available: `<list>`."

The exact phrasing belongs to the area README that documents the CLI surface; the COR pins the principle that errors are actionable and reference the install / spelling correction the user most likely needs.

### Backwards compatibility

Direct-path invocation continues to work for capabilities whose scripts remain executable. The dispatcher is additive — a capability that adopts the `commands:` block surfaces the new invocation form while existing direct-path consumers continue working unchanged. Migration to the dispatcher form is per-capability, opt-in via the `package.yaml` addition.

### Schema and version

Adding the `commands:` block is a schema change to the capability `package.yaml` schema; the schema's `schema_version` bumps. Capabilities updating to the new schema_version ship a migration at the backbone tier per COR-010, idempotent on already-migrated state.

The principle this record fixes is a new convention adopters can break against, so the PR landing the record + dispatcher implementation bumps the kit version per the per-component bump policy from COR-010 and the project's per-component bump policy.

## Rationale

**Why explicit `commands:` declaration over implicit filesystem scan.** Implicit scan (every script in `scripts/` becomes a command) has three concrete failures: (1) capabilities ship private helper scripts that should not surface as commands (e.g., shared libraries, internal utilities, migration runners); (2) the command's user-facing help text has no place to live except inside the script itself, which forces the dispatcher to execute the script just to extract help — slow and brittle; (3) renames in the scripts directory silently re-shape the CLI, breaking adopters' documented invocations. Explicit declaration in `package.yaml` captures the help text where it belongs (alongside the capability's metadata), separates user-facing commands from internal scripts, and makes the CLI surface a deliberate decision rather than a filesystem accident. The capability author writes one line per command; the cost is small; the safety and discoverability gain is large.

**Why a nested tree rather than flat kebab single-token.** A capability's command vocabulary is naturally two-axis — verbs (what action) and subjects (acting on what entity). Flat kebab (`create-issue`, `move-issue`, `validate-issue`) preserves the semantic in the token but loses the structural grouping at help-time: `pkit <capability> --help` shows a wall of every command; the user has to scan for the verb prefix. Nested form (`create issue`, `move issue`, `validate issue`) lets the framework's help present verbs at the top level (`create`, `move`, `validate`) and subjects underneath, naturally surfacing the structure the capability already has. For capabilities whose vocabulary is noun-only (`pre-check`, `bootstrap`, `migrate`), flat top-level works without forcing artificial verb-subject pairing.

**Why kit-shipped `package.yaml` is the only source of declaration.** Permitting adopter-side overrides of the `commands:` block would let an adopter remove, rename, or alias subcommands — producing a CLI surface that differs across adopters and breaks the methodology's shared vocabulary. The capability's CLI surface is part of its methodology contract; consistency across adopters is more valuable than per-adopter customisation. Adopters who want a different surface can install a different capability (or fork).

**Why stateless registration at invocation time.** Caching the registered command set across invocations would require an invalidation step on capability install / uninstall / upgrade — three new failure modes (stale cache, missed invalidation, race conditions on concurrent modifications) for a feature that, at CLI invocation latency budgets, has no measurable cost. Walking the manifest on every invocation is cheap; the manifest is small; the parse is local. Statelessness is the simpler design.

**Why the dispatcher does not consult per-adopter state.** The dispatcher's job is mapping `<capability> <subcommand>` to a script path; that mapping lives entirely in the capability's `package.yaml`. Per-adopter state (project-side config, migration state, etc.) is the script's concern, read by the script itself when it runs. Keeping the dispatcher's input set to the installed capability set + each capability's `package.yaml` keeps the dispatcher's contract small and testable.

**Why backwards compatibility for direct-path invocation.** Capabilities that exist today (evidence) have adopters whose docs, CI workflows, and scripts already invoke by direct path. Breaking those invocations would force every adopter to migrate in lockstep with the dispatcher's landing. Additive opt-in lets the dispatcher land cleanly; the per-capability migration to the dispatcher form is a separate gesture documented in each capability's own README.

### Alternatives considered

- **Implicit filesystem scan of `scripts/`.** Rejected per the explicit-declaration rationale above.
- **Flat kebab single-token subcommands.** Rejected — loses the structural grouping the verb-subject vocabulary provides; help output flattens to a single long list.
- **Per-adopter command overrides via project-side config.** Rejected — fragments the methodology contract across adopters; conflicts with the no-shared-files invariant's spirit (the kit-shipped surface is the canonical surface).
- **Cached registration with invalidation on install / uninstall.** Rejected — three new failure modes for no measurable performance gain.
- **A separate top-level command tree per capability rather than a namespace prefix** (e.g., installing project-management adds `pkit create`, `pkit validate`, …, without a `pm` prefix). Rejected — capabilities' command vocabularies overlap (every capability that mediates entities will want `create`, `validate`, `show`); namespace prefixes are the disambiguator.
- **Dispatch by execution-time delegation through a generic `pkit run <capability> <script>` command.** Rejected — loses every discoverability and help-text benefit; equivalent to keeping direct-path with extra ceremony.
- **Defer until a third concrete consumer.** Rejected — COR-007's threshold is two recurring instances; evidence + project-management both have concrete command surfaces today.

## Implications

- **The capability `package.yaml` schema gains a `commands:` block.** The schema's `schema_version` bumps. The per-area schema authoring discipline (per COR-018, COR-019) applies; the change is a kit-shipped schema, not adopter-facing data.
- **A backbone-tier migration script ships in the same PR** as the dispatcher implementation, idempotent on already-migrated state per COR-010 and per the per-tier migration discipline in `.pkit/lifecycle/README.md`.
- **The kit's CLI gains a registration step** in its entry point that reads the backbone manifest and walks installed capabilities. The detailed implementation lives in the CLI area's reference docs (`.pkit/cli/README.md`).
- **The area README at `.pkit/cli/README.md`** documents the dispatcher's user-facing surface — including the precise error message wording, the `pkit <capability>` listing format, and the help-output shape — since those are inventory per the principles-not-inventory discipline.
- **Evidence and project-management** migrate to the dispatcher form by adding `commands:` blocks to their `package.yaml`. Each migration is a separate PR scoped to the capability; the dispatcher's landing PR does not require synchronised capability migrations (they are independent gestures enabled by the dispatcher's presence).
- **Direct-path invocation continues to work** for the foreseeable future. The COR does not deprecate direct-path; future records may, but the present record establishes only the additive surface.
- **A capability that ships no `commands:` block** has its namespace registered (so `pkit <capability>` produces an informative "no commands declared" message) but contributes nothing to the CLI surface. This keeps the install / uninstall round-trip clean: every installed capability is visible; the absence of commands is not an error.
- **Tests at the kit level** cover the registration round-trip (install adds; uninstall removes), the unknown-namespace + unknown-subcommand error paths, the help-output aggregation, and the proxy contract (arg passthrough, exit-code passthrough). The test idiom is whatever the kit's existing CLI tests use; the COR does not pin a framework.
- **Tab completion, capability-to-capability invocation, and per-script `--help` standardisation** are explicitly out of scope. Those are follow-up records per COR-007 if recurrence justifies them.
