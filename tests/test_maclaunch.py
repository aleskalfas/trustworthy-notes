"""Tests for the macOS-only droplet mechanics (issues #69, #102).

The real trigger — a Finder drag onto a compiled droplet that opens Terminal — can't
be exercised on Linux/CI, and we never run the real `osacompile` against the real
Desktop here, so these stub the platform check, the path resolver, and `subprocess` to
drive every branch. Both droplets — "Send Feedback" (`tnotes feedback <pdf>`) and
"Make Notes" (the bare `tnotes <pdf>` book flow) — share one builder, so we assert each
one's `osacompile` invocation, its baked absolute path and (for feedback) `feedback`
subcommand, its safe quoting of a dropped path, and its off-macOS no-op with
`subprocess` mocked. First real validation of the live droplet is a macOS run (mirroring
how `winlaunch`'s `.lnk` is validated on Windows).
"""

from __future__ import annotations

import subprocess

from trustworthy_notes import maclaunch


# --- create_feedback_droplet: macOS gate (off-Darwin → no-op, no subprocess) -------


def test_droplet_is_a_noop_off_macos(monkeypatch):
    monkeypatch.setattr(maclaunch.platform, "system", lambda: "Windows")

    def must_not_shell_out(*_a, **_k):
        raise AssertionError("must not shell out off macOS")

    monkeypatch.setattr(maclaunch.subprocess, "run", must_not_shell_out)
    assert maclaunch.create_feedback_droplet() is False


# --- create_feedback_droplet: osacompile invocation + baked absolute path ----------


