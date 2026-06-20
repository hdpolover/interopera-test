"""Deterministic compliance figure computation engine.

Traverses Neo4j graph, applies primitives, produces Figure objects.
NO LLM client. Constructor accepts only (driver, config: FirmConfig).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

from src.compute.config_loader import FirmConfig
from src.compute.primitives import (
    dv01, max_cap, max_group_pct, min_floor, nav,
    percent_1dp, sgd_dv01, sum_pct, truncated_bps,
    weighted_avg_duration, within_min_max, years_2dp,
)
from src.compute.registry import FIGURE_REGISTRY, Figure, FigureSpec
from src.graph import queries
from src.graph.constants import ASSET_CLASS_SLUG as _ASSET_CLASS_SLUG

def _build_limit_bounds(limits: dict[str, Any]) -> dict[str, dict[str, Decimal]]:
    """Normalize config.limits dict to engine-internal {figure_id: {min/max/cap/floor: Decimal}}.

    Config shape → engine key mapping:
      min_pct / min_years  → "min"
      max_pct / max_years  → "max"
      max_sgd              → "cap"
    When only min_pct is present (no max_pct), the figure uses a floor comparator → "floor".
    When only max_pct is present (no min_pct), the figure uses a cap comparator → "cap".
    """
    required_figure_ids = {
        "allocation_sgs", "allocation_mas_bills", "allocation_ig_corp",
        "allocation_high_yield", "allocation_fx_bonds", "allocation_structured_credit",
        "allocation_cash", "aggregate_non_ig_exposure", "largest_single_corporate_issuer",
        "largest_gre_issuer", "liquid_assets_ratio", "portfolio_duration", "portfolio_dv01",
    }
    missing = required_figure_ids - set(limits.keys())
    if missing:
        raise ValueError(f"config.limits missing required figure keys: {sorted(missing)}")

    result: dict[str, dict[str, Decimal]] = {}
    for fig_id, raw in limits.items():
        bounds: dict[str, Decimal] = {}
        if "min_pct" in raw and "max_pct" in raw:
            bounds["min"] = Decimal(str(raw["min_pct"]))
            bounds["max"] = Decimal(str(raw["max_pct"]))
        elif "min_years" in raw and "max_years" in raw:
            bounds["min"] = Decimal(str(raw["min_years"]))
            bounds["max"] = Decimal(str(raw["max_years"]))
        elif "min_pct" in raw:
            bounds["floor"] = Decimal(str(raw["min_pct"]))
        elif "max_pct" in raw:
            bounds["cap"] = Decimal(str(raw["max_pct"]))
        elif "max_sgd" in raw:
            bounds["cap"] = Decimal(str(raw["max_sgd"]))
        result[fig_id] = bounds
    return result

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

    def __init__(self, driver: Any, config: FirmConfig) -> None:
        self._driver = driver
        self._config = config
        self._nav: Decimal | None = None
        self._limit_bounds: dict[str, dict[str, Decimal]] = _build_limit_bounds(config.limits)

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
    ) -> tuple[Decimal | None, str, str, list[str]]:
        """Compute grouped figure (max_group_pct). Returns (value, group_name, group_key, member_ids).

        Returns None as value when no groups exist, signalling an ERROR figure to the caller.
        """
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
            # Return sentinel None to signal "no groups found" — caller routes to ERROR figure.
            return None, "", group_key, []

        gname, gpct = max_group_pct(all_groups, nav_value)
        member_ids = [p.get("instrument_id", "UNKNOWN") for p in all_groups[gname]]
        return gpct, gname, group_key, member_ids

    def _apply_comparator(self, spec: FigureSpec, value: Decimal) -> str:
        """Apply comparator to produce OK/BREACH/AT LIMIT."""
        comp = spec.comparator
        bounds = self._limit_bounds.get(spec.id, {})

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
        bounds = self._limit_bounds.get(spec.id, {})
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

        if denom is None or denom == Decimal("0"):
            return "n/a"

        raw_util = value / denom

        if util_fmt == "truncated_bps":
            return truncated_bps(raw_util)
        else:
            return percent_1dp(raw_util)

    def _fetch_non_ig_ac_names(self) -> list[str]:
        """Query Neo4j for asset-class slugs that CONTRIBUTES_TO the non_ig aggregate.

        Returns slugs in alphabetical order (ORDER BY a.slug). Extracted from
        _build_graph_path so the graph builder is pure and Neo4j I/O is explicit
        at the call site in compute_figure.
        """
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (a:AssetClass)-[:CONTRIBUTES_TO]->(agg:Aggregate {name: 'non_ig'})
                RETURN a.slug AS name ORDER BY a.slug
                """
            )
            return [r["name"] for r in result]

    def _build_non_ig_path(
        self,
        positions: list[dict],
        ac_names: list[str],
    ) -> str:
        """Build the graph path string for the positions_matching (non-IG) selector.

        ac_names must be pre-fetched by the caller (no I/O here).
        """
        if ac_names:
            path = f"(AssetClass:{ac_names[0]})-[:CONTRIBUTES_TO]->(Aggregate:non_ig)"
            for nm in ac_names[1:]:
                path += f"<-[:CONTRIBUTES_TO]-(AssetClass:{nm})"
        else:
            path = "(Aggregate:non_ig)"
        if self._config.non_ig.include_fallen_angels:
            fallen = [
                p.get("instrument_id", "UNKNOWN")
                for p in positions
                if p.get("asset_class") == "Investment Grade Corporate Bonds"
            ]
            if fallen:
                path += (
                    f", (Position:{', '.join(fallen)})"
                    f"-[:RATED_BELOW_IG]->(Aggregate:non_ig)"
                )
        return path

    def _build_graph_path(
        self,
        spec: FigureSpec,
        positions: list[dict],
        group_name: str = "",
        group_key: str = "",
        member_ids: list[str] | None = None,
        non_ig_ac_names: list[str] | None = None,
    ) -> str:
        """Build a human-readable graph path from the actual traversal result.

        Pure function: all graph data must be passed in as parameters.
        No live I/O is performed here — callers fetch data before calling.
        """
        sel = spec.selector
        if sel == "positions_in_asset_class":
            ac_display = spec.predicate.get("asset_class", "?")
            ac = _ASSET_CLASS_SLUG.get(ac_display, ac_display)
            ids = [p.get("instrument_id", "UNKNOWN") for p in positions]
            return f"(Position:{', '.join(ids)})-[:IN_ASSET_CLASS]->(AssetClass:{ac})"
        if sel == "positions_matching":
            return self._build_non_ig_path(positions, non_ig_ac_names or [])
        if sel == "liquid_positions":
            ids = [p.get("instrument_id", "UNKNOWN") for p in positions]
            return f"(Position:{', '.join(ids)})-[:IN_ASSET_CLASS]->(AssetClass:liquid)"
        if sel == "all_positions":
            return "(Position:all)-[:IN_ASSET_CLASS]->(AssetClass:all)"
        if sel == "positions_by_issuer":
            ids_str = ", ".join(sorted(member_ids or []))
            if group_key == "parent_issuer":
                return (
                    f"(Position:{ids_str})-[:ISSUED_BY]->(Issuer)"
                    f"-[:ROLLS_UP_TO]->(ParentIssuer:{group_name})"
                )
            return f"(Position:{ids_str})-[:ISSUED_BY]->(Issuer:{group_name})"
        return f"({sel})"

    def _get_citation(self, spec: FigureSpec) -> dict | None:
        """Return citation from the SourceChunk node reachable via this figure's Limit node.

        Traversal: (Limit {rule_type})-[:DERIVED_FROM]->(SourceChunk)
        The Limit.rule_type property is set by builder.load_rules from extracted_fields.

        Returns None when no SourceChunk is reachable (missing or broken DERIVED_FROM edge).
        The caller (compute_figure) must treat None as an unresolvable citation and return
        Figure(status="ERROR") — a figure that cannot be traced to a source document is not
        safe to emit as a numeric value.
        """
        rule_type = _FIGURE_RULE_TYPE.get(spec.id, "")
        # Guard: if rule_type is empty (falsy), we have no rule anchor to cite.
        # Return None so that the caller's missing-citation→ERROR path fires,
        # rather than returning a random VERIFIED SourceChunk unrelated to this figure.
        if not rule_type:
            return None
        with self._driver.session() as session:
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

    def _check_gates(
        self, spec: FigureSpec, citation: dict | None
    ) -> Figure | None:
        """Check citation and PENDING_REVIEW gates. Returns a blocking Figure or None to proceed."""
        _empty_citation: dict = {"source_doc": "", "page": 0, "chunk_id": "", "passage_summary": ""}
        if citation is None:
            return Figure(
                figure=spec.id, value="ERROR", utilization="n/a", status="ERROR",
                limit=spec.limit_display,
                graph_path="no reachable SourceChunk — citation unresolvable",
                citation=_empty_citation,
            )
        if self._check_limit_node_pending(spec):
            return Figure(
                figure=spec.id, value="ERROR", utilization="n/a", status="ERROR",
                limit=spec.limit_display,
                graph_path="PENDING_REVIEW Limit node blocks computation",
                citation=citation,
            )
        return None

    def _resolve_value(
        self,
        spec: FigureSpec,
        nav_value: Decimal,
        citation: dict,
    ) -> tuple[Decimal, list[dict], str, str, list[str]] | Figure:
        """Resolve positions and compute the raw Decimal value for a figure.

        Returns either (value, positions, group_name, group_key, member_ids)
        or a blocking Figure on error.
        """
        if spec.selector == "positions_by_issuer":
            raw_value, group_name, group_key, member_ids = self._compute_group_value(spec, nav_value)
            if raw_value is None:
                return Figure(
                    figure=spec.id, value="ERROR", utilization="n/a", status="ERROR",
                    limit=spec.limit_display,
                    graph_path="no positions found for group comparison",
                    citation=citation,
                )
            return raw_value, [], group_name, group_key, member_ids

        positions = self._get_positions(spec)
        for p in positions:
            if p.get("status") == "PENDING_REVIEW":
                return Figure(
                    figure=spec.id, value="ERROR", utilization="n/a", status="ERROR",
                    limit=spec.limit_display,
                    graph_path="PENDING_REVIEW node blocks computation",
                    citation=citation,
                )
        return self._compute_value(spec, positions, nav_value), positions, "", "", []

    def compute_figure(self, spec: FigureSpec) -> Figure:
        """Compute a single Figure by traversing the graph."""
        nav_value = self._get_nav()
        citation = self._get_citation(spec)

        gate_result = self._check_gates(spec, citation)
        if gate_result is not None:
            return gate_result

        # _check_gates returns a blocking figure when citation is None, so it is a dict here.
        citation = cast(dict, citation)
        resolved = self._resolve_value(spec, nav_value, citation)
        if isinstance(resolved, Figure):
            return resolved
        value, positions, group_name, group_key, member_ids = resolved

        status = self._apply_comparator(spec, value)
        formatted_value = self._apply_formatter(spec, value)
        utilization = self._compute_utilization(spec, value)
        non_ig_ac_names: list[str] = (
            self._fetch_non_ig_ac_names() if spec.selector == "positions_matching" else []
        )
        graph_path = self._build_graph_path(
            spec, positions,
            group_name=group_name, group_key=group_key, member_ids=member_ids,
            non_ig_ac_names=non_ig_ac_names,
        )
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
