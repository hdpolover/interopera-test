"""Phase 5 evaluate tests: unit checks + end-to-end reconcile + traceability + firewall.

End-to-end tests (marked neo4j) require a running Neo4j instance and the full graph built
from sample_docs. All 13 figures must reconcile for both Firm A (xlsx answer key) and
Firm B (yaml expected). A real mismatch surfaces here and BLOCKS a pass — do NOT soften.
"""
from __future__ import annotations

import os
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEO4J_URI = os.environ.get("NEO4J_TEST_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_TEST_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_TEST_PASSWORD", "password")


# ---------------------------------------------------------------------------
# Shared test data (mirrors FIRM_A_FIGURES_DATA from test_reconciler)
# ---------------------------------------------------------------------------

from tests.test_reconciler import FIRM_A_FIGURES_DATA  # noqa: E402


def _make_passing_figures():
    from src.compute.registry import Figure
    return [
        Figure(
            figure=fid,
            value=val,
            utilization="n/a",
            status=stat,
            limit="",
            graph_path="test_path",
            citation={"chunk_id": "abc12345", "source_doc": "test.pdf", "page": 1, "passage_summary": "test"},
        )
        for fid, val, stat in FIRM_A_FIGURES_DATA
    ]


# ---------------------------------------------------------------------------
# Unit tests — no Neo4j needed
# ---------------------------------------------------------------------------

def test_evaluate_exits_zero_when_all_pass():
    """evaluate logic exits OK when all 13 figures reconcile against expected."""
    from src.reconcile.reconciler import reconcile
    from src.firewall.checker import check_firewall
    from src.narrative.narrator import Narrator

    figures = _make_passing_figures()
    firm_a_expected = {
        f.figure: {"value": f.value, "utilization": f.utilization, "status": f.status}
        for f in figures
    }

    recon_results = reconcile(figures, firm_a_expected)
    assert len(recon_results) == 13
    failed = [r for r in recon_results if not r.passed]
    assert not failed, f"Expected all 13 to pass, got failures: {[(r.figure, r.delta) for r in failed]}"

    narrator = Narrator(api_key=None)
    narrative = narrator.write_narrative(figures, firm_id="firm_a")
    fw_result = check_firewall(narrative, figures)
    assert fw_result.passed is True, f"Firewall failed on stub narrative: {fw_result.offending_numbers}"


def test_evaluate_detects_reconcile_failure():
    """evaluate detects when a figure value doesn't match expected."""
    from src.compute.registry import Figure
    from src.reconcile.reconciler import reconcile

    figures = _make_passing_figures()
    # Corrupt one figure to induce a mismatch
    wrong_figures = list(figures)
    wrong_figures[0] = Figure(
        figure="allocation_sgs",
        value="36.0%",
        status="OK",
        utilization="n/a",
        limit="20–60%",
        graph_path="test_path",
        citation={"chunk_id": "abc12345"},
    )
    firm_a_expected = {
        f.figure: {"value": f.value, "utilization": f.utilization, "status": f.status}
        for f in _make_passing_figures()
    }
    recon_results = reconcile(wrong_figures, firm_a_expected)
    assert len(recon_results) == 13
    failed = [r for r in recon_results if not r.passed]
    assert len(failed) == 1
    assert failed[0].figure == "allocation_sgs"
    assert "35.0%" in failed[0].delta
    assert "36.0%" in failed[0].delta


def test_firewall_detects_injected_number_in_evaluate():
    """evaluate detects when narrative contains a number not in computed figures."""
    from src.firewall.checker import check_firewall
    figures = _make_passing_figures()
    bad_narrative = "The SGS allocation is 35.0% but risk is 99.9% elevated."
    result = check_firewall(bad_narrative, figures)
    assert result.passed is False, "Firewall should reject 99.9% which is not in computed figures"


def test_traceability_check():
    """Each figure must have non-empty graph_path and citation.chunk_id."""
    figures = _make_passing_figures()
    for fig in figures:
        assert fig.graph_path, f"Empty graph_path for {fig.figure}"
        assert fig.citation.get("chunk_id"), f"Empty citation.chunk_id for {fig.figure}"


