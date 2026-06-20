import pytest


# Fix 7: chunk ID is now 16 hex chars
def test_chunk_id_is_16_char_hex():
    from src.ingestion.guidelines_parser import chunk_id_from_text
    cid = chunk_id_from_text("test passage content")
    assert len(cid) == 16, f"Expected 16 hex chars, got {len(cid)}: {cid!r}"
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

# Fix 7: stub chunk IDs are 16 hex chars
def test_stub_chunk_ids_are_16_char_hex():
    from src.ingestion.guidelines_parser import parse_guidelines
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    for chunk in chunks:
        assert len(chunk.chunk_id) == 16, f"Expected 16 chars, got {len(chunk.chunk_id)}: {chunk.chunk_id!r}"
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
    chunks[0]
    field_names = {f.name for f in dataclasses.fields(RuleChunk)}
    assert field_names == {"chunk_id", "source_doc", "page", "passage",
                           "passage_summary", "extracted_fields", "extraction_confidence"}

# Fix 7: pin test uses first 16 hex chars of sha256("hello")
def test_chunk_id_pins_to_known_sha256():
    # sha256("hello") = 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824
    # first 16 hex chars = "2cf24dba5fb0a30e"
    from src.ingestion.guidelines_parser import chunk_id_from_text
    assert chunk_id_from_text("hello") == "2cf24dba5fb0a30e"

def test_stub_chunk_ids_are_distinct():
    from src.ingestion.guidelines_parser import parse_guidelines
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    ids = [c.chunk_id for c in chunks]
    assert len(set(ids)) == len(ids), f"Duplicate chunk_ids: {ids}"
    # 6 reported-figure rule types + market_risk_metrics + the low-confidence
    # counterparty_limit chunk (demonstrates the human-verification gate) = 8.
    assert len(ids) == 8


# Fix 5: LLM path with pdf_path provided but extraction returns nothing raises ValueError
def test_pdf_with_llm_that_returns_no_chunks_raises_valueerror():
    from src.ingestion.guidelines_parser import parse_guidelines

    class AlwaysNoneLLM:
        def extract_rule(self, text: str) -> None:
            return None

    # Create a fake PDF-like temp file — pdfplumber will fail to open it,
    # which is caught and re-raised. We test the ValueError path directly
    # by mocking the whole pdfplumber open context.
    import unittest.mock as mock

    mock_page = mock.MagicMock()
    mock_page.extract_text.return_value = "A long enough paragraph that passes the minimum length filter for testing purposes here."
    mock_pdf = mock.MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = mock.MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = mock.MagicMock(return_value=False)

    with mock.patch("pdfplumber.open", return_value=mock_pdf):
        with pytest.raises(ValueError, match="no rule chunks"):
            parse_guidelines(pdf_path="fake.pdf", llm_client=AlwaysNoneLLM())


# Fix 5: stub path (pdf_path=None) still returns stubs, not an error
def test_stub_mode_pdf_path_none_returns_stubs():
    from src.ingestion.guidelines_parser import parse_guidelines
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    assert len(chunks) >= 6


# Fix 6: _MIN_PARAGRAPH_CHARS constant is exported from the module
def test_min_paragraph_chars_constant_exists():
    import src.ingestion.guidelines_parser as gp
    assert hasattr(gp, "_MIN_PARAGRAPH_CHARS"), "_MIN_PARAGRAPH_CHARS constant not found"
    assert isinstance(gp._MIN_PARAGRAPH_CHARS, int)
    assert gp._MIN_PARAGRAPH_CHARS > 0


# Fix 8: RuleChunk must be frozen (immutable)
def test_rule_chunk_is_frozen():
    from src.ingestion.guidelines_parser import RuleChunk
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
        chunk.chunk_id = "mutated"
