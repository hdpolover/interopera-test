"""Tests for graph query selectors. Requires Neo4j with 13 positions loaded."""
import pytest
from decimal import Decimal


@pytest.fixture(scope="module")
def loaded_graph(driver):
    """Load all 13 positions, stub rules, and risk metrics once for the module."""
    import os
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions, load_rules, load_risk_metrics
    from src.ingestion.holdings_parser import parse_holdings
    from src.ingestion.guidelines_parser import parse_guidelines

    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

    apply_schema(driver)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path = os.path.join(repo_root, "sample_docs", "sample_holdings.csv")
    positions = parse_holdings(csv_path)
    load_positions(driver, positions)
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    load_rules(driver, chunks)
    load_risk_metrics(driver, chunks)
    return driver


def test_positions_in_sgs_asset_class(loaded_graph):
    from src.graph.queries import positions_in_asset_class
    results = positions_in_asset_class(loaded_graph, "Singapore Government Securities")
    ids = [r["instrument_id"] for r in results]
    assert sorted(ids) == ["SGS-01", "SGS-02"]


def test_positions_in_asset_class_sorted(loaded_graph):
    from src.graph.queries import positions_in_asset_class
    results = positions_in_asset_class(loaded_graph, "Singapore Government Securities")
    ids = [r["instrument_id"] for r in results]
    assert ids == sorted(ids)


def test_positions_matching_hy_and_sc(loaded_graph):
    from src.graph.queries import positions_matching
    results = positions_matching(
        loaded_graph,
        {"asset_class_in": ["High Yield Bonds", "Structured Credit"]}
    )
    ids = {r["instrument_id"] for r in results}
    assert ids == {"HY-01", "HY-02", "SC-01"}


def test_positions_matching_excludes_fallen_angels_when_false(loaded_graph):
    from src.graph.queries import positions_matching
    # Non-IG without fallen angels: HY + SC only (no COR-05)
    results = positions_matching(
        loaded_graph,
        {"asset_class_in": ["High Yield Bonds", "Structured Credit"],
         "include_fallen_angels": False}
    )
    ids = {r["instrument_id"] for r in results}
    assert "COR-05" not in ids
    assert ids == {"HY-01", "HY-02", "SC-01"}


def test_positions_matching_includes_fallen_angels_when_true(loaded_graph):
    from src.graph.queries import positions_matching
    # Non-IG with fallen angels: HY + SC + COR-05 (BB, was BBB-)
    # Uses _BELOW_IG_RATINGS explicit set to identify fallen angels
    results = positions_matching(
        loaded_graph,
        {
            "asset_class_in": ["High Yield Bonds", "Structured Credit",
                               "Investment Grade Corporate Bonds"],
            "include_fallen_angels": True,
        }
    )
    ids = {r["instrument_id"] for r in results}
    assert "COR-05" in ids


def test_only_cor05_is_fallen_angel(loaded_graph):
    from src.graph.queries import positions_matching
    # Only COR-05 has downgraded_from set AND BB rating (below IG)
    results = positions_matching(
        loaded_graph,
        {
            "asset_class_in": ["High Yield Bonds", "Structured Credit",
                               "Investment Grade Corporate Bonds"],
            "include_fallen_angels": True,
        }
    )
    {r["instrument_id"] for r in results}
    fallen_angels = {
        r["instrument_id"] for r in results
        if r.get("downgraded_from") and r.get("asset_class") == "Investment Grade Corporate Bonds"
    }
    assert fallen_angels == {"COR-05"}, f"Expected only COR-05 as fallen angel, got {fallen_angels}"


def test_positions_by_issuer_groups_correctly(loaded_graph):
    from src.graph.queries import positions_by_issuer
    groups = positions_by_issuer(loaded_graph, "issuer")
    # Redhill Power and Redhill Transport are separate issuers
    assert "Redhill Power Pte Ltd" in groups
    assert "Redhill Transport Pte Ltd" in groups
    # They should NOT be merged under issuer grouping
    assert "Redhill Holdings" not in groups


def test_positions_by_parent_issuer_merges_gre(loaded_graph):
    from src.graph.queries import positions_by_issuer
    groups = positions_by_issuer(loaded_graph, "parent_issuer")
    assert "Redhill Holdings" in groups
    redhill_ids = {p["instrument_id"] for p in groups["Redhill Holdings"]}
    assert redhill_ids == {"COR-03", "COR-04"}


