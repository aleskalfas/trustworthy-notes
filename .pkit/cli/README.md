---
variant: specialized
---

# Command-line interface

project-kit ships a CLI that adopting projects use to install the methodology, pull updates, manage capabilities, and check state. The binary's name is **`pkit`** (per PRJ-001). The CLI is the surface through which project-kit's mechanisms (propagation, extension, suspension) and delivery operations (seed, merge) are exercised against your project — see `.pkit/decisions/README.md` and the COR records in `.pkit/decisions/core/` for the underlying contracts.

The design rules governing the CLI's shape — why these commands exist and not others, why some verbs stay separate — are recorded in `.pkit/decisions/core/COR-004-cli-surface.md`. This document is the spec: what each command does, which flags it accepts, what guarantees it provides.

## Implementation status

The CLI is implemented in Python (per PRJ-003), with `.pkit/cli/pkit` as a thin proxy that exec's the Python runtime via `uv` and bypasses to the adapter's shell scripts for `deploy-skills` / `merge-settings` (which are shell to the bone — primitives the adapter ships, not surface commands).

The full COR-004 surface is implemented: `init`, `sync`, `merge`, `upgrade`, `capabilities install / uninstall / upgrade / list` (per COR-017), `status`, `validate`, `version`, `version bump`, `new decision`, the authoring commands (`area`, `adapter`, `capability`, `agent`, `storyboard`, `schema`, `migration`), and the scratchpad commands (`new scratchpad`, `scratchpad done`, `scratchpad drop`) per COR-012. Each authoring command ships paired with its skill under `.pkit/skills/core/<name>-author/` per COR-005's "Skill / command pairing". (The `bundle` command family was retired in COR-027 — capabilities subsumed the bundle role.)

## Installing pkit on PATH

**Recommended (per PRJ-004):** install pkit globally via `uv tool install`:

```
uv tool install git+ssh://git@github.com/aleskalfas/project-kit.git
```

After this, `pkit` is on PATH; the binary works against any project-kit-adopting project — the runtime resolves the current project's root from CWD at invocation time (via `git rev-parse --show-toplevel`, with a CWD-walk fallback). Re-installing the kit into more adopter projects does **not** require additional installs of pkit.

Pin to a specific kit version:

```
uv tool install git+ssh://git@github.com/aleskalfas/project-kit.git@v0.10.0
```

**Alternative (project-kit contributor convenience):** symlink the source-tree dispatcher onto PATH so changes you make to the kit's source are picked up without re-installing:

```
ln -s /path/to/project-kit/.pkit/cli/pkit ~/.local/bin/pkit
```

This is useful while developing the kit itself. The symlink target is the thin proxy; it routes to Python via `uv run --project /path/to/project-kit` so the source tree's `pyproject.toml` resolves the package version.

**Requirements either way:** Python 3.11+ and `uv` (per PRJ-003). Install `uv`:

```
curl -LsSf https://astral.sh/uv/install.sh | sh   # or: brew install uv
```

## Surface

