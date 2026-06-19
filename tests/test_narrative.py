"""Narrative writer tests — stub mode (no LLM key required)."""
import pytest
from src.compute.registry import Figure


@pytest.fixture
def firm_a_figures():
    return [
        Figure(figure="allocation_sgs",                  value="35.0%",            utilization="58.3%",    status="OK",       limit="20–60%",            graph_path="", citation={}),
        Figure(figure="allocation_mas_bills",            value="8.0%",             utilization="20.0%",    status="OK",       limit="0–40%",             graph_path="", citation={}),
        Figure(figure="allocation_ig_corp",              value="33.0%",            utilization="66.0%",    status="OK",       limit="10–50%",            graph_path="", citation={}),
        Figure(figure="allocation_high_yield",           value="9.0%",             utilization="60.0%",    status="OK",       limit="0–15%",             graph_path="", citation={}),
        Figure(figure="allocation_fx_bonds",             value="5.0%",             utilization="25.0%",    status="OK",       limit="0–20%",             graph_path="", citation={}),
        Figure(figure="allocation_structured_credit",    value="6.0%",             utilization="60.0%",    status="OK",       limit="0–10%",             graph_path="", citation={}),
        Figure(figure="allocation_cash",                 value="4.0%",             utilization="n/a",      status="BREACH",   limit="min 5%",            graph_path="", citation={}),
        Figure(figure="aggregate_non_ig_exposure",       value="15.0%",            utilization="75.0%",    status="OK",       limit="max 20%",           graph_path="", citation={}),
        Figure(figure="largest_single_corporate_issuer", value="8.0%",             utilization="100.0%",   status="AT LIMIT", limit="max 8%",            graph_path="", citation={}),
        Figure(figure="largest_gre_issuer",              value="7.0%",             utilization="58.3%",    status="OK",       limit="max 12%",           graph_path="", citation={}),
        Figure(figure="liquid_assets_ratio",             value="47.0%",            utilization="188.0%",   status="OK",       limit="min 25%",           graph_path="", citation={}),
        Figure(figure="portfolio_duration",              value="3.88 yrs",         utilization="n/a",      status="OK",       limit="2.0–6.5 yrs",       graph_path="", citation={}),
        Figure(figure="portfolio_dv01",                  value="SGD 38,790 / bp",  utilization="45.6%",    status="OK",       limit="max SGD 85,000 / bp", graph_path="", citation={}),
    ]


def test_stub_narrative_returns_string(firm_a_figures):
    from src.narrative.narrator import Narrator
    narrator = Narrator(api_key=None)
    narrative = narrator.write_narrative(firm_a_figures, firm_id="firm_a")
    assert isinstance(narrative, str)
    assert len(narrative) > 50


def test_stub_narrative_contains_sgs_value(firm_a_figures):
    from src.narrative.narrator import Narrator
    narrator = Narrator(api_key=None)
    narrative = narrator.write_narrative(firm_a_figures, firm_id="firm_a")
    assert "35.0%" in narrative


def test_stub_narrative_contains_cash_breach(firm_a_figures):
    from src.narrative.narrator import Narrator
    narrator = Narrator(api_key=None)
    narrative = narrator.write_narrative(firm_a_figures, firm_id="firm_a")
    assert "4.0%" in narrative
    assert "BREACH" in narrative or "breach" in narrative.lower()


def test_stub_narrative_contains_dv01(firm_a_figures):
    from src.narrative.narrator import Narrator
    narrator = Narrator(api_key=None)
    narrative = narrator.write_narrative(firm_a_figures, firm_id="firm_a")
    assert "38,790" in narrative or "38790" in narrative


def test_stub_narrative_passes_firewall(firm_a_figures):
    from src.narrative.narrator import Narrator
    from src.firewall.checker import check_firewall
    narrator = Narrator(api_key=None)
    narrative = narrator.write_narrative(firm_a_figures, firm_id="firm_a")
    result = check_firewall(narrative, firm_a_figures)
    assert result.passed is True, (
        f"Stub narrative failed firewall. Offending: {result.offending_numbers}"
    )


def test_stub_narrative_is_deterministic(firm_a_figures):
    from src.narrative.narrator import Narrator
    narrator = Narrator(api_key=None)
    n1 = narrator.write_narrative(firm_a_figures, firm_id="firm_a")
    n2 = narrator.write_narrative(firm_a_figures, firm_id="firm_a")
    assert n1 == n2
