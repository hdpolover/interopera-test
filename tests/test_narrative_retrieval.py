"""Tests for global/local passage retrieval for narrative (Bonus 3)."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.compute.registry import Figure
from src.graph.queries import retrieve_passages_for_narrative
from src.narrative.narrator import Narrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_figure(
    figure_id: str,
    chunk_id: str = "chunk_01",
    passage_summary: str = "A rule passage.",
    page: int = 1,
) -> Figure:
    return Figure(
        figure=figure_id,
        value="10.0%",
        utilization="50.0%",
        status="OK",
        limit="max 20%",
        graph_path=f"(Position)-[:IN]->(AssetClass:{figure_id})",
        citation={
            "chunk_id": chunk_id,
            "page": page,
            "passage_summary": passage_summary,
            "source_doc": "guidelines.pdf",
        },
    )


def _make_driver_with_chunks(chunks: list[dict[str, Any]]) -> MagicMock:
    """Return a mock Neo4j driver whose session yields the given chunk records."""
    record_list = []
    for chunk in chunks:
        rec = MagicMock()
        rec.__iter__ = lambda self, _c=chunk: iter(_c.items())
        rec.keys = lambda _c=chunk: list(_c.keys())
        rec.__getitem__ = lambda self, k, _c=chunk: _c[k]
        record_list.append(rec)

    session_mock = MagicMock()
    run_result = MagicMock()
    run_result.__iter__ = lambda self: iter(record_list)
    session_mock.run.return_value = run_result
    session_mock.__enter__ = lambda self: self
    session_mock.__exit__ = MagicMock(return_value=False)

    driver = MagicMock()
    driver.session.return_value = session_mock
    return driver


# ---------------------------------------------------------------------------
# retrieve_passages_for_narrative
# ---------------------------------------------------------------------------


def test_retrieve_passages_returns_global_chunks() -> None:
    """retrieve_passages_for_narrative should return passages from graph query."""
    chunks = [
        {"chunk_id": "c001", "passage_summary": "Allocation rule.", "rule_type": "allocation limits", "page": 2},
        {"chunk_id": "c002", "passage_summary": "Concentration rule.", "rule_type": "concentration limits", "page": 3},
    ]
    driver = _make_driver_with_chunks(chunks)
    figures: list[Figure] = []

    result = retrieve_passages_for_narrative(driver, figures)

    chunk_ids = {p["chunk_id"] for p in result}
    assert "c001" in chunk_ids
    assert "c002" in chunk_ids


def test_retrieve_passages_local_fallback() -> None:
    """retrieve_passages should include figure citation passages when graph returns nothing."""
    driver = _make_driver_with_chunks([])
    figures = [_make_figure("allocation_sgs", chunk_id="local_chunk", passage_summary="Local passage.")]

    result = retrieve_passages_for_narrative(driver, figures)

    chunk_ids = {p["chunk_id"] for p in result}
    assert "local_chunk" in chunk_ids


def test_retrieve_passages_deduplicates_by_chunk_id() -> None:
    """Global and local passages with the same chunk_id should appear only once."""
    chunks = [
        {"chunk_id": "shared_id", "passage_summary": "Global version.", "rule_type": "allocation limits", "page": 1},
    ]
    driver = _make_driver_with_chunks(chunks)
    figures = [_make_figure("allocation_sgs", chunk_id="shared_id", passage_summary="Local version.")]

    result = retrieve_passages_for_narrative(driver, figures)

    matching = [p for p in result if p["chunk_id"] == "shared_id"]
    assert len(matching) == 1
    # Global retrieval takes priority
    assert matching[0]["passage_summary"] == "Global version."


def test_retrieve_passages_empty_graph_graceful() -> None:
    """retrieve_passages should not raise when graph has no SourceChunk nodes."""
    driver = _make_driver_with_chunks([])
    figures = [_make_figure("allocation_sgs")]

    result = retrieve_passages_for_narrative(driver, figures)

    # Should return at least the figure's local citation
    assert isinstance(result, list)


def test_retrieve_passages_driver_error_graceful() -> None:
    """retrieve_passages should not raise when the graph query raises an exception."""
    driver = MagicMock()
    session_mock = MagicMock()
    session_mock.run.side_effect = RuntimeError("connection refused")
    session_mock.__enter__ = lambda self: self
    session_mock.__exit__ = MagicMock(return_value=False)
    driver.session.return_value = session_mock

    figures = [_make_figure("allocation_sgs", chunk_id="fallback", passage_summary="Fallback passage.")]

    result = retrieve_passages_for_narrative(driver, figures)

    # Should fall back to local citations without raising
    chunk_ids = {p["chunk_id"] for p in result}
    assert "fallback" in chunk_ids


# ---------------------------------------------------------------------------
# Narrator — driver integration
# ---------------------------------------------------------------------------


def test_narrator_driver_none_unchanged_stub() -> None:
    """Without a driver, write_narrative returns the deterministic stub."""
    figures = [_make_figure("allocation_sgs")]
    narrator = Narrator(api_key=None, client=None, driver=None)

    narrative = narrator.write_narrative(figures, firm_id="firm_a")

    assert isinstance(narrative, str)
    assert len(narrative) > 0
    # Stub always contains the firm id
    assert "firm_a" in narrative.lower() or "FIRM_A" in narrative


def test_narrator_with_driver_includes_passages_in_prompt() -> None:
    """When driver is set, _llm_narrative should include passage context in the prompt."""
    figures = [_make_figure("allocation_sgs", chunk_id="p01", passage_summary="Rule about allocation.")]

    # Use a mock client so we can inspect the prompt without hitting the API
    captured_prompt: list[str] = []

    class _MockMessage:
        content = [MagicMock(text="Narrative text from LLM.")]

    class _MockClient:
        def messages(self):
            pass

        @property
        def messages(self):  # type: ignore[override]
            class _Messages:
                @staticmethod
                def create(**kwargs):
                    captured_prompt.append(kwargs["messages"][0]["content"])
                    return _MockMessage()
            return _Messages()

    chunks = [
        {"chunk_id": "p01", "passage_summary": "Rule about allocation.", "rule_type": "allocation limits", "page": 2},
    ]
    driver = _make_driver_with_chunks(chunks)

    narrator = Narrator(api_key=None, client=_MockClient(), driver=driver)
    narrative = narrator.write_narrative(figures, firm_id="firm_a")

    # The returned narrative should be our mock LLM response
    assert "Narrative text from LLM." in narrative

    # The prompt captured by the mock client should include passage context
    assert len(captured_prompt) == 1
    prompt = captured_prompt[0]
    assert "Rule about allocation." in prompt or "Regulatory basis" in prompt


def test_narrator_without_driver_stub_no_passage() -> None:
    """Stub path should not include passage section when driver is None."""
    figures = [_make_figure("allocation_sgs")]
    narrator = Narrator(api_key=None, client=None, driver=None)

    narrative = narrator.write_narrative(figures, firm_id="firm_a")

    # Stub narrative should not contain the retrieval section header
    assert "Regulatory basis" not in narrative
    assert "Figure-specific citations" not in narrative


def test_narrator_init_accepts_driver_parameter() -> None:
    """Narrator.__init__ should accept driver as a keyword argument."""
    mock_driver = MagicMock()
    narrator = Narrator(driver=mock_driver)

    assert narrator._driver is mock_driver


def test_narrator_driver_retrieval_failure_falls_back_to_stub_prompt() -> None:
    """If retrieve_passages raises, _llm_narrative should still return a narrative."""
    figures = [_make_figure("allocation_sgs")]

    class _MockMessage:
        content = [MagicMock(text="LLM narrative.")]

    captured_prompt: list[str] = []

    class _MockClient:
        @property
        def messages(self):
            class _Messages:
                @staticmethod
                def create(**kwargs):
                    captured_prompt.append(kwargs["messages"][0]["content"])
                    return _MockMessage()
            return _Messages()

    broken_driver = MagicMock()
    broken_session = MagicMock()
    broken_session.run.side_effect = RuntimeError("broken")
    broken_session.__enter__ = lambda self: self
    broken_session.__exit__ = MagicMock(return_value=False)
    broken_driver.session.return_value = broken_session

    narrator = Narrator(api_key=None, client=_MockClient(), driver=broken_driver)
    narrative = narrator.write_narrative(figures, firm_id="firm_a")

    assert "LLM narrative." in narrative
    # Prompt should still be sent even if passage retrieval failed
    assert len(captured_prompt) == 1
