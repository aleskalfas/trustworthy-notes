# trustworthy-notes (`tnotes`)

Turn a large document into **trustworthy notes**: small, typed, source-anchored
pieces of knowledge where every claim can be traced back to the exact place it
came from. Not summarization (compression) — a faithful, verifiable
re-representation. See `docs/METHODOLOGY.md` (the source of truth) and
`docs/ARCHITECTURE.md` (how it's implemented).

## Installation

You only do this once. Pick the section for your computer.

### Windows

There's nothing to build and no GitHub account needed.

1. Go to the project's **Releases** page on GitHub (the "Releases" link on the
   right-hand side of the repository page) and download **`tnotes.exe`** from the
   newest release.
2. Move `tnotes.exe` into a folder you can write to and will remember — for
   example `C:\Users\<you>\tnotes\`. (Avoid `C:\Program Files`; that folder needs
   administrator rights.)
3. Double-click it, or run it from a terminal (see Usage below).

**The first time you run it, Windows may show a blue "Windows protected your PC"
box.** This is normal and expected. It appears because the program isn't signed
with a paid certificate yet — not because anything is wrong with it. To continue:
click **More info**, then click **Run anyway**. Windows remembers your choice, so
it won't ask again.

### macOS / Linux

There's no prebuilt download yet; you install from the source code. The one-time
setup installs `uv` (a small tool that manages the install) if it's missing, then
installs the `tnotes` command. From the project folder:

```
bash scripts/bootstrap.sh
```

If you use [mise](https://mise.jdx.dev), the equivalent is `mise run bootstrap`.
Then **open a new terminal window** so the `tnotes` command is found, and
confirm it works:

```
tnotes --help
```

(The "Quick start" and "Platform" sections further down have the finer details —
the cross-platform core, the Windows source path, and alternatives.)

## Usage

### The one command you'll use most

Point `tnotes` at a PDF and it does everything, then writes the finished book
right next to the original file:

```
tnotes ./your.pdf
```

That produces **`your.tnotes.pdf`** beside `your.pdf` — a clean, readable book of
the notes. A few options change what you get:

```
tnotes ./your.pdf -p 1-30      # only pages 1–30  →  your.p1-30.tnotes.pdf
tnotes ./your.pdf --cite       # the anchored version: [s-N] markers + a Notes & Sources list
tnotes ./your.pdf --force      # regenerate from scratch (normally finished work is reused)
```

By default a re-run skips work that's already done, so if it stops partway you can
just run the same command again and it picks up where it left off. Use `--force`
when you want it to redo everything.

On **Windows** the only difference is how paths are written — use a Windows-style
path, e.g. `tnotes C:\Users\<you>\Documents\your.pdf`.

### One-time setup: connect to Claude

`tnotes` uses Anthropic's Claude to read your document, so it needs an Anthropic
API key once. Run:

```
tnotes auth set-key
```

It will ask you to paste your key (the typing stays hidden). The key is saved
privately in your home folder — never inside the project — and `tnotes` reuses it
from then on.

By default `tnotes` uses Claude **Sonnet** (`claude-sonnet-4-6`), a sensible,
cost-appropriate choice. If you'd rather use the premium model, set it once:

```
tnotes config set-model claude-opus-4-8
```

## Updating

On **Windows**, run:

```
tnotes upgrade
```

It checks the **Releases** page for a newer version and, if there is one,
downloads the latest `tnotes.exe`, verifies its published SHA-256 checksum, and
replaces your copy in place. The swap is fail-safe — an interrupted or failed
upgrade always leaves your current working copy untouched — and the download is
verified to launch before it is installed. If you are already up to date it says
so and does nothing. (You can still update by hand: download `tnotes.exe` from the
Releases page and replace your copy.)

**Trust model.** The trust root is GitHub over TLS: `tnotes upgrade` fetches the
release and its assets over HTTPS and trusts that connection. The published
SHA-256 is an integrity check — it guards against a truncated or corrupted
download — not a second trust anchor.

**Launch-time nudge.** When you run the Windows `tnotes.exe` and a newer release
exists, tnotes offers a one-keypress upgrade (`tnotes vX.Y.Z is available —
upgrade now? [Y/n]`); pressing Enter runs the same `tnotes upgrade` above, and
declining just continues with your command. The check is cached to at most once a
day, uses a short timeout, and fails silently — it never slows down or blocks your
work, and never runs in scripts/CI (it only prompts at a real terminal). To turn
it off, set `TNOTES_NO_UPDATE_CHECK=1` in your environment, or run
`tnotes config set-no-update-check true`.

On **macOS/Linux** you run from source, so there is no exe to swap; `tnotes
upgrade` says as much and tells you to `git pull`. Re-run the bootstrap from the
updated source.

## Quick start (one command)

> This section is the **from-source** install for contributors and the
> macOS/Linux path. Non-technical users on Windows should follow the
> [Installation](#installation) section above (download `tnotes.exe`) instead.

From the project root, run the bootstrap for your OS. It installs `uv` (if
missing) and the `tnotes` command — that's everything needed to be functional.

**If you use [mise](https://mise.jdx.dev) — same command on macOS *and* Windows:**
```
mise run bootstrap
```
(mise must be installed first; it then provides `uv` and installs `tnotes`.)

**Otherwise, run the bootstrap for your OS (no mise needed):**

macOS / Linux:
```
bash scripts/bootstrap.sh
```
Windows (PowerShell — built into Windows, nothing to install first):
```
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

