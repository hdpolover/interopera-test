import pytest
import re

def test_chunk_id_is_8_char_hex():
    from src.ingestion.guidelines_parser import chunk_id_from_text
    cid = chunk_id_from_text("test passage content")
    assert len(cid) == 8
    int(cid, 16)  # must be valid hex

def test_chunk_id_is_deterministic():
    from src.ingestion.guidelines_parser import chunk_id_from_text
    text = "The allocation to Singapore Government Securities shall be between 20% and 60%."
    assert chunk_id_from_text(text) == chunk_id_from_text(text)

def test_chunk_id_differs_for_different_text():
    from src.ingestion.guidelines_parser import chunk_id_from_text
    assert chunk_id_from_text("text a") != chunk_id_from_text("text b")

def test_stub_returns_at_least_6_chunks():
    from src.ingestion.guidelines_parser import parse_guidelines
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    assert len(chunks) >= 6

def test_stub_chunk_ids_are_8_char_hex():
    from src.ingestion.guidelines_parser import parse_guidelines
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    for chunk in chunks:
        assert len(chunk.chunk_id) == 8
        int(chunk.chunk_id, 16)

def test_stub_extraction_confidence_is_float():
    from src.ingestion.guidelines_parser import parse_guidelines
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    for chunk in chunks:
        assert isinstance(chunk.extraction_confidence, float)
        assert 0.0 <= chunk.extraction_confidence <= 1.0

def test_stub_covers_known_rule_types():
    from src.ingestion.guidelines_parser import parse_guidelines
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    rule_types = {c.extracted_fields.get("rule_type") for c in chunks}
    required = {"allocation_limit", "concentration_limit", "liquidity_requirement",
                "duration_limit", "dv01_limit", "non_ig_cap"}
    assert required.issubset(rule_types), f"Missing rule types: {required - rule_types}"

def test_stub_source_doc_is_set():
    from src.ingestion.guidelines_parser import parse_guidelines
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    for chunk in chunks:
        assert chunk.source_doc, "source_doc must not be empty"

def test_rule_chunk_has_all_fields():
    from src.ingestion.guidelines_parser import parse_guidelines, RuleChunk
    import dataclasses
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    assert len(chunks) > 0
    chunk = chunks[0]
    field_names = {f.name for f in dataclasses.fields(RuleChunk)}
    assert field_names == {"chunk_id", "source_doc", "page", "passage",
                           "passage_summary", "extracted_fields", "extraction_confidence"}

def test_chunk_id_pins_to_known_sha256():
    # sha256("hello") = 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824
    # first 8 hex chars = "2cf24dba"
    from src.ingestion.guidelines_parser import chunk_id_from_text
    assert chunk_id_from_text("hello") == "2cf24dba"

def test_stub_chunk_ids_are_distinct():
    from src.ingestion.guidelines_parser import parse_guidelines
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    ids = [c.chunk_id for c in chunks]
    assert len(set(ids)) == len(ids), f"Duplicate chunk_ids: {ids}"
    assert len(ids) == 7
