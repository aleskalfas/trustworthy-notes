---
id: DEC-021
title: Team membership gate — pm operations check a member list before mutating; open mode bootstraps; closed mode locks
status: accepted
date: 2026-05-24
author: Ales Kalfas
---

## Context

The capability's authority model today trusts the invoker. [project-management:DEC-008-pm-and-implementer-roles] distinguishes PM and Implementer roles for *what* operations are appropriate, but every command treats whoever runs it as authorised to do the role's work. The two evolving operation sets (the verb-subject scripts pinned by [project-management:DEC-020-methodology-as-executable-commands] and the prerequisite/setup/migrate trio from [project-management:DEC-017-prerequisites-bootstrap-migrate-discipline]) inherit the same trust model — anyone with repo access can invoke them.

This works for single-repo private projects where everyone with access is on the team. It fails for **public-org repos where many people have read or write access but only a subset of the team actually does project-management work**. Without a membership gate, anyone in the org can mediate the methodology — file structurally-wrong issues, mis-classify, mass-transition states, mis-shape titles. The methodology gets diluted; the team's signal weakens.

The user's framing captures the requirement: *"if there isn't yet [a member list] all can manage. If there is, just people from the list can work with project management; others should be added by someone from the list."* A first-member bootstrap (open mode → first add → closed mode), with self-add only while open, and adds via PR review by an existing member thereafter. The pattern has prior art in pm-workflow's **Quorum** convention — a maintained list of authoritative people; ops gate on membership.

A separate full design walk for the membership mechanism (canonical-from-main vs working-tree read, identity resolution across surfaces, removal authority, lockout recovery) is **deferred**. This DEC pins the principle and the v1 file shape; mechanism details land alongside the implementing PR.

## Decision

Every pm operation that mutates external state checks a project-side **`members.yaml`** file before proceeding. The check has two modes: open (the file is absent or empty — any invoker passes) and closed (the file lists ≥1 member — only listed members pass). The first member adds themselves while open mode applies; from that gesture forward the file is closed.

### File location and shape

The members file lives at **`.pkit/capabilities/project-management/project/members.yaml`** — project-side per the no-shared-files invariant, adopter-owned, committed to main, schema-validated against a kit-shipped `schemas/members.schema.json` companion.

V1 shape (per-entry shape may add fields later as needs surface; v1 commitments are below):

```yaml
schema_version: 1
members:
  - github_login: aleskalfas
    name: Ales Kalfas
    email: kalfas.ales@gmail.com
    role: PM                  # optional; PM | Implementer; default Implementer
    added_at: 2026-05-22
    added_by: bootstrap       # "bootstrap" for first member; GitHub login of adder otherwise
```

`github_login` is the canonical identity; `name` + `email` are present for multi-surface identity resolution and human readability. `role` is informational at v1 (DEC-008 already distinguishes the roles); enforcement of role-specific ops gating is out of v1 scope and follows COR-007 if the recurrence appears.

### Two modes; the predicate

- **Open mode** — `members.yaml` is absent, or present with an empty `members:` list. The predicate **passes for any invoker** with repo access. This is the bootstrap state.
- **Closed mode** — `members.yaml` is present with ≥1 member. The predicate **passes only if** the invoker's identity matches an entry. Non-members get a structured refusal:

  ```
  [refused] Membership required for `<verb> <subject>` operation
            → This repository is in closed mode (.pkit/capabilities/project-management/project/members.yaml has ≥1 entry).
            → Your identity (<github-login>) is not in the member list.
            → Remediation: ask an existing member to add you via `add-member.py`.
  ```

The predicate runs at script startup, before any other work. Membership is not re-checked mid-operation.

### Bootstrap: the first member self-adds

While open mode applies, anyone with repo access may run `add-member.py` to add themselves. The PR landing the first member entry is reviewable by anyone with repo access — there is no "existing member" to review it yet. From the moment the first entry lands on main, the repo is in closed mode, and subsequent member additions require an existing member's review on the adding PR.

The first member's `added_by:` field is the literal string `bootstrap` to mark the seed event.

### Membership change authority

- **Adding members** — an existing member authors the change (`add-member.py` stamps an entry; the actual landing is via PR). The PR requires review by ≥1 existing member who is not the author. The first-member exception above applies only when open mode applies.
- **Self-removal** — a member removes themselves; the change is reviewable by any other member.
- **Removing another member** — any member authors; the PR cannot be approved solely by the author.
- **Lockout recovery** — if all members are removed (legitimately or by accident), the repo re-enters open mode. Anyone with write access via GitHub's permissions can then edit the file directly and the cycle restarts.

The git history of `members.yaml` IS the audit trail; no extra audit machinery ships.

### Identity resolution

The predicate resolves the invoker's identity from three surfaces, in order:

1. **`gh api user --jq .login`** — primary; matches the methodology's GitHub-bound substrate from [project-management:DEC-003-github-bound-substrate].
2. **`git config user.email`** — fallback when `gh` is unavailable.
3. **Process-environment override** — `PM_INVOKER_LOGIN` reserved for CI / agent contexts where the natural sources don't apply; sourced from a CI secret or workflow input, never from user-controllable env.

`members.yaml` lists `github_login` + `email` per entry; the match is positive if any surface's resolved value matches any entry's corresponding field.

The detailed mechanics — canonical-from-main vs working-tree read, fail-open vs fail-closed on network errors, caching — are **deferred** to the implementing PR. The principle is: closed mode prefers the authoritative `members.yaml` as committed to main, with a sensible fallback the implementing PR makes explicit.

