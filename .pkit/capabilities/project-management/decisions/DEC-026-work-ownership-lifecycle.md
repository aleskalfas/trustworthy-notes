---
id: DEC-026
title: Work-ownership lifecycle — seven workflow wrappers compose over `move-issue`
status: accepted
date: 2026-05-27
author: Ales Kalfas
---

## Context

[project-management:DEC-006-state-machine-and-cascade] fixed the five-state issue machine (Todo → Backlog → In Progress → Review → Done) and the transition-authorisation table (who owns each gate). [project-management:DEC-020-methodology-as-executable-commands] fixed the verb-subject convention as the methodology's executable surface and ships `move-issue` as the substrate state-transitioner — it owns the actual state change, the DEC-006 cascade, and the DEC-021 membership gate. [project-management:DEC-024-lifecycle-hooks] anchored `after_move_issue` as *the* hook event for state changes.

What's missing is the layer above `move-issue` that captures the **standard work-flow**: the human-or-PM-driven sequence that moves an issue from triage to merged. The standard flow has structure `move-issue` alone doesn't express:

- **Audit-trail comments** for transitions that carry human authorisation (verbal-in-session promotion, bypass approvals, ownership handoff). The authorisation source has to live on the issue.
- **Workflow side-effects** beyond the state change itself: `start-work` creates a branch + assigns; `review-work` opens a PR; `done-work` merges + pulls.
- **Composite gates** specific to each workflow step: `done-work`'s three-way approval check, `review-work`'s branch-name-matches-issue-type validation, `promote-issue`'s milestone-exists check, `create-draft`'s "commit exists on branch" precondition.

Today these side-effects and gates are scattered. The project-manager might invoke `move-issue` directly to flip Backlog → In Progress *and then separately* run branch-creation. Each call site reimplements the orchestration. The audit comments — when present — vary in format. The gate enforcement varies in strictness.

