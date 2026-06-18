"""Output-cache fingerprint — frozen-build keying on build identity, not source."""

from __future__ import annotations

import sys

from trustworthy_notes import build, report


def test_build_identity_is_version_plus_stamp():
    ident = build.build_identity()
    assert ident.startswith(build.__version__ + "+")
    assert ident.endswith("dev")  # default stamp in a checkout


def test_code_identity_hashes_source_in_dev():
    # In a checkout the code identity is the concatenated module source, so it is
    # long (kilobytes) and not the short build-identity string.
    ident = report._code_identity()
    assert len(ident) > 200
    assert b"def read_pages" in ident or b"def " in ident  # real source bytes


def test_code_identity_uses_build_identity_when_frozen(monkeypatch):
    # A frozen build has no .py on disk; the fingerprint must fall back to the
    # baked build identity rather than reading module source.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    ident = report._code_identity()
    assert ident == build.build_identity().encode()


def test_frozen_builds_differing_only_by_stamp_get_distinct_fingerprints(tmp_path, monkeypatch):
    # Two frozen builds with the same version but different code (different stamp)
    # must not collide — otherwise the second reads the first's stale cache.
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake bytes")
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    monkeypatch.setattr(build, "_BUILD_STAMP", "sha-aaaaaaa")
    fp_a = report.inputs_fingerprint(pdf, tmp_path)
    monkeypatch.setattr(build, "_BUILD_STAMP", "sha-bbbbbbb")
    fp_b = report.inputs_fingerprint(pdf, tmp_path)

    assert fp_a != fp_b
