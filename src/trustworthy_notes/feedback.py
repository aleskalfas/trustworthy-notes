"""`tnotes feedback` — file a structured problem report into a private repo.

A non-technical user (running the frozen ``tnotes.exe`` with no GitHub account)
reports a problem; we capture diagnostics + a reproduction bundle, AI-structure
the report, and file it as a GitHub issue in a **private** feedback repo via a
fine-grained PAT — committing the bundle into that repo and linking it. When the
repo/token isn't configured, the user is offline, the token is missing/expired,
or the user declines the upload, we **fall back to a local file** so feedback is
never lost. The full design (forces, credential model, privacy boundary) lives in
the scratchpad note ``2026-06-17-tn-feedback-design.md``.

Isolation: the deterministic pipeline NEVER imports this module. The dependency
arrow is ``cli → feedback`` only — this keeps Waves 0–4 runnable with zero network
and zero second-credential surface (a trust-domain property, per the design note).

Privacy / consent: the bundle carries *verbatim source excerpts* of copyrighted
documents (the same reason ``.tnotes`` notes are git-ignored). So before anything
leaves the machine the caller must show the user exactly what will be uploaded
(diagnostics + the bundle's file list) and get a yes; a no degrades to the local
file. The GitHub HTTP layer is injectable (``post=``/``get=``) so the filing path
is unit-testable without a real repo or PAT.
"""

from __future__ import annotations

import base64
import json
import platform
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import build, config, workspace

# GitHub's REST API; the repo path (owner/name) is filled from config, never
# hardcoded. A short timeout keeps an offline user from hanging — a failed call
# collapses to the local-file fallback.
_GITHUB_API = "https://api.github.com"
_HTTP_TIMEOUT_S = 15


class FeedbackError(RuntimeError):
    """A filing attempt failed in a way the caller should fall back from.

    Raised by the GitHub path (offline, 401/expired token, API error). The caller
    catches it and writes the local-file fallback — feedback is never lost.
    """


@dataclass
class Diagnostics:
    """The always-safe context auto-captured with every report.

    Safe to show and to upload without further consent (no source material): the
    tool version (build identity, so a frozen build is identifiable), the OS, and
    the user's own message. ``reporter`` is the remembered name.
    """

    message: str
    reporter: str
    version: str
    os: str

    def as_text(self) -> str:
        return (
            f"Reported by: {self.reporter}\n"
            f"tnotes version: {self.version}\n"
            f"OS: {self.os}\n\n"
            f"{self.message}"
        )


def capture_diagnostics(message: str, reporter: str) -> Diagnostics:
    """Auto-capture the diagnostics for a report: version via ``build``, OS via
    ``platform``, plus the reporter's name and message."""
    return Diagnostics(
        message=message,
        reporter=reporter,
        version=build.build_identity(),
        os=platform.platform(),
    )


@dataclass
class StructuredReport:
    """The report after AI-structuring (or the raw-text fallback).

    ``ai_structured`` records which path produced it, so the caller can tell the
    user (and so a degraded report is never silently passed off as the polished
    one). ``title`` is the issue title; ``body`` is the issue/file body.
    """

    title: str
    body: str
    ai_structured: bool


# --- Reproduction bundle -------------------------------------------------------


def collect_bundle_files(
    doc: Optional[Path], pages: Optional[str], notes_dir: Optional[Path] = None
) -> list[Path]:
    """The files to bundle for reproduction: the referenced document's ``.tnotes``
    per-page notes, restricted to ``pages`` when a range is given.

    The bundle is the *notes* (verbatim excerpts) + the page range, NOT the source
    PDF (per the design: attach the smallest thing that reproduces). ``doc`` None or
    a missing notes dir yields an empty list — a report with no repro data is still
    valid (e.g. a general comment). ``pages`` uses the same 1-based spec the rest of
    the CLI accepts; an unparseable/empty spec means "all notes for the document".
    """
    if doc is None:
        return []
    work = workspace.work_dir(doc, notes_dir)
    extract = workspace.extract_dir(work)
    if not extract.is_dir():
        return []
    all_notes = sorted(extract.glob("page-*.notes.yaml"))
    wanted = _parse_page_indices(pages) if pages else None
    if wanted is None:
        return all_notes
    return [n for n in all_notes if _page_index_of(n) in wanted]


def _page_index_of(notes_path: Path) -> Optional[int]:
    """The 0-based page index encoded in a ``page-NNNN.notes.yaml`` filename."""
    stem = notes_path.name.split(".")[0]  # "page-0013"
    try:
        return int(stem.split("-")[1])
    except (IndexError, ValueError):
        return None


