# pm batch-plan — take fuzzy intent + reference material and file a sliced plan behind a single approval gate

Sub-procedure of the pm composite skill (`pm.md` in this folder). The `project-manager` agent dispatches here when the user supplies fuzzy multi-issue intent + a reference document (scratchpad, handoff, related issue, decision record) and wants the work sliced into filed issues without a per-issue back-and-forth. The user-facing dialogue and scripted scenarios are authored in the storyboard sibling to the agent (`.pkit/capabilities/project-management/agents/project-manager/storyboard.md`) per [COR-016](../../../../decisions/core/COR-016-scripted-scenario-storyboards.md).

## When to use this operation

- The user provides intent + at least one reference artifact and asks the agent to plan / scope / slice the work.
- The agent infers batch-planning from request shape per step 3 of `project-manager.md`'s `How you work` — the user does not name "batch-plan mode" explicitly.

When the request is **single-issue** ("file this one bug", "create the EPIC for X"), use [create-issue](create-issue.md) directly instead.

## What this sub-procedure carries

Five sequential steps. The agent narrates each step's start to the user per the storyboard's tone rules; the procedural detail is here.

### 1. Read intent and reference material

- Read the user's fuzzy intent verbatim from the conversation.
- Read every reference artifact the user points at, using the `Read` tool. Common shapes: a scratchpad note under `.pkit/scratchpad/`, a handoff document, a related GitHub issue (fetch via `gh issue view`), a decision record, or a verbal description from earlier in the session.
- If any reference cannot be resolved (path not found, issue not accessible), surface the gap before proposing a slicing — do not guess content.
- If the user's intent has missing inputs that prevent slicing (no reference at all; scope too vague), ask at most two clarifying questions per the storyboard's Scenario 2 — not a sequence of single-question turns.

### 2. Propose the slicing

Apply the methodology's typing rules to the work units implied by intent + references:

- **Hierarchy choice** — [project-management:DEC-004-six-level-hierarchy] gives the Umbrella / EPIC / Feature / Task / Milestone taxonomy. Choose the smallest type that contains the work; do not over-nest. A multi-deliverable arc → EPIC with Feature children; a single deliverable → standalone Feature (no EPIC wrapper) per the small-adopter shortcut.
- **Classification per ticket** — [project-management:DEC-012-classification-axes] specifies workstream / priority / kind labels. Read the adopter's `project/workstreams.yaml` for allowed workstream values; the kind axis maps to `type:*` labels per the script's enforcement. Default priority is Medium unless intent signals otherwise.
- **Parent-refs** — [project-management:DEC-005-linking-and-containment] specifies the `Milestone: #N` / `EPIC: #N` / `Feature: #N` / `Task: #N` body-first-line format. The slicing must produce a consistent reference graph (no cycles; each child has the correct parent type per `issue-types.yaml`'s containment graph).
- **Dependency chain** — express ordering between issues either implicitly (via parent-refs) or explicitly (as Dependencies sections in the body). Flag tight coupling in the body's Approach / Notes section.
- **Milestone resolution** — if the adopter's config or the intent names a milestone, attach it. If neither, prompt before the approval gate.

Render the slicing as a single table the user can scan at a glance:

| # | Type | Title | Parent | Workstream | Milestone | Priority | Notes |
|---|---|---|---|---|---|---|---|

### 3. Adversarial review (when threshold applies)

Per [project-management:DEC-029-project-manager-agent-shape]'s reviewer-invocation discipline:

- **Multi-issue arcs (≥3 issues to file)** invoke the `critic` agent against the proposed slicing. Pass the slicing table + the source reference document.
- **Cross-component work (≥3 components touched, or any work introducing a new abstraction)** additionally invoke the `architect` agent.
- **Narrow single-issue work** skips the reviewer pass.

Capture each reviewer's findings. Decide per finding whether to (a) revise the slicing to incorporate the concern, (b) annotate the EPIC body's Approach / Notes section to record the unresolved concern, or (c) note the disagreement and let the user resolve at the approval gate.

### 4. Single approval gate

Present the slicing to the user as a single message:

- The slicing table.
- The dependency chain (explicit ordering).
- Reviewer findings summary (which were incorporated, which are noted, which need user resolution).
- Bodies are not shown at the gate — they are filled per ticket after approval. The slicing's classifications and parent-refs are the contract the user approves.

End the message with: "Approve, revise, or cancel?"

**No `gh` mutation happens before this gate fires positively.** On revision, return to step 2 and re-render. On cancel, end the operation; surface "Cancelled. Nothing filed." On approve, proceed to step 5.

### 5. File via primitives

In dependency order (parents before children so parent-ref values are available):

- For each ticket: call `scripts/create-issue.py` with `--type`, `--title`, `--kind`, `--workstream`, `--priority`, `--parent` (if any), `--yes`.
- Parse the script's `[ok] created: <URL>` line for the new issue number.
- Immediately call `scripts/edit-issue.py --body-file <tmp> --yes` to overwrite the auto-generated template body with the planned body content (the create-issue.py script produces a placeholder body; the real content is what was approved at the gate).
- Attach milestone via `gh issue edit <number> -R <repo> --milestone "<title>"` per the workaround for issue #177 (the create-issue.py `--milestone NUM` path is broken pending that issue's fix).
- Handle each script's failure modes per [validate-body](validate-body.md)'s severity model: warnings emit and continue; hard-rejects pause and follow the storyboard's Scenario 4 walkthrough.

After the filing loop completes:

- Surface the final state to the user: filed issue numbers + URLs, skipped issues (if any), total mutations.
- If state transitions were part of the plan (move issue from Triage to Backlog, etc.), invoke the [transition-state](transition-state.md) sub-procedure for each transition. Cascades fire per the workflow schema.

## Handling failures during filing

Per the storyboard's Scenario 4: on hard-reject, surface the specific rule that fired (DEC + schema entry), propose at least one corrective action, wait for the user's authorisation. Do not bypass hard-rejects. Aggregate consecutive failures where possible so the user is not asked one-by-one for related fixes.

## What this sub-procedure does NOT do

- It does not architect *what* to build. Architectural and product decisions go to the user, the `architect` agent, or a human. Batch-planning takes the user's stated outcomes and slices them into tickets; it does not invent the outcomes.
- It does not authorise itself to bypass the membership gate ([project-management:DEC-021-team-membership-gate]) or any hard-reject severity. The user authorises bypassable-with-audit overrides; hard-rejects are never bypassable.
- It does not skip the single approval gate even when "the slicing seems obvious". The gate is the contract; the agent waits.
- It does not file before the cited prerequisites (parent EPIC, dependent decisions). If a slicing depends on an unfiled prerequisite, file the prerequisite first and then file the dependents in the same approval-gated session.
