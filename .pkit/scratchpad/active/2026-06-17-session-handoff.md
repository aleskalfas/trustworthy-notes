---
authors:
  - Aleš Kalfas <ales.kalfas@apoco.com>
started: 2026-06-17
---

# Session handoff — trustworthy-notes (post folder-rename)

Continuation note for the next session, which opens in the **renamed** folder
`…/git-public/trustworthy-notes/`. Git history is intact (it lives in `.git/`,
which moved with the folder); only the previous Claude Code session was lost to
the rename — hence this note.

## Where things stand

- **Repo:** `github.com/aleskalfas/trustworthy-notes` (GitHub repo already
  renamed; `origin` URL updated). **Nothing pushed yet** — the remote is empty,
  so it has no default branch.
- **Local commits (2, unpushed):**
  - `38ba068` feat: initial import — trustworthy-notes (tn)
  - `cac417c` chore(pm): configure project-management for trustworthy-notes
- **Uncommitted:** `.pkit/permissions/project/sandbox-provenance.yaml` (auto-
  modified by sandbox-escape usage this session). Decide: commit or leave.
- **Identities are consistent now:** dist `trustworthy-notes`, CLI `tn`, import
  package `trustworthy_notes` (renamed from `summarizer`).

## Immediate next steps (do in order)

1. **Push** to set the default branch and unblock pm operations:

   `git push -u origin main`

   (Publishes code to the *public* repo. Sets `main` as default branch.)

2. **Re-run pre-check** — should now be fully green:

   `uv run --script .pkit/capabilities/project-management/scripts/pre-check.py`

   (The only failing check before the push was `default branch matches config`.)

3. **Start using gh issues** via the project-manager agent (this repo boots as
   `project-manager` by default). E.g. "file an EPIC for the core pipeline",
   "file a docs task for the README". The agent runs title/body/classification/
   validation/cascade through the methodology.

4. (Optional, still pending) nothing else — setup is otherwise complete.

## Key context / gotchas for the next session

- **project-management capability is configured and bootstrapped:**
  - Config: `.pkit/capabilities/project-management/project/config.yaml`
    (retargeted from project-kit's dogfood config to this repo).
  - **`gh.host` is pinned to `github.com`** because this machine's *ambient*
    `gh` default is `github.ibm.com` (IBM Enterprise). Without the pin, `gh api`
    calls (milestones, etc.) would hit the wrong host. Don't remove it.
  - Workstreams (`project/workstreams.yaml`): `ingest, extract, compose,
    validate, export, cli, methodology, infra` (pipeline domain areas).
    "development → adoption" is *milestone* sequencing, not a workstream.
  - **22 labels created** on GitHub: `type:*` (6), `priority:*` (3),
    `workstream:*` (8), `state:*` (5). Label-fallback mode (no Projects v2 board).
  - Review mode: `agent` with the kit `reviewer` agent registered; no remote bot
    → `done-work --bypass "<reason>"` is the solo escape hatch.
- **Running pkit scripts:** they are PEP-723 `uv run --script` files:
  `uv run --script .pkit/capabilities/project-management/scripts/<verb>-<subject>.py`
  (auto-provisions `ruamel.yaml`). pre-check is the hard gate on every pm op.
- **Sandbox quirks (this environment):**
  - `git commit`/`git push` need the **1Password SSH agent** → run with the
    sandbox disabled (the agent socket isn't reachable inside the sandbox).
  - `uv` and `gh` (network) also need the sandbox disabled — sandboxed `uv`
    panics in `system-configuration`, and network is allow-listed only to
    `api.github.com` / `api.anthropic.com`.
- **Generated data is git-ignored everywhere:** `*.notes/`, `data/*/`,
  `data/*.pdf`, `scans/`, `*.scan.png`, `pdf-page-*.txt`, `build/`, `dist/`.
  Test fixtures under `tests/fixtures/` stay tracked (project assets).

## What this session did (summary)

- **Transliteration fidelity:** the source sets Egyptological transliteration in
  a legacy non-Unicode "Transliteration" font (glyphs on ASCII/punctuation
  codepoints). Completed the font-scoped MdC→Unicode map in
  `trustworthy_notes/translit.py` (capitals `# % + * © @ $ ^` → `Ḫ S Ḏ Ṯ Ḏ Ḥ H̱
  Š`), re-extracted the whole document, recomposed, re-exported. Excerpts are now
  verbatim Unicode, not model-guessed.
- **PDF rendering:** switched the whole document to the **bundled Charis SIL**
  serif (`trustworthy_notes/fonts/`, SIL OFL) — full Unicode coverage (Egyptological
  signs, combining marks like `H̱`, Latin-Extended names like `Myśliwiec`). Removed
  the old per-glyph Helvetica+fallback machinery.
- **`tn book --no-citations`:** new flag → clean reading copy
  (`book.reading.md/.pdf`), strips `[s-N]` + the Notes & Sources appendix, no API.
- **Project hygiene:** initial commit; renamed project + GitHub repo
  (`trustworthy-summarizer` → `trustworthy-notes`); renamed import package
  (`summarizer` → `trustworthy_notes`); hardened `.gitignore`; squashed to a clean
  baseline; configured + bootstrapped the project-management capability.

## Superseded

- `2026-06-13-session-handoff.md` — the earlier (pre-rebrand) handoff. This note
  supersedes it for current state.