| Command | Operation | Mutates? | Idempotent? |
|---|---|---|---|
| `init` | first install (propagation + seed + merge) | yes | no — refuses re-run |
| `sync` | re-run propagation | yes | yes |
| `merge [<target>...]` | re-run merge for one or all targets | yes | yes |
| `upgrade` | version-aware migrations + sync | yes | yes |
| `visibility` | control pkit's git footprint (per ADR-009). No subcommand = status | no | yes (read-only) |
| `visibility shared` / `visibility private` | `private` hides the whole footprint via the per-clone `.git/info/exclude` (no committed `.gitignore` is ever written) + a confirm-gated untrack; `shared` (default) keeps pkit committed. `--dry-run` previews | yes | yes — idempotent |
| `visibility untrack [--dry-run]` | remove already-tracked pkit footprint files from the git index (`git rm --cached`, working copies preserved). Footprint-only, confirm-gated; refuses mid-merge/rebase or on staged footprint changes. Its own subcommand so the git-index-mutating gesture stays explicit (per ADR-009) | yes | yes — no-op when nothing tracked |
| `capabilities install <name>` | install a capability (per COR-017) | yes | already-installed reports, no re-run |
| `capabilities uninstall <name>` | remove an installed capability | yes | yes |
| `new area <name>` | scaffold a new area (per COR-011) | yes | no — refuses if area already exists |
| `new adapter <name>` | scaffold a new adapter (per COR-005) | yes | no — refuses if adapter already exists |
| `new capability <name>` | scaffold a new capability (per COR-017) | yes | no — refuses if capability already exists |
| `new migration [...]` | scaffold a migration script in the right `<major>.<minor>.0/` directory | yes | no — emits a fresh, numbered file each call |
| `new decision <namespace> <slug>` | scaffold a new decision record stub (frontmatter + four sections + next number in namespace) | yes | no — refuses if a record with that slug already exists |
| `new scratchpad <slug>` | stamp a new active-state scratchpad note (per COR-012) | yes | no — refuses if the slug is already in use across any state |
| `scratchpad done <slug> [--produced <ref>...]` | move a note from `active/` to `done/`, append `retired`/`produced` to frontmatter | yes | no — refuses if no active note matches |
| `scratchpad drop <slug>` | move a note from `active/` to `dropped/`, append `retired` to frontmatter | yes | no — refuses if no active note matches |
| `status` | show how project-kit is wired in this project (paths, installed backbone version vs source, adapter, deployed skills, capabilities, decision counts) | no | yes (read-only) |
| `validate` | check project state against invariants | no | yes (read-only) |
| `schemas validate [<path>]` | validate capability schema YAMLs against their JSON Schema companions + cross-file refs | no | yes (read-only) |
| `data validate <path>` | validate adopter data files against their bound capability schemas (per COR-023); resolves binding field-first via `pkit_schema:`, then via per-schema `binds_to:` fallback | no | yes (read-only) |
| `agents` | report which kit-shipped agents will deploy vs. be skipped — and why (an overlay category the agent references but `.pkit/agents/project/overlay.yaml` doesn't define), per COR-013. Deployment itself happens in `sync`; this is the diagnostic | no | yes (read-only) |
| `agents reconcile [--write]` | surface referenced-but-undefined overlay categories into `overlay.yaml` as commented stubs (explicit; `sync` never mutates the seeded overlay). Dry-run by default | yes (with `--write`) | yes — idempotent (skips already-present categories) |
| `permissions explain [<agent>]` | render the per-agent permission mental model — grants, scopes, effects (per COR-028) | no | yes (read-only) |
| `permissions diff [<agent>]` | reconcile the model against live `.claude/settings.json`: flag live rules no granted privilege justifies + dimensions the harness can't natively enforce | no | yes (read-only) |
| `permissions catalog` | list the privilege catalog (baseline + extensions) | no | yes (read-only) |
| `permissions overview` | role-grouped catalog view — guardrails vs enablers, provenance, granted-to, live-enforcement status | no | yes (read-only) |
| `permissions grant <subject> <privilege> [--scope <glob>...] [--deny]` | add/update a grant in the project model, validated against the catalog | yes | no — idempotent (updates a matching grant) |
| `permissions revoke <subject> <privilege>` | remove a grant from the project model | yes | no — no-ops when absent |
| `permissions mode [additive\|managed]` | show (no arg) or set the ownership mode | yes (on set) | no |
| `permissions enable` | turn on live enforcement: register the PreToolUse hook (opt-in) + ensure native guardrail denies (the double-lock) | yes | no — idempotent |
| `permissions disable` | turn off live enforcement: strip the PreToolUse hook registration (guardrail denies stay) | yes | no — idempotent |
| `permissions apply` | additively realize the model into `.claude/settings.json` — union the projected session-wide allow rules + ensure guardrail denies — and print the out-of-harness gap report. Additive only (managed-mode wholesale regeneration is separate) | yes | no — additive, idempotent (set-union) |
| `permissions setup` | list the permissions domain's setup goals (per ADR-007) | no | yes (read-only) |
| `permissions setup autonomy [--profile <name>]` | goal-oriented setup (first ADR-007 instance): stand up autonomous agents by composing `profile activate` + `enable` + `sandbox enable`, auto-resolving the SSH-agent socket (`$SSH_AUTH_SOCK`, per ADR-010), stop honestly at the session-restart boundary, and on re-run verify via the probe suite — the goal is declared reached only when the proof passes (decision layer + credential floor). Surfaces a **NEXT** block of explicit gestures it detects but won't run for you — `gh` exclusion (widening) and commit-signing socket (`accommodate --socket`). Stepwise, resumable; no dangerous-flag pass-through | yes | no — resumable + idempotent (live system is the checkpoint) |
| `permissions setup autonomy down` | tear the goal's live switches down (hook + sandbox) and loudly report residual state (profile still active in the model, unenforced; operator sandbox keys left) | yes | no — idempotent |
| `permissions probe [--subject <s>] [--live]` | probe-by-probe proof that the current model rejects/allows what it declares: drives the live hook's entry point (`hook_decide`) over curated concrete requests and checks each verdict against the declared contract (REJECTED / ALLOWED / NOT COVERED → ✓ works / ✗ BROKEN); checks the native double-lock denies; `--live` adds honest reachability probes of the sandbox credential denyRead floor (never certifies a pass it can't prove). Non-zero exit on any broken probe (CI-able) | no | yes (read-only; `--live` performs open-attempts, reads no content) |
| `permissions sandbox` | status of the OS-sandbox confinement (per ADR-004): enabled, auto-allow, fail mode, fail-over, credential denyRead floor | no | yes (read-only) |
| `permissions sandbox enable [--strict] [--dangerously-allow-unconfined]` | turn on the OS sandbox (Seatbelt / bubblewrap) with prompt-free sandboxed Bash, always fail-closed (`failIfUnavailable: true`) + a credential `denyRead` floor; additive over operator sandbox keys. Also auto-applies the **narrowing** allowance of any detected toolkit whose allowances are ALL narrowing — specifically the `uv` toolkit's `~/.cache/uv` write allowance when `uv.lock` or `pyproject.toml` is present, so the confined `pkit`/`uv` CLI can reach its package cache on Linux/bubblewrap without a manual `sandbox accommodate uv` step; inert on macOS where the uv CLI is excluded from the box (ADR-014). Written via the single provenance writer (ADR-008 rule 2); idempotent. `--strict` also locks the unsandboxed fail-over escape hatch; the dangerous flag (operator-only, per-invocation, never a committable default) is the sole way to write fail-open | yes | no — additive, idempotent |
| `permissions sandbox disable` | turn the OS sandbox off (`enabled: false`); operator sandbox keys (excludedCommands, denyRead, …) survive | yes | no — idempotent |
| `permissions sandbox toolkit list` | list confinement toolkits (per ADR-008) — per-tool sandbox allowances, each marked **narrowing** (makes the box usable) or **widening** (carves a tool out of the box) + which are accommodated | no | yes (read-only) |
| `permissions sandbox toolkit show <name>` | show a toolkit's exact allowances, each classified by boundary effect, with honesty glosses on widening entries | no | yes (read-only) |
| `permissions sandbox accommodate <tool>… [--detect] [--remove]` | apply a toolkit's **narrowing** allowances (build caches, sockets) so legit tooling works inside the box; records the choice in `permission-config` (committable, narrowing-only); `--detect` scans lockfiles/manifests; `--remove` drops only pkit-authored entries (operator entries untouched, via provenance). Never applies widening | yes | no — additive, idempotent |
| `permissions sandbox accommodate --socket <path> [--name <id>] [--remove]` | a one-off **narrowing** unix-socket allowance (e.g. `--socket "$SSH_AUTH_SOCK"` for the SSH agent / signing socket) — per-machine, `_manual`-provenance, **never committed** (per ADR-010); `--name` keys it for recompute-replace. `setup autonomy` reuses this writer to auto-resolve `$SSH_AUTH_SOCK` | yes | no — recompute-replace, idempotent |
| `permissions sandbox exclude <cmd> [--weaker-tls] [--remove]` | the **widening** gesture: carve a command out of the box so it runs UNCONFINED. Loud, per-invocation, **never** written to committed config, never proposed by detect, never applied by setup; reported by `sandbox status` + `probe` | yes | no — additive, idempotent |
| `permissions profile list` | list available autonomy profiles (shipped + project), marking the active one (per ADR-005) | no | yes (read-only) |
| `permissions profile show <name>` | show a profile's posture + layered grants | no | yes (read-only) |
| `permissions profile activate <name> [--no-apply]` | activate a profile: set posture + layer its grants under your own (never overwriting manual grants), then `apply` unless `--no-apply`. Does not enable the hook | yes | no — idempotent (overwrite + swap) |
| `version` | show CLI version + project's recorded core-layer version | no | yes (read-only) |
| `version bump <segment>` | bump `.pkit/VERSION` (`segment` = `patch` / `minor` / `major`); see PRJ-002 | yes | no — each call increments |

