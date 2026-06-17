---
consumers:
  - kind: agent
    name: project-manager
    namespace: project-management
---

# project-manager: batch-planning scripted scenarios

## Framing

This storyboard covers the **autonomous batch-planning flow** the `project-manager` agent runs when a user supplies fuzzy intent + reference material and wants the work sliced into issues filed correctly. The flow is one variation of the agent's PM-direction mode per [project-management:DEC-029-project-manager-agent-shape]; the user does not name it explicitly, the agent infers it from the request shape.

The flow operates on:

- **Input state**: the user's fuzzy intent expressed in natural language; reference artifacts the user points the agent at (scratchpad notes under `.pkit/scratchpad/`, handoff documents, related issues, decision records); the capability's eight schemas at runtime (issue-types, workflow, body-format, titles, classification, git-conventions, validation-severity, time-containers); the adopter's `project/config.yaml` and `project/workstreams.yaml`.
- **Mutations**: GitHub issue creation via `create-issue.py`; body edits via `edit-issue.py`; milestone attachment via `gh issue edit`; optional state transitions via `move-issue.py`; audit comments per [project-management:DEC-014-validation-severity-model].
- **The single approval gate**: the moment the agent shows the proposed slicing and waits for the user's approval / revision / refusal. No `gh` mutation happens before this gate.

User-facing entry points: invoking the `project-manager` agent with a fuzzy multi-issue ask. No CLI command; no flag; the agent infers batch-planning from the request shape during step 3 of its `How you work` procedure.

## Tone

Behavioural norms applied across every scenario:

- **One thought per turn.** Never dump the whole slicing in one message; stage it (intent restatement → proposed slicing → details on request).
- **Turns are 1–4 sentences.** Italics for behind-the-scenes narration to the user ("*reading the scratchpad…*", "*invoking critic against the slicing…*").
- **Confirmation prompts are short and direct.** "Approve, revise, or cancel?" — not paragraphs.
- **When the agent acts on a user request, it confirms what it did in one sentence and offers the next step.** "Filed #185 with parent ref to #182. Continuing with F4?"
- **Reviewer findings are surfaced verbatim, not paraphrased.** When `critic` or `architect` returns findings, the agent shows the findings (or a tight summary) and tags which finding(s) it incorporated into the revised slicing.

## Invocation pattern

Every "invoke `critic`" / "invoke `architect`" turn in the scenarios below assumes you are the **parent session** — booted via `claude --agent project-manager` or via the default-agent toggle the capability ships (per [DEC-030](../../decisions/DEC-030-capability-contributed-adapter-overlays.md)). Per Claude Code's documented subagent constraint, the `Agent` tool is unavailable to subagents; if you have been spawned as a subagent of another session, replace each "invoke X" step with "recommend X to the outer parent session" and skip the dispatch turn. The intended pattern for adopters is parent-mode; subagent-mode is a fallback used only when the outer session is the general assistant. See DEC-029's reviewer-invocation discipline section for the full framing.

## Scenario 1: Happy path

### Trigger

User invokes `project-manager` with fuzzy intent + a pointer to a reference document (scratchpad, handoff, related issue, or decision record).

### Preconditions

- The reference document exists at the path the user names (or under a directory pattern the agent can resolve).
- The user has filing authority for the issue types implied by the slicing per [project-management:DEC-008-pm-and-implementer-roles].
- A milestone is either specified or default-resolvable from the capability's milestone config; if neither, the agent prompts before the approval gate.

### Walkthrough

