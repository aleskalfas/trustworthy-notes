---
authors:
  - Aleš Kalfas <kalfas.ales@gmail.com>
started: 2026-06-17
---

# `tn feedback` — design note

> Status: design settled in a brainstorming session (2026-06-17); filed as
> Feature [#4] with implementation Task [#11], and a recording obligation in
> docs Task [#13]. This note consolidates the design for handoff to pkit.

## The question

How should a non-technical end user (running a frozen, unsigned `tn.exe` on
Windows, with **no GitHub account**) report a problem so that the maintainer
gets a structured report **with enough data to reproduce it** — without shipping
any credential inside the publicly downloadable binary, and without publishing
the user's private source material to the world?

## Forces

- **No account.** The end user has no GitHub login and we don't want to require
  one. So the usual "open an issue" path is closed.
- **Public distribution artifact.** The tool ships as a public, unsigned
  `tn.exe`. Anything baked into it is effectively published — so **no token may
  live in the binary**.
- **Reproduction needs data.** "It looks wrong on page 12" is useless without
  the document's extracted notes + the page. The maintainer wants the repro
  bundle attached.
- **The data is sensitive.** The `.notes` outputs contain *verbatim source
  excerpts* of copyrighted documents (they are git-ignored for exactly this
  reason). They must **not** land in a public repo.
- **Degrade gracefully.** The user may be offline, or a token may have expired.
  Feedback must never be silently lost.
- **Trust posture.** Introducing a second outbound credential and a data-upload
  path into a previously offline-capable CLI is a trust-domain change; it must
  be isolated from the deterministic pipeline.

## What is already known / decided

- The tool stores its Anthropic key in `~/.trustworthy-notes/config.yaml`
  (cleartext, user-profile-scoped) and has Claude already wired in — so an
  AI-assisted step is cheap to add.
- A fine-grained GitHub PAT can be scoped to **one repo, Issues + Contents
  only, with an expiry** — blast radius if leaked is "create/edit issues +
  commits on one private repo," instantly revocable.
- GitHub's REST API has **no direct "attach a binary to an issue" endpoint** —
  attachments are a web-UI convenience only. Programmatic attach = commit the
  file to the repo (Contents API) and link it.

## The settled design

### Flow

`tn feedback "page 12 export looks wrong"`:

1. **Identity (once).** First run asks the reporter's name (e.g. *Jana*) and
   stores it. Because the PAT authors *as the maintainer's account*, every
   report is tagged **"Reported by: \<name\>"** for attribution.
2. **Diagnostics.** Auto-capture version, OS, the last command, and any error /
   traceback.
3. **Repro bundle.** Zip the *referenced document's* `.notes` outputs + the
   specific page range (not the whole source PDF).
4. **AI-structure.** Claude (via the user's existing key) reframes the raw text
   + diagnostics into a clean title / summary / reproduction steps. **Raw-text
   fallback** if the call fails.
5. **File it.** Create an issue in a **private** feedback repo via the
   fine-grained PAT; commit the bundle into that repo and link it in the body.
6. **Confirm locally.** Show the user *"Sent — thanks, \<name\>."* The issue URL
   goes to the maintainer; the user never touches GitHub.

### Where feedback goes

A **separate private repo** (e.g. `trustworthy-notes-feedback`), **not** the
public code repo — because the bundle carries copyrighted source excerpts. The
PAT is scoped to *that* private repo only (Issues + Contents).

### Credential model

- Fine-grained PAT, single private repo, **Issues + Contents: write**, with an
  expiry.
- Belongs to the **maintainer's** account (simplest; leak ⇒ scoped to one
  private repo; revoke in one click).
- **Delivered out-of-band via 1Password** (like the Anthropic key) and stored in
  the user's local config — **never inside the exe.**

### Privacy / consent boundary

The bundle leaves the user's machine, so the user must **see and consent to
exactly what is uploaded** before it's sent. Diagnostics are always safe;
document excerpts require explicit acknowledgement.

### Fallback

If offline, or the token is missing / expired: **write a local `feedback.txt`**
(diagnostics + her text + a pointer to the bundle) and tell the user to send it.
An expired token degrades to "ping the maintainer for a new one." Feedback is
never lost.

### Isolation

`feedback` lives in its own module that the **pipeline never imports** — the
dependency arrow is `cli → feedback`, never `pipeline → feedback`. This keeps
the deterministic Waves 0–4 runnable with zero network and zero second-credential
surface.

## Alternatives considered and rejected

- **PAT baked into the exe.** Rejected — public artifact ⇒ published token.
  (The save was: deliver the PAT *separately* via 1Password, store locally.)
- **`mailto:` / local-file only (no GitHub at all).** Viable and the simplest,
  but loses auto-filing + repro-bundle attachment. Kept as the *fallback*, not
  the primary.
- **A serverless proxy the maintainer hosts** (Worker / Formspree) that files
  the issue server-side with a secret never shipped to the user. Architecturally
  cleanest for "no credential on the client," but infrastructure to stand up and
  keep alive. Deferred — revisit if PAT rotation becomes a burden or volume grows.
- **A throwaway/bot GitHub account for the user.** Cleaner attribution, but an
  extra account to manage. Rejected in favour of name-tagging on the
  maintainer's account.
- **Filing into the public code repo.** Rejected — would publish copyrighted
  source excerpts.
- **Opening the issue in the user's browser ("session on GitHub").** Doesn't
  work: private repo + no account ⇒ she can't view it. Replaced by the local
  confirmation; the maintainer gets the URL.

## Open questions

- **PAT expiry handling.** Detect 401/expired and surface a clear "ping the
  maintainer" message + always fall back to the local file. How proactively
  should the tool warn before expiry?
- **Bundle size / redaction.** Is the page-range + that document's notes always
  the right scope? Should the user be able to trim what's attached?
- **De-duplication.** Multiple reports of the same issue — leave as separate
  issues, or thread? (Probably out of scope for v1.)
- **Whether the proxy alternative should be the v2 target** once the trust-model
  ADR is written (see [#13]).

## Cross-refs

- Feature [#4] — "Send feedback into a private repo with `tn feedback`."
- Task [#11] — implementation (command + bundle + AI-structure + fallback).
- Docs Task [#13] — records the data-exfiltration boundary as an ADR.
