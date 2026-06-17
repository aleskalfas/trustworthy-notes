---
id: COR-007
title: Extract recurring patterns into tooling
status: accepted
date: 2026-05-05
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

A methodology's value compounds when the same shape of work, recognised as it recurs, gets distilled into tooling — a skill, an agent, a script, a template, a new artifact-type rule. Without that compounding, every author re-invents the same setup; accumulated wisdom about "how to do X well" stays in individual heads as folklore.

The methodology itself is this principle applied at its own level: the repeated work of starting and running development practices across projects is what the methodology captures. The same disposition belongs inside any adopting project — when project authors notice their own recurring shapes, the response is to invest in carrying the pattern, not to repeat the manual work.

This record names the disposition and locks it as part of the methodology.

## Decision

When the same shape of work recurs, invest in tooling — a skill, an agent, a script, a template, an area convention, or a new decision — that carries the pattern. Do not repeat the manual work indefinitely.

The choice is between two practices:

- **Pattern extraction (this rule).** At recurrence, name the pattern and invest in a carrier. Accept the upfront tooling cost; future occurrences are cheaper and more consistent.
- **One-time-each-time (rejected).** Treat each occurrence as fresh. Lower upfront cost; repeated cost forever; lose the chance for the pattern's quality to improve.

This record chooses the first.

### Trigger and threshold

The trigger is **recurrence visible after roughly 2–3 occurrences**, not anticipation. Pattern extraction on the first occurrence is likely premature abstraction — the pattern's actual shape isn't yet known. By the second or third occurrence, both the pattern and its variations are visible and a carrier can be designed without guessing.

The number is not a hard rule; some patterns are obvious on first sight, others never reach the threshold. The discipline is to *notice* when something has recurred and *deliberately decide* whether to extract — not to default to "do it manually again."

### Choice of carrier

The carrier is whichever artifact (per COR-006) fits the pattern's shape best:

- A repeating procedural workflow → a **skill**.
- A repeating perspective with boundaries → an **agent**.
- A repeating choice that should be locked → a **decision**.
- A repeating piece of state or reference → a **doc**.
- A repeating low-level action across many tasks → a **script** or **template**.
- A repeating *kind of pattern* (a meta-pattern) → meta-tooling, recursively.

COR-006 decides the carrier; this record decides whether to invest in one at all.

### Recursive application

The principle applies to itself. If extracting a `skill-author` agent becomes patterned (also wanting `agent-author`, `decision-author`, etc.), the right response is meta-tooling that handles pattern extraction across artifact types — not five hand-authored specialist agents. Self-application is the test that confirms the principle is live and not slogan.

## Rationale

**Why this is a methodology principle, not just a productivity tip.** A methodology is the accumulated discipline of doing certain kinds of work well. Tooling is what crystallises that discipline into a transferable form. Without pattern extraction as a deliberate practice, methodology quality stalls at "the founders' folklore" and never compounds across people or projects.

**Why the trigger is recurrence rather than anticipation.** Premature abstraction is a real failure mode. The pattern's actual shape — what varies vs what's stable — is invisible until you've done it a few times. Extracting on the first occurrence locks in guesses; extracting after recurrence locks in observations.

**Why the carrier choice belongs to COR-006, not here.** Conflating "should we extract?" with "what artifact should the extraction be?" overloads this principle. Two records, two questions; each stays sharp.

**Why recursion is named explicitly.** A principle that doesn't pass its own test would be hypocrisy. Naming the recursive case forces the principle to stay consistent with itself.

### Alternatives considered

- **Leave the disposition implicit.** Rejected — without an explicit rule, drift happens silently. Naming it makes it visible to call out when it's slipping.
- **A hard rule like "extract on the second occurrence."** Rejected — different patterns reach the threshold at different rates. A hard rule trades one drift mode for another.
- **Limit the rule to skills only.** Rejected — the principle is broader. Decisions, docs, agents, scripts, and templates all emerge from pattern extraction.

## Implications

- **Authoring tooling** — when a skill or agent is authored, the implicit reasoning is "this pattern recurred." That reasoning belongs in the artifact's commit message or README, not buried.
- **Reviewing for missed patterns** — periodic review of what's been done manually multiple times surfaces extraction candidates. No formal cadence yet; deferred until the project is bigger.
- **Adopter relevance** — the disposition propagates. Adopters who recognise recurring shapes in their own work apply the same rule.
- **`CLAUDE.md` cross-reference** — a one-line pointer ensures the disposition is loaded every session, without restating the rule (per COR-006's single-source-of-truth discipline).
