# ADR-002: Frozen-build correctness — resource seam and build-identity cache key

- Status: Accepted
- Date: 2026-06-20

**In one minute:** freezing the CLI into a one-file exe breaks two assumptions the source code silently relied on — that package data is a real file on disk, and that `__file__` points at readable source. We fix both with a single frozen-aware resource seam (`resources.py`) that every package-data consumer must go through, and by keying the output cache on a baked *build identity* (version + stamp) when frozen instead of hashing module source. A CI smoke test runs the actual exe, because these failures are invisible to the source test suite.

## Context

The application is pure-Python and runs fine from a checkout, but ships as a PyInstaller one-file executable (see ADR-001). A freeze changes two things the running code had implicitly assumed:

1. **Package data is no longer a real directory on disk.** Under a freeze the package's files are unpacked under PyInstaller's `_MEIPASS`, and `importlib.resources.files()` returns a `Traversable` that is not guaranteed to be a filesystem path. Any consumer that hands a *path* to an API which opens files by name breaks. There are at least three such consumers of the same hazard: the bundled Charis SIL fonts (reportlab's `TTFont` opens by filename, in `pdf.py`), the notes JSON Schema (`validation.py`), and pdfminer's cmap data.

2. **`__file__` no longer points at readable source.** The output cache (`report.py`) keyed freshness partly on hashing the `.py` source of the modules that produce an artifact — giving fine-grained invalidation in a checkout (edit `ingest.py`, dependent artifacts rebuild). A frozen build has no `.py` on disk, so that source hash is impossible there, and a naive fallback would let two different builds collide on a stale cache.

Both failures share a property that makes them dangerous: **they are invisible to the source test suite.** Every test passes from a checkout; the breakage only appears in the frozen exe a user runs.

## Decision

**One frozen-aware resource seam.** `resources.py` is the single place that knows how to reach package data, frozen or not. It exposes `package_path(*parts)` (a context manager yielding a real `Path` via `importlib.resources.as_file()`) and a `read_text` convenience. Every consumer that needs a real path routes through it rather than calling `importlib.resources` directly. Because `as_file()` may extract to a temporary location that is cleaned up when its `with` block exits, all file work happens inside the block. Fonts are the one consumer whose registered path must **outlive** the block (reportlab holds the path and reads it later, at render time), so fonts are materialised into a **process-lifetime temp directory** rather than a block-scoped one. (pdfminer locates its own cmap data internally, so the only obligation there is the build config bundling it via `--collect-data pdfminer` — there is no runtime call to make.)

**The output cache keys on build identity when frozen.** `build.py` defines a build identity as `"<version>+<stamp>"` — the baked `__version__` plus a build stamp (a git SHA or timestamp written into a generated, git-ignored `_build_stamp.py` at freeze time, defaulting to `"dev"`). When `sys.frozen`, `report.py` keys the output fingerprint on this identity instead of hashing module source. Version alone is insufficient: two nightly builds can share version `0.2.0` yet carry different code, and the stamp is what breaks that collision. Dev checkouts keep source-hashing, preserving fine-grained "edit this module, rebuild that artifact" invalidation where it is both possible and useful.

**A CI smoke test exercises the real exe.** Because both hazards are invisible to the source suite, CI builds the frozen exe and runs it — at minimum a load plus a Charis-font PDF render (the path that exercises the resource seam end to end) — so a regression in the freeze surface fails the build rather than reaching a user.

## Consequences

- **A new package-data consumer has one correct path and one wrong one.** It must go through `resources.py`; calling `importlib.resources` (or worse, `__file__`-relative path math) directly reintroduces the frozen hazard. The seam's module docstring states this; reviewers should enforce it.
- **Anything holding a resource path past a function return must use the process-lifetime materialisation**, as fonts do. A block-scoped `as_file()` path handed to a consumer that reads it later is a latent frozen-only bug.
- **The build stamp is load-bearing for cache correctness in frozen builds.** If a release process forgets to bake `_build_stamp.py`, two same-version builds fall back to identity `0.2.0+dev` and can collide on a stale cache. The packaging process (`tn.spec` / the stamp step, documented in `docs/PACKAGING.md`) owns this; it is a release-checklist item, not a code-path guard.
- **The frozen smoke test is the only thing standing between a freeze-surface regression and the user.** It must run on every release build and should grow to cover each new resource consumer as one is added. Treating it as optional reopens the exact invisibility this ADR exists to close.
- **The cache key is intentionally coarser in frozen builds.** A frozen user gets whole-build invalidation, not per-module — acceptable because a frozen user does not edit individual modules between runs, which is the only scenario fine-grained hashing serves.
