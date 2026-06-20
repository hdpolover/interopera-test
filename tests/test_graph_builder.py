"""Tests for graph schema and builder.

Uses a Neo4j driver fixture. Set NEO4J_TEST_URI env var (default: bolt://localhost:7687).
Tests are skipped if Neo4j is not available.
"""
import pytest
from decimal import Decimal


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


# --- Review round 1 tests (I-1..I-4, M-1) ---


def test_provenance_on_nodes_and_edges(driver, sample_positions):
    """I-1: Position nodes and IN_ASSET_CLASS edges must all carry the five provenance props."""
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions
    apply_schema(driver)
    load_positions(driver, sample_positions)
    with driver.session() as session:
        # Check a Position node has all five provenance props non-null
        result = session.run(
            """
            MATCH (p:Position {instrument_id: 'SGS-01'})
            RETURN p.source_doc AS source_doc,
                   p.page AS page,
                   p.chunk_id AS chunk_id,
                   p.ingested_at AS ingested_at,
                   p.extraction_confidence AS extraction_confidence
            """
        )
        record = result.single()
    assert record["source_doc"] is not None, "Position.source_doc must be set"
    assert record["page"] is not None, "Position.page must be set"
    assert record["chunk_id"] is not None, "Position.chunk_id must be set"
    assert record["ingested_at"] is not None, "Position.ingested_at must be set"
    assert record["extraction_confidence"] is not None, "Position.extraction_confidence must be set"

    with driver.session() as session:
        # IN_ASSET_CLASS edges must all have provenance — zero with nulls means all are set
        result = session.run(
            """
            MATCH ()-[r:IN_ASSET_CLASS]->()
            WHERE r.source_doc IS NULL OR r.ingested_at IS NULL
            RETURN count(r) AS bad
            """
        )
        bad = result.single()["bad"]
    assert bad == 0, f"Found {bad} IN_ASSET_CLASS edges missing provenance props"


def test_asset_class_slug_values(driver, sample_positions):
    """I-2: AssetClass nodes must carry correct URL-safe slugs."""
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions
    from src.ingestion.holdings_parser import PositionRecord
    from decimal import Decimal

    apply_schema(driver)
    # Load positions that include High Yield Bonds and Structured Credit
    extra_positions = [
        PositionRecord(
            instrument_id="HY-01",
            instrument_name="APAC Yield 5.5% 2027",
            asset_class="High Yield Bonds",
            issuer_name="Garuda Energy Tbk",
            issuer_type="corporate",
            parent_issuer=None,
            credit_rating="BB",
            downgraded_from=None,
            market_value_sgd=Decimal("5000000"),
            modified_duration=Decimal("3.0"),
        ),
        PositionRecord(
            instrument_id="SC-01",
            instrument_name="AAA ABS Series 2024-1",
            asset_class="Structured Credit",
            issuer_name="Harbour ABS Trust",
            issuer_type="spv",
            parent_issuer=None,
            credit_rating="AAA",
            downgraded_from=None,
            market_value_sgd=Decimal("6000000"),
            modified_duration=Decimal("2.5"),
        ),
    ]
    load_positions(driver, extra_positions)

    with driver.session() as session:
        result = session.run(
            "MATCH (a:AssetClass {name: 'High Yield Bonds'}) RETURN a.slug AS slug"
        )
        hy_slug = result.single()["slug"]

        result = session.run(
            "MATCH (a:AssetClass {name: 'Structured Credit'}) RETURN a.slug AS slug"
        )
        sc_slug = result.single()["slug"]

    assert hy_slug == "high_yield", f"Expected 'high_yield', got '{hy_slug}'"
    assert sc_slug == "structured_credit", f"Expected 'structured_credit', got '{sc_slug}'"


def test_contributes_to_edges_for_non_ig(driver):
    """I-3 (CRITICAL): Both High Yield Bonds and Structured Credit must have CONTRIBUTES_TO->non_ig."""
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions
    from src.ingestion.holdings_parser import PositionRecord
    from decimal import Decimal

    apply_schema(driver)
    positions = [
        PositionRecord(
            instrument_id="HY-01",
            instrument_name="APAC Yield 5.5% 2027",
            asset_class="High Yield Bonds",
            issuer_name="Garuda Energy Tbk",
            issuer_type="corporate",
            parent_issuer=None,
            credit_rating="BB",
            downgraded_from=None,
            market_value_sgd=Decimal("5000000"),
            modified_duration=Decimal("3.0"),
        ),
        PositionRecord(
            instrument_id="SC-01",
            instrument_name="AAA ABS Series 2024-1",
            asset_class="Structured Credit",
            issuer_name="Harbour ABS Trust",
            issuer_type="spv",
            parent_issuer=None,
            credit_rating="AAA",
            downgraded_from=None,
            market_value_sgd=Decimal("6000000"),
            modified_duration=Decimal("2.5"),
        ),
    ]
    load_positions(driver, positions)

    with driver.session() as session:
        result = session.run(
            """
            MATCH (a:AssetClass)-[:CONTRIBUTES_TO]->(agg:Aggregate {name:'non_ig'})
            RETURN a.slug AS slug ORDER BY slug
            """
        )
        slugs = [record["slug"] for record in result]

    assert slugs == ["high_yield", "structured_credit"], (
        f"Expected ['high_yield', 'structured_credit'], got {slugs}"
    )


