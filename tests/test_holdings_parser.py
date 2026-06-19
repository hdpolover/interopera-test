import os
import pytest
from decimal import Decimal

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(REPO_ROOT, "sample_docs", "sample_holdings.csv")

def test_parse_holdings_returns_13_records():
    from src.ingestion.holdings_parser import parse_holdings
    records = parse_holdings(CSV_PATH)
    assert len(records) == 13

def test_parse_holdings_sorted_by_instrument_id():
    from src.ingestion.holdings_parser import parse_holdings
    records = parse_holdings(CSV_PATH)
    ids = [r.instrument_id for r in records]
    assert ids == sorted(ids), f"Not sorted: {ids}"

def test_sgs_01_market_value():
    from src.ingestion.holdings_parser import parse_holdings
    records = parse_holdings(CSV_PATH)
    sgs01 = next(r for r in records if r.instrument_id == "SGS-01")
    assert sgs01.market_value_sgd == Decimal("20000000")

def test_sgs_01_duration():
    from src.ingestion.holdings_parser import parse_holdings
    records = parse_holdings(CSV_PATH)
    sgs01 = next(r for r in records if r.instrument_id == "SGS-01")
    assert sgs01.modified_duration == Decimal("5.0")

def test_cash_01_market_value():
    from src.ingestion.holdings_parser import parse_holdings
    records = parse_holdings(CSV_PATH)
    cash = next(r for r in records if r.instrument_id == "CASH-01")
    assert cash.market_value_sgd == Decimal("4000000")
    assert cash.modified_duration == Decimal("0.0")

def test_cor_05_has_downgraded_from():
    from src.ingestion.holdings_parser import parse_holdings
    records = parse_holdings(CSV_PATH)
    cor05 = next(r for r in records if r.instrument_id == "COR-05")
    assert cor05.downgraded_from == "BBB-"
    assert cor05.credit_rating == "BB"

def test_cor_03_is_gre_with_parent():
    from src.ingestion.holdings_parser import parse_holdings
    records = parse_holdings(CSV_PATH)
    cor03 = next(r for r in records if r.instrument_id == "COR-03")
    assert cor03.issuer_type == "GRE"
    assert cor03.parent_issuer == "Redhill Holdings"

def test_market_value_is_decimal_not_float():
    from src.ingestion.holdings_parser import parse_holdings, PositionRecord
    records = parse_holdings(CSV_PATH)
    for r in records:
        assert isinstance(r.market_value_sgd, Decimal), f"{r.instrument_id} market_value_sgd is not Decimal"
        assert isinstance(r.modified_duration, Decimal), f"{r.instrument_id} modified_duration is not Decimal"

def test_chunk_id_is_8_char_hex():
    from src.ingestion.holdings_parser import parse_holdings
    records = parse_holdings(CSV_PATH)
    # chunk_id is on the parser module level, derived from CSV content
    from src.ingestion.holdings_parser import get_csv_chunk_id
    chunk_id = get_csv_chunk_id(CSV_PATH)
    assert len(chunk_id) == 8
    int(chunk_id, 16)  # must be valid hex

def test_total_nav_equals_100_million():
    from src.ingestion.holdings_parser import parse_holdings
    records = parse_holdings(CSV_PATH)
    total = sum(r.market_value_sgd for r in records)
    assert total == Decimal("100000000")
