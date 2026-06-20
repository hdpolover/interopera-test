"""Graph query selectors for the compliance engine.

All selectors return list[dict] with provenance included.
All position queries ORDER BY p.instrument_id for determinism.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Final, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class _HasCitation(Protocol):
    """Structural type for objects that carry a citation dict (e.g. Figure)."""

    @property
    def citation(self) -> dict: ...

# Asset classes considered liquid (government securities + cash)
_LIQUID_ASSET_CLASSES = {
    "Singapore Government Securities",
    "MAS Bills",
    "Cash & Cash Equivalents",
}

# Investment-grade ratings (floor is BBB-)
_IG_RATINGS = {"AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"}

# Explicit below-IG ratings used to identify fallen angels.
# A fallen angel is an IG-class position whose credit_rating has dropped into this set
# and whose downgraded_from field is set (proving prior IG status).
# Investment-grade floor is BBB-; anything below that is in this set.
_BELOW_IG_RATINGS = {
    "BB+", "BB", "BB-",
    "B+", "B", "B-",
    "CCC+", "CCC", "CCC-",
    "CC", "C", "D",
}

# Allowlisted position property names returned in every selector query.
# Expressed as a frozen tuple so static analysis and runtime checks can verify
# each entry is a plain identifier with no injection surface.
_POSITION_COLUMN_NAMES: Final[tuple[str, ...]] = (
    "instrument_id",
    "instrument_name",
    "asset_class",
    "issuer_name",
    "issuer_type",
    "credit_rating",
    "downgraded_from",
    "market_value_sgd",
    "modified_duration",
    "status",
    "source_doc",
    "page",
    "chunk_id",
    "ingested_at",
    "extraction_confidence",
)

# Verify every column name is a safe identifier (letters, digits, underscores only).
assert all(
    name.replace("_", "").isalnum() for name in _POSITION_COLUMN_NAMES
), "BUG: _POSITION_COLUMN_NAMES contains an unsafe identifier"

# Cypher RETURN clause built once from the allowlisted column names.
# Columns are comma-separated so the snippet is valid inside a RETURN clause.
_POSITION_COLUMNS: Final[str] = ",\n    ".join(
    f"p.{col} AS {col}" for col in _POSITION_COLUMN_NAMES
)


def _row_to_dict(record: Any) -> dict[str, Any]:
    """Convert a Neo4j Record to a plain Python dict."""
    return dict(record)


def positions_in_asset_class(driver: Any, ac: str) -> list[dict[str, Any]]:
    """Return all positions in the given asset class, sorted by instrument_id."""
    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (p:Position)-[:IN_ASSET_CLASS]->(a:AssetClass {{name: $ac}})
            RETURN {_POSITION_COLUMNS}
            ORDER BY p.instrument_id
            """,
            ac=ac,
        )
        return [_row_to_dict(r) for r in result]


def positions_matching(driver: Any, predicate: dict[str, Any]) -> list[dict[str, Any]]:
    """Return positions matching the given predicate dict.

    Predicate keys:
    - asset_class_in: list[str] — match positions in these asset classes
    - include_fallen_angels: bool — if True, also include positions in the
      listed IG-class asset classes whose credit_rating has fallen below IG
      (i.e. credit_rating is in _BELOW_IG_RATINGS AND downgraded_from is set).
      Default False.

    Fallen-angel logic (precise):
    - Without include_fallen_angels: return only positions whose AssetClass.name
      is in asset_class_in.
    - With include_fallen_angels: additionally return positions where
      downgraded_from IS NOT NULL AND credit_rating IN _BELOW_IG_RATINGS
      (regardless of which asset class they are in, because the position is still
      booked under its original IG class but its rating has degraded).
    """
    asset_classes: list[str] = predicate.get("asset_class_in", [])
    include_fallen_angels: bool = predicate.get("include_fallen_angels", False)

    with driver.session() as session:
        if include_fallen_angels:
            result = session.run(
                f"""
                MATCH (p:Position)-[:IN_ASSET_CLASS]->(a:AssetClass)
                WHERE a.name IN $asset_classes
                   OR (
                       p.downgraded_from IS NOT NULL
                       AND p.downgraded_from <> ''
                       AND p.credit_rating IN $below_ig_ratings
                   )
                RETURN {_POSITION_COLUMNS}
                ORDER BY p.instrument_id
                """,
                asset_classes=asset_classes,
                below_ig_ratings=list(_BELOW_IG_RATINGS),
            )
        else:
            result = session.run(
                f"""
                MATCH (p:Position)-[:IN_ASSET_CLASS]->(a:AssetClass)
                WHERE a.name IN $asset_classes
                RETURN {_POSITION_COLUMNS}
                ORDER BY p.instrument_id
                """,
                asset_classes=asset_classes,
            )
        return [_row_to_dict(r) for r in result]


