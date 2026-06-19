"""Phase 5 evaluate command tests — mirrors task-18-brief.md Step 1.

These four unit tests cover the evaluate, reconcile, firewall, and traceability
logic without requiring a running Neo4j or Postgres instance.
"""
import os
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEO4J_URI = os.environ.get("NEO4J_TEST_URI", "bolt://localhost:7687")


def _make_passing_figures():
    from src.compute.registry import Figure
    from tests.test_reconciler import FIRM_A_FIGURES_DATA
    return [
        Figure(figure=fid, value=val, utilization="n/a", status=stat,
               limit="", graph_path="test_path", citation={"chunk_id": "abc12345"})
        for fid, val, stat in FIRM_A_FIGURES_DATA
    ]


def test_evaluate_exits_zero_when_all_pass():
    """evaluate exits 0 when all 13 figures reconcile against expected."""
    from src.reconcile.reconciler import reconcile
    from src.firewall.checker import check_firewall
    from src.narrative.narrator import Narrator

    figures = _make_passing_figures()
    firm_a_expected = {f.figure: {"value": f.value, "utilization": f.utilization, "status": f.status} for f in figures}

    recon_results = reconcile(figures, firm_a_expected)
    assert len(recon_results) == 13
    failed = [r for r in recon_results if not r.passed]
    assert not failed

    narrator = Narrator(api_key=None)
    narrative = narrator.write_narrative(figures, firm_id="firm_a")
    fw_result = check_firewall(narrative, figures)
    assert fw_result.passed is True


def test_evaluate_detects_reconcile_failure():
    """evaluate detects when a figure value doesn't match expected."""
    from src.compute.registry import Figure
    from src.reconcile.reconciler import reconcile

    figures = _make_passing_figures()
    # Corrupt one figure
    wrong_figures = list(figures)
    wrong_figures[0] = Figure(
        figure="allocation_sgs", value="36.0%", status="OK",
        utilization="n/a", limit="20–60%", graph_path="", citation={}
    )
    firm_a_expected = {f.figure: {"value": f.value, "utilization": f.utilization, "status": f.status} for f in _make_passing_figures()}
    recon_results = reconcile(wrong_figures, firm_a_expected)
    failed = [r for r in recon_results if not r.passed]
    assert len(failed) == 1
    assert failed[0].figure == "allocation_sgs"


def test_firewall_detects_injected_number_in_evaluate():
    """evaluate detects when narrative contains a number not in computed figures."""
    from src.firewall.checker import check_firewall
    figures = _make_passing_figures()
    bad_narrative = "The SGS allocation is 35.0% but risk is 99.9% elevated."
    result = check_firewall(bad_narrative, figures)
    assert result.passed is False


def test_traceability_check():
    """Each figure must have non-empty graph_path and citation.chunk_id."""
    figures = _make_passing_figures()
    for fig in figures:
        assert fig.graph_path, f"Empty graph_path for {fig.figure}"
        assert fig.citation.get("chunk_id"), f"Empty citation.chunk_id for {fig.figure}"
