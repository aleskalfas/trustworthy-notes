*Operational rules and tool hygiene shipped by the methodology core. Loaded into the host `CLAUDE.md` via `@.pkit/rules/core.md`; rationale for each rule lives in the cited record or area README. This file is operational, not expository — read the cited records when a rule's "why" is not obvious, do not violate the rule in the meantime. The file has no top-level heading by design (rule 13 below). Project-specific operational rules — those failing universal applicability per COR-014 — live in `.pkit/rules/project.md`.*

## Hard rules

Violating any of these breaks the methodology's invariants. Treat them as gates, not guidelines.

1. **The no-shared-files invariant.** Every file has exactly one owner — the methodology core or the project. Never edit core-owned files; edits are silently overwritten by `pkit sync`. To extend content, add sibling files in the matching `project/` directory (or in the file the adapter merges into). See `.pkit/decisions/README.md`.

2. **The acceptance gate.** Only act on `accepted` decisions. Proposed records are draft hypotheses. Do not author dependent code, docs, or downstream decisions citing a proposed record — accept it first (one-line status flip + commit) or pause. See `.pkit/decisions/README.md`.

3. **For authoring core-shipped artifacts (decisions, adapters, migrations, areas, scratchpad notes, agents, capabilities), invoke the paired skill or call the underlying `pkit new <kind>` command directly — never hand-stamp the file.** The script enforces correct numbering, frontmatter, and layout deterministically; the skill enforces the disciplines. See COR-005 ("Skill / command pairing") and `.pkit/cli/README.md`'s "Authoring commands" section for the current set of paired skills.

4. **PRJ records live in `.pkit/decisions/project/`; never edit `.pkit/decisions/core/`.** Core records are managed by the methodology source and refreshed on every sync. Numbering is independent across the two namespaces. See `.pkit/decisions/README.md`.

5. **Migrations are idempotent.** If you author a migration script, it must be safe to re-run on already-migrated state — detect already-applied state and exit cleanly. See COR-010 and `.pkit/lifecycle/README.md`'s "Migration framework → Script contract".

6. **Settings-file changes go through the merge primitive.** Do not edit fixed-path config files (`.claude/settings.json`, `.gitignore`, etc.) directly to add core-shipped content; the adapter merges baseline + project additions. Edit only the project-additions side. See COR-002.

7. **Surface changes ship a migration in the same change-set.** A change that alters an installed adopter's state observably and breaks against it — file or directory renames / removals in kit-owned trees, schema_version bumps in YAML schemas, breaking CLI signature changes, capability subtree restructures — must include a migration script at the affected tier (backbone / adapter / capability) in the same commit or PR. The migration is idempotent (per rule 5 above). Pure additions, documentation refinements, behaviour-preserving fixes don't trigger. Before committing, check the diff for triggers; `pkit migrations check-diff` (when available) verifies coverage; CI gates the merge. See COR-010 ("Migrations are mandatory on adopter-breaking surface changes").

## Tool hygiene

Operational practices that keep work consistent and recoverable.

8. **Pause and confirm before destructive operations.** `git reset --hard`, `git push --force`, deleting files outside `project/`, dropping database tables, killing processes, `rm -rf` — all warrant explicit confirmation from the user, even when the task seemed to authorize them generally. Authorization for one destructive op is not authorization for the next.

9. **Use conventional commits and keep one logical unit per commit.** The branch-naming convention (`<type>/<issue-number>-<slug>`) and any work-tracker-specific requirements for branches (issue-linking, label conventions, etc.) live in the installed work-tracking capability's documentation. See COR-008's "Operational reference" section for the recommended type list and branch-naming examples.

10. **Surface changes bump the version of the affected component.** A change that an adopter could observe, depend on, or break against is a *surface change*; documentation refinements and internal refactors are not. The exact bump policy is per-project (each project records its policy as a PRJ record); each component adopts analogous rules.

11. **Validate before assuming state.** Use `pkit status` to see how the methodology is wired in this project (paths, adapter, deployed skills, capabilities, decision counts). Don't infer state from prior sessions; the file system is the source of truth.