def test_distinct_source_chunk_per_rule_area(driver, sample_chunks):
    """I-4: Two different rule-area Limits must reach SourceChunks with distinct chunk_ids."""
    from src.graph.schema import apply_schema
    from src.graph.builder import load_rules
    apply_schema(driver)
    load_rules(driver, sample_chunks)

    with driver.session() as session:
        # Fetch chunk_id for allocation_limit Limit
        result = session.run(
            """
            MATCH (l:Limit {rule_type: 'allocation_limit'})-[:DERIVED_FROM]->(sc:SourceChunk)
            RETURN sc.chunk_id AS chunk_id
            """
        )
        alloc_record = result.single()

        # Fetch chunk_id for liquidity_requirement Limit
        result = session.run(
            """
            MATCH (l:Limit {rule_type: 'liquidity_requirement'})-[:DERIVED_FROM]->(sc:SourceChunk)
            RETURN sc.chunk_id AS chunk_id
            """
        )
        liquid_record = result.single()

    assert alloc_record is not None, "allocation_limit Limit -> SourceChunk not found"
    assert liquid_record is not None, "liquidity_requirement Limit -> SourceChunk not found"
    assert alloc_record["chunk_id"] != liquid_record["chunk_id"], (
        "allocation_limit and liquidity_requirement must have DIFFERENT chunk_ids, "
        f"got both = '{alloc_record['chunk_id']}'"
    )


def test_structural_node_status_is_verified(driver, sample_positions):
    """M-1: AssetClass (and other structural nodes) must have status='VERIFIED'."""
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions
    apply_schema(driver)
    load_positions(driver, sample_positions)

    with driver.session() as session:
        result = session.run(
            "MATCH (a:AssetClass) WHERE a.status <> 'VERIFIED' OR a.status IS NULL "
            "RETURN count(a) AS bad"
        )
        bad = result.single()["bad"]

    assert bad == 0, f"Found {bad} AssetClass nodes without status='VERIFIED'"


# --- RiskMetric / Threshold / BreachAction / Owner node tests ---


@pytest.fixture
def risk_metric_graph(driver, sample_chunks):
    """Load schema, rules, and risk metrics for the Phase 2 entity tests."""
    from src.graph.schema import apply_schema
    from src.graph.builder import load_rules, load_risk_metrics
    apply_schema(driver)
    load_rules(driver, sample_chunks)
    load_risk_metrics(driver, sample_chunks)
    return driver


def test_load_risk_metrics_creates_six_risk_metric_nodes(risk_metric_graph):
    with risk_metric_graph.session() as session:
        result = session.run("MATCH (rm:RiskMetric) RETURN count(rm) AS cnt")
        count = result.single()["cnt"]
    assert count == 6, f"Expected 6 RiskMetric nodes, got {count}"


def test_load_risk_metrics_creates_threshold_per_metric(risk_metric_graph):
    with risk_metric_graph.session() as session:
        result = session.run(
            "MATCH (rm:RiskMetric)-[:HAS_THRESHOLD]->(t:Threshold) RETURN count(rm) AS cnt"
        )
        count = result.single()["cnt"]
    assert count == 6, f"Expected 6 HAS_THRESHOLD edges, got {count}"


def test_load_risk_metrics_creates_breach_action_per_metric(risk_metric_graph):
    with risk_metric_graph.session() as session:
        result = session.run(
            "MATCH (rm:RiskMetric)-[:HAS_BREACH_ACTION]->(ba:BreachAction) RETURN count(rm) AS cnt"
        )
        count = result.single()["cnt"]
    assert count == 6, f"Expected 6 HAS_BREACH_ACTION edges, got {count}"


def test_load_risk_metrics_breach_action_notifies_owner(risk_metric_graph):
    with risk_metric_graph.session() as session:
        result = session.run(
            "MATCH (ba:BreachAction)-[:NOTIFIES]->(o:Owner) RETURN count(ba) AS cnt"
        )
        count = result.single()["cnt"]
    assert count == 6, f"Expected 6 NOTIFIES edges, got {count}"


