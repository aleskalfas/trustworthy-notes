---
id: DEC-027
title: Review modes — agent (default) and human, with three-layer per-PR override resolution
status: accepted
date: 2026-05-27
author: Ales Kalfas
---

## Context

[project-management:DEC-026-work-ownership-lifecycle] ships the seven workflow-wrapper commands and pins `done-work`'s approval gate as a three-way OR (APPROVED review / `Approved`-prefix comment / `--bypass`). The three-way OR assumes a human reviewer is available — but the methodology has no vocabulary for *which* humans review, *when* an agent can substitute, or *how* the choice composes across project-default-vs-per-issue.

Three forces pull apart:

1. **Solo developers and exploratory projects have no human reviewer**, yet still want an approval gate. Routinising `--bypass` defeats the bypass mechanism's audit-trail purpose. Self-approval via the `Approved`-prefix path doesn't add signal beyond the merge action itself.

2. **Multi-member teams may prefer agent review by default** even when humans are available — for efficiency, for routine changes, or for fast-iteration phases. Tying review mode to team size assumes "team exists ⇒ human review required", which doesn't match the real preference space.

3. **Some issues need human review regardless of project default** — security-sensitive changes, architectural reworks, scope-shifting refactors. The mode has to be overridable per-issue, not just per-project.

The methodology should commit to a **review-mode configuration** that is set per project (with a sensible default), overridable per-issue (via labels), and overridable per-invocation (via flags). The *mechanism* by which an agent's review counts as approval lives in [project-management:DEC-028-agent-as-approver-paths] — a sibling DEC that owns the verdict-comment + identity-check + allowlist contract. This DEC owns the **resolution** (which mode applies to this PR) and the **human path** (who is assigned, how the gate is satisfied).

This DEC and DEC-028 land as a coherent pair. Either may accept independently; both are required for `done-work` to evaluate the gate when mode resolves to `agent`.

## Decision

The pm capability ships a **review-mode configuration** in `project/config.yaml` and a **per-issue label override** system. Two modes are supported at v1, with three layers of override resolution per PR.

### Two modes

| Mode | Approval path | Reviewer selection |
|---|---|---|
| **`agent`** (default) | Designated agent's verdict comment (per [project-management:DEC-028-agent-as-approver-paths]) | No human reviewers auto-assigned; the registered agent reviews. |
| **`human`** | DEC-026's three-way OR (APPROVED review / `Approved`-prefix comment / `--bypass`) | Members of `members.yaml` whose `role:` matches the configured `reviewer_role:` are auto-assigned as PR reviewers (excluding the author). |

Mode names are `agent` and `human` (not `solo` and `human-review`) because the choice is about which kind of reviewer satisfies the gate, not about team size. A multi-member team can use `agent` mode for efficiency; a solo developer can use `human` mode if they have an out-of-band reviewer.

Agent is the default because:

- It covers solo developers and proof-of-concept teams without configuration friction.
- Multi-member teams that *prefer* agent review opt in by leaving the default; teams that *require* human review opt in explicitly with `mode: human`.
- Per-issue overrides give fine-grained control where the project default is wrong for a specific change.

### Three-layer override resolution

Each PR's effective mode is resolved by precedence (highest wins):

| Layer | Where | Effect |
|---|---|---|
| **Layer 1: project default** | `review.mode:` in `project/config.yaml` | Sets the floor; applies to every PR unless overridden. |
| **Layer 2: per-issue label** | `review:human` or `review:agent` label on the issue | Forces this issue's mode regardless of project default. |
| **Layer 3: per-invocation flag** | `review-work --require-human` on the invocation | Forces human mode for this invocation. |

`done-work --bypass "<reason>"` remains the ultimate override — bypasses the gate entirely with an audited reason, regardless of resolved mode. The audit comment (`Approved by bypass: <reason>`) is the trail.

If Layer 2 (label) and Layer 3 (flag) conflict (e.g. issue is labelled `review:agent` but the operator invokes with `--require-human`), the flag wins — Layer 3 represents the operator's most recent intent. The DEC does not refuse the conflict because Layer 3 may be a deliberate one-off (the issue's persistent label remains for future PRs on the same issue; only this invocation is overridden).

### Config shape

```yaml
# .pkit/capabilities/project-management/project/config.yaml
review:
  mode: agent                             # agent | human (default: agent)

  # Used when resolved mode == human
  human_review:
    reviewer_role: Implementer            # which role auto-assigned as reviewers
                                          # values: any role defined in DEC-021's members.yaml
                                          # (v1 enum: PM | Implementer per DEC-021)
```

The `review.agents.*` config block (registered agents, allowlist) lives in DEC-028, which owns the agent-as-approver mechanism. This DEC needs no agent-specific config.

### Label namespace

One new label namespace, fitting the existing `<namespace>:<value>` pattern:

- `review:<mode>` — forces resolved mode for this issue. Values: `human`, `agent`.

### Human path: role-based reviewer assignment

When the resolved mode is `human`:

1. `review-work` queries `members.yaml` for members whose `role:` matches `review.human_review.reviewer_role:`, excluding the PR author.
2. The matched members are assigned as PR reviewers via `gh pr edit --add-reviewer`.
3. The gate is satisfied via DEC-026's three-way OR (APPROVED review or `Approved`-prefix comment from any non-author identity, or `--bypass`).

Per [project-management:DEC-021-team-membership-gate]'s v1 enum, `role:` is a single string (`PM | Implementer | (none)`). The query is a single-string equality match against the configured `reviewer_role:`. List-valued roles and free-text role taxonomies are out of v1 scope; if multi-role-per-member or project-defined role vocabularies recur, a future DEC refines DEC-021 per COR-007.

If the role-based query returns zero eligible reviewers (no team member with the configured role, or the only matching member is the author), `review-work` warns but proceeds — assignment is best-effort. `done-work`'s gate may still be satisfied via `Approved`-prefix comment from any non-author identity (someone who isn't an auto-assigned reviewer but reads the PR and approves).

### Refusal when human-mode-required-but-no-signal

`done-work` refuses to merge when the resolved mode is `human` and the gate has no valid signal:

```
[refused] Human review required but no approval signal present
            → resolved mode: human (source: <project default | label `review:human` | --require-human flag>)
            → no `APPROVED` review on the PR
            → no `Approved`-prefix comment from a non-author identity
            → Remediation:
                a) wait for a reviewer to approve
                b) remove the human-required override (label / flag) if mistakenly set
                c) merge with `done-work --bypass "<reason>"`
```