### Tooling surface

Three verb-subject scripts ship under [project-management:DEC-020-methodology-as-executable-commands]'s convention:

- `scripts/add-member.py` — stamp a new entry. Validates invoker is a current member (or that open mode applies). Writes the entry; commits to a working branch the user opens a PR from.
- `scripts/remove-member.py` — stamp the removal. Same constraints.
- `scripts/show-members.py` — read-only inspection; lists the current members + their roles.

All other verb-subject scripts gain a **membership predicate check at startup** — the first thing the script does after parsing args. Open mode bypasses; closed mode applies the closed-mode predicate above.

A shared library (`scripts/_lib/membership.py` or equivalent) holds the predicate so every script invokes the same implementation.

### Sequencing

The principle lands at **v0.3.0** as a stub: the predicate library + the file shape + the read-only check; bootstrap mode active by default. The management commands (`add-member.py`, `remove-member.py`, `show-members.py`) land alongside `create-issue.py` + `validate-issue.py` in v0.3.0 so the first verb-subject scripts have a complete authority story.

Cross-repo membership coordination (a `members_source:` field pointing at a central governance-repo file) is out of v1 scope; that interaction lives with the methodology-mesh design.

## Rationale

**Why a member list rather than relying on GitHub repo permissions.** GitHub permissions are coarse — `read`, `write`, `admin`, applied across the whole repo. Methodology authority is finer-grained: someone can have write access for code contributions without being authorised to mediate the methodology's issue lifecycle. A separate `members.yaml` lets the methodology declare its own authority surface without conflating it with code-write authority. It also makes membership *visible in main* — a reviewer can audit the team without invoking the GitHub API.

**Why open mode for empty / absent file.** Bootstrap chicken-and-egg: someone has to be the first member, and they cannot be approved by an existing member who does not yet exist. The empty-file-is-open convention lets the first member self-add. The cost is that an unconfigured repo has no methodology authority gate at all — but an unconfigured repo also has nobody on the team to be gated against, so the cost is theoretical until the first add.

**Why review-by-an-existing-member for closed mode.** Trust within the team is symmetric — any existing member's review is sufficient. Asking for quorum, role-specific approvers, or a separate review-agent at v1 is over-design before there's evidence the simple rule fails. COR-007 says wait for recurrence; promote to richer authority models if real cases demand them.

**Why role is informational at v1.** [project-management:DEC-008-pm-and-implementer-roles] already names PM vs Implementer as a role distinction in prose; encoding it in `members.yaml` makes the assignment visible. But gating role-specific ops (e.g., refusing EPIC filing from an Implementer) on the role field is a separate enforcement decision. Doing it at v1, before there's evidence of frequent role-confusion, risks codifying the wrong gates. The role field is present so the assignment is visible; enforcement is a future refinement.

**Why git history as the audit trail.** Every `members.yaml` change is a PR landing on main with author, reviewer, commit message, and date. Recreating that audit in a separate ledger duplicates state; trusting git history keeps the methodology lean.

**Why mechanism details are deferred.** The five questions left open — canonical-from-main vs working tree, fail-open vs fail-closed on network errors, identity resolution edge cases, removal vs deactivation, multi-repo central membership — each have legitimate trade-offs that benefit from being decided alongside the implementing PR's actual code, not in advance. The DEC pins the principle and the file shape; the implementing PR pins the mechanics.

### Alternatives considered

- **Rely solely on GitHub repo permissions.** Rejected — coarse-grained, not visible in main, conflates code-write authority with methodology authority.
- **CODEOWNERS file as the gate.** Rejected — CODEOWNERS gates code review, not methodology mediation. Different surface; mixing the two breaks both.
- **Quorum-of-N approval per pm operation.** Rejected at v1 — over-design before evidence. The capability's mutating operations land in PRs that already have review; per-op quorum is duplicate friction.
- **Role-strict gating (Implementer can't file EPICs).** Rejected at v1 — the role distinction is informational until recurrence proves the gate is worth the friction.
- **Bootstrap requires admin self-add via a privileged command.** Rejected — over-engineered for the chicken-and-egg case; open mode is simpler and visible.

## Implications

- **Every verb-subject script per DEC-020** invokes the shared membership predicate at startup. Open mode bypasses; closed mode refuses non-members with the closed-mode refusal template above.
- **The capability `version:`** bumps to v0.3.0 on the implementing PR (the stub + the three management scripts + the predicate library).
- **The `schemas/members.schema.json`** validates `members.yaml` against the shape above. Adding fields is a same-PR-as-surface-change discipline per [project-management:DEC-017-prerequisites-bootstrap-migrate-discipline]'s `schema_version` bump rule.
- **Bootstrap state is the install default** — a fresh `pkit capabilities install project-management` leaves `members.yaml` absent. First-time adopters use `add-member.py` to seed it; the first add is the moment the repo transitions to closed mode.
- **The project-manager** does not need to know membership — the verb-subject scripts enforce. If an agent runs on behalf of a non-member's chat session, the scripts refuse and the agent surfaces the refusal.
- **CI invocations** of verb-subject scripts authenticate as a service identity that is added to `members.yaml` like any other member, or set `PM_INVOKER_LOGIN` from a CI secret. CI is not exempt from the gate by design.
- **Cross-repo membership** (a shared `members.yaml` across a team's repos) is out of v1 scope; the cross-repo coordination of `members.yaml` content is in the methodology-mesh design's scope.
- **A future kit-level COR may generalise the membership pattern** if a second capability adopts an equivalent gate. Promotion follows COR-007.
