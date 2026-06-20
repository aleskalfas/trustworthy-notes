# ADR-003: Feedback data-exfiltration boundary

- Status: Accepted
- Date: 2026-06-20

**In one minute:** the feedback feature uploads a reproduction bundle that contains verbatim copyrighted source excerpts — the most sensitive data the tool handles. We confine that exfiltration behind four boundaries: it goes only to a **private** repo, authenticated by a fine-grained token that is **never baked into the exe**; nothing leaves the machine without an explicit consent gate that shows the user the exact file list; every off-ramp falls back to a local file so feedback is never lost; and the module is **isolated from the pipeline**, which never imports it.

## Context

`tnotes feedback` lets a non-technical user — running the frozen exe, with no GitHub account — file a structured problem report. To be actionable, a report needs reproduction data, and the smallest thing that reproduces an extraction problem is the document's `.tnotes` per-page notes. Those notes contain **verbatim excerpts of the copyrighted source document** — the exact content that is git-ignored everywhere else precisely because it is sensitive. So this one feature does something nothing else in the tool does: it sends the user's most sensitive data off their machine.

Two hard constraints shape the design:

- **The artifact is public.** `tnotes.exe` is downloadable by anyone, so no credential — not even a scoped one — may live inside the binary. Anything baked in is effectively published.
- **The user has no GitHub account.** The credential and destination cannot come from the user's own identity; they must be provisioned out of band by the maintainer.

The risk being managed is data exfiltration: copyrighted excerpts leaving the user's machine, to the wrong place, without the user's informed agreement, or being silently dropped on failure.

## Decision

**Private destination, out-of-band credential.** Feedback with data goes to a **private** feedback repo, never the public code repo. Authentication is a **fine-grained personal access token** scoped to Issues + Contents on that one repo, stored in the user's config and delivered out of band (1Password) by the maintainer — **never compiled into the exe** (`feedback.py`; full design in the scratchpad note `2026-06-17-tn-feedback-design.md`). The repo path is read from config, not hardcoded. Because GitHub has no programmatic issue-attachment endpoint, the bundle is committed into the repo (Contents API, namespaced and timestamped to avoid collisions) and linked from the issue.

**A consent gate stands in front of every upload.** Before anything leaves the machine, the user is shown exactly what will be sent: the always-safe diagnostics (tool version, OS, their own message) **and the bundle's file list, explicitly flagged as containing verbatim excerpts of their source document** (`upload_preview`). A yes is required; a no falls back to local. The consent text is the real payload's file list, not a generic warning, so the user's agreement is informed.

**Every off-ramp lands on a local file.** When the repo/token is unconfigured, the user declines consent, the machine is offline, or the token is missing/expired (401), the report is written to a local `feedback-<timestamp>.txt` with the bundle beside it, and the user is told where it is and why (`write_local_fallback`, `run_feedback`). Feedback is never silently lost. The AI-structuring step degrades the same way: no key or a flaky model yields a raw-text report rather than a failure.

**Listing already-reported issues is a read-only inbound path, outside the exfiltration boundary.** The feedback flow also *lists* issues already filed in the private feedback repo, pulling maintainer-authored issue titles and bodies onto the user's screen (the existing `GitHubClient.get` / `GetFn` seam in `feedback.py`, currently declared but unused). This is **inbound** — data arriving at the machine, not leaving it — so it is not exfiltration, and the bright line above is untouched: there is still no baked credential, the destination is still the private repo, and the consent gate still stands in front of everything that *leaves*. The read path deliberately carries **no consent gate**, precisely because nothing departs the machine on a read. It must degrade exactly like the write path: offline, unconfigured, or a 401 yields a clear "couldn't list issues" message, never a crash of the windowless flow. And it stays *inside* `feedback.py` — it reuses the same seam rather than adding a new one — so the isolation invariant below holds unchanged.

**The feedback module is isolated from the pipeline.** The only dependency arrow is `cli → feedback`; the deterministic Waves 0–4 never import it. This keeps the pipeline runnable with zero network and zero second-credential surface, and it means the data-exfiltration path is a single, auditable module rather than a concern smeared across the pipeline. This realises the network-posture invariant in `docs/ARCHITECTURE.md` (feedback is an isolated module the pipeline never imports).

## Consequences

- **The exfiltration surface is one reviewable module.** Auditing "what can leave the machine, and under what gate" means reading `feedback.py`, not tracing the whole pipeline. New code must not move upload logic out of this module or have the pipeline import it.
- **Token rotation is a maintainer operation, out of band.** An expired token surfaces as a clear 401 message ("ask the maintainer for a fresh one") and a local fallback, not a crash. The token's lifecycle lives with the maintainer's 1Password, not in the tool.
- **The consent text must keep tracking the real payload.** Its value is that it names the actual files being uploaded and flags them as verbatim excerpts. If the bundle contents ever change (e.g. someone adds the source PDF), the preview must change with it, or the consent stops being informed. This is a coupling to preserve deliberately.
- **The private repo is the trust boundary for the copyrighted data.** Anyone with read access to that repo can read uploaded excerpts. Access to it must stay as narrow as the maintainer; widening it widens who can see users' source material.
- **A baked credential is the one thing that breaks this model.** Because the exe is public, any future "convenience" that embeds the token — even scoped, even obfuscated — publishes it. This is the bright line of this ADR.
