"""Verify gate: engine must refuse to compute figures from PENDING_REVIEW nodes.

TDD requirement (Task 10):
- A figure that depends on a PENDING_REVIEW Limit node must compute as Figure(status="ERROR").
- approve_node flips the node to VERIFIED and the engine then computes normally.
- A figure with no reachable SourceChunk (missing DERIVED_FROM edge) must also be ERROR (I-2).
"""
from __future__ import annotations

import os
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def graph_with_pending(driver):
    """Load 13 positions + rules, then mark the 'allocation_limit' Limit node PENDING_REVIEW.

    The real rule_type for allocation_sgs (and all allocation figures) is 'allocation_limit',
    as set by guidelines_parser._STUB_PASSAGES and mapped in engine._FIGURE_RULE_TYPE.
    Marking that Limit node PENDING_REVIEW causes _check_limit_node_pending to return True
    for allocation_sgs, so the engine returns Figure(status="ERROR") for that figure.
    """
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions, load_rules
    from src.ingestion.holdings_parser import parse_holdings
    from src.ingestion.guidelines_parser import parse_guidelines

    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

    apply_schema(driver)
    csv_path = os.path.join(REPO_ROOT, "sample_docs", "sample_holdings.csv")
    positions = parse_holdings(csv_path)
    load_positions(driver, positions)
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    load_rules(driver, chunks)

    # Mark the allocation_limit Limit node as PENDING_REVIEW to simulate a rule/limit
    # that has not yet been verified by a human reviewer.
    # rule_type 'allocation_limit' is the real value from guidelines_parser._STUB_PASSAGES.
    with driver.session() as session:
        session.run(
            "MATCH (l:Limit {rule_type: 'allocation_limit'}) SET l.status = 'PENDING_REVIEW'"
        )
    return driver


def test_pending_review_node_listed(graph_with_pending):
    """list_pending_nodes must return at least one PENDING_REVIEW node (the marked Limit).

    Note: list_pending_nodes uses COALESCE(n.instrument_id, n.chunk_id, n.ref, n.name, '')
    to derive node_id.  For Limit nodes the builder also stores chunk_id as a property,
    so COALESCE picks chunk_id (the 8-char content hash) before ref.  We therefore check
    labels == ['Limit'] rather than matching on the ref string.
    """
    from src.graph.queries import list_pending_nodes
    pending = list_pending_nodes(graph_with_pending)
    # There must be at least one pending node (the allocation_limit Limit we marked above)
    assert len(pending) >= 1, "Expected at least one PENDING_REVIEW node after fixture setup"
    # Every returned node must carry status == PENDING_REVIEW
    for node in pending:
        assert node["status"] == "PENDING_REVIEW"
    # At least one of the pending nodes must be a Limit node
    limit_pending = [n for n in pending if "Limit" in n.get("labels", [])]
    assert len(limit_pending) >= 1, (
        f"Expected at least one pending Limit node, got: {pending}"
    )


def test_engine_returns_error_for_pending_figure(graph_with_pending):
    """The engine must return Figure(status="ERROR") for allocation_sgs when its Limit node
    is PENDING_REVIEW — untrusted/unverified data must never become a numeric value."""
    from src.compute.config_loader import load_config
    from src.compute.engine import ComputeEngine
    from src.compute.registry import FIGURE_REGISTRY

    config = load_config(
        os.path.join(REPO_ROOT, "config", "base.yaml"),
        os.path.join(REPO_ROOT, "config", "firm_a.yaml"),
    )
    engine = ComputeEngine(graph_with_pending, config)
    # allocation_sgs's anchor Limit node (rule_type='allocation_limit') is PENDING_REVIEW
    sgs_spec = next(s for s in FIGURE_REGISTRY if s.id == "allocation_sgs")
    figure = engine.compute_figure(sgs_spec)
    assert figure.status == "ERROR", (
        f"Expected ERROR for allocation_sgs with pending Limit node, got: {figure.status}"
    )
    assert figure.value == "ERROR"


def test_approve_node_flips_to_verified(graph_with_pending):
    """approve_node must flip the PENDING_REVIEW Limit node to VERIFIED (happy-path gate).

    Uses the node_id returned by list_pending_nodes — which for Limit nodes is the
    chunk_id (8-char hash) because COALESCE picks chunk_id before ref.  approve_node
    matches on COALESCE(...) so the same identifier is used for both listing and approval.
    """
    from src.graph.queries import approve_node, list_pending_nodes

    # Find any pending Limit node (our fixture marked allocation_limit Limit nodes)
    pending_before = list_pending_nodes(graph_with_pending)
    limit_nodes = [n for n in pending_before if "Limit" in n.get("labels", [])]
    assert len(limit_nodes) >= 1, (
        f"Expected at least one pending Limit node, got: {pending_before}"
    )
    limit_node_id = limit_nodes[0]["node_id"]

    approve_node(graph_with_pending, limit_node_id, actor="test_human")

    pending_after = list_pending_nodes(graph_with_pending)
    still_pending = [n for n in pending_after if n["node_id"] == limit_node_id]
    assert len(still_pending) == 0, (
        f"Node '{limit_node_id}' still pending after approve_node"
    )

    # Confirm the node is now VERIFIED and has approved_by set
    # We match on chunk_id since that is the node_id used by COALESCE
    with graph_with_pending.session() as session:
        result = session.run(
            """
            MATCH (l:Limit {chunk_id: $cid})
            RETURN l.status AS status, l.approved_by AS approved_by
            """,
            cid=limit_node_id,
        )
        record = result.single()
        assert record is not None, f"Could not find Limit node with chunk_id='{limit_node_id}'"
        assert record["status"] == "VERIFIED"
        assert record["approved_by"] == "test_human"