Then **open a new terminal** (so your PATH refreshes) and connect to Claude:
```
tnotes auth set-key      # paste your Anthropic API key once
tnotes --help
```

> There is no single command that's identical on both macOS and Windows — the
> shells differ — so each OS has its own one-liner above. If `uv` is already
> installed, the cross-platform core is just `uv tool install --editable .`.
> A script can't refresh your *current* shell's PATH, hence the "new terminal"
> step (one time).

`mise`/`ant` are **not** required for this. They're only for the optional
account-login path (`tnotes auth login`); see Platform below.

## One command (the whole pipeline)

For the non-technical path, point `tnotes` at a PDF — no subcommand — and it runs
every stage end-to-end (extract → compose → export → book) and writes the finished
book beside the source:

```
tnotes INPUT.pdf                 # → INPUT.tnotes.pdf (clean prose reading copy)
tnotes INPUT.pdf -p 1-30         # just pages 1–30 → INPUT.p1-30.tnotes.pdf
tnotes INPUT.pdf --cite          # the anchored copy: [s-N] markers + Notes & Sources
tnotes INPUT.pdf --force         # regenerate every stage (default: skip finished ones)
```

Already-finished stages are skipped, so a re-run resumes where it left off (use
`--force` to redo everything). A single-section document (e.g. a paper with no
chapter headers) still produces a book — no flags needed. Connect to Claude once
with `tnotes auth set-key` first. For per-stage control, the subcommands below
remain available and unchanged.

## Usage (per-stage)

Wave 0 (ingest) and layout inspection are built; the extraction waves are in
progress. Useful commands now:

```
tnotes layout INPUT.pdf                 # classify every page: text / figure / table / blank
tnotes probe INPUT.pdf --pages 14-16    # dump the extracted text of chosen pages
tnotes render INPUT.pdf --pages 15 -o scans   # annotated scan PNGs (header/columns/footnotes)
tnotes extract INPUT.pdf                # extract notes from ALL text pages (needs auth)
tnotes extract INPUT.pdf --pages 14-17  # …or just a range — see output convention below
tnotes gap INPUT.pdf --pages 14         # §7.6 coverage report on already-extracted notes
```

`--pages` is optional: omit it and `tnotes extract` does every text page of the
document (figure / table / blank pages are skipped automatically, using the same
classification as `tnotes layout`). Pass a range to override that default.

### Choosing the model and effort