def test_traceability_fails_for_empty_graph_path():
    """Traceability check detects missing graph_path."""
    from src.compute.registry import Figure
    bad_fig = Figure(
        figure="allocation_sgs",
        value="35.0%",
        utilization="n/a",
        status="OK",
        limit="",
        graph_path="",  # empty — should fail traceability
        citation={"chunk_id": "abc12345"},
    )
    assert not bad_fig.graph_path


def test_traceability_fails_for_missing_chunk_id():
    """Traceability check detects missing citation.chunk_id."""
    from src.compute.registry import Figure
    bad_fig = Figure(
        figure="allocation_sgs",
        value="35.0%",
        utilization="n/a",
        status="OK",
        limit="",
        graph_path="test_path",
        citation={"source_doc": "test.pdf"},  # no chunk_id
    )
    assert not bad_fig.citation.get("chunk_id")


def test_empty_group_produces_error_figure():
    """Fix #7: _compute_group_value returns None when no groups → compute_figure routes to ERROR.

    Regression guard: previously returned Decimal('0') producing a spurious BREACH.
    """
    from unittest.mock import MagicMock
    from src.compute.engine import ComputeEngine
    from src.compute.config_loader import FirmConfig, NonIgConfig, GREConfig, ConcentrationConfig, OutputConfig
    from src.compute.registry import FigureSpec, Figure
    from decimal import Decimal

    config = FirmConfig(
        firm_id="firm_test",
        non_ig=NonIgConfig(include_fallen_angels=False),
        concentration=ConcentrationConfig(gre=GREConfig(group_key="issuer")),
        output=OutputConfig(utilization_format="percent_1dp"),
        limits={
            "allocation_sgs": {"min_pct": 0.20, "max_pct": 0.60},
            "allocation_mas_bills": {"min_pct": 0.00, "max_pct": 0.40},
            "allocation_ig_corp": {"min_pct": 0.10, "max_pct": 0.50},
            "allocation_high_yield": {"min_pct": 0.00, "max_pct": 0.15},
            "allocation_fx_bonds": {"min_pct": 0.00, "max_pct": 0.20},
            "allocation_structured_credit": {"min_pct": 0.00, "max_pct": 0.10},
            "allocation_cash": {"min_pct": 0.05},
            "aggregate_non_ig_exposure": {"max_pct": 0.20},
            "largest_single_corporate_issuer": {"max_pct": 0.08},
            "largest_gre_issuer": {"max_pct": 0.12},
            "liquid_assets_ratio": {"min_pct": 0.25},
            "portfolio_duration": {"min_years": 2.0, "max_years": 6.5},
            "portfolio_dv01": {"max_sgd": 85000},
        },
    )

    # Mock driver: citation query returns a valid chunk, pending check returns no pending nodes
    citation_record = {"chunk_id": "cid", "source_doc": "test.pdf", "page": 1, "passage_summary": "test"}
    pending_record = {"cnt": 0}

    call_count = [0]

    def mock_run(query, **kwargs):
        result = MagicMock()
        if "PENDING_REVIEW" in query and "count" in query:
            result.single.return_value = pending_record
        else:
            result.single.return_value = citation_record
        result.__iter__ = MagicMock(return_value=iter([]))
        return result

    mock_session = MagicMock()
    mock_session.run.side_effect = mock_run
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session

    from src.graph import queries as gq
    original_positions_by_issuer = gq.positions_by_issuer
    original_all_positions = gq.all_positions
    gq.positions_by_issuer = MagicMock(return_value={})  # empty groups
    gq.all_positions = MagicMock(return_value=[{"market_value_sgd": "100000000", "modified_duration": "3.0"}])

    try:
        engine = ComputeEngine(mock_driver, config)
        engine._nav = Decimal("100000000")
        spec = FigureSpec(
            id="largest_single_corporate_issuer",
            selector="positions_by_issuer",
            predicate={"group_key": "issuer", "issuer_type_filter": "corporate"},
            aggregator="max_group_pct",
            limit_ref="corporate_issuer_limit",
            comparator="max_cap",
            formatter="percent_1dp",
            limit_display="max 8%",
            utilization_basis="cap",
        )
        figure = engine.compute_figure(spec)
        assert figure.status == "ERROR", (
            f"Expected ERROR for empty groups, got {figure.status!r} with value {figure.value!r}"
        )
        assert figure.value == "ERROR"
    finally:
        gq.positions_by_issuer = original_positions_by_issuer
        gq.all_positions = original_all_positions


