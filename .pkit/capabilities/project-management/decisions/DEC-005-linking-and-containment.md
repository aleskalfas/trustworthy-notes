---
id: DEC-005
title: Native sub-issues + textual first-line parent-ref; explicit containment graph
status: accepted
date: 2026-05-21
author: Ales Kalfas
source:
  upstream: pm-workflow
  upstream_id: MET-004
  commit: 9d1f0237f5d5778ed9811c72f22ae8268e5faff3
  captured_at: 2026-05-21
---

## Context

The hierarchy from [project-management:DEC-004-six-level-hierarchy] needs a mechanism that links children to parents in a way that's both UI-visible (so a parent surfaces its children automatically) and readable in contexts where the GitHub UI isn't rendering (PR bodies, diffs, exported issues, archived snapshots). It also needs containment rules so the validator can refuse impossible filings (a Feature inside a Feature, an EPIC under another EPIC).

## Decision

### Canonical mechanism: native sub-issues

The capability uses **GitHub's native sub-issues field** as the canonical structural mechanism. The agent reads and writes the `parent` and `subIssues` GraphQL fields on every parent-link mutation. Native sub-issues populate the Projects v2 "Sub-issues progress" board field automatically.

| Relation | Substrate |
|---|---|
| Hierarchy parent ↔ child | Native sub-issue field |
| Issue → delivery wave | Native Milestone field |
| "Blocked by", "follow-up to", "see also" | Textual in a body section |
| Cross-repo references | Textual (`owner/repo#N`) |
| PR closes Task | Textual `Closes #N` in PR body |

### Textual first-line projection

Every issue body opens with a textual ancestry ref naming the immediate parent in `<Type>: #<N>` form. The exact form per issue type is fixed in [`schemas/issue-types.yaml`](../schemas/issue-types.yaml)'s `parent_ref_form` field. The agent maintains the line on every parent-link mutation; if the textual line disagrees with the native parent field, **native wins** and the agent rewrites the line to match.

### Containment graph

The containment rules are encoded in [`schemas/issue-types.yaml`](../schemas/issue-types.yaml) two ways:

- Per-entry `can_contain` and `parent_issue_types` lists fix the allowed parent/child edges in the graph.
- The schema-level `containment_invariants` block names the cross-cut rules that aren't expressible as single per-type fields:
  - EPIC does not contain EPIC (no chains of nested theses).
  - Feature does not nest (atomic capability claim).
  - Feature does not contain Umbrella (same atomicity invariant).
  - Task contains only markdown sub-tasks, not other issues (sub-task promotion changes the parent of the new Task to the *original Task's parent*).

The validator refuses filings that violate either layer. Severity is `[validation-severity:hard-reject]` — containment violations corrupt downstream logic.

## Rationale

Native sub-issues fix the parent-side visibility failure automatically — parents surface their children in the GitHub UI without any human or agent action. The textual first-line projection fixes the child-side readability problem and survives in environments where the GitHub UI isn't rendering. Maintaining both in parallel is free in an agent-mediated context: the agent writes both on every mutation, and the "native wins" rule resolves disagreements deterministically.

The containment graph formalises the Feature/Umbrella distinction from [project-management:DEC-004-six-level-hierarchy]. Allowing Feature-in-Feature would muddy that distinction; allowing EPIC-in-EPIC would invite long chains of nested outcomes that no one reads. The schema-level invariants encode these rules where the engine can dispatch on them.

### Alternatives considered

- **Textual only (no native sub-issues).** Rejected — fails the parent-side visibility test. Even with agent-maintained textual conventions, GitHub's UI doesn't render parents without native links.
- **Native only (no textual projection).** Rejected — loses readability outside the GitHub Issue UI.
- **Loose containment (anything contains anything).** Rejected — erases the Feature/Umbrella distinction.

## Implications

- The create-issue skill walks the issue-types schema's containment graph to refuse impossible filings before mutating GitHub.
- The validate-body skill checks the first-line parent-ref against the type-specific `parent_ref_form` pattern; a missing or wrong-shape ref is a hard reject.
- The project-manager maintains the textual line on every native parent-link mutation; if the two disagree, the agent rewrites the text to match the native field (per the "native wins" rule).
- Cross-repo references stay textual (`owner/repo#N`); native sub-issues do support cross-repo but the textual form reads better in most contexts.
- Promoting a markdown sub-task to a standalone Task changes the new Task's parent to the *original Task's parent* (not the original Task) — see [`schemas/body-format.yaml`](../schemas/body-format.yaml)'s `sub_task_promotion` block.
- "Sub-issues progress" on a Projects v2 board populates from native sub-issues automatically, giving parents a built-in completion view at no engine cost.
