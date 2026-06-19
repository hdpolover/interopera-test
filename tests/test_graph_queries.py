"""Tests for graph query selectors. Requires Neo4j with 13 positions loaded."""
import os
import pytest
from decimal import Decimal

NEO4J_URI = os.environ.get("NEO4J_TEST_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_TEST_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_TEST_PASSWORD", "password")


@pytest.fixture(scope="module")
def driver():
    try:
        from neo4j import GraphDatabase
        drv = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
        drv.verify_connectivity()
        yield drv
        drv.close()
    except Exception as e:
        pytest.skip(f"Neo4j not available: {e}")


@pytest.fixture(scope="module")
def loaded_graph(driver):
    """Load all 13 positions and stub rules once for the module."""
    import os
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions, load_rules
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
    ids = {r["instrument_id"] for r in results}
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
    from src.graph.queries import list_pending_nodes
    pending = list_pending_nodes(loaded_graph)
    # Guidelines parser produces at least one PENDING_REVIEW chunk (low confidence)
    # All are dicts with at least status key
    for node in pending:
        assert node["status"] == "PENDING_REVIEW"


def test_approve_node_raises_on_empty_actor(loaded_graph):
    from src.graph.queries import approve_node
    with pytest.raises(ValueError, match="actor"):
        approve_node(loaded_graph, "some-node-id", "")


def test_approve_node_raises_on_whitespace_actor(loaded_graph):
    from src.graph.queries import approve_node
    with pytest.raises(ValueError, match="actor"):
        approve_node(loaded_graph, "some-node-id", "   ")


def test_approve_node_flips_status_to_verified(loaded_graph):
    from src.graph.queries import list_pending_nodes, approve_node
    pending = list_pending_nodes(loaded_graph)
    if not pending:
        pytest.skip("No PENDING_REVIEW nodes to test approval")
    node_id = pending[0]["node_id"]
    approve_node(loaded_graph, node_id, "test_reviewer")
    # After approval, should no longer be pending
    remaining = {n["node_id"] for n in list_pending_nodes(loaded_graph)}
    assert node_id not in remaining