def positions_by_issuer(driver: Any, group_key: str) -> dict[str, list[dict[str, Any]]]:
    """Return positions grouped by issuer or parent_issuer.

    group_key values:
    - "issuer": group by the immediate Issuer node name (p.issuer_name)
    - "parent_issuer": group GREs by their ParentIssuer name; non-GREs fall
      back to issuer name (via COALESCE).

    All sub-lists are sorted by instrument_id (ORDER BY in the query).
    """
    groups: dict[str, list[dict[str, Any]]] = {}

    with driver.session() as session:
        if group_key == "parent_issuer":
            result = session.run(
                f"""
                MATCH (p:Position)-[:ISSUED_BY]->(i:Issuer)
                OPTIONAL MATCH (i)-[:ROLLS_UP_TO]->(pi:ParentIssuer)
                RETURN {_POSITION_COLUMNS},
                       COALESCE(pi.name, i.name) AS group_name
                ORDER BY p.instrument_id
                """
            )
        else:
            # group by immediate issuer
            result = session.run(
                f"""
                MATCH (p:Position)-[:ISSUED_BY]->(i:Issuer)
                RETURN {_POSITION_COLUMNS},
                       i.name AS group_name
                ORDER BY p.instrument_id
                """
            )

        for record in result:
            row = _row_to_dict(record)
            gname = row.pop("group_name")
            groups.setdefault(gname, []).append(row)

    return groups


def liquid_positions(driver: Any) -> list[dict[str, Any]]:
    """Return positions in liquid asset classes (SGS, MAS Bills, Cash), sorted by instrument_id."""
    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (p:Position)-[:IN_ASSET_CLASS]->(a:AssetClass)
            WHERE a.name IN $liquid_classes
            RETURN {_POSITION_COLUMNS}
            ORDER BY p.instrument_id
            """,
            liquid_classes=list(_LIQUID_ASSET_CLASSES),
        )
        return [_row_to_dict(r) for r in result]


def all_positions(driver: Any) -> list[dict[str, Any]]:
    """Return all Position nodes sorted by instrument_id."""
    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (p:Position)
            RETURN {_POSITION_COLUMNS}
            ORDER BY p.instrument_id
            """
        )
        return [_row_to_dict(r) for r in result]


def list_pending_nodes(driver: Any) -> list[dict[str, Any]]:
    """Return all nodes with status = 'PENDING_REVIEW'.

    Returns dicts with: labels, node_id, status, confidence.
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (n)
            WHERE n.status = 'PENDING_REVIEW'
            RETURN labels(n) AS labels,
                   COALESCE(n.instrument_id, n.chunk_id, n.ref, n.name, '') AS node_id,
                   n.status AS status,
                   n.extraction_confidence AS confidence
            """
        )
        return [_row_to_dict(r) for r in result]


