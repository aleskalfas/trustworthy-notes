# Claude Code adapter

Translates kit content for the [Claude Code](https://docs.claude.com/en/docs/claude-code/) harness. This adapter is what makes a project-kit-adopting project usable from Claude Code — sets up its permissions, deploys its skills, and (eventually) its agents.

## What this adapter ships

```
.pkit/adapters/claude-code/
├── README.md                          # this file
├── settings/
│   ├── core/settings.json             # kit baseline — universal allows + denies
│   └── project/settings.json          # adopter's project-specific additions
├── deploy-skills.sh                   # creates .claude/skills/ symlinks pointing back at .pkit/skills/
├── permission-enforcement.yaml        # which permission dimensions this harness realizes, and via which layer
└── permission-hook.py                 # the PreToolUse enforcement hook (registered by `pkit permissions enable`)
```

### `settings/`

The kit's permissions story for Claude Code — what allows and denies are pre-configured in adopters' `.claude/settings.json`. Two halves per the universal area pattern (COR-005):

- **`core/settings.json`** — kit baseline. Universal allows (`gh`, `git`, `ssh`, common UNIX tools, kit-shipped script execution, agent-tool allows, `Skill(update-config)`) and universal safety denies (`git push --force` variants, `git reset --hard`, `rm -rf` family, `sudo`). The discriminator is "would every project-kit adopter benefit?"
- **`project/settings.json`** — adopter's project-specific additions on top of the baseline (language tooling, enterprise hosts, project-specific paths). Adopters typically add allows here; denies stay in the kit baseline.

The file Claude Code actually reads is the adopter's `.claude/settings.json`, hand-merged from these two until the merge command lands per COR-002 / COR-004. See **How adopters use this adapter** below.

Top-level keys outside `permissions` (e.g. `agent`, `model`) in either `core/settings.json` or `project/settings.json` flow through to `.claude/settings.json` with last-write-wins precedence (project overrides core; an existing adopter entry overrides both). Permissions keep their existing union-deduped semantics.

**Ownership modes (COR-002 authoritative-region tier).** By default (`ownership_mode: additive`) the merge is append/union/baseline-enforce — it only ever *adds* to `permissions` and re-asserts the safety denies, never removing adopter entries. Under `ownership_mode: managed` (set via `pkit permissions mode managed`), the realizer **owns the `permissions` region** and regenerates it **wholesale** from its model projection: the merge replaces `.permissions` with the projection supplied per-run (via `$PKIT_MANAGED_REGION_FILE`, written by `pkit permissions apply`) instead of unioning it, so a grant removed from the model vanishes (drift heals down to empty) — everything *outside* `.permissions` stays byte-for-byte adopter-owned. This needs no in-file markers and no strip-logic: `permissions` is already stripped from every source and recomputed each run, so managed mode only swaps the *source* of that recompute. The owned region is the fixed realizer constant `.permissions` (the hook rides the separate top-level `hooks` key); the gate is the `ownership_mode` config flag, never file-presence, so a stray region file can't reactivate managed behaviour. Managed mode only replaces when a projection is actually supplied: a plain `pkit sync` in managed mode with no projection in hand falls through to the additive default (it never blanks the region). *(The `apply` realizer that generates the projection is a later increment; this section documents the merge-primitive tier it builds on.)*

**Capability-contributed overlays** (per [project-management:DEC-030]). Installed capabilities can ship per-harness overlay templates and adopter-toggled live overlays under `.pkit/capabilities/<cap>/adapters/claude-code/overlay.template.json` (core-owned) and `.pkit/capabilities/<cap>/project/adapter-overlays/claude-code.json` (adopter-owned). `merge-settings.sh` walks manifest-registered capabilities; each capability whose adopter-owned overlay file is *present* contributes its top-level keys into the merge chain between `project/settings.json` and the existing target. The opt-in flow is the capability's own `enable-*` / `disable-*` CLI subcommand pair; for project-management, see `pkit project-management enable-default-agent`. Overlay `permissions` keys are reserved — silently stripped at merge time so overlays cannot influence allow/deny.

### `deploy-skills.sh`

Walks `.pkit/skills/{core,project}/<name>/` and creates relative symlinks at `.claude/skills/<name>/` so Claude Code can discover and load the skills. Idempotent; safe to re-run; skips non-kit-managed content under `.claude/skills/`. Per COR-005's adapter pattern, this is the Claude-Code-specific deployment for the harness-agnostic skill content stored at `.pkit/skills/`.

### Live permission enforcement (`permission-hook.py`)

The realizer that makes declared permissions *bite* at runtime (per [COR-028](../../decisions/core/COR-028-permission-model-realization.md) / [ADR-002](../../../docs/architecture/decisions/ADR-002-permission-realizer-ownership.md)). It's **opt-in** — see *enable / disable* below.

`permission-hook.py` runs under the **system `python3`** interpreter — no `uv`, no PEP-723 metadata, no third-party deps at startup. This is required so the hook starts inside macOS Seatbelt, where `uv` panics on a fixed `SCDynamicStore` denial (ADR-014). On each matched tool call Claude Code pipes a PreToolUse payload to its stdin; the hook builds the model through the shared, harness-neutral decision core (`.pkit/permissions/decide.py`) and either prints a `permissionDecision` (`allow` / `deny`) or **abstains** (exit 0, no stdout → the harness's normal permission flow proceeds). It imports the *same* `decide.load_model` + `decide.decide` the `pkit permissions` CLI uses, so the hook and the CLI can never decide differently (ADR-002's same-code invariant).

**Zero-dep shebang + stdlib YAML fallback.** The hook's shebang is `#!/usr/bin/env python3` (bare, no `uv`). The shared loader in `decide.py` (`load_yaml`) tries `ruamel.yaml` when available and falls back to a stdlib-only YAML-subset parser when not — handling the full file subset (block mappings/sequences, single/double-quoted strings, flow sequences, block scalars, booleans). **The fallback lives in the shared `decide.py` loader, not in the hook**, so both the hook and the `pkit permissions` CLI parse via the same code path — the same-code invariant is mechanically preserved, not aspirational.

**The double-lock.** The non-negotiable guardrail denies — every privilege the catalog flags `guardrail: true` (currently `privilege-escalation`, `destructive-fs`, `vcs-history-rewrite`) — are enforced in two independent layers:

1. **fail-open hook half** — synthesized as `{subject: all, effect: deny}` grants in the model, derived from the privileges the catalog flags `guardrail: true` (the catalog is the single source of truth). The hook **fails open on decision faults** (malformed payload, ambiguous model): any such fault yields a silent abstain, never a silent block. Set `PKIT_PERMISSIONS_DEBUG=1` to surface decision fault reasons on stderr.
2. **fail-closed native half** — the catastrophic `deny` patterns in `settings/core/settings.json`. These hold even if the hook is absent, faults, or is version-skewed, so failing open in layer 1 can never bypass them.

**Enforcement-runtime fault taxonomy (ADR-002 amendment).** The fail-open contract covers *decision faults* (hook ran, couldn't resolve). A distinct class — *enforcement-runtime faults* — means the hook **cannot start at all** (python3 missing, decide.py absent, syntax error). This class is **fail-loud**, not fail-open: `pkit permissions enable` and `pkit permissions sandbox enable` run a startup self-check after registering the hook and warn loudly if the hook cannot start, so the operator learns enforcement is not running rather than believing a dead hook is gating calls. `pkit permissions overview` also surfaces this state when enforcement is registered-but-dead: it runs the self-check and reports "ENFORCEMENT-RUNTIME FAULT — hook CANNOT START" with the diagnosed reason.

**enable / disable** (the opt-in toggle, per issue #247's "Option B" — mirroring the [project-management:DEC-030] default-agent precedent). Because the hook fires per tool call, registering it is the adopter's explicit choice, not an install default:

```
pkit permissions enable
```

Registers the hook under the top-level `hooks.PreToolUse` key in `.claude/settings.json` (command `${CLAUDE_PROJECT_DIR}/.pkit/adapters/claude-code/permission-hook.py`, matcher `*`) and ensures the fail-closed native guardrail denies are present. Refuses if the claude-code adapter isn't installed. Idempotent.

After registering, runs the **enforcement-runtime self-check** (per the ADR-002 amendment): drives the hook script under `python3` with a probe payload to verify it can start. If the hook cannot start (python3 missing, decide.py absent, etc.), outputs a loud WARNING naming the fault and the remediation — rather than silently proceeding with a dead hook that fail-opens on every call.

```
pkit permissions disable
```

Strips *only* the pkit hook registration (matched by its command path), preserving any other adopter hooks, and leaves the native guardrail denies in place. The explicit strip is required because the merge primitive treats existing top-level settings keys as last-write-wins survivors — the DEC-030 strip-logic pattern. Idempotent; leaves no orphaned registration.

The hook **script** itself is a propagated adapter file — `pkit sync` owns its lifecycle, so `enable`/`disable` manage only its *registration*, never deploy or remove the file (there is no orphaned-script failure mode). The registration is written only to the live `.claude/settings.json`, never to a merge source, so it survives re-merge and is removable by strip (the `hooks` key lives outside any realizer-owned region per ADR-002).

**`pkit permissions sandbox enable`** sets `failIfUnavailable: true` always (the ADR-004 / ADR-014 §6 fail-closed invariant), so Claude Code refuses to start an unconfined session rather than silently running without a box. It also runs the enforcement-runtime self-check (same as `enable`) AND verifies **actual confinement** — attempts a write outside the workspace that Seatbelt/bubblewrap must deny. If the write succeeds, it warns "sandbox configured ON but NOT actually confining" loudly (box may not have initialized, or the session hasn't been restarted). `pkit permissions sandbox status` and `pkit permissions overview` report the same actual-confinement probe result so the operator never believes confinement is active when it is not.

### Prompt-free command shape under the sandbox

This is the Claude Code realization of the universal "work with the permission layer, not around it" rule (`.pkit/rules/core.md`). With the sandbox on, `.claude/settings.json` carries `sandbox.autoAllowBashIfSandboxed: true` — so a **single, simple Bash command auto-allows** because it runs inside the box, no prompt. What still prompts is the command *shape* the parser can't statically vet: a leading `cd`, statements chained with `;`, pipelines (`| grep | head`), and command substitution. Those fall back to a confirmation even under the sandbox, and an allow-list entry for the inner tool does not help (the parser keys on the outer/first token). So the agent's discipline is: **one clean command per call; the harness's `Read` / `Grep` / `Glob` / `Write` tools for inspection and file I/O — not `cat`/`sed`/heredocs/pipelines.**

For a genuinely multi-step diagnostic, compose the complexity into a file and run it as one invocation: author the script with the `Write` tool (prompt-free, and the call shows its contents), then run a single `bash <file>`. The parser sees only that one clean command; the box auto-allows it; the multi-step logic runs *inside* the sandbox.

**Caveat — this is for read-only diagnostics only.** Wrapping commands in a script **bypasses the PreToolUse hook**: the hook inspects the outer `bash <file>` invocation, not the script's contents, so a gated mutation hidden inside a script (e.g. a raw `gh issue edit` the model denies) slips past the check. The OS sandbox still bounds the script at the OS level, but the hook's *intent* denies are policy, not OS-enforced (ADR-004 §61 — the allowlist is not a security boundary). So never use the script-wrap mechanic to run mutations the model gates; those go through the validated capability scripts, which the hook sees and the model checks.

When a diagnostic recurs, it graduates from a `/tmp` throwaway into a committed project command (or a `pkit` subcommand for repo-agnostic ones) per the core rule's COR-007 extraction.

### `permission-enforcement.yaml`

The per-adapter enforcement-capability declaration (per COR-028): which dimensions of the permission model this harness realizes natively, via the hook (runtime, fail-open), or not at all (reported for the OS/container layer). `pkit permissions diff` reads it to label declared intent the harness cannot faithfully enforce.

## How adopters use this adapter

Until the install/sync runtime per COR-004 lands, deployment is manual:

1. **Permissions.** Hand-merge `settings/core/settings.json` + `settings/project/settings.json` into your project's `.claude/settings.json`. Per COR-002's merge contract: append-only for adopter content, baseline-enforce for safety denies, idempotent.
2. **Skills.** Run `.pkit/adapters/claude-code/deploy-skills.sh`. Creates the `.claude/skills/` symlinks (tracked in git per the project's `.gitignore`, so a fresh clone has the same environment).
3. (Future) **Agents.** A `deploy-agents.sh` will land here once `.pkit/agents/` has content.
4. **Permission enforcement (opt-in).** Run `pkit permissions enable` to register the PreToolUse hook; `pkit permissions disable` to remove it. See *Live permission enforcement* above.

When the merge command exists, `pk merge` (or the equivalent verb) automates step 1 honouring the COR-002 contract; step 2 becomes part of the install/sync flow.

### Git footprint (per ADR-009)

This adapter declares its out-of-`.pkit/` deploys as a `footprint:` list in its `package.yaml` (`.claude/skills`, `.claude/agents`). `pkit visibility private` aggregates that with the backbone's `.pkit/` and routes the whole set into the per-clone `.git/info/exclude` — so a developer can run pkit on a repo whose team hasn't adopted it, with no committed trace. `pkit visibility shared` (the default, and what project-kit itself uses) keeps the deploys committed so a fresh clone shares the environment.

## Project-kit's own use

project-kit self-hosts: it's the first adopter of its own kit. The `.claude/settings.json` at the repo root and the symlinks under `.claude/skills/` are what's been deployed by hand-following the steps above. When the merge command exists, project-kit re-deploys via the command.

## Codex / other harnesses

A separate adapter under `.pkit/adapters/<harness-name>/` would carry equivalent translations for that harness — potentially different file formats, different deployment paths, different scripts. The kit's own content (skills, agents, decisions, workflow) is portable across harnesses; only this adapter layer is harness-specific.