def _parse_page_indices(spec: str) -> set[int]:
    """Parse a 1-based page spec ('14', '14-18', '14,16') into 0-based indices.

    Mirrors the CLI's ``_parse_pages`` shape, but returns the *indices* the notes
    files are named by (page N → ``page-{N-1:04d}``). Unparseable parts are skipped
    rather than raising — a bad range should not abort a feedback report.
    """
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                out.update(range(int(a), int(b) + 1))
            else:
                out.add(int(part))
        except ValueError:
            continue
    return {n - 1 for n in out if n >= 1}


def write_bundle(files: list[Path], dest: Path) -> Path:
    """Zip ``files`` into ``dest`` (a ``.zip``), preserving just the filename.

    Flat archive — the notes filenames already encode the page index, so a flat
    layout is unambiguous and avoids leaking the user's directory structure. Returns
    ``dest``. An empty file list still produces a (valid, empty) zip so the caller
    has a stable artifact to reference.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=f.name)
    return dest


# --- AI structuring (with raw-text fallback) -----------------------------------

_STRUCTURE_SYSTEM = """You turn a user's raw problem report about a CLI tool into a \
clean bug report. Return ONLY a JSON object with two string fields:
  "title": a short, specific one-line summary (no trailing period).
  "body": markdown with three sections — "## Summary", "## Reproduction", and
          "## Diagnostics" — restating the user's report clearly. Preserve every
          concrete detail (page numbers, document names, error text). Do not invent
          facts the user did not give. Keep the user's own words where they are clear.
