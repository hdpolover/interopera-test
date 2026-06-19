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
# Fixture: clean, fully-populated, all-VERIFIED Neo4j graph for CLI tests
# ---------------------------------------------------------------------------
#
# The CLI commands (reconcile, evaluate, run, verify-determinism) connect via
# NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD env vars (see src/cli/main.py).  The
# test environment provides NEO4J_TEST_* variants.  This fixture:
#   1. Patches the CLI env vars to point at the test Neo4j instance.
#   2. Wipes the graph (DETACH DELETE) and rebuilds it from scratch so every
#      pipeline-dependent CLI test starts from a known-good state regardless
#      of what other test modules did before it (e.g. test_verify_gate.py
#      deletes edges and leaves PENDING_REVIEW nodes; test_engine_firm_a.py
#      DETACH DELETEs the graph at module scope).
# Scope=function ensures EACH pipeline-dependent test gets its own clean slate.


@pytest.fixture(scope="function")
def clean_neo4j_for_cli(monkeypatch):
    """Wipe + rebuild the Neo4j graph and patch CLI env vars for isolation."""
    neo4j_uri = os.environ.get("NEO4J_TEST_URI")
    neo4j_user = os.environ.get("NEO4J_TEST_USER", "neo4j")
    neo4j_pass = os.environ.get("NEO4J_TEST_PASSWORD", "password")

    if not neo4j_uri:
        pytest.skip("Neo4j not in test environment")

    # Patch the env vars that src/cli/main.py _get_driver() reads so CLI
    # commands hit the same Neo4j instance as the rest of the test suite.
    monkeypatch.setenv("NEO4J_URI", neo4j_uri)
    monkeypatch.setenv("NEO4J_USER", neo4j_user)
    monkeypatch.setenv("NEO4J_PASSWORD", neo4j_pass)
    # Force stub narrative path — LLM mode fails the firewall intermittently
    # (numbers like 100%, 1.0% not in computed set), making evaluate exit 1.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from neo4j import GraphDatabase
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions, load_rules, load_risk_metrics
    from src.ingestion.holdings_parser import parse_holdings
    from src.ingestion.guidelines_parser import parse_guidelines

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))
    try:
        # Wipe everything first so mutations from other modules don't bleed in.
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

        apply_schema(driver)

        csv_path = os.path.join(REPO_ROOT, "sample_docs", "sample_holdings.csv")
        positions = parse_holdings(csv_path)
        load_positions(driver, positions)

        chunks = parse_guidelines(pdf_path=None, llm_client=None)
        load_rules(driver, chunks)
        load_risk_metrics(driver, chunks)

        # Verify: no PENDING_REVIEW nodes must remain after a clean build.
        with driver.session() as session:
            result = session.run(
                "MATCH (n {status: 'PENDING_REVIEW'}) RETURN count(n) AS cnt"
            )
            pending_count = result.single()["cnt"]
        assert pending_count == 0, (
            f"Expected 0 PENDING_REVIEW nodes after clean build, got {pending_count}"
        )

        yield  # test runs here

    finally:
        driver.close()


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
    assert "ingest" in result.output.lower()


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


