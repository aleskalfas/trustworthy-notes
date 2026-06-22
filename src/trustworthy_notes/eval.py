"""The deterministic floor-score harness — a maintainer instrument (ADR-007).

An offline yardstick: it scores how well a corpus of generated notes clears the
**mechanical floor** (METHODOLOGY §7), emitting a fingerprinted, reproducible
number so a model/prompt change can be judged as a regression. It is an
*instrument reading, never a gate* (ADR-007): no correctness decision depends on
it, it lives outside the enforced §7 checks, and it never touches the pipeline.

What it reuses, and why. The floor is computed by calling the **real** checks —
``validation.validate_structure`` (§7.1/§7.4/§7.5) and ``validation.check_traceability``
(§7.2 verbatim-anchoring) — over each doc's per-page notes, never a second copy
of them (COR-007). A re-implemented floor could drift from what the pipeline
actually enforces, so we measure against the genuine article.

Isolation (ADR-007 Invariant 5). The only inbound arrow is ``cli → eval``. Inside,
``eval → validation`` and ``eval → normalize`` is required (the floor must reuse
the real checks). ``pipeline → eval`` / ``extract → eval`` is **forbidden** — a
stochastic, corpus-private grade must never reach into deterministic extraction.
This module therefore imports neither ``pipeline``/``extract``/``compose`` nor
``ingest``: the corpus is self-contained (each doc carries the source page streams
it needs as a ``source-pages.yaml`` companion), so scoring needs no PDF and no
pipeline call.

The judge is deferred. There are no judge fields here — the stochastic LLM
entailment judge ADR-007 defers is not built; this is the floor only.

Corpus layout. A corpus dir holds one subdirectory per document. Each doc dir
carries the generated per-page notes under ``1-extract/page-*.notes.yaml`` (the
workspace convention) plus a ``source-pages.yaml`` listing the source page
streams (``page_index`` / ``text`` / ``footnotes``) §7.2 anchors against, each
optionally marked ``expected_notes: true/false`` for the completeness check::

    corpus/
      doc-a/
        source-pages.yaml
        1-extract/
          page-0000.notes.yaml
      doc-b/
        ...

The real corpus is verbatim copyrighted excerpts — private, config-pointed
(``config.eval_corpus_dir``), never committed (ADR-003 inherited). Only a small
public smoke corpus ships (``tests/fixtures/eval-smoke/``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from . import build, validation, workspace
from .models import PageText

# The companion artifact, beside each doc's notes, holding the source page streams
# the §7.2 traceability check anchors excerpts against. Named, not derived, so the
# corpus stays self-contained and the harness never re-reads a PDF (keeping `eval`
# isolated from `ingest`/the pipeline — ADR-007).
SOURCE_PAGES_FILE = "source-pages.yaml"

# The schema version of the emitted JSON score. Bumped when the score's stable
# shape changes, so a stored reading is never misread by a newer harness. This is
# part of what makes two runs comparable (ADR-007's fingerprint discipline).
SCORE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FloorCounts:
    """The deterministic §7 floor tallies — facts, 100% reproducible (ADR-007).

    Identical notes in → identical counts out. ``*_problems`` count the problem
    strings the real checks emit; the rate properties derive the simple
    anchored/grounded fractions a regression moves.

    ``pages_expected``/``pages_present`` are the **completeness** axis (ADR-007's
    completeness-aware floor): a count of how many of the source pages a corpus doc
    declared as *expected to have notes* actually do. A run that lost half a document
    (extraction failed mid-sweep, stale notes left behind) shows ``pages_present <
    pages_expected`` here — so a partial or stale-contaminated corpus can never read
    as a clean 100%. This is part of the fingerprint, so coverage is one of the things
    that makes two runs comparable.
    """

    statements_total: int = 0
    statements_grounded: int = 0
    excerpts_total: int = 0
    excerpts_anchored: int = 0
    referential_problems: int = 0
    schema_problems: int = 0
    pages_expected: int = 0
    pages_present: int = 0

    def __add__(self, other: "FloorCounts") -> "FloorCounts":
        """Aggregate two docs' counts (so the corpus total is the sum of its docs)."""
        return FloorCounts(
            statements_total=self.statements_total + other.statements_total,
            statements_grounded=self.statements_grounded + other.statements_grounded,
            excerpts_total=self.excerpts_total + other.excerpts_total,
            excerpts_anchored=self.excerpts_anchored + other.excerpts_anchored,
            referential_problems=self.referential_problems + other.referential_problems,
            schema_problems=self.schema_problems + other.schema_problems,
            pages_expected=self.pages_expected + other.pages_expected,
            pages_present=self.pages_present + other.pages_present,
        )

    @property
    def anchored_rate(self) -> float:
        """§7.2: fraction of text excerpts that anchor verbatim. 1.0 when there are none."""
        return _rate(self.excerpts_anchored, self.excerpts_total)

    @property
    def grounded_rate(self) -> float:
        """§7.1: fraction of statements that cite at least one evidence record."""
        return _rate(self.statements_grounded, self.statements_total)

    @property
    def complete_rate(self) -> float:
        """Completeness: fraction of expected note-pages that are present. 1.0 when none.

        Below 1.0 means a doc lost expected pages — the exact signal a failed/stale
        sweep produces (ADR-007). The empty denominator (a doc with no expected-page
        info) reads as vacuously complete, never a fabricated gap."""
        return _rate(self.pages_present, self.pages_expected)


