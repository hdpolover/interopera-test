from __future__ import annotations

import dataclasses
import json
import os

import pytest

from src.ingestion.guidelines_parser import RuleChunk, chunk_id_from_text, parse_guidelines


# ---------------------------------------------------------------------------
# chunk_id_from_text tests (preserved from original)
# ---------------------------------------------------------------------------

def test_chunk_id_is_16_char_hex():
    cid = chunk_id_from_text("test passage content")
    assert len(cid) == 16, f"Expected 16 hex chars, got {len(cid)}: {cid!r}"
    int(cid, 16)  # must be valid hex


def test_chunk_id_is_deterministic():
    text = "The allocation to Singapore Government Securities shall be between 20% and 60%."
    assert chunk_id_from_text(text) == chunk_id_from_text(text)


def test_chunk_id_differs_for_different_text():
    assert chunk_id_from_text("text a") != chunk_id_from_text("text b")


# Fix 7: pin test uses first 16 hex chars of sha256("hello")
def test_chunk_id_pins_to_known_sha256():
    # sha256("hello") = 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824
    # first 16 hex chars = "2cf24dba5fb0a30e"
    assert chunk_id_from_text("hello") == "2cf24dba5fb0a30e"


# ---------------------------------------------------------------------------
# RuleChunk dataclass tests (preserved)
# ---------------------------------------------------------------------------

def test_rule_chunk_has_all_fields():
    field_names = {f.name for f in dataclasses.fields(RuleChunk)}
    assert field_names == {
        "chunk_id", "source_doc", "page", "passage",
        "passage_summary", "extracted_fields", "extraction_confidence",
    }


def test_rule_chunk_is_frozen():
    chunk = RuleChunk(
        chunk_id="abc",
        source_doc="test.pdf",
        page=1,
        passage="test",
        passage_summary="summary",
        extracted_fields={},
        extraction_confidence=0.9,
    )
    with pytest.raises((AttributeError, TypeError)):
        chunk.chunk_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# parse_guidelines tests (new — from brief)
# ---------------------------------------------------------------------------

def test_parse_produces_thirteen_figure_chunks_plus_counterparty_and_metrics():
    chunks = parse_guidelines()
    refs = {c.extracted_fields.get("limit_ref") for c in chunks if c.extracted_fields.get("limit_ref")}
    assert refs == {
        "allocation_sgs_limit", "allocation_mas_limit", "allocation_ig_limit",
        "allocation_hy_limit", "allocation_fx_limit", "allocation_sc_limit",
        "allocation_cash_limit", "non_ig_cap_limit", "corporate_issuer_limit",
        "gre_issuer_limit", "liquidity_limit", "duration_limit", "dv01_limit",
    }
    rule_types = {c.extracted_fields["rule_type"] for c in chunks}
    assert "counterparty_limit" in rule_types
    assert "market_risk_metrics" in rule_types


def test_sgs_chunk_has_correct_bounds_and_page():
    chunks = parse_guidelines()
    sgs = next(c for c in chunks if c.extracted_fields.get("limit_ref") == "allocation_sgs_limit")
    assert sgs.extracted_fields["bounds"] == {"min_value": "0.20", "max_value": "0.60", "unit": "pct"}
    assert sgs.page == 1
    assert sgs.extraction_confidence >= 0.85


def test_counterparty_chunk_is_low_confidence():
    chunks = parse_guidelines()
    cp = next(c for c in chunks if c.extracted_fields["rule_type"] == "counterparty_limit")
    assert cp.extraction_confidence < 0.85


def test_dv01_bounds():
    chunks = parse_guidelines()
    dv01 = next(c for c in chunks if c.extracted_fields.get("limit_ref") == "dv01_limit")
    assert dv01.extracted_fields["bounds"] == {"cap_value": "85000", "unit": "sgd"}


# ---------------------------------------------------------------------------
# Golden snapshot regression test
# ---------------------------------------------------------------------------

def test_parse_matches_golden_snapshot():
    fixture = os.path.join("tests", "fixtures", "parsed_guidelines.json")
    with open(fixture) as f:
        expected = json.load(f)
    actual = [dataclasses.asdict(c) for c in parse_guidelines()]
    assert actual == expected, "parser output drifted from golden snapshot (pdfplumber change?)"
