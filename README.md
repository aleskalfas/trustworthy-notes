# trustworthy-notes (`tnotes`)

Turn a large document into **trustworthy notes**: small, typed, source-anchored
pieces of knowledge where every claim can be traced back to the exact place it
came from. Not summarization (compression) — a faithful, verifiable
re-representation. See `docs/METHODOLOGY.md` (the source of truth) and
`docs/ARCHITECTURE.md` (how it's implemented).

## Quick start (one command)

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

## Usage (today)

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
`tnotes auth set-key`. *(Windows is supported by design but not yet verified on a
Windows machine — please report issues.)*

## Status

Wave 0 ingest is real (column-aware reading, running-header stripping, layout
classification + routing for text/table/figure/blank). The note-extraction
waves are under active design — see the docs above.
