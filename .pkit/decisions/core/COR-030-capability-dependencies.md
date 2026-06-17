---
id: COR-030
title: Capabilities declare versioned dependencies on other capabilities
status: accepted
date: 2026-06-17
author: Aleš Kalfas <kalfas.ales@gmail.com>
---

## Context

A capability is an opt-in installable unit (COR-017). Capabilities increasingly build on one another — one capability's behaviour invokes another's interface (its scripts, its tracker, its data). Today a capability can declare only its compatibility with the backbone (`requires_backbone`); it has no way to declare that it depends on *another capability*.

Two failures follow from that gap. The obvious one: a dependent is installed while its dependency is absent, so the dependent's calls fail. The insidious one: the dependency is present but has **evolved its interface incompatibly** while the dependent still expects the old contract — which fails silently at runtime, not at any lifecycle boundary. For an actively-developed dependency the second failure is the more likely one, and a presence check cannot see it. The methodology needs a way for a capability to declare a dependency on another *with a compatibility constraint*, so both failures surface loudly at install/upgrade/uninstall rather than at runtime.

## Decision

**A capability may declare dependencies on other capabilities in its manifest, each carrying a version constraint; the lifecycle gates on them.**

- **`requires_capabilities`** — an optional field in the capability's per-component manifest (its `package.yaml`, beside `requires_backbone`): a list of entries, each a capability **name** plus a **semver range** (the multi-target analogue of `requires_backbone`, which is a single range against the one backbone).
- **Install is gated on presence *and* version.** Before a dependent's files are placed, a pre-flight check — alongside COR-017's existing existence / backbone / collision pre-flights — verifies each declared dependency is installed *and* its version satisfies the range. If a dependency is absent or out-of-range, install **refuses with an actionable hint** (install or upgrade the dependency first). It never silently proceeds, and never auto-installs the dependency.
- **Incompatible evolution screams — direction-split, and deadlock-free.** The compatibility check applies at **both** upgrade entry points — the backbone-wide upgrade (which already refuses to advance the backbone past an installed component's `requires_backbone` range) *and* the single-capability upgrade (which has no compatibility check today) — sharing one version-range / installed-state primitive, not living solely in the backbone resolver. The disposition is keyed to *which side is moving and whether the operator can resolve it by choosing a version*:
  - *Installing or upgrading a **dependent** against an out-of-range dependency* → **refuse with an actionable hint** (as the install gate above). The operator controls the dependent's version, so there is no deadlock.
  - *Upgrading a **dependency** past an installed dependent's range* → **loud warning naming each now-desynced dependent, proceeding only under an explicit `--force`** — never a hard block. A hard block here would deadlock: the operator could not advance the dependency until a wider-range dependent existed, and cascade-upgrade is deliberately out of scope, so nothing in the mechanism would produce one. The override is the by-hand analogue of cascade-upgrade, and the dependent's own runtime guard is the backstop. This mirrors the existing uninstall refuse-but-`--force` disposition.

  A capability's version reflects its surface changes, so a breaking change to a dependency trips its dependents' ranges.
- **Uninstall is gated.** Uninstalling a capability **refuses** when an installed capability declares it in `requires_capabilities` (a manifest walk), extending the existing reference-based uninstall refusal to *behavioural* dependencies that leave no textual citation. Refusal with an explicit `--force` escape — not cascade-uninstall.

**Deliberately out of scope** (deferred until a consumer requires them): topological install-ordering and cycle detection (install is one-at-a-time and operator-driven, so a missing dependency surfaces as an immediate, comprehensible refusal — not corruption, not a resolver hang); and automatic cascade-install of missing dependencies or cascade-upgrade of dependents (refuse-with-hint, not auto-resolve).

**The runtime guarantee lives in the dependent, not in this mechanism.** A dependent refusing to operate when its dependency is absent or unreachable *at the moment it is invoked* is owned by the dependent capability itself. The lifecycle gates above are an early, friendly surface on top of that runtime guard — not a substitute for it.

## Rationale

- **Why a versioned edge, not presence-only.** The dependency is on the source capability's *interface*, not merely its existence. Presence catches an absent dependency but not one that is present yet evolved incompatibly — the dominant failure for an evolving dependency. A version range is precisely what converts silent interface drift into a loud, lifecycle-time refusal.
- **Why generalize the existing resolver, not build a new one.** Backbone-compatibility resolution already expresses "refuse or surface when a version falls outside a declared range." A capability dependency is the same shape on a second axis; reusing the same resolution keeps one compatibility mechanism instead of two.
- **Why refuse rather than auto-resolve.** Refuse-with-actionable-hint is the methodology's consistent disposition (uninstall refuses rather than cascades; sync warns rather than auto-removes). Auto-install / auto-cascade would be the surprising choice, and it imports package-manager machinery — ordering, cycle detection — that one-at-a-time install does not need.
- **Why the disposition is direction-split, not uniform.** It is keyed to which side moves and whether the operator can resolve it by choosing a version. Installing a dependent is fully in the operator's control, so an out-of-range dependency is a refuse-with-hint (pick a compatible dependent). Upgrading a dependency can desync an *already-installed* dependent the operator cannot instantly replace — so it warns and proceeds under an explicit override (the deadlock-free, by-hand analogue of cascade-upgrade) rather than hard-blocking.
- **Why the runtime guard lives in the dependent.** No lifecycle check can prevent the dependency from being absent or broken at the instant the dependent actually invokes it; the only robust guarantee is the dependent refusing to operate. The lifecycle gates are convenience and early warning, not the guarantee.

### Alternatives considered

- **Presence-only dependency (no version).** Rejected — catches absence but not incompatible evolution, leaving the likely failure (interface drift in an actively-developed dependency) to fail silently at runtime.
- **Full dependency resolver (topological ordering, cycle detection, cascade install/upgrade).** Rejected as premature — one-at-a-time operator-driven install makes ordering and cycles a non-issue (a missing dependency is an immediate, comprehensible refusal), and auto-resolution contradicts the refuse-with-hint disposition. The field can grow these later if a real multi-dependency install path appears.
- **Couple the dependency edge to a capability's permission/grant contributions.** Rejected — the two are orthogonal. A dependency edge gates *presence* at lifecycle boundaries; a capability's permission contributions are a function of *installed-state* composed downstream. The edge sits upstream of that composition; neither needs to know about the other (uninstalling a dependent already drops its own contributions; uninstalling a dependency is already blocked by the edge).

## Implications

- A capability manifest gains an optional `requires_capabilities` list (name + semver range). Pure addition; capabilities that declare none are unaffected. No migration (additive field, no schema rename or removal).
- The install pre-flight gains a dependency check; the compatibility check is wired at **both** upgrade entry points (the backbone-wide upgrade and the single-capability upgrade — the latter has no compatibility check today), sharing one version-range / installed-state primitive rather than living only in the backbone resolver; the uninstall refusal gains a manifest-walk for declared dependents. Implementations reuse the existing version-range and installed-state primitives rather than introducing new ones.
- This **stands on COR-017** (the capability primitive) and **supersedes nothing**. COR-017's single-capability lifecycle is unchanged; this adds a composition relationship between capabilities. COR-017 may gain a one-line forward pointer to this record.
- A dependent capability's own runtime guard (refuse-to-operate when a dependency is absent or unreachable) is a capability-internal concern, recorded in that capability's own decisions, not here.
- Versioned ranges, like all cross-component compatibility, presume the dependency's version reflects its surface changes; a project whose version policy bumps on surface changes gets meaningful ranges for free.
