"""Command-line interface for tnotes (trustworthy-notes)."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from typer.core import TyperGroup

from . import __version__, config, ingest, workspace


def _force_utf8_streams() -> None:
    """Make stdout/stderr encode UTF-8, so non-ASCII output never crashes.

    Help text and reports contain non-ASCII (e.g. the ``→`` arrow). On Windows
    when stdout isn't UTF-8 — redirected/captured output, or a legacy cp1252
    console — Python's default codec raises UnicodeEncodeError trying to encode
    those characters, taking the whole process down (issue #26). Reconfiguring to
    UTF-8 up front avoids that. It runs for both entry points because both import
    this module: the ``tnotes`` console script (``cli:app``) and the frozen exe /
    ``python -m trustworthy_notes`` (via ``__main__`` importing ``cli``).

    Harmless on macOS/Linux (already UTF-8). Guarded so it's a no-op where
    ``reconfigure`` is unavailable (e.g. an already-wrapped stream, or pytest's
    captured streams).
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


_force_utf8_streams()


class _DefaultGroup(TyperGroup):
    """Route a bare PDF path (no subcommand) to the one-command orchestrator.

    Typer/Click resolve the first token as a subcommand; an optional positional on
    the group callback would instead *swallow* the subcommand name. So we keep the
    orchestrator as a hidden ``run`` command and, when the first token isn't a known
    subcommand (i.e. it's a file path), transparently prepend ``run`` — leaving every
    real subcommand to dispatch exactly as before.

    A bare invocation with *no args* normally falls through to Typer's
    ``no_args_is_help``. But a windowless launch (a Windows double-click of the exe,
    issue #33) has no args either, and dumping ``--help`` there is the wrong screen —
    so we intercept that one case in :meth:`parse_args` and show the onboarding
    screen instead. Every other no-args run is unchanged.
    """

    def parse_args(self, ctx, args):
        # Only a *windowless* bare launch (double-click, no PDF, no subcommand) is
        # diverted to onboarding; a normal terminal `tnotes` with no args still gets
        # Typer's help. is_windowless_launch() is False off Windows and on any
        # ambiguity, so this branch is dead weight in a terminal/pipe/CI run.
        if not args:
            from . import onboarding, winlaunch

            if winlaunch.is_windowless_launch():
                onboarding.onboard()
                winlaunch.pause()
                raise typer.Exit()
        return super().parse_args(ctx, args)

    def resolve_command(self, ctx, args):
        try:
            return super().resolve_command(ctx, args)
        except typer.Exit:
            raise
        except Exception:
            return super().resolve_command(ctx, ["run", *args])


app = typer.Typer(
    add_completion=False,
    cls=_DefaultGroup,
    no_args_is_help=True,
    help="tnotes — trustworthy, evidence-anchored notes from PDF documents.\n\n"
    "Run `tnotes <pdf>` to take a PDF through the whole pipeline (extract → compose → "
    "export → book) and write the finished book beside it as <stem>.tnotes.pdf. "
    "Already-finished stages are skipped (--force to redo). Use the subcommands below "
    "for per-stage control. Connect to Claude once with `tnotes auth set-key`.",
)


def _version_callback(value: bool) -> None:
    """Print the version and exit — the ``tnotes --version`` flag.

    Beyond being useful on its own, this is the gate `tnotes upgrade` relies on:
    it runs a freshly downloaded exe with ``--version`` to confirm it is a
    launchable tnotes before swapping it in (see updater.verify_launchable).
    """
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True,
        help="Show the tnotes version and exit.",
    ),
) -> None:
    """Sweep a stale upgrade leftover and offer a one-tap upgrade, then dispatch.

    `tnotes upgrade` renames the running exe to tnotes.exe.old (Windows won't let a
    running exe be deleted); by the next launch that process has exited, so this is
    where the leftover gets removed. Cheap and silent on every other invocation.

    This callback fires for *every* invocation, including the eager `--version` /
    `--help` paths — but those exit before this body runs (their callbacks/Click
    handle them first), so the nudge never touches their output.
    """
    from . import updater

    # Only a frozen build has an exe that could have a .old leftover; in a source
    # run sys.executable is the interpreter, so there is nothing of ours to sweep.
    if updater.is_frozen():
        updater.cleanup_stale()
        _maybe_nudge_upgrade()


