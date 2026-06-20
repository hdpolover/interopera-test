from decimal import Decimal
from src.ingestion.pdf_tables import pct_fraction, sgd_int, year_range, normalize_ws


def test_pct_fraction_strips_stray_chars():
    assert pct_fraction(") 20%") == Decimal("0.20")
    assert pct_fraction("60%") == Decimal("0.60")
    assert pct_fraction("5%") == Decimal("0.05")
    assert pct_fraction("no number") is None


def test_sgd_int_handles_currency_artifacts():
    assert sgd_int("£ SGD 85,000 per bp") == Decimal("85000")
    assert sgd_int("SGD 85,000") == Decimal("85000")
    assert sgd_int("nope") is None


def test_year_range_parses_two_values():
    assert year_range("2.0 – 6.5 years") == (Decimal("2.0"), Decimal("6.5"))
    assert year_range("single 3.0") is None


def test_normalize_ws_joins_lines_and_unescapes():
    assert normalize_ws("must not\nexceed   20%") == "must not exceed 20%"
    assert normalize_ws("Cash &amp; Cash") == "Cash & Cash"