def test_droplet_compiles_with_baked_absolute_path_and_feedback_subcommand(monkeypatch):
    monkeypatch.setattr(maclaunch.platform, "system", lambda: "Darwin")
    # Pin the resolver so the bake is deterministic — an absolute install path.
    monkeypatch.setattr(
        maclaunch, "_resolve_tnotes_path", lambda _arg: "/Users/me/.local/bin/tnotes"
    )

    captured = {}

    def fake_run(argv, **_k):
        captured["argv"] = argv
        # Read back the compiled source so we can assert on what got baked in.
        captured["source"] = _read_script_from_argv(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(maclaunch.subprocess, "run", fake_run)

    assert maclaunch.create_feedback_droplet() is True
    argv = captured["argv"]
    # osacompile -o "<Desktop>/Send Feedback.app" <script>
    assert argv[0] == "osacompile"
    assert "-o" in argv
    out_path = argv[argv.index("-o") + 1]
    assert out_path.endswith("Desktop/Send Feedback.app")

    source = captured["source"]
    # The absolute tnotes path is baked in, with the feedback subcommand, and both the
    # drag handler and the double-click handler are present.
    assert "/Users/me/.local/bin/tnotes" in source
    assert "feedback" in source
    assert "on open theFiles" in source
    assert "on run" in source
    assert 'tell application "Terminal"' in source


def test_droplet_quotes_dropped_path_safely(monkeypatch):
    """The droplet uses AppleScript's own shell-quoting for the dropped file's path.

    A Finder drop hands the script an arbitrary POSIX path; the generated AppleScript
    must shell-quote it (`quoted form of POSIX path of f`) rather than splicing it raw,
    so a path with spaces or shell metacharacters can't break the command.
    """
    monkeypatch.setattr(maclaunch.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(maclaunch, "_resolve_tnotes_path", lambda _arg: "/abs/tnotes")

    captured = {}

    def fake_run(argv, **_k):
        captured["source"] = _read_script_from_argv(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(maclaunch.subprocess, "run", fake_run)
    assert maclaunch.create_feedback_droplet() is True
    assert "quoted form of POSIX path of f" in captured["source"]


def test_droplet_shell_quotes_a_tnotes_path_with_spaces(monkeypatch):
    """A baked tnotes path containing spaces is shell-quoted, not spliced raw."""
    monkeypatch.setattr(maclaunch.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        maclaunch,
        "_resolve_tnotes_path",
        lambda _arg: "/Users/me/Application Support/tnotes",
    )

    captured = {}

    def fake_run(argv, **_k):
        captured["source"] = _read_script_from_argv(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(maclaunch.subprocess, "run", fake_run)
    assert maclaunch.create_feedback_droplet() is True
    # shlex.quote wraps a spaced path in single quotes inside the baked command.
    assert "'/Users/me/Application Support/tnotes'" in captured["source"]


# --- create_feedback_droplet: fail-safe (osacompile failure / missing) -------------


def test_droplet_returns_false_when_osacompile_fails(monkeypatch):
    monkeypatch.setattr(maclaunch.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(maclaunch, "_resolve_tnotes_path", lambda _arg: "/abs/tnotes")

    def fake_run(argv, **_k):
        return subprocess.CompletedProcess(argv, 1, b"", b"boom")

    monkeypatch.setattr(maclaunch.subprocess, "run", fake_run)
    assert maclaunch.create_feedback_droplet() is False


def test_droplet_returns_false_when_osacompile_missing(monkeypatch):
    monkeypatch.setattr(maclaunch.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(maclaunch, "_resolve_tnotes_path", lambda _arg: "/abs/tnotes")

    def fake_run(*_a, **_k):
        raise OSError("osacompile not found")

    monkeypatch.setattr(maclaunch.subprocess, "run", fake_run)
    assert maclaunch.create_feedback_droplet() is False


# --- create_make_notes_droplet: book flow, no `feedback` token (issue #102) --------


def test_make_notes_droplet_is_a_noop_off_macos(monkeypatch):
    monkeypatch.setattr(maclaunch.platform, "system", lambda: "Windows")

    def must_not_shell_out(*_a, **_k):
        raise AssertionError("must not shell out off macOS")

    monkeypatch.setattr(maclaunch.subprocess, "run", must_not_shell_out)
    assert maclaunch.create_make_notes_droplet() is False


def test_make_notes_droplet_compiles_bare_tnotes_with_no_feedback_token(monkeypatch):
    monkeypatch.setattr(maclaunch.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        maclaunch, "_resolve_tnotes_path", lambda _arg: "/Users/me/.local/bin/tnotes"
    )

    captured = {}

    def fake_run(argv, **_k):
        captured["argv"] = argv
        captured["source"] = _read_script_from_argv(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(maclaunch.subprocess, "run", fake_run)

    assert maclaunch.create_make_notes_droplet() is True
    argv = captured["argv"]
    # osacompile -o "<Desktop>/Make Notes.app" <script>
    assert argv[0] == "osacompile"
    assert "-o" in argv
    out_path = argv[argv.index("-o") + 1]
    assert out_path.endswith("Desktop/Make Notes.app")

    source = captured["source"]
    # The absolute tnotes path is baked in and both handlers are present, but this is
    # the bare book flow — there is NO `feedback` subcommand anywhere in the script.
    assert "/Users/me/.local/bin/tnotes" in source
    assert "feedback" not in source
    assert "on open theFiles" in source
    assert "on run" in source
    assert 'tell application "Terminal"' in source


def test_make_notes_droplet_passes_the_dropped_file_as_the_argument(monkeypatch):
    """The dropped PDF is the bare positional arg, shell-quoted by AppleScript itself."""
    monkeypatch.setattr(maclaunch.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(maclaunch, "_resolve_tnotes_path", lambda _arg: "/abs/tnotes")

    captured = {}

    def fake_run(argv, **_k):
        captured["source"] = _read_script_from_argv(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(maclaunch.subprocess, "run", fake_run)
    assert maclaunch.create_make_notes_droplet() is True
    assert "quoted form of POSIX path of f" in captured["source"]


def test_make_notes_droplet_returns_false_when_osacompile_fails(monkeypatch):
    monkeypatch.setattr(maclaunch.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(maclaunch, "_resolve_tnotes_path", lambda _arg: "/abs/tnotes")

    def fake_run(argv, **_k):
        return subprocess.CompletedProcess(argv, 1, b"", b"boom")

    monkeypatch.setattr(maclaunch.subprocess, "run", fake_run)
    assert maclaunch.create_make_notes_droplet() is False


def test_make_notes_droplet_returns_false_when_osacompile_missing(monkeypatch):
    monkeypatch.setattr(maclaunch.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(maclaunch, "_resolve_tnotes_path", lambda _arg: "/abs/tnotes")

    def fake_run(*_a, **_k):
        raise OSError("osacompile not found")

    monkeypatch.setattr(maclaunch.subprocess, "run", fake_run)
    assert maclaunch.create_make_notes_droplet() is False


# --- path resolution: arg > which > argv[0], always absolute -----------------------


def test_resolve_prefers_explicit_arg(monkeypatch):
    monkeypatch.setattr(maclaunch.shutil, "which", lambda _n: "/should/not/be/used")
    assert maclaunch._resolve_tnotes_path("/explicit/tnotes") == "/explicit/tnotes"


def test_resolve_falls_back_to_which(monkeypatch):
    monkeypatch.setattr(maclaunch.shutil, "which", lambda _n: "/usr/local/bin/tnotes")
    assert maclaunch._resolve_tnotes_path(None) == "/usr/local/bin/tnotes"


def test_resolve_falls_back_to_argv0_when_not_on_path(monkeypatch):
    monkeypatch.setattr(maclaunch.shutil, "which", lambda _n: None)
    monkeypatch.setattr(maclaunch.sys, "argv", ["/run/from/here/tnotes"])
    assert maclaunch._resolve_tnotes_path(None) == "/run/from/here/tnotes"


# --- isolation: the pipeline / feedback never import this module --------------------


def test_maclaunch_does_not_import_the_pipeline():
    """OS-integration isolation (ADR-005 + ARCHITECTURE.md §4): maclaunch is a leaf
    OS-glue module the pipeline never imports, and it carries no network surface."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(maclaunch))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[-1])
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[-1])
    assert imported.isdisjoint({"pipeline", "compose", "ingest", "extract", "feedback"})


def _read_script_from_argv(argv: list[str]) -> str:
    """Read the .applescript source osacompile was pointed at (the last argv token)."""
    from pathlib import Path

    return Path(argv[-1]).read_text(encoding="utf-8")
