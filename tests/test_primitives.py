"""Tests for compute primitives. All math uses Decimal for exact assertions."""
import pytest
from decimal import Decimal


# The 13 positions as dicts (matching what graph queries return)
POSITIONS = [
    {"instrument_id": "CASH-01", "market_value_sgd": "4000000",  "modified_duration": "0.0",  "asset_class": "Cash & Cash Equivalents"},
    {"instrument_id": "COR-01",  "market_value_sgd": "8000000",  "modified_duration": "4.5",  "asset_class": "Investment Grade Corporate Bonds"},
    {"instrument_id": "COR-02",  "market_value_sgd": "6000000",  "modified_duration": "4.5",  "asset_class": "Investment Grade Corporate Bonds"},
    {"instrument_id": "COR-03",  "market_value_sgd": "7000000",  "modified_duration": "4.5",  "asset_class": "Investment Grade Corporate Bonds"},
    {"instrument_id": "COR-04",  "market_value_sgd": "6000000",  "modified_duration": "4.5",  "asset_class": "Investment Grade Corporate Bonds"},
    {"instrument_id": "COR-05",  "market_value_sgd": "6000000",  "modified_duration": "4.5",  "asset_class": "Investment Grade Corporate Bonds"},
    {"instrument_id": "FX-01",   "market_value_sgd": "5000000",  "modified_duration": "4.0",  "asset_class": "Foreign Currency Bonds"},
    {"instrument_id": "HY-01",   "market_value_sgd": "5000000",  "modified_duration": "3.0",  "asset_class": "High Yield Bonds"},
    {"instrument_id": "HY-02",   "market_value_sgd": "4000000",  "modified_duration": "3.0",  "asset_class": "High Yield Bonds"},
    {"instrument_id": "MAS-01",  "market_value_sgd": "8000000",  "modified_duration": "0.3",  "asset_class": "MAS Bills"},
    {"instrument_id": "SC-01",   "market_value_sgd": "6000000",  "modified_duration": "2.5",  "asset_class": "Structured Credit"},
    {"instrument_id": "SGS-01",  "market_value_sgd": "20000000", "modified_duration": "5.0",  "asset_class": "Singapore Government Securities"},
    {"instrument_id": "SGS-02",  "market_value_sgd": "15000000", "modified_duration": "5.0",  "asset_class": "Singapore Government Securities"},
]

SGS_POSITIONS = [p for p in POSITIONS if p["asset_class"] == "Singapore Government Securities"]
HY_SC_POSITIONS = [p for p in POSITIONS if p["asset_class"] in ("High Yield Bonds", "Structured Credit")]


def test_nav_equals_100_million():
    from src.compute.primitives import nav
    result = nav(POSITIONS)
    assert result == Decimal("100000000")


def test_nav_returns_decimal():
    from src.compute.primitives import nav
    result = nav(POSITIONS)
    assert isinstance(result, Decimal)


def test_sum_pct_sgs_is_35_percent():
    from src.compute.primitives import nav, sum_pct
    portfolio_nav = nav(POSITIONS)
    result = sum_pct(SGS_POSITIONS, portfolio_nav)
    assert result == Decimal("0.3500")


def test_sum_pct_mas_is_8_percent():
    from src.compute.primitives import nav, sum_pct
    portfolio_nav = nav(POSITIONS)
    mas = [p for p in POSITIONS if p["asset_class"] == "MAS Bills"]
    result = sum_pct(mas, portfolio_nav)
    assert result == Decimal("0.0800")


def test_sum_pct_cash_is_4_percent():
    from src.compute.primitives import nav, sum_pct
    portfolio_nav = nav(POSITIONS)
    cash = [p for p in POSITIONS if p["asset_class"] == "Cash & Cash Equivalents"]
    result = sum_pct(cash, portfolio_nav)
    assert result == Decimal("0.0400")


def test_weighted_avg_duration():
    """
    Weighted duration = sum(mv * dur) / nav
    = (20M*5.0 + 15M*5.0 + 8M*0.3 + 8M*4.5 + 6M*4.5 + 7M*4.5 + 6M*4.5
       + 6M*4.5 + 5M*3.0 + 4M*3.0 + 5M*4.0 + 6M*2.5 + 4M*0.0) / 100M
    = 387900000 / 100000000 = 3.879
    Rounded ROUND_HALF_UP 4dp = 3.8790
    """
    from src.compute.primitives import nav, weighted_avg_duration
    portfolio_nav = nav(POSITIONS)
    result = weighted_avg_duration(POSITIONS, portfolio_nav)
    assert result == Decimal("3.8790")


