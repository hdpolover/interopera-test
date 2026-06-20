"""Figure and FigureSpec dataclasses, plus the FIGURE_REGISTRY of all 13 specs."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Figure:
    figure: str
    value: str
    utilization: str
    status: str
    limit: str
    graph_path: str
    citation: dict


@dataclass(frozen=True)
class FigureSpec:
    id: str
    selector: str
    aggregator: str
    comparator: str
    formatter: str
    limit_display: str
    predicate: dict = field(default_factory=dict)
    limit_ref: str = ""
    utilization_basis: str = "none"


FIGURE_REGISTRY: tuple[FigureSpec, ...] = (
    FigureSpec(
        id="allocation_sgs",
        selector="positions_in_asset_class",
        predicate={"asset_class": "Singapore Government Securities"},
        aggregator="sum_pct",
        limit_ref="allocation_sgs_limit",
        comparator="within_min_max",
        formatter="percent_1dp",
        limit_display="20–60%",
        utilization_basis="max",
    ),
    FigureSpec(
        id="allocation_mas_bills",
        selector="positions_in_asset_class",
        predicate={"asset_class": "MAS Bills"},
        aggregator="sum_pct",
        limit_ref="allocation_mas_limit",
        comparator="within_min_max",
        formatter="percent_1dp",
        limit_display="0–40%",
        utilization_basis="max",
    ),
    FigureSpec(
        id="allocation_ig_corp",
        selector="positions_in_asset_class",
        predicate={"asset_class": "Investment Grade Corporate Bonds"},
        aggregator="sum_pct",
        limit_ref="allocation_ig_limit",
        comparator="within_min_max",
        formatter="percent_1dp",
        limit_display="10–50%",
        utilization_basis="max",
    ),
    FigureSpec(
        id="allocation_high_yield",
        selector="positions_in_asset_class",
        predicate={"asset_class": "High Yield Bonds"},
        aggregator="sum_pct",
        limit_ref="allocation_hy_limit",
        comparator="within_min_max",
        formatter="percent_1dp",
        limit_display="0–15%",
        utilization_basis="max",
    ),
    FigureSpec(
        id="allocation_fx_bonds",
        selector="positions_in_asset_class",
        predicate={"asset_class": "Foreign Currency Bonds"},
        aggregator="sum_pct",
        limit_ref="allocation_fx_limit",
        comparator="within_min_max",
        formatter="percent_1dp",
        limit_display="0–20%",
        utilization_basis="max",
    ),
    FigureSpec(
        id="allocation_structured_credit",
        selector="positions_in_asset_class",
        predicate={"asset_class": "Structured Credit"},
        aggregator="sum_pct",
        limit_ref="allocation_sc_limit",
        comparator="within_min_max",
        formatter="percent_1dp",
        limit_display="0–10%",
        utilization_basis="max",
    ),
    FigureSpec(
        id="allocation_cash",
        selector="positions_in_asset_class",
        predicate={"asset_class": "Cash & Cash Equivalents"},
        aggregator="sum_pct",
        limit_ref="allocation_cash_limit",
        comparator="min_floor",
        formatter="percent_1dp",
        limit_display="min 5%",
        utilization_basis="none",
    ),
    FigureSpec(
        id="aggregate_non_ig_exposure",
        selector="positions_matching",
        predicate={"asset_class_in": ["High Yield Bonds", "Structured Credit"],
                   "fallen_angel_config_key": "non_ig.include_fallen_angels"},
        aggregator="sum_pct",
        limit_ref="non_ig_cap_limit",
        comparator="max_cap",
        formatter="percent_1dp",
        limit_display="max 20%",
        utilization_basis="cap",
    ),
    FigureSpec(
        id="largest_single_corporate_issuer",
        selector="positions_by_issuer",
        predicate={"group_key": "issuer", "issuer_type_filter": "corporate"},
        aggregator="max_group_pct",
        limit_ref="corporate_issuer_limit",
        comparator="max_cap",
        formatter="percent_1dp",
        limit_display="max 8%",
        utilization_basis="cap",
    ),
    FigureSpec(
        id="largest_gre_issuer",
        selector="positions_by_issuer",
        predicate={"group_key_config_key": "concentration.gre.group_key",
                   "issuer_type_filter": "GRE"},
        aggregator="max_group_pct",
        limit_ref="gre_issuer_limit",
        comparator="max_cap",
        formatter="percent_1dp",
        limit_display="max 12%",
        utilization_basis="cap",
    ),
    FigureSpec(
        id="liquid_assets_ratio",
        selector="liquid_positions",
        predicate={},
        aggregator="sum_pct",
        limit_ref="liquidity_limit",
        comparator="min_floor",
        formatter="percent_1dp",
        limit_display="min 25%",
        utilization_basis="floor",
    ),
    FigureSpec(
        id="portfolio_duration",
        selector="all_positions",
        predicate={},
        aggregator="weighted_avg_duration",
        limit_ref="duration_limit",
        comparator="within_min_max",
        formatter="years_2dp",
        limit_display="2.0–6.5 yrs",
        utilization_basis="none",
    ),
    FigureSpec(
        id="portfolio_dv01",
        selector="all_positions",
        predicate={},
        aggregator="dv01",
        limit_ref="dv01_limit",
        comparator="max_cap",
        formatter="sgd_dv01",
        limit_display="max SGD 85,000 / bp",
        utilization_basis="cap",
    ),
)