def test_reconcile_13_figures_from_data():
    """Verify FIRM_A_FIGURES_DATA contains exactly 13 entries with unique figure IDs."""
    assert len(FIRM_A_FIGURES_DATA) == 13
    ids = [fid for fid, _, _ in FIRM_A_FIGURES_DATA]
    assert len(set(ids)) == 13, "Duplicate figure IDs in FIRM_A_FIGURES_DATA"


def test_cli_module_importable():
    """CLI module must be importable without side effects."""
    import importlib
    mod = importlib.import_module("src.cli.main")
    assert hasattr(mod, "app"), "src.cli.main must expose 'app' (Typer instance)"
    assert hasattr(mod, "evaluate"), "src.cli.main must expose 'evaluate' command"
    assert hasattr(mod, "reconcile"), "src.cli.main must expose 'reconcile' command"
    assert hasattr(mod, "verify_determinism"), "src.cli.main must expose 'verify_determinism' command"


def test_evaluate_report_structure():
    """evaluate produces a JSON report with reconcile, traceability, and firewall keys."""
    from src.reconcile.reconciler import reconcile
    from src.firewall.checker import check_firewall
    from src.narrative.narrator import Narrator

    figures = _make_passing_figures()
    expected = {
        f.figure: {"value": f.value, "utilization": f.utilization, "status": f.status}
        for f in figures
    }

    recon_results = reconcile(figures, expected)
    assert len(recon_results) == 13
    recon_failed = [r for r in recon_results if not r.passed]
    trace_failed = [f for f in figures if not f.graph_path or not f.citation.get("chunk_id")]
    narrator = Narrator(api_key=None)
    narrative = narrator.write_narrative(figures, firm_id="firm_a")
    fw_result = check_firewall(narrative, figures)

    report = {
        "firm_id": "firm_a",
        "reconcile": {
            "passed": len(recon_failed) == 0,
            "total": len(recon_results),
            "failed": [r.__dict__ for r in recon_failed],
        },
        "traceability": {
            "passed": len(trace_failed) == 0,
            "failed_figures": [f.figure for f in trace_failed],
        },
        "firewall": {
            "passed": fw_result.passed,
            "offending_numbers": fw_result.offending_numbers,
        },
        "overall_passed": len(recon_failed) == 0 and len(trace_failed) == 0 and fw_result.passed,
    }

    assert report["reconcile"]["passed"] is True
    assert report["traceability"]["passed"] is True
    assert report["firewall"]["passed"] is True
    assert report["overall_passed"] is True
    assert report["reconcile"]["total"] == 13


# ---------------------------------------------------------------------------
# Neo4j integration fixtures (shared by both firm tests)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def neo4j_driver():
    """Connect to Neo4j; skip if unavailable."""
    try:
        from neo4j import GraphDatabase
        drv = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
        drv.verify_connectivity()
        yield drv
        drv.close()
    except Exception as e:
        pytest.skip(f"Neo4j not available: {e}")


@pytest.fixture(scope="module")
def populated_graph(neo4j_driver):
    """Wipe graph, load sample_docs (holdings + guidelines) once for both firm tests."""
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions, load_rules
    from src.ingestion.holdings_parser import parse_holdings
    from src.ingestion.guidelines_parser import parse_guidelines

    with neo4j_driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

    apply_schema(neo4j_driver)
    csv_path = os.path.join(REPO_ROOT, "sample_docs", "sample_holdings.csv")
    positions = parse_holdings(csv_path)
    load_positions(neo4j_driver, positions)
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    load_rules(neo4j_driver, chunks)
    return neo4j_driver