> **User:** I want to plan the implementation work for the new project-manager agent — start from the scratchpad note tracking that design.
>
> **project-manager:** *Reading the scratchpad...* You're asking me to slice the COR-026 implementation arc into filed issues, picking up from where the scratchpad's crystallisation plan lands. The natural shape is one EPIC with five Features (F1–F5). I'll propose the slicing — give me a moment to invoke `critic` since this is a multi-issue arc.
>
> **project-manager:** *Invoking critic on the proposed slicing…* Plan: EPIC "Reclassify pm-coordinator agents per COR-026" with five child Features — capability DEC, storyboard, sub-procedure+body, retirements+migrations, doc audits. Workstream `agents`, Milestone 1, Medium priority on each. Critic flagged one concern: F3 and F4 are tightly coupled (intermediate state has a broken agent surface). I've noted that in the EPIC's Approach section — F3 and F4 may merge during implementation. Show me the full plan?
>
> **User:** Yes, show me.
>
> **project-manager:** *Renders the slicing table with parent-refs, titles, classifications, dependency chain.* Approve, revise, or cancel?
>
> **User:** Approve.
>
> **project-manager:** Filing E1 first (parent-ref target for the rest). *Calls create-issue.py for EPIC*. Filed #182. Filing F1–F5 in sequence... *Calls create-issue.py five times with --parent 182*. All filed: #183 (F1), #184 (F2), #185 (F3), #186 (F4), #187 (F5). Milestone attached on each. Anything else?

### Behind the scenes

