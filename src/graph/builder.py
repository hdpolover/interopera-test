"""Build the Neo4j compliance knowledge graph from ingested records."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.ingestion.holdings_parser import PositionRecord
    from src.ingestion.guidelines_parser import RuleChunk

_CONFIDENCE_THRESHOLD = 0.85

# Maps each AssetClass display name to its URL-safe slug used in graph_path serialization.
# Positions still match on the full `asset_class` string; the slug is an extra property
# on the AssetClass node so the engine can read it back without string munging.
_ASSET_CLASS_SLUG: dict[str, str] = {
    "Singapore Government Securities": "sgs",
    "MAS Bills": "mas_bills",
    "Investment Grade Corporate Bonds": "ig_corp",
    "High Yield Bonds": "high_yield",
    "Foreign Currency Bonds": "fx_bonds",
    "Structured Credit": "structured_credit",
    "Cash & Cash Equivalents": "cash",
}

# Asset classes that contribute to the non_ig aggregate bucket.
_NON_IG_ASSET_CLASSES: frozenset[str] = frozenset({"High Yield Bonds", "Structured Credit"})


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def load_positions(driver: Any, positions: list["PositionRecord"]) -> None:
    """Create Position, AssetClass, Issuer, ParentIssuer nodes and edges.

    All nodes carry provenance props: source_doc, page, chunk_id, ingested_at,
    extraction_confidence.  Idempotent via MERGE.

    Structural nodes (AssetClass, Issuer, ParentIssuer, Aggregate) are always
    status='VERIFIED' because they are deterministically derived from authoritative
    holdings CSV data — no confidence-gating is needed (unlike LLM-extracted Limits).
    """
    ingested_at = _now_iso()

    with driver.session() as session:
        for pos in positions:
            # Merge Position node with provenance
            session.run(
                """
                MERGE (p:Position {instrument_id: $instrument_id})
                SET p.instrument_name        = $instrument_name,
                    p.asset_class            = $asset_class,
                    p.issuer_name            = $issuer_name,
                    p.issuer_type            = $issuer_type,
                    p.credit_rating          = $credit_rating,
                    p.downgraded_from        = $downgraded_from,
                    p.market_value_sgd       = $market_value_sgd,
                    p.modified_duration      = $modified_duration,
                    p.status                 = 'VERIFIED',
                    p.extraction_confidence  = 1.0,
                    p.source_doc             = 'holdings_csv',
                    p.page                   = 0,
                    p.chunk_id               = $instrument_id,
                    p.ingested_at            = $ingested_at
                """,
                instrument_id=pos.instrument_id,
                instrument_name=pos.instrument_name,
                asset_class=pos.asset_class,
                issuer_name=pos.issuer_name,
                issuer_type=pos.issuer_type,
                credit_rating=pos.credit_rating,
                downgraded_from=pos.downgraded_from,
                market_value_sgd=str(pos.market_value_sgd),
                modified_duration=str(pos.modified_duration),
                ingested_at=ingested_at,
            )

            # Merge AssetClass node with slug + provenance; create IN_ASSET_CLASS edge
            session.run(
                """
                MERGE (a:AssetClass {name: $asset_class})
                SET a.slug                  = $slug,
                    a.source_doc            = 'holdings_csv',
                    a.page                  = 0,
                    a.chunk_id              = $asset_class,
                    a.ingested_at           = $ingested_at,
                    a.extraction_confidence = 1.0,
                    a.status                = 'VERIFIED'
                WITH a
                MATCH (p:Position {instrument_id: $instrument_id})
                MERGE (p)-[r:IN_ASSET_CLASS]->(a)
                SET r.source_doc            = 'holdings_csv',
                    r.page                  = 0,
                    r.chunk_id              = $instrument_id,
                    r.ingested_at           = $ingested_at,
                    r.extraction_confidence = 1.0
                """,
                asset_class=pos.asset_class,
                slug=_ASSET_CLASS_SLUG.get(pos.asset_class, pos.asset_class.lower().replace(" ", "_")),
                instrument_id=pos.instrument_id,
                ingested_at=ingested_at,
            )

            # For non-IG asset classes: ensure Aggregate {name:'non_ig'} exists and wire CONTRIBUTES_TO
            if pos.asset_class in _NON_IG_ASSET_CLASSES:
                session.run(
                    """
                    MERGE (agg:Aggregate {name: 'non_ig'})
                    SET agg.source_doc            = 'holdings_csv',
                        agg.page                  = 0,
                        agg.chunk_id              = 'non_ig',
                        agg.ingested_at           = $ingested_at,
                        agg.extraction_confidence = 1.0,
                        agg.status                = 'VERIFIED'
                    WITH agg
                    MATCH (a:AssetClass {name: $asset_class})
                    MERGE (a)-[r:CONTRIBUTES_TO]->(agg)
                    SET r.source_doc            = 'holdings_csv',
                        r.page                  = 0,
                        r.chunk_id              = $asset_class,
                        r.ingested_at           = $ingested_at,
                        r.extraction_confidence = 1.0
                    """,
                    asset_class=pos.asset_class,
                    ingested_at=ingested_at,
                )

            # Merge Issuer node with provenance; create ISSUED_BY edge
            session.run(
                """
                MERGE (i:Issuer {name: $issuer_name})
                SET i.issuer_type            = $issuer_type,
                    i.source_doc             = 'holdings_csv',
                    i.page                   = 0,
                    i.chunk_id               = $issuer_name,
                    i.ingested_at            = $ingested_at,
                    i.extraction_confidence  = 1.0,
                    i.status                 = 'VERIFIED'
                WITH i
                MATCH (p:Position {instrument_id: $instrument_id})
                MERGE (p)-[r:ISSUED_BY]->(i)
                SET r.source_doc            = 'holdings_csv',
                    r.page                  = 0,
                    r.chunk_id              = $instrument_id,
                    r.ingested_at           = $ingested_at,
                    r.extraction_confidence = 1.0
                """,
                issuer_name=pos.issuer_name,
                issuer_type=pos.issuer_type,
                instrument_id=pos.instrument_id,
                ingested_at=ingested_at,
            )

            # GRE issuers: create ParentIssuer node and ROLLS_UP_TO edge
            if pos.issuer_type == "GRE" and pos.parent_issuer:
                session.run(
                    """
                    MERGE (pi:ParentIssuer {name: $parent_issuer})
                    SET pi.source_doc            = 'holdings_csv',
                        pi.page                  = 0,
                        pi.chunk_id              = $parent_issuer,
                        pi.ingested_at           = $ingested_at,
                        pi.extraction_confidence = 1.0,
                        pi.status                = 'VERIFIED'
                    WITH pi
                    MATCH (i:Issuer {name: $issuer_name})
                    MERGE (i)-[r:ROLLS_UP_TO]->(pi)
                    SET r.source_doc            = 'holdings_csv',
                        r.page                  = 0,
                        r.chunk_id              = $issuer_name,
                        r.ingested_at           = $ingested_at,
                        r.extraction_confidence = 1.0
                    """,
                    parent_issuer=pos.parent_issuer,
                    issuer_name=pos.issuer_name,
                    ingested_at=ingested_at,
                )


def load_risk_metrics(driver: Any, chunks: list["RuleChunk"]) -> None:
    """Create RiskMetric, Threshold, BreachAction, Owner nodes from the market_risk_metrics chunk.

    Graph structure per metric:
      (RiskMetric)-[:HAS_THRESHOLD]->(Threshold)
      (RiskMetric)-[:HAS_BREACH_ACTION]->(BreachAction)
      (BreachAction)-[:NOTIFIES]->(Owner)
      (RiskMetric)-[:DERIVED_FROM]->(SourceChunk)

    Enables multi-hop queries such as:
      "What is the breach action for portfolio_duration and who is notified?"
    All nodes carry standard provenance props. Idempotent via MERGE.
    """
    ingested_at = _now_iso()
    metric_chunks = [c for c in chunks if c.extracted_fields.get("rule_type") == "market_risk_metrics"]
    if not metric_chunks:
        return

    chunk = metric_chunks[0]
    metrics: list[dict] = chunk.extracted_fields.get("metrics", [])
    status = "VERIFIED" if chunk.extraction_confidence >= _CONFIDENCE_THRESHOLD else "PENDING_REVIEW"

    with driver.session() as session:
        for m in metrics:
            metric_key: str = m["metric"]
            limit_val: str = m["limit"]
            monitoring: str = m["monitoring_frequency"]
            breach_action: str = m["breach_action"]
            owner_name: str = m["owner"]

            prov = dict(
                source_doc=chunk.source_doc,
                page=chunk.page,
                chunk_id=chunk.chunk_id,
                ingested_at=ingested_at,
                extraction_confidence=chunk.extraction_confidence,
            )

            # RiskMetric node + DERIVED_FROM -> SourceChunk
            session.run(
                """
                MERGE (rm:RiskMetric {metric: $metric})
                SET rm.limit                 = $limit,
                    rm.monitoring_frequency  = $monitoring_frequency,
                    rm.source_doc            = $source_doc,
                    rm.page                  = $page,
                    rm.chunk_id              = $chunk_id,
                    rm.ingested_at           = $ingested_at,
                    rm.extraction_confidence = $extraction_confidence,
                    rm.status                = $status
                """,
                metric=metric_key, limit=limit_val, monitoring_frequency=monitoring,
                status=status, **prov,
            )
            session.run(
                """
                MATCH (rm:RiskMetric {metric: $metric})
                MATCH (sc:SourceChunk {chunk_id: $chunk_id})
                MERGE (rm)-[r:DERIVED_FROM]->(sc)
                SET r.source_doc            = $source_doc,
                    r.page                  = $page,
                    r.chunk_id              = $chunk_id,
                    r.ingested_at           = $ingested_at,
                    r.extraction_confidence = $extraction_confidence
                """,
                metric=metric_key, **prov,
            )

            # Threshold node + HAS_THRESHOLD edge
            session.run(
                """
                MERGE (t:Threshold {metric: $metric})
                SET t.limit_value            = $limit_value,
                    t.source_doc             = $source_doc,
                    t.page                   = $page,
                    t.chunk_id               = $chunk_id,
                    t.ingested_at            = $ingested_at,
                    t.extraction_confidence  = $extraction_confidence,
                    t.status                 = $status
                """,
                metric=metric_key, limit_value=limit_val, status=status, **prov,
            )
            session.run(
                """
                MATCH (rm:RiskMetric {metric: $metric})
                MATCH (t:Threshold {metric: $metric})
                MERGE (rm)-[r:HAS_THRESHOLD]->(t)
                SET r.source_doc            = $source_doc,
                    r.ingested_at           = $ingested_at,
                    r.extraction_confidence = $extraction_confidence
                """,
                metric=metric_key, **prov,
            )

            # Owner node
            session.run(
                """
                MERGE (o:Owner {name: $owner_name})
                SET o.source_doc            = $source_doc,
                    o.page                  = $page,
                    o.chunk_id              = $chunk_id,
                    o.ingested_at           = $ingested_at,
                    o.extraction_confidence = $extraction_confidence,
                    o.status                = $status
                """,
                owner_name=owner_name, status=status, **prov,
            )

            # BreachAction node + HAS_BREACH_ACTION + NOTIFIES edges
            session.run(
                """
                MERGE (ba:BreachAction {action: $action})
                SET ba.metric                = $metric,
                    ba.source_doc            = $source_doc,
                    ba.page                  = $page,
                    ba.chunk_id              = $chunk_id,
                    ba.ingested_at           = $ingested_at,
                    ba.extraction_confidence = $extraction_confidence,
                    ba.status                = $status
                """,
                action=breach_action, metric=metric_key, status=status, **prov,
            )
            session.run(
                """
                MATCH (rm:RiskMetric {metric: $metric})
                MATCH (ba:BreachAction {action: $action})
                MERGE (rm)-[r:HAS_BREACH_ACTION]->(ba)
                SET r.source_doc            = $source_doc,
                    r.ingested_at           = $ingested_at,
                    r.extraction_confidence = $extraction_confidence
                """,
                metric=metric_key, action=breach_action, **prov,
            )
            session.run(
                """
                MATCH (ba:BreachAction {action: $action})
                MATCH (o:Owner {name: $owner_name})
                MERGE (ba)-[r:NOTIFIES]->(o)
                SET r.source_doc            = $source_doc,
                    r.ingested_at           = $ingested_at,
                    r.extraction_confidence = $extraction_confidence
                """,
                action=breach_action, owner_name=owner_name, **prov,
            )


def load_rules(driver: Any, chunks: list["RuleChunk"]) -> None:
    """Create SourceChunk and Limit nodes, with DERIVED_FROM edges.

    All nodes carry provenance props: source_doc, page, chunk_id, ingested_at,
    extraction_confidence.  Status is VERIFIED if confidence >= 0.85, else PENDING_REVIEW.
    Idempotent via MERGE.
    """
    ingested_at = _now_iso()

    with driver.session() as session:
        for chunk in chunks:
            status = (
                "VERIFIED"
                if chunk.extraction_confidence >= _CONFIDENCE_THRESHOLD
                else "PENDING_REVIEW"
            )

            # Merge SourceChunk node — chunk_id is the content-hash key
            session.run(
                """
                MERGE (sc:SourceChunk {chunk_id: $chunk_id})
                SET sc.source_doc            = $source_doc,
                    sc.page                  = $page,
                    sc.passage               = $passage,
                    sc.passage_summary       = $passage_summary,
                    sc.extraction_confidence = $extraction_confidence,
                    sc.ingested_at           = $ingested_at,
                    sc.status                = $status
                """,
                chunk_id=chunk.chunk_id,
                source_doc=chunk.source_doc,
                page=chunk.page,
                passage=chunk.passage,
                passage_summary=chunk.passage_summary,
                extraction_confidence=chunk.extraction_confidence,
                ingested_at=ingested_at,
                status=status,
            )

            rule_type = chunk.extracted_fields.get("rule_type", "unknown")
            ref = f"{rule_type}_{chunk.chunk_id}"

            # Merge Limit node linked to its SourceChunk via DERIVED_FROM
            session.run(
                """
                MERGE (l:Limit {ref: $ref})
                SET l.rule_type              = $rule_type,
                    l.status                 = $status,
                    l.extraction_confidence  = $extraction_confidence,
                    l.source_doc             = $source_doc,
                    l.page                   = $page,
                    l.chunk_id               = $chunk_id,
                    l.ingested_at            = $ingested_at
                WITH l
                MATCH (sc:SourceChunk {chunk_id: $chunk_id})
                MERGE (l)-[r:DERIVED_FROM]->(sc)
                SET r.source_doc            = $source_doc,
                    r.page                  = $page,
                    r.chunk_id              = $chunk_id,
                    r.ingested_at           = $ingested_at,
                    r.extraction_confidence = $extraction_confidence
                """,
                ref=ref,
                rule_type=rule_type,
                status=status,
                extraction_confidence=chunk.extraction_confidence,
                source_doc=chunk.source_doc,
                page=chunk.page,
                chunk_id=chunk.chunk_id,
                ingested_at=ingested_at,
            )
