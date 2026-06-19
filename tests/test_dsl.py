"""Tests for 'generate-dsl' and 'preview-config' CLI commands (Bonus 2)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()

NEO4J_AVAILABLE = bool(os.environ.get("NEO4J_TEST_URI"))

REPO_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# generate-dsl tests
# ---------------------------------------------------------------------------


def test_generate_dsl_outputs_valid_yaml() -> None:
    """generate-dsl --firm A should produce output parseable as YAML."""
    result = runner.invoke(app, ["generate-dsl", "--firm", "A"])

    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}\n{result.output}"

    # Strip comment lines before YAML-parsing (comments are valid YAML but
    # our DSL mixes trailing comments on value lines — safe_load handles them)
    parsed = yaml.safe_load(result.output)
    assert parsed is not None
    assert "firm_id" in parsed


def test_generate_dsl_firm_a_keys_present() -> None:
    """generate-dsl --firm A output should contain all required DSL keys."""
    result = runner.invoke(app, ["generate-dsl", "--firm", "A"])

    assert result.exit_code == 0
    assert "firm_id" in result.output
    assert "include_fallen_angels" in result.output
    assert "group_key" in result.output
    assert "utilization_format" in result.output


def test_generate_dsl_firm_a_values() -> None:
    """generate-dsl --firm A should reflect firm_a.yaml values."""
    result = runner.invoke(app, ["generate-dsl", "--firm", "A"])

    assert result.exit_code == 0
    # firm_a has include_fallen_angels: false
    assert "false" in result.output
    # firm_a uses issuer grouping
    assert "issuer" in result.output
    # firm_a uses percent_1dp
    assert "percent_1dp" in result.output


def test_generate_dsl_firm_b() -> None:
    """generate-dsl --firm B should reflect firm_b.yaml values (include_fallen_angels: true)."""
    result = runner.invoke(app, ["generate-dsl", "--firm", "B"])

    assert result.exit_code == 0
    # firm_b has include_fallen_angels: true
    assert "true" in result.output
    # firm_b uses parent_issuer grouping
    assert "parent_issuer" in result.output
    # firm_b uses truncated_bps
    assert "truncated_bps" in result.output


def test_generate_dsl_invalid_firm() -> None:
    """generate-dsl with unknown firm ID should exit 1."""
    result = runner.invoke(app, ["generate-dsl", "--firm", "Z"])

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# preview-config tests
# ---------------------------------------------------------------------------


def _write_dsl(tmp_path: Path, **overrides) -> Path:
    """Write a minimal valid DSL file and return its path."""
    defaults = {
        "firm_id": "custom",
        "include_fallen_angels": False,
        "group_key": "issuer",
        "utilization_format": "percent_1dp",
    }
    defaults.update(overrides)
    dsl_path = tmp_path / "test.dsl"
    dsl_path.write_text(yaml.dump(defaults))
    return dsl_path


def test_preview_config_missing_file(tmp_path: Path) -> None:
    """preview-config with a non-existent DSL file should exit 1."""
    missing = str(tmp_path / "doesnotexist.dsl")
    result = runner.invoke(app, ["preview-config", "--dsl", missing])

    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "Error" in result.output


def test_preview_config_invalid_dsl(tmp_path: Path) -> None:
    """preview-config with an invalid utilization_format value should exit 1."""
    dsl_path = _write_dsl(tmp_path, utilization_format="bad_value")
    result = runner.invoke(app, ["preview-config", "--dsl", str(dsl_path)])

    assert result.exit_code == 1
    assert "validation" in result.output.lower() or "Error" in result.output


def test_preview_config_invalid_group_key(tmp_path: Path) -> None:
    """preview-config with an invalid group_key value should exit 1."""
    dsl_path = _write_dsl(tmp_path, group_key="wrong_key")
    result = runner.invoke(app, ["preview-config", "--dsl", str(dsl_path)])

    assert result.exit_code == 1


@pytest.mark.skipif(not NEO4J_AVAILABLE, reason="Neo4j not in test environment")
def test_preview_config_with_valid_dsl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """preview-config with valid DSL should exit 0 and print a table."""
    neo4j_uri = os.environ.get("NEO4J_TEST_URI")
    monkeypatch.setenv("NEO4J_URI", neo4j_uri)
    monkeypatch.setenv("NEO4J_USER", os.environ.get("NEO4J_TEST_USER", "neo4j"))
    monkeypatch.setenv("NEO4J_PASSWORD", os.environ.get("NEO4J_TEST_PASSWORD", "password"))

    dsl_path = _write_dsl(tmp_path)
    result = runner.invoke(app, ["preview-config", "--dsl", str(dsl_path)])

    assert result.exit_code == 0
    # Should show figure names in the table
    assert "allocation_sgs" in result.output or "Figure" in result.output


@pytest.mark.skipif(not NEO4J_AVAILABLE, reason="Neo4j not in test environment")
def test_preview_config_firm_b_knobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """preview-config with firm_b knobs should still exit 0."""
    neo4j_uri = os.environ.get("NEO4J_TEST_URI")
    monkeypatch.setenv("NEO4J_URI", neo4j_uri)
    monkeypatch.setenv("NEO4J_USER", os.environ.get("NEO4J_TEST_USER", "neo4j"))
    monkeypatch.setenv("NEO4J_PASSWORD", os.environ.get("NEO4J_TEST_PASSWORD", "password"))

    dsl_path = _write_dsl(
        tmp_path,
        firm_id="firm_b_custom",
        include_fallen_angels=True,
        group_key="parent_issuer",
        utilization_format="truncated_bps",
    )
    result = runner.invoke(app, ["preview-config", "--dsl", str(dsl_path)])

    assert result.exit_code == 0