def test_liquid_positions_returns_govt_and_cash(loaded_graph):
    from src.graph.queries import liquid_positions
    results = liquid_positions(loaded_graph)
    ids = {r["instrument_id"] for r in results}
    # Liquid = SGS + MAS Bills + Cash
    assert "SGS-01" in ids
    assert "SGS-02" in ids
    assert "MAS-01" in ids
    assert "CASH-01" in ids
    # IG Corp bonds are NOT liquid
    assert "COR-01" not in ids


def test_liquid_positions_total_is_47m(loaded_graph):
    from src.graph.queries import liquid_positions
    results = liquid_positions(loaded_graph)
    total = sum(Decimal(r["market_value_sgd"]) for r in results)
    assert total == Decimal("47000000")


def test_all_positions_returns_13(loaded_graph):
    from src.graph.queries import all_positions
    results = all_positions(loaded_graph)
    assert len(results) == 13


def test_all_positions_sorted(loaded_graph):
    from src.graph.queries import all_positions
    results = all_positions(loaded_graph)
    ids = [r["instrument_id"] for r in results]
    assert ids == sorted(ids)


def test_list_pending_nodes(loaded_graph):
    """list_pending_nodes returns all PENDING_REVIEW nodes; every returned node has status=PENDING_REVIEW.

    Note: all stub SourceChunk/Limit nodes produced by guidelines_parser have extraction_confidence
    >= 0.92 (well above the 0.85 threshold), so they are all VERIFIED after load_rules.  To make
    this test meaningful we inject a synthetic Limit node with PENDING_REVIEW status, assert it
    appears in the listing AND that every item returned has the correct status, then clean it up.
    """
    from src.graph.queries import list_pending_nodes

    _SYNTHETIC_REF = "test_pending_ref_list"

    with loaded_graph.session() as session:
        session.run(
            "MERGE (l:Limit {ref: $ref}) SET l.status = 'PENDING_REVIEW', l.rule_type = 'test_type'",
            ref=_SYNTHETIC_REF,
        )

    try:
        pending = list_pending_nodes(loaded_graph)
        # Every node returned must have status PENDING_REVIEW
        for node in pending:
            assert node["status"] == "PENDING_REVIEW"
        # Our injected node must appear
        node_ids = [n["node_id"] for n in pending]
        assert _SYNTHETIC_REF in node_ids, (
            f"Injected PENDING_REVIEW node '{_SYNTHETIC_REF}' not found in listing: {node_ids}"
        )
    finally:
        with loaded_graph.session() as session:
            session.run("MATCH (l:Limit {ref: $ref}) DETACH DELETE l", ref=_SYNTHETIC_REF)


def test_approve_node_raises_on_empty_actor(loaded_graph):
    from src.graph.queries import approve_node
    with pytest.raises(ValueError, match="actor"):
        approve_node(loaded_graph, "some-node-id", "")


def test_approve_node_raises_on_whitespace_actor(loaded_graph):
    from src.graph.queries import approve_node
    with pytest.raises(ValueError, match="actor"):
        approve_node(loaded_graph, "some-node-id", "   ")


def test_breach_action_for_portfolio_duration(loaded_graph):
    """Multi-hop: portfolio_duration -> PM notification within 1h -> Portfolio Manager."""
    from src.graph.queries import breach_action_for_metric
    result = breach_action_for_metric(loaded_graph, "portfolio_duration")
    assert result, "Expected result for portfolio_duration, got empty dict"
    assert result["metric"] == "portfolio_duration"
    assert result["breach_action"] == "PM notification within 1h"
    assert result["owner"] == "Portfolio Manager"
    assert result["monitoring_frequency"] == "Daily"


def test_breach_action_for_portfolio_dv01(loaded_graph):
    from src.graph.queries import breach_action_for_metric
    result = breach_action_for_metric(loaded_graph, "portfolio_dv01")
    assert result["breach_action"] == "Risk Committee alert"
    assert result["owner"] == "Risk Committee"


def test_breach_action_for_unknown_metric_returns_empty(loaded_graph):
    from src.graph.queries import breach_action_for_metric
    result = breach_action_for_metric(loaded_graph, "nonexistent_metric")
    assert result == {}


def test_breach_action_for_all_six_metrics(loaded_graph):
    """All 6 market risk metrics must be queryable via breach_action_for_metric."""
    from src.graph.queries import breach_action_for_metric
    expected_metrics = [
        "portfolio_duration",
        "portfolio_dv01",
        "value_at_risk_95_10d",
        "expected_shortfall_97_5",
        "interest_rate_sensitivity",
        "tracking_error_vs_benchmark",
    ]
    for metric in expected_metrics:
        result = breach_action_for_metric(loaded_graph, metric)
        assert result, f"breach_action_for_metric returned empty for {metric}"
        assert result["breach_action"], f"breach_action missing for {metric}"
        assert result["owner"], f"owner missing for {metric}"


