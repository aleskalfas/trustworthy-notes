---
variant: universal
---

# Skills

Installable agent skills — harness-agnostic instructions that the adapter (per COR-005) deploys into the active AI harness. A skill is a Markdown file with frontmatter (name, description, optional metadata) and a procedural body. Atomic skills live as a single file; skills with sibling helpers (templates, references, scripts) live in a per-name folder. The file-layout rule is recorded in COR-015.

Skills are the **conversational, judgement-bearing** half of the methodology's authoring loop (per COR-006's discriminator). For authoring tasks where the methodology also ships a deterministic command (`pkit new decision`, `pkit new bundle`, etc.), the skill is the agent-facing entry point; the script is the substrate underneath. The pairing is recorded in COR-005's "Skill / command pairing" section. Each paired skill declares `wraps_command` in its frontmatter so the pairing is queryable.

## Layout

Per COR-015, a skill takes one of two forms:

```
.pkit/skills/
├── core/                                 # core-shipped skills (propagation; refreshed on sync)
│   ├── <skill-name>.md                   # flat form: atomic skill, no helpers
│   └── <skill-name>/                     # folder form: skill with sibling helpers
│       ├── <skill-name>.md               #   canonical file (name matches the folder)
│       └── (supporting files)            #   templates, scripts, reference fragments
└── project/                              # adopter-authored skills (extension; never touched by sync)
    ├── <skill-name>.md
    └── <skill-name>/
        ├── <skill-name>.md
        └── (supporting files)
```

The flat form is the default for new skills; promote to folder form only when a sibling helper materialises. The legacy `SKILL.md` filename inside folders is dropped (per COR-015) in favour of `<name>.md`, uniform across kinds and across the flat-vs-folder distinction.

The `core/` + `project/` split is the universal area pattern (per COR-003): core-shipped content lives in `core/` and is read-only for adopters; adopter-authored content lives in `project/` and is never overwritten by sync. The no-shared-files invariant rules out collisions — adopters cannot author a skill with a name the methodology ships, since paths can't overlap.

## Today

Core-shipped skills currently in `core/`:

- **`decision-author`** — paired with `pkit new decision`. Walks the author through a new COR or PRJ record: disciplines (axiom / project-neutrality / principles-not-inventory), slug, command invocation for the stub, body drafting, self-checks, commit. See `.pkit/skills/core/decision-author.md`.
- **`bundle-author`** — paired with `pkit new bundle`. Walks the author through adding a new bundle to a bundle-based area: area selection, contract review, scaffold, README + config template + internals drafting, self-checks, commit. See `.pkit/skills/core/bundle-author.md`.
- **`adapter-author`** — paired with `pkit new adapter`. Walks the author through adding a new harness adapter at `.pkit/adapters/<name>/`: contract review, scaffold, README + harness-specific content drafting, self-checks, commit. See `.pkit/skills/core/adapter-author.md`.
- **`migration-author`** — paired with `pkit new migration`. Walks the author through adding a new migration script: tier / scope / version / slug selection, scaffold, idempotent-body drafting, self-checks, commit. See `.pkit/skills/core/migration-author.md`.
- **`area-author`** — paired with `pkit new area`. Walks the author through adding a new top-level area: name + variant selection, scaffold, README drafting per the variant's layout, self-checks, commit. See `.pkit/skills/core/area-author.md`.
- **`scratchpad-author`** — paired with `pkit new scratchpad`. Walks the author through starting an exploratory note: slug, date stamping, framing prompts, retirement guidance. See `.pkit/skills/core/scratchpad-author.md`.

## Frontmatter

Every skill file starts with YAML frontmatter at minimum:

```yaml
---
name: <skill-name>                        # matches the filename / directory name
description: <one-line description>       # surfaces in skill registries / agent harnesses
wraps_command: <pkit subcommand>          # optional — only if the skill pairs with an authoring command
reads:                                    # optional — references consulted at task time (see agents README)
  paths: [...]
  records: [...]
  patterns: [...]
answers:                                  # optional — hook names this skill provides (see agents README)
  - <hook-name>
gates:                                    # optional — record IDs whose `accepted` status is load-bearing
  - COR-NNN
---
```

The frontmatter shape is unified with agents (per COR-013) — see `.pkit/agents/README.md` for full field semantics. `gates` entries automatically count as `reads.records` for the reference-graph check.

The body that follows is a procedural walkthrough — readable by both humans and agents. Keep it operational (numbered steps the author/agent runs) rather than expository (re-stating principles that already live in records).

## Deployment

Skills don't run from `.pkit/skills/` directly. The adapter for the active harness deploys them where the harness expects — for `claude-code`, that's `.claude/skills/<name>/SKILL.md` (a file-symlink into the source, regardless of whether the source is flat or folder) via the deploy primitive `deploy-skills.sh`. The skills themselves are harness-agnostic by design (per COR-006); the `SKILL.md` filename at the harness side is Claude Code's expectation and lives in the adapter, not the source layout.

Symlinks (rather than copies) are used because skill content is unchanged from source to destination — no placeholder substitution step. Editing a skill source updates the harness view immediately, no `deploy-skills.sh` rerun needed during authoring. Agents differ on this point because they carry overlay placeholders; see `.pkit/agents/README.md`'s "Why copies, not symlinks" for the rationale.

Run `pkit status` to see which core-shipped skills are deployed for the project's active harness.

## Authoring a new skill

For now: create `<name>.md` under `core/` (core-shipped — requires landing through a methodology PR) or `project/` (adopter-owned), drop the frontmatter and procedural body, and run `pkit deploy-skills` so the harness picks it up. Promote to folder form (`<name>/<name>.md` + siblings) only when a helper materialises.

A future `pkit new skill` command (with paired `skill-author` skill per the COR-005 pairing convention) will scaffold the file + frontmatter — runtime-blocked per the build roadmap.