def test_dv01():
    """
    DV01 = sum(mv * dur) * 0.0001 = 387900000 * 0.0001 = 38790
    Rounded to 0 decimal places = 38790
    """
    from src.compute.primitives import nav, dv01
    portfolio_nav = nav(POSITIONS)
    result = dv01(POSITIONS, portfolio_nav)
    assert result == Decimal("38790")


def test_max_group_pct_issuer():
    """Changi Logistics has 8M = 8% — highest single issuer."""
    from src.compute.primitives import nav, max_group_pct
    portfolio_nav = nav(POSITIONS)
    # Groups by issuer_name
    groups: dict = {}
    for p in POSITIONS:
        issuer = p.get("issuer_name", p["instrument_id"])
        groups.setdefault(issuer, []).append(p)
    # inject issuer_name
    full_positions = [
        {"instrument_id": "COR-01", "issuer_name": "Changi Logistics Pte Ltd",
         "market_value_sgd": "8000000", "modified_duration": "4.5"},
    ]
    groups2 = {"Changi Logistics Pte Ltd": full_positions}
    name, pct = max_group_pct(groups2, portfolio_nav)
    assert name == "Changi Logistics Pte Ltd"
    assert pct == Decimal("0.0800")


def test_within_min_max_ok():
    from src.compute.primitives import within_min_max
    assert within_min_max(Decimal("35"), Decimal("20"), Decimal("60")) == "OK"


def test_within_min_max_breach_below():
    from src.compute.primitives import within_min_max
    assert within_min_max(Decimal("4"), Decimal("5"), Decimal("100")) == "BREACH"


def test_within_min_max_breach_above():
    from src.compute.primitives import within_min_max
    assert within_min_max(Decimal("101"), Decimal("0"), Decimal("100")) == "BREACH"


def test_within_min_max_at_limit_min():
    from src.compute.primitives import within_min_max
    assert within_min_max(Decimal("20"), Decimal("20"), Decimal("60")) == "OK"


def test_max_cap_ok():
    from src.compute.primitives import max_cap
    assert max_cap(Decimal("7"), Decimal("8")) == "OK"


def test_max_cap_at_limit():
    from src.compute.primitives import max_cap
    assert max_cap(Decimal("8"), Decimal("8")) == "AT LIMIT"


def test_max_cap_breach():
    from src.compute.primitives import max_cap
    assert max_cap(Decimal("9"), Decimal("8")) == "BREACH"


def test_min_floor_ok():
    from src.compute.primitives import min_floor
    assert min_floor(Decimal("47"), Decimal("25")) == "OK"


def test_min_floor_breach():
    from src.compute.primitives import min_floor
    assert min_floor(Decimal("4"), Decimal("5")) == "BREACH"


def test_min_floor_at_limit():
    from src.compute.primitives import min_floor
    assert min_floor(Decimal("25"), Decimal("25")) == "OK"


def test_percent_1dp():
    from src.compute.primitives import percent_1dp
    assert percent_1dp(Decimal("0.35")) == "35.0%"
    assert percent_1dp(Decimal("0.04")) == "4.0%"
    assert percent_1dp(Decimal("0.15")) == "15.0%"
    assert percent_1dp(Decimal("0.08")) == "8.0%"


def test_truncated_bps():
    from src.compute.primitives import truncated_bps
    # 58.333...% → floor(5833.3) = 5833
    assert truncated_bps(Decimal("0.58333")) == "5833 bps"
    assert truncated_bps(Decimal("0.35")) == "3500 bps"
    assert truncated_bps(Decimal("0.15")) == "1500 bps"


def test_years_2dp():
    from src.compute.primitives import years_2dp
    assert years_2dp(Decimal("3.8790")) == "3.88 yrs"
    assert years_2dp(Decimal("3.879")) == "3.88 yrs"
    assert years_2dp(Decimal("2.0")) == "2.00 yrs"


def test_sgd_dv01():
    from src.compute.primitives import sgd_dv01
    assert sgd_dv01(Decimal("38790")) == "SGD 38,790 / bp"
    assert sgd_dv01(Decimal("85000")) == "SGD 85,000 / bp"
    assert sgd_dv01(Decimal("1000")) == "SGD 1,000 / bp"


def test_no_llm_imports_in_primitives():
    """Static import gate: primitives.py must not import LLM clients."""
    import ast, os
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, "src", "compute", "primitives.py")
    with open(path) as f:
        tree = ast.parse(f.read())
    forbidden = {"anthropic", "openai", "httpx", "requests"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for name in names:
                top = name.split(".")[0]
                assert top not in forbidden, f"Forbidden import '{top}' found in primitives.py"
