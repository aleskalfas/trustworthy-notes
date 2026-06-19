"""Unit tests for the self-update logic (issue #7).

The actual running-exe swap can only be exercised on Windows (the file-locking
semantics that make the rename dance necessary are Windows-only), and this suite
runs on macOS/Linux CI. So we test the parts that *are* portable: the latest-
release query and checksum verification with a mocked HTTP layer, and the swap's
rename/move/cleanup choreography against temp files (which exercises the ordering
and the rollback even though no exe is genuinely locked here). First real
validation of the live swap is running `tnotes upgrade` on Windows.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from trustworthy_notes import updater
from trustworthy_notes.updater import Release, UpgradeError


def _release_json(tag="v0.2.0", assets=("tnotes.exe", "tnotes.exe.sha256")):
    return json.dumps(
        {
            "tag_name": tag,
            "assets": [
                {"name": name, "browser_download_url": f"https://example/{tag}/{name}"}
                for name in assets
            ],
        }
    ).encode()


# --- version comparison ---


@pytest.mark.parametrize(
    "candidate,current,expected",
    [
        ("0.2.0", "0.1.0", True),
        ("0.1.1", "0.1.0", True),
        ("0.1.0", "0.1.0", False),  # equal is not newer
        ("0.1.0", "0.2.0", False),
        ("1.0.0", "0.9.9", True),
        ("0.2.0-rc1", "0.1.0", True),  # non-numeric suffix tolerated, compares on prefix
    ],
)
def test_is_newer(candidate, current, expected):
    assert updater.is_newer(candidate, current) is expected


# --- latest-release query ---


def test_fetch_latest_release_parses_tag_and_asset_urls():
    rel = updater.fetch_latest_release(get=lambda *a, **k: _release_json("v0.3.0"))
    assert rel == Release(
        tag="v0.3.0",
        version="0.3.0",
        exe_url="https://example/v0.3.0/tnotes.exe",
        checksum_url="https://example/v0.3.0/tnotes.exe.sha256",
    )


def test_fetch_latest_release_rejects_missing_checksum_asset():
    body = _release_json(assets=("tnotes.exe",))  # no .sha256
    with pytest.raises(UpgradeError, match="checksum cannot be verified"):
        updater.fetch_latest_release(get=lambda *a, **k: body)


def test_fetch_latest_release_rejects_missing_exe_asset():
    body = _release_json(assets=("tnotes.exe.sha256",))  # no exe
    with pytest.raises(UpgradeError, match="no tnotes.exe asset"):
        updater.fetch_latest_release(get=lambda *a, **k: body)


def test_fetch_latest_release_rejects_unparseable_body():
    with pytest.raises(UpgradeError, match="unexpected release response"):
        updater.fetch_latest_release(get=lambda *a, **k: b"not json")


# --- checksum verification ---


def test_verify_checksum_accepts_bare_digest():
    data = b"the new exe bytes"
    digest = hashlib.sha256(data).hexdigest()
    updater.verify_checksum(data, digest)  # does not raise


def test_verify_checksum_accepts_sha256sum_form():
    data = b"the new exe bytes"
    digest = hashlib.sha256(data).hexdigest()
    updater.verify_checksum(data, f"{digest}  tnotes.exe\n")  # does not raise


def test_verify_checksum_rejects_a_corrupted_download():
    digest = hashlib.sha256(b"the intended bytes").hexdigest()
    with pytest.raises(UpgradeError, match="failed SHA-256 verification"):
        updater.verify_checksum(b"corrupted bytes", digest)


def test_verify_checksum_rejects_a_non_hex_published_value():
    with pytest.raises(UpgradeError, match="not a SHA-256 hex digest"):
        updater.verify_checksum(b"x", "totally-not-a-digest")


# --- the fail-safe swap ---


def test_swap_in_place_replaces_target_and_leaves_old(tmp_path):
    target = tmp_path / "tnotes.exe"
    target.write_text("OLD running exe")
    new = tmp_path / "staging" / "tnotes.exe"
    new.parent.mkdir()
    new.write_text("NEW verified exe")

    old = updater.swap_in_place(new, target)

    assert target.read_text() == "NEW verified exe"  # new bytes installed
    assert old.read_text() == "OLD running exe"  # prior exe preserved as .old
    assert old.name == "tnotes.exe.old"
    assert not new.exists()  # moved out of staging


def test_swap_in_place_clears_a_prior_old_before_renaming(tmp_path):
    target = tmp_path / "tnotes.exe"
    target.write_text("CURRENT")
    stale_old = tmp_path / "tnotes.exe.old"
    stale_old.write_text("a leftover from a past upgrade")
    new = tmp_path / "new.exe"
    new.write_text("NEW")

    updater.swap_in_place(new, target)

    assert target.read_text() == "NEW"
    assert (tmp_path / "tnotes.exe.old").read_text() == "CURRENT"  # is the just-replaced one


def test_swap_in_place_rolls_back_when_the_move_fails(tmp_path, monkeypatch):
    # Simulate the move-into-place failing AFTER the running exe was renamed away.
    # The fail-safe promise: the user is left with exactly the working exe they had.
    target = tmp_path / "tnotes.exe"
    target.write_text("WORKING exe")
    new = tmp_path / "new.exe"
    new.write_text("NEW exe")

    import os as _os

    real_replace = _os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:  # step 2 = move new -> target
            raise OSError("simulated cross-device / locked failure")
        return real_replace(src, dst)

    monkeypatch.setattr(updater.os, "replace", flaky_replace)

    with pytest.raises(UpgradeError, match="restored the existing build"):
        updater.swap_in_place(new, target)

    assert target.read_text() == "WORKING exe"  # rolled back; never left without an exe
    assert not (tmp_path / "tnotes.exe.old").exists()  # .old was rolled back into place


# --- stale cleanup ---


def test_cleanup_stale_removes_a_leftover_old(tmp_path):
    target = tmp_path / "tnotes.exe"
    old = tmp_path / "tnotes.exe.old"
    old.write_text("a finished old build")
    updater.cleanup_stale(target)
    assert not old.exists()


def test_cleanup_stale_is_silent_when_no_old_exists(tmp_path):
    target = tmp_path / "tnotes.exe"
    updater.cleanup_stale(target)  # must not raise


# --- the end-to-end upgrade, fully mocked ---


def _make_frozen(monkeypatch, tmp_path):
    """Pretend we are a frozen build whose exe lives at tmp_path/tnotes.exe."""
    target = tmp_path / "tnotes.exe"
    target.write_text("OLD running exe")
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setattr(updater, "running_exe_path", lambda: target)
    monkeypatch.setattr(updater, "running_version", lambda: "0.1.0")
    return target


def _stub_get(release_tag, exe_bytes):
    """An injectable HTTP layer: release JSON, then the exe, then its checksum."""
    checksum = hashlib.sha256(exe_bytes).hexdigest().encode()

    def get(url, **_kwargs):
        if url == updater._LATEST_RELEASE_URL:
            return _release_json(release_tag)
        if url.endswith("tnotes.exe.sha256"):
            return checksum
        if url.endswith("tnotes.exe"):
            return exe_bytes
        raise AssertionError(f"unexpected url {url}")

    return get


def test_upgrade_from_source_explains_and_does_nothing(monkeypatch):
    monkeypatch.setattr(updater, "is_frozen", lambda: False)
    outcome = updater.upgrade(get=lambda *a, **k: _release_json())
    assert outcome.status == "not-frozen"
    assert "git pull" in outcome.message


def test_upgrade_up_to_date_does_nothing(monkeypatch, tmp_path):
    target = _make_frozen(monkeypatch, tmp_path)
    outcome = updater.upgrade(get=_stub_get("v0.1.0", b"same version"))
    assert outcome.status == "up-to-date"
    assert target.read_text() == "OLD running exe"  # untouched


def test_upgrade_happy_path_verifies_and_swaps(monkeypatch, tmp_path):
    target = _make_frozen(monkeypatch, tmp_path)
    new_bytes = b"the NEW verified exe bytes"
    # The launchable check would run the real exe; stub it to a pass.
    monkeypatch.setattr(updater, "verify_launchable", lambda _exe: None)

    outcome = updater.upgrade(get=_stub_get("v0.2.0", new_bytes))

    assert outcome.status == "upgraded"
    assert target.read_bytes() == new_bytes  # swapped in
    assert (tmp_path / "tnotes.exe.old").read_text() == "OLD running exe"
    # staging dir cleaned up: only the exe and its .old remain
    assert sorted(p.name for p in tmp_path.iterdir()) == ["tnotes.exe", "tnotes.exe.old"]


def test_upgrade_aborts_on_bad_checksum_without_touching_the_exe(monkeypatch, tmp_path):
    target = _make_frozen(monkeypatch, tmp_path)

    def get(url, **_kwargs):
        if url == updater._LATEST_RELEASE_URL:
            return _release_json("v0.2.0")
        if url.endswith(".sha256"):
            return hashlib.sha256(b"intended bytes").hexdigest().encode()
        return b"CORRUPTED different bytes"  # won't match the checksum

    with pytest.raises(UpgradeError, match="failed SHA-256 verification"):
        updater.upgrade(get=get)

    assert target.read_text() == "OLD running exe"  # never touched
    assert not (tmp_path / "tnotes.exe.old").exists()
    # no staging dir left behind
    assert [p.name for p in tmp_path.iterdir()] == ["tnotes.exe"]


def test_upgrade_aborts_when_download_is_not_launchable(monkeypatch, tmp_path):
    target = _make_frozen(monkeypatch, tmp_path)
    new_bytes = b"checksum-valid but not launchable"

    def fail_launch(_exe):
        raise UpgradeError("downloaded exe is not launchable (boom) — not installing")

    monkeypatch.setattr(updater, "verify_launchable", fail_launch)

    with pytest.raises(UpgradeError, match="not launchable"):
        updater.upgrade(get=_stub_get("v0.2.0", new_bytes))

    assert target.read_text() == "OLD running exe"  # never swapped
    assert not (tmp_path / "tnotes.exe.old").exists()
    assert [p.name for p in tmp_path.iterdir()] == ["tnotes.exe"]