The symmetric refusal in `agent` mode is defined by DEC-028 (it's about whether the agent's verdict is present, which is DEC-028's territory).

### Open mode and review-mode

When `members.yaml` is absent (DEC-021 open mode):

- Project default `review.mode:` still applies. Open mode does not force review-mode to any particular value.
- If resolved mode is `human`, `review-work` cannot auto-assign reviewers (no members.yaml). The gate is still satisfied via `Approved`-prefix comment from any non-author identity with repo access. This is acknowledged-permissive — open mode is "membership not configured", and the gate degrades gracefully rather than refusing operation.
- If resolved mode is `agent`, the agent path works as configured per DEC-028.

### Sub-decisions index

| Topic | Resolution |
|---|---|
| Default mode | `agent`. Minimum-friction adoption; teams that require human review opt in explicitly. |
| Mode override mechanism | Three layers: project config (Layer 1), issue label `review:<mode>` (Layer 2), command flag `--require-human` (Layer 3). |
| Layer 2 vs Layer 3 conflict | Layer 3 wins. The flag represents the operator's most recent intent; the label persists for future PRs on the same issue. |
| Label namespace | `review:<mode>` — fits the existing `<namespace>:<value>` label pattern (`type:`, `area:`, `priority:`). |
| Mode names | `agent` and `human`, not `solo` and `human-review`. The choice is about which kind of reviewer satisfies the gate, not about team size. |
| Role-based reviewer query | Single-string equality match: members where `role` == `reviewer_role`, excluding author. Per DEC-021's v1 enum (`PM | Implementer`). |
| List-valued or free-text roles | Out of v1 scope. Future DEC refines DEC-021 if multi-role-per-member or project-defined role vocabularies recur per COR-007. |
| Refusal when human-mode + no signal | `done-work` refuses with remediation pointer (wait, remove override, or `--bypass`). |
| Open mode + human mode | Best-effort assignment (no members.yaml to query); gate satisfied by any non-author `Approved`-prefix comment. |

## Rationale

**Why mode-as-config, not team-size-derived.** Earlier drafts of this DEC derived mode from team size (single-member = solo; multi-member = human-review). The reviewer feedback was that this conflates team configuration with review preference — they are independent. A multi-member team may genuinely prefer agent review (efficiency, routine work); a solo developer may want human review for sensitive changes (e.g., by asking a colleague offline and using `--bypass` with the offline-review reason). Config-driven mode separates these concerns and lets the project pick what fits its workflow.

**Why `agent` as default.** Two reasons:

- *Bootstrap cost*: a new project has no `members.yaml`, no `reviewer_role:` defined. Defaulting to `agent` + DEC-028's path means the methodology works out of the box for solo developers and proof-of-concept teams. `mode: human` is a deliberate opt-in, not a stumbled-into-friction.
- *Override safety*: per-issue and per-invocation overrides let the team escalate to human review for the cases that need it without changing the project default. The default doesn't have to be "the strictest" — strict-when-it-matters via override is enough.

**Why three layers of override (not two, not four).** Three layers cover the natural cases without compounding complexity:

- *One layer (project only)* — too coarse; can't say "this specific issue needs human review".
- *Two layers (project + per-issue label)* — covers most needs but leaves no per-invocation hatch for one-offs (a critical PR that happens to need human review but the issue wasn't marked).
- *Three layers (project + label + flag)* — covers per-project default, per-issue persistent override, and per-invocation one-off. The flag is rare; the label is the common per-issue case.
- *More than three* — workstream-level overrides, milestone-level overrides, type-based overrides — were considered and deferred per COR-007. Per-label and per-flag cover the recurrent cases; add more layers only on observed recurrence.

**Why labels (not body markers) for Layer 2.** Labels are first-class GitHub objects, filterable in the UI, already used by the methodology for typed classification (`type:*`, `area:*`, `priority:*`). Adding `review:*` fits the existing pattern. Body markers (like the existing `Integration:` line) are unsearchable in the UI and require parsing the issue body.

**Why role-based reviewer assignment (not by-name or round-robin).** By-name assignment in config is brittle (people leave teams; config has to be updated). Round-robin is fairer but adds state (who reviewed last) that the methodology shouldn't carry. Role-based is the right axis: declare *what kind* of reviewer the project wants, let `members.yaml` map people to roles, and let the query resolve. When a person leaves, removing them from `members.yaml` removes them from the reviewer pool automatically.

**Why single-string role at v1 (against DEC-021's existing enum).** DEC-021 v1 commits to `role:` as a single optional string with the `PM | Implementer` enum. The role-based reviewer query in this DEC works against that v1 shape. List-valued roles and free-text role vocabularies are real future enhancements but require schema refinement to DEC-021 — and per COR-007's recurrence test, we wait for observed need (a project that genuinely has `developer / lead / frontend` etc. roles) before authoring that refinement.

**Why the conflict-between-Layer-2-and-Layer-3 resolves to Layer 3 wins, not refusal.** The flag is the operator's most recent intent — possibly a one-off "this PR specifically needs human review even though the issue isn't normally that strict". Refusing on conflict would force the operator to either change the persistent label (heavy) or drop the flag (defeats the intent). Layer 3 wins keeps the persistent label intact for future PRs on the same issue and respects the current invocation's intent.

### Alternatives considered

- **Team-size-derived mode (single-member = solo; multi-member = human-review).** Rejected. Conflates team configuration with review preference. A multi-member team that prefers agent review can't express it via team-size-derived; config-driven gives that flexibility.

- **Single review mode per project, no per-issue overrides.** Rejected. Too coarse. The recurrent case "most PRs use agent; some need human" can't be expressed without per-issue override.

- **Body markers (`Review: human` line in issue body) instead of labels for Layer 2.** Rejected. Labels are searchable/filterable in the GitHub UI; body markers aren't.

- **Mode names `solo` / `human-review`.** Rejected — `solo` is misnamed for the multi-member-team-prefers-agent case. Reviewer feedback called this out. `agent` / `human` are accurate and shorter.

- **List-valued or free-text roles in `members.yaml`.** Deferred per COR-007. The v1 single-string enum from DEC-021 covers the v1 mechanism; multi-role-per-member or free-text vocabularies wait for observed need.

- **Refuse on Layer 2 / Layer 3 conflict instead of Layer 3 wins.** Rejected. The conflict is normal operational behaviour, not an error — the operator is making a per-invocation override of a persistent label. Refusal would force heavy remediation for a routine case.

- **Workstream-level or milestone-level override (Layer 4+).** Deferred per COR-007. Per-label and per-flag cover the observed cases; add more layers on recurrence.

- **Default mode = `human`** (safer default; multi-member teams get human review unless they opt out). Rejected. Bootstrap cost is the dominant factor at v1: a fresh project shouldn't require `members.yaml` + `reviewer_role:` configuration before `done-work` works. `agent` default + per-issue / per-invocation overrides cover the security-sensitive cases. The default biases toward "works out of the box"; sensitivity is opt-in.

## Implications

- The pm capability extends `project/config.yaml` with the `review:` block above. No new schema file is introduced at v1 — `pre-check.py` validates the new block alongside its existing checks. A formal config schema may follow as a separate decision when other capabilities or methodology-wide schema vocabularies converge.
- The pm capability gains the `review:<mode>` label namespace. The kit-shipped label vocabulary documented in [project-management:DEC-012-classification-axes] is extended (no separate schema file at v1).
- `review-work` extended: resolves mode (Layer 3 → 2 → 1); in `agent` mode, defers to DEC-028's mechanism; in `human` mode, queries `members.yaml` by `role:` and assigns matched reviewers.
- `done-work` extended: queries the resolved mode; checks the appropriate gate (DEC-028's agent path OR DEC-026's three-way OR for human path).
- Existing DEC-026's reviewer-assignment section is updated to defer to this DEC for mode resolution. DEC-026's `done-work` approval-gate row notes that the gate's structure is mode-conditional rather than three-way-OR-with-extension.
- v1 implementation: single-string role matching against DEC-021's existing enum. No schema bump to DEC-021 at v1.
- **Acceptance gate** (per `.pkit/rules/core.md` rule 2): this DEC lands as `proposed`. Promotion to `accepted` is a separate gesture. Implementation work citing this DEC is forbidden until acceptance. DEC-027 and [project-management:DEC-028-agent-as-approver-paths] land as a coherent pair; either may accept independently. DEC-026 must accept before either of these — they build on its three-way OR.
- **Universal-applicability flag for methodology review**: the three-layer override pattern (project default → per-issue label → per-invocation flag) is potentially universal — release management, incident management, and other capabilities with mode-resolved gates may want the same shape. COR-007's recurrence test should fire on second-instance use; the pattern can promote to a kit-level COR at that point. Flagged here for future maintainers.