def test_engine_computes_after_approval(graph_with_pending):
    """After approval the engine must compute allocation_sgs normally (not ERROR)."""
    from src.compute.config_loader import load_config
    from src.compute.engine import ComputeEngine
    from src.compute.registry import FIGURE_REGISTRY

    # Limit node is now VERIFIED (set by test_approve_node_flips_to_verified above)
    config = load_config(
        os.path.join(REPO_ROOT, "config", "base.yaml"),
        os.path.join(REPO_ROOT, "config", "firm_a.yaml"),
    )
    engine = ComputeEngine(graph_with_pending, config)
    sgs_spec = next(s for s in FIGURE_REGISTRY if s.id == "allocation_sgs")
    figure = engine.compute_figure(sgs_spec)
    assert figure.status != "ERROR", (
        f"Expected non-ERROR for allocation_sgs after approval, got: {figure.status}"
    )
    assert figure.value == "35.0%"


def test_approve_node_requires_actor():
    """approve_node must raise ValueError when actor is empty (audit trail requirement)."""
    from src.graph.queries import approve_node
    with pytest.raises(ValueError):
        approve_node(None, "some-node-id", actor="")


# ---------------------------------------------------------------------------
# I-2: Missing-citation → ERROR
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def graph_with_broken_citation(driver):
    """Load a fresh graph, then delete the DERIVED_FROM edge for the dv01_limit Limit node.

    This simulates a rule node whose SourceChunk link is missing or corrupted.
    The engine must detect this and return Figure(status="ERROR") for portfolio_dv01.
    """
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions, load_rules
    from src.ingestion.holdings_parser import parse_holdings
    from src.ingestion.guidelines_parser import parse_guidelines

    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

    apply_schema(driver)
    csv_path = os.path.join(REPO_ROOT, "sample_docs", "sample_holdings.csv")
    positions = parse_holdings(csv_path)
    load_positions(driver, positions)
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    load_rules(driver, chunks)

    # Delete the DERIVED_FROM edge from the dv01_limit Limit node so that
    # _get_citation cannot trace portfolio_dv01 to any SourceChunk.
    with driver.session() as session:
        session.run(
            "MATCH (l:Limit {rule_type: 'dv01_limit'})-[r:DERIVED_FROM]->(:SourceChunk) DELETE r"
        )
    return driver


def test_missing_citation_returns_error(graph_with_broken_citation):
    """A figure with no reachable SourceChunk (missing DERIVED_FROM edge) must return
    Figure(status="ERROR") — unresolvable citation must never become a numeric value."""
    from src.compute.config_loader import load_config
    from src.compute.engine import ComputeEngine
    from src.compute.registry import FIGURE_REGISTRY

    config = load_config(
        os.path.join(REPO_ROOT, "config", "base.yaml"),
        os.path.join(REPO_ROOT, "config", "firm_a.yaml"),
    )
    engine = ComputeEngine(graph_with_broken_citation, config)
    dv01_spec = next(s for s in FIGURE_REGISTRY if s.id == "portfolio_dv01")
    figure = engine.compute_figure(dv01_spec)
    assert figure.status == "ERROR", (
        f"Expected ERROR for portfolio_dv01 with broken DERIVED_FROM edge, got: {figure.status}"
    )
    assert figure.value == "ERROR"
    # citation field must still be a dict (not None) — consumers expect a dict
    assert isinstance(figure.citation, dict)


def test_other_figures_unaffected_by_broken_dv01_citation(graph_with_broken_citation):
    """Removing the DERIVED_FROM edge for dv01_limit must NOT break other figures
    that use different rule_types (their SourceChunks are still reachable)."""
    from src.compute.config_loader import load_config
    from src.compute.engine import ComputeEngine
    from src.compute.registry import FIGURE_REGISTRY

    config = load_config(
        os.path.join(REPO_ROOT, "config", "base.yaml"),
        os.path.join(REPO_ROOT, "config", "firm_a.yaml"),
    )
    engine = ComputeEngine(graph_with_broken_citation, config)
    # allocation_sgs uses allocation_limit rule_type — should compute normally
    sgs_spec = next(s for s in FIGURE_REGISTRY if s.id == "allocation_sgs")
    figure = engine.compute_figure(sgs_spec)
    assert figure.status != "ERROR", (
        "allocation_sgs should not be ERROR (its rule_type is allocation_limit, not dv01_limit)"
    )
    assert figure.value == "35.0%"