def test_load_risk_metrics_portfolio_duration_multihop(risk_metric_graph):
    """The brief's example query: breach action + owner for portfolio_duration via graph traversal."""
    with risk_metric_graph.session() as session:
        result = session.run(
            """
            MATCH (rm:RiskMetric {metric: 'portfolio_duration'})
                  -[:HAS_BREACH_ACTION]->(ba:BreachAction)
                  -[:NOTIFIES]->(o:Owner)
            RETURN rm.limit AS limit, ba.action AS breach_action, o.name AS owner
            """
        )
        record = result.single()
    assert record is not None, "Multi-hop query for portfolio_duration returned no result"
    assert record["limit"] == "2.0-6.5 years"
    assert record["breach_action"] == "PM notification within 1h"
    assert record["owner"] == "Portfolio Manager"


def test_load_risk_metrics_risk_metric_derived_from_source_chunk(risk_metric_graph):
    """Every RiskMetric must be traceable to a SourceChunk via DERIVED_FROM."""
    with risk_metric_graph.session() as session:
        result = session.run(
            """
            MATCH (rm:RiskMetric)-[:DERIVED_FROM]->(sc:SourceChunk)
            RETURN count(rm) AS cnt
            """
        )
        count = result.single()["cnt"]
    assert count == 6, f"Expected 6 RiskMetric->SourceChunk DERIVED_FROM edges, got {count}"


def test_load_risk_metrics_provenance_on_risk_metric_node(risk_metric_graph):
    """RiskMetric nodes must carry all five provenance properties."""
    with risk_metric_graph.session() as session:
        result = session.run(
            """
            MATCH (rm:RiskMetric {metric: 'portfolio_dv01'})
            RETURN rm.source_doc AS source_doc, rm.page AS page,
                   rm.chunk_id AS chunk_id, rm.ingested_at AS ingested_at,
                   rm.extraction_confidence AS extraction_confidence
            """
        )
        record = result.single()
    assert record is not None
    assert record["source_doc"] is not None
    assert record["page"] is not None
    assert record["chunk_id"] is not None
    assert record["ingested_at"] is not None
    assert record["extraction_confidence"] is not None


def test_load_risk_metrics_idempotent(driver, sample_chunks):
    """Calling load_risk_metrics twice must not double-create nodes (MERGE is idempotent)."""
    from src.graph.schema import apply_schema
    from src.graph.builder import load_rules, load_risk_metrics
    apply_schema(driver)
    load_rules(driver, sample_chunks)
    load_risk_metrics(driver, sample_chunks)
    load_risk_metrics(driver, sample_chunks)
    with driver.session() as session:
        result = session.run("MATCH (rm:RiskMetric) RETURN count(rm) AS cnt")
        count = result.single()["cnt"]
    assert count == 6, f"Idempotency broken: expected 6 RiskMetric nodes, got {count}"


# ---------------------------------------------------------------------------
# Fix 3: Unknown asset class raises ValueError
# ---------------------------------------------------------------------------


def test_load_positions_raises_for_unknown_asset_class(driver):
    """load_positions must raise ValueError for an unrecognised asset_class.

    An unknown class cannot be assigned a slug and would violate the slug
    uniqueness constraint if the fallback were allowed to proceed.
    """
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions
    from src.ingestion.holdings_parser import PositionRecord
    from decimal import Decimal
    import pytest

    apply_schema(driver)
    bad_position = PositionRecord(
        instrument_id="BAD-01",
        instrument_name="Unknown Class Bond",
        asset_class="Crypto Assets",  # not in ASSET_CLASS_SLUG
        issuer_name="Some Corp",
        issuer_type="corporate",
        parent_issuer=None,
        credit_rating="BB",
        downgraded_from=None,
        market_value_sgd=Decimal("1000000"),
        modified_duration=Decimal("2.0"),
    )
    with pytest.raises(ValueError, match="Unknown asset_class"):
        load_positions(driver, [bad_position])


# ---------------------------------------------------------------------------
# Fix 4: GRE without parent_issuer emits a logging.warning
# ---------------------------------------------------------------------------