# ---------------------------------------------------------------------------
# End-to-end: Firm A — all 13 figures must reconcile against answer key
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def firm_a_e2e_figures(populated_graph):
    from src.compute.config_loader import load_config
    from src.compute.engine import ComputeEngine

    config = load_config(
        os.path.join(REPO_ROOT, "config", "base.yaml"),
        os.path.join(REPO_ROOT, "config", "firm_a.yaml"),
    )
    engine = ComputeEngine(populated_graph, config)
    return engine.run_all()


def test_e2e_firm_a_reconcile_all_13(firm_a_e2e_figures):
    """HARD OBLIGATION (constraint-4): All 13 Firm A figures reconcile against xlsx answer key.

    If ANY figure fails, this test surfaces the exact mismatch and BLOCKS a pass.
    Do NOT loosen comparison or edit expected values — a real mismatch is a finding.
    """
    from src.reconcile.reconciler import reconcile, parse_answer_key_xlsx

    xlsx_path = os.path.join(REPO_ROOT, "sample_docs", "firm_A_answer_key.xlsx")
    expected = parse_answer_key_xlsx(xlsx_path)
    assert len(expected) == 13, f"Answer key has {len(expected)} figures, expected 13"

    results = reconcile(firm_a_e2e_figures, expected)
    failed = [r for r in results if not r.passed]

    mismatch_detail = "\n".join(
        f"  FAIL {r.figure}: computed=({r.computed_value!r}, {r.computed_utilization!r}, {r.computed_status!r})"
        f" expected=({r.expected_value!r}, {r.expected_utilization!r}, {r.expected_status!r})"
        f" delta={r.delta!r}"
        for r in failed
    )
    assert not failed, (
        f"BLOCKED: Firm A — {len(failed)}/13 figures did NOT reconcile:\n{mismatch_detail}"
    )

    passed_count = len([r for r in results if r.passed])
    assert passed_count == 13, f"Firm A: only {passed_count}/13 reconciled"


def test_e2e_firm_a_traceability(firm_a_e2e_figures):
    """Constraint-2: every Firm A figure has a non-empty graph_path and citation chunk_id."""
    trace_failed = [
        f for f in firm_a_e2e_figures
        if not f.graph_path or not f.citation.get("chunk_id")
    ]
    detail = "\n".join(
        f"  {f.figure}: graph_path={f.graph_path!r} chunk_id={f.citation.get('chunk_id')!r}"
        for f in trace_failed
    )
    assert not trace_failed, (
        f"BLOCKED: Firm A traceability — {len(trace_failed)} figures missing graph_path or chunk_id:\n{detail}"
    )


def test_e2e_firm_a_firewall(firm_a_e2e_figures):
    """Constraint-3: stub narrative for Firm A introduces no number outside computed figures."""
    from src.firewall.checker import check_firewall
    from src.narrative.narrator import Narrator

    narrator = Narrator(api_key=None)
    narrative = narrator.write_narrative(firm_a_e2e_figures, firm_id="firm_a")
    fw_result = check_firewall(narrative, firm_a_e2e_figures)
    assert fw_result.passed is True, (
        f"BLOCKED: Firm A firewall — offending numbers in narrative: {fw_result.offending_numbers}\n"
        f"Narrative: {narrative[:500]}"
    )


# ---------------------------------------------------------------------------
# End-to-end: Firm B — all 13 figures must reconcile against yaml expected
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def firm_b_e2e_figures(populated_graph):
    from src.compute.config_loader import load_config
    from src.compute.engine import ComputeEngine

    config = load_config(
        os.path.join(REPO_ROOT, "config", "base.yaml"),
        os.path.join(REPO_ROOT, "config", "firm_b.yaml"),
    )
    engine = ComputeEngine(populated_graph, config)
    return engine.run_all()