def _rate(numerator: int, denominator: int) -> float:
    """A safe rate: ``numerator / denominator``, or 1.0 when there is nothing to score.

    An empty denominator reads as "no failures possible here", not a division error —
    a doc with zero excerpts has, vacuously, a perfect anchoring rate.
    """
    return 1.0 if denominator == 0 else numerator / denominator


@dataclass(frozen=True)
class DocFloorScore:
    """One document's floor score: its counts plus the verbatim problem strings.

    ``doc_id`` is the corpus subdir name (stable across runs). ``problems`` carries
    the human-readable strings the real checks emitted, so a regression report can
    show *what* failed, not just that a rate dropped.

    The completeness fields (ADR-007) are page-index sets: ``expected_pages`` are the
    source pages the corpus declared *should* have notes, ``present_pages`` are those
    that actually have a notes file, and ``missing_pages`` is the gap. A non-empty
    ``missing_pages`` means the doc is **incomplete** — a failed/stale-contaminated run
    that must not read as a clean 100%.
    """

    doc_id: str
    counts: FloorCounts
    problems: list[str] = field(default_factory=list)
    expected_pages: list[int] = field(default_factory=list)
    present_pages: list[int] = field(default_factory=list)
    missing_pages: list[int] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """True when every expected note-page is present — no missing/failed pages."""
        return not self.missing_pages


@dataclass(frozen=True)
class InstrumentFingerprint:
    """The conditions that make a reading mean something (ADR-007).

    A score without its fingerprint is uninterpretable: change the instrument and
    you cannot compare across runs. Records the corpus id (its dir name), a hash of
    the doc list (so a corpus that gained/lost a doc is visibly a different
    instrument), the timestamp, the tool/build version, and the aggregate floor
    counts. No judge fields — the judge is deferred (ADR-007).
    """

    corpus_id: str
    corpus_hash: str
    generated_at: str
    tool_version: str
    floor_counts: FloorCounts


@dataclass(frozen=True)
class FloorScore:
    """The whole reading: the fingerprint, every doc's score, and the aggregate.

    The aggregate counts are the per-doc counts summed; ``aggregate_rate`` helpers
    live on :class:`FloorCounts`. Serialise with :func:`to_json` for a stable,
    comparable artifact.
    """

    fingerprint: InstrumentFingerprint
    docs: list[DocFloorScore]

    @property
    def aggregate(self) -> FloorCounts:
        return self.fingerprint.floor_counts


# --- Scoring -------------------------------------------------------------------


