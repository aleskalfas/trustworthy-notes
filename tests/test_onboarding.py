"""Tests for the first-run onboarding flow (issues #33, #39).

The real trigger — a Windows double-click that gives the exe its own console —
can't be exercised on macOS/Linux/CI, so these stub `input` and the config setters
to drive every branch: the API-key prompt (extracted from `winlaunch` unchanged),
the optional feedback-setup step (opt-in stores repo/token/name; declining skips
cleanly), and the one-tap desktop-shortcut offer. First real validation of the
live windowless path is a Windows run of the packaged exe.
"""

from __future__ import annotations

import builtins

import pytest

from trustworthy_notes import config, feedback, onboarding, winlaunch


def _stub_listing(monkeypatch, *, available, reason=None):
    """Stub the read-only connection check that setup_feedback now runs (issue #47).

    setup_feedback verifies repo+token via feedback.list_recent_issues before
    saving; tests drive both the success and failure paths through this stub so no
    network is touched. Records the (repo, token) pairs it was called with.
    """
    calls = []

    def fake(repo, token, **_kw):
        calls.append((repo, token))
        return feedback.IssueListing(available=available, reason=reason)

    monkeypatch.setattr(feedback, "list_recent_issues", fake)
    return calls


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point the config at a throwaway dir and clear the auth env/login signals."""
    monkeypatch.setenv("TN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # auth_source() also checks ~/.config/anthropic; force a clean "none".
    monkeypatch.setattr(config, "auth_source", _real_then())
    return tmp_path


def _real_then():
    # auth_source must reflect the saved key after we write it, so we delegate to a
    # live reimplementation keyed only on the saved config (env already cleared).
    def fn():
        return "config" if config.get_api_key() else "none"

    return fn


def _scripted_input(answers):
    """An `input` stub that returns the queued answers in order."""
    queue = list(answers)

    def fake_input(_prompt=""):
        return queue.pop(0)

    return fake_input


# --- ensure_api_key: prompt + save on first run (unchanged after extraction) -------


def test_ensure_api_key_prompts_and_saves_when_unset(isolated_config, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "sk-ant-test-123")
    assert config.get_api_key() is None
    assert onboarding.ensure_api_key() is True
    assert config.get_api_key() == "sk-ant-test-123"


def test_ensure_api_key_returns_false_on_empty_input(isolated_config, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "   ")
    assert onboarding.ensure_api_key() is False
    assert config.get_api_key() is None


def test_ensure_api_key_skips_prompt_when_already_set(isolated_config, monkeypatch):
    config.set_api_key("sk-already-there")

    def must_not_prompt(_p=""):
        raise AssertionError("must not prompt when a key is already configured")

    monkeypatch.setattr(builtins, "input", must_not_prompt)
    assert onboarding.ensure_api_key() is True


# --- setup_feedback: opt-in stores repo/token/name; declining skips cleanly --------


def test_setup_feedback_stores_token_and_name_against_default_repo(isolated_config, monkeypatch):
    # #53: token-only happy path. The repo is the built-in default (nothing stored);
    # the user pastes only the token and their name, and both are saved against it.
    calls = _stub_listing(monkeypatch, available=True)
    monkeypatch.setattr(
        builtins,
        "input",
        _scripted_input(["ghp_test_token", "Ada Lovelace"]),
    )
    assert onboarding.setup_feedback() is True
    assert config.get_feedback_repo() == config.DEFAULT_FEEDBACK_REPO
    assert config.get_feedback_token() == "ghp_test_token"
    assert config.get_reporter_name() == "Ada Lovelace"
    assert calls == [(config.DEFAULT_FEEDBACK_REPO, "ghp_test_token")]


def test_setup_feedback_name_is_optional(isolated_config, monkeypatch):
    # #53: an explicitly configured repo overrides the default; token + Enter-to-skip-name.
    config.set_feedback_repo("acme/fb")
    _stub_listing(monkeypatch, available=True)
    monkeypatch.setattr(
        builtins, "input", _scripted_input(["ghp_tok", ""])
    )
    assert onboarding.setup_feedback() is True
    assert config.get_feedback_repo() == "acme/fb"
    assert config.get_feedback_token() == "ghp_tok"
    assert config.get_reporter_name() is None


def test_setup_feedback_token_only_against_configured_repo(isolated_config, monkeypatch):
    # #53: the maintainer pre-seeded the repo; the end user only pastes the token
    # and the connection check runs against the configured repo.
    config.set_feedback_repo("acme/preseeded")
    calls = _stub_listing(monkeypatch, available=True)
    monkeypatch.setattr(builtins, "input", _scripted_input(["ghp_tok", ""]))
    assert onboarding.setup_feedback() is True
    assert config.get_feedback_repo() == "acme/preseeded"
    assert config.get_feedback_token() == "ghp_tok"
    assert calls == [("acme/preseeded", "ghp_tok")]


def test_setup_feedback_skips_when_token_left_blank(isolated_config, monkeypatch):
    # #53: the token is the single, one-keypress skip. Enter at the first (token)
    # prompt stores nothing — not even the repo (the default is only a read-time
    # fallback, never persisted on a skip).
    monkeypatch.setattr(builtins, "input", _scripted_input([""]))
    assert onboarding.setup_feedback() is False
    assert config.get_feedback_token() is None
    # Nothing was persisted: the repo read-back is the unconfigured default, and the
    # raw config carries no stored repo key.
    assert config.load().get("feedback_repo") is None


def test_setup_feedback_dirty_url_default_is_normalised_on_read(isolated_config, monkeypatch):
    # #50/#53 defensive: a config dirtied before the storage fix (a full URL stored
    # as feedback_repo) is canonicalised by get_feedback_repo() on read, so the
    # token-only flow runs the connection check against owner/name (not the 404ing
    # URL) and saves the clean owner/name back. No upfront repo prompt is involved.
    raw = config.load()
    raw["feedback_repo"] = "https://github.com/acme/preseeded"
    config.save(raw)
    calls = _stub_listing(monkeypatch, available=True)
    monkeypatch.setattr(builtins, "input", _scripted_input(["ghp_tok", ""]))
    assert onboarding.setup_feedback() is True
    assert config.get_feedback_repo() == "acme/preseeded"
    assert calls == [("acme/preseeded", "ghp_tok")]


def test_setup_feedback_failed_check_then_retry_succeeds(isolated_config, monkeypatch):
    # #47/#53: first token fails the check; user re-enters (r), keeps the repo
    # (Enter at the retry-only repo prompt), pastes a good token, and the second
    # check passes and saves. The repo is the built-in default throughout.
    listings = iter(
        [
            feedback.IssueListing(available=False, reason="feedback token rejected (401)"),
            feedback.IssueListing(available=True),
        ]
    )
    seen = []

    def fake(repo, token, **_kw):
        seen.append((repo, token))
        return next(listings)

    monkeypatch.setattr(feedback, "list_recent_issues", fake)
    # token → name → choice [r] → repo (Enter keeps default) → new token.
    monkeypatch.setattr(
        builtins,
        "input",
        _scripted_input(["ghp_bad", "Ada", "r", "", "ghp_good"]),
    )
    assert onboarding.setup_feedback() is True
    assert config.get_feedback_token() == "ghp_good"
    assert config.get_reporter_name() == "Ada"
    default = config.DEFAULT_FEEDBACK_REPO
    assert seen == [(default, "ghp_bad"), (default, "ghp_good")]


def test_setup_feedback_failed_check_retry_can_change_repo(isolated_config, monkeypatch):
    # #53: the retry path keeps the URL-tolerant change-the-repo capability —
    # the user re-enters (r), types a *different* repo (as a pasted URL, to prove
    # _prompt_repo still normalises), and a fresh token, and the new pair is saved.
    listings = iter(
        [
            feedback.IssueListing(available=False, reason="feedback token rejected (401)"),
            feedback.IssueListing(available=True),
        ]
    )
    seen = []

    def fake(repo, token, **_kw):
        seen.append((repo, token))
        return next(listings)

    monkeypatch.setattr(feedback, "list_recent_issues", fake)
    # token → name → choice [r] → new repo (pasted URL) → new token.
    monkeypatch.setattr(
        builtins,
        "input",
        _scripted_input(["ghp_bad", "", "r", "https://github.com/acme/other.git", "ghp_good"]),
    )
    assert onboarding.setup_feedback() is True
    assert config.get_feedback_repo() == "acme/other"
    assert config.get_feedback_token() == "ghp_good"
    default = config.DEFAULT_FEEDBACK_REPO
    assert seen == [(default, "ghp_bad"), ("acme/other", "ghp_good")]


def test_setup_feedback_failed_check_proceed_anyway_saves(isolated_config, monkeypatch, capsys):
    # #47/#53: an offline-but-correct setup must stay possible by explicit choice —
    # the check fails, the user chooses [p] and the details are saved unverified.
    config.set_feedback_repo("acme/fb")
    _stub_listing(monkeypatch, available=False, reason="could not reach the feedback repo")
    # token → name → choice [p].
    monkeypatch.setattr(
        builtins, "input", _scripted_input(["ghp_tok", "", "p"])
    )
    assert onboarding.setup_feedback() is True
    assert config.get_feedback_repo() == "acme/fb"
    assert config.get_feedback_token() == "ghp_tok"
    out = capsys.readouterr().out
    assert "could not reach the feedback repo" in out


def test_setup_feedback_failed_check_skip_saves_nothing(isolated_config, monkeypatch):
    # #47/#53: the check fails and the user chooses [s] — nothing broken is saved.
    config.set_feedback_repo("acme/fb")
    _stub_listing(monkeypatch, available=False, reason="feedback token rejected (401)")
    # token → name → choice [s].
    monkeypatch.setattr(
        builtins, "input", _scripted_input(["ghp_tok", "", "s"])
    )
    assert onboarding.setup_feedback() is False
    assert config.get_feedback_token() is None


def test_setup_feedback_short_circuits_when_token_configured(isolated_config, monkeypatch):
    # #53: the gate is the token alone — the repo is always present (default or
    # override), so a configured token is enough to short-circuit without nagging.
    config.set_feedback_token("ghp_existing")

    def must_not_prompt(_p=""):
        raise AssertionError("must not prompt when the feedback token is already set")

    monkeypatch.setattr(builtins, "input", must_not_prompt)
    assert onboarding.setup_feedback() is True


# --- seed_language: first-run-only OS-locale seed of the reading language (#114) ----


def test_seed_language_offers_os_default_and_persists_on_enter(isolated_config, monkeypatch):
    # #114: nothing configured → offer the OS-detected default; a bare Enter accepts it.
    monkeypatch.setattr(config, "detect_os_language", lambda: "cs")
    monkeypatch.setattr(builtins, "input", lambda _p="": "")  # Enter
    assert config.get_language() is None
    onboarding.seed_language()
    assert config.get_language() == "cs"


def test_seed_language_persists_typed_override(isolated_config, monkeypatch):
    # #114: the user can type a different code, which is persisted instead of the default.
    monkeypatch.setattr(config, "detect_os_language", lambda: "en")
    monkeypatch.setattr(builtins, "input", lambda _p="": "ja")
    onboarding.seed_language()
    assert config.get_language() == "ja"


def test_seed_language_falls_back_to_built_in_when_os_undetectable(isolated_config, monkeypatch):
    # #114: an undeterminable OS locale → the built-in default is offered and accepted.
    monkeypatch.setattr(config, "detect_os_language", lambda: None)
    monkeypatch.setattr(builtins, "input", lambda _p="": "")
    onboarding.seed_language()
    assert config.get_language() == config.DEFAULT_LANGUAGE


def test_seed_language_does_not_nag_when_already_set(isolated_config, monkeypatch):
    # #114: a returning user who has a language configured is never prompted.
    config.set_language("de")

    def must_not_prompt(_p=""):
        raise AssertionError("must not prompt when a language is already configured")

    monkeypatch.setattr(builtins, "input", must_not_prompt)
    onboarding.seed_language()
    assert config.get_language() == "de"  # unchanged


# --- seed_book_citations: first-run-only seed of the book-citations default (#154) --


def test_seed_book_citations_asks_once_and_persists_yes(isolated_config, monkeypatch):
    # #154: nothing configured → ask; a bare Enter accepts the offered "yes" (on).
    monkeypatch.setattr(builtins, "input", lambda _p="": "")  # Enter
    assert config.get_book_citations() is None
    onboarding.seed_book_citations()
    assert config.get_book_citations() is True


def test_seed_book_citations_persists_no(isolated_config, monkeypatch):
    # #154: an explicit "n" flips the default to off (clean reading copy).
    monkeypatch.setattr(builtins, "input", lambda _p="": "n")
    onboarding.seed_book_citations()
    assert config.get_book_citations() is False


def test_seed_book_citations_does_not_nag_when_already_set(isolated_config, monkeypatch):
    # #154: a returning user who has set the default is never prompted, even to off.
    config.set_book_citations(False)

    def must_not_prompt(_p=""):
        raise AssertionError("must not prompt when the citations default is already set")

    monkeypatch.setattr(builtins, "input", must_not_prompt)
    onboarding.seed_book_citations()
    assert config.get_book_citations() is False  # unchanged


def test_seed_book_citations_fail_safe_on_eof_defaults_to_yes(isolated_config, monkeypatch):
    # #154: a non-interactive run (EOF) keeps the offered "yes" and persists it (on).
    def raise_eof(_p=""):
        raise EOFError

    monkeypatch.setattr(builtins, "input", raise_eof)
    onboarding.seed_book_citations()
    assert config.get_book_citations() is True


def test_seed_language_is_eof_safe_keeps_default(isolated_config, monkeypatch):
    # #114: a non-interactive run (EOF) keeps the offered default — fail-safe, no crash.
    monkeypatch.setattr(config, "detect_os_language", lambda: "cs")

    def eof(_p=""):
        raise EOFError

    monkeypatch.setattr(builtins, "input", eof)
    onboarding.seed_language()
    assert config.get_language() == "cs"


# --- normalise_feedback_repo: forgiving URL → owner/name (issue #47) ----------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("acme/fb", "acme/fb"),
        ("  acme/fb  ", "acme/fb"),
        ("https://github.com/acme/fb", "acme/fb"),
        ("https://github.com/acme/fb/", "acme/fb"),
        ("https://github.com/acme/fb.git", "acme/fb"),
        ("http://www.github.com/acme/fb", "acme/fb"),
        ("git@github.com:acme/fb.git", "acme/fb"),
        ("HTTPS://GitHub.com/acme/fb", "acme/fb"),
    ],
)
def test_normalise_feedback_repo(raw, expected):
    assert onboarding.normalise_feedback_repo(raw) == expected


# --- offer_desktop_shortcuts: one combined confirm gates both (mocked) primitives ---


def _count_both(monkeypatch, *, make_notes=True, feedback_ok=True):
    """Stub both shortcut primitives, counting calls; return the counter dict."""
    calls = {"make_notes": 0, "feedback": 0}

    def fake_make():
        calls["make_notes"] += 1
        return make_notes

    def fake_feedback():
        calls["feedback"] += 1
        return feedback_ok

    monkeypatch.setattr(winlaunch, "create_make_notes_shortcut", fake_make)
    monkeypatch.setattr(winlaunch, "create_feedback_shortcut", fake_feedback)
    return calls


def test_shortcut_offer_creates_both_on_yes(monkeypatch, capsys):
    monkeypatch.setattr(builtins, "input", lambda _p="": "y")
    calls = _count_both(monkeypatch)
    onboarding.offer_desktop_shortcuts()
    assert calls == {"make_notes": 1, "feedback": 1}
    out = capsys.readouterr().out
    # Both are reported on their own line — one combined confirm, two outcomes.
    assert "Added a Make Notes shortcut" in out
    assert "Added a Send Feedback shortcut" in out


def test_shortcut_offer_defaults_to_yes_on_enter(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "")
    calls = _count_both(monkeypatch)
    onboarding.offer_desktop_shortcuts()
    assert calls == {"make_notes": 1, "feedback": 1}


def test_shortcut_offer_reports_each_independently(monkeypatch, capsys):
    # One failing must not hide the other: Make Notes fails, Send Feedback succeeds —
    # both are attempted and each reports its own outcome.
    monkeypatch.setattr(builtins, "input", lambda _p="": "y")
    calls = _count_both(monkeypatch, make_notes=False, feedback_ok=True)
    onboarding.offer_desktop_shortcuts()
    assert calls == {"make_notes": 1, "feedback": 1}
    out = capsys.readouterr().out
    assert "Couldn't create the Make Notes shortcut" in out
    assert "Added a Send Feedback shortcut" in out


def test_shortcut_offer_declines_on_no(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "n")

    def must_not_create():
        raise AssertionError("must not create a shortcut when the user declines")

    monkeypatch.setattr(winlaunch, "create_make_notes_shortcut", must_not_create)
    monkeypatch.setattr(winlaunch, "create_feedback_shortcut", must_not_create)
    onboarding.offer_desktop_shortcuts()  # no exception → declined cleanly


# --- onboard: end-to-end flow stitches the steps together -------------------------


def test_onboard_full_optin_flow_stores_everything(isolated_config, monkeypatch, capsys):
    # Key prompt, then the language seed (#114, Enter accepts the OS default), then the
    # book-citations seed (#154, Enter accepts the default on), then token/name
    # (token-only feedback, #53), then 'y' to the shortcut offer. The feedback repo is
    # the built-in default.
    _stub_listing(monkeypatch, available=True)
    monkeypatch.setattr(config, "detect_os_language", lambda: "cs")
    monkeypatch.setattr(
        builtins,
        "input",
        _scripted_input(["sk-ant-onboard", "", "", "ghp_tok", "Grace", "y"]),
    )
    monkeypatch.setattr(winlaunch, "create_make_notes_shortcut", lambda: True)
    monkeypatch.setattr(winlaunch, "create_feedback_shortcut", lambda: True)
    onboarding.onboard()
    out = capsys.readouterr().out
    assert config.get_api_key() == "sk-ant-onboard"
    assert config.get_language() == "cs"  # seeded from the OS default
    assert config.get_feedback_repo() == config.DEFAULT_FEEDBACK_REPO
    assert config.get_feedback_token() == "ghp_tok"
    assert config.get_reporter_name() == "Grace"
    assert "Drag a PDF" in out


def test_onboard_key_then_skip_feedback(isolated_config, monkeypatch, capsys):
    # Key set, language seeded (Enter accepts the default), book-citations seeded
    # (Enter accepts on), but the user skips feedback (empty token): no shortcut
    # offer reached.
    monkeypatch.setattr(config, "detect_os_language", lambda: "en")
    monkeypatch.setattr(builtins, "input", _scripted_input(["sk-ant-onboard", "", "", ""]))

    def must_not_create():
        raise AssertionError("shortcut offer must not run when feedback was skipped")

    monkeypatch.setattr(winlaunch, "create_make_notes_shortcut", must_not_create)
    monkeypatch.setattr(winlaunch, "create_feedback_shortcut", must_not_create)
    onboarding.onboard()
    out = capsys.readouterr().out
    assert config.get_api_key() == "sk-ant-onboard"
    assert config.get_feedback_token() is None
    assert "Drag a PDF" in out


def test_onboard_returns_early_when_no_key(isolated_config, monkeypatch):
    # No key entered: we don't pile feedback questions on a user who isn't ready.
    monkeypatch.setattr(builtins, "input", _scripted_input([""]))

    def must_not_run(*_a, **_k):
        raise AssertionError("feedback setup must not run without a key")

    monkeypatch.setattr(onboarding, "setup_feedback", must_not_run)
    onboarding.onboard()
    assert config.get_api_key() is None
