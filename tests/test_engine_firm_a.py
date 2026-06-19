"""Engine tests against 13 real holdings with Firm A config."""
import os
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


@pytest.fixture(scope="module")
def firm_a_engine(driver):
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions, load_rules
    from src.ingestion.holdings_parser import parse_holdings
    from src.ingestion.guidelines_parser import parse_guidelines
    from src.compute.config_loader import load_config
    from src.compute.engine import ComputeEngine

    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

    apply_schema(driver)
    csv_path = os.path.join(REPO_ROOT, "sample_docs", "sample_holdings.csv")
    positions = parse_holdings(csv_path)
    load_positions(driver, positions)
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    load_rules(driver, chunks)

    config = load_config(
        os.path.join(REPO_ROOT, "config", "base.yaml"),
        os.path.join(REPO_ROOT, "config", "firm_a.yaml"),
    )
    return ComputeEngine(driver, config)


@pytest.fixture(scope="module")
def firm_a_figures(firm_a_engine):
    return {f.figure: f for f in firm_a_engine.run_all()}


def test_allocation_sgs(firm_a_figures):
    fig = firm_a_figures["allocation_sgs"]
    assert fig.value == "35.0%"
    assert fig.utilization == "58.3%"
    assert fig.status == "OK"
    assert fig.limit == "20–60%"


def test_allocation_mas_bills(firm_a_figures):
    fig = firm_a_figures["allocation_mas_bills"]
    assert fig.value == "8.0%"
    assert fig.utilization == "20.0%"
    assert fig.status == "OK"
    assert fig.limit == "0–40%"


def test_allocation_ig_corp(firm_a_figures):
    fig = firm_a_figures["allocation_ig_corp"]
    assert fig.value == "33.0%"
    assert fig.utilization == "66.0%"
    assert fig.status == "OK"
    assert fig.limit == "10–50%"


def test_allocation_high_yield(firm_a_figures):
    fig = firm_a_figures["allocation_high_yield"]
    assert fig.value == "9.0%"
    assert fig.utilization == "60.0%"
    assert fig.status == "OK"
    assert fig.limit == "0–15%"


def test_allocation_fx_bonds(firm_a_figures):
    fig = firm_a_figures["allocation_fx_bonds"]
    assert fig.value == "5.0%"
    assert fig.utilization == "25.0%"
    assert fig.status == "OK"
    assert fig.limit == "0–20%"


def test_allocation_structured_credit(firm_a_figures):
    fig = firm_a_figures["allocation_structured_credit"]
    assert fig.value == "6.0%"
    assert fig.utilization == "60.0%"
    assert fig.status == "OK"
    assert fig.limit == "0–10%"


def test_allocation_cash_breach(firm_a_figures):
    """Cash is 4.0% against min 5% → BREACH."""
    fig = firm_a_figures["allocation_cash"]
    assert fig.value == "4.0%"
    assert fig.utilization == "n/a"
    assert fig.status == "BREACH"
    assert fig.limit == "min 5%"


def test_aggregate_non_ig_firm_a(firm_a_figures):
    """Non-IG Firm A: HY-01(5M) + HY-02(4M) + SC-01(6M) = 15M = 15.0% (no fallen angels)."""
    fig = firm_a_figures["aggregate_non_ig_exposure"]
    assert fig.value == "15.0%"
    assert fig.utilization == "75.0%"
    assert fig.status == "OK"
    assert fig.limit == "max 20%"


def test_largest_single_corporate_issuer_at_limit(firm_a_figures):
    """COR-01 Changi Logistics = 8M = 8.0% = AT LIMIT (max 8%)."""
    fig = firm_a_figures["largest_single_corporate_issuer"]
    assert fig.value == "8.0%"
    assert fig.utilization == "100.0%"
    assert fig.status == "AT LIMIT"
    assert fig.limit == "max 8%"


def test_largest_gre_issuer_firm_a(firm_a_figures):
    """GRE by issuer: Redhill Power = 7M = 7.0% (max 12%) → OK."""
    fig = firm_a_figures["largest_gre_issuer"]
    assert fig.value == "7.0%"
    assert fig.utilization == "58.3%"
    assert fig.status == "OK"
    assert fig.limit == "max 12%"


