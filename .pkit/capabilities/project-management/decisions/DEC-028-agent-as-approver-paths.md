---
id: DEC-028
title: Agent-as-approver — remote bot identity or locally-invoked kit agent satisfies `done-work` in agent mode
status: accepted
date: 2026-05-27
author: Ales Kalfas
---

## Context

[project-management:DEC-027-review-modes] establishes review modes (`agent` default, `human` opt-in) with three-layer per-PR override resolution. It defines *which mode applies* but defers *how an agent counts as approval* to this DEC.

When the resolved mode is `agent`, `done-work`'s gate cannot rely on human review (no human reviewer is auto-assigned in agent mode). The methodology needs a concrete mechanism for "this agent's review counts as approval".

Two execution paths cover the real-world cases:

- **Remote path**: an agent with its own GitHub identity (bot account, GitHub App, CI service account) reviews out-of-band — fired by webhook, GitHub Action, or scheduled job. Posts the verdict via its own identity.
- **Local path**: a kit-shipped or project-shipped agent (e.g., a Claude Code agent under `.claude/agents/`) is invoked on the developer's machine — typically as part of the standard workflow. Posts the verdict via the user's gh credentials.

The remote path is the lower-friction *operational* path (no developer involvement after setup; fully autonomous loop closure). The local path is the lower-friction *adoption* path (no GitHub App / bot account setup needed; leverages the kit's existing `.claude/agents/` deployment surface).

The mechanism has to answer:

1. **What is the approval signal?** A comment? A review? Something parseable and recognised.
2. **Whose signal counts?** Anyone? A specific identity? A list of identities? Different per path?
3. **What prevents self-approval?** The whole point of an approval gate is an external signal.
4. **What if the signal goes stale (new commits invalidate it)?**

This DEC settles all four for both paths, **singleton at v1** (one remote agent OR one local agent OR both — but no multi-agent pipelines yet). Multi-agent review pipelines (N agents in sequence) are deferred per COR-007 until a second specialist-agent use case appears.

This DEC builds on DEC-027's mode resolution and on DEC-026's `done-work` gate. DEC-026 and DEC-027 must accept before DEC-028 can accept (the cite-graph is one-directional: DEC-028 → DEC-027 + DEC-026, not bidirectional).

## Decision

In `agent` mode (per DEC-027), `done-work`'s approval gate is satisfied when **a registered reviewer agent has posted an `APPROVED` verdict comment on the PR, post-dating the latest commit, via either the remote path (bot identity) or the local path (user attestation of locally-run agent)**.

This adds a fourth path to `done-work`'s approval-gate OR in `agent` mode (the other three are still available: APPROVED review, `Approved`-prefix comment from non-author human, `--bypass "<reason>"`).

### The verdict signal

The agent posts a PR comment whose **first line** carries an uppercase verdict, with `Reviewer agent:` prefix. Two verdicts at v1:

| Verdict | Effect |
|---|---|
| `Reviewer agent: APPROVED` | Satisfies `done-work`'s gate in `agent` mode. |
| `Reviewer agent: CHANGES_REQUESTED` | Explicit "needs work" signal. Does not satisfy the gate. Informational signal to the author and to any reviewer-watching automation. |

The first line is the gate signal; the rest of the body (everything after the first newline) is **freeform commentary** — findings, summary, rationale, links. Example:

```
Reviewer agent: CHANGES_REQUESTED

Three findings:

1. `find_target_root` in `install.py` line 122 — `.git` should be tested with `.exists()` not `.is_dir()` to cover worktrees.
2. Tests at `tests/test_install.py` don't cover the worktree-no-git case.
3. The docstring on line 105 says "Mirrors the bash dispatcher" but the dispatcher hasn't been updated.
```

The verdict vocabulary (`APPROVED`, `CHANGES_REQUESTED`) matches GitHub's native PR-review state names — transferable mental model, and future migration from comment-based sentinels to actual `gh pr review` objects is mechanically straightforward (the verdict maps to the Review state).

A comment without the `Reviewer agent:` first-line prefix is implicitly informational commentary — no special verdict needed. Comments from the agent without the prefix do not affect the gate.

### Two paths, two registration lists

The project declares registered agents in `project/config.yaml`:

```yaml
review:
  agents:
    # Remote path — agents with their own GitHub identity (bot, App, service account)
    remote_registered:
      - github_login: claude-bot          # the agent's GitHub identity
                                          # (additional fields may be added later)
    # Local path — kit-shipped or project-shipped agents under .claude/agents/
    local_registered:
      - name: reviewer                    # matches `.claude/agents/reviewer.md` (default, shipped by this capability)
      - name: code-review                 # matches `.claude/agents/code-review.md` (adopter-authored)
```

Both lists are optional; at least one path must have at least one entry for the agent gate to be satisfiable. At v1 **both paths may be populated** — a project that wants belt-and-suspenders (bot for autonomous flow + local agent for developer-at-keyboard) configures both. When both paths are populated, the gate is satisfied if **either path's component-of-the-gate is satisfied** (the natural OR composition).

Within each path, the list is **singleton** at v1 — exactly one entry per populated list. If more than one entry appears in either list, validation refuses with "v1 supports one agent per path; multi-agent pipelines are not yet specified".

The **strict-composition** question (when both paths are configured, should the gate require *both* to approve? prioritise one over the other? defer to the more-rigorous?) is deferred to a future DEC per COR-007 — the OR default works without requiring lived evidence on which strictness rule matches adopter intent. Adopters who need stricter composition today can configure only one path until the future DEC settles the question.

(`review.agents.registered:` was the v0 field name; the rename to `remote_registered:` distinguishes the two paths.)

### Path 1: Remote agent (bot identity)

When a remote-registered agent reviews, it posts the verdict comment using its own GitHub identity (bot account, GitHub App installation, service account). The verdict satisfies the gate via **identity match + author exclusion**:

- Comment first line exactly `Reviewer agent: APPROVED`.
- Comment author matches `review.agents.remote_registered[0].github_login`.
- Comment author is **not** the PR author (author-exclusion enforced).
- Comment timestamp post-dates the latest commit.

The remote path's invocation is **adopter-managed** — the kit does not ship the bot; adopters wire their own via GitHub Action, webhook, or external service.

### Path 2: Local agent (kit-invoked)

When a local-registered agent reviews, it runs on the developer's machine via a kit-shipped command (see "Invocation commands" below). The agent's output is posted as a PR comment by the **developer's** gh identity, with a structured attestation indicating the local path:

- Comment first line exactly `Reviewer agent (local, <name>): APPROVED` — where `<name>` matches an entry in `review.agents.local_registered:`.
- Comment author is the developer who ran the local command (typically the PR author in a solo workflow).
- **Author-exclusion is relaxed** for the local path — the developer attests they ran the agent and is taking responsibility for the verdict.
- Comment timestamp post-dates the latest commit.

The local path's *trust model* is the same as DEC-026's `--bypass "<reason>"`: the developer attests via the kit command that they ran the agent and accepts the verdict; the comment records what was attested; the kit does not verify what actually happened. The *mechanisms* differ (`--bypass` posts a single audit comment at merge time with a freeform reason; `review-pr` posts a structured verdict comment before merge with `APPROVED` or `CHANGES_REQUESTED` + freeform commentary) — but the same honor-system trust posture applies. The honor-system aspect is acknowledged — see Rationale.

The local-registered name `<name>` must (a) appear in `review.agents.local_registered:` AND (b) correspond to an actual file at `.claude/agents/<name>.md` (or wherever the harness deploys agents). The kit command refuses to invoke a registered name that has no corresponding file (and vice versa: an agent file not in the registered list is not invoked).

### Invocation command (local path)

The local path has a single entry point:

- **`review-pr <N>`** — invokes all locally-registered agents against the PR's diff. Each agent runs in parallel; each posts its verdict comment under the developer's identity. Re-runs are idempotent: post-dating-latest-commit invalidates prior verdicts automatically (see "Stale-verdict handling" below).

`review-pr` is a new verb-subject command added to the pm capability, fitting DEC-020's verb-subject convention (verb=`review`, subject=`pr` — `pr` is an established entity per DEC-020's verb-subject set). It is **not** part of DEC-026's seven-command lifecycle palette — DEC-028 introduces `review-pr` as a sibling addition to DEC-020's verb-subject set. DEC-026's `review-work` is unchanged by this DEC.

