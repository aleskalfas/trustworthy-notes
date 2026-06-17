---
id: DEC-015
title: Code and docs ship together — mandatory `## Doc impact` sections on Tasks and PRs
status: accepted
date: 2026-05-21
author: Ales Kalfas
source:
  upstream: pm-workflow
  upstream_id: MET-014
  commit: 9d1f0237f5d5778ed9811c72f22ae8268e5faff3
  captured_at: 2026-05-21
---

## Context

Docs that describe code rot the moment code and docs ship separately. The "we'll update the docs in a follow-up" pattern produces follow-ups that never happen and docs that lie about current behaviour. The capability has to enforce the code-and-docs-together principle without imposing a specific doc system on every adopter — the mechanism has to work in projects with mature docs and in projects with minimal docs, producing a one-line justification in the latter case.

## Decision

### Principle

When a Task changes code or behaviour, any docs that describe that code or behaviour must change in the **same PR**.

### Mandatory `## Doc impact` section in Task body

Every Task body carries a mandatory `## Doc impact` section. Encoded as a required section in [`schemas/body-format.yaml`](../schemas/body-format.yaml)'s `bodies.task.required_sections` with severity `[validation-severity:hard-reject]`. One of two shapes:

**Shape A — docs need updating:**

```markdown
## Doc impact
- [ ] Update README.md "Install" section to reference the new sandbox image name
- [ ] Update CONTRIBUTING.md to document the new --workspace flag
- [ ] Add a one-line note to CHANGELOG.md under "unreleased"
```

Standard checkbox rules from [project-management:DEC-007-checkbox-validation] and [project-management:DEC-009-living-documents] apply — doc-impact checkboxes count toward the close-gate the same way acceptance criteria do.

**Shape B — no doc impact:**

```markdown
## Doc impact
No doc impact: internal refactor only; no behavioural change observable from any user-facing surface.
```

A one-line justification is **required** — "no doc impact" alone isn't accepted. The validator hard-rejects an empty Shape B. Forces deliberate consideration.

### Mandatory `## Doc impact` section in PR body

The PR body carries a matching `## Doc impact` section mirroring what was actually done. Encoded as a required PR-body section in [`schemas/git-conventions.yaml`](../schemas/git-conventions.yaml)'s `pr-body` entry with severity `[validation-severity:hard-reject]`:

```markdown
## Doc impact
- Updated README.md "Install" section (commit 4a3b2c1).
- Updated CONTRIBUTING.md to document --workspace (commit 5e8f3a2).
- No CHANGELOG.md entry needed — the unreleased branch already lists this change.
```

Differences between the Task's planned doc impact and the PR's actual doc impact are surfaced by the project-manager as a warning for human reconciliation (typically by editing the Task body to match reality per [project-management:DEC-009-living-documents]).

### Optional: project-specific code-path → doc-path mappings

Adopters may declare a mapping like:

```
src/sandbox/**            → README.md, docs/sandbox.md
src/cli/**                → docs/cli/commands.md
scripts/work-*.sh         → WORKFLOW.md
```

When configured, the project-manager runs the mapping at PR-open time and emits a `[validation-severity:warning]` if the PR touches a code path without touching the mapped doc path. The user can acknowledge the warning or edit the mapping if the rule is stale.

The mapping config lives in the adopter's project namespace (the capability is team-wide generic per [project-management:DEC-002-team-wide-generic-scope]; specific paths are project-side).

### Severity classifications

| Validation | Severity |
|---|---|
| Task body has a `## Doc impact` section in Shape A or Shape B | `[validation-severity:hard-reject]` |
| Shape B's justification is non-empty (not just `No doc impact`) | `[validation-severity:hard-reject]` |
| PR body has a `## Doc impact` section | `[validation-severity:hard-reject]` |
| Task's planned doc impact diverges from PR's actual doc impact | `[validation-severity:warning]` |
| PR touches code path with a mapped doc rule the PR doesn't touch | `[validation-severity:warning]` (adopter may upgrade) |

## Rationale

Code-and-docs-together is a hard discipline because the rewards are deferred (docs that don't rot, six months from now) and the costs are immediate (the PR is bigger). Making the `## Doc impact` section mandatory — including the Shape B justification — keeps the question visible without imposing a specific doc system on every adopter.

The Shape B "no doc impact: ..." pattern is the trick that makes the rule live in projects without rich docs. The author still has to *consider* docs; they just legitimately conclude there's no impact. Without the mandatory section, the consideration never happens.

Project-side mappings give an extra signal where the adopter has invested — the agent catches the obvious "this code change should have touched this doc" cases. They stay optional because not every adopter has stable enough docs to maintain mappings against.

### Alternatives considered

- **Voluntary doc-update mention (no required section).** Rejected — soft conventions drift; docs end up un-updated.
- **Mandatory doc-update with no Shape B escape.** Rejected — forces internal refactors with no doc impact to invent updates. One-size-fits-all rule that doesn't fit.
- **Doc-update as a separate Task linked to the implementation Task.** Rejected — separates code from docs; the rot we're preventing returns immediately.
- **Mandatory project mappings (not optional).** Rejected — many projects don't have mature enough docs to define mappings; the capability should work without them.

## Implications

- The validate-body skill enforces the Task-body `## Doc impact` section at filing and edit time (hard reject if missing or malformed).
- The project-manager enforces the PR-body `## Doc impact` section at PR-open time (hard reject if missing).
- The project-manager's PR-open flow checks planned-vs-actual doc impact and emits a warning if they diverge.
- For projects without rich docs, every Task body legitimately uses Shape B with a brief one-line justification.
- Doc-impact checkboxes count toward [project-management:DEC-007-checkbox-validation]'s close-gate — unticked doc updates block Task close.
- Adopting projects may optionally define code-path → doc-path mappings; not part of the capability mandate.
- The `## Doc impact` section is instantiated in `templates/task.md` (Shape A and Shape B documented inline) and in `templates/pr.md` (showing the PR-side bullet form mirroring what was actually done).