def test_liquid_assets_ratio(firm_a_figures):
    """Liquid = SGS-01(20M) + SGS-02(15M) + MAS-01(8M) + CASH-01(4M) = 47M = 47.0%."""
    fig = firm_a_figures["liquid_assets_ratio"]
    assert fig.value == "47.0%"
    assert fig.utilization == "188.0%"
    assert fig.status == "OK"
    assert fig.limit == "min 25%"


def test_portfolio_duration(firm_a_figures):
    """Weighted duration = 387.9M / 100M = 3.879 → 3.88 yrs."""
    fig = firm_a_figures["portfolio_duration"]
    assert fig.value == "3.88 yrs"
    assert fig.utilization == "n/a"
    assert fig.status == "OK"
    assert fig.limit == "2.0–6.5 yrs"


def test_portfolio_dv01(firm_a_figures):
    """DV01 = 387.9M * 0.0001 = 38790."""
    fig = firm_a_figures["portfolio_dv01"]
    assert fig.value == "SGD 38,790 / bp"
    assert fig.utilization == "45.6%"
    assert fig.status == "OK"
    assert fig.limit == "max SGD 85,000 / bp"


def test_figures_have_graph_path(firm_a_figures):
    for fig in firm_a_figures.values():
        assert fig.graph_path, f"Empty graph_path for {fig.figure}"


def test_figures_have_citation(firm_a_figures):
    for fig in firm_a_figures.values():
        assert isinstance(fig.citation, dict), f"citation not a dict for {fig.figure}"


def test_citations_are_populated(firm_a_figures):
    """Citations must be non-empty (chunk_id and source_doc populated) across all rule areas."""
    for fid in ["allocation_sgs", "aggregate_non_ig_exposure", "largest_gre_issuer",
                "liquid_assets_ratio", "portfolio_duration", "portfolio_dv01"]:
        cit = firm_a_figures[fid].citation
        assert cit.get("chunk_id"), f"{fid} has empty chunk_id: {cit}"
        assert cit.get("source_doc"), f"{fid} has empty source_doc: {cit}"


def test_engine_constructor_has_no_llm_param():
    import inspect
    from src.compute.engine import ComputeEngine
    sig = inspect.signature(ComputeEngine.__init__)
    param_names = list(sig.parameters.keys())
    for forbidden in ("llm", "llm_client", "anthropic", "openai"):
        assert forbidden not in param_names, f"LLM param '{forbidden}' found in engine __init__"


def test_non_ig_graph_path_firm_a(firm_a_figures):
    """Firm A non-IG graph_path must EQUAL the guidelines structure exactly (brief example).

    This forces the graph builder to set AssetClass.slug ('high_yield', 'structured_credit')
    and the engine to query a.slug (ORDER BY a.slug) when serializing the CONTRIBUTES_TO
    traversal — not an authored constant. The aggregate stays as 'non_ig' (name == slug).
    """
    fig = firm_a_figures["aggregate_non_ig_exposure"]
    assert fig.graph_path == (
        "(AssetClass:high_yield)-[:CONTRIBUTES_TO]->(Aggregate:non_ig)"
        "<-[:CONTRIBUTES_TO]-(AssetClass:structured_credit)"
    )


def test_different_figures_have_different_citations(firm_a_figures):
    """Each figure should cite its own rule SourceChunk (different chunk_ids where available)."""
    sgs_citation = firm_a_figures["allocation_sgs"].citation
    dv01_citation = firm_a_figures["portfolio_dv01"].citation
    # Both must be non-empty dicts with source_doc
    assert isinstance(sgs_citation, dict)
    assert isinstance(dv01_citation, dict)
    # Different rule types should cite different chunks
    assert sgs_citation["chunk_id"] != dv01_citation["chunk_id"], (
        "Different figures should cite different SourceChunk nodes"
    )


def test_largest_gre_issuer_graph_path_firm_a(firm_a_figures):
    """Firm A GRE graph_path (group_key=issuer) must name 'Redhill Power' directly."""
    fig = firm_a_figures["largest_gre_issuer"]
    assert "Redhill Power" in fig.graph_path, (
        f"Expected 'Redhill Power' in graph_path, got: {fig.graph_path}"
    )


def test_largest_single_corporate_issuer_graph_path_firm_a(firm_a_figures):
    """Single corporate issuer graph_path must name 'Changi Logistics'."""
    fig = firm_a_figures["largest_single_corporate_issuer"]
    assert "Changi Logistics" in fig.graph_path, (
        f"Expected 'Changi Logistics' in graph_path, got: {fig.graph_path}"
    )