Output the JSON object and nothing else."""


def structure_report(
    diagnostics: Diagnostics,
    *,
    model: str,
    api_key: Optional[str],
    client: Optional[object] = None,
) -> StructuredReport:
    """AI-structure the raw report into title / summary / reproduction via Claude.

    Falls back to a plain raw-text report (``ai_structured=False``) whenever the
    structured path can't run or fails: no API key, the ``anthropic`` SDK or call
    raising, or a response we can't parse. The fallback always succeeds, so a report
    is never lost to a flaky model — it just ships less polished. ``client`` is an
    injection seam for tests (an object exposing ``messages.create``); in production
    it is built from ``api_key``.
    """
    if client is None and not api_key:
        return _raw_report(diagnostics)
    try:
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=2000,
            system=_STRUCTURE_SYSTEM,
            messages=[{"role": "user", "content": diagnostics.as_text()}],
        )
        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            return _raw_report(diagnostics)
        data = json.loads(_strip_code_fence(text))
        title = str(data["title"]).strip()
        body = str(data["body"]).strip()
        if not title or not body:
            return _raw_report(diagnostics)
        # Always re-attach the attribution + machine diagnostics verbatim, so the
        # model can never drop or alter the "Reported by" tag or the version/OS.
        body = f"{body}\n\n---\n{_diagnostics_footer(diagnostics)}"
        return StructuredReport(title=title, body=body, ai_structured=True)
    except Exception:
        return _raw_report(diagnostics)


def _raw_report(diagnostics: Diagnostics) -> StructuredReport:
    """The fallback report: the raw message + diagnostics, no model involved."""
    title = _title_from_message(diagnostics.message)
    body = (
        "## Report (raw — AI structuring unavailable)\n\n"
        f"{diagnostics.message}\n\n"
        f"---\n{_diagnostics_footer(diagnostics)}"
    )
    return StructuredReport(title=title, body=body, ai_structured=False)


def _diagnostics_footer(diagnostics: Diagnostics) -> str:
    return (
        f"Reported by: {diagnostics.reporter}\n"
        f"tnotes version: {diagnostics.version}\n"
        f"OS: {diagnostics.os}"
    )


def _title_from_message(message: str) -> str:
    """A one-line title from the raw message: first line, length-capped."""
    first = message.strip().splitlines()[0] if message.strip() else "feedback"
    return first if len(first) <= 72 else first[:69] + "…"


def _strip_code_fence(text: str) -> str:
    """Drop a ```json fence if the model wrapped its JSON in one."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: -3]
    return t.strip()


# --- GitHub filing (injectable HTTP seam) --------------------------------------

# The injectable HTTP seam: the filing path calls through these, so a test passes
# stubs and never touches a real repo/PAT. Signatures mirror the slice of GitHub's
# REST API we use.
PostFn = Callable[[str, str, dict], dict]
GetFn = Callable[[str, str], dict]


@dataclass
class GitHubClient:
    """A thin, injectable GitHub REST client scoped to the filing path.

    ``post``/``get`` default to a stdlib-``urllib`` implementation (no heavy dep);
    tests inject stubs to exercise filing without a real repo or PAT. A 401 (missing
    /expired token) surfaces as ``FeedbackError`` so the caller falls back locally.
    """

    token: str
    post: PostFn = field(default=None)  # type: ignore[assignment]
    get: GetFn = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.post is None:
            self.post = self._urllib_post
        if self.get is None:
            self.get = self._urllib_get

    def _urllib_post(self, url: str, token: str, payload: dict) -> dict:
        return _urllib_request(url, token, method="POST", payload=payload)

    def _urllib_get(self, url: str, token: str) -> dict:
        return _urllib_request(url, token, method="GET", payload=None)


def _urllib_request(url: str, token: str, *, method: str, payload: Optional[dict]) -> dict:
    """One GitHub REST call over stdlib urllib; raises ``FeedbackError`` on failure.

    Collapses urllib's error zoo into one fallback-triggering type. A 401 is called
    out specially (missing/expired token → 'ping the maintainer') so the caller can
    surface the right message; everything else (offline, 5xx, 404) is a generic
    'couldn't reach the feedback repo'.
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "trustworthy-notes-feedback",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise FeedbackError(
                "feedback token rejected (401) — it is missing or expired; "
                "ask the maintainer for a fresh one"
            ) from exc
        raise FeedbackError(f"GitHub API error {exc.code} filing feedback") from exc
    except Exception as exc:  # offline, DNS, timeout — collapse to one fallback type
        raise FeedbackError(f"could not reach the feedback repo: {exc}") from exc


def file_issue(
    report: StructuredReport,
    repo: str,
    client: GitHubClient,
    *,
    bundle: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> str:
    """File the report as a GitHub issue in ``repo`` (``owner/name``); return the URL.

    When a ``bundle`` is given, commit it into the repo first (Contents API — GitHub
    has no programmatic issue-attachment endpoint) and link it in the issue body. Any
    failure raises ``FeedbackError`` for the caller to fall back from. ``now`` is
    injectable so the committed bundle path (timestamped) is deterministic in tests.
    """
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    body = report.body
    if bundle is not None:
        bundle_url = _commit_bundle(bundle, repo, client, stamp)
        body = f"{body}\n\n**Reproduction bundle:** {bundle_url}"
    created = client.post(
        f"{_GITHUB_API}/repos/{repo}/issues",
        client.token,
        {"title": report.title, "body": body},
    )
    url = created.get("html_url")
    if not url:
        raise FeedbackError("GitHub did not return an issue URL")
    return url


def _commit_bundle(bundle: Path, repo: str, client: GitHubClient, stamp: str) -> str:
    """Commit the bundle into ``repo`` via the Contents API; return its blob URL.

    Programmatic 'attach a file to an issue' doesn't exist in GitHub's API, so a
    bundle is committed into the repo and linked. The path is namespaced + timestamped
    (``feedback-bundles/feedback-<stamp>.zip``) so concurrent reports never collide.
    """
    path = f"feedback-bundles/feedback-{stamp}.zip"
    content = base64.b64encode(bundle.read_bytes()).decode("ascii")
    result = client.post(
        f"{_GITHUB_API}/repos/{repo}/contents/{path}",
        client.token,
        {"message": f"feedback bundle {stamp}", "content": content},
    )
    url = (result.get("content") or {}).get("html_url")
    if not url:
        raise FeedbackError("GitHub did not return a committed-bundle URL")
    return url


# --- Local-file fallback -------------------------------------------------------


@dataclass
class FeedbackOutcome:
    """What the run did, for the caller to confirm to the user.

    ``filed`` True ⇒ ``location`` is the issue URL (for the maintainer); False ⇒ it
    is the local file path. ``reporter`` and ``ai_structured`` feed the confirmation
    line. ``reason`` explains a fallback (offline, declined, unconfigured, 401).
    """

    filed: bool
    location: str
    reporter: str
    ai_structured: bool
    reason: Optional[str] = None


def write_local_fallback(
    report: StructuredReport,
    diagnostics: Diagnostics,
    bundle: Optional[Path],
    dest_dir: Path,
    *,
    now: Optional[datetime] = None,
) -> Path:
    """Write the structured report + a pointer to the bundle to a local file.

    The graceful-degradation path: when the repo/token isn't configured, the user
    is offline/declined, or the token is expired, the report is saved to
    ``feedback-<timestamp>.txt`` in ``dest_dir`` and the user is told where it is.
    The bundle (if any) is left beside it; the file points at it. Feedback is never
    lost. Returns the report file path.
    """
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"feedback-{stamp}.txt"
    lines = [
        report.title,
        "=" * len(report.title),
        "",
        report.body,
    ]
    if bundle is not None:
        lines += ["", f"Reproduction bundle: {bundle}"]
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


# --- Orchestration -------------------------------------------------------------


def upload_preview(diagnostics: Diagnostics, bundle_files: list[Path]) -> str:
    """The exact 'here's what will leave your machine' text shown before consent.

    The consent boundary's payload: the always-safe diagnostics, plus the bundle's
    *file list* — because each bundled file contains verbatim source excerpts, the
    user must see and acknowledge them before they leave the machine.
    """
    lines = [
        "This will upload the following to the private feedback repo:",
        "",
        "  Diagnostics (safe):",
        f"    Reported by : {diagnostics.reporter}",
        f"    tnotes version: {diagnostics.version}",
        f"    OS  : {diagnostics.os}",
        "",
        "  Your message:",
        f"    {diagnostics.message}",
    ]
    if bundle_files:
        lines += [
            "",
            "  Reproduction bundle — contains VERBATIM excerpts of your source document:",
        ]
        lines += [f"    {f.name}" for f in bundle_files]
    else:
        lines += ["", "  Reproduction bundle: (none — no document/notes referenced)"]
    return "\n".join(lines)


def run_feedback(
    message: str,
    *,
    reporter: str,
    doc: Optional[Path],
    pages: Optional[str],
    model: str,
    api_key: Optional[str],
    repo: Optional[str],
    token: Optional[str],
    fallback_dir: Path,
    confirm: Callable[[str], bool],
    log: Callable[[str], None],
    notes_dir: Optional[Path] = None,
    structure_client: Optional[object] = None,
    github_client: Optional[GitHubClient] = None,
    now: Optional[datetime] = None,
) -> FeedbackOutcome:
    """Run the whole feedback flow and return the outcome to confirm to the user.

    Steps: capture diagnostics → build the repro bundle → AI-structure (raw-text
    fallback inside) → show the consent preview and ask (``confirm``) → file to the
    private repo (when configured + consented + online) or write the local fallback.
    Every off-ramp lands on the local file, so feedback is never lost:

      * repo/token unconfigured        → local file
      * user declines the consent      → local file
      * offline / API error / 401      → local file (with the reason)

    ``confirm`` and ``log`` are injected (the CLI wires them to prompts/echo) so this
    orchestration is fully testable; ``structure_client``/``github_client``/``now``
    are injected in tests to avoid the network and to pin timestamps.
    """
    diagnostics = capture_diagnostics(message, reporter)
    bundle_files = collect_bundle_files(doc, pages, notes_dir)
    bundle_path: Optional[Path] = None
    if bundle_files:
        bundle_path = write_bundle(bundle_files, fallback_dir / "feedback-bundle.zip")

    report = structure_report(
        diagnostics, model=model, api_key=api_key, client=structure_client
    )
    if not report.ai_structured:
        log("note: couldn't AI-structure the report — sending it as raw text.")

    # Off-ramp: nothing configured to file to → straight to the local file, no
    # consent prompt (nothing is leaving the machine).
    if not repo or not token:
        dest = write_local_fallback(report, diagnostics, bundle_path, fallback_dir, now=now)
        return FeedbackOutcome(
            filed=False, location=str(dest), reporter=reporter,
            ai_structured=report.ai_structured,
            reason="no feedback repo/token configured",
        )

    # Consent boundary: the bundle (verbatim excerpts) is about to leave the
    # machine, so show exactly what and require a yes. A no falls back locally.
    if not confirm(upload_preview(diagnostics, bundle_files)):
        dest = write_local_fallback(report, diagnostics, bundle_path, fallback_dir, now=now)
        return FeedbackOutcome(
            filed=False, location=str(dest), reporter=reporter,
            ai_structured=report.ai_structured, reason="upload declined",
        )

    client = github_client or GitHubClient(token=token)
    try:
        url = file_issue(report, repo, client, bundle=bundle_path, now=now)
    except FeedbackError as exc:
        dest = write_local_fallback(report, diagnostics, bundle_path, fallback_dir, now=now)
        return FeedbackOutcome(
            filed=False, location=str(dest), reporter=reporter,
            ai_structured=report.ai_structured, reason=str(exc),
        )
    return FeedbackOutcome(
        filed=True, location=url, reporter=reporter,
        ai_structured=report.ai_structured,
    )
