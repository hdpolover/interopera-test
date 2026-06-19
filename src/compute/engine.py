"""Deterministic compliance figure computation engine.

Traverses Neo4j graph, applies primitives, produces Figure objects.
NO LLM client. Constructor accepts only (driver, config: FirmConfig).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.compute.config_loader import FirmConfig
from src.compute.primitives import (
    dv01, max_cap, max_group_pct, min_floor, nav,
    percent_1dp, sgd_dv01, sum_pct, truncated_bps,
    weighted_avg_duration, within_min_max, years_2dp,
)
from src.compute.registry import FIGURE_REGISTRY, Figure, FigureSpec
from src.graph import queries

# Maps AssetClass display name → slug, mirrors builder._ASSET_CLASS_SLUG.
# Used in _build_graph_path to fall back when a.slug is unavailable.
_ASSET_CLASS_SLUG: dict[str, str] = {
    "Singapore Government Securities": "sgs",
    "MAS Bills": "mas_bills",
    "Investment Grade Corporate Bonds": "ig_corp",
    "High Yield Bonds": "high_yield",
    "Foreign Currency Bonds": "fx_bonds",
    "Structured Credit": "structured_credit",
    "Cash & Cash Equivalents": "cash",
}

# Limit bounds by figure id (fractions for pct figures, raw for others)
_LIMIT_BOUNDS: dict[str, dict[str, Any]] = {
    "allocation_sgs":                    {"min": Decimal("0.20"), "max": Decimal("0.60")},
    "allocation_mas_bills":              {"min": Decimal("0.00"), "max": Decimal("0.40")},
    "allocation_ig_corp":                {"min": Decimal("0.10"), "max": Decimal("0.50")},
    "allocation_high_yield":             {"min": Decimal("0.00"), "max": Decimal("0.15")},
    "allocation_fx_bonds":               {"min": Decimal("0.00"), "max": Decimal("0.20")},
    "allocation_structured_credit":      {"min": Decimal("0.00"), "max": Decimal("0.10")},
    "allocation_cash":                   {"floor": Decimal("0.05")},
    "aggregate_non_ig_exposure":         {"cap": Decimal("0.20")},
    "largest_single_corporate_issuer":   {"cap": Decimal("0.08")},
    "largest_gre_issuer":                {"cap": Decimal("0.12")},
    "liquid_assets_ratio":               {"floor": Decimal("0.25")},
    "portfolio_duration":                {"min": Decimal("2.0"), "max": Decimal("6.5")},
    "portfolio_dv01":                    {"cap": Decimal("85000")},
}

# Maps each figure id to the actual rule_type stored on SourceChunk nodes.
# These must match the rule_type values produced by guidelines_parser.py's _STUB_PASSAGES.
_FIGURE_RULE_TYPE: dict[str, str] = {
    "allocation_sgs":                   "allocation_limit",
    "allocation_mas_bills":             "allocation_limit",
    "allocation_ig_corp":               "allocation_limit",
    "allocation_high_yield":            "allocation_limit",
    "allocation_fx_bonds":              "allocation_limit",
    "allocation_structured_credit":     "allocation_limit",
    "allocation_cash":                  "allocation_limit",
    "aggregate_non_ig_exposure":        "non_ig_cap",
    "largest_single_corporate_issuer":  "concentration_limit",
    "largest_gre_issuer":               "concentration_limit",
    "liquid_assets_ratio":              "liquidity_requirement",
    "portfolio_duration":               "duration_limit",
    "portfolio_dv01":                   "dv01_limit",
}


class ComputeEngine:
    """Compute all 13 compliance figures by traversing the Neo4j graph."""

    def __init__(self, driver, config: FirmConfig) -> None:
        self._driver = driver
        self._config = config
        self._nav: Decimal | None = None

    def _get_nav(self) -> Decimal:
        """Compute NAV once per run."""
        if self._nav is None:
            all_pos = queries.all_positions(self._driver)
            self._nav = nav(all_pos)
        return self._nav

    def _get_positions(self, spec: FigureSpec) -> list[dict]:
        """Fetch positions based on selector and predicate."""
        sel = spec.selector
        pred = dict(spec.predicate)

        if sel == "positions_in_asset_class":
            return queries.positions_in_asset_class(self._driver, pred["asset_class"])

        if sel == "positions_matching":
            # Resolve fallen_angel_config_key at runtime from config
            include_fallen = False
            if "fallen_angel_config_key" in pred:
                include_fallen = self._config.non_ig.include_fallen_angels
            asset_classes = pred.get("asset_class_in", [])
            effective_pred: dict[str, Any] = {"asset_class_in": asset_classes}
            if include_fallen:
                # The query's OR clause picks up fallen angels (downgraded_from IS NOT NULL
                # AND credit_rating IN below_ig_ratings) regardless of asset class,
                # so asset_class_in stays as-is (HY + SC only).
                effective_pred["include_fallen_angels"] = True
            else:
                effective_pred["include_fallen_angels"] = False
            return queries.positions_matching(self._driver, effective_pred)

        if sel == "liquid_positions":
            return queries.liquid_positions(self._driver)

        if sel == "all_positions":
            return queries.all_positions(self._driver)

        return []

    def _compute_value(
        self, spec: FigureSpec, positions: list[dict], nav_value: Decimal
    ) -> Decimal:
        """Apply the aggregator to positions."""
        agg = spec.aggregator
        if agg == "sum_pct":
            return sum_pct(positions, nav_value)
        if agg == "weighted_avg_duration":
            return weighted_avg_duration(positions, nav_value)
        if agg == "dv01":
            return dv01(positions, nav_value)
        raise ValueError(f"Unknown aggregator: {agg}")

    def _compute_group_value(
        self, spec: FigureSpec, nav_value: Decimal
    ) -> tuple[Decimal, str]:
        """Compute grouped figure (max_group_pct). Returns (value, group_name)."""
        pred = dict(spec.predicate)
        # Resolve group_key from config if needed
        if "group_key_config_key" in pred:
            group_key = self._config.concentration.gre.group_key
        else:
            group_key = pred.get("group_key", "issuer")

        issuer_type_filter = pred.get("issuer_type_filter")
        all_groups = queries.positions_by_issuer(self._driver, group_key)

        # Filter groups by issuer type if needed
        if issuer_type_filter:
            filtered: dict[str, list] = {}
            for gname, gpositions in all_groups.items():
                matching = [p for p in gpositions if p.get("issuer_type") == issuer_type_filter]
                if matching:
                    filtered[gname] = matching
            all_groups = filtered

        if not all_groups:
            return Decimal("0"), ""

        gname, gpct = max_group_pct(all_groups, nav_value)
        return gpct, gname

    def _apply_comparator(self, spec: FigureSpec, value: Decimal) -> str:
        """Apply comparator to produce OK/BREACH/AT LIMIT."""
        comp = spec.comparator
        bounds = _LIMIT_BOUNDS.get(spec.id, {})

        if comp == "within_min_max":
            return within_min_max(value, bounds["min"], bounds["max"])
        if comp == "max_cap":
            return max_cap(value, bounds["cap"])
        if comp == "min_floor":
            return min_floor(value, bounds["floor"])
        return "ERROR"

    def _apply_formatter(self, spec: FigureSpec, value: Decimal) -> str:
        """Format the value field (always independent of utilization_format)."""
        fmt = spec.formatter
        if fmt == "percent_1dp":
            return percent_1dp(value)
        if fmt == "years_2dp":
            return years_2dp(value)
        if fmt == "sgd_dv01":
            return sgd_dv01(value)
        return str(value)

    def _compute_utilization(self, spec: FigureSpec, value: Decimal) -> str:
        """Compute utilization string based on utilization_basis and config format."""
        basis = spec.utilization_basis
        bounds = _LIMIT_BOUNDS.get(spec.id, {})
        util_fmt = self._config.output.utilization_format

        if basis == "none":
            return "n/a"

        # Compute raw utilization fraction
        if basis == "max":
            denom = bounds.get("max")
        elif basis == "cap":
            denom = bounds.get("cap")
        elif basis == "floor":
            denom = bounds.get("floor")
        else:
            return "n/a"

        if denom is None or denom == 0:
            return "n/a"

        raw_util = value / denom

        if util_fmt == "truncated_bps":
            return truncated_bps(raw_util)
        else:
            return percent_1dp(raw_util)

    def _build_graph_path(self, spec: FigureSpec, positions: list[dict]) -> str:
        """Build a human-readable graph path from the actual traversal result."""
        sel = spec.selector
        if sel == "positions_in_asset_class":
            ac_display = spec.predicate.get("asset_class", "?")
            ac = _ASSET_CLASS_SLUG.get(ac_display, ac_display)
            ids = [p["instrument_id"] for p in positions]
            return f"(Position:{', '.join(ids)})-[:IN_ASSET_CLASS]->(AssetClass:{ac})"
        if sel == "positions_matching":
            # Serialize the ACTUAL matched CONTRIBUTES_TO traversal feeding the aggregate.
            # Query a.slug so paths use slug identifiers (e.g. high_yield, structured_credit).
            # ORDER BY a.slug produces alphabetical slug order: high_yield before structured_credit,
            # matching the brief's worked example for Firm A exactly.
            with self._driver.session() as session:
                result = session.run(
                    """
                    MATCH (a:AssetClass)-[:CONTRIBUTES_TO]->(agg:Aggregate {name: 'non_ig'})
                    RETURN a.slug AS name ORDER BY a.slug
                    """
                )
                ac_names = [r["name"] for r in result]
            if ac_names:
                path = f"(AssetClass:{ac_names[0]})-[:CONTRIBUTES_TO]->(Aggregate:non_ig)"
                for nm in ac_names[1:]:
                    path += f"<-[:CONTRIBUTES_TO]-(AssetClass:{nm})"
            else:
                path = "(Aggregate:non_ig)"
            if self._config.non_ig.include_fallen_angels:
                fallen = [
                    p["instrument_id"]
                    for p in positions
                    if p.get("asset_class") == "Investment Grade Corporate Bonds"
                ]
                if fallen:
                    path += (
                        f", (Position:{', '.join(fallen)})"
                        f"-[:RATED_BELOW_IG]->(Aggregate:non_ig)"
                    )
            return path
        if sel == "liquid_positions":
            ids = [p["instrument_id"] for p in positions]
            return f"(Position:{', '.join(ids)})-[:IN_ASSET_CLASS]->(AssetClass:liquid)"
        if sel == "all_positions":
            return "(Position:all)-[:IN_ASSET_CLASS]->(AssetClass:all)"
        if sel == "positions_by_issuer":
            return "(Position)-[:ISSUED_BY]->(Issuer)-[:ROLLS_UP_TO?]->(ParentIssuer)"
        return f"({sel})"

    def _get_citation(self, spec: FigureSpec | None = None) -> dict | None:
        """Return citation from the SourceChunk node reachable via this figure's Limit node.

        Traversal: (Limit {rule_type})-[:DERIVED_FROM]->(SourceChunk)
        The Limit.rule_type property is set by builder.load_rules from extracted_fields.

        Returns None when no SourceChunk is reachable (missing or broken DERIVED_FROM edge).
        The caller (compute_figure) must treat None as an unresolvable citation and return
        Figure(status="ERROR") — a figure that cannot be traced to a source document is not
        safe to emit as a numeric value.
        """
        rule_type = _FIGURE_RULE_TYPE.get(spec.id, "") if spec else ""
        with self._driver.session() as session:
            if rule_type:
                result = session.run(
                    """
                    MATCH (l:Limit {rule_type: $rule_type})-[:DERIVED_FROM]->(sc:SourceChunk)
                    WHERE sc.status = 'VERIFIED'
                    RETURN sc.chunk_id AS chunk_id,
                           sc.source_doc AS source_doc,
                           sc.page AS page,
                           sc.passage_summary AS passage_summary
                    LIMIT 1
                    """,
                    rule_type=rule_type,
                )
            else:
                result = session.run(
                    """
                    MATCH (sc:SourceChunk)
                    WHERE sc.status = 'VERIFIED'
                    RETURN sc.chunk_id AS chunk_id,
                           sc.source_doc AS source_doc,
                           sc.page AS page,
                           sc.passage_summary AS passage_summary
                    LIMIT 1
                    """
                )
            record = result.single()
            if record:
                return {
                    "source_doc": record["source_doc"],
                    "page": record["page"],
                    "chunk_id": record["chunk_id"],
                    "passage_summary": record["passage_summary"],
                }
        return None

    def _check_limit_node_pending(self, spec: FigureSpec) -> bool:
        """Return True if the anchor Limit node for this figure is PENDING_REVIEW.

        Limit nodes are keyed by ref = '{rule_type}_{chunk_id}'.  We match on
        the Limit.rule_type property (which equals the chunk's extracted rule_type)
        to find limit nodes anchoring this figure type.
        """
        rule_type = _FIGURE_RULE_TYPE.get(spec.id, "")
        if not rule_type:
            return False
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (l:Limit {rule_type: $rule_type})
                WHERE l.status = 'PENDING_REVIEW'
                RETURN count(l) AS cnt
                """,
                rule_type=rule_type,
            )
            record = result.single()
            return bool(record and record["cnt"] > 0)

    def compute_figure(self, spec: FigureSpec) -> Figure:
        """Compute a single Figure by traversing the graph."""
        nav_value = self._get_nav()
        citation = self._get_citation(spec)

        # Gate 1: no reachable SourceChunk — figure cannot be traced to a source document.
        # A figure with an unresolvable citation must not be emitted as a numeric value.
        _empty_citation: dict = {"source_doc": "", "page": 0, "chunk_id": "", "passage_summary": ""}
        if citation is None:
            return Figure(
                figure=spec.id,
                value="ERROR",
                utilization="n/a",
                status="ERROR",
                limit=spec.limit_display,
                graph_path="no reachable SourceChunk — citation unresolvable",
                citation=_empty_citation,
            )

        # Gate 2: anchor Limit node is pending human verification
        if self._check_limit_node_pending(spec):
            return Figure(
                figure=spec.id,
                value="ERROR",
                utilization="n/a",
                status="ERROR",
                limit=spec.limit_display,
                graph_path="PENDING_REVIEW Limit node blocks computation",
                citation=citation,
            )

        if spec.selector == "positions_by_issuer":
            value, _group_name = self._compute_group_value(spec, nav_value)
            positions = []  # groups don't return flat list
        else:
            positions = self._get_positions(spec)
            # Check for PENDING_REVIEW nodes in positions
            for p in positions:
                if p.get("status") == "PENDING_REVIEW":
                    return Figure(
                        figure=spec.id,
                        value="ERROR",
                        utilization="n/a",
                        status="ERROR",
                        limit=spec.limit_display,
                        graph_path="PENDING_REVIEW node blocks computation",
                        citation=citation,
                    )
            value = self._compute_value(spec, positions, nav_value)

        status = self._apply_comparator(spec, value)
        formatted_value = self._apply_formatter(spec, value)
        utilization = self._compute_utilization(spec, value)
        graph_path = self._build_graph_path(spec, positions)

        return Figure(
            figure=spec.id,
            value=formatted_value,
            utilization=utilization,
            status=status,
            limit=spec.limit_display,
            graph_path=graph_path,
            citation=citation,
        )

    def run_all(self) -> list[Figure]:
        """Run all figures in FIGURE_REGISTRY order. Reset NAV cache per run."""
        self._nav = None  # reset for determinism
        return [self.compute_figure(spec) for spec in FIGURE_REGISTRY]
