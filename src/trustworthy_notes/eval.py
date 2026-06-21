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
streams (``page_index`` / ``text`` / ``footnotes``) §7.2 anchors against::

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
    """

    statements_total: int = 0
    statements_grounded: int = 0
    excerpts_total: int = 0
    excerpts_anchored: int = 0
    referential_problems: int = 0
    schema_problems: int = 0

    def __add__(self, other: "FloorCounts") -> "FloorCounts":
        """Aggregate two docs' counts (so the corpus total is the sum of its docs)."""
        return FloorCounts(
            statements_total=self.statements_total + other.statements_total,
            statements_grounded=self.statements_grounded + other.statements_grounded,
            excerpts_total=self.excerpts_total + other.excerpts_total,
            excerpts_anchored=self.excerpts_anchored + other.excerpts_anchored,
            referential_problems=self.referential_problems + other.referential_problems,
            schema_problems=self.schema_problems + other.schema_problems,
        )

    @property
    def anchored_rate(self) -> float:
        """§7.2: fraction of text excerpts that anchor verbatim. 1.0 when there are none."""
        return _rate(self.excerpts_anchored, self.excerpts_total)

    @property
    def grounded_rate(self) -> float:
        """§7.1: fraction of statements that cite at least one evidence record."""
        return _rate(self.statements_grounded, self.statements_total)


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
    """

    doc_id: str
    counts: FloorCounts
    problems: list[str] = field(default_factory=list)


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


def score_doc(doc_id: str, notes_files: list[Path], pages: list[PageText]) -> DocFloorScore:
    """Run the real §7 floor checks over one doc's per-page notes and tally counts.

    Calls ``validation.validate_structure`` (§7.1/§7.4/§7.5 via the schema +
    referential integrity) and ``validation.check_traceability`` (§7.2 verbatim
    anchoring) — the genuine checks, never a re-implementation (COR-007). Counts are
    derived per page and summed: a statement is grounded (§7.1) when it cites at
    least one evidence record; a text excerpt is anchored (§7.2) when it is NOT named
    in a traceability problem for its evidence id.
    """
    by_index = {p.page_index: p for p in pages}
    counts = FloorCounts()
    problems: list[str] = []

    for notes_path in sorted(notes_files):
        data = _load_notes(notes_path)
        if data is None:
            problems.append(f"schema [{notes_path.name}]: not valid YAML or not a mapping")
            counts = counts + FloorCounts(schema_problems=1)
            continue

        structure_problems = validation.validate_structure(data)
        # The source streams for this notes-set's page; default index from `source`.
        default_index = (data.get("source") or {}).get("page_index")
        relevant_pages = _pages_for(data, by_index, default_index)
        traceability_problems = validation.check_traceability(data, relevant_pages)

        page_counts = _count_floor(data, structure_problems, traceability_problems)
        counts = counts + page_counts
        problems.extend(f"{notes_path.name}: {p}" for p in structure_problems + traceability_problems)

    return DocFloorScore(doc_id=doc_id, counts=counts, problems=problems)


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
        pages = _load_source_pages(doc_dir / SOURCE_PAGES_FILE)
        doc_score = score_doc(doc_dir.name, notes_files, pages)
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


def _load_source_pages(path: Path) -> list[PageText]:
    """Load a doc's ``source-pages.yaml`` into the PageText list §7.2 anchors against.

    Each entry needs ``page_index``, ``text``, ``footnotes``; the remaining PageText
    fields are §7.2-irrelevant (check_traceability reads only those three) so they
    take harmless placeholder values. A missing/unreadable file yields an empty list —
    then every text excerpt fails to anchor (its page is "not among extracted pages"),
    which the floor correctly surfaces rather than silently passing.
    """
    if not path.is_file():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    entries = raw.get("pages") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return []
    pages: list[PageText] = []
    for entry in entries:
        if not isinstance(entry, dict) or "page_index" not in entry:
            continue
        index = entry["page_index"]
        pages.append(
            PageText(
                page_index=int(index),
                page_number=int(index) + 1,
                text=str(entry.get("text", "")),
                width=0.0,
                height=0.0,
                footnotes=str(entry.get("footnotes", "")),
            )
        )
    return pages


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
            }
            for d in score.docs
        ],
    }


def _counts_with_rates(counts: FloorCounts) -> dict:
    """A counts dict with the derived rates inlined, for the serialised artifact."""
    out = asdict(counts)
    out["anchored_rate"] = counts.anchored_rate
    out["grounded_rate"] = counts.grounded_rate
    return out


def to_json(score: FloorScore) -> str:
    """Serialise a floor score to stable, sorted JSON (comparable across runs)."""
    return json.dumps(to_dict(score), indent=2, sort_keys=True, ensure_ascii=False)
