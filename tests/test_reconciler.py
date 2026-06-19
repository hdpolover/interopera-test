"""Reconciler tests — Firm A exact match and Firm B config-only."""
import os
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FIRM_A_FIGURES_DATA = [
    ("allocation_sgs",                  "35.0%", "OK"),
    ("allocation_mas_bills",            "8.0%",  "OK"),
    ("allocation_ig_corp",              "33.0%", "OK"),
    ("allocation_high_yield",           "9.0%",  "OK"),
    ("allocation_fx_bonds",             "5.0%",  "OK"),
    ("allocation_structured_credit",    "6.0%",  "OK"),
    ("allocation_cash",                 "4.0%",  "BREACH"),
    ("aggregate_non_ig_exposure",       "15.0%", "OK"),
    ("largest_single_corporate_issuer", "8.0%",  "AT LIMIT"),
    ("largest_gre_issuer",              "7.0%",  "OK"),
    ("liquid_assets_ratio",             "47.0%", "OK"),
    ("portfolio_duration",              "3.88 yrs", "OK"),
    ("portfolio_dv01",                  "SGD 38,790 / bp", "OK"),
]


@pytest.fixture
def firm_a_figures():
    from src.compute.registry import Figure
    return [
        Figure(figure=fid, value=val, status=stat,
               utilization="n/a", limit="", graph_path="", citation={})
        for fid, val, stat in FIRM_A_FIGURES_DATA
    ]


@pytest.fixture
def firm_a_expected():
    """Build expected dict matching firm_A_answer_key.xlsx format."""
    return {fid: {"value": val, "utilization": "n/a", "status": stat} for fid, val, stat in FIRM_A_FIGURES_DATA}


def test_reconcile_all_pass_firm_a(firm_a_figures, firm_a_expected):
    from src.reconcile.reconciler import reconcile
    results = reconcile(firm_a_figures, firm_a_expected)
    assert len(results) == 13
    failed = [r for r in results if not r.passed]
    assert not failed, f"Unexpected failures: {[(r.figure, r.delta) for r in failed]}"


def test_reconcile_detects_wrong_value(firm_a_figures, firm_a_expected):
    from src.reconcile.reconciler import reconcile
    wrong_expected = dict(firm_a_expected)
    wrong_expected["allocation_sgs"] = {"value": "36.0%", "status": "OK"}
    results = reconcile(firm_a_figures, wrong_expected)
    sgs_result = next(r for r in results if r.figure == "allocation_sgs")
    assert sgs_result.passed is False
    assert "35.0%" in sgs_result.delta
    assert "36.0%" in sgs_result.delta


def test_reconcile_detects_wrong_status(firm_a_figures, firm_a_expected):
    from src.reconcile.reconciler import reconcile
    wrong_expected = dict(firm_a_expected)
    wrong_expected["allocation_cash"] = {"value": "4.0%", "status": "OK"}  # wrong status
    results = reconcile(firm_a_figures, wrong_expected)
    cash_result = next(r for r in results if r.figure == "allocation_cash")
    assert cash_result.passed is False


def test_parse_expected_yaml_firm_b():
    from src.reconcile.reconciler import parse_expected_yaml
    yaml_path = os.path.join(REPO_ROOT, "config", "firm_b_expected.yaml")
    expected = parse_expected_yaml(yaml_path)
    assert len(expected) == 13
    assert expected["aggregate_non_ig_exposure"]["value"] == "21.0%"
    assert expected["aggregate_non_ig_exposure"]["utilization"] == "10500 bps"
    assert expected["aggregate_non_ig_exposure"]["status"] == "BREACH"
    assert expected["largest_gre_issuer"]["value"] == "13.0%"
    assert expected["largest_gre_issuer"]["utilization"] == "10833 bps"
    assert expected["largest_gre_issuer"]["status"] == "BREACH"
    assert expected["portfolio_duration"]["value"] == "3.88 yrs"
    assert expected["portfolio_duration"]["utilization"] == "n/a"


def test_reconcile_result_dataclass_fields():
    from src.reconcile.reconciler import ReconcileResult
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(ReconcileResult)}
    assert field_names == {
        "figure", "expected_value", "computed_value",
        "expected_utilization", "computed_utilization",
        "expected_status", "computed_status", "delta", "passed"
    }


def test_parse_answer_key_xlsx_firm_a():
    """Test parsing firm_A_answer_key.xlsx if it exists."""
    xlsx_path = os.path.join(REPO_ROOT, "sample_docs", "firm_A_answer_key.xlsx")
    if not os.path.exists(xlsx_path):
        pytest.skip("firm_A_answer_key.xlsx not present")
    from src.reconcile.reconciler import parse_answer_key_xlsx
    expected = parse_answer_key_xlsx(xlsx_path)
    assert len(expected) == 13
    assert expected["allocation_sgs"]["value"] == "35.0%"
    assert expected["allocation_sgs"]["utilization"] == "58.3%"
    assert expected["allocation_cash"]["utilization"] == "n/a"
    assert expected["portfolio_duration"]["utilization"] == "n/a"