def score_doc(
    doc_id: str, notes_files: list[Path], source: "SourcePages"
) -> DocFloorScore:
    """Run the real §7 floor checks over one doc's per-page notes and tally counts.

    Calls ``validation.validate_structure`` (§7.1/§7.4/§7.5 via the schema +
    referential integrity) and ``validation.check_traceability`` (§7.2 verbatim
    anchoring) — the genuine checks, never a re-implementation (COR-007). Counts are
    derived per page and summed: a statement is grounded (§7.1) when it cites at
    least one evidence record; a text excerpt is anchored (§7.2) when it is NOT named
    in a traceability problem for its evidence id.

    Completeness (ADR-007). ``source`` carries the source page streams *and* the set
    of pages the corpus declared as **expected** to have notes. The expected set is
    compared against the page indices that actually have a notes file: any expected
    page with no notes is a **missing** page, and a doc with any missing page is
    flagged incomplete (it cannot read as a clean 100%). When the corpus declared no
    expected set (a pre-completeness corpus like the public smoke fixture), expected
    falls back to the pages that *have* notes — completeness is then trivially
    satisfied, never a fabricated gap (the backward-compat contract).
    """
    by_index = {p.page_index: p for p in source.pages}
    counts = FloorCounts()
    problems: list[str] = []
    present: set[int] = set()

    for notes_path in sorted(notes_files):
        index = _page_index_of(notes_path)
        data = _load_notes(notes_path)
        if data is None:
            problems.append(f"schema [{notes_path.name}]: not valid YAML or not a mapping")
            counts = counts + FloorCounts(schema_problems=1)
            continue
        if index is not None:
            present.add(index)

        structure_problems = validation.validate_structure(data)
        # The source streams for this notes-set's page; default index from `source`.
        default_index = (data.get("source") or {}).get("page_index")
        relevant_pages = _pages_for(data, by_index, default_index)
        traceability_problems = validation.check_traceability(data, relevant_pages)

        page_counts = _count_floor(data, structure_problems, traceability_problems)
        counts = counts + page_counts
        problems.extend(f"{notes_path.name}: {p}" for p in structure_problems + traceability_problems)

    # Expected = what the corpus declared, or (backward-compat) the pages that have
    # notes when no expectation was recorded — so a pre-completeness corpus never
    # invents a gap. Missing = expected pages with no notes file: the failed/stale
    # pages ADR-007's completeness check exists to surface.
    expected = source.expected_pages if source.expected_pages is not None else set(present)
    missing = expected - present
    completeness = FloorCounts(pages_expected=len(expected), pages_present=len(expected & present))

    if missing:
        problems.append(
            f"completeness: {len(missing)} expected page(s) have no notes "
            f"(missing/failed: {sorted(missing)})"
        )

    return DocFloorScore(
        doc_id=doc_id,
        counts=counts + completeness,
        problems=problems,
        expected_pages=sorted(expected),
        present_pages=sorted(present),
        missing_pages=sorted(missing),
    )


def _count_floor(
    data: dict, structure_problems: list[str], traceability_problems: list[str]
) -> FloorCounts:
    """Tally one notes-set's floor counts from its data and the real checks' output.

    Grounding (§7.1) is read off the notes (a statement with a non-empty ``evidence``
    list is grounded); anchoring (§7.2) counts the text excerpts NOT flagged by the
    traceability check; referential/schema problem counts partition
    ``structure_problems`` by their prefix (``validate_structure`` tags each line)."""
    statements = [s for s in data.get("statements", []) if isinstance(s, dict)]
    grounded = sum(1 for s in statements if s.get("evidence"))

    text_excerpts = [
        e for e in data.get("evidence", [])
        if isinstance(e, dict) and e.get("kind", "text") == "text"
    ]
    # check_traceability emits one problem per excerpt that fails to anchor, so the
    # anchored count is total-minus-failures (figure/table evidence is excluded above,
    # matching what the check skips).
    excerpts_total = len(text_excerpts)
    excerpts_anchored = max(0, excerpts_total - len(traceability_problems))

    referential = sum(1 for p in structure_problems if p.startswith("referential:"))
    schema = sum(1 for p in structure_problems if p.startswith("schema "))

    return FloorCounts(
        statements_total=len(statements),
        statements_grounded=grounded,
        excerpts_total=excerpts_total,
        excerpts_anchored=excerpts_anchored,
        referential_problems=referential,
        schema_problems=schema,
    )


