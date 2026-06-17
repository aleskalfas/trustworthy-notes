# pm create-issue — file a new EPIC, Feature, Umbrella, or Task

Sub-procedure of the pm composite skill (`pm.md` in this folder). Per [project-management:DEC-020-methodology-as-executable-commands], this sub-procedure has thinned to an intent-to-command router: methodology rules live in the schemas + the deterministic `create-issue.py` script; this file maps user intent to a script invocation and surfaces the result.

## When to use this operation

- The user wants to file a new EPIC, Feature, Umbrella, or Task.
- A markdown sub-task in a Task body needs **promotion** to a standalone Task — sub-task promotion is a `create-issue` invocation with the new Task's parent set to the *original Task's parent* (per [project-management:DEC-005-linking-and-containment] and `body-format.yaml`'s `sub_task_promotion` block).

Filing a sub-task (markdown checkbox in a Task body) is *not* this operation — it's an edit to the parent Task's body, validated via [validate-body](validate-body.md).

## What the script enforces

The deterministic enforcement lives in `scripts/create-issue.py`. It reads `issue-types.yaml`, `titles.yaml`, `body-format.yaml`'s template, `classification.yaml`, and the adopter's `project/config.yaml` at every invocation; rule changes propagate automatically without skill edits.

Behaviour summary (the script is the source of truth — read it for the exact contract):

- **Membership gate** (per [project-management:DEC-021-team-membership-gate]) — closed mode refuses non-members with the standard refusal template; the user fixes by getting added via `add-member` before the operation will proceed.
- **Title composition** — prepends the type's `title_prefix` (EPIC for epic, Feature/Umbrella/Task for the others) and validates against `titles.yaml`'s per-type regex before any `gh` call.
- **Body composition** — reads `templates/<Prefix>.md`, strips frontmatter, substitutes the parent-ref line when `--parent` is provided.
- **Classification labels** — applies `type:<kind>` always; in label-fallback mode (no Projects v2 board) also `priority:<P>` and `workstream:<W>`.
- **Mandatory assignment** (per [project-management:DEC-019-mandatory-issue-state]) — defaults the assignee to the resolved invoker identity; `--assignee=<login>` overrides.
- **Auto-add to board** (per DEC-019) — for board-substrate adopters, the new issue is added to the configured Projects v2 board as the final filing step.
- **Validation refusals** — workstream value not in the adopter's declared list, parent type not in the issue type's `parent_issue_types`, title regex mismatch — all surface as structured error messages before `gh` is invoked.

## How to invoke

Dispatch to the script via the kit-level capability-command dispatcher (per [pkit:COR-021]):

```
pkit project-management create-issue \
  --type <epic|feature|umbrella|task> \
  --title "<plain-English sentence (no [Type] prefix)>" \
  [--kind <feature|bug|docs|test|refactor|maintenance>] \
  [--priority <High|Medium|Low>] \
  [--workstream <slug>] \
  [--parent <issue-number>] \
  [--assignee <github-login>] \
  [--milestone <number>] \
  [--board <projects-v2-id>] \
  [--dry-run] [--yes]
```

Direct-path is equivalent for adopters whose kit predates the dispatcher:

```
.pkit/capabilities/project-management/scripts/create-issue.py --type task --title "Install CLI" --parent 42
```

## Handling the script's output

- **Success** — the script prints the new issue URL on the final line. Surface it verbatim to the user.
- **Refusal** — surface the script's stderr message verbatim. The script writes the structured refusal exactly as DEC-021 prescribes; do not paraphrase.
- **`gh` failure** (exit 3) — surface the stderr (auth, network, repo not found). The remediation usually lies outside the methodology (`gh auth refresh`, network connectivity).

## Intent recognition before invocation

Three judgments belong to the LLM before invoking the script — these are interpretation, not deterministic:

1. **Pick the structural type.** Map the user's natural-language intent to one of `epic|feature|umbrella|task`. Default to Task for code-change intents from Implementer-role callers; default to EPIC or Feature for outcome-shaped intents from PM-role callers (per [project-management:DEC-008-pm-and-implementer-roles]). When ambiguous, ask.
2. **Pick the parent.** From recent context, prior conversation, or by asking. If the type requires a parent (`parent_ref_optional: false` in `issue-types.yaml`) and none is supplied, the script refuses — pre-empt the refusal by asking up front.
3. **Pick the workstream and priority defaults.** Infer the workstream from file paths or topic when possible; ask if ambiguous. Priority defaults to `Medium`; only override on explicit user signal.

Everything else is the script's job — pass the inferred arguments through and surface the result.
