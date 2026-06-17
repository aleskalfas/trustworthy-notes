"""Regression tests for the notes model: the schema + the §7 validity checks.

The structural tests need no PDF (CI-safe). The traceability test needs the
(gitignored, copyrighted) source PDF and SKIPS when it's absent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from trustworthy_notes import ingest
from trustworthy_notes.validation import check_traceability, load_notes_schema, validate_structure

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "notes.printed-p3.yaml"
PDFS = sorted((ROOT / "data").glob("*.pdf"))


def load_fixture() -> dict:
    return yaml.safe_load(FIXTURE.read_text())


def _minimal(**source) -> dict:
    """A smallest valid-ish notes-set with the given source block."""
    return {
        "schema_version": 1,
        "source": source,
        "evidence": [{"id": "e-x", "excerpt": "y", "source": "body"}],
        "statements": [{"id": "s-x", "type": "claim", "text": "y", "evidence": ["e-x"]}],
    }


def test_schema_is_well_formed():
    Draft202012Validator.check_schema(load_notes_schema())


def test_fixture_is_structurally_valid():
    problems = validate_structure(load_fixture())
    assert not problems, "\n".join(problems)


def test_fixture_is_page_scoped_and_grounded():
    data = load_fixture()
    assert data["source"]["scope"] == "page"
    assert all(s.get("evidence") for s in data["statements"]), "every statement must be grounded (§7.1)"


@pytest.mark.parametrize(
    "source, valid",
    [
        ({"document": "d", "scope": "page", "page_index": 1}, True),
        ({"document": "d", "page_index": 1}, True),                       # scope defaults to page
        ({"document": "d", "scope": "page"}, False),                      # page scope needs page_index
        ({"document": "d", "scope": "chapter", "page_range": [1, 5]}, True),
        ({"document": "d", "scope": "chapter", "chapter_id": "ch1"}, False),  # chapter needs page_range
    ],
)
def test_scope_conditionals(source, valid):
    problems = validate_structure(_minimal(**source))
    assert (not problems) == valid, problems


def test_wrong_kind_reference_is_rejected():
    # a statement referencing a term-id where an evidence-id is required
    doc = _minimal(document="d", page_index=1)
    doc["terms"] = [{"id": "t-x", "label": "x"}]
    doc["statements"][0]["evidence"] = ["t-x"]
    assert validate_structure(doc), "expected the e-/t- prefix mismatch to be rejected"


def test_evidence_script_field_accepted():
    doc = _minimal(document="d", page_index=1)
    doc["evidence"][0]["script"] = "egyptian-transliteration"
    assert not validate_structure(doc), "the optional evidence `script` field should validate"


def test_referential_integrity_catches_dangling_evidence():
    doc = _minimal(document="d", page_index=1)
    doc["statements"][0]["evidence"] = ["e-missing"]
    problems = validate_structure(doc)
    assert any("e-missing" in p for p in problems), problems


@pytest.mark.skipif(not PDFS, reason="no test PDF under data/ (gitignored)")
def test_fixture_is_traceable():
    data = load_fixture()
    pages = ingest.read_pages(PDFS[0])
    problems = check_traceability(data, pages)
    assert not problems, "\n".join(problems)
