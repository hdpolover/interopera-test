import pdfplumber
from decimal import Decimal

from src.ingestion.pdf_tables import (
    duration_bounds,
    dv01_cap,
    extract_allocations,
    extract_risk_metrics,
    normalize_ws,
    pct_fraction,
    sgd_int,
    year_range,
)


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


_PDF = "sample_docs/sample_fund_guidelines.pdf"


def test_duration_and_dv01_from_risk_table():
    with pdfplumber.open(_PDF) as pdf:
        dmin, dmax, dpage = duration_bounds(pdf)
        cap, cpage = dv01_cap(pdf)
    assert (dmin, dmax) == (Decimal("2.0"), Decimal("6.5"))
    assert cap == Decimal("85000")
    assert dpage == 2 and cpage == 2


def test_extract_risk_metrics_has_six_rows():
    with pdfplumber.open(_PDF) as pdf:
        metrics = extract_risk_metrics(pdf)
    assert "Modified Duration" in metrics
    assert "Portfolio DV01" in metrics
    assert len(metrics) == 6


def test_extract_allocations_merges_all_seven_rows():
    with pdfplumber.open(_PDF) as pdf:
        rows = extract_allocations(pdf)
    by_name = {r.asset_class: r for r in rows}
    assert set(by_name) == {
        "Singapore Government Securities", "MAS Bills",
        "Investment Grade Corporate Bonds", "High Yield Bonds",
        "Foreign Currency Bonds", "Structured Credit", "Cash & Cash Equivalents",
    }
    assert (by_name["Singapore Government Securities"].min_frac,
            by_name["Singapore Government Securities"].max_frac) == (Decimal("0.20"), Decimal("0.60"))
    assert by_name["Singapore Government Securities"].page == 1
    assert by_name["Cash & Cash Equivalents"].page == 2
    assert by_name["Cash & Cash Equivalents"].min_frac == Decimal("0.05")
    assert by_name["Structured Credit"].max_frac == Decimal("0.10")