# Maps each node label to the single property that uniquely identifies it.
# Used by approve_node when the caller provides a node_label discriminator.
_LABEL_KEY_MAP: Final[dict[str, str]] = {
    "Position": "instrument_id",
    "Limit": "chunk_id",
    "SourceChunk": "chunk_id",
    "RiskMetric": "metric",
    "AssetClass": "name",
    "Issuer": "name",
    "ParentIssuer": "name",
    "Owner": "name",
    "BreachAction": "action",
    "Threshold": "metric",
}


def approve_node(
    driver: Any,
    node_id: str,
    actor: str,
    node_label: str | None = None,
) -> None:
    """Flip a PENDING_REVIEW node to VERIFIED.

    When node_label is provided (e.g. "Limit"), the MATCH targets only nodes
    with that label, keyed by the label's canonical identity property from
    _LABEL_KEY_MAP.  This prevents a same-valued property on a different node
    type from being accidentally approved.

    When node_label is None the legacy COALESCE path is used (backward-compatible
    for callers that do not yet supply a label).

    Raises ValueError if actor is empty or whitespace-only — every approval
    must be attributed to a named reviewer for audit purposes.
    Raises ValueError if node_label is supplied but not in _LABEL_KEY_MAP.
    """
    if not actor or not actor.strip():
        raise ValueError("actor must be a non-empty string for approve_node")

    if node_label is not None:
        if node_label not in _LABEL_KEY_MAP:
            raise ValueError(
                f"Unknown node_label {node_label!r}. "
                f"Known labels: {sorted(_LABEL_KEY_MAP)}"
            )
        key_prop = _LABEL_KEY_MAP[node_label]
        cypher = (
            f"MATCH (n:{node_label} {{{key_prop}: $node_id}})\n"
            "WHERE n.status = 'PENDING_REVIEW'\n"
            "SET n.status = 'VERIFIED', n.approved_by = $actor"
        )
    else:
        cypher = (
            "MATCH (n)\n"
            "WHERE COALESCE(n.instrument_id, n.chunk_id, n.ref, n.name, '') = $node_id\n"
            "  AND n.status = 'PENDING_REVIEW'\n"
            "SET n.status = 'VERIFIED', n.approved_by = $actor"
        )

    with driver.session() as session:
        session.run(cypher, node_id=node_id, actor=actor)


# ---------------------------------------------------------------------------
# Utility lookups for rule nodes (used by the compliance engine)
# ---------------------------------------------------------------------------


def limit_node(driver: Any, ref: str) -> dict[str, Any]:
    """Return a Limit node by ref, or empty dict if not found."""
    with driver.session() as session:
        result = session.run(
            "MATCH (l:Limit {ref: $ref}) RETURN l",
            ref=ref,
        )
        record = result.single()
        return dict(record["l"]) if record else {}


def aggregate_node(driver: Any, name: str) -> dict[str, Any]:
    """Return an Aggregate node by name, or empty dict if not found."""
    with driver.session() as session:
        result = session.run(
            "MATCH (a:Aggregate {name: $name}) RETURN a",
            name=name,
        )
        record = result.single()
        return dict(record["a"]) if record else {}


def threshold_node(driver: Any, metric: str) -> dict[str, Any]:
    """Return a Threshold node by metric, or empty dict if not found."""
    with driver.session() as session:
        result = session.run(
            "MATCH (t:Threshold {metric: $metric}) RETURN t",
            metric=metric,
        )
        record = result.single()
        return dict(record["t"]) if record else {}