## Lifecycle commands

### `init`

Runs first install in this order:

1. **Propagation** — every path in the synced manifest is written into the project's `.pkit/` tree.
2. **Seed** — every path in the seed manifest is written once with its template content.
3. **Merge** — every declared merge target is merged with its core baseline (per COR-002's two-tier contract).

`init` refuses to run if the project is already initialised. If you arrive at a partial or broken state, run `validate` to see what is and isn't consistent, then use targeted `sync` / `merge` to recover.

### `sync`

Re-runs propagation only. Pulls current canonical core content into your project's `.pkit/` tree. Does **not** invoke seed (one-shot only — see COR-001) or merge (separate consent profile — see COR-002 and COR-004). Idempotent: re-running with no changes pending reports "current" and exits cleanly.

### `merge [<target>...]`

Re-runs merge against one or more declared merge targets, or against all targets if no argument is given. Honours the two-tier (auto-add / prompt-once) contract from COR-002. Idempotent.

Use this when you want to pull baseline updates for a single fixed-path config file (e.g., `.claude/settings.json`, `.gitignore`) without invoking other operations.

### `upgrade`

Compares the version of the core layer recorded in your project against the version this CLI was built from. Runs any pending migrations in order, then runs `sync`. Refuses to proceed if your project's recorded version is ahead of the CLI's (and tells you so).

## Authoring commands

The `new` family scaffolds first-class methodology elements — areas, adapters, capabilities, migrations — by stamping the contract their owning record fixes (COR-005 for adapters, COR-010 for the manifest layer and migrations, COR-011 for areas, COR-017 for capabilities). Every `new` command is a one-shot generator: it refuses to overwrite existing targets, and the output is a directory or file the rest of the CLI surface (`status`, `sync`, `upgrade`, etc.) recognises immediately. No manual manifest edits are needed after a scaffold call.

Templates live where the contract they instantiate lives — `.pkit/lifecycle/templates/` for migration scripts and per-component manifest skeletons; `.pkit/cli/scaffolds/` for area, adapter, and capability directory shapes — so a kit upgrade that changes a contract also updates what gets stamped.

### `new area <name> [--variant <variant>]`

Scaffolds an adopter-owned area at `.pkit/<name>/` with the README skeleton appropriate to the chosen variant (per COR-011). The variant is one of:

- **`universal`** — gives the area the `core/` + `project/` layout (per COR-003).
- **`adapter-umbrella`** — top-level harness translations, like `.pkit/adapters/` itself.
- **`specialized`** — minimal layout (just a README); the area's content shape is documented in the README directly.

Default variant is `specialized` if `--variant` is omitted. Refuses if `<name>` is a kit-shipped area name (no-shared-files invariant) or if `.pkit/<name>/` already exists. (The `bundle-based` variant was retired in COR-027 — alternative implementations live as capability-internal data per COR-018, not as filesystem-level bundles.)

### `new adapter <name>`

Scaffolds a top-level adapter at `.pkit/adapters/<name>/` (per COR-005). Stamps:

- `package.yaml` — versioned `0.1.0`, `requires_backbone` pinned to a range matching the project's current backbone (per COR-010's compatibility model).
- `README.md` — skeleton.
- `settings/core/settings.json` — empty baseline.
- `deploy-skills.sh`, `merge-settings.sh` — primitive stubs.
- `migrations/` — empty directory.

