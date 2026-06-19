"""Encoding hardening for the CLI entry point (issue #26).

The Windows release smoke test crashed running ``tnotes.exe --help``: the help
text contains non-ASCII (the ``→`` arrow) and, when Windows stdout isn't UTF-8
(redirected/captured output, or a legacy cp1252 console), the default codec
raises UnicodeEncodeError and the process dies. The fix forces UTF-8 on
stdout/stderr at import time of ``cli``. We can't reproduce the Windows console
locally, so these tests assert the mechanism rather than the OS behaviour.
"""

from __future__ import annotations

import io
import sys

from trustworthy_notes import cli


class _Reconfigurable(io.StringIO):
    """A stream that records the encoding it was reconfigured to."""

    reconfigured_to: str | None = None

    def reconfigure(self, *, encoding=None, **kwargs):  # noqa: D401 - test double
        self.reconfigured_to = encoding


def test_force_utf8_reconfigures_both_streams(monkeypatch):
    out, err = _Reconfigurable(), _Reconfigurable()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    cli._force_utf8_streams()

    assert out.reconfigured_to == "utf-8"
    assert err.reconfigured_to == "utf-8"


def test_force_utf8_is_a_no_op_when_reconfigure_unavailable(monkeypatch):
    # A plain StringIO has no reconfigure(); the guard must swallow AttributeError
    # rather than let it propagate (mirrors an already-wrapped/captured stream).
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    cli._force_utf8_streams()  # must not raise


def test_help_arrow_encodes_to_a_legacy_codepage_after_reconfigure(monkeypatch):
    # Reproduce the failure shape: a buffer whose codec can't encode '→'. Before
    # the fix the help render would raise UnicodeEncodeError on it; after forcing
    # UTF-8 on the text wrapper, the same '→' encodes cleanly.
    raw = io.BytesIO()
    legacy = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", legacy)

    cli._force_utf8_streams()

    sys.stdout.write("extract → compose\n")
    sys.stdout.flush()
    assert "→".encode("utf-8") in raw.getvalue()