def score_corpus(corpus_dir: str | Path, *, now: Optional[datetime] = None) -> FloorScore:
    """Score every document in a corpus dir and return the fingerprinted aggregate.

    A corpus is a dir of doc subdirectories, each with ``1-extract/page-*.notes.yaml``
    notes and a ``source-pages.yaml`` companion (see the module docstring). Docs are
    discovered and processed in sorted order so the reading is deterministic — same
    corpus bytes in → identical score out (timestamp aside), which is the
    reproducibility ADR-007 requires. ``now`` is injectable so tests can pin the
    timestamp and assert determinism.
    """
    corpus_path = Path(corpus_dir)
    doc_dirs = sorted(d for d in corpus_path.iterdir() if d.is_dir()) if corpus_path.is_dir() else []

    docs: list[DocFloorScore] = []
    aggregate = FloorCounts()
    for doc_dir in doc_dirs:
        notes_files = sorted(workspace.extract_dir(doc_dir).glob("page-*.notes.yaml"))
        source = _load_source_pages(doc_dir / SOURCE_PAGES_FILE)
        doc_score = score_doc(doc_dir.name, notes_files, source)
        docs.append(doc_score)
        aggregate = aggregate + doc_score.counts

    fingerprint = InstrumentFingerprint(
        corpus_id=corpus_path.name,
        corpus_hash=_corpus_hash([d.name for d in doc_dirs]),
        generated_at=(now or datetime.now(timezone.utc)).isoformat(),
        tool_version=build.build_identity(),
        floor_counts=aggregate,
    )
    return FloorScore(fingerprint=fingerprint, docs=docs)


def _corpus_hash(doc_ids: list[str]) -> str:
    """A short, stable hash of the doc list — so a corpus that gained or lost a doc
    is visibly a *different instrument* (ADR-007), invalidating cross-run comparison.
    Hashes the names only (the corpus's identity is which docs it holds); the content
    is captured by the floor counts the fingerprint also carries."""
    digest = hashlib.sha256("\n".join(sorted(doc_ids)).encode("utf-8")).hexdigest()
    return digest[:16]


# --- Corpus / notes IO ---------------------------------------------------------


