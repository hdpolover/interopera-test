"""Tests for graph schema and builder.

Uses a Neo4j driver fixture. Set NEO4J_TEST_URI env var (default: bolt://localhost:7687).
Tests are skipped if Neo4j is not available.
"""
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


@pytest.fixture(autouse=True)
def clean_graph(driver):
    """Wipe test data before each test."""
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    yield


@pytest.fixture
def sample_positions():
    from src.ingestion.holdings_parser import PositionRecord
    return [
        PositionRecord(
            instrument_id="SGS-01",
            instrument_name="SGS 2.5% 2030",
            asset_class="Singapore Government Securities",
            issuer_name="Singapore Government",
            issuer_type="government",
            parent_issuer=None,
            credit_rating="AAA",
            downgraded_from=None,
            market_value_sgd=Decimal("20000000"),
            modified_duration=Decimal("5.0"),
        ),
        PositionRecord(
            instrument_id="COR-03",
            instrument_name="Redhill Power 3.1% 2030",
            asset_class="Investment Grade Corporate Bonds",
            issuer_name="Redhill Power Pte Ltd",
            issuer_type="GRE",
            parent_issuer="Redhill Holdings",
            credit_rating="A",
            downgraded_from=None,
            market_value_sgd=Decimal("7000000"),
            modified_duration=Decimal("4.5"),
        ),
    ]


@pytest.fixture
def sample_chunks():
    from src.ingestion.guidelines_parser import parse_guidelines
    return parse_guidelines(pdf_path=None, llm_client=None)


def test_apply_schema_succeeds(driver):
    from src.graph.schema import apply_schema
    apply_schema(driver)  # should not raise


def test_load_positions_creates_position_nodes(driver, sample_positions):
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions
    apply_schema(driver)
    load_positions(driver, sample_positions)
    with driver.session() as session:
        result = session.run("MATCH (p:Position) RETURN count(p) AS cnt")
        count = result.single()["cnt"]
    assert count == 2


def test_load_positions_creates_asset_class_edges(driver, sample_positions):
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions
    apply_schema(driver)
    load_positions(driver, sample_positions)
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Position)-[:IN_ASSET_CLASS]->(a:AssetClass) RETURN count(p) AS cnt"
        )
        count = result.single()["cnt"]
    assert count == 2


def test_load_positions_creates_parent_issuer_for_gre(driver, sample_positions):
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions
    apply_schema(driver)
    load_positions(driver, sample_positions)
    with driver.session() as session:
        result = session.run(
            "MATCH (i:Issuer)-[:ROLLS_UP_TO]->(pi:ParentIssuer {name: 'Redhill Holdings'}) "
            "RETURN count(i) AS cnt"
        )
        count = result.single()["cnt"]
    assert count == 1


def test_load_positions_status_is_verified(driver, sample_positions):
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions
    apply_schema(driver)
    load_positions(driver, sample_positions)
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Position) WHERE p.status <> 'VERIFIED' RETURN count(p) AS cnt"
        )
        count = result.single()["cnt"]
    assert count == 0, "All Position nodes should be VERIFIED"


def test_load_rules_creates_source_chunks(driver, sample_chunks):
    from src.graph.schema import apply_schema
    from src.graph.builder import load_rules
    apply_schema(driver)
    load_rules(driver, sample_chunks)
    with driver.session() as session:
        result = session.run("MATCH (sc:SourceChunk) RETURN count(sc) AS cnt")
        count = result.single()["cnt"]
    assert count == len(sample_chunks)


def test_load_rules_chunk_id_on_source_chunk(driver, sample_chunks):
    from src.graph.schema import apply_schema
    from src.graph.builder import load_rules
    apply_schema(driver)
    load_rules(driver, sample_chunks)
    with driver.session() as session:
        result = session.run(
            "MATCH (sc:SourceChunk) WHERE sc.chunk_id IS NOT NULL RETURN count(sc) AS cnt"
        )
        count = result.single()["cnt"]
    assert count == len(sample_chunks)


def test_load_rules_low_confidence_is_pending(driver):
    from src.graph.schema import apply_schema
    from src.graph.builder import load_rules
    from src.ingestion.guidelines_parser import RuleChunk, chunk_id_from_text
    apply_schema(driver)
    passage = "Low confidence rule passage for testing."
    low_conf_chunk = RuleChunk(
        chunk_id=chunk_id_from_text(passage),
        source_doc="test.pdf",
        page=1,
        passage=passage,
        passage_summary="Low confidence test",
        extracted_fields={"rule_type": "allocation_limit"},
        extraction_confidence=0.50,
    )
    load_rules(driver, [low_conf_chunk])
    with driver.session() as session:
        result = session.run(
            "MATCH (sc:SourceChunk {chunk_id: $cid}) RETURN sc.status AS status",
            cid=low_conf_chunk.chunk_id,
        )
        record = result.single()
    assert record["status"] == "PENDING_REVIEW"


def test_load_rules_high_confidence_is_verified(driver, sample_chunks):
    from src.graph.schema import apply_schema
    from src.graph.builder import load_rules
    apply_schema(driver)
    high_conf = [c for c in sample_chunks if c.extraction_confidence >= 0.85]
    load_rules(driver, high_conf)
    with driver.session() as session:
        result = session.run(
            "MATCH (sc:SourceChunk) WHERE sc.status = 'VERIFIED' RETURN count(sc) AS cnt"
        )
        count = result.single()["cnt"]
    assert count == len(high_conf)