### `new migration --tier <tier> [--component <name>] --version <X.Y.0> [--scope <scope>] --slug <kebab>`

Drops a numbered, executable script into the right `<major>.<minor>.0/` directory under the relevant tier's migrations tree (per COR-010 and `.pkit/lifecycle/README.md`).

- **`--tier`** is one of `backbone`, `adapter`, `capability`. Determines the tree the migration lands in.
- **`--component <name>`** is required when `--tier` is `adapter` or `capability`; identifies the component the migration belongs to.
- **`--version <X.Y.0>`** is the target minor version. The patch segment is always `.0` (per the lifecycle spec — patches have no migrations).
- **`--scope <scope>`** is one of `manifest-schema`, `structural`, `resource` (default). Scope determines the script's boilerplate header and the ordering convention within its directory.
- **`--slug <kebab>`** is a kebab-case description used for the file name.

The output filename is `<NNN>-<slug>.sh`, where `NNN` is the next zero-padded index in the directory. The stamped script includes the contract boilerplate from `.pkit/lifecycle/README.md` ("Migration framework" → "Script contract"): `set -euo pipefail`, `ROOT` env consumption, and an idempotence-pattern comment.

### `new decision <namespace> <slug>`

Scaffolds a new decision-record stub per the schema in `.pkit/decisions/README.md`. The command is the deterministic part of authoring a record: pick the next number in the namespace, stamp the frontmatter and the four required section headers, leave the body empty for the author to fill.