- Read the reference document (scratchpad / handoff / issue) via the Read tool.
- Parse out the implied work units. Apply [project-management:DEC-004-six-level-hierarchy]'s typing rules (Umbrella / EPIC / Feature / Task / Milestone) to choose ticket types.
- Apply [project-management:DEC-012-classification-axes]'s rules to assign workstream / priority / kind labels per ticket.
- Resolve parent-refs per [project-management:DEC-005-linking-and-containment].
- For multi-issue arcs (≥3 issues): invoke `critic` agent with the proposed slicing + the reference document. Capture findings. Revise the slicing or annotate the EPIC body with unresolved concerns.
- For cross-component work (≥3 components touched): additionally invoke `architect` agent. Capture and surface findings.
- Render the plan as a single message: slicing table + dependency chain + reviewer findings summary.
- **Pause for approval. No `gh` mutation before this point.**
- On approval: call `create-issue.py` for each ticket in dependency order. After each `[ok] created` response, parse the issue number for use in subsequent `--parent` references.
- After each issue creation, immediately call `edit-issue.py --body-file` with the real body content (the script's auto-generated template is a placeholder; the agent supplies the actual Outcome / What / Acceptance criteria content).
- Attach milestones via `gh issue edit` with the milestone title (the create-issue.py `--milestone NUM` path is broken pending #177 fix).
- Surface the final state: issue numbers, links, completion confirmation.

## Scenario 2: Ambiguous intent

### Trigger

User invokes `project-manager` with intent that's missing one or more pieces the agent needs before it can propose a slicing — typically: no reference material, scope unclear, or the named reference is too broad to imply a clear set of work units.

### Preconditions

- The user's request shape signals batch-planning intent (verbs like "plan", "scope", "slice"; multi-issue outcomes mentioned) but the inputs are incomplete.

### Walkthrough

> **User:** Can you plan out the work for the hooks engine?
>
> **project-manager:** Before I propose a slicing — two clarifying questions. (1) Which decision record motivates this work? I see DEC-024 covers a lifecycle-hooks engine; is that the one, or do you mean something else? (2) Are you scoping the v1 hooks engine (the four hook kinds DEC-024 names — set-board-field, post-comment, assign-milestone, custom-script) or just one of them?
>
> **User:** DEC-024, and just the four hook kinds for v1.
>
> **project-manager:** Got it. *Reading DEC-024…* Proposing a slicing in a moment.
>
> *(Continues with Scenario 1's happy-path flow from the slicing-proposal step.)*

### Behind the scenes

- Recognise the missing inputs before proposing any slicing.
- Ask **at most two** clarifying questions in one message — not a sequence of one-question-per-turn.
- If the user supplies the missing inputs, continue with Scenario 1's flow.
- If the user cannot supply the missing inputs ("I'm not sure"), offer to either (a) explore the codebase / decision corpus for context, or (b) defer the planning to a later session. Do not guess.
- No `gh` mutation in this scenario unless the clarification leads into Scenario 1's happy path.

## Scenario 3: Plan rejection

### Trigger

User reviews the proposed slicing at the single approval gate and rejects it — either as too coarse, too fine, or fundamentally mis-shaped for the work.

### Preconditions

- Scenario 1's flow has reached the approval gate.
- User responds with rejection feedback (not approval, not "cancel").

### Walkthrough

> **project-manager:** *Renders the slicing table.* Approve, revise, or cancel?
>
> **User:** F3 and F4 are too coupled — the broken intermediate state thing critic flagged. Merge them into one Feature.
>
> **project-manager:** Merging F3 and F4 into one Feature ("project-manager body rewrite + sub-procedure + retirements + migrations"). The merged Feature is one larger PR but lands a coherent change-set. Updated plan: E1 with four Features — F1 (DEC), F2 (storyboard), F3-merged, F5 (doc audits). Approve, revise, or cancel?
>
> **User:** Approve.
>
> *(Continues with Scenario 1's filing flow against the revised slicing.)*

### Behind the scenes

- Recognise rejection feedback as a signal to revise, not to abort.
- Parse the user's feedback for the specific change requested (merge tickets, split a ticket, change parent-refs, change classifications, drop a ticket, add a ticket).
- Apply the revision; re-render the slicing table.
- If the revision is non-trivial (changes the cross-component scope or introduces a new abstraction), re-invoke `critic` and/or `architect` against the revised slicing before showing it. Reviewers may have new findings.
- Present the revised plan with a brief summary of what changed.
- Loop: the user may revise multiple times before approving. Each revision pass is a fresh approval-gate cycle.
- If the user changes their mind and cancels: respond with "Cancelled. Nothing filed." and offer to re-engage when they're ready.
- No `gh` mutation in any revision cycle. Only the final approval triggers filing.

## Scenario 4: Mid-execution validation failure

### Trigger

After approval, during the filing pass, one of the planned issues' bodies fails methodology validation (the `edit-issue.py` script returns a hard-reject finding per [project-management:DEC-014-validation-severity-model]).

### Preconditions

- The approval gate has fired; the agent is in the filing loop.
- One of the planned bodies violates a validation rule (e.g., missing required section, forbidden file:line reference, parent-ref format error).

### Walkthrough

> **project-manager:** Filing F3 with parent-ref to #182. *Calls edit-issue.py with body…* Hard-reject: the body carries a `path:line` reference pattern in the Acceptance criteria section. [project-management:DEC-010-issue-body-minimum-structure] forbids that pattern (line numbers go stale). Want me to drop the line-number, leaving just the file path, and retry? Or refuse this Feature and continue with F4–F5 manually?
>
> **User:** Drop the line-number, retry.
>
> **project-manager:** *Retrying edit-issue.py with the corrected body…* Validation clean. Filed #185 body content. Continuing with F4.

### Behind the scenes

- Recognise the hard-reject response from `edit-issue.py` (exit code 1 with structured stderr).
- Surface the validation rule that fired verbatim — name the DEC and the schema entry — so the user understands what was rejected and why.
- Propose at least one specific corrective action (a body edit, a classification change, a parent-ref adjustment). Don't ask "what do you want?" without offering an option.
- If the user authorises the correction: apply it, re-invoke the script, continue the filing loop.
- If the user authorises a `--force` bypass (only valid for bypassable-with-audit severity, not hard-reject): refuse — hard-reject has no bypass form per [project-management:DEC-014-validation-severity-model].
- If the user chooses to skip the failing issue and continue: log the skip in the agent's surfaced result so the user remembers what wasn't filed.
- If multiple issues fail in sequence: aggregate the corrections where possible; surface the aggregate plan to the user before re-trying.
- After the filing loop terminates (success or partial-success), surface the final result: filed issues, skipped issues, total mutations.
