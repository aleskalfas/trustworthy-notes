---
id: DEC-030
title: Capability-contributed adapter overlays — per-harness settings fragments with file-presence opt-in
status: accepted
date: 2026-05-28
author: Ales Kalfas
---

## Context

The claude-code adapter's `merge-settings.sh` (per [COR-002](../../../decisions/core/COR-002-merge-delivery.md)) builds `.claude/settings.json` from a fixed source chain: `.pkit/adapters/claude-code/settings/core/settings.json`, `.pkit/adapters/claude-code/settings/project/settings.json`, and the existing target. The script already walks installed capabilities for one thing — emitting `Skill(<name>)` allows from `.pkit/capabilities/<cap>/skills/` via `collect_skill_grants`. That walker is a one-off carve-out; there is no general path for a capability to contribute *settings keys* to `.claude/settings.json`.

Issue [#188](https://github.com/aleskalfas/project-kit/issues/188) (default project-manager agent for adopters) needs a top-level `"agent": "project-manager"` key in `.claude/settings.json`, conditional on the adopter opting in. The merge-broadening from [#190](https://github.com/aleskalfas/project-kit/issues/190) makes top-level keys flow through; this DEC pins *where the capability declares the contribution* and *how the adopter toggles it*.

A prior draft of this DEC put a `session_defaults:` block in the capability's `project/config.yaml`. Adversarial review (critic agent, 2026-05-28) rejected that shape: `project/config.yaml` has no validating schema, it conflates harness-agnostic capability config with harness-shaped payload, and the proposed alphabetical-tiebreak precedence was a category error. A second review of the revision below pushed on uninstall semantics, template-drift, and walker scope; this final shape addresses those by clarifying each.

Three questions this DEC pins:

1. **Where does the capability declare its proposed settings contribution?** In a dedicated, harness-specific subtree.
2. **Where does the activation state live?** In a separate, adopter-owned file whose *presence* is the activation signal.
3. **How does the toggle expose itself to the adopter?** Capability-shipped `enable-*` / `disable-*` CLI subcommands.

## Decision

### Layout: per-capability, per-harness overlay subtree

Capabilities that contribute settings to a harness ship two file roles, in two locations under the capability directory:

```
.pkit/capabilities/<cap>/
├── adapters/
│   └── <harness>/
│       └── overlay.template.json           # core-owned; capability ships it
└── project/
    └── adapter-overlays/
        └── <harness>.json                  # adopter-owned; created by enable, removed by disable
```

- **`overlay.template.json`** is core-owned (capability source-of-truth; sync overwrites on capability update). It is a JSON object whose top-level keys are the settings the capability would contribute when active. The shape constraint: top-level keys outside `permissions` (see "Reserved keys" below).
- **`<harness>.json`** is adopter-owned (under `project/`; sync does not touch). Its **presence is the activation signal**. The file's content is always a copy of the current template at the time of last `enable` — adopters do not hand-edit this file in v1 (see "v1 scope: no in-place customisation" below).

The `<cap>/adapters/<harness>/` subtree extends [COR-017](../../../decisions/core/COR-017-capability-pattern.md)'s capability layout convention. Both new subtrees are *optional*: capabilities that don't contribute settings (the common case today) carry neither. When a second capability adopts the pattern, the addition stabilises into a convention worth formalising in COR-017's body; until then, this DEC is the reference.

### Activation: file-presence semantics, manifest-scoped walker

The contribution is *active* when the adopter-owned overlay file exists, *inactive* when it does not. No flag, no schema field, no null-vs-absent ambiguity.

`merge-settings.sh` gains a `collect_capability_overlays` walker analogous to `collect_skill_grants`, with one important refinement over the existing skills walker:

- **The walker iterates capabilities registered in the manifest** (`.pkit/manifest.yaml`'s `components:` list), not arbitrary directories under `.pkit/capabilities/`. This prevents orphan capability directories (left behind by botched uninstall, stash, or rebase) from silently contributing to `.claude/settings.json`.
- For each manifest-registered capability `<cap>`, the walker checks for `.pkit/capabilities/<cap>/project/adapter-overlays/claude-code.json`.
- If present, that file is included as a merge source between the adapter's `project/settings.json` and the existing target.
- If absent, the walker skips silently.

The merge precedence is the jq `*` operator's natural behaviour from [#190](https://github.com/aleskalfas/project-kit/issues/190): later sources win for scalars and arrays; deep merge for nested objects. The walker visits capabilities in dictionary order of capability name — deterministic and reproducible, but **not load-bearing**: capabilities are expected not to contribute to the same top-level keys (each capability owns a distinct concern). The ordering exists only to make collisions deterministic in the corner case where two capabilities do collide; the DEC does not declare collision a supported configuration.

### Reserved keys: `permissions` is owned by the existing two-layer merge

Step 1 of `merge-settings.sh`'s jq filter (per #190) computes `permissions.allow` / `permissions.deny` from the existing inputs and Skill grants, then layers that on top of the reduction. **A `permissions` key inside a capability overlay is silently overridden by step 1 and effectively a no-op.**

Overlay templates must not contain a top-level `permissions` key. Capabilities that need to add allows or denies do so via the existing skill-grant mechanism (`Skill(<name>)`) or by contributing to the kit's core settings during a future DEC — not through the overlay subtree.

**Deferral to a permission realizer ([COR-028](../../../decisions/core/COR-028-permission-model-realization.md)).** The "future DEC" anticipated above is COR-028. A permission realizer operating in its **managed** ownership mode owns and regenerates the `permissions` region as an *authoritative region* (per the COR-002 refinement) — it is the sanctioned writer of that region, beyond merely reserving it against overlay contribution. The realizer's **additive** default contributes nothing to `permissions` beyond what this rule already permits (baseline denies + skill grants), so this reserved-key rule stands unchanged for the default and for any adopter not running a managed realizer.

### Toggle: enable always refreshes from template; disable always removes

Each capability that ships an overlay template ships paired `enable-*` / `disable-*` CLI subcommands. For project-management, the first instance is:

```
pkit project-management enable-default-agent
pkit project-management disable-default-agent
```

**`enable`** copies `adapters/claude-code/overlay.template.json` to `project/adapter-overlays/claude-code.json`, **overwriting any existing live file**. Then runs `pkit sync` to re-execute `merge-settings.sh` against the updated state. Idempotent in the sense that re-running converges on "live matches current template"; the **live file is always derived from the current template at the moment of the most recent enable**.

**`disable`** does three things in order: (1) reads the live overlay file to enumerate the top-level keys it contributed; (2) strips those keys from `.claude/settings.json` (in-place edit, skipping any `permissions` since the reserved-key rule means an overlay never legitimately contributed permissions); (3) removes the live overlay file. Then runs `pkit sync` to re-merge with the updated state. The explicit strip is necessary because the merge primitive treats existing target entries as last-write-wins survivors (per [#190](https://github.com/aleskalfas/project-kit/issues/190)'s broadening) — the primitive cannot distinguish "stale source contribution" from "manual adopter edit", so it would otherwise carry forward the overlay's keys after the overlay file is gone. The disable subcommand owns the cleanup knowledge. (Under a managed permission realizer per [COR-028](../../../decisions/core/COR-028-permission-model-realization.md), this concern does not arise for the `permissions` region: that region is an authoritative region the realizer regenerates wholesale, so removing the realizer's source makes the region vanish on the next run — no strip-logic, no markers, and no need to distinguish stale contribution from manual edit.)

No-op semantics: re-running `disable` when the live overlay is already absent skips steps 1–3 and re-runs sync only.

**Adapter precondition.** `enable` refuses with a clear message if the claude-code adapter is not installed in the adopter project — writing an overlay file no walker will read would be silent dead weight. The check inspects the backbone manifest for an `adapter:claude-code` component.

The `enable` semantics is deliberately *always overwrite* — not "copy iff absent". The intent: after a capability update changes the template (e.g. a new key, a renamed value), re-running `enable` brings the adopter's live overlay back in sync with the capability's current intent. The cost: no in-place customisation in v1.

### v1 scope: no in-place customisation

The live overlay file is not an adopter customisation surface in this DEC's scope. Adopters who want to override what the capability would contribute have two options today:

- **Don't enable.** Hand-edit `.claude/settings.json` directly with whatever values they want. The adapter never strips keys it didn't put there.
- **Wait.** A future DEC may introduce an `overlay.override.json` mechanism (adopter-owned, applies after the live overlay in the merge chain) once a real customisation need surfaces. Speculating now would over-spec; the v1 surface is exactly "enable / disable, no middle".

This boundary is what makes `enable always overwrites` viable: there is no hand-edited live file to preserve.

### Uninstall: capability uninstall removes the overlay activation

Uninstalling a capability removes the entire `.pkit/capabilities/<cap>/` directory, including the `project/adapter-overlays/<harness>.json` file if present. This is **not** a violation of the no-shared-files invariant or the "sync doesn't touch project/" rule: those rules govern *sync* and *content-update* operations, not uninstall.

`sync` is the operation that must not touch adopter content (because sync runs implicitly on update). Uninstall is the operation an adopter invokes explicitly to remove the whole capability; sweeping the capability's directory entirely (including the live overlay) is the documented semantics, the only honest behaviour, and the only one that does not leave orphan settings keys persistently referenced in `.claude/settings.json`.

After uninstall, the previously-contributed keys remain in `.claude/settings.json` because the merge primitive carries existing target entries forward (per [#190](https://github.com/aleskalfas/project-kit/issues/190)). Adopters who uninstall a capability with an active overlay should run `disable-<name>` *before* uninstalling so the keys are stripped cleanly; uninstall does not currently invoke the capability's own disable subcommand on the way out (a recognised follow-up — a capability-tier uninstall hook would address this). The walker stops including the overlay source on the next merge regardless, so the contribution can never be reactivated by accident; only the prior values linger.

## Consequences

**Opt-in default semantics preserved.** Installing the project-management capability creates the template (`adapters/claude-code/overlay.template.json`) but no activation file. `.claude/settings.json` is unchanged on install. The adopter runs `enable-default-agent` to activate; `disable-default-agent` reverses; uninstall removes the whole tree.

**No-shared-files preserved in the sync path.** The template is core-owned (sync overwrites on capability update). The live overlay is adopter-owned (under `project/`; sync does not touch). The CLI subcommands write only the adopter-owned location.

**Manifest-scoped walker prevents orphan contributions.** Stash, rebase, or botched-uninstall states that leave a capability directory present but unregistered in the manifest no longer silently activate that capability's contribution. The walker honours the manifest as the source of truth for installed-ness.

**Template-drift handled by always-overwrite.** Capability updates that change the template land on the adopter's next `enable` invocation, without divergence detection or interactive prompts. The trade-off is the v1 no-customisation boundary.

**Reserved-key contract is explicit.** Overlays must not contain `permissions` — that key is owned by the adapter's existing two-layer merge and would be silently overridden. Capabilities that need permissions contribute via the existing skill-grant mechanism.

**Non-additive template changes use the migration framework.** If a future template revision *renames* or *removes* a top-level key (a breaking change to overlay content), the capability ships a capability-tier migration script per [COR-010](../../../decisions/core/COR-010-resource-lifecycle.md) that detects adopters with the live overlay present and re-runs `enable` on their behalf. Pure-additive template changes (new key with sensible default) do not need a migration — adopters either re-run `enable` to pick up the new key, or carry on with the prior live overlay until they do.

**Second-harness generalisation is deferred.** The DEC's layout (`<cap>/adapters/<harness>/`) implies generalisation across harnesses, but the contract — JSON shape, the reserved `permissions` rule, jq `*` semantics — is claude-code-specific. When a second harness adapter materialises (Codex, Cursor, etc.), each capability with overlay support will need a sibling `<cap>/adapters/<other>/` template carrying that adapter's shape rules. This DEC does not pre-define those rules; the second harness's adapter authors do.

**Surface change.** This DEC defines a new optional layout convention plus a `merge-settings.sh` walker addition. Both are pure additions (no breaking changes to existing inputs; capabilities without the overlay subtree behave identically to before). The adapter version bumps in the implementing PR (#191); the backbone version bumps because adopters can rely on the new convention.

## Rejected alternatives

**`session_defaults:` block in the capability's `project/config.yaml`** (the original draft). Rejected per the prior critic pass: `project/config.yaml` is consumed by capability scripts as harness-agnostic config; no validating schema; collision precedence by directory ordering would have been a category error.

**Always-on capability contribution** (no opt-in). Rejected per #188's explicit opt-in requirement.

**Marker file or manifest entry as the activation signal, separate from the overlay content** (critic's counter-alternative #7/#8). Considered: split activation (a marker file or manifest field) from content (the overlay file). Rejected for v1 because the two-file shape (template + live) collapses to one of each role cleanly, and "file presence = active" is greppable and inspectable. The counter-alternative's added clarity matters only when in-place customisation is on the table; v1 scope rules that out.

**Hand-edit-as-escape-hatch on the live file.** Considered for v1 inclusion. Rejected because it conflicts with "enable always overwrites" — and weakening enable's semantics to "copy iff absent" would create the template-drift problem (capability updates would stop reaching adopters who'd enabled at an earlier template version). Customisation deferred to a follow-up DEC if real demand emerges.

**Hard-coded contribution in `.pkit/adapters/claude-code/settings/core/settings.json`**. Rejected because the adapter is harness-specific but capability-agnostic; coupling it to a specific capability's agent name would force the agent on every adopter regardless of which capabilities they install.