def _interactive() -> bool:
    """True only when both stdin and stdout are real terminals.

    The nudge prompts on stdin, so it must run only when a human can answer. A
    redirected/piped/captured run (e.g. CI's `tnotes.exe --help` with stdout
    captured) is not interactive, and prompting there would block forever — so we
    gate the whole prompt on this. Factored out so it can be stubbed in tests
    (CliRunner swaps the std streams, which makes patching isatty directly brittle).
    """
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _maybe_nudge_upgrade() -> None:
    """If a newer release exists, offer a one-keypress upgrade. Never blocks or breaks.

    Three guards keep this from ever harming a normal or automated run:

    * **Non-interactive → no prompt.** If stdin or stdout is not a TTY (redirected,
      piped, or captured — as in CI's `tnotes.exe --help` smoke), we skip silently
      rather than block waiting on stdin that will never arrive. This is the guard
      that guarantees the check can never hang automation.
    * **Frozen-only + cached + short-timeout + silent-fail** all live in
      :func:`updater.check_for_update`; a failed/slow check returns ``None`` here.
    * **Decline proceeds normally.** Answering no (or anything but yes) just returns,
      and the requested command runs as if the nudge never happened.

    On yes, we hand off to the very same `tnotes upgrade` path (the updater's
    ``upgrade``), then exit so the user restarts into the new build.
    """
    from . import updater

    if not _interactive():
        return

    latest = updater.check_for_update()
    if not latest:
        return

    answer = typer.prompt(
        f"tnotes v{latest} is available — upgrade now? [Y/n]",
        default="Y",
        show_default=False,
    ).strip().lower()
    if answer not in ("", "y", "yes"):
        return  # declined — fall through to the requested command

    def log(msg: str) -> None:
        typer.echo(msg, err=True)

    try:
        outcome = updater.upgrade(log=log)
    except updater.UpgradeError as exc:
        typer.echo(f"tnotes upgrade: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(outcome.message)
    raise typer.Exit(0)


@app.command(name="run", hidden=True)
def run(
    pdf: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source PDF."),
    pages: str = typer.Option(
        None, "--pages", "-p",
        help="Restrict the book to a page range: '1-30', '14', or '14,16'. "
        "Tags the output (e.g. -p 1-30 → <stem>.p1-30.tnotes.pdf).",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Regenerate every stage, even ones already finished."
    ),
    cite: bool = typer.Option(
        False, "--cite",
        help="Produce the anchored version ([s-N] markers + Notes & Sources appendix) "
        "instead of the default clean prose reading copy.",
    ),
):
    """One-command book generation: run the whole pipeline on a bare PDF.

    Reached as `tnotes <pdf>` (the `run` name is internal). Drives every stage —
    extract → terms → dedup → relations → assemble → export → book — skipping any
    already finished, and writes the finished book beside the source as
    <stem>[.pRANGE].tnotes.pdf (clean prose by default; --cite for the anchored copy).
    """
    from . import onboarding, pipeline, winlaunch

    # Windowless launch (a PDF dragged onto the exe, issue #33): a bare console that
    # closes on exit. Prompt for + save the key on first run before the auth gate,
    # and PAUSE at every exit so the user can read the result or the error instead of
    # watching the window flash shut. All of this is a no-op in a terminal/pipe/CI run
    # (is_windowless_launch() is False there), so the existing behaviour is untouched.
    windowless = winlaunch.is_windowless_launch()
    if windowless and not onboarding.ensure_api_key():
        winlaunch.pause()
        raise typer.Exit(1)

    if config.auth_source() == "none":
        typer.echo(
            "tnotes isn't connected to Claude yet. Run `tnotes auth set-key` (API key) "
            "or `tnotes auth login` (your account) first.",
            err=True,
        )
        winlaunch.pause()
        raise typer.Exit(1)

    def log(msg: str) -> None:
        typer.echo(msg, err=True)

    try:
        book_pdf = pipeline.run(
            pdf, pages=pages, force=force, cite=cite, log=log, parse_pages=_parse_pages
        )
    except ValueError as exc:
        typer.echo(f"tnotes: {exc}", err=True)
        winlaunch.pause()
        raise typer.Exit(1)
    if windowless:
        # A friendlier line than the bare path for the double-click/drag user.
        typer.echo(f"\nDone — wrote {book_pdf.name} in {book_pdf.parent}.")
        winlaunch.pause()
    else:
        typer.echo(str(book_pdf))


auth_app = typer.Typer(help="Connect tnotes to Claude (so you don't touch API keys or env vars).")
app.add_typer(auth_app, name="auth")


@auth_app.command("set-key")
def auth_set_key():
    """Save an Anthropic API key for tnotes to use (stored privately in your home)."""
    key = typer.prompt("Paste your Anthropic API key", hide_input=True).strip()
    if not key:
        typer.echo("No key entered — nothing saved.", err=True)
        raise typer.Exit(1)
    config.set_api_key(key)
    if platform.system() == "Windows":
        privacy = "private to your Windows account (inherited NTFS permissions)"
    else:
        privacy = "chmod 600"
    typer.echo(
        f"Saved to {config.config_file()} ({privacy}, in your home — never in the repo). "
        f"tnotes will use this key."
    )


@auth_app.command("status")
def auth_status():
    """Show how tnotes will authenticate to Claude."""
    source = config.auth_source()
    typer.echo(f"tnotes saved key : {'yes (' + str(config.config_file()) + ')' if config.get_api_key() else 'no'}")
    typer.echo(f"env API key  : {'set' if os.environ.get('ANTHROPIC_API_KEY') else 'not set'}")
    typer.echo(f"account login: {'present' if (Path.home() / '.config' / 'anthropic').exists() else 'none'}")
    label = {
        "config": "your saved key (tnotes auth set-key)",
        "env": "the ANTHROPIC_API_KEY in your shell",
        "login": "your account login (ant auth login)",
        "none": "NOTHING — run `tnotes auth set-key` or `tnotes auth login`",
    }[source]
    typer.echo(f"→ tnotes will use: {label}")


@auth_app.command("login")
def auth_login():
    """Log in with your Anthropic account (uses the `ant` helper under the hood)."""
    if shutil.which("ant") is None:
        system = platform.system()
        install = {
            "Darwin": "brew install anthropics/tap/ant",
            "Linux": "download from https://github.com/anthropics/anthropic-cli/releases",
            "Windows": "download the Windows build from https://github.com/anthropics/anthropic-cli/releases",
        }.get(system, "see https://github.com/anthropics/anthropic-cli/releases")
        typer.echo("Account login needs Anthropic's `ant` helper, which isn't installed.")
        typer.echo(f"Install it:  {install}")
        typer.echo("Then run again:  tnotes auth login")
        typer.echo("Or skip all this and use an API key (works everywhere):  tnotes auth set-key")
        raise typer.Exit(1)
    subprocess.run(["ant", "auth", "login"], check=False)
    if config.get_api_key() or os.environ.get("ANTHROPIC_API_KEY"):
        typer.echo(
            "\nNote: a saved/env API key takes precedence over the login. "
            "Run `tnotes auth clear-key` and `unset ANTHROPIC_API_KEY` to use the login.",
            err=True,
        )


@auth_app.command("clear-key")
def auth_clear_key():
    """Forget the saved API key."""
    config.clear_api_key()
    typer.echo("Cleared the saved key.")


config_app = typer.Typer(help="Set tnotes's defaults (extraction model and effort), stored in your home.")
app.add_typer(config_app, name="config")


@config_app.command("set-model")
def config_set_model(model: str = typer.Argument(..., help="Claude model id, e.g. claude-sonnet-4-6.")):
    """Save the default extraction model (used when no --model flag is given)."""
    config.set_model(model)
    typer.echo(f"Saved default model: {model} ({config.config_file()}).")


@config_app.command("set-effort")
def config_set_effort(
    effort: str = typer.Argument(
        ..., help="Effort: low | medium | high, or '' for models without an effort knob."
    )
):
    """Save the default effort (used when no --effort flag is given)."""
    config.set_effort(effort)
    shown = effort or "'' (none)"
    typer.echo(f"Saved default effort: {shown} ({config.config_file()}).")


@config_app.command("set-no-update-check")
def config_set_no_update_check(
    disabled: bool = typer.Argument(
        ..., help="true to silence the launch-time upgrade nudge, false to re-enable it."
    )
):
    """Opt out of (or back into) the launch-time upgrade nudge.

    The same effect as setting TNOTES_NO_UPDATE_CHECK=1 in your environment, but
    persisted in your config. The nudge only ever appears on the Windows tnotes.exe.
    """
    config.set_no_update_check(disabled)
    state = "off" if disabled else "on"
    typer.echo(f"Launch-time upgrade nudge: {state} ({config.config_file()}).")


@config_app.command("set-feedback-repo")
def config_set_feedback_repo(
    repo: str = typer.Argument(..., help="Private feedback repo as owner/name, e.g. acme/tnotes-feedback.")
):
    """Save the private feedback repo `tnotes feedback` files into (owner/name).

    The repo + its PAT are the maintainer's manual setup; when unset, `tnotes
    feedback` falls back to writing a local file instead of filing online.
    """
    config.set_feedback_repo(repo)
    typer.echo(f"Saved feedback repo: {repo} ({config.config_file()}).")


@config_app.command("set-feedback-token")
def config_set_feedback_token():
    """Save the fine-grained GitHub PAT for the feedback repo (stored privately).

    Get this token from the maintainer (delivered out-of-band, e.g. 1Password) — it
    is NEVER baked into the binary. Scoped to one private repo (Issues + Contents).
    """
    token = typer.prompt("Paste the feedback PAT", hide_input=True).strip()
    if not token:
        typer.echo("No token entered — nothing saved.", err=True)
        raise typer.Exit(1)
    config.set_feedback_token(token)
    typer.echo(
        f"Saved feedback token to {config.config_file()} (private to your home, "
        f"never in the repo or the exe)."
    )


@config_app.command("set-reporter-name")
def config_set_reporter_name(
    name: str = typer.Argument(..., help="Your name, tagged onto every report you send.")
):
    """Save your reporter name (asked once on first feedback, remembered after)."""
    config.set_reporter_name(name)
    typer.echo(f"Saved reporter name: {name} ({config.config_file()}).")


@config_app.command("show")
def config_show():
    """Show the resolved default model and effort, and where each comes from."""
    saved_model = config.get_model()
    saved_effort = config.get_effort()
    model = saved_model or config.DEFAULT_MODEL
    effort = saved_effort if saved_effort is not None else config.DEFAULT_EFFORT
    model_src = "config" if saved_model else f"built-in ({config.DEFAULT_MODEL})"
    effort_src = "config" if saved_effort is not None else f"built-in ({config.DEFAULT_EFFORT})"
    effort_shown = effort or "'' (none)"
    typer.echo(f"config file : {config.config_file()}")
    typer.echo(f"model : {model}  (from {model_src})")
    typer.echo(f"effort: {effort_shown}  (from {effort_src})")
    repo = config.get_feedback_repo()
    typer.echo(f"feedback repo : {repo or 'not set'}")
    typer.echo(f"feedback token: {'set' if config.get_feedback_token() else 'not set (falls back to local file)'}")
    typer.echo(f"reporter name : {config.get_reporter_name() or 'not set (asked on first feedback)'}")
    typer.echo("A --model/--effort flag on `tnotes extract` overrides these.")


def _parse_pages(spec: str, max_page: int) -> list[int]:
    """Parse a 1-based page spec like '15', '14-18', or '14,16,20'.

    Returns de-duplicated, in-order page numbers clamped to [1, max_page].
    """
    wanted: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            wanted.extend(range(int(a), int(b) + 1))
        else:
            wanted.append(int(part))
    seen: set[int] = set()
    out: list[int] = []
    for n in wanted:
        if 1 <= n <= max_page and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _render_page(p) -> str:
    """Human-readable dump of one extracted page (header + body + footnotes)."""
    lines = [
        f"=== PDF page {p.page_number} (index {p.page_index}) | {p.page_type} | printed "
        f"label '{p.page_label}' | {p.column_count} column(s) | {p.char_count} body chars ===",
        "",
        p.text,
    ]
    if p.footnotes:
        lines += ["", f"--- footnotes ({len(p.footnotes)} chars) ---", "", p.footnotes]
    return "\n".join(lines)


@app.command()
def extract(
    input: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source PDF."),
    pages: str = typer.Option(
        None, "--pages", "-p",
        help="Page(s): '14', '14-17', or '14,16'. Optional — default: all text pages of the document.",
    ),
    out: Path = typer.Option(
        None, "--out", "-o", file_okay=False,
        help="Output dir. Default: a folder beside the PDF (data/Foo.pdf → data/Foo.pdf.tnotes/).",
    ),
    window: int = typer.Option(1, "--window", "-w", help="Neighbour text pages of context each side."),
    model: str = typer.Option(
        None, "--model", "-m",
        help="Claude model. Resolves: this flag > `model:` in config > built-in "
        f"({config.DEFAULT_MODEL}). Cheaper still: claude-haiku-4-5 (use --effort '').",
    ),
    effort: str = typer.Option(
        None, "--effort", "-e",
        help="Effort: low | medium | high. Use '' for models without effort. "
        "Resolves: this flag > `effort:` in config > built-in (low). "
        "medium/high let adaptive thinking run very long on this bounded task.",
    ),
    gaps: bool = typer.Option(
        False, "--gaps", help="After each page, run the §7.6 gap report: source sentences no evidence covers."
    ),
    skip_existing: bool = typer.Option(
        False, "--skip-existing",
        help="Skip pages whose notes file already exists — makes a long run resumable/chunkable.",
    ),
    concurrency: int = typer.Option(
        1, "--concurrency", "-j", help="Pages to extract in parallel (independent LLM calls)."
    ),
    max_tokens: int = typer.Option(
        32000, "--max-tokens", help="Output token budget per page (raise if pages fail on token exhaustion)."
    ),
):
    """Wave 1: extract trustworthy notes from one or more pages with Claude.

    Set up auth once with `tnotes auth set-key` (or `tnotes auth login`). Each page is one
    LLM call. Output is per-page notes; composing pages into a chapter is not
    built yet.
    """
    from .extract import run_extract_with_usage, write_notes
    from .extract_anthropic import AnthropicExtractor
    from . import pricing

    # Resolve in layers: explicit flag > user config > built-in default. The flag
    # default is None, so "not passed" is distinguishable from "passed as ''"
    # (a meaningful effort value for models without an effort knob).
    model = config.resolve_model(model)
    effort = config.resolve_effort(effort)

    if config.auth_source() == "none":
        typer.echo(
            "tnotes isn't connected to Claude yet. Run `tnotes auth set-key` (API key) "
            "or `tnotes auth login` (your account) first.",
            err=True,
        )
        raise typer.Exit(1)

    all_pages = ingest.read_pages(input)
    by_number = {p.page_number: p for p in all_pages}
    if pages is None:
        # No range given: default to every text page. read_pages already ran the
        # same layout classification the `layout` command uses (classify_page),
        # so non-text pages (figure/table/blank) never reach the extractor.
        selected = [p.page_number for p in all_pages if p.page_type == "text"]
        if not selected:
            typer.echo(f"no text pages found in {input.name}", err=True)
            raise typer.Exit(1)
        typer.echo(f"no --pages given: extracting all {len(selected)} text page(s)", err=True)
    else:
        selected = _parse_pages(pages, len(all_pages))
        if not selected:
            typer.echo(f"no pages in range 1..{len(all_pages)} matched {pages!r}", err=True)
            raise typer.Exit(1)
    out = workspace.work_dir(input, out)
    workspace.extract_dir(out).mkdir(parents=True, exist_ok=True)
    typer.echo(f"writing notes to {workspace.extract_dir(out)}/", err=True)

    extractor = AnthropicExtractor(
        model=model, effort=effort, max_tokens=max_tokens, api_key=config.get_api_key()
    )

    # Build the work list serially (cheap: type/skip checks + neighbour context),
    # then extract pages — optionally several in parallel, since each page is an
    # independent LLM call. Output for a page is emitted as one block so parallel
    # runs don't interleave mid-page.
    worklist: list[tuple[int, Path, dict]] = []
    for n in selected:
        target = by_number[n]
        if target.page_type not in ("text", "figure"):
            typer.echo(f"skip page {n}: '{target.page_type}' (not extractable text)", err=True)
            continue
        dest = workspace.page_notes_path(out, target.page_index)
        if skip_existing and dest.is_file():
            typer.echo(f"skip page {n}: notes already exist ({dest})", err=True)
            continue
        idx = all_pages.index(target)
        neighbors = [
            all_pages[j]
            for j in range(max(0, idx - window), min(len(all_pages), idx + window + 1))
            if j != idx and all_pages[j].page_type == "text"
        ]
        worklist.append((n, dest, {"neighbors": neighbors}))

    def _work(item: tuple[int, Path, dict]) -> dict:
        n, dest, context = item
        target = by_number[n]
        try:
            notes, dropped, usage = run_extract_with_usage(
                target, extractor, document=input.stem, context=context
            )
        except Exception as exc:  # one page must not abort a long batch
            return {"n": n, "ok": False, "error": str(exc)}
        write_notes(notes, dest)
        return {
            "n": n, "ok": True, "notes": notes, "dropped": dropped,
            "dest": dest, "target": target, "usage": usage,
        }

    # Per-page cost estimates accumulate here; summed into a run total at the end.
    # None entries are pages we couldn't price (unknown model / no usage reported).
    run_costs: list[float] = []

    def _cost_line(usage: object) -> str:
        """A one-line cost estimate for a page, or the graceful unavailable note.

        Always labelled an estimate with the as-of date; never prints a bare
        ``$0`` for an unknown model (that would read as 'free', not 'unknown').
        """
        est = pricing.estimate_cost(model, usage) if usage is not None else None
        if est is None:
            return f"  cost estimate unavailable for {model!r}"
        run_costs.append(est)
        return f"  est. ${est:.4f} (pricing as of {pricing.PRICING_AS_OF})"

    def _report(res: dict) -> None:
        n = res["n"]
        if not res["ok"]:
            failed.append(n)
            typer.echo(
                f"FAILED page {n}: {res['error']} — skipping (rerun with --skip-existing to retry)",
                err=True,
            )
            return
        notes, dropped = res["notes"], res["dropped"]
        typer.echo(
            f"page {n}: statements={len(notes['statements'])} evidence={len(notes['evidence'])} "
            f"terms={len(notes['terms'])} relations={len(notes['relations'])} dropped={len(dropped)}"
        )
        typer.echo(_cost_line(res.get("usage")))
        for d in dropped:
            typer.echo(f"  dropped {d['kind']} {d['id']}: {d['reason']}", err=True)
        if gaps:
            from .gap import gap_report

            rep = gap_report(notes, res["target"])
            b, f = rep["body"], rep["footnotes"]
            typer.echo(
                f"  coverage: body {b['ratio']:.0%} ({len(b['gaps'])} gap(s)), "
                f"footnotes {f['ratio']:.0%} ({len(f['gaps'])} gap(s))"
            )
            for stream_name, srep in (("body", b), ("footnote", f)):
                for g in srep["gaps"]:
                    snippet = g["text"] if len(g["text"]) <= 120 else g["text"][:117] + "…"
                    typer.echo(f"    GAP [{stream_name} {g['coverage']:.0%}]: {snippet}")
        typer.echo(f"[wrote {res['dest']}]", err=True)

    failed: list[int] = []
    results: list[dict] = []
    typer.echo(
        f"extracting {len(worklist)} page(s) with {model} "
        f"(effort={effort or 'none'}, concurrency={concurrency})…",
        err=True,
    )
    if concurrency > 1 and len(worklist) > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for res in pool.map(_work, worklist):
                _report(res)
                results.append(res)
    else:
        for item in worklist:
            res = _work(item)
            _report(res)
            results.append(res)

    # Run total: sum of the pages we could price. If no page priced (unknown
    # model, or no usage reported at all), say so rather than print $0.00.
    priced = len([r for r in results if r["ok"] and r.get("usage") is not None])
    if run_costs:
        suffix = "" if priced == len(run_costs) else f" ({priced} of {len(results)} page(s) priced)"
        typer.echo(
            f"run total: est. ${sum(run_costs):.4f} "
            f"(pricing as of {pricing.PRICING_AS_OF}){suffix}"
        )
    else:
        typer.echo(f"run total: cost estimate unavailable for {model!r}")

    # Single-page interactive use: also echo the notes to stdout.
    if len(selected) == 1 and len(results) == 1 and results[0]["ok"]:
        import yaml

        typer.echo(yaml.safe_dump(results[0]["notes"], sort_keys=False, allow_unicode=True))

    if failed:
        typer.echo(
            f"\n{len(failed)} page(s) failed: {failed}. Re-run the same command with "
            f"--skip-existing to retry only those.",
            err=True,
        )


@app.command()
def layout(
    input: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source PDF."),
    list_pages: bool = typer.Option(False, "--list", help="List the page numbers in each type."),
):
    """Classify every page's layout (text / figure / table / blank) and report the counts."""
    import pdfplumber
    from collections import Counter, defaultdict

    by_type: dict[str, list[int]] = defaultdict(list)
    with pdfplumber.open(input) as pdf:
        for page in pdf.pages:
            by_type[ingest.classify_page(page)["type"]].append(page.page_number)

    dist = Counter({t: len(ns) for t, ns in by_type.items()})
    typer.echo("=== page-type distribution ===")
    for t, n in dist.most_common():
        typer.echo(f"{t:8} {n}")
    if list_pages:
        for t, ns in sorted(by_type.items()):
            typer.echo(f"\n{t}: {ns}")


@app.command()
def render(
    input: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source PDF."),
    pages: str = typer.Option(..., "--pages", "-p", help="Pages to render, e.g. '14' or '14-16'."),
    out: Path = typer.Option(Path("scans"), "--out", "-o", file_okay=False, help="Output dir for PNGs."),
    resolution: int = typer.Option(120, "--resolution", "-r", help="Render DPI."),
):
    """Show what the reader SEES: header (red), body columns (green), footnotes (blue)."""
    import pdfplumber

    out.mkdir(parents=True, exist_ok=True)
    with pdfplumber.open(input) as pdf:
        pdf_pages = list(pdf.pages)
        selected = _parse_pages(pages, len(pdf_pages))
        if not selected:
            typer.echo(f"no pages in range 1..{len(pdf_pages)} matched {pages!r}", err=True)
            raise typer.Exit(1)
        headers = ingest.detect_headers(pdf_pages)
        for n in selected:
            page = pdf_pages[n - 1]
            is_header = bool(ingest.top_line(page)) and ingest.top_line(page) in headers
            r = ingest.region_map(page, is_header)
            w, h = r["width"], r["height"]
            im = page.to_image(resolution=resolution)
            if r["header_bottom"] > 0:
                im.draw_rect((0, 0, w, r["header_bottom"]), fill=None, stroke="red", stroke_width=3)
            for col in r["columns"]:
                im.draw_rect((col["x0"], r["header_bottom"], col["x1"], col["fn_top"]),
                             fill=None, stroke="green", stroke_width=3)
                if col["fn_top"] < h:
                    im.draw_rect((col["x0"], col["fn_top"], col["x1"], h),
                                 fill=None, stroke="blue", stroke_width=3)
            dest = out / f"pdf-page-{n:04d}.scan.png"
            im.save(dest)
            typer.echo(
                f"[{dest}] header={'stripped' if is_header else 'none'} "
                f"columns={len(r['columns'])}"
            )


@app.command()
def probe(
    input: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source PDF."),
    pages: str = typer.Option(
        None, "--pages", "-p", help="Pages to dump: '15', '14-18', or '14,16,20'."
    ),
    out: Path = typer.Option(
        None, "--out", "-o", file_okay=False, help="Also write each page to DIR/pdf-page-NNNN.txt."
    ),
):
    """Run Wave 0 (ingest) only: text-layer report, and dump the chosen pages."""
    extracted = ingest.read_pages(input)
    report = ingest.text_layer_report(extracted)
    typer.echo("=== text-layer report ===")
    for k, v in report.items():
        typer.echo(f"{k}: {v}")

    if pages is None:
        return

    selected = _parse_pages(pages, len(extracted))
    if not selected:
        typer.echo(f"no pages in range 1..{len(extracted)} matched {pages!r}", err=True)
        raise typer.Exit(1)

    if out is not None:
        out.mkdir(parents=True, exist_ok=True)

    by_number = {p.page_number: p for p in extracted}
    for n in selected:
        page = by_number[n]
        rendered = _render_page(page)
        typer.echo("\n" + rendered)
        if out is not None:
            dest = out / f"pdf-page-{n:04d}.txt"
            dest.write_text(rendered + "\n", encoding="utf-8")
            typer.echo(f"[wrote {dest}]", err=True)


@app.command()
def gap(
    input: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source PDF."),
    notes_dir: Path = typer.Option(
        None, "--notes", "-n", file_okay=False,
        help="Dir of page-NNNN.notes.yaml files. Default: the PDF's folder (data/Foo.pdf → data/Foo.pdf.tnotes/).",
    ),
    pages: str = typer.Option(None, "--pages", "-p", help="Pages to check; default: all notes found."),
    threshold: float = typer.Option(
        0.5, "--threshold", "-t", help="A sentence is a gap below this covered fraction (0..1)."
    ),
    below: float = typer.Option(
        None, "--below",
        help="Re-do list mode: list only pages whose BODY coverage is below this fraction, "
        "with a ready-to-paste --pages spec (e.g. `tnotes gap PDF --below 0.8` → pages to re-run at higher effort).",
    ),
    all_sections: bool = typer.Option(
        False, "--all-sections",
        help="In --below mode, also include reference matter (tables/indexes/figures), "
        "where low coverage is normal. Default: prose chapters only.",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Regenerate even if the saved view is still fresh."),
):
    """§7.6 gap report on already-extracted notes: source sentences no evidence covers.

    Re-ingests the PDF and, for each page that has a notes file, lists the body
    and footnote sentences that evidence does not cover. With --below, switches to
    "re-do list" mode: the under-covered prose pages (worst first) and a copy-paste
    --pages spec to re-extract them at higher effort. Saved to gaps.txt in the
    notes dir; shown instantly next time unless inputs change (--force regenerates).
    No API calls.
    """
    import yaml

    from . import compose, report
    from .gap import gap_report

    notes_dir = workspace.work_dir(input, notes_dir)
    if not notes_dir.is_dir():
        typer.echo(f"notes dir {notes_dir} does not exist — run `tnotes extract` first", err=True)
        raise typer.Exit(1)

    def render() -> str:
        all_pages = ingest.read_pages(input)
        by_number = {p.page_number: p for p in all_pages}
        selected = _parse_pages(pages, len(all_pages)) if pages else None
        sections = compose.page_sections(input) if (below is not None and not all_sections) else None

        out: list[str] = []
        checked = 0
        skipped_ref = 0
        redo: list[tuple[int, str, float, str]] = []
        for p in all_pages:
            if selected is not None and p.page_number not in selected:
                continue
            nf = workspace.page_notes_path(notes_dir, p.page_index)
            if not nf.is_file():
                continue
            notes = yaml.safe_load(nf.read_text(encoding="utf-8")) or {}
            rep = gap_report(notes, by_number[p.page_number], threshold=threshold)
            b, f = rep["body"], rep["footnotes"]
            if below is not None:
                sec = (sections or {}).get(p.page_index, {"title": "?", "prose": True})
                if sections is not None and not sec["prose"]:
                    skipped_ref += 1
                    continue
                checked += 1
                if b["ratio"] < below:
                    redo.append((p.page_number, p.page_label, b["ratio"], sec["title"]))
                continue
            checked += 1
            out.append(
                f"page {p.page_number} (printed '{p.page_label}'): body {b['ratio']:.0%} "
                f"({len(b['gaps'])} gap(s)), footnotes {f['ratio']:.0%} ({len(f['gaps'])} gap(s))"
            )
            for stream_name, srep in (("body", b), ("footnote", f)):
                for g in srep["gaps"]:
                    snippet = g["text"] if len(g["text"]) <= 120 else g["text"][:117] + "…"
                    out.append(f"  GAP [{stream_name} {g['coverage']:.0%}]: {snippet}")

        if checked == 0 and not redo and skipped_ref == 0:
            return f"no page-NNNN.notes.yaml files found in {notes_dir}"

        if below is None:
            return "\n".join(out)

        scope = "all sections" if all_sections else "prose chapters"
        head = [
            "Body coverage = the share of a page's text backed by an evidence quote in the notes.",
            "Low coverage on a prose page can mean missed content; on tables/indexes it is normal.",
            "",
            f"{len(redo)} of {checked} {scope} pages are below {below:.0%} body coverage"
            + (f"  (skipped {skipped_ref} reference pages — see --all-sections)" if skipped_ref else ""),
        ]
        if redo:
            redo.sort(key=lambda r: r[2])
            head += ["", f"  {'cov':>4}  {'page (printed)':<16}  section"]
            for n, label, ratio, sec in redo:
                title = sec if len(sec) <= 34 else sec[:31] + "…"
                head.append(f"  {ratio:>4.0%}  {f'p{n} ({label})':<16}  {title}")
            spec = ",".join(str(n) for n, _, _, _ in sorted(redo))
            head += [
                "",
                "These prose pages likely have missed content — re-extract them at higher effort:",
                f'  tnotes extract "{input}" --pages {spec} -e medium',
            ]
        return "\n".join(head)

    params = f"below={below};threshold={threshold};pages={pages};all_sections={all_sections}"
    fp = report.inputs_fingerprint(input, notes_dir, params=params)
    report.emit(workspace.validate_dir(notes_dir) / "gaps.txt", fp, force, render, label="tnotes gap")


@app.command()
def stitches(
    input: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source PDF."),
    notes_dir: Path = typer.Option(
        None, "--notes", "-n", file_okay=False,
        help="Notes dir. Default: the PDF's folder (data/Foo.pdf → data/Foo.pdf.tnotes/).",
    ),
    full: bool = typer.Option(False, "--full", help="Show the complete stitched quote, not a snippet."),
    force: bool = typer.Option(False, "--force", "-f", help="Regenerate even if the saved view is still fresh."),
):
    """Wave 2 stage 2: show proposed cross-page evidence stitches (quotes cut at a
    page break, rejoined with their continuation on the next page). No API calls;
    proposes only, mutates nothing. Saved to stitches.txt in the notes dir."""
    from . import compose, report

    notes_dir = workspace.work_dir(input, notes_dir)

    def render() -> str:
        st = compose.find_stitches(input, notes_dir)
        out = [
            "Cross-page quotes — evidence cut off at a page break, rejoined with its",
            "continuation on the next page (Wave 2 stage 2). Each line shows the tail on",
            "page N and ⟦+ the continuation⟧ from page N+1. Proposals only — nothing is",
            "written yet; compose applies them at assembly. Use --full for whole quotes.",
            "",
            f"{len(st)} cross-page quote(s) detected:",
            "",
        ]
        for s in st:
            out.append(f"page-index {s['page_index']} → {s['next_page_index']}  [{s['evidence_id']}]")
            if full:
                out.append(f"  {s['stitched']}\n")
            else:
                tail = s["tail"][-55:]
                done = s["stitched"][len(s["tail"]):]
                done = done if len(done) <= 80 else done[:77] + "…"
                out.append(f"  …{tail}  ⟦+ {done.strip()}⟧\n")
        return "\n".join(out)

    fp = report.inputs_fingerprint(input, notes_dir, params=f"full={full}")
    report.emit(workspace.compose_stage_dir(notes_dir, "stitches") / "stitches.txt", fp, force, render, label="tnotes stitches")


@app.command()
def book(
    input: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source PDF."),
    notes_dir: Path = typer.Option(
        None, "--notes", "-n", file_okay=False,
        help="Notes dir. Default: the PDF's folder (data/Foo.pdf → data/Foo.pdf.tnotes/).",
    ),
    style: str = typer.Option("outline", "--style", "-s", help="Which exported style to combine."),
    prose_only: bool = typer.Option(
        True, "--prose-only/--all",
        help="Include only prose chapters (default), or --all to include tables/indexes too.",
    ),
    no_citations: bool = typer.Option(
        False, "--no-citations/--citations",
        help="Strip [s-N] citations and the Notes & Sources appendix for a clean reading copy "
             "(writes <stem>.tnotes.reading.md/.pdf). Default keeps citations (<stem>.tnotes.md/.pdf).",
    ),
):
    """Combine the per-chapter exports into one navigable book beside the source PDF.

    Concatenates 4-export/chapter-*.<style>.md into a single document with a master
    hierarchical Contents and namespaced cross-chapter links, and renders one
    interactive PDF. The book is written beside the source as <stem>.tnotes.md and
    <stem>.tnotes.pdf (e.g. data/Foo.pdf → data/Foo.tnotes.pdf). Chapter titles come
    from the composed notes-sets. Prose chapters only by default (--all to include
    reference sections). With --no-citations, also drops the [s-N] markers and Notes
    & Sources for a clean read-through (<stem>.tnotes.reading.*), leaving the cited
    <stem>.tnotes.* as the authority. Run `tnotes export --pdf` first. No API calls.
    """
    import yaml as _yaml

    from . import book as bookmod, compose, export as exp, pdf as pdfmod

    notes_dir = workspace.work_dir(input, notes_dir)
    exdir = workspace.export_dir(notes_dir)
    files = sorted(exdir.glob(f"chapter-*.{style}.md"))
    if not files:
        typer.echo(f"no chapter-*.{style}.md in {exdir} — run `tnotes export` first.", err=True)
        raise typer.Exit(1)

    chapters: list[tuple[int, str, str]] = []
    skipped = 0
    for f in files:
        num = int(f.stem.split("-")[1].split(".")[0])
        cfile = workspace.compose_stage_dir(notes_dir, "chapters") / f"chapter-{num:03d}.notes.yaml"
        src = (_yaml.safe_load(cfile.read_text(encoding="utf-8")) or {}).get("source", {}) if cfile.is_file() else {}
        title = src.get("chapter_title") or src.get("chapter_id") or f"Chapter {num}"
        if prose_only and not compose._is_prose_section(title):
            skipped += 1
            continue
        chapters.append((num, title, f.read_text(encoding="utf-8")))

    if no_citations:
        chapters = [(num, title, exp.strip_citations(md)) for num, title, md in chapters]
    # The book lives beside the source PDF, named after it: data/Foo.pdf →
    # data/Foo.tnotes.md/.pdf (the reading copy adds a .reading marker).
    suffix = ".tnotes.reading" if no_citations else ".tnotes"
    stem = input.stem + suffix
    book_md = bookmod.combine(chapters, doc_title=input.stem)
    md_path = input.parent / f"{stem}.md"
    pdf_path = input.parent / f"{stem}.pdf"
    md_path.write_text(book_md, encoding="utf-8")
    pdfmod.markdown_to_pdf(book_md, pdf_path)
    typer.echo(f"combined {len(chapters)} chapters"
               + (" (no citations — reading copy)" if no_citations else "")
               + (f" (skipped {skipped} reference sections; --all to include)" if skipped else "")
               + f" → {md_path} and {pdf_path.name}")


@app.command()
def export(
    input: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source PDF."),
    notes_dir: Path = typer.Option(
        None, "--notes", "-n", file_okay=False,
        help="Notes dir. Default: the PDF's folder (data/Foo.pdf → data/Foo.pdf.tnotes/).",
    ),
    chapters: str = typer.Option(None, "--chapters", "-c", help="Chapter file numbers, e.g. '6' or '6,9-11'. Default: all."),
    style: str = typer.Option("outline", "--style", "-s", help="Study-note style (currently: outline)."),
    model: str = typer.Option(
        None, "--model", "-m",
        help="Model for synthesis. Resolves: this flag > `model:` in config > built-in "
        f"({config.DEFAULT_MODEL}).",
    ),
    effort: str = typer.Option(
        None, "--effort", "-e",
        help="Effort for synthesis. Resolves: this flag > `effort:` in config > built-in "
        f"({config.DEFAULT_EFFORT}). Use '' for models without an effort knob.",
    ),
    pdf: bool = typer.Option(
        False, "--pdf",
        help="Also render an interactive PDF (bookmarks + clickable Contents + [s-N] links) beside the .md.",
    ),
    prose_only: bool = typer.Option(
        True, "--prose-only/--all",
        help="Export only prose chapters (default), or --all to include tables/indexes too.",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Re-export chapters that already have a .md."),
):
    """Wave 4: export human-readable study notes from the composed chapters.

    Synthesizes a study document per chapter (default style: outline) ONLY from its
    notes, citing note ids that link to the verbatim evidence (page citations are
    plain text). Writes 4-export/chapter-NNN.<style>.md, and with --pdf an
    interactive PDF beside it. Prose chapters only by default (--all for reference
    sections). Skips chapters already done unless --force. Run `tnotes assemble` first.
    """
    from . import compose, export as exp

    model = config.resolve_model(model)
    effort = config.resolve_effort(effort)
    notes_dir = workspace.work_dir(input, notes_dir)
    if config.auth_source() == "none":
        typer.echo("export needs Claude; run `tnotes auth set-key` first.", err=True)
        raise typer.Exit(1)

    src_dir = workspace.compose_stage_dir(notes_dir, "chapters")
    files = sorted(src_dir.glob("chapter-*.notes.yaml"))
    if not files:
        typer.echo(f"no composed chapters in {src_dir} — run `tnotes assemble` first.", err=True)
        raise typer.Exit(1)
    wanted = set(_parse_pages(chapters, len(files))) if chapters else None
    out_dir = workspace.export_dir(notes_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    import yaml as _yaml
    import anthropic

    client = anthropic.Anthropic(api_key=config.get_api_key())
    written = skipped = flagged = pdfs = 0
    for f in files:
        num = int(f.stem.split("-")[1].split(".")[0])
        if wanted is not None and num not in wanted:
            continue
        if prose_only:
            src = (_yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("source", {})
            if not compose._is_prose_section(src.get("chapter_title") or src.get("chapter_id") or ""):
                skipped += 1
                continue
        dest = out_dir / f"chapter-{num:03d}.{style}.md"
        pdf_dest = dest.with_suffix(".pdf")
        need_md = force or not dest.is_file()
        need_pdf = pdf and (force or not pdf_dest.is_file())
        if not need_md and not need_pdf:
            skipped += 1
            continue
        if need_md:
            cset = _yaml.safe_load(f.read_text(encoding="utf-8"))
            title = cset.get("source", {}).get("chapter_title", f.name)
            typer.echo(f"exporting chapter {num:03d} ({title}) [{style}]…", err=True)
            try:
                res = exp.study_document(cset, style=style, client=client, model=model, effort=effort)
            except Exception as exc:
                typer.echo(f"  FAILED chapter {num}: {exc}", err=True)
                continue
            dest.write_text(res["markdown"], encoding="utf-8")
            written += 1
            md_text = res["markdown"]
            if res["unknown"]:
                flagged += 1
            note = f"  ⚠ {len(res['unknown'])} stray citation(s)" if res["unknown"] else ""
            typer.echo(f"[wrote {dest}]  ({len(res['cited'])} notes cited){note}", err=True)
        else:
            md_text = dest.read_text(encoding="utf-8")  # reuse existing .md to render the PDF (no API)
        if need_pdf:
            from . import pdf as pdfmod

            pdfmod.markdown_to_pdf(md_text, pdf_dest)
            pdfs += 1
            typer.echo(f"[wrote {pdf_dest}]", err=True)

    typer.echo(f"\nexported {written} markdown" + (f" + {pdfs} pdf" if pdf else "")
               + f" chapter(s), skipped {skipped} existing"
               + (f", {flagged} with stray citations" if flagged else "") + f" → {out_dir}/")


@app.command()
def assemble(
    input: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source PDF."),
    notes_dir: Path = typer.Option(
        None, "--notes", "-n", file_okay=False,
        help="Notes dir. Default: the PDF's folder (data/Foo.pdf → data/Foo.pdf.tnotes/).",
    ),
):
    """Wave 2 stage 6: assemble per-page notes into chapter-scope deliverables.

    Groups each section's pages and applies everything compose computed — dedup
    merges, term links, and intra-page + cross-page relations — lifting scope to
    chapter, then re-validates each (§7.1–7.5). Writes chapter-NNN.notes.yaml to
    the notes dir. No API calls (consumes the saved Wave 2 artifacts).
    """
    import yaml

    from . import compose
    from .validation import validate_structure

    notes_dir = workspace.work_dir(input, notes_dir)
    summaries = compose.assemble_document(input, notes_dir, document=input.stem)
    if not summaries:
        typer.echo("nothing to assemble — run `tnotes extract` first.", err=True)
        raise typer.Exit(1)

    typer.echo(f"assembled {len(summaries)} chapter notes-sets → {workspace.compose_stage_dir(notes_dir, 'chapters')}/\n")
    typer.echo(f"{'statements':>10} {'evid':>5} {'terms':>5} {'rels':>5}  chapter")
    bad = 0
    for s in summaries:
        cset = yaml.safe_load((workspace.compose_stage_dir(notes_dir, "chapters") / s["file"]).read_text(encoding="utf-8"))
        errs = validate_structure(cset)
        flag = "" if not errs else f"  ✗ {len(errs)} schema/ref errors"
        if errs:
            bad += 1
        title = s["title"] if len(s["title"]) <= 40 else s["title"][:37] + "…"
        typer.echo(f"{s['statements']:>10} {s['evidence']:>5} {s['terms']:>5} {s['relations']:>5}  {title}{flag}")
    tot = lambda k: sum(s[k] for s in summaries)  # noqa: E731
    typer.echo(
        f"\ntotals: {tot('statements')} statements, {tot('evidence')} evidence, "
        f"{tot('relations')} relations across {len(summaries)} chapters"
        + (f"  —  {bad} chapter(s) FAILED validation" if bad else "  —  all valid ✓")
    )


@app.command()
def relations(
    input: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source PDF."),
    notes_dir: Path = typer.Option(
        None, "--notes", "-n", file_okay=False,
        help="Notes dir. Default: the PDF's folder (data/Foo.pdf → data/Foo.pdf.tnotes/).",
    ),
    build: bool = typer.Option(False, "--build", help="Discover cross-page relations via the model (uses the API)."),
    model: str = typer.Option(
        None, "--model", "-m",
        help="Model for --build. Resolves: this flag > `model:` in config > built-in "
        f"({config.DEFAULT_MODEL}).",
    ),
    effort: str = typer.Option(
        None, "--effort", "-e",
        help="Effort for --build. Resolves: this flag > `effort:` in config > built-in "
        f"({config.DEFAULT_EFFORT}). Use '' for models without an effort knob.",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Rebuild even if the saved view is still fresh."),
):
    """Wave 2 stage 5: cross-page relations (term-blocked).

    Adds the argument structure that only appears at chapter scope — typed
    relations (supports/contrasts/elaborates/…) between statements on different
    pages. Candidates are bounded by shared terms (needs the Stage-4 term store);
    a bounded model call per chapter proposes the relations. --build runs the
    model (writes relations.yaml for assembly); without it, shows the saved view.
    """
    from . import relate, report

    model = config.resolve_model(model)
    effort = config.resolve_effort(effort)
    notes_dir = workspace.work_dir(input, notes_dir)
    params = f"model={model};effort={effort}"
    fp = report.inputs_fingerprint(input, notes_dir, params=params)
    txt_path = workspace.compose_stage_dir(notes_dir, "relations") / "relations.txt"

    if not build:
        cached = report.read_fresh(txt_path, fp)
        if cached is None:
            typer.echo("no fresh cross-page relations — run `tnotes relations --build` (uses the API).", err=True)
            raise typer.Exit(1)
        typer.echo(cached)
        return

    if config.auth_source() == "none":
        typer.echo("--build needs Claude; run `tnotes auth set-key` first.", err=True)
        raise typer.Exit(1)

    def render() -> str:
        import yaml as _yaml

        rels = relate.build_relations(input, notes_dir, model=model, effort=effort, api_key=config.get_api_key())
        yaml_path = workspace.compose_stage_dir(notes_dir, "relations") / "relations.yaml"
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text(_yaml.safe_dump({"relations": rels}, allow_unicode=True), encoding="utf-8")
        from collections import Counter

        by_type = Counter(r["type"] for r in rels)
        out = [
            "Cross-page relations — argument structure spanning pages (Wave 2 stage 5; "
            f"model={model}, effort={effort or 'none'}).",
            f"Term-blocked candidates, proposed per chapter. Written to {yaml_path.name} for assembly.",
            "",
            f"{len(rels)} cross-page relation(s):  "
            + ", ".join(f"{t}={n}" for t, n in by_type.most_common()),
            "",
        ]
        for r in rels[:60]:
            out.append(f"  {r['from']}  --{r['type']}-->  {r['to']}")
        if len(rels) > 60:
            out.append(f"  … and {len(rels) - 60} more (see relations.yaml)")
        return "\n".join(out)

    report.emit(txt_path, fp, force, render, label="tnotes relations")


@app.command()
def terms(
    input: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source PDF."),
    notes_dir: Path = typer.Option(
        None, "--notes", "-n", file_okay=False,
        help="Notes dir. Default: the PDF's folder (data/Foo.pdf → data/Foo.pdf.tnotes/).",
    ),
    build: bool = typer.Option(False, "--build", help="Build/refresh the term store via the model (uses the API)."),
    model: str = typer.Option(
        None, "--model", "-m",
        help="Model for --build. Resolves: this flag > `model:` in config > built-in "
        f"({config.DEFAULT_MODEL}).",
    ),
    effort: str = typer.Option(
        None, "--effort", "-e",
        help="Effort for --build. Resolves: this flag > `effort:` in config > built-in "
        f"({config.DEFAULT_EFFORT}). Use '' for models without an effort knob.",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Rebuild even if the saved store is still fresh."),
):
    """Wave 2 stage 4: the document-global term store (vocabulary + statement links).

    A term is document-global (METHODOLOGY §4.1), so it's derived at compose: one
    bounded model pass per prose chapter names that chapter's vocabulary, then code
    dedups labels across chapters and links statements to them. --build runs the
    model (writes terms.yaml for assembly); without it, shows the saved store.
    """
    from . import report, term_store

    model = config.resolve_model(model)
    effort = config.resolve_effort(effort)
    notes_dir = workspace.work_dir(input, notes_dir)
    params = f"model={model};effort={effort}"
    fp = report.inputs_fingerprint(input, notes_dir, params=params)
    txt_path = workspace.compose_stage_dir(notes_dir, "terms") / "terms.txt"

    if not build:
        cached = report.read_fresh(txt_path, fp)
        if cached is None:
            typer.echo("no fresh term store — run `tnotes terms --build` (uses the API).", err=True)
            raise typer.Exit(1)
        typer.echo(cached)
        return

    if config.auth_source() == "none":
        typer.echo("--build needs Claude; run `tnotes auth set-key` first.", err=True)
        raise typer.Exit(1)

    def render() -> str:
        import yaml as _yaml

        store = term_store.build_store(input, notes_dir, model=model, effort=effort, api_key=config.get_api_key())
        yaml_path = workspace.compose_stage_dir(notes_dir, "terms") / "terms.yaml"
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text(_yaml.safe_dump(store, allow_unicode=True, sort_keys=False), encoding="utf-8")
        linked = len(store["links"])
        out = [
            "Term store — the document-global vocabulary (Wave 2 stage 4; "
            f"model={model}, effort={effort or 'none'}).",
            f"Derived per prose chapter, deduplicated across the document. Written to "
            f"{yaml_path.name} for assembly.",
            "",
            f"{len(store['terms'])} terms; {linked} statements linked to ≥1 term.",
            "",
            f"{'uses':>5}  term (id)",
        ]
        for t in store["terms"]:
            out.append(f"{t['count']:>5}  {t['label']}  ({t['id']})")
        return "\n".join(out)

    report.emit(txt_path, fp, force, render, label="tnotes terms")


@app.command()
def dedup(
    input: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source PDF."),
    notes_dir: Path = typer.Option(
        None, "--notes", "-n", file_okay=False,
        help="Notes dir. Default: the PDF's folder (data/Foo.pdf → data/Foo.pdf.tnotes/).",
    ),
    adjudicate: bool = typer.Option(
        False, "--adjudicate",
        help="Part (b): ask the model to confirm which candidates truly merge (uses the API).",
    ),
    model: str = typer.Option(
        None, "--model", "-m",
        help="Model for --adjudicate. Resolves: this flag > `model:` in config > built-in "
        f"({config.DEFAULT_MODEL}).",
    ),
    effort: str = typer.Option(
        None, "--effort", "-e",
        help="Effort for --adjudicate. Resolves: this flag > `effort:` in config > built-in "
        f"({config.DEFAULT_EFFORT}). Use '' for models without an effort knob.",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Regenerate even if the saved view is still fresh."),
):
    """Wave 2 stage 3 (dedup): candidate duplicate statements.

    Part (a), default — mechanical blocking: clusters statements of the same type
    that cite the same verbatim evidence (the high-precision "same claim" signal).
    No API; mutates nothing. Part (b), --adjudicate — a bounded model call per
    cluster confirms which members truly merge and the merged wording, written to
    dedup-merges.yaml for assembly. Saved to dedup.txt in the notes dir.
    """
    from . import compose, report

    model = config.resolve_model(model)
    effort = config.resolve_effort(effort)
    notes_dir = workspace.work_dir(input, notes_dir)
    if adjudicate and config.auth_source() == "none":
        typer.echo("--adjudicate needs Claude; run `tnotes auth set-key` first.", err=True)
        raise typer.Exit(1)

    def render() -> str:
        clusters = compose.dedup_candidates(notes_dir)
        dup_stmts = sum(len(c) for c in clusters)
        if not adjudicate:
            out = [
                "Duplicate candidates — statements of the same type citing the same verbatim",
                "evidence (Wave 2 stage 3, mechanical blocking). Candidates only: run with",
                "--adjudicate to have the model confirm which truly merge.",
                "",
                f"{len(clusters)} candidate cluster(s) covering {dup_stmts} statements:",
            ]
            for i, c in enumerate(clusters, 1):
                out.append(f"\ncluster {i}  (type={c[0]['type']}, {len(c)} statements):")
                for s in c:
                    text = s["text"] if len(s["text"]) <= 100 else s["text"][:97] + "…"
                    out.append(f"  [{s['key']}]  {text}")
            return "\n".join(out)

        from . import adjudicate as adj

        decisions = adj.adjudicate(clusters, model=model, effort=effort, api_key=config.get_api_key())
        merges = [m for d in decisions for m in d["merges"]]
        # structured decisions for assembly (stage 6)
        import yaml as _yaml

        merges_path = workspace.compose_stage_dir(notes_dir, "dedup") / "dedup-merges.yaml"
        merges_path.parent.mkdir(parents=True, exist_ok=True)
        merges_path.write_text(_yaml.safe_dump({"merges": merges}, allow_unicode=True), encoding="utf-8")

        out = [
            "Dedup adjudication — the model's verdict on each candidate cluster (Wave 2",
            f"stage 3, part b; model={model}, effort={effort or 'none'}). MERGE groups are",
            f"written to {merges_path.name} for assembly; code unions the evidence.",
            "",
            f"{len(clusters)} cluster(s) → {len(merges)} confirmed merge group(s):",
        ]
        for i, c in enumerate(clusters, 1):
            cmerges = next(d["merges"] for d in decisions if d["cluster"] is c)
            merged_keys = {k for m in cmerges for k in m["members"]}
            out.append(f"\ncluster {i}  (type={c[0]['type']}, {len(c)} statements):")
            for s in c:
                mark = "MERGE" if s["key"] in merged_keys else "keep "
                text = s["text"] if len(s["text"]) <= 90 else s["text"][:87] + "…"
                out.append(f"  [{mark}] [{s['key']}]  {text}")
            for m in cmerges:
                mt = m["text"] if len(m["text"]) <= 110 else m["text"][:107] + "…"
                out.append(f"     ⟹ merged: {mt}")
        return "\n".join(out)

    params = f"adjudicate={adjudicate};model={model};effort={effort}"
    fp = report.inputs_fingerprint(input, notes_dir, params=params)
    report.emit(workspace.compose_stage_dir(notes_dir, "dedup") / "dedup.txt", fp, force, render, label="tnotes dedup")


@app.command()
def chapters(
    input: Path = typer.Argument(..., exists=True, dir_okay=False, help="Source PDF."),
    notes_dir: Path = typer.Option(
        None, "--notes", "-n", file_okay=False,
        help="Notes dir. Default: the PDF's folder (data/Foo.pdf → data/Foo.pdf.tnotes/).",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Regenerate even if the saved view is still fresh."),
):
    """Wave 2 stage 0–1: show the chapter map derived from running-header detection.

    Groups every page into a chapter/section (reusing Wave 0's header detection)
    and annotates each with how many pages have notes and their statement/evidence
    counts. Saved to chapters.txt in the notes dir; shown instantly next time
    unless the PDF, notes, or ingest code change (--force regenerates). No API.
    """
    from . import compose, report

    notes_dir = workspace.work_dir(input, notes_dir)

    def render() -> str:
        rows = compose.chapter_summaries(input, notes_dir)
        out = [
            "Chapter map — every page grouped into a chapter/section by its running header",
            "(Wave 2 stage 0–1). Columns: PDF page span · pages-with-notes/total · statements.",
            "",
            f"{len(rows)} chapters/sections detected:",
            "",
            f"{'pages (PDF)':>13}  {'notes':>5}  {'stmts':>5}  title",
        ]
        for r in rows:
            pn = r["page_numbers"]
            span = f"{pn[0]}–{pn[-1]}" if len(pn) > 1 else f"{pn[0]}"
            title = r["title"] if len(r["title"]) <= 52 else r["title"][:49] + "…"
            out.append(f"{span:>13}  {r['with_notes']:>2}/{r['pages']:<2}  {r['statements']:>5}  {title}")
        out += [
            "",
            f"totals: {sum(r['pages'] for r in rows)} pages, "
            f"{sum(r['statements'] for r in rows)} statements, "
            f"{sum(r['evidence'] for r in rows)} evidence",
        ]
        return "\n".join(out)

    fp = report.inputs_fingerprint(input, notes_dir)
    report.emit(workspace.compose_stage_dir(notes_dir, "chapter-map") / "chapters.txt", fp, force, render, label="tnotes chapters")


@app.command()
def feedback(
    message: str = typer.Argument(None, help="What went wrong. Prompted for if omitted."),
    doc: Path = typer.Option(
        None, "--doc", exists=True, dir_okay=False,
        help="The PDF the problem is about — its .tnotes notes + page range are bundled for reproduction.",
    ),
    pages: str = typer.Option(
        None, "--pages", "-p",
        help="Restrict the bundled notes to a page range: '12', '10-14', or '10,12'. Default: all the doc's notes.",
    ),
):
    """Report a problem — files a structured issue into the private feedback repo.

    Captures diagnostics (version, OS, your message), bundles the referenced
    document's notes + page range for reproduction, AI-structures the report, and —
    with the feedback repo + token configured and your consent — files it as a
    GitHub issue. When that isn't possible (unconfigured, offline, expired token, or
    you decline the upload), it saves everything to a local file so feedback is never
    lost. The bundle carries verbatim source excerpts, so you're shown exactly what
    will be uploaded and asked before anything leaves your machine.
    """
    from . import feedback as feedbackmod

    if not message:
        message = typer.prompt("What went wrong?").strip()
    if not message:
        typer.echo("No message entered — nothing to report.", err=True)
        raise typer.Exit(1)

    # Reporter name: asked once, then remembered (every report is tagged with it,
    # because the PAT authors as the maintainer's account, not the user's).
    reporter = config.get_reporter_name()
    if not reporter:
        reporter = typer.prompt("Your name (remembered for next time)").strip()
        if reporter:
            config.set_reporter_name(reporter)

    def confirm(preview: str) -> bool:
        typer.echo(preview)
        return typer.confirm("\nSend this?", default=False)

    def log(msg: str) -> None:
        typer.echo(msg, err=True)

    # The bundle and any local fallback land in the document's own .tnotes folder
    # when a doc is given (keeps repro data beside its source), else the config dir.
    fallback_dir = workspace.work_dir(doc) if doc else config.config_dir()

    outcome = feedbackmod.run_feedback(
        message,
        reporter=reporter or "(anonymous)",
        doc=doc,
        pages=pages,
        model=config.resolve_model(None),
        api_key=config.get_api_key(),
        repo=config.get_feedback_repo(),
        token=config.get_feedback_token(),
        fallback_dir=fallback_dir,
        confirm=confirm,
        log=log,
    )

    if outcome.filed:
        typer.echo(f"Sent — thanks, {outcome.reporter}.")
        typer.echo(f"(issue: {outcome.location})", err=True)
    else:
        typer.echo(f"Saved your report to {outcome.location}")
        if outcome.reason:
            typer.echo(f"({outcome.reason} — send that file to the maintainer)", err=True)


@app.command()
def upgrade():
    """Update the installed tnotes.exe in place from the latest GitHub Release.

    Checks the latest release; if it is newer than the running build, downloads its
    tnotes.exe, verifies the published SHA-256 checksum, confirms the download is
    launchable, and swaps it into place fail-safely (a failed or interrupted upgrade
    always leaves the current working exe untouched). If you are already up to date
    it says so and does nothing; from a source checkout it explains that upgrade
    applies to the packaged exe only (use `git pull`). Trust model: GitHub over TLS
    is the trust root; the SHA-256 guards against a corrupted download.
    """
    from . import updater

    def log(msg: str) -> None:
        typer.echo(msg, err=True)

    try:
        outcome = updater.upgrade(log=log)
    except updater.UpgradeError as exc:
        typer.echo(f"tnotes upgrade: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(outcome.message)


if __name__ == "__main__":
    app()