def test_e2e_firm_b_reconcile_all_13(firm_b_e2e_figures):
    """HARD OBLIGATION (constraint-4): All 13 Firm B figures reconcile against yaml expected.

    If ANY figure fails, this test surfaces the exact mismatch and BLOCKS a pass.
    Do NOT loosen comparison or edit expected values — a real mismatch is a finding.
    """
    from src.reconcile.reconciler import reconcile, parse_expected_yaml

    yaml_path = os.path.join(REPO_ROOT, "config", "firm_b_expected.yaml")
    expected = parse_expected_yaml(yaml_path)
    assert len(expected) == 13, f"firm_b_expected.yaml has {len(expected)} figures, expected 13"

    results = reconcile(firm_b_e2e_figures, expected)
    failed = [r for r in results if not r.passed]

    mismatch_detail = "\n".join(
        f"  FAIL {r.figure}: computed=({r.computed_value!r}, {r.computed_utilization!r}, {r.computed_status!r})"
        f" expected=({r.expected_value!r}, {r.expected_utilization!r}, {r.expected_status!r})"
        f" delta={r.delta!r}"
        for r in failed
    )
    assert not failed, (
        f"BLOCKED: Firm B — {len(failed)}/13 figures did NOT reconcile:\n{mismatch_detail}"
    )

    passed_count = len([r for r in results if r.passed])
    assert passed_count == 13, f"Firm B: only {passed_count}/13 reconciled"

    # Named assertions for Firm B's distinct figures (vs Firm A)
    figs_by_id = {f.figure: f for f in firm_b_e2e_figures}
    assert figs_by_id["aggregate_non_ig_exposure"].value == "21.0%", (
        f"Firm B aggregate_non_ig_exposure value mismatch: expected '21.0%', got {figs_by_id['aggregate_non_ig_exposure'].value!r}"
    )
    assert figs_by_id["aggregate_non_ig_exposure"].utilization == "10500 bps", (
        f"Firm B aggregate_non_ig_exposure utilization mismatch: expected '10500 bps', got {figs_by_id['aggregate_non_ig_exposure'].utilization!r}"
    )
    assert figs_by_id["aggregate_non_ig_exposure"].status == "BREACH", (
        f"Firm B aggregate_non_ig_exposure status mismatch: expected 'BREACH', got {figs_by_id['aggregate_non_ig_exposure'].status!r}"
    )
    assert figs_by_id["largest_gre_issuer"].value == "13.0%", (
        f"Firm B largest_gre_issuer value mismatch: expected '13.0%', got {figs_by_id['largest_gre_issuer'].value!r}"
    )
    assert figs_by_id["largest_gre_issuer"].utilization == "10833 bps", (
        f"Firm B largest_gre_issuer utilization mismatch: expected '10833 bps', got {figs_by_id['largest_gre_issuer'].utilization!r}"
    )
    assert figs_by_id["largest_gre_issuer"].status == "BREACH", (
        f"Firm B largest_gre_issuer status mismatch: expected 'BREACH', got {figs_by_id['largest_gre_issuer'].status!r}"
    )


def test_e2e_firm_b_traceability(firm_b_e2e_figures):
    """Constraint-2: every Firm B figure has a non-empty graph_path and citation chunk_id."""
    trace_failed = [
        f for f in firm_b_e2e_figures
        if not f.graph_path or not f.citation.get("chunk_id")
    ]
    detail = "\n".join(
        f"  {f.figure}: graph_path={f.graph_path!r} chunk_id={f.citation.get('chunk_id')!r}"
        for f in trace_failed
    )
    assert not trace_failed, (
        f"BLOCKED: Firm B traceability — {len(trace_failed)} figures missing graph_path or chunk_id:\n{detail}"
    )


