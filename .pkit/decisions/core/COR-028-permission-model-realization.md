---
id: COR-028
title: Permission model realized by adapters
status: accepted
date: 2026-05-29
author: Ales Kalfas <kalfas.ales@gmail.com>
---

## Context

Agents (COR-013) and the human operator act through a harness, and the harness gates what they may do through its own permission mechanisms — configuration files, per-agent tool lists, runtime interception of calls, and the like. Today an adopter configures those mechanisms directly, in harness-native form. Three problems follow:

- **No domain-level view.** What a given agent is permitted to do is spread across harness-native config in harness-native vocabulary. An adopter cannot see, from one place and in their own terms, "this agent may use the container tool here but nowhere else."
- **No fault localization.** When something is wrongly allowed or wrongly blocked, the adopter cannot tell whether the harness config states the wrong rule, the intended rule was applied to the wrong place, or the harness simply cannot enforce what was intended.
- **Hand-editing low-level config.** Changing permissions means editing harness-native files by hand, which is exactly the surface adopters should not have to reason about.

Harnesses also differ in what they can enforce: some scope rules per agent, others only per session; some can restrict by location, others cannot; and some intents — confining network egress, for instance — are not enforceable inside any harness at all. COR-013 already establishes that agent content is harness-neutral and the adapter translates it to harness-native form; COR-002 establishes the merge-delivery contract by which methodology content reaches adopter-owned configuration. This record extends that same split to permissions.

## Decision

Permissions are a **harness-neutral model owned by the methodology**, and each harness adapter is the **realizer** that enforces it.

1. **The model is the source of truth.** It declares, in domain terms, what each *subject* — an agent, a shared baseline applying to all, or the operator (the human driving the session) — is permitted to do: a named *privilege*, optionally constrained to a *scope* (where or when it applies), with an *effect* of allow or deny. Each agent's effective permissions are the union of the shared baseline and the agent's own grants; where an allow and a deny conflict, deny prevails. The set of privileges and how each is recognized is methodology data (a catalog), extensible by the layers that own the relevant tools.

2. **The adapter realizes the model.** Each harness adapter translates the model into that harness's native enforcement mechanisms, preferring the most-native faithful mechanism available and reserving heavier mechanisms (such as runtime interception) for intent the native configuration cannot express. Because some enforcement mechanisms fail open — a fault in the mechanism lets the call proceed — a deny that must never be bypassed is realized on a fail-closed mechanism rather than entrusted to a fail-open one. The adapter also reads realized state back, so the model and reality can be reconciled.

3. **Unenforceable intent is reported, not dropped.** A realizer declares which dimensions of the model its harness can natively enforce. When the model expresses intent the harness cannot faithfully enforce, the realizer renders the closest achievable enforcement and **reports the residual gap** rather than silently discarding it — so the adopter can close the gap outside the harness (for example at the operating-system, container, or network layer).

4. **Ownership of adopter config is a per-project mode.** How much of the adopter's harness-owned configuration a realizer may own is chosen per project. The default is **additive**: the realizer only adds, never removes, leaving the adopter's configuration under the adopter's control. An opt-in **managed** mode lets the realizer own and regenerate its region of that configuration, healing drift so the model is the whole truth.

The model is authoritative; realized harness state is a generated projection of it.

## Rationale

- **One source of truth, in domain terms.** An adopter sees and changes a single model rather than hand-editing scattered harness-native config, and a failure localizes to exactly one of three layers — the model states the wrong intent, the realizer mis-translated it, or the harness cannot enforce it — instead of being opaque.
- **Reuse of the established split.** Adapter-as-realizer is COR-013's harness-neutral-content / adapter-translation rule applied one domain over. The model stays portable across harnesses while each adapter does what its harness permits.
- **Honesty about capability gaps.** Harnesses enforce different subsets of any expressive model. Reporting what cannot be enforced turns a silent hole into an auditable boundary the adopter can close deliberately, which is the difference between believing a confinement holds and knowing where it does not.
- **Adopter sovereignty by default.** The additive default never removes adopter configuration, so adopting the model is non-destructive; projects that want full reliance opt into managed ownership explicitly.

### Alternatives considered

- **Configure harness-native permissions directly (status quo).** Rejected: no domain-level view, no fault localization, no portability across harnesses; every change is a hand-edit of low-level config.
- **A single runtime interceptor as the sole authority.** Rejected: it couples the model to one harness's interception feature, forgoes faster and fail-closed native mechanisms where they exist, and concentrates enforcement in one failure-prone point. The realizer prefers the most-native faithful mechanism and uses interception only for what native configuration cannot express.
- **A least-common-denominator model (express only what every harness can enforce).** Rejected: it would forbid stating real intent — such as per-agent or per-location limits — merely because some harness cannot enforce it. Reporting the gap (decision point 3) is strictly more expressive and more honest.

## Implications

- **Model and catalog are schema'd data.** The permission model (subjects, privileges, scope, effect) and the privilege catalog are methodology data; their concrete shape is owned by their schemas per COR-018 and the relevant area and adapter documentation, not enumerated in this record.
- **Adapters gain a realizer responsibility.** Each harness adapter declares the enforcement dimensions it supports and implements the translate-realize-read-back-report contract above. The concrete realization for any specific harness — which native mechanism carries which grant, and the exact registration and abstention details — is that adapter's documentation, not this record.
- **The CLI gains permission operations.** The methodology's CLI provides operations to inspect the model, mutate it, realize it, and reconcile it against realized state; the command surface is owned by the CLI reference per COR-004, not enumerated here.
- **Refines COR-002.** Managed mode requires the merge-delivery contract to support an *authoritative region* that a realizer owns and replaces wholesale, while leaving the rest of the adopter-owned file untouched — distinct from COR-002's append-only union. COR-002 is refined to add this delivery tier; the additive default rides the existing append behavior unchanged.
- **Resolves a deferred reservation.** Any capability or adapter mechanism that reserves the harness permission region against contribution defers, in managed mode, to the realizer as the sanctioned owner of that region; the additive default contributes only through mechanisms already permitted. (The concrete instance is the project-management capability's reservation of that region, amended to point at this record.)
- **Architecturally significant.** A realizer owning a region of an adopter-owned harness file is a boundary change recorded as an ADR at the project's architecture-decision path per COR-025.
- **Migration is additive and behavior-preserving.** Introducing a realizer into an installed adopter changes nothing by default — it reports and abstains rather than altering existing enforcement — so the surface change ships with a migration per COR-010 that is a no-op for the default mode.