def _load_notes(notes_path: Path) -> Optional[dict]:
    """Load a per-page notes YAML, or None if unreadable/not a mapping.

    A None return is scored as a schema problem by the caller rather than raising —
    one malformed file should not abort scoring the rest of the corpus.
    """
    try:
        data = yaml.safe_load(notes_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


@dataclass(frozen=True)
class SourcePages:
    """A corpus doc's source streams plus its declared expected note-page set.

    ``pages`` are the PageText streams §7.2 anchors excerpts against. ``expected_pages``
    is the set of page indices the corpus declared as *expected to have notes* (ADR-007's
    completeness denominator), or ``None`` when the corpus declared no expectation — the
    pre-completeness/backward-compat case the scorer reads as "expected = whatever has
    notes", so no gap is fabricated.
    """

    pages: list[PageText]
    expected_pages: Optional[set[int]]


def _load_source_pages(path: Path) -> SourcePages:
    """Load a doc's ``source-pages.yaml`` into the streams §7.2 anchors against, plus
    the completeness expected-page set.

    Each entry needs ``page_index``, ``text``, ``footnotes``; the remaining PageText
    fields are §7.2-irrelevant (check_traceability reads only those three) so they
    take harmless placeholder values. A missing/unreadable file yields empty streams
    and no expectation — then every text excerpt fails to anchor (its page is "not
    among extracted pages"), which the floor correctly surfaces rather than silently
    passing.

    Completeness markers (ADR-007). A page entry may carry ``expected_notes: true/false``
    declaring whether the page is *expected* to have notes (the ``add-doc`` capture
    writes this from ``page_type == "text"``). If **any** entry carries the marker, the
    expected-page set is the indices marked ``true``; if **no** entry carries it (the
    pre-completeness smoke corpus), ``expected_pages`` is ``None`` — the backward-compat
    signal the scorer reads as "expect exactly what has notes", so no false MISSING.
    """
    if not path.is_file():
        return SourcePages(pages=[], expected_pages=None)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return SourcePages(pages=[], expected_pages=None)
    entries = raw.get("pages") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return SourcePages(pages=[], expected_pages=None)
    pages: list[PageText] = []
    expected: set[int] = set()
    saw_marker = False
    for entry in entries:
        if not isinstance(entry, dict) or "page_index" not in entry:
            continue
        index = int(entry["page_index"])
        pages.append(
            PageText(
                page_index=index,
                page_number=index + 1,
                text=str(entry.get("text", "")),
                width=0.0,
                height=0.0,
                footnotes=str(entry.get("footnotes", "")),
            )
        )
        if "expected_notes" in entry:
            saw_marker = True
            if entry["expected_notes"]:
                expected.add(index)
    return SourcePages(pages=pages, expected_pages=expected if saw_marker else None)


def _page_index_of(notes_path: Path) -> Optional[int]:
    """The 0-based page index encoded in a ``page-NNNN.notes.yaml`` filename, or None.

    Mirrors ``feedback._page_index_of`` but kept local so ``eval`` imports no pipeline
    module (ADR-007 isolation); the filename convention is the workspace's, stable."""
    stem = notes_path.name.split(".")[0]  # "page-0013"
    try:
        return int(stem.split("-")[1])
    except (IndexError, ValueError):
        return None


def _pages_for(
    data: dict, by_index: dict[int, PageText], default_index: Optional[int]
) -> list[PageText]:
    """The source pages a notes-set's evidence could cite — its own page plus any an
    evidence record overrides to via ``page_index``. Passing only the relevant pages
    keeps ``check_traceability`` honest while the corpus may hold many pages."""
    wanted: set[int] = set()
    if default_index is not None:
        wanted.add(int(default_index))
    for e in data.get("evidence", []):
        if isinstance(e, dict) and "page_index" in e:
            wanted.add(int(e["page_index"]))
    return [by_index[i] for i in sorted(wanted) if i in by_index]


# --- Serialisation -------------------------------------------------------------


def to_dict(score: FloorScore) -> dict:
    """The stable, JSON-ready shape of a floor score — fingerprint + per-doc + aggregate.

    A small fixed shape so two runs are byte-comparable (the point of the fingerprint,
    ADR-007). ``schema_version`` lets a future harness reject a shape it doesn't
    understand. The two-number split ADR-007 mandates is honoured by omission: there
    is a floor and *no* judge field — nothing to launder together.
    """
    return {
        "schema_version": SCORE_SCHEMA_VERSION,
        "kind": "floor-only",  # the judge is deferred (ADR-007); say so in the artifact
        "fingerprint": {
            "corpus_id": score.fingerprint.corpus_id,
            "corpus_hash": score.fingerprint.corpus_hash,
            "generated_at": score.fingerprint.generated_at,
            "tool_version": score.fingerprint.tool_version,
            "floor_counts": asdict(score.fingerprint.floor_counts),
        },
        "aggregate": _counts_with_rates(score.aggregate),
        "docs": [
            {
                "doc_id": d.doc_id,
                "counts": _counts_with_rates(d.counts),
                "problems": d.problems,
                "complete": d.is_complete,
                "expected_pages": d.expected_pages,
                "present_pages": d.present_pages,
                "missing_pages": d.missing_pages,
            }
            for d in score.docs
        ],
    }


def _counts_with_rates(counts: FloorCounts) -> dict:
    """A counts dict with the derived rates inlined, for the serialised artifact."""
    out = asdict(counts)
    out["anchored_rate"] = counts.anchored_rate
    out["grounded_rate"] = counts.grounded_rate
    out["complete_rate"] = counts.complete_rate
    return out


def to_json(score: FloorScore) -> str:
    """Serialise a floor score to stable, sorted JSON (comparable across runs)."""
    return json.dumps(to_dict(score), indent=2, sort_keys=True, ensure_ascii=False)
