---
id: COR-006
title: Roles of content artifacts
status: accepted
date: 2026-05-05
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

The methodology's content arrives in five shapes:

- **Decisions** (COR-NNN, PRJ-NNN records under `.pkit/decisions/`).
- **Docs** (READMEs, spec files, contributor guides).
- **Skills** (procedural automation files loaded by an AI agent at task time).
- **Agents** (persistent role definitions an AI agent can be invoked as).
- **Scratchpad notes** (exploratory working drafts under `.pkit/scratchpad/` that retire by producing other artifacts or being abandoned).

Each shape has a different purpose, but the boundaries blur in practice. A piece of guidance like "how to author a record" could plausibly land in a contributor doc, a skill that automates the workflow, an agent's prompt, or a meta-decision about authoring. Without a rule, content drifts across artifacts and authors invent inconsistent placements.

This record settles the rule: which shape carries which kind of content, and how the four interact without duplication.

## Decision

Each artifact shape carries one kind of content. Cross-references replace duplication.

### The discriminator

| Artifact | Carries | Loaded / read when |
|---|---|---|
| **Decision** (COR/PRJ) | A choice among alternatives — the *why*. | Authoring something needing the rule; resolving disputes |
| **Doc** (README, spec, contributor guide) | State / reference — the *what-is*: schemas, structures, contracts. | Working in an area; looking up shape |
| **Skill** | Procedural automation — the *how-to-do-X*. | An AI agent invokes a skill while performing a matching task |
| **Agent** | A persistent role with boundaries — the *who*. | Delegated to for a perspective-shaped task |
| **Scratchpad note** | Non-normative exploratory draft — the *what-might-become*. | Mapping the design space for an open question before a decision crystallises |

The five shapes are content peers; none is built on top of another.

### The discipline

1. **Single source of truth.** Each piece of content lives in its primary artifact. Other artifacts cite it; they do not restate it.
2. **Decisions do not carry procedure.** A decision establishes "we use process X"; a doc or skill describes X. The decision references the doc or skill rather than embedding it.
3. **Skills cite docs and decisions.** Procedural automation reads from authoritative sources at task time; doesn't bake them in.
4. **Agents reference; don't embed.** An agent's prompt cites the matrix, the rules, and the docs — it does not restate them. The agent is a thin role wrapper around shared content.

### Skills and agents are harness-agnostic

Skills and agents are general AI-tooling concepts. The core layer ships them in canonical paths under harness-neutral formats (markdown with frontmatter). The harness adapter (e.g. Claude Code's, when present) is responsible for translating canonical paths to the harness's expected locations — symlinks from `.claude/skills/<name>/` to `.pkit/skills/<core|project>/<name>/` for Claude Code, equivalents for other harnesses.

This translation is a runtime-deployment concern, not a content concern, and is governed by COR-003's principle that runtime-deployment paths are not mechanism rows — the mechanism applies to the source path; the harness target is regenerated.

## Rationale

**Why one rule.** Without it, the same content drifts. "How to author a good agent prompt" could land in a doc, a skill, or an agent. Each author picks differently, the corpus develops overlapping content, and consistency becomes an authoring chore rather than a property of the system.

**Why these five shapes.** Decisions and docs cover the universal split (*why* vs *what-is*). Skills and agents cover the AI-tooling split (*procedure* vs *role*). Scratchpad notes cover non-normative exploratory work that retires — the *what-might-become*. Combinations exist (a manifest is partly state, partly contract; a checklist is partly procedure, partly reference) but are placed by their primary nature. Finer slicing creates more boundary questions than it resolves; the fifth shape was added because exploration has its own retire-or-abandon lifecycle that does not fit any of the four persisting shapes.

**Why decisions can't carry procedure.** A decision is a choice. Procedures evolve frequently (new tools, refined steps) without changing the choice. Embedding procedure in a decision forces amendments for tweaks that aren't fundamentally about the choice. Keeping procedure out keeps decisions stable.

**Why skills and agents cite rather than embed.** Embedded content goes stale; cited content always reads the current version. The cost of one extra load at task time is trivial; the cost of stale embedded rules is high.

**Why harness-agnostic.** Coupling skills and agents to one specific harness limits the methodology's reach. Writing in harness-neutral formats and letting harness-specific adapters bridge to specific tools keeps content portable as the AI-tooling landscape evolves.

### Alternatives considered

- **Folding skills and agents into docs.** Rejected — both are loaded by AI tooling at execution time; their lifecycles and load semantics differ from reference docs.
- **Folding decisions into docs.** Rejected — decisions are stable choices; docs describe state. Different lifecycles, different audiences.
- **Allowing decisions to carry procedure when "really part of the decision."** Rejected — every procedure feels "really part of" something. The discipline depends on a sharp boundary.

## Implications

- **Each piece of content has one obvious home** — apply the discriminator and place accordingly.
- **Cross-references replace duplication** — skills cite docs; agents cite decisions and docs; decisions cite docs (when describing reference material the decision relies on).
- **Updating shared content** — a rule in `CONTRIBUTING.md`, a schema in a README — flows automatically to skills/agents/decisions because they cite, not embed.
- **Per-shape authoring guides live in their own area's README.** `CONTRIBUTING.md` for CORs (today). Future `.pkit/skills/README.md` for skills, `.pkit/agents/README.md` for agents.
- **Adopters inherit the same discipline** for their own decisions, agents, skills, and docs.
- **Harness adapters are the seam** between the core layer's harness-neutral skill/agent content and any specific AI harness's deployment paths. The adapter list grows as the core layer gains support for new tools; the content's shape does not change per harness.