Every command that calls Claude (`extract`, `export`, `terms --build`,
`relations --build`, `dedup --adjudicate`) resolves which model and effort to use
in layers, most specific first:

1. an explicit `--model` / `--effort` flag on the command,
2. else a default you saved with `tnotes config` (below),
3. else the built-in defaults: model `claude-sonnet-4-6`, effort `low`.

So with nothing configured and no flag you get Sonnet at low effort — a
cost-appropriate default. The premium model stays one flag (or one config) away:

```
tnotes config set-model claude-opus-4-8   # use the premium model by default
tnotes config set-effort medium           # raise the default effort
tnotes config set-effort ''               # for models without an effort knob (e.g. haiku)
tnotes config show                        # show the resolved model/effort and where each comes from
tnotes extract INPUT.pdf --pages 14 -m claude-haiku-4-5 -e ''   # a flag overrides config for one run
```

These defaults are stored in the same `~/.trustworthy-notes/config.yaml` as your
API key (see Platform below); setting them never touches the saved key.

### Where generated files go

By default every artifact for a document lands in a **folder beside the PDF,
named after it** — `data/Foo.pdf` → `data/Foo.pdf.tnotes/`. The `.tnotes` marker is
required: a folder can't share a name with the source file, so we keep the full
filename and append it. One folder per document, never mixed.

Inside, outputs are grouped into **numbered wave folders** that mirror the
pipeline, so the folder reads in pipeline order:

```
Foo.pdf.tnotes/
  1-extract/    page-NNNN.notes.yaml            # Wave 1: per-page notes
  2-compose/                                    # Wave 2: chapter assembly (multi-stage)
    1-chapter-map/  chapters.txt
    2-stitches/     stitches.txt
    3-dedup/        dedup.txt, dedup-merges.yaml
    4-terms/        terms.txt, terms.yaml
    5-relations/    relations.txt, relations.yaml
    6-chapters/     chapter-NNN.notes.yaml       # the composed deliverables
  3-validate/   gaps.txt                        # Wave 3: coverage report
```

The `.txt` views are saved, human-readable, and shown instantly on re-run unless
their inputs change (`--force` regenerates). Override the location with `--out DIR`
(`--notes DIR` for `tnotes gap`/`chapters`/`stitches`). These folders are git-ignored —
they hold verbatim source excerpts.

## Platform

Pure-Python, no system binaries (no poppler/ghostscript/ImageMagick), so it's
designed to run on macOS, Linux, and Windows. The simplest, fully cross-platform
setup is the API-key path:

```
tnotes auth set-key      # paste your Anthropic API key once (stored privately in your home)
tnotes auth status       # confirm how tnotes will connect
```

The key is written to `~/.trustworthy-notes/config.yaml` — the same path on every
OS. That resolves to `/Users/<you>/.trustworthy-notes/config.yaml` on macOS,
`/home/<you>/...` on Linux, and `C:\Users\<you>\.trustworthy-notes\config.yaml`
on Windows. It lives outside the repo, so git never sees it. On macOS/Linux it's
`chmod 600`; on Windows it inherits the user-profile NTFS permissions, which
already restrict reads to your account. (As with any CLI credential — `aws`,
`gh` — a process running as *you* can still read it; use a scoped key with a
spend cap and rotate if exposed.)

`tnotes auth login` (use your Anthropic account instead of a key) relies on the
external `ant` helper and is most convenient on macOS; on Windows/Linux prefer
`tnotes auth set-key`. *(Windows ships as a prebuilt `tnotes.exe` on the Releases
page — see the Installation section above; the release build is verified by CI.)*

## Status

All pipeline waves are implemented — ingest (column-aware reading, running-header
stripping, layout classification + routing for text/table/figure/blank) → extract
→ compose → validate → export → book. v0.1.0 ships the one-command `tnotes <pdf>`
flow and a prebuilt Windows `tnotes.exe` on the Releases page. See the docs above
for the methodology and architecture.
