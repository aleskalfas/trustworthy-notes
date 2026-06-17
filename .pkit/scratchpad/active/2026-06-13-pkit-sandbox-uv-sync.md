---
authors:
  - Aleš Kalfas <kalfas.ales@gmail.com>
started: 2026-06-13
---

# pkit CLI panics under a sandboxed harness (uv sync proxy probe)

> Escalation candidate for the **project-kit** repo. Discovered while using pkit
> inside an adopter project (`evidence-summarizer`) under Claude Code's macOS
> seatbelt sandbox.

## The question

How should the `pkit` CLI behave when invoked inside a harness sandbox that
denies the macOS SystemConfiguration mach service? Today it hard-panics on
every command, even purely local ones (`new scratchpad`, `status`, `version`).

## Symptom

Any `pkit <cmd>` run inside the sandbox aborts with a Rust panic from `uv`:

```
thread 'main2' panicked at .../system-configuration-0.6.1/src/dynamic_store.rs:154:1:
Attempted to create a NULL object.
thread 'main' panicked at .../uv-0.9.8/crates/uv/src/lib.rs:2432:10:
Tokio executor failed, was there a panic?: Any { .. }
```

Exit code 101. Happens for local-only commands too (`pkit version`,
`pkit status`, `pkit new scratchpad`), which need no network at all.

## Root cause

The launcher (`~/.local/bin/pkit`, the bash proxy = `.pkit/cli/pkit`) ends with:

```sh
exec uv run --quiet --project "$SOURCE_REPO" python -m project_kit "$@"
```

Plain `uv run` performs an implicit **sync** of the project-kit environment
before running. The sync constructs uv's HTTP client, which on macOS probes
system proxy settings via the SystemConfiguration `SCDynamicStore` API — a
`mach` lookup to `com.apple.SystemConfiguration.configd`. The seatbelt sandbox
denies that mach service, the `system-configuration` crate gets a NULL store,
and uv panics.

This is NOT a filesystem or network-host denial — those are configurable in the
harness sandbox allowlists and are already permitted. It is a mach-service
denial, which the harness sandbox does not expose a knob for.

## Evidence (all run inside the sandbox)

| Command | Result |
|---|---|
| `uv --version` | OK (0.9.8 Homebrew) |
| `uv run --no-sync python -c "print('ok')"` | OK |
| `uv run python …` (implicit sync) via pkit | PANIC |
| `UV_OFFLINE=1 pkit version` | PANIC (offline still builds the client) |
| proxy env cleared (`NO_PROXY=* ALL_PROXY= …`) `pkit version` | PANIC |
| `UV_NO_SYNC=1 pkit version` | **OK** → `pkit 1.67.0` |
| `UV_NO_SYNC=1 pkit status` | **OK** |

So the trigger is specifically the sync step's network-client construction.
Skipping sync (`UV_NO_SYNC=1` / `--no-sync`) avoids building the client and the
mach probe never happens.

## Workaround (in use now)

Prefix local commands with `UV_NO_SYNC=1`. Safe because the project-kit env is
already installed; sync is only needed when deps actually change.

## Candidate fixes for pkit (pick/refine upstream)

1. **Launcher passes `--no-sync` for local commands.** Classify the COR-004
   surface: local commands (`new`, `status`, `version`, `validate`, scratchpad
   transitions) `exec uv run --no-sync …`; only genuinely network commands
   (`sync`, `upgrade`, `init` pulling capabilities) use the syncing path. This
   makes pkit sandbox-friendly by default with no env-var ritual.
2. **Lazy sync.** `exec uv run --no-sync`; if the module import fails (env stale
   / missing), fall back to a syncing run. Keeps the fast path local.
3. **Prefer `uv tool install`.** PRJ-004 recommends `uv tool install` which puts
   a self-contained binary on PATH that doesn't re-`uv run` per invocation. This
   adopter's PATH `pkit` is the *bash proxy*, not the tool-installed binary — so
   the source-tree proxy path is the one biting here. Worth documenting that the
   proxy path is sandbox-hostile and steering adopters to the tool install.
4. **Upstream uv robustness.** uv arguably should not panic when SCDynamicStore
   is unavailable; it could fall back to no-proxy. File upstream, but pkit should
   not depend on that landing.

## Recommendation

Option 1 (command-classified `--no-sync`) is the cleanest pkit-side fix: it
makes the documented CLI surface work inside a sandbox out of the box, reserving
network (and thus a sandbox exception) for the commands that truly need it.

## Open questions

- Does the same panic occur on Linux harness sandboxes, or is it macOS-only
  (SCDynamicStore is macOS-specific)? Likely macOS-only, but the `--no-sync`
  fix is portable regardless.
- Should pkit set `UV_NO_SYNC` in the launcher env rather than passing the flag,
  to also cover any nested `uv run` calls the runtime itself makes?
