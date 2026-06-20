# ADR-001: Distribution and self-upgrade trust model

- Status: Accepted
- Date: 2026-06-20

**In one minute:** trustworthy-notes ships as an unsigned Windows exe that downloads and replaces itself. We accept GitHub-over-TLS as the only trust root (no code signing, no second anchor), and we make the self-replacement physically incapable of leaving the user without a working exe. The published checksum guards against a corrupted download, not against a malicious one. The upgrade is always user-initiated (a one-tap nudge), never silent, and the version check never runs on the pipeline's hot path.

## Context

trustworthy-notes is delivered to a single, non-technical Windows user as one **unsigned** one-file PyInstaller executable (`tnotes.exe`), downloaded from the public GitHub Releases page — no GitHub account, no installer, no Python. The same exe **self-upgrades in place**: `tnotes upgrade` pulls the latest published build and replaces the running executable, and a launch-time nudge offers the upgrade when a newer release exists (`updater.py`).

This combination — unsigned, self-downloading, self-replacing — is the exact behavioural signature of malware, and Windows SmartScreen and antivirus will flag it. That is a foreseeable cost of the chosen distribution shape, not an accident, so the trust model has to be stated deliberately rather than assumed.

The forces in tension:

- **Zero-friction delivery for one trusted, non-technical user** versus the cost and ceremony of an EV code-signing certificate (annual cost, identity verification, signing infrastructure) whose only beneficiary here is that one user.
- **A genuinely useful in-place upgrade** versus the risk that a botched or interrupted self-replacement bricks the only copy of the tool the user has.
- **Convenient "you're out of date" prompting** versus the AV blast radius of an exe that silently rewrites itself over the network, and versus any network dependency creeping onto the pipeline's hot path (which must stay runnable offline).

## Decision

**The trust root is GitHub plus TLS, and nothing else.** The updater fetches release metadata and assets from `api.github.com` / `github.com` over HTTPS and trusts the platform-validated certificate chain (`updater.py`). We explicitly **do not** defend against a compromised release pipeline or a malicious GitHub account: an attacker who can publish a forged release can forge everything we would check. The published `tnotes.exe.sha256` is therefore an **integrity guard against a corrupted or truncated download**, not a second trust anchor — it catches the realistic failure (a partial download) that TLS does not, and is deliberately not treated as a security boundary.

**The in-place swap is fail-safe by construction.** The order is fixed: download to a temp file beside the target → verify the published SHA-256 → verify the downloaded exe is *launchable* (`<exe> --version` exits clean) → only then swap. The swap respects the Windows constraint that a running exe can be renamed but not overwritten: rename the live `tnotes.exe` → `tnotes.exe.old`, move the verified new exe into the freed name, and roll the `.old` back if the move fails. The stale `.old` is swept on the next launch (`cleanup_stale`, called from `cli`). Every failure path raises `UpgradeError` *before* the live exe is touched, so a failed or interrupted upgrade always leaves exactly the working build the user started with.

**Upgrades are user-initiated, never silent.** The launch-time check only *reports* that a newer version exists; the CLI then offers a one-keypress upgrade, and only when there is an interactive TTY. A silently self-rewriting unsigned exe would multiply the AV blast radius and remove the user's agency over what code runs; a one-tap nudge keeps the human in the loop with negligible friction.

**The version check never touches the pipeline hot path.** The check is frozen-only, opt-out (`TNOTES_NO_UPDATE_CHECK` / config), cached so at most one network call happens per day, bounded by a short (3 s) timeout, and swallows every error. A slow or unreachable GitHub costs only a missed nudge — never a hang and never a failed pipeline command. This realises the network-posture invariant recorded in `docs/ARCHITECTURE.md` (the pipeline commands touch the network only for the Anthropic extract calls they already make; `updater` is an isolated module the pipeline never imports).

## Consequences

- **SmartScreen "More info → Run anyway" is expected on first launch**, and possibly after each upgrade. For a single trusted user this is a one-time, explainable speed bump; it is documented in the user-facing release notes rather than engineered away.
- **Code signing is deliberately deferred.** If the audience ever widens beyond a single trusted user — broader distribution, an untrusted recipient, or AV false-positives that block use — an EV certificate (and re-signing each release in CI) becomes the right next step. Revisit this ADR at that point; the trust root would change from "GitHub + TLS" to "our signing identity."
- **The checksum's role must not be over-read.** Because it is published in the same place as the exe, it adds no protection against a malicious release. Future maintainers must not mistake it for one (e.g. by treating "checksum verified" as "exe trusted"). The launchable-before-swap gate, not the checksum, is what protects the *user's working install*.
- **The Windows running-exe swap is validated last, on real hardware.** The rename/move/cleanup dance is authored and unit-tested on macOS with mocked I/O; the file-locking semantics that make it necessary are Windows-only, so the first real validation is `tnotes upgrade` on Windows against a published release. This is a known validation gap carried deliberately, not an oversight.
- **No network on the pipeline hot path is now an invariant**, enforced by module isolation (the pipeline never imports `updater`) and recorded in `docs/ARCHITECTURE.md`. A future change that reaches for the network inside a Wave 0–4 command contradicts this ADR.
