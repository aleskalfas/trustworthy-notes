# pm transition-state — move an issue through the lifecycle state machine

Sub-procedure of the pm composite skill (`pm.md` in this folder). Per [project-management:DEC-020-methodology-as-executable-commands], this sub-procedure is a thin intent-to-command router: the state-machine rules + cascade live in `workflow.yaml` + the deterministic `scripts/move-issue.py` / `close-issue.py` / `reopen-issue.py` scripts; this file maps user intent to a script invocation and surfaces the result.

## When to use this operation

- The user wants to **move** an issue forward through the lifecycle (Todo → Backlog → In Progress → Review).
- The user wants to **close** an issue (PR-merge-driven closure or explicit won't-do gesture per [project-management:DEC-006-state-machine-and-cascade]).
- The user wants to **reopen** a closed issue (e.g., it regressed).
- The agent is running a cascade pass after a child's state changed (the scripts handle the cascade internally; this sub-procedure is the entry point).

This operation **does mutate** issue state. Every mutation is gated by the membership predicate (per [project-management:DEC-021-team-membership-gate]) + the schema's authorisation field + the checkbox close-gate (on closure paths) per [project-management:DEC-007-checkbox-validation].

## What the scripts enforce

The deterministic enforcement lives in the three verb-subject scripts. Each reads `workflow.yaml` + `issue-types.yaml` + the adopter's config at every invocation; rule changes propagate automatically without skill edits.

Behaviour summary (the scripts are the source of truth — read them for the exact contract):

- **Membership gate** (DEC-021) — closed mode refuses non-members with the standard refusal template.
- **Transition lookup** — `move-issue.py` looks up the requested transition in `workflow.yaml`'s `transitions:` list and refuses any move not in the schema, with a diagnostic listing the legal targets.
- **Authorisation gate** — user-authorised transitions (Todo → Backlog; Review → Done; Backlog/Todo → Done; In-progress → Done parent close) require `--yes` from the caller as the explicit authorisation signal; bypassable-with-audit transitions accept `--bypass --bypass-reason "..."` to record an audit comment.
- **Forward cascade** (DEC-006) — `move-issue.py` walks the parent chain via the body's parent-ref line and bumps any parent that's behind. Skip with `--no-cascade`.
- **Closure cascade** (DEC-006) — `close-issue.py` surfaces parent-eligibility findings after the close, never auto-closes parents.
- **Checkbox close-gate** (DEC-007) — `close-issue.py --mode=wont-do` refuses if any `- [ ]` box remains unticked in the body. Override with `--skip-checkbox-gate` (discouraged).

## How to invoke

Dispatch to the script via the kit-level capability-command dispatcher (per [pkit:COR-021]):

**Move forward:**
```
pkit project-management move-issue <N> --to <todo|backlog|in-progress|review|done> \
  [--bypass --bypass-reason "<text>"] [--no-cascade] [--dry-run] [--yes]
```

**Close (won't-do):**
```
pkit project-management close-issue <N> --mode wont-do --reason "<text>" \
  [--skip-checkbox-gate] [--no-cascade] [--dry-run] [--yes]
```

**Close (PR-merge cascade hook):**
```
pkit project-management close-issue <N> --mode pr-merge [--no-cascade]
```

**Reopen:**
```
pkit project-management reopen-issue <N> [--reason "<text>"] [--dry-run] [--yes]
```

Direct-path is equivalent for adopters whose kit predates the dispatcher:
```
.pkit/capabilities/project-management/scripts/move-issue.py 42 --to in-progress
```

## Handling the script's output

- **Success** — the script prints `[ok] transitioned #N: <old> → <new>` (or the equivalent for close/reopen) on the final line. Surface verbatim.
- **Refusal** — surface the script's stderr message verbatim. Refusals carry structured remediation; do not paraphrase.
- **`gh` failure** (exit 3) — surface the stderr; remediation usually lies outside the methodology.

## Intent recognition before invocation

Three judgments belong to the LLM before invoking the script — these are interpretation, not deterministic:

1. **Pick the operation.** Map the user's natural-language intent to `move`, `close`, or `reopen`. "Start work on #42" → move-issue --to in-progress; "won't fix this" → close-issue --mode wont-do; "this regressed" → reopen-issue.
2. **Pick the target state for `move`.** Default to the next-forward state from the issue's current state unless the user names a specific target.
3. **Resolve authorisation prompts.** When the script returns a refusal mentioning `--yes` or `--bypass`, surface the prompt to the user; re-invoke once the user has authorised.

Everything else is the scripts' job — pass the inferred arguments through and surface the result.