def retrieve_passages_for_narrative(
    driver: Any, figures: Sequence[_HasCitation]
) -> list[dict[str, Any]]:
    """Retrieve SourceChunk passages for narrative grounding.

    Global retrieval: query chunk/rule nodes whose rule_type is in
    ('allocation limits', 'concentration limits', 'market risk').
    Local retrieval: include citation passage_summary from each figure.

    Returns list of dicts: {chunk_id, passage_summary, rule_type, page}.
    Deduplicates by chunk_id (global retrieval first, local fills in missing).
    """
    seen: dict[str, dict[str, Any]] = {}

    # Global retrieval — query broadly for any node with chunk_id property.
    # CypherSyntaxError and ServiceUnavailable indicate the graph legitimately
    # has no such nodes (missing label) or a transient connection issue.
    # Other exceptions are unexpected and are logged before re-raising.
    try:
        from neo4j.exceptions import CypherSyntaxError, ServiceUnavailable  # type: ignore[import-untyped]
    except ImportError:
        CypherSyntaxError = Exception  # type: ignore[misc,assignment]
        ServiceUnavailable = Exception  # type: ignore[misc,assignment]

    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (c)
                WHERE (c:RuleChunk OR c:Chunk OR c:SourceChunk)
                  AND c.chunk_id IS NOT NULL
                RETURN c.chunk_id       AS chunk_id,
                       c.passage_summary AS passage_summary,
                       c.rule_type       AS rule_type,
                       c.page            AS page
                ORDER BY c.chunk_id
                """
            )
            for record in result:
                row = _row_to_dict(record)
                cid = row.get("chunk_id")
                if cid and cid not in seen:
                    seen[cid] = row
    except (CypherSyntaxError, ServiceUnavailable):
        # Graph may lack chunk nodes or be transiently unavailable;
        # fall through to local retrieval.
        pass
    except Exception as exc:
        # Log unexpected errors at WARNING and fall through to local retrieval.
        # This function is designed to degrade gracefully so narrative generation
        # is never blocked by a graph retrieval failure.
        logger.warning(
            "Unexpected error during global passage retrieval: %s", exc, exc_info=True
        )

    # Local retrieval — pull citation from each figure's citation dict
    for fig in figures:
        citation = getattr(fig, "citation", None)
        if not isinstance(citation, dict):
            continue
        cid = citation.get("chunk_id")
        if cid and cid not in seen:
            seen[cid] = {
                "chunk_id": cid,
                "passage_summary": citation.get("passage_summary"),
                "rule_type": None,
                "page": citation.get("page"),
            }

    return list(seen.values())


def list_all_breach_actions(driver: Any) -> list[dict[str, Any]]:
    """Return all RiskMetric nodes with their breach actions and owners, ordered by metric name.

    Returns list of dicts, each with: metric, limit, monitoring_frequency, breach_action, owner.
    Returns empty list if no RiskMetric nodes exist.
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (rm:RiskMetric)
                  -[:HAS_BREACH_ACTION]->(ba:BreachAction)
                  -[:NOTIFIES]->(o:Owner)
            RETURN rm.metric              AS metric,
                   rm.limit               AS limit,
                   rm.monitoring_frequency AS monitoring_frequency,
                   ba.action              AS breach_action,
                   o.name                 AS owner
            ORDER BY rm.metric
            """
        )
        return [_row_to_dict(r) for r in result]


def breach_action_for_metric(driver: Any, metric: str) -> dict[str, Any]:
    """Multi-hop query: RiskMetric -> BreachAction -> Owner.

    Returns dict with: metric, limit, monitoring_frequency, breach_action, owner.
    Returns empty dict if metric not found — callers must handle this case.

    Example traversal for 'portfolio_duration':
      (RiskMetric {metric:'portfolio_duration'})
        -[:HAS_BREACH_ACTION]->
      (BreachAction {action:'PM notification within 1h'})
        -[:NOTIFIES]->
      (Owner {name:'Portfolio Manager'})
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (rm:RiskMetric {metric: $metric})
                  -[:HAS_BREACH_ACTION]->(ba:BreachAction)
                  -[:NOTIFIES]->(o:Owner)
            RETURN rm.metric              AS metric,
                   rm.limit               AS limit,
                   rm.monitoring_frequency AS monitoring_frequency,
                   ba.action              AS breach_action,
                   o.name                 AS owner
            """,
            metric=metric,
        )
        record = result.single()
        return dict(record) if record else {}
