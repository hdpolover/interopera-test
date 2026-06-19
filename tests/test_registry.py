import pytest


def test_figure_registry_has_13_entries():
    from src.compute.registry import FIGURE_REGISTRY
    assert len(FIGURE_REGISTRY) == 13


def test_figure_registry_allocation_sgs():
    from src.compute.registry import FIGURE_REGISTRY
    spec = next(s for s in FIGURE_REGISTRY if s.id == "allocation_sgs")
    assert spec.selector == "positions_in_asset_class"
    assert spec.aggregator == "sum_pct"
    assert spec.formatter == "percent_1dp"


def test_figure_registry_aggregate_non_ig():
    from src.compute.registry import FIGURE_REGISTRY
    spec = next(s for s in FIGURE_REGISTRY if s.id == "aggregate_non_ig_exposure")
    assert spec.selector == "positions_matching"
    assert spec.comparator == "max_cap"


def test_figure_registry_largest_gre_issuer():
    from src.compute.registry import FIGURE_REGISTRY
    spec = next(s for s in FIGURE_REGISTRY if s.id == "largest_gre_issuer")
    assert spec.selector == "positions_by_issuer"


def test_figure_registry_all_ids_unique():
    from src.compute.registry import FIGURE_REGISTRY
    ids = [s.id for s in FIGURE_REGISTRY]
    assert len(ids) == len(set(ids))


def test_figure_dataclass_fields():
    from src.compute.registry import Figure
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(Figure)}
    assert field_names == {"figure", "value", "utilization", "status", "limit", "graph_path", "citation"}


def test_figure_spec_dataclass_fields():
    from src.compute.registry import FigureSpec
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(FigureSpec)}
    assert field_names == {"id", "selector", "predicate", "aggregator", "limit_ref",
                           "comparator", "formatter", "limit_display", "utilization_basis"}


def test_all_13_figure_ids_present():
    from src.compute.registry import FIGURE_REGISTRY
    ids = {s.id for s in FIGURE_REGISTRY}
    expected = {
        "allocation_sgs", "allocation_mas_bills", "allocation_ig_corp",
        "allocation_high_yield", "allocation_fx_bonds", "allocation_structured_credit",
        "allocation_cash", "aggregate_non_ig_exposure", "largest_single_corporate_issuer",
        "largest_gre_issuer", "liquid_assets_ratio", "portfolio_duration", "portfolio_dv01",
    }
    assert ids == expected