def test_e2e_firm_b_firewall(firm_b_e2e_figures):
    """Constraint-3: stub narrative for Firm B introduces no number outside computed figures."""
    from src.firewall.checker import check_firewall
    from src.narrative.narrator import Narrator

    narrator = Narrator(api_key=None)
    narrative = narrator.write_narrative(firm_b_e2e_figures, firm_id="firm_b")
    fw_result = check_firewall(narrative, firm_b_e2e_figures)
    assert fw_result.passed is True, (
        f"BLOCKED: Firm B firewall — offending numbers in narrative: {fw_result.offending_numbers}\n"
        f"Narrative: {narrative[:500]}"
    )


# ---------------------------------------------------------------------------
# End-to-end: combined summary assertion (prints human-readable summary)
# ---------------------------------------------------------------------------

def test_e2e_phase5_summary(firm_a_e2e_figures, firm_b_e2e_figures):
    """Combined Phase 5 summary: both firms must pass reconcile + traceability + firewall.

    This test acts as the single authoritative statement of constraint-4 compliance.
    """
    from src.reconcile.reconciler import reconcile, parse_answer_key_xlsx, parse_expected_yaml
    from src.firewall.checker import check_firewall
    from src.narrative.narrator import Narrator

    # --- Firm A ---
    xlsx_path = os.path.join(REPO_ROOT, "sample_docs", "firm_A_answer_key.xlsx")
    firm_a_expected = parse_answer_key_xlsx(xlsx_path)
    firm_a_results = reconcile(firm_a_e2e_figures, firm_a_expected)
    firm_a_failed = [r for r in firm_a_results if not r.passed]

    firm_a_trace_failed = [
        f for f in firm_a_e2e_figures
        if not f.graph_path or not f.citation.get("chunk_id")
    ]
    narrator = Narrator(api_key=None)
    firm_a_narrative = narrator.write_narrative(firm_a_e2e_figures, firm_id="firm_a")
    firm_a_fw = check_firewall(firm_a_narrative, firm_a_e2e_figures)

    # --- Firm B ---
    yaml_path = os.path.join(REPO_ROOT, "config", "firm_b_expected.yaml")
    firm_b_expected = parse_expected_yaml(yaml_path)
    firm_b_results = reconcile(firm_b_e2e_figures, firm_b_expected)
    firm_b_failed = [r for r in firm_b_results if not r.passed]

    firm_b_trace_failed = [
        f for f in firm_b_e2e_figures
        if not f.graph_path or not f.citation.get("chunk_id")
    ]
    firm_b_narrative = narrator.write_narrative(firm_b_e2e_figures, firm_id="firm_b")
    firm_b_fw = check_firewall(firm_b_narrative, firm_b_e2e_figures)

    # --- Assert all passing ---
    all_errors = []
    if firm_a_failed:
        all_errors.append(
            f"Firm A reconcile: {len(firm_a_failed)}/13 FAILED — "
            + "; ".join(f"{r.figure}:{r.delta}" for r in firm_a_failed)
        )
    if firm_a_trace_failed:
        all_errors.append(f"Firm A traceability: {[f.figure for f in firm_a_trace_failed]}")
    if not firm_a_fw.passed:
        all_errors.append(f"Firm A firewall: {firm_a_fw.offending_numbers}")
    if firm_b_failed:
        all_errors.append(
            f"Firm B reconcile: {len(firm_b_failed)}/13 FAILED — "
            + "; ".join(f"{r.figure}:{r.delta}" for r in firm_b_failed)
        )
    if firm_b_trace_failed:
        all_errors.append(f"Firm B traceability: {[f.figure for f in firm_b_trace_failed]}")
    if not firm_b_fw.passed:
        all_errors.append(f"Firm B firewall: {firm_b_fw.offending_numbers}")

    assert not all_errors, (
        "Phase 5 BLOCKED — one or more checks failed:\n"
        + "\n".join(f"  - {e}" for e in all_errors)
    )

    # Confirm exact counts for the report
    assert len([r for r in firm_a_results if r.passed]) == 13, "Firm A: not 13/13"
    assert len([r for r in firm_b_results if r.passed]) == 13, "Firm B: not 13/13"