def test_approve_node_flips_status_to_verified(loaded_graph):
    """approve_node must flip a PENDING_REVIEW node to VERIFIED (happy path, end-to-end).

    Injects a synthetic Limit node with PENDING_REVIEW status, calls approve_node,
    then asserts the node no longer appears in list_pending_nodes output.
    """
    from src.graph.queries import list_pending_nodes, approve_node

    _SYNTHETIC_REF = "test_pending_ref_approve"

    with loaded_graph.session() as session:
        session.run(
            "MERGE (l:Limit {ref: $ref}) SET l.status = 'PENDING_REVIEW', l.rule_type = 'test_type'",
            ref=_SYNTHETIC_REF,
        )

    try:
        # Confirm node is pending before approval
        pending_before = {n["node_id"] for n in list_pending_nodes(loaded_graph)}
        assert _SYNTHETIC_REF in pending_before, "Injected node not pending before approval"

        approve_node(loaded_graph, _SYNTHETIC_REF, actor="test_reviewer")

        # After approval the node must NOT appear in pending list
        remaining = {n["node_id"] for n in list_pending_nodes(loaded_graph)}
        assert _SYNTHETIC_REF not in remaining, (
            f"Node '{_SYNTHETIC_REF}' still pending after approve_node call"
        )

        # Verify the approved_by attribute was set
        with loaded_graph.session() as session:
            result = session.run(
                "MATCH (l:Limit {ref: $ref}) RETURN l.status AS status, l.approved_by AS approved_by",
                ref=_SYNTHETIC_REF,
            )
            record = result.single()
            assert record is not None
            assert record["status"] == "VERIFIED"
            assert record["approved_by"] == "test_reviewer"
    finally:
        with loaded_graph.session() as session:
            session.run("MATCH (l:Limit {ref: $ref}) DETACH DELETE l", ref=_SYNTHETIC_REF)


def test_approve_node_label_does_not_approve_different_label(loaded_graph):
    """approve_node with node_label must NOT flip a node of a different label.

    Two nodes share the same chunk_id value: one Limit (PENDING_REVIEW) and one
    SourceChunk (also PENDING_REVIEW).  Approving via node_label='Limit' must
    leave the SourceChunk untouched, proving the label discriminator works.
    """
    from src.graph.queries import approve_node

    _SHARED_ID = "shared_chunk_id_for_label_test"

    with loaded_graph.session() as session:
        session.run(
            "MERGE (l:Limit {chunk_id: $cid}) "
            "SET l.status = 'PENDING_REVIEW', l.rule_type = 'test_label_limit'",
            cid=_SHARED_ID,
        )
        session.run(
            "MERGE (sc:SourceChunk {chunk_id: $cid}) "
            "SET sc.status = 'PENDING_REVIEW'",
            cid=_SHARED_ID,
        )

    try:
        # Approve only the Limit label — SourceChunk must remain PENDING_REVIEW
        approve_node(loaded_graph, _SHARED_ID, actor="label_tester", node_label="Limit")

        with loaded_graph.session() as session:
            limit_rec = session.run(
                "MATCH (l:Limit {chunk_id: $cid}) RETURN l.status AS status",
                cid=_SHARED_ID,
            ).single()
            sc_rec = session.run(
                "MATCH (sc:SourceChunk {chunk_id: $cid}) RETURN sc.status AS status",
                cid=_SHARED_ID,
            ).single()

        assert limit_rec["status"] == "VERIFIED", (
            "Limit node must be VERIFIED after label-targeted approval"
        )
        assert sc_rec["status"] == "PENDING_REVIEW", (
            "SourceChunk must remain PENDING_REVIEW — it shares chunk_id but was NOT targeted"
        )
    finally:
        with loaded_graph.session() as session:
            session.run(
                "MATCH (n) WHERE n.chunk_id = $cid AND (n:Limit OR n:SourceChunk) "
                "DETACH DELETE n",
                cid=_SHARED_ID,
            )


def test_approve_node_unknown_label_raises(loaded_graph):
    """approve_node raises ValueError when node_label is not in _LABEL_KEY_MAP."""
    from src.graph.queries import approve_node
    with pytest.raises(ValueError, match="Unknown node_label"):
        approve_node(loaded_graph, "some-id", actor="tester", node_label="GhostNode")