12. **Skills and agents are deployed by the adapter, not hand-symlinked.** The adapter's deploy primitive (e.g. `deploy-skills.sh` for Claude Code, plus future `deploy-agents.sh` per COR-013) symlinks canonical content from `.pkit/skills/` and `.pkit/agents/` into the harness's expected location. Editing the deployed symlinks instead of the canonical core-side file violates the no-shared-files invariant.

13. **Files intended for `@<path>` include omit the H1 and start with prose or H2 sections** *(applies when using the Claude Code harness; other harnesses have different include mechanisms documented in their adapter README)*. The host file owns the H1; the included content nests under it. Place the `@<path>` line after the host's intro paragraph, not at line 1, so the included sections become natural sub-sections of the host. This file is the canonical example: no H1, opens with an italic preface, sections start at H2; CLAUDE.md includes it after its own intro.

14. **Don't escalate past the permission model for commands it already permits.** When a project runs a permission model and a confinement sandbox, both are configured so that allowlisted domain commands — version control, the issue tracker, the kit CLI — run with the network egress and scratch-file access they need *inside* the sandbox, auto-approved with no prompt. Reaching for a sandbox-escape or permission-escalating flag on such a command forces a manual operator confirmation *by design* and overrides that auto-approval — so doing it reflexively on routine work buries the operator in avoidable confirmations (a single session has produced dozens). Run the command as-is and let the model approve it; reserve any escape/escalation flag for the rare command that genuinely cannot run within the model. *(The escape mechanism is harness-specific — e.g. the Claude Code harness's sandbox-disable flag; other harnesses differ. What the sandbox permits is documented by the permission capability.)* The model's rationale lives in the permission capability's decisions (COR-028 and its ADRs).

15. **Work with the permission layer, not around it.** Issue the narrowest action that layer can vet and auto-approve: a single, simple command rather than a compound that bundles several operations into one opaque step the layer must approve whole. Prefer the harness's dedicated read / search / write tools over ad-hoc shell for inspection. When a diagnostic recurs or is non-trivial, extract it into committed project tooling — a named command the project owns — rather than re-deriving a throwaway script each time; that is COR-007's pattern-extraction applied to debugging, turning disposable complexity into one clean, reusable, reviewable invocation. And never compose a command to *evade* the intent layer's gated mutations: slipping a denied operation past the check by wrapping it defeats the control, and the validated path exists precisely so the mutation is checked. *(What counts as a single auto-approvable action, and any script-composition mechanic, is harness-specific — documented in the harness's adapter; the Claude Code adapter is the worked example.)* Same confirmation-fatigue-and-lost-work rationale as the rule above.

## Communicating with the user

How an agent talks with the user, independent of any project's tooling.

16. **Discuss one decision at a time.** When a choice needs the user's input, surface a single decision per turn — don't stack several open questions or unknowns into one message. A wall of simultaneous decisions forces the user to parse and re-litigate everything at once; a stepped conversation is faster and clearer. This applies to discussion and decision-making, not to summaries of work already done.

17. **Reference by meaning, then identifier.** When pointing at a rule, record, or section, state what it actually says in plain language first, then put the identifier in brackets after — "a Task must have a parent (DEC-005 P2.1)". A precise sub-locator is welcome; just write it without cryptic glyphs (no §), and never reference by bare code alone. The reader should learn the substance from the sentence, not have to chase the reference.

## Where rationale lives

Each rule cites the record or doc that owns its "why". The umbrella references:

- `.pkit/decisions/README.md` — the schema, statuses, the no-shared-files invariant, the acceptance gate.
- `.pkit/decisions/core/COR-NNN-*.md` — accepted core records; each captures a principle with rationale.
- `.pkit/lifecycle/README.md` — the manifest schema, upgrade procedure, migration framework.
- `.pkit/cli/README.md` — the CLI surface and per-command behaviour.
- `.pkit/adapters/README.md` and per-adapter READMEs — harness translations.

## Where this file came from

The split between this file and `.pkit/rules/project.md` is governed by COR-014's universal-applicability principle: rules that apply to any adopting project ship here; rules tied to a specific project's tooling live in the project namespace. Capability-specific operational rules (e.g. work-tracker conventions) live in the capability's own documentation.
