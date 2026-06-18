# Packaging tnotes as a one-file executable

`tnotes` ships as a pure-Python CLI, but a one-file [PyInstaller](https://pyinstaller.org)
build lets someone run it with no Python install. This note covers how to produce
that build and the three things that make a freeze of `tnotes` correct rather than
broken-at-runtime.

## Build it

The build toolchain lives in the `build` dependency group, kept out of `dev` so a
plain test run doesn't pull it. Bake the build stamp (see below), then freeze:

`python scripts/stamp_build.py && uv run --with pyinstaller pyinstaller tn.spec`

Output is a single executable at `dist/tnotes`. Smoke-test it:

`./dist/tnotes --help`

The spec (`tn.spec`) is the source of truth; the equivalent flag form is:

`uv run --with pyinstaller pyinstaller --onefile --name tnotes --collect-data trustworthy_notes --collect-data pdfminer --copy-metadata jsonschema src/trustworthy_notes/__main__.py`

## Why a naive freeze breaks, and what the spec does about it

A frozen one-file build has no source tree on disk: the package's files are
unpacked under a temporary `_MEIPASS` directory at launch, and only what the spec
*tells* PyInstaller to bundle comes along. Three `tnotes` concerns hit that wall.

1. **Bundled package data — fonts and the JSON Schema.** The Charis SIL fonts
   (`trustworthy_notes/fonts/`) and the notes schema (`trustworthy_notes/schemas/`)
   are data files, not imported modules, so a default freeze drops them. The spec
   pulls them in with `collect_data_files("trustworthy_notes")`. At runtime every
   consumer reaches them through the single seam in `resources.py`, which uses
   `importlib.resources.as_file()` to hand out a *real* filesystem path — needed
   because reportlab's `TTFont` opens fonts by filename and won't accept the
   `Traversable` that `importlib.resources.files()` returns under a freeze.

2. **pdfminer's cmap data.** pdfminer (under pdfplumber) reads character-map data
   files at runtime to decode text. Same story — data, not code — so the spec adds
   `collect_data_files("pdfminer")`. pdfminer finds these itself; there's no `tnotes`
   runtime call involved, only the bundling.

3. **jsonschema's metadata.** jsonschema discovers its validator classes through
   its installed-distribution metadata (entry points). A freeze omits `.dist-info`
   by default, so the discovery comes up empty and validation fails. The spec
   copies it in with `copy_metadata("jsonschema")`.

## The cache fingerprint under a freeze

The output cache (`report.py`) keys freshness partly on the code that produces an
artifact. In a checkout it hashes the relevant `.py` source for fine-grained
invalidation. There's no `.py` to hash in a freeze, so when `sys.frozen` is set it
keys on a **build identity** instead — `__version__` plus a build stamp (see
`build.py`). The stamp matters: two same-version frozen builds with different code
must not collide on a cache key, or the second build reads the first's stale cache.

### How the stamp gets baked

The mechanism is a generated module, not a hand-edited constant:

1. **`scripts/stamp_build.py`** writes `src/trustworthy_notes/_build_stamp.py`
   holding `STAMP = "<value>"`. The value is the current git short SHA
   (`git-<sha>`, with `-dirty` when the tree has uncommitted changes), or a UTC
   build timestamp (`build-<ts>`) when git isn't available, or whatever
   `TN_BUILD_STAMP` is set to (an explicit override wins).
2. **`build.py`** imports that module under a `try` and falls back to `"dev"` when
   it's absent — which it is in a clean checkout, since the file is generated and
   git-ignored. So a checkout reports `0.1.0+dev` (harmless there: source hashing,
   not the stamp, keys the cache in a checkout) and a freeze reports the baked SHA.
3. **`tn.spec`** names `trustworthy_notes._build_stamp` as a hidden import so the
   guarded import doesn't cause PyInstaller to drop the module from the freeze.

Run the script immediately before the freeze (the one-liner under "Build it" does
this). Skip it and the build still succeeds but ships `0.1.0+dev`.

> **For CI (#6):** the override point is the `TN_BUILD_STAMP` env var. The CI build
> job should set it (e.g. to the full release SHA or a tag) and then run the same
> freeze command; everything downstream — `build.py`, the spec, the cache key —
> already consumes it. No further wiring is needed in CI beyond exporting that var
> (or relying on the auto-detected git SHA, which also works in CI checkouts).