- **`<namespace>`** is one of:

  | Namespace | Prefix | Location | Per COR |
  |---|---|---|---|
  | `core` | `COR-NNN` | `.pkit/decisions/core/` | (the methodology) |
  | `project` | `PRJ-NNN` | `.pkit/decisions/project/` | (the methodology) |
  | `adr` | `ADR-NNN` | overlay-resolved (see below) | COR-025 |

  Numbering is independent per prefix.

- **`<slug>`** is a kebab-case shorthand of the decision's title — short enough to keep listings self-documenting (e.g., `merge-delivery`, `pattern-extraction`).

For `core` and `project` namespaces, the target directory is fixed at `.pkit/decisions/<namespace>/`. For the `adr` namespace, the target directory is read from the agents overlay at `.pkit/agents/project/overlay.yaml` — specifically the first entry of the top-level `adr-records:` list (per COR-024's `<adr-records>` placeholder + COR-025's ADR decision space). The command refuses with a helpful message if:

- the overlay file is missing,
- the `adr-records:` key is missing or empty,
- the resolved path is inside `.pkit/` (ADRs describe the adopter's project, not the methodology installed in it — per COR-025),
- the resolved directory doesn't exist on disk (suggests `mkdir -p <path>` first, so typos don't silently become directories).

Per-agent overrides of `adr-records` (under `overrides.<agent>:`) are *not* consulted by the stamping command — the top-level key is the canonical write target. If an adopter sets a per-agent override that diverges, that's a configuration error to reconcile by hand.

The stamped file includes:

- Frontmatter — `id` (auto-numbered), `title` (placeholder), `status: proposed`, `date` (today's date), `author` (read from `git config user.name` and `git config user.email`).
- The four required section headers — `## Context`, `## Decision`, `## Rationale`, `## Implications` — empty.

Refuses if a record with the same slug already exists in the namespace, or if the namespace is invalid.

**Coordination with the `decision-author` skill.** Per COR-006's discriminator: a command stamps deterministically, a skill drafts content conversationally. The `decision-author` skill (`.pkit/skills/core/decision-author/`) calls `pkit new decision <namespace> <slug>` for the stub, then walks the author through filling the body — content drafting, discipline self-checks, and approval. Authors who don't need the conversational help can call the command directly.

### `new scratchpad <slug>`

Stamps a new active-state scratchpad note at `.pkit/scratchpad/active/<YYYY-MM-DD>-<slug>.md` per the convention in COR-012 and the spec in `.pkit/scratchpad/README.md`. The command is the deterministic part of starting a note: pick today's date, validate the slug, seed the frontmatter, write an H1 derived from the slug.

- **`<slug>`** is a kebab-case shorthand of the question the note explores (e.g. `agent-architecture`, `versioning-policy`). Slugs are unique across the entire scratchpad area — the command refuses if any state folder already contains a note with this slug.

The stamped file includes:

- Frontmatter — `authors` (a list seeded from `git config user.name` / `user.email`) and `started` (today's date).
- A level-1 heading derived from the slug as a starting title (the author edits it on first pass).

Supports `--dry-run`.

**Coordination with the `scratchpad-author` skill.** The paired skill (`.pkit/skills/core/scratchpad-author/`) carries the slug-choice judgement, the topic-boundary discipline, and the body-drafting opening prompt. Authors who don't need the conversational help can call the command directly.

## Scratchpad commands

Scratchpad notes (per COR-012) move between three state folders — `active/`, `done/`, `dropped/`. Two retire-direction commands wrap the `git mv` + frontmatter update; the convention's full spec lives in `.pkit/scratchpad/README.md`.

### `scratchpad done <slug> [--produced <ref>...]`

Moves a note from `active/` to `done/` and appends `retired` (today) and `produced` (the list of `--produced` refs) to its frontmatter. Use when the note's content has been incorporated into other artifacts (records, docs, skills, agents).

- **`<slug>`** matches either the slug portion of the filename or the full filename. Use the full filename to disambiguate when multiple notes share a slug (rare; the `new scratchpad` command refuses duplicates within the area).
- **`--produced <ref>`** is repeatable. Each value is a record ID (`COR-013`), file path (`.pkit/agents/README.md`), or URL. May be omitted; the `produced:` field is then not added (the author can edit it later by hand).

Supports `--dry-run`. Refuses if no active note matches the slug, or if the destination filename already exists in `done/`.

### `scratchpad drop <slug>`

Moves a note from `active/` to `dropped/` and appends `retired` (today) to its frontmatter. Use when the line of thought did not pan out.

Before dropping, the convention asks the author to append a closing paragraph to the body explaining *why* the line was abandoned, so future readers do not re-tread the path silently.

Supports `--dry-run`. Refuses if no active note matches the slug, or if the destination filename already exists in `dropped/`.

## Diagnostic commands

### `status`

Read-only inventory of how project-kit is wired in this project — useful as a one-shot answer to "is this set up correctly?" Reports:

- **Project root** and the resolved **source pkit binary** (the `pkit` you ran from).
- **Whether `.pkit/` is installed** at the project root (and a hint to run `pkit init` if not).
- **Adapter status** (Claude Code today): whether `.claude/settings.json` is merged, whether a `.pre-pkit` backup exists, and a list of deployed skills split into kit-managed (symlinks into `.pkit/skills/`) vs user-managed (anything else under `.claude/skills/`).
- **Capabilities** — which are available in `.pkit/capabilities/` and which are installed (per COR-017).
- **Counts** for decisions (COR / PRJ records) and skills (core / project).

Output is human-readable with tagged status lines. Makes no changes.

### `validate`

Read-only state check. Verifies:

- The no-shared-files invariant — no project edits to core-owned paths.
- The manifest — every declared path is present and well-formed.
- Per-area schema rules — decision-record schema, link validity, naming conventions, and any rules each area documents in its own README.

Reports issues with their locations and a brief diagnosis. Makes no changes.

`status` answers "what's installed?"; `validate` answers "is it consistent?". Different questions, different commands.

### `schemas validate [<path>]`

Read-only check on the **capability-side schemas mechanism**: every YAML schema under `.pkit/capabilities/<cap>/schemas/` is validated against its JSON Schema companion (shape pass) and every typed-token cross-schema reference is resolved against the target namespace's id collection (resolver pass).

With `<path>`, runs the same passes scoped to the given file or directory — useful for adopters whose data follows the same conventions outside the capabilities tree.

`--shape-only` skips the resolver pass (useful mid-refactor when a referenced target schema doesn't exist yet).

### `data validate <path>`

Read-only check on **adopter-side data files** against capability schemas (per COR-023, superseding COR-022). Resolves each file's binding in two steps:

1. **Field-first.** A top-level `pkit_schema: <capability>:<schema>` field is authoritative.
2. **Capability fallback.** Otherwise, the resolver walks every installed capability's `schemas/*.yaml`, collects each schema's `binds_to:` glob entries, and uses the first matching glob.

When neither resolves, the file is reported as unresolved. Schema-version mismatches refuse with a structured migration hint (auto-migration is out of scope in v1).

`<path>` is a file or directory; directories walk recursively for `*.yaml` (`.pkit/` subtrees are excluded — those are kit-managed, not adopter data).

`pkit data validate` is distinct from `pkit schemas validate`: the latter validates the *spec* (capability YAML + companion); the former validates *instance data* (adopter file + its bound schema).

### `version`

Prints the CLI's version and your project's recorded core-layer version side by side. Useful for confirming whether `upgrade` has work to do.

### `version bump <segment>`

Bumps `.pkit/VERSION` per the policy in PRJ-002. `<segment>` is `patch`, `minor`, or `major`:

- **`patch`** — backward-compatible bug fix to existing surface.
- **`minor`** — new surface added (new command, new principle, new area). Pre-1.0, this is the typical bump and may carry breaking changes per semver convention for `0.x` releases.
- **`major`** — reserved for `1.0.0` and post-1.0 spec breakage. Pre-1.0 the command refuses major bumps.

The command parses the current version, validates it as semver, computes the new version, writes it back, and prints `Bumped backbone: <old> -> <new>`.

After writing the new backbone version, the command **auto-broadens** the `requires_backbone` upper bound on every kit-shipped `package.yaml` under `$SOURCE_KIT` whose existing range no longer includes the new backbone version. The new upper bound is `<NEW_MAJOR.(NEW_MINOR+1).0`. Components whose range still covers the new version are untouched (so patch bumps that stay within the current minor line are no-ops on `requires_backbone`). Component authors who deliberately want a tighter range narrow it manually after the bump.

The bump commit lands inside the same PR as the surface change it accompanies (per PRJ-002), so reviewers see both in one diff. Recommended commit message: `chore(versioning): bump backbone <old> -> <new>`.

## Standard flags

- **`--help`** on every command, including the root.
- **`--version`** on the root, equivalent to running the `version` subcommand.
- **`--dry-run`** on every mutating command (`init`, `sync`, `merge`, `upgrade`, `capabilities install`, `capabilities uninstall`, `capabilities upgrade`). Shows the plan without applying any changes.
- **`--color {auto,always,never}`** on the root (default `auto`). Colourizes human output via the semantic styling layer (per ADR-011); resolved once at the command boundary. Honours `NO_COLOR`; styling is never load-bearing (plain text carries all structure), so this never changes machine output or piped/redirected output.

## Command output conventions

Human-readable command output (the default read-for-understanding view) follows one shape so every command is consistent and self-explanatory without each author re-inventing layout. Machine output (`--json`, exit codes) is a separate concern. The exemplars are `pkit permissions overview` / `explain` / `profile list`; the shared renderer is `cli_render` (per ADR-006) — read-views should render through it rather than hand-building strings.

**The skeleton** (read-views):

```
<Title — what this is>   (pointer to the sibling view)

  <status banner: current state + glossed config>     # only if there's live state

SECTION — <what it is>
  <aligned rows, widths computed across all rows>

Legend
  <token>   <one-line meaning>                         # only tokens actually shown

Commands
  pkit … <args>   <3–5 word next step>
```

**Rules** (apply to *all* human output, including procedural/step logs like `setup autonomy`, even where `cli_render` doesn't fit):

- **Three zones, marked by typography + whitespace — never horizontal rules.** A view has a Header zone (title + status), a Body zone (sections + rows), and a Reference zone (Legend + Commands / next-steps). Mark boundaries with **header case** + one blank line, not drawn lines: data sections are **ALL-CAPS** with an em-dash gloss (`GUARDRAILS — …`); Reference/advisory zones use **Title-case** labels (`Legend`, `Commands`, `Next — …`, `One-time tip — …`). **No `────`/`====`/`----` rules** — width-ambiguous, alignment-fragile, and louder than the whitespace+typography scheme the field standardises on (gh / kubectl / docker / cargo use no rules).
- **One line per idea.** No multi-sentence headers or footer paragraphs; if a thing needs a sentence it's a Legend entry, not a paragraph. Empty/edge states get one line.
- **Label ↔ gloss is inline-parenthetical.** Put the secondary gloss in parentheses after the value (`Active profile: none   (only your manual grants apply)`); the em-dash carries a count/qualifier (`— 3 available`). Table rows keep the gloss as a *column* (stacking per row breaks alignment). Don't stack a plain indented sub-line as a subtitle — without a styling layer it's indistinguishable from a soft-wrap.
- **Compute column widths** across all rows; never hardcode (fixed widths go ragged on the longest entry). Sections share the width basis so they align.
- **Symbols sparingly:** `—` for glosses, `·` as a separator, `[…]` for tags. Avoid box-drawing and emoji (alignment-fragile, inconsistent across terminals). A command offered as a next step goes on its own indented line so it's copy-paste-obvious.
- **Cross-reference sibling views by name** so the surface is discoverable.
- **Styling is never load-bearing.** Structure must read with zero styling — header case + whitespace + indentation carry all meaning, exactly the plain output. Emphasis (bold/dim, later colour) only *amplifies* what the plain text already says; it never encodes information the plain text lacks. This holds for hand-authored output too, not just `cli_render`: if a reader piping to a file or using a screen-reader loses the meaning, the structure was wrong. The styling layer enforces it mechanically (`strip_ansi(styled) == plain`); hand-authored output owes the same discipline.

A stronger visible break is a *dim* header from the TTY-aware styling layer (per ADR-011): authors tag a semantic role (`heading` / `strong` / `muted`), one gate maps it to bold/dim on a TTY, degrading to plain whitespace when piped / `NO_COLOR` / `--color never` — not a drawn rule.

## Failure mode

The CLI runs forward-only — no transactional rollback across the manifest (see COR-004). If a command fails partway:

1. The project is left at a known partial state.
2. The error message identifies what went wrong and where.
3. Run `validate` to see the full picture.
4. Address the underlying issue and re-run the failing command, or revert the partial mutations through git.

Idempotent commands (`sync`, `merge`, `upgrade`, `validate`, `version`) are safe to re-run. `init` is not — recover via `validate` and targeted commands instead.