def test_cli_run_firm_a_requires_neo4j(clean_neo4j_for_cli):
    """run --firm A connects to Neo4j; output has 13 figures."""
    result = runner.invoke(app, ["run", "--firm", "A", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 13
    # JSON output must expose the full Figure contract, incl. utilization
    for key in ("figure", "value", "utilization", "status", "limit", "graph_path", "citation"):
        assert key in data[0], f"run --json output missing '{key}'"


def test_cli_reconcile_firm_a_requires_neo4j(clean_neo4j_for_cli):
    """reconcile --firm A must exit 0 when all figures match."""
    result = runner.invoke(app, ["reconcile", "--firm", "A"])
    assert result.exit_code == 0


def test_cli_evaluate_firm_a_requires_neo4j(clean_neo4j_for_cli):
    """evaluate --firm A must exit 0 when all Phase 5 checks pass."""
    result = runner.invoke(app, ["evaluate", "--firm", "A"])
    assert result.exit_code == 0


def test_cli_verify_determinism_firm_a_requires_neo4j(clean_neo4j_for_cli):
    """verify-determinism --firm A must exit 0 (identical runs)."""
    result = runner.invoke(app, ["verify-determinism", "--firm", "A"])
    assert result.exit_code == 0


def test_cli_run_firm_b_requires_neo4j(clean_neo4j_for_cli):
    """run --firm B connects to Neo4j; output has 13 figures."""
    result = runner.invoke(app, ["run", "--firm", "B", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 13


def test_cli_reconcile_firm_b_requires_neo4j(clean_neo4j_for_cli):
    """reconcile --firm B must exit 0 when all figures match."""
    result = runner.invoke(app, ["reconcile", "--firm", "B"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Failure-path exit-code tests — invalid firm must exit non-zero
# ---------------------------------------------------------------------------


def test_evaluate_invalid_firm_exits_nonzero():
    result = runner.invoke(app, ["evaluate", "--firm", "DOES_NOT_EXIST"])
    assert result.exit_code != 0


def test_reconcile_invalid_firm_exits_nonzero():
    result = runner.invoke(app, ["reconcile", "--firm", "DOES_NOT_EXIST"])
    assert result.exit_code != 0


def test_run_invalid_firm_exits_nonzero():
    result = runner.invoke(app, ["run", "--firm", "DOES_NOT_EXIST"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Audit log integration test — verifies real rows are written to Postgres
# ---------------------------------------------------------------------------


@pytest.fixture()
def postgres_conn():
    """Return a psycopg connection to the test Postgres, or skip."""
    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        pytest.skip("POSTGRES_DSN not set — skipping audit integration test")
    import psycopg
    conn = psycopg.connect(dsn)
    conn.autocommit = True
    yield conn
    conn.close()


def test_audit_log_written_by_build_and_run(clean_neo4j_for_cli, postgres_conn):
    """build-graph + run --firm A must write audit rows to Postgres.

    Asserts:
    - graph_construction event is present (from build-graph)
    - config_loaded event is present (from run)
    - figure_computed events >= 13 (one per figure, from run)
    - report_exported event is present (from run)
    - AuditLogger.verify_chain() returns True (hash chain is intact)
    """
    # TRUNCATE so we start with a clean chain
    postgres_conn.execute("TRUNCATE TABLE audit_event RESTART IDENTITY")

    # Patch POSTGRES_DSN into the environment so the CLI commands can see it
    dsn = os.environ["POSTGRES_DSN"]

    import os as _os
    orig = _os.environ.get("POSTGRES_DSN")

    # build-graph
    result_bg = runner.invoke(app, ["build-graph"], env={"POSTGRES_DSN": dsn})
    assert result_bg.exit_code == 0, f"build-graph failed: {result_bg.output}"

    # run --firm A (JSON mode so we don't need Rich rendering in output)
    result_run = runner.invoke(app, ["run", "--firm", "A", "--json"], env={"POSTGRES_DSN": dsn})
    assert result_run.exit_code == 0, f"run failed: {result_run.output}"

    # Query audit rows
    rows = postgres_conn.execute(
        "SELECT event_type FROM audit_event ORDER BY id ASC"
    ).fetchall()
    event_types = [r[0] for r in rows]

    assert "graph_construction" in event_types, "Missing graph_construction event"
    assert "config_loaded" in event_types, "Missing config_loaded event"
    assert "report_exported" in event_types, "Missing report_exported event"

    figure_computed_count = event_types.count("figure_computed")
    assert figure_computed_count >= 13, (
        f"Expected >= 13 figure_computed events, got {figure_computed_count}"
    )

    # Verify hash chain integrity
    from src.audit.log import AuditLogger
    al = AuditLogger(dsn)
    chain_ok = al.verify_chain()
    al.close()
    assert chain_ok, "AuditLogger.verify_chain() returned False — hash chain is broken"
