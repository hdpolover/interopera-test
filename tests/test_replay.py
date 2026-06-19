"""Tests for the 'replay' CLI command (Bonus 1)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_SAMPLE_FIGURES = [
    {
        "figure": "allocation_sgs",
        "value": "35.0%",
        "utilization": "58.3%",
        "status": "OK",
        "limit": "20–60%",
        "graph_path": "(Position:SGS-01)-[:IN_ASSET_CLASS]->(AssetClass:sgs)",
        "citation": {
            "chunk_id": "abc123",
            "page": 2,
            "passage_summary": "Asset class allocation limits for all buckets.",
            "source_doc": "sample_fund_guidelines.pdf",
        },
    },
    {
        "figure": "largest_gre_issuer",
        "value": "10.5%",
        "utilization": "87.5%",
        "status": "OK",
        "limit": "max 12%",
        "graph_path": "(Position:GRE-01)-[:ISSUED_BY]->(Issuer:temasek)",
        "citation": {
            "chunk_id": "def456",
            "page": 4,
            "passage_summary": "GRE concentration limits apply to parent issuer grouping.",
            "source_doc": "sample_fund_guidelines.pdf",
        },
    },
]


@pytest.fixture()
def figures_firm_a(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write a temporary figures_firm_a.json and patch OUT_DIR in main.py."""
    figures_file = tmp_path / "figures_firm_a.json"
    figures_file.write_text(json.dumps(_SAMPLE_FIGURES))

    import src.cli.main as cli_main
    monkeypatch.setattr(cli_main, "OUT_DIR", tmp_path)
    monkeypatch.setattr(cli_main, "SAMPLE_DOCS", tmp_path)
    return figures_file


# ---------------------------------------------------------------------------
# Test: missing figures file → exit 1 with helpful message
# ---------------------------------------------------------------------------


def test_replay_missing_figures_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """replay should exit 1 and print a helpful message when figures file is missing."""
    import src.cli.main as cli_main
    monkeypatch.setattr(cli_main, "OUT_DIR", tmp_path)

    result = runner.invoke(app, ["replay", "--figure", "allocation_sgs", "--firm", "A"])

    assert result.exit_code == 1
    assert "run" in result.output.lower() or "Error" in result.output


# ---------------------------------------------------------------------------
# Test: valid figures file — graph_path, passage_summary, chunk_id in output
# ---------------------------------------------------------------------------


def test_replay_shows_graph_path(figures_firm_a: Path) -> None:
    """replay should print the graph_path of the requested figure."""
    result = runner.invoke(app, ["replay", "--figure", "allocation_sgs", "--firm", "A"])

    assert result.exit_code == 0
    assert "(Position:SGS-01)" in result.output


def test_replay_shows_passage_summary(figures_firm_a: Path) -> None:
    """replay should print the citation passage_summary."""
    result = runner.invoke(app, ["replay", "--figure", "allocation_sgs", "--firm", "A"])

    assert result.exit_code == 0
    assert "Asset class allocation limits for all buckets." in result.output


def test_replay_shows_chunk_id(figures_firm_a: Path) -> None:
    """replay should print the citation chunk_id."""
    result = runner.invoke(app, ["replay", "--figure", "allocation_sgs", "--firm", "A"])

    assert result.exit_code == 0
    assert "abc123" in result.output


# ---------------------------------------------------------------------------
# Test: unknown figure → exit 1
# ---------------------------------------------------------------------------


def test_replay_unknown_figure_exits_1(figures_firm_a: Path) -> None:
    """replay should exit 1 when the figure name is not in the figures file."""
    result = runner.invoke(app, ["replay", "--figure", "nonexistent_figure", "--firm", "A"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "Error" in result.output


# ---------------------------------------------------------------------------
# Test: Firm B shows "no answer key" message
# ---------------------------------------------------------------------------


def test_replay_firm_b_no_answer_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """replay for Firm B should print a note that no answer key is available."""
    figures_file = tmp_path / "figures_firm_b.json"
    figures_file.write_text(json.dumps(_SAMPLE_FIGURES))

    import src.cli.main as cli_main
    monkeypatch.setattr(cli_main, "OUT_DIR", tmp_path)
    monkeypatch.setattr(cli_main, "SAMPLE_DOCS", tmp_path)

    result = runner.invoke(app, ["replay", "--figure", "allocation_sgs", "--firm", "B"])

    assert result.exit_code == 0
    output_lower = result.output.lower()
    assert "no answer key" in output_lower or "firm b" in output_lower


# ---------------------------------------------------------------------------
# Test: delta calculation (mock answer key)
# ---------------------------------------------------------------------------


def test_replay_delta_calculation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """replay should compute a numeric delta against the answer key value."""
    import openpyxl

    # Create a minimal answer-key xlsx
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Section", "Metric", "Value", "Limit", "Utilization", "Status", "Source"])
    ws.append(["Allocation", "Singapore Government Securities", "33.0%", "20-60%", "55.0%", "OK", "doc"])
    xlsx_path = tmp_path / "firm_A_answer_key.xlsx"
    wb.save(str(xlsx_path))

    figures_file = tmp_path / "figures_firm_a.json"
    figures_file.write_text(json.dumps(_SAMPLE_FIGURES))

    import src.cli.main as cli_main
    monkeypatch.setattr(cli_main, "OUT_DIR", tmp_path)
    monkeypatch.setattr(cli_main, "SAMPLE_DOCS", tmp_path)

    result = runner.invoke(app, ["replay", "--figure", "allocation_sgs", "--firm", "A"])

    assert result.exit_code == 0
    # Should show expected, computed, and delta values
    assert "33.0%" in result.output or "Expected" in result.output


# ---------------------------------------------------------------------------
# Test: config knob section is displayed
# ---------------------------------------------------------------------------


def test_replay_shows_config_knob_for_gre(figures_firm_a: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """replay for largest_gre_issuer should mention concentration.gre.group_key."""
    import src.cli.main as cli_main
    monkeypatch.setattr(cli_main, "CONFIG_DIR", Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "config")

    result = runner.invoke(app, ["replay", "--figure", "largest_gre_issuer", "--firm", "A"])

    assert result.exit_code == 0
    assert "concentration.gre.group_key" in result.output