The standard developer flow:

1. `start-work <N>` — branch + assignee
2. (work, commits)
3. `review-work <N>` — open PR, mark ready, assign human reviewers if `human` mode
4. **`review-pr <N>`** — invoke local agents (if `agent` mode and any are registered)
5. (fix findings if `CHANGES_REQUESTED`; push; re-run `review-pr`)
6. `done-work <N>` — merge

`review-work` and `review-pr` are deliberately separate commands. `review-work` is a fast, deterministic state-transition wrapper (per DEC-020's verb-subject performance profile); `review-pr` is a potentially-long-running LLM invocation. Folding the LLM call into `review-work` would make the transition wrapper slow and non-deterministic — strain the methodology-as-executable-commands philosophy. Keeping them separate preserves DEC-020's performance contract.

The two commands share the `review` verb across different subjects (`work` for the lifecycle wrapper, `pr` for the agent-invocation command). The asymmetry is deliberate: `review-work` operates on the work-in-progress (issue + branch + assignee context per DEC-026); `review-pr` operates on the pull request as a methodology entity (per DEC-020's `pr` subject). Reading them together: "mark the work ready for review" (`review-work`) precedes "run the agent review on the PR" (`review-pr`).

The `done-work` refusal template (see below) names `review-pr` as the remediation when the agent gate isn't satisfied — closing the discoverability gap that automatic invocation would have addressed.

**`review-pr` in `human` mode (per DEC-027).** The command runs regardless of resolved mode — it's a tool, not a gate-satisfaction trigger. In `human` mode, the verdict comments are informational (pre-flight checks the developer wants before requesting human review); the gate is DEC-026's three-way OR and ignores the local-path verdict format. A developer in `human` mode who runs `review-pr` and sees `CHANGES_REQUESTED` fixes the findings and re-runs before requesting human review — but `done-work`'s gate path doesn't change. This makes `review-pr` useful in both modes: gate-satisfying in `agent`, advisory in `human`.

### Multi-local-agent composition

When `review.agents.local_registered:` lists N local agents (v1 caps at 1; future v2 may extend), the gate semantics are **all-must-approve**:

- All N local agents must post `Reviewer agent (local, <name>): APPROVED` post-dating the latest commit.
- If any local agent's most recent verdict is `CHANGES_REQUESTED`, the gate is not satisfied via the local path.
- The agents run in parallel during `review-pr`; ordering is implementation-detail.

At v1 (singleton), all-must-approve trivially reduces to the single agent's verdict.

### CHANGES_REQUESTED behaviour

`CHANGES_REQUESTED` verdicts are observed and surfaced in operational diagnostics (e.g., `done-work`'s refusal message names them) but do not block in a separate way — the gate fires on **absence of fresh APPROVED**, not on presence of `CHANGES_REQUESTED`. An author who pushes a fix doesn't need to mark the prior verdict resolved; the agent's fresh re-review (manual via `review-pr` or automatic via remote path) produces a new verdict line.

The gate-checker uses **latest-by-timestamp per agent** among verdicts post-dating the latest commit. If an agent has multiple fresh verdicts (e.g., the developer re-ran `review-pr` and the agent's second invocation disagreed with its first — possible for non-deterministic LLM calls), the most recent verdict wins. A fresh `CHANGES_REQUESTED` after a fresh `APPROVED` means the agent's current opinion is "needs work"; the gate doesn't satisfy until a newer `APPROVED` exists.

### Gate-checker algorithm

The pm capability's `done-work` runs the algorithm:

1. Determine which paths are configured (either or both of `remote_registered:` and `local_registered:` non-empty).
2. Find all PR comments with first line matching the verdict shape of any configured path — `Reviewer agent: APPROVED` (remote) or `Reviewer agent (local, <name>): APPROVED` (local).
3. **Remote path filter**: author matches `review.agents.remote_registered[0].github_login` AND author is not the PR author.
   **Local path filter**: `<name>` matches an entry in `review.agents.local_registered:`. No author-exclusion check.
4. Filter to comments post-dating the latest commit.
5. **Latest-per-agent**: among comments passing steps 2–4, take the latest by timestamp per agent identity (remote) or per `<name>` (local). If that latest is `APPROVED`, the agent's path-component is satisfied; if it's `CHANGES_REQUESTED`, not satisfied.
6. **Per-path satisfaction**: the remote path is satisfied if the remote agent's component is satisfied (singleton at v1). The local path is satisfied if every local agent in `local_registered:` has a satisfied component (multi-local all-must-approve; trivial at v1 singleton).
7. The gate is satisfied if **any configured path is satisfied** (OR composition across configured paths).

When only one path is configured, step 7 reduces to "that path's satisfaction". When both are configured, the OR-composition is the v1 default; strict-composition rules defer per COR-007.

### Stale-verdict handling

A verdict's freshness is tied to the latest commit. New commits invalidate prior verdicts — the gate-checker only accepts `APPROVED` verdicts post-dating the most recent commit on the PR.

This handles the common cycle: agent reviews, posts `APPROVED`; author pushes a fix; the prior `APPROVED` is now stale; agent must re-review and post a fresh verdict (remote path: triggered out-of-band; local path: developer runs `review-pr` to re-invoke).

The `back-to-draft` cycle (per DEC-026) explicitly dismisses prior `APPROVED` GitHub reviews; it does **not** dismiss the verdict comments (comments are informational; the timestamp predicate above already invalidates a verdict that predates new commits, which is what `back-to-draft` is reacting to).

### Allowlist as attestation, not security

The `review.agents.remote_registered:` and `review.agents.local_registered:` allowlists are the project's **attestation** that these identities / names are trusted to satisfy the approval gate. They are not security controls in the cryptographic sense:

- An adopter with repo write access can add an identity to either list by editing `project/config.yaml`. Anyone who can push to `main` can modify the allowlists.
- The local path's relaxation of author-exclusion makes the honor-system aspect explicit: the developer attests they ran the agent and accepts the verdict. A malicious developer could post the structured comment without actually running the agent. The kit doesn't prevent this; the comment records what was claimed, and the developer bears the same responsibility as for a `--bypass "<reason>"` invocation.
- The actual server-side enforcement of "who can merge" is GitHub branch protection (CODEOWNERS, required reviewers, required status checks). The allowlists do not interpose between a malicious actor with repo write and a merge.
- What the allowlists *do* prevent: an honest mistake (a random identity posting `Reviewer agent: APPROVED` by accident or as a joke; a developer typing a non-existent local agent name), a typo in agent setup, an unregistered identity / name satisfying the gate.

Adopters who need cryptographic guarantees configure GitHub branch protection with required-reviewer constraints layered on top of this DEC's mechanism. The methodology provides the attestation surface; server-side security is out of scope here.

### Refusal when agent-mode + no APPROVED verdict

`done-work` refuses to merge when the resolved mode is `agent` and the gate has no valid `APPROVED` verdict on either path:

```
[refused] Agent approval required but no valid APPROVED verdict present
            → resolved mode: agent (source: <project default | label `review:agent`>)
            → remote registered: <github_login or "(none)">
            → local registered: <name(s) or "(none)">
            → no fresh APPROVED verdict post-dating commit <sha>
            → most recent verdicts on this PR:
                - remote (<github_login>): <APPROVED (stale) | CHANGES_REQUESTED | none>
                - local (<name>): <APPROVED (stale) | CHANGES_REQUESTED | none>
            → Remediation:
                a) wait for the remote agent to post APPROVED (or trigger it manually)
                b) run `review-pr <N>` to re-invoke the local agent(s)
                c) merge with `done-work --bypass "<reason>"`
                d) if no agent is configured, set `review.mode: human` or merge with --bypass
```

When the most recent verdict is `CHANGES_REQUESTED`, the refusal message surfaces that fact — the developer knows there are findings to address before re-review will produce `APPROVED`.

### Sub-decisions index

| Topic | Resolution |
|---|---|
| Two execution paths | Remote (bot identity) and local (developer attestation of locally-run agent). Project may use either or both. |
| Verdict format — remote path | First line: `Reviewer agent: APPROVED` or `Reviewer agent: CHANGES_REQUESTED`. Body below is freeform commentary. |
| Verdict format — local path | First line: `Reviewer agent (local, <name>): APPROVED` or `Reviewer agent (local, <name>): CHANGES_REQUESTED`. `<name>` matches `review.agents.local_registered:` entry. Body below is freeform commentary. |
| Verdict vocabulary at v1 | `APPROVED` (satisfies gate) and `CHANGES_REQUESTED` (does not satisfy gate). Matches GitHub native PR-review state names for transferable mental model. |
| Comments without the prefix | Implicitly informational. Do not affect the gate. |
| Remote-path identity check | Author matches `review.agents.remote_registered[0].github_login` AND author is not the PR author. |
| Local-path identity check | Author-exclusion **relaxed** — the developer attests they ran the agent. The local agent name must be in `review.agents.local_registered:` AND a file must exist at `.claude/agents/<name>.md`. |
| Freshness | Verdict must post-date the latest commit on the PR. Both paths. |
| Multi-local-agent composition | All-must-approve — every locally-registered agent must have a fresh APPROVED verdict for the gate's local path to satisfy. At v1 (singleton), trivially reduces to one agent. |
| Number of registered agents at v1 | At most one remote, at most one local. Multi-agent pipelines deferred per COR-007. |
| Invocation command (local path) | `review-pr <N>` is the sole entry point. The developer invokes it after `review-work` (and after any subsequent fix-push cycle). `review-work` is unchanged by this DEC. |
| Allowlist framing | Attestation, not security. The local path's relaxation of author-exclusion is explicit honor-system; the developer takes responsibility. |
| Stale verdict from prior commit | Ignored by the gate-checker (timestamp predicate). Re-invoke (remote: out-of-band; local: `review-pr`) to produce a fresh verdict. |
| `back-to-draft` interaction | Does not dismiss verdict comments; the timestamp predicate handles staleness automatically. |
| Refusal when agent-mode + no fresh APPROVED | `done-work` refuses with remediation pointer (wait for remote, run `review-pr`, bypass, or switch mode). |

## Rationale

**Why a comment sentinel (not a review, not a label).** Three reasons:

- *Reviews require write authority to a specific GitHub permission level* that not every agent identity has. Comments require only repo-comment permission, which is a lower bar.
- *Labels are heavyweight for transient approval signals* — they persist on the issue/PR until explicitly removed, and don't carry timestamps cleanly. Comments do.
- *Comments are streams the methodology already uses for audit trails* (DEC-026's `Promoted`, `Approved`, `Handoff` comments). The sentinel fits the existing pattern.

**Why first-line-exact-match (not whole-body-exact-match or arbitrary regex).** A whole-body-exact-match (where the comment is *only* `Reviewer agent: APPROVED` with nothing else) conflates the *gate signal* with the *commentary*: findings the agent wants to surface require a separate comment with a different shape. First-line-exact-match separates them cleanly — the first line is the signal (machine-parseable, auditable at a glance), the rest of the comment is the explanation (free-form, human-readable). Anyone scanning the PR thread sees the verdict line and knows the state; anyone wanting detail reads on.

**Why GitHub-aligned verdicts (`APPROVED` / `CHANGES_REQUESTED`).** Three reasons: (a) the vocabulary is already in adopters' mental models from GitHub's native PR review — no new terminology to learn; (b) the verdicts map 1:1 to GitHub Review states (`APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`, `DISMISSED`), so future migration from comment-based verdicts to actual `gh pr review` objects is a mechanical change with no semantic shift; (c) "REJECTED" was considered and rejected as too terminal — `CHANGES_REQUESTED` correctly signals "iterate, don't abandon".

**Why two verdicts at v1 (not three, not just one).** GitHub natively supports four review states (`APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`, `DISMISSED`). For v1, only `APPROVED` and `CHANGES_REQUESTED` carry verdict semantics. `COMMENTED` is unnecessary — any comment without the `Reviewer agent:` prefix is already implicitly commentary. `DISMISSED` doesn't apply to comments (it's a transition on a GitHub Review object). Two verdicts cover the gate-relevant cases; the third (commentary) is absence-of-verdict.

**Why singleton (one remote, one local) at v1.** Per COR-007's recurrence test: zero specialist-agent use cases exist today. No kit-shipped reviewer agent produces the verdict yet; no project has two reviewer agents in use. Pinning a multi-agent contract before single-agent observation is premature abstraction. The v1 singleton mechanism per path is forward-compatible — the list shape of both `remote_registered:` and `local_registered:` permits future extension.

**Why two paths (remote + local), not one.** The two paths serve distinct adoption modes. The remote path is the *operational* path — fully autonomous, no developer involvement after setup, supports CI-driven workflows and closes the autonomous-feature-delivery loop. The local path is the *adoption* path — leverages the kit's `.claude/agents/` deployment surface that's already configured for any Claude Code-using project, requires no GitHub App installation or service-account creation, fits the developer-at-the-keyboard workflow. Shipping only the remote path would force every adopter to set up a bot (high friction for solo developers and exploratory projects); shipping only the local path would block fully autonomous workflows. Both paths together cover the real-world spectrum.

**Why relax author-exclusion for the local path (the honor-system trade-off).** The local agent runs on the developer's machine and posts the verdict using the developer's gh credentials. The developer is also the PR author in solo workflows. Strict author-exclusion would reject every local-path verdict; the path would be useless in its primary use case.

The relaxation is structurally equivalent to DEC-026's `--bypass "<reason>"`: the developer signals via the kit command that they are taking responsibility for the merge, with the comment as the recorded reason. The local path adds two constraints over a raw `--bypass`:

- **A structured shape** — the comment must match the `Reviewer agent (local, <name>):` format and uppercase verdict. Manually fabricated verdicts are at least *visible as such* in the PR thread (a verdict comment without a corresponding `review-pr` invocation log entry is detectable on inspection).
- **A registered-name constraint** — the agent name must appear in `review.agents.local_registered:` AND have a deployed agent file at `.claude/agents/<name>.md`. The developer can't claim a verdict from a nonexistent agent.

Beyond those, the kit does not verify that the agent actually ran or that its output matches the verdict claimed. The honor-system aspect is essential to the local path; concealing or overstating it would mislead adopters about what guarantees the gate provides.

Adopters who need stronger guarantees layer GitHub branch protection on top — required-reviewer constraints on `main` enforce server-side checks that the local path cannot satisfy alone. The methodology's responsibility is to provide the *attestation surface*; the *enforcement floor* is the substrate's job.

The honor-system relaxation is provisional at the capability level: the pattern "kit-invocation grants developer-attestation that substitutes for identity-based author-exclusion" is methodology-level by shape (it would recur in any capability that invokes agents on the developer's machine to satisfy a gate). Per COR-007, when a second capability adopts the same shape, the principle should promote to a kit-level COR that captures the trust model uniformly. Flagged in Implications for future maintainers.

**Why `review-pr` is the sole local-path entry point (no auto-invocation in `review-work`).** Two reasons:

- *Performance contract*: DEC-020's verb-subject command surface is implicitly fast and deterministic. Folding LLM calls into `review-work` would make a state-transition wrapper potentially-multi-minute and non-deterministic — strain the philosophy. `review-pr` is the explicit slow-command entry point; the developer knows what they're signing up for when they run it.
- *Failure isolation*: an LLM call failing (rate limit, timeout, network error) shouldn't fail the state transition. Keeping `review-pr` separate means `review-work` always exits cleanly regardless of LLM availability; the developer runs `review-pr` independently and handles failures there.

The "discoverability gap" concern (developer forgets to run `review-pr` after `review-work`) is closed by `done-work`'s refusal template: when `done-work` is invoked without a valid local-agent verdict, the refusal names `review-pr` as the remediation. The developer cannot accidentally skip the local-agent review and still merge.

**Why all-must-approve for multi-local-agent composition.** When N local agents are registered, each represents a specialist concern the project decided matters (e.g., a security checker plus a code-quality reviewer). Any-approves semantics would let a passing-but-unrelated agent satisfy a gate the project explicitly wanted N concerns checked for. All-must-approve preserves the project's stated review surface. (At v1 N=1, so the rule is moot operationally; the contract is pinned for future N>1 extension.)

**Why identity-check on the comment author.** Without it, anyone with repo-comment permission could post `Reviewer agent: APPROVED` and satisfy the gate. The identity match limits the signal to the configured agent. The combination of (a) identity-match and (b) author-exclusion prevents both impersonation (a random commenter pretending to be the agent) and self-approval (the PR author posting as themselves).

**Why allowlist-as-attestation (not allowlist-as-security).** The allowlist file is project-side and adopter-editable. A malicious actor with repo write can modify it. Calling it "security" overstates what it provides; the real security boundary is GitHub branch protection (server-side, not adopter-modifiable). The attestation framing is honest about what it guarantees: "this identity is the one the project agreed to trust", subject to the project's own access controls.

**Why timestamp-post-dates-latest-commit (not other freshness rules).** Three alternatives considered:

- *No freshness check* — would allow a sentinel posted in PR week 1 to satisfy a merge in week 4 after substantial changes. Defeats the gate.
- *Post-date a specific marker (e.g., last `review-work` invocation)* — depends on a methodology event that isn't always invoked. Some PRs may bypass `review-work`.
- *Post-date the latest commit* (chosen) — uses the substrate's most-recent change as the freshness boundary. Any new commit invalidates the prior sentinel, forcing re-review.

**Why no separate `--require-agent` flag in DEC-027.** DEC-027's Layer 3 has `--require-human`. There's no symmetric `--require-agent` because the agent path is the default; an operator who wants agent review uses no flag (and the default kicks in). If the project default is `human` and the operator wants agent for this invocation, they can flip the issue label (`review:agent`) per Layer 2 — but per-invocation agent-override is a rare enough case that a flag isn't worth shipping.

### Alternatives considered

- **Multi-agent pipelines (named ordered chains) at v1.** Rejected — no recurrence; premature per COR-007. Future DEC pins the pipeline contract when a second specialist-agent use case appears. The singleton mechanism here is forward-compatible (the list shape of `registered:` extends without breaking).

- **Verdict line includes the agent name in the remote path (`Reviewer agent (<name>): APPROVED`).** Rejected *for the remote path only*. The remote path's identity-check on the comment author already disambiguates the agent (the GitHub author metadata is authoritative); baking the name into the remote-path body would be redundant and create two sources of truth. The **local path includes the name in the body necessarily** — when multiple local agents are registered, all post under the same developer's identity, so the body name is the only disambiguator. The asymmetry is intentional: remote-path uses author metadata, local-path uses comment-body marker; whichever source is authoritative for the path is the disambiguator.

- **Use a GitHub Review object (not a comment) as the sentinel.** Rejected. Reviews require specific GitHub permissions some bot identities don't have; the comment-based mechanism works for any identity with repo-comment permission. Reviews are also coupled to the PR's diff state in ways that make "fresh review after commit" semantics more complex than the simple timestamp check.

- **Allow the PR author to post the sentinel if it matches a kit-known agent signature.** Rejected. Defeats the identity check. The author-identity exclusion is what makes the path different from self-approval.

- **No allowlist; any non-author identity posting `Reviewer agent: APPROVED` counts.** Rejected. Without the allowlist, a random commenter (or a stale CI bot, or a misconfigured workflow) could trivially satisfy the gate. The allowlist makes "which agents count" explicit and version-controlled.

- **Allow multiple registered agents per path; any of them satisfies the gate.** Rejected at v1 — the question of "do all of them have to approve, or any one?" depends on the project's review surface (specialist agents typically should all approve; redundant general-purpose agents typically any-approves). The multi-agent extension defers per COR-007 until concrete patterns emerge. Singleton-per-path at v1; the all-must-approve rule is pinned for future multi-local extension.

- **Remote-path only — no local path at v1.** Rejected. The local path is the lower-friction adoption path for solo developers and exploratory projects; requiring a bot setup for every agent-mode adoption is a friction cliff. The two paths cover distinct workflows; shipping both at v1 is small marginal cost over the remote path alone.

- **Local-path only — no remote path at v1.** Rejected. The remote path is required for the autonomous-feature-delivery loop (no developer at the keyboard). Without it, agent mode can't run fully autonomously. The two paths together cover both adoption modes.

- **Strict author-exclusion for the local path (no honor-system relaxation).** Rejected. Strict author-exclusion would reject every local-path verdict in solo workflows (the developer is both the runner and the PR author). The local path would be unusable in its primary use case. The honor-system trade-off is acknowledged and bounded by the structured comment shape + registered-name constraint; adopters who need stronger guarantees layer branch protection.

- **Local agents register only via `.claude/agents/` filesystem presence (no separate config allowlist).** Rejected. Filesystem-only registration means any agent file in `.claude/agents/` could satisfy the gate — including agents the project hasn't reviewed or approved. The dual requirement (registered AND deployed) makes the project's review surface explicit in config.

- **Auto-invoke local agents in `review-work` (after the PR opens).** Rejected. Folding LLM calls into `review-work` would make a fast state-transition wrapper potentially-multi-minute and non-deterministic, straining DEC-020's verb-subject performance profile. It also extends DEC-026's `review-work` contract from another DEC — an architectural smell. v1 ships `review-pr` as an explicit separate command; the developer chooses when to incur the LLM-call latency.

- **Auto-invoke local agents on `after_open_pr` hook (per DEC-024).** Considered as a way to keep `review-work` fast while still automatically firing agents on PR creation. Deferred — adopters who want auto-invocation can wire it themselves via DEC-024's `custom-script` hook kind invoking `review-pr`. A kit-shipped default hook is an additive future option once DEC-024's hook surface and the `review-pr` mechanism both stabilise.

- **Freshness via last `review-work` invocation, not last commit.** Rejected — depends on a methodology event that isn't always invoked. Commit timestamp is the substrate-authoritative freshness signal.

## Implications

- The pm capability extends `project/config.yaml` with `review.agents.remote_registered:` and `review.agents.local_registered:` (each a list of at most one entry at v1). `pre-check.py` validates the singleton-per-path constraint and verifies that every `local_registered:` name has a corresponding file at `.claude/agents/<name>.md`.
- `done-work` extended: when resolved mode is `agent` (per DEC-027), the gate-checker query runs the seven-step algorithm above. If satisfied via the configured path(s), merge proceeds; if not, the refusal template fires.
- The pm capability gains a new `review-pr` verb-subject script at `.pkit/capabilities/project-management/scripts/review-pr.py`. It fits DEC-020's verb-subject convention (verb=`review`, subject=`pr` — `pr` is an established entity); it is sibling to DEC-026's seven-command lifecycle palette, not a member of it. `review-work` is unchanged by this DEC.
- `review-pr <N>` reads `review.agents.local_registered:`, validates each name against `.claude/agents/`, dispatches each agent in parallel against the PR's diff, captures verdicts, and posts each as a comment in the local-path format under the developer's gh identity.
- **Local-path default reviewer agent.** The pm capability ships a default `reviewer` agent at `.pkit/capabilities/project-management/agents/reviewer.md` (per COR-026 — discipline-implying agents live in the capability that ships the discipline). Adopters who configure `local_registered: name: reviewer` get the kit-shipped default; adopters may also replace or add to it with their own agents under `.claude/agents/` (subject to v1's singleton-per-path constraint). The reviewer agent's body emits the local-path verdict format and applies the capability's conventions (Conventional Commits, branch/type alignment, classification axes, surface-change discipline). The remote path ships no default — bot identity, GitHub App, or service-account setup is adopter-managed. The methodology specifies the contract; the local-path agent implementation is now kit-shipped via this capability, the remote-path agent implementation is adopter-side.
- DEC-026's `done-work` approval-gate row is mode-conditional after this DEC lands: in `human` mode, the three-way OR per DEC-026; in `agent` mode, the remote-or-local agent paths from this DEC plus `--bypass`.
- v1 ships singleton-per-path support. Multi-agent pipelines are a future DEC after COR-007 recurrence; the all-must-approve rule for multi-local is the contract that future extension will inherit. The list shapes of `remote_registered:` and `local_registered:` are forward-compatible — extending each to lists of N agents is additive, not breaking.
- **Acceptance gate** (per `.pkit/rules/core.md` rule 2): this DEC lands as `proposed`. Promotion to `accepted` is a separate gesture. Implementation work (the gate-check algorithm, the config schema fields, the refusal template, `review-pr.py`) is forbidden until acceptance. **DEC-026 and DEC-027 must both accept before DEC-028 can accept** — the cite-graph is one-directional (this DEC depends on both, not vice versa).
- **Universal-applicability flag for methodology review**: "designated agent satisfies an authorisation gate via attested comment" is a pattern potentially reusable across other capabilities (decision-record acceptance, release management, incident management — anywhere an approval gate exists). Both paths (remote bot identity, local user attestation) have the same universal shape. COR-007's recurrence test should fire on second-instance use; the pattern may promote to a kit-level COR at that point. Flagged here for future maintainers.
