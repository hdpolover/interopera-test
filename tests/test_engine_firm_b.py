"""Firm B engine tests: fallen angels + parent_issuer GRE + truncated_bps format."""
import os
import subprocess
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
def firm_b_engine(driver):
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
        os.path.join(REPO_ROOT, "config", "firm_b.yaml"),
    )
    return ComputeEngine(driver, config)


@pytest.fixture(scope="module")
def firm_b_figures(firm_b_engine):
    return {f.figure: f for f in firm_b_engine.run_all()}


def test_aggregate_non_ig_firm_b_breach(firm_b_figures):
    """Firm B: HY(9M) + SC(6M) + COR-05 fallen angel(6M) = 21M = 21.0% → BREACH."""
    fig = firm_b_figures["aggregate_non_ig_exposure"]
    assert fig.value == "21.0%"
    assert fig.utilization == "10500 bps"
    assert fig.status == "BREACH"


def test_largest_gre_firm_b_breach(firm_b_figures):
    """Firm B: Redhill Holdings = Redhill Power(7M) + Redhill Transport(6M) = 13M = 13.0% → BREACH."""
    fig = firm_b_figures["largest_gre_issuer"]
    assert fig.value == "13.0%"
    assert fig.utilization == "10833 bps"
    assert fig.status == "BREACH"


def test_allocation_sgs_same_in_firm_b(firm_b_figures):
    """SGS allocation is not affected by firm config — still 35.0%."""
    fig = firm_b_figures["allocation_sgs"]
    assert fig.value == "35.0%"
    assert fig.utilization == "5833 bps"
    assert fig.status == "OK"


def test_allocation_cash_still_breach_in_firm_b(firm_b_figures):
    fig = firm_b_figures["allocation_cash"]
    assert fig.value == "4.0%"
    assert fig.utilization == "n/a"
    assert fig.status == "BREACH"  # still 4% < 5%


def test_portfolio_duration_same_in_firm_b(firm_b_figures):
    """Duration uses years_2dp formatter regardless of utilization_format."""
    fig = firm_b_figures["portfolio_duration"]
    assert fig.value == "3.88 yrs"  # duration always in years
    assert fig.utilization == "n/a"
    assert fig.status == "OK"


def test_portfolio_dv01_same_in_firm_b(firm_b_figures):
    """DV01 uses sgd_dv01 formatter regardless of utilization_format."""
    fig = firm_b_figures["portfolio_dv01"]
    assert fig.value == "SGD 38,790 / bp"
    assert fig.utilization == "4563 bps"
    assert fig.status == "OK"


def test_no_firm_b_hardcoding_in_compute():
    """grep check: no 'firm_b' or 'firm b' in src/compute/ source code."""
    compute_dir = os.path.join(REPO_ROOT, "src", "compute")
    result = subprocess.run(
        ["grep", "-ri", r"firm_b\|firm b", compute_dir],
        capture_output=True,
        text=True,
    )
    # grep returns exit 0 if found, exit 1 if not found
    assert result.returncode != 0, (
        f"Found firm-specific hardcoding in src/compute/:\n{result.stdout}"
    )