The **PR sub-lifecycle** compounds this. Real-world development uses draft PRs (CI runs but the work isn't yet ready for review), ready-for-review PRs (reviewers requested), and the round-trip between them when changes are requested. Today the methodology has no vocabulary for draft↔ready transitions or for reviewer-assignment defaults — these happen by hand or by ad-hoc `gh pr ready` / `gh pr ready --undo` invocations.

Four problems follow:

1. **Audit-trail invisibility.** Authorisation-bearing transitions sometimes carry comments and sometimes don't, with no standard prefix shape.
2. **Orchestration scattered.** No single command owns "start work" as a coherent operation; the human or agent assembles it from primitives.
3. **PR sub-lifecycle informal.** Draft↔ready transitions and reviewer assignment have no methodology-owned vocabulary.
4. **Lifecycle vocabulary diffuse.** DEC-024's `after_move_issue` fires on *every* state transition equally — the kit has no name for "this transition was part of a standard workflow step" vs "this was a one-off retag". Vocabulary for the standard flow doesn't exist.

Review-mode resolution (which kind of approval gate applies to a given PR) is a *related but separable* concern. This DEC defers that question to [project-management:DEC-027-review-modes] (the resolution algorithm + human path) and [project-management:DEC-028-agent-as-approver-paths] (the agent path mechanism). The three DECs land as a coherent set; this one owns the seven-command palette + PR sub-lifecycle, DEC-027 owns review-mode resolution + the human path, DEC-028 owns the agent-as-approver mechanism.

The example-brownfield methodology (the upstream this capability distilled from) solved this with five `mise run work:*` tasks. This DEC adopts that pattern into the pm capability.

## Decision

The pm capability ships **seven verb-subject workflow-wrapper commands** that compose over `move-issue` to own the standard work-flow. They are the **workflow-wrapper layer** per [project-management:DEC-020-methodology-as-executable-commands]'s per-layer invocation discipline; `move-issue` remains the substrate state-transitioner.

The per-layer invocation principle (workflow wrappers / substrate primitives / gh — invoke at the appropriate layer) lives in DEC-020 with the wrapper-substrate distinction. This DEC adds the wrapper layer's *contents* — what specific wrappers exist, what each one composes, and how the PR sub-lifecycle is modelled within that layer.

### The seven commands

| Command | DEC-006 transition (delegated to `move-issue`) | PR-state effect | Composite gates + side-effects |
|---|---|---|---|
| `promote-issue <N> [--milestone "<M>"] --reason "<R>"` | Todo → Backlog | none | `--reason` non-empty; **if** `--milestone` is given, `<M>` matches exact title of an OPEN milestone (omit it to promote milestone-free); current `Status = Todo`. Posts audit comment, attaches the milestone when given, then calls `move-issue --to backlog`. |
| `start-work <N>` | Backlog → In Progress | none | Current user is a team member (DEC-021 open-mode degrades to no-op); issue not assigned to someone else; if a branch exists, matches `<type>/<N>-<slug>`. Creates branch, sets assignee, then calls `move-issue --to in-progress`. |
| `create-draft <N>` | (no transition; issue stays In Progress) | None → Draft | Branch exists per `<type>/<N>-<slug>`; at least one commit not on `main`. Opens a *draft* PR via `gh pr create --draft`. No reviewer assignment yet. Used when the PR is needed for CI but the work isn't yet ready for review. |
| `review-work <N>` | In Progress → Review | None → Ready, **or** Draft → Ready | Current branch matches `<type>/<N>-<slug>`; branch's `<type>` prefix matches issue's `type:*` label per DEC-013; PR title is Conventional Commits. Opens a ready PR if none exists; flips draft→ready if a draft exists. Assigns reviewers (see "Reviewer assignment" below), then calls `move-issue --to review`. |
| `back-to-draft <N>` | (no transition; issue stays in Review) | Ready → Draft | A ready PR exists for the issue. Flips PR draft via `gh pr ready --undo`. Dismisses any stale `APPROVED` reviews via `gh pr review --dismiss` to prevent the next `done-work` from acting on outdated approval (see "Stale-approval handling" below). Used by the author after a reviewer requests changes to signal "I have more work to do — not currently ready for re-review." Issue stays in Review because the PR is still in the review *workflow* even when draft. |
| `done-work <N> [--bypass "<R>"]` | Review → Done | Ready → Merged | Approval gate is **mode-conditional** per [project-management:DEC-027-review-modes]: in `human` mode the three-way OR (latest APPROVED review, `Approved`-prefix comment from non-author, or `--bypass "<reason>"`); in `agent` mode the agent-verdict path per [project-management:DEC-028-agent-as-approver-paths] plus `--bypass`. Squash-merges, pulls `main`, then calls `move-issue --to done`. |
| `handoff-issue <N>` | (no state change) | none | Current user is a team member; issue currently in `In Progress` or `Review`. Posts audit comment; calls `gh issue edit --remove-assignee <from> --add-assignee <to>`. No `move-issue` call (no state transition). |

`handoff-issue` exists because the alternative to handing off an in-flight issue is closing it — which loses sub-issues, comments, and branch state. Continuing under a new owner is the common case for vacation, illness, or scope shift.

> **Amendment (#61, under EPIC #59) — `promote-issue --milestone` is optional; the command carries a two-substrate authorisation.** As accepted, the row hard-required `--milestone` to resolve to an OPEN Milestone, which made `promote-issue` unusable in a project that has created no Milestone *instances* (e.g. project-kit: a Milestone category is declared but no Milestone exists). The only Todo → Backlog path there was `move-issue --to backlog --bypass`, which loses the authorisation-source attribution `promote-issue` exists to capture. The contract now: `--milestone` given → resolve + attach as before; `--milestone` omitted → promote on `--reason` alone, posting the same audit comment and calling `move-issue --to backlog`, with no Milestone attachment. The audit comment text (`Promoted Todo → Backlog by PM on user's in-session request: <reason>`) is already Milestone-free, so no template fork is needed.
>
> This broadens the *substrate* of the Todo → Backlog authorisation (Milestone-assignment OR audited verbal reason) without touching its severity — the transition stays **bypassable-with-audit** per [project-management:DEC-006-state-machine-and-cascade] (see that record's #61/#62 amendment, which also records the decline of the proposal to lower the severity for milestone-less projects). The `--reason` is the audit substrate that satisfies the gate when no Milestone is assigned.

### PR sub-lifecycle and issue-state mapping

The PR has its own state machine, coupled to the issue state machine:

| PR state | Issue state | Command(s) that enter it |
|---|---|---|
| **None** (no PR yet) | In Progress | `start-work` completes; author hasn't opened a PR |
| **Draft** | In Progress *or* Review | `create-draft` (from In Progress, no transition) or `back-to-draft` (from Review, no transition) |
| **Ready** (open for review, reviewers assigned) | Review | `review-work` (from None or Draft; transitions issue to Review) |
| **Merged** | Done | `done-work` |

The PR-state column is informational — the methodology doesn't store it independently; it's derivable from `gh pr view --json isDraft,state`. The commands above are the legitimate transitions; manual `gh pr ready` / `gh pr ready --undo` / `gh pr merge` from outside the wrappers bypasses the audit + gate layer (same per-layer principle from DEC-020).

PR closure without merge (the PR is abandoned, replaced, or superseded) is out of scope here — `close-issue` and a future `close-pr` wrapper cover that path; see "Closure outside the standard flow" below.

### Stale-approval handling

`back-to-draft` dismisses any PR reviews that are currently in `APPROVED` state via `gh pr review --dismiss`. Without this, the standard `done-work` cycle is vulnerable to a stale-approval failure mode: a PR was approved, then changes were requested and made, and `done-work` merges on the stale approval without the reviewer seeing the new changes. Dismissing on `back-to-draft` forces re-review when the PR comes back to Ready.

Adopters who configure GitHub branch-protection with "Dismiss stale pull request approvals when new commits are pushed" get equivalent protection at the substrate; the wrapper's dismissal is belt-and-suspenders.

### Reviewer assignment

Reviewer assignment is governed by **review-mode resolution** per [project-management:DEC-027-review-modes]. Briefly:

- The effective mode (`agent` or `human`) is resolved per PR via three layers: project-default config → per-issue `review:<mode>` label → `review-work --require-human` flag. DEC-027 owns the resolution algorithm.
- **`agent` mode (default)**: no human reviewers are auto-assigned. The registered agent reviews per [project-management:DEC-028-agent-as-approver-paths]; the gate is satisfied by the agent's verdict comment.
- **`human` mode**: `review-work` queries `members.yaml` for members whose `role:` matches the configured `review.human_review.reviewer_role:`, excluding the PR author. The matched members are assigned as PR reviewers via `gh pr edit --add-reviewer`.
- **`--reviewer @<user>` override**: explicit reviewer assignment; overrides the role-based default in any mode.
- The audit comment for `review-work` is the PR creation itself plus the reviewer-assignment metadata GitHub records — no separate audit comment.

### Closure outside the standard flow

`close-issue` (existing) handles abandonment (won't-do, duplicate) — not part of this DEC's palette because it isn't a forward-progress workflow step. The seven commands here cover **forward progress and the draft↔ready round-trip**; closure-without-completion is its own command.

### Audit-trail comments

Each authorisation-bearing transition writes a parseable-prefix comment using DEC-024's template-stamp idempotence discipline (re-running a command checks for an existing comment with the same template stamp and skips re-posting):

- `promote-issue` → `Promoted Todo → Backlog by PM on user's in-session request: <reason>`
- `done-work --bypass` → `Approved by bypass: <reason>`
- `handoff-issue` → `Handoff: @<from> → @<to> (YYYY-MM-DD, reason: <text>)`

`start-work` and `review-work` write no comment because the action itself is the audit trail (branch creation + assignee for start; PR creation for review). The `Promoted`, `Approved`, `Handoff` prefixes mirror example-brownfield's `<verb>: <details>` convention; future tooling may parse them as state-machine signals.

### Failure semantics

Per example-brownfield's discipline (`WORKFLOW.md` "Failure recovery"): **the audit trail is non-negotiable**. If a comment posts but a later step fails, the comment stands; the error message names the retry command so the operator can finish the operation by hand without re-posting the comment. The audit-comment idempotence above ensures re-running the wrapper command after a partial failure recovers cleanly.

For `done-work`: the squash-merge is *not* rolled back on a subsequent failure (pull-main fails, the post-merge cascade fails). The merged state is durable; the operator runs the recovery commands the error message names. This is intentional — merge irreversibility is the architectural constraint.

### Idempotence

All seven commands are idempotent at the level of *observable state* (issue state, PR state, branch existence). Invoking when state already matches the target is a no-op; invoking when transition is needed performs it. Re-running after a partial failure recovers without duplicating the audit comment, without re-creating the branch, without re-opening the PR, without re-flipping draft↔ready. The implementing scripts adopt DEC-024's template-stamp idempotence discipline for any comment-posting step.

### Open-mode degradation

When the pm capability is configured in open mode per DEC-021, the team-membership hard-gate degrades to a no-op for `start-work` and `handoff-issue` — anyone can start or hand off.

For `handoff-issue` specifically: open-mode still supports the operation as a self-service ownership-transfer (`@<from> → @<to>` is recorded regardless of whether there's a formal "team"; the audit comment retains its value as the trace of the change). The two-party-consent semantic the `handoff` verb suggests is informational in open mode — the assignee field changes and the comment records who did it, without a membership-check enforcement layer.

### Sub-decisions index

| Topic | Resolution |
|---|---|
| Assignee conflict in `start-work` (issue already assigned to another team member) | Hard refusal; error message points at `handoff-issue`. No `--force` escape. |
| Branch already exists when running `start-work` | Idempotent: no-op if branch matches `<type>/<N>-<slug>`; refuse if branch exists with wrong shape. |
| Team membership in DEC-021 open mode | Hard-gate degrades to no-op. |
| Handoff audit comment shape | `Handoff: @<from> → @<to> (YYYY-MM-DD, reason: <text>)`. Parseable prefix. |
| `done-work` approval gate | Mode-conditional per [project-management:DEC-027-review-modes]: in `human` mode, three-way OR (latest APPROVED review, `Approved`-prefix comment from non-author, or `--bypass "<reason>"`); in `agent` mode, the agent-verdict path per [project-management:DEC-028-agent-as-approver-paths] plus `--bypass`. |
| PR sub-lifecycle modelling | The PR has its own state machine (None / Draft / Ready / Merged) coupled to the issue state machine. Draft↔Ready transitions get explicit commands (`create-draft`, `back-to-draft`); the mapping table in "PR sub-lifecycle and issue-state mapping" is authoritative. PR closure without merge is out of scope here (handled by `close-issue` + future `close-pr`). |
| Reviewer assignment in `review-work` | Per [project-management:DEC-027-review-modes]'s mode resolution. In `human` mode: role-based query of `members.yaml`. In `agent` mode: no human auto-assignment. `--reviewer @<user>` override available in any mode. |
| Stale-approval handling on `back-to-draft` | Dismisses prior `APPROVED` reviews via `gh pr review --dismiss` so the next `done-work` cycle requires fresh review of changed content. |
| Membership gate on `create-draft` and `back-to-draft` | Same as other state-changing commands per [project-management:DEC-021-team-membership-gate]: current user must be a team member (closed mode); open-mode degrades to no-op. |
| Naming convention (`work` vs `issue` subject) | Subject = `work` when the command operates on the work-in-progress (branch + assignee context exists — start/review/done); subject = `issue` when the command operates at the ticket level without WIP context (`promote-issue` runs before WIP exists; `handoff-issue` shifts ownership without branch change). Hyphenated single token per DEC-020. |
| `handoff-issue` in open mode | Functions as self-service ownership transfer; audit comment posts regardless of formal team membership. The verb's two-party-consent connotation is informational in open mode. |

### Schema-level commitment

The seven command names are bound to `schemas/workflow.yaml` — a single schema, not a split. Each issue-state transition entry gains a `command:` field naming the wrapper that owns it; the entry without a wrapper (closure as won't-do) has `command: close-issue`. The PR sub-lifecycle is modelled as additional fields on the same transition entries: a `pr_state_effect:` field records "none → ready" (for `review-work`), "none → draft" (for `create-draft`, paired with a no-issue-transition row), "ready → draft" (for `back-to-draft`, also no-issue-transition), and "ready → merged" (for `done-work`). PR state is *coupled* to issue state by construction, and modelling them in one schema preserves that coupling at the file level.

This binding makes the wrapper-to-transition relationship schema-checkable, prevents wrapper names from being free variables across the corpus, and gives the convention-compliance-reviewer something to validate.

## Rationale

**Why compose over `move-issue`, not replace it.** `move-issue` is the existing substrate that already owns the DEC-006 cascade, DEC-021 membership, and the substrate-specific (board vs label-fallback) mechanics. Replacing it would duplicate that logic across seven new scripts; composing over it keeps the substrate-aware code in one place. DEC-024's `after_move_issue` hook continues to fire from `move-issue` regardless of which wrapper invoked it, so the existing hook surface is preserved.

**Why seven (and not just four issue-state-transitioners).** DEC-006 has four forward-progress issue transitions, which give the four commands `promote-issue / start-work / review-work / done-work`. Three more commands cover concerns DEC-006 doesn't model:

- `handoff-issue` — ownership change without state transition (alternative to abandoning in-flight work).
- `create-draft` — PR creation before the work is ready for review (so CI can run during in-progress work).
- `back-to-draft` — PR-state round-trip after a reviewer requests changes; the issue stays in Review (the work-flow phase hasn't changed, only the PR-readiness).

Won't-do closure is `close-issue` — explicitly outside this palette because abandonment is its own concern, not a step in the standard work-flow.

**Why model the PR sub-lifecycle in the palette.** Real-world development has draft↔ready round-trips driven by review feedback, and the methodology can't pretend they don't exist. Modelling them gives reviewers and authors named commands instead of ad-hoc `gh pr ready --undo` invocations, keeps the audit trail consistent (the issue-state side-effect is automatic), and gives the convention-compliance-reviewer something to enforce.

**Why `handoff` not `reassign`.** `handoff` connotes consent of both parties; `reassign` connotes unilateral. The semantic matches the typical case: the assignee change is requested by the previous owner (blocked, unavailable), not unilaterally imposed.

**Why the three-way OR for `done-work` approval in `human` mode.** Adopted verbatim from example-brownfield's `work:done`: formal `APPROVED` review, `Approved`-prefix comment from the last non-bot commenter (case-sensitive exact prefix), and `--bypass "<reason>"`. Each path is auditable: a review carries its own metadata; a comment is on the issue; `--bypass` posts the reason as a comment. The agent path in `agent` mode is settled in [project-management:DEC-028-agent-as-approver-paths]; the mode resolution that picks between them is in [project-management:DEC-027-review-modes].

**Why keep the issue in Review during `back-to-draft`.** When a reviewer requests changes and the author flips the PR back to draft, the issue is still in the review *workflow* — the reviewer is waiting to re-review, and the author is briefly addressing comments before re-marking ready. Flipping the issue to In Progress would lose the "this work is being reviewed, just not currently re-reviewable" signal. The PR-state flip is enough to communicate "not currently ready"; the issue-state stays in Review because the work-flow phase hasn't changed.

The per-layer invocation principle that determines when to use a wrapper vs `move-issue` vs `gh` lives in DEC-020 (refined as part of this DEC's landing); enforcement is also covered there (convention + code review + convention-compliance-reviewer awareness).

### Alternatives considered

- **Replace `move-issue` as the state-transitioner; the wrappers own the state change directly.** Rejected. `move-issue` owns the substrate-specific mechanics, DEC-006 cascade walk, and DEC-021 membership gate. Replacing it would duplicate that logic across the wrappers and break DEC-024's existing `after_move_issue` hook contract. Composition is cheaper and preserves the hook surface.

- **Three commands only (`start-work`, `review-work`, `done-work`); promote and handoff handled by direct `move-issue` or `gh`.** Rejected. `promote-issue` exists *because* verbal-in-session authorisation needs the audit comment — direct `move-issue` loses the authorisation-source attribution. `handoff-issue` exists *because* the alternative (close + refile) loses history.

- **One generic `transition <N> <to-state>` command on top of `move-issue`.** Rejected. Each transition's *composite gates* and *side-effects* are different (promote needs milestone + reason + audit comment; start needs branch + assignee; review needs PR + type-prefix; done needs approval + merge). A generic command needs an unwieldy flag matrix; the verb-subject form per DEC-020 keeps each command focused and discoverable.

- **Generate the wrapper scripts from `workflow.yaml`'s `transitions:` list.** Rejected at v1 — the wrappers' side-effects (branch creation, PR creation, merge, draft↔ready flip) are non-uniform enough that generic generation would carry conditional logic per transition. Hand-coded scripts are clearer; the schema records the binding but doesn't generate the bodies. Revisit if an eighth wrapper appears and the per-wrapper boilerplate becomes a tax.

- **Allow humans to bypass the wrappers (use `gh` directly); constrain agents only.** Rejected. The audit trail and gate consistency benefits apply equally to human and agent workflows. The wrapper is also faster (one command vs three) for humans in the standard case. Comp-analysis's WORKFLOW.md does carve out a "user prefers to drive directly" path for promotion (raw `gh issue edit --milestone` + `project:sync`); this DEC adopts the same carve-out implicitly by *allowing* `move-issue` direct for non-flow state changes — but the standard flow stays in the wrappers.

- **Use git hooks (post-commit / post-checkout) to drive transitions.** Rejected. Coupling git workflow to issue workflow makes both fragile. Lifecycle hooks per DEC-024 fire at `move-issue` (the substrate) — they don't need a separate git-hook layer.

- **Use a generic state-machine library to define gates declaratively.** Rejected. The gates are interdependent with substrate calls (gh review check, branch shape, milestone existence); abstracting them adopts a library's mental model on top of the methodology's, with little benefit at this scale.

- **Adopt mise tasks (`mise run work:start <N>`) verbatim from example-brownfield instead of Python scripts.** Rejected. mise is the upstream's task-runner; the pm capability ships per-script `*.py` files per DEC-020 (uv-runnable, PEP 723, dispatcher-resolvable via `pkit project-management <verb>-<subject>`). The shape changes; the substance is preserved.

## Implications

- The pm capability ships seven new scripts at `.pkit/capabilities/project-management/scripts/`: `promote-issue.py`, `start-work.py`, `create-draft.py`, `review-work.py`, `back-to-draft.py`, `done-work.py`, `handoff-issue.py`. Of these, `start-work`, `review-work`, `back-to-draft`, and `done-work` compose over `move-issue.py` for their issue-state transitions. `create-draft` and `back-to-draft` add PR-state side-effects via the `gh pr create --draft` / `gh pr ready --undo` substrate; `back-to-draft` additionally dismisses prior `APPROVED` reviews via `gh pr review --dismiss`.
- `schemas/workflow.yaml`'s `transitions:` list gains two new fields per entry: `command:` (naming the wrapper that owns the transition) and `pr_state_effect:` (recording the PR-state change the wrapper drives, e.g. `none → ready`). Two no-issue-transition rows are added for `create-draft` and `back-to-draft` so the PR sub-lifecycle is captured in the same file. Adopters who customise `workflow.yaml` set these fields per the migration policy below. This is a schema_version bump per COR-010 — a migration script updates installed adopters' `workflow.yaml` on the next `pkit upgrade`.
- Each command consumes [project-management:DEC-023-gh-host-and-owner]'s `gh` helper for any `gh` shell-outs not delegated to `move-issue` (i.e., `gh pr create`, `gh pr merge`, `gh issue comment`).
- [project-management:DEC-024-lifecycle-hooks] fires `after_move_issue` from the substrate when a wrapper triggers a state transition — no change to the existing hook surface. `after_open_pr` and `after_merge_pr` fire from `review-work` and `done-work` respectively, also using DEC-024's existing event names. No new hook event names are introduced by this DEC.
- Existing project-manager and human workflows that currently call `move-issue` directly for standard-flow transitions migrate to the seven wrappers. Direct `move-issue` use remains valid for non-flow state changes (e.g. triage retag).
- `close-issue` (existing, won't-do closure) remains outside this palette per the rationale above. The convention-compliance-reviewer's awareness of "use the wrapper for forward-progress flow" doesn't extend to `close-issue`.
- Each command has gate-enforcement + idempotence tests at `.pkit/capabilities/project-management/scripts/tests/`. Tests cover the sub-decisions table above.
- The pm capability bumps minor version on landing (per [PRJ-002] surface-change rule — seven new commands plus a `workflow.yaml` schema_version bump for the `command:` and `pr_state_effect:` fields). The migration script updates installed adopters' `workflow.yaml`:
  - For unmodified kit-default transition rows (matched by `(from, to)` tuple), inject the `command:` and `pr_state_effect:` fields with kit-default values.
  - For adopter-customised or adopter-added rows, leave the rows untouched and warn the adopter (with the missing-field details) so the adopter sets the fields explicitly. The migration is idempotent per `.pkit/rules/core.md` rule 5 — re-running on a partially-migrated file does not clobber adopter changes.
- **Acceptance gate** (per `.pkit/rules/core.md` rule 2): this DEC lands as `proposed`. Promotion to `accepted` is a separate gesture. Implementation work citing this DEC (the seven scripts, the schema bump, the migration) is forbidden until acceptance. [project-management:DEC-027-review-modes] and [project-management:DEC-028-agent-as-approver-paths] are the sibling DECs for review-mode resolution and the agent approval path; the three land as a coherent set, each may accept independently.
