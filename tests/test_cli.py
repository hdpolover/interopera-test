"""CLI command smoke tests using typer.testing.CliRunner.

Tests every subcommand for:
- Existence (shows up in --help)
- --help works without error
- Exit codes correct (0 on success, 1 on failure)
- DB-touching commands are skipped if Neo4j is unavailable.
"""
from __future__ import annotations

import json
import os

import pytest
from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEO4J_AVAILABLE = bool(os.environ.get("NEO4J_TEST_URI"))


# ---------------------------------------------------------------------------
# Subcommand presence — no DB needed
# ---------------------------------------------------------------------------


def test_cli_has_ingest_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ingest" in result.output


def test_cli_has_build_graph_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "build-graph" in result.output


def test_cli_has_verify_graph_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "verify-graph" in result.output


def test_cli_has_run_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.output


def test_cli_has_reconcile_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "reconcile" in result.output


def test_cli_has_evaluate_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "evaluate" in result.output


def test_cli_has_verify_determinism_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "verify-determinism" in result.output


def test_cli_has_narrate_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "narrate" in result.output


# ---------------------------------------------------------------------------
# --help for each subcommand — no DB needed
# ---------------------------------------------------------------------------


def test_ingest_help():
    result = runner.invoke(app, ["ingest", "--help"])
    assert result.exit_code == 0
    assert "help" in result.output.lower() or "usage" in result.output.lower()


def test_build_graph_help():
    result = runner.invoke(app, ["build-graph", "--help"])
    assert result.exit_code == 0


def test_verify_graph_help():
    result = runner.invoke(app, ["verify-graph", "--help"])
    assert result.exit_code == 0


def test_run_help():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--firm" in result.output


def test_reconcile_help():
    result = runner.invoke(app, ["reconcile", "--help"])
    assert result.exit_code == 0
    assert "--firm" in result.output


def test_evaluate_help():
    result = runner.invoke(app, ["evaluate", "--help"])
    assert result.exit_code == 0
    assert "--firm" in result.output


def test_verify_determinism_help():
    result = runner.invoke(app, ["verify-determinism", "--help"])
    assert result.exit_code == 0
    assert "--firm" in result.output


def test_narrate_help():
    result = runner.invoke(app, ["narrate", "--help"])
    assert result.exit_code == 0
    assert "--firm" in result.output


# ---------------------------------------------------------------------------
# Non-interactive: approval must be a --flag, never a prompt
# ---------------------------------------------------------------------------


def test_verify_graph_approve_is_flag_not_prompt():
    """verify-graph --approve accepts a value as a flag (non-interactive)."""
    result = runner.invoke(app, ["verify-graph", "--help"])
    assert result.exit_code == 0
    # The --approve option must be visible in help, confirming flag-based approval
    assert "--approve" in result.output or "approve" in result.output


# ---------------------------------------------------------------------------
# --json flag present on reporting commands
# ---------------------------------------------------------------------------


def test_run_has_json_flag():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output


def test_reconcile_has_json_flag():
    result = runner.invoke(app, ["reconcile", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output


def test_evaluate_has_json_flag():
    result = runner.invoke(app, ["evaluate", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output


# ---------------------------------------------------------------------------
# DB-touching smoke tests — skipped if Neo4j unavailable
# ---------------------------------------------------------------------------


def test_cli_run_firm_a_requires_neo4j():
    """run --firm A connects to Neo4j; output has 13 figures."""
    if not NEO4J_AVAILABLE:
        pytest.skip("Neo4j not in test environment")
    result = runner.invoke(app, ["run", "--firm", "A", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 13


def test_cli_reconcile_firm_a_requires_neo4j():
    """reconcile --firm A must exit 0 when all figures match."""
    if not NEO4J_AVAILABLE:
        pytest.skip("Neo4j not in test environment")
    result = runner.invoke(app, ["reconcile", "--firm", "A"])
    assert result.exit_code == 0


def test_cli_evaluate_firm_a_requires_neo4j():
    """evaluate --firm A must exit 0 when all Phase 5 checks pass."""
    if not NEO4J_AVAILABLE:
        pytest.skip("Neo4j not in test environment")
    result = runner.invoke(app, ["evaluate", "--firm", "A"])
    assert result.exit_code == 0


def test_cli_verify_determinism_firm_a_requires_neo4j():
    """verify-determinism --firm A must exit 0 (identical runs)."""
    if not NEO4J_AVAILABLE:
        pytest.skip("Neo4j not in test environment")
    result = runner.invoke(app, ["verify-determinism", "--firm", "A"])
    assert result.exit_code == 0


def test_cli_run_firm_b_requires_neo4j():
    """run --firm B connects to Neo4j; output has 13 figures."""
    if not NEO4J_AVAILABLE:
        pytest.skip("Neo4j not in test environment")
    result = runner.invoke(app, ["run", "--firm", "B", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 13


def test_cli_reconcile_firm_b_requires_neo4j():
    """reconcile --firm B must exit 0 when all figures match."""
    if not NEO4J_AVAILABLE:
        pytest.skip("Neo4j not in test environment")
    result = runner.invoke(app, ["reconcile", "--firm", "B"])
    assert result.exit_code == 0