def test_gre_without_parent_issuer_emits_warning(driver, caplog):
    """load_positions emits a WARNING when a GRE issuer has no parent_issuer."""
    import logging
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions
    from src.ingestion.holdings_parser import PositionRecord
    from decimal import Decimal

    apply_schema(driver)
    gre_no_parent = PositionRecord(
        instrument_id="GRE-NO-PARENT",
        instrument_name="Orphan GRE Bond",
        asset_class="Investment Grade Corporate Bonds",
        issuer_name="Orphan GRE Corp",
        issuer_type="GRE",
        parent_issuer=None,  # deliberately absent
        credit_rating="A",
        downgraded_from=None,
        market_value_sgd=Decimal("5000000"),
        modified_duration=Decimal("3.0"),
    )
    with caplog.at_level(logging.WARNING, logger="src.graph.builder"):
        load_positions(driver, [gre_no_parent])

    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Orphan GRE Corp" in m or "GRE-NO-PARENT" in m for m in warning_messages), (
        f"Expected a warning mentioning the issuer or instrument, got: {warning_messages}"
    )


# ---------------------------------------------------------------------------
# Fix 2: load_risk_metrics warns when SourceChunk is missing
# ---------------------------------------------------------------------------


def test_load_risk_metrics_warns_when_source_chunk_missing(driver, sample_chunks, caplog):
    """load_risk_metrics emits a WARNING for each metric when SourceChunk is absent.

    Calling load_risk_metrics before load_rules means no SourceChunk nodes exist.
    The DERIVED_FROM edge cannot be created; a warning must be emitted instead
    of silently skipping.
    """
    import logging
    from src.graph.schema import apply_schema
    from src.graph.builder import load_risk_metrics

    apply_schema(driver)
    # Deliberately omit load_rules so no SourceChunk nodes exist
    with caplog.at_level(logging.WARNING, logger="src.graph.builder"):
        load_risk_metrics(driver, sample_chunks)

    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_messages) >= 1, (
        "Expected at least one warning when SourceChunk is missing before load_risk_metrics"
    )
    assert any("SourceChunk" in m or "DERIVED_FROM" in m for m in warning_messages), (
        f"Warning did not mention SourceChunk or DERIVED_FROM: {warning_messages}"
    )


# ---------------------------------------------------------------------------
# Fix 5: ingested_at parameter pins timestamp across all three loaders
# ---------------------------------------------------------------------------


def test_load_positions_accepts_external_ingested_at(driver, sample_positions):
    """load_positions stores the caller-supplied ingested_at on Position nodes."""
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions

    apply_schema(driver)
    fixed_ts = "2025-01-01T00:00:00+00:00"
    load_positions(driver, sample_positions, ingested_at=fixed_ts)

    with driver.session() as session:
        result = session.run(
            "MATCH (p:Position) RETURN p.ingested_at AS ts ORDER BY p.instrument_id"
        )
        timestamps = [record["ts"] for record in result]

    assert all(ts == fixed_ts for ts in timestamps), (
        f"All Position nodes must carry the supplied ingested_at; got: {timestamps}"
    )


def test_threshold_key_constraint_present(driver):
    from src.graph.schema import apply_schema
    apply_schema(driver)
    with driver.session() as session:
        names = [r["name"] for r in session.run("SHOW CONSTRAINTS YIELD name RETURN name")]
    assert any("threshold" in (n or "").lower() for n in names)


def test_single_ingested_at_consistent_across_loaders(driver, sample_positions, sample_chunks):
    """When all three loaders receive the same ingested_at, every node carries that value.

    This proves that a caller can pin a single timestamp across the whole ingest run
    so audit queries can group all nodes created in one run by ingested_at.
    """
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions, load_rules, load_risk_metrics

    apply_schema(driver)
    fixed_ts = "2025-06-01T12:00:00+00:00"
    load_positions(driver, sample_positions, ingested_at=fixed_ts)
    load_rules(driver, sample_chunks, ingested_at=fixed_ts)
    load_risk_metrics(driver, sample_chunks, ingested_at=fixed_ts)

    with driver.session() as session:
        # Sample one Position, one SourceChunk, one RiskMetric
        pos_ts = session.run(
            "MATCH (p:Position) RETURN p.ingested_at AS ts LIMIT 1"
        ).single()["ts"]
        sc_ts = session.run(
            "MATCH (sc:SourceChunk) RETURN sc.ingested_at AS ts LIMIT 1"
        ).single()["ts"]
        rm_ts = session.run(
            "MATCH (rm:RiskMetric) RETURN rm.ingested_at AS ts LIMIT 1"
        ).single()["ts"]

    assert pos_ts == fixed_ts, f"Position ingested_at mismatch: {pos_ts!r}"
    assert sc_ts == fixed_ts, f"SourceChunk ingested_at mismatch: {sc_ts!r}"
    assert rm_ts == fixed_ts, f"RiskMetric ingested_at mismatch: {rm_ts!r}"
