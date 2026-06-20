import os
import tempfile
from decimal import Decimal

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(REPO_ROOT, "sample_docs", "sample_holdings.csv")

VALID_CSV_HEADER = (
    "instrument_id,instrument_name,asset_class,issuer_name,issuer_type,"
    "parent_issuer,credit_rating,downgraded_from,market_value_sgd,modified_duration"
)
VALID_CSV_ROW = "SGS-01,Test Bond,SGS,Test Issuer,Sovereign,,AAA,,20000000,5.0"


def _write_csv(content: str) -> str:
    """Write CSV content to a temp file and return its path."""
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
    tf.write(content)
    tf.close()
    return tf.name

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
    from src.ingestion.holdings_parser import parse_holdings
    records = parse_holdings(CSV_PATH)
    for r in records:
        assert isinstance(r.market_value_sgd, Decimal), f"{r.instrument_id} market_value_sgd is not Decimal"
        assert isinstance(r.modified_duration, Decimal), f"{r.instrument_id} modified_duration is not Decimal"

# Fix 7: chunk ID is now 16 hex chars
def test_chunk_id_is_16_char_hex():
    from src.ingestion.holdings_parser import get_csv_chunk_id
    chunk_id = get_csv_chunk_id(CSV_PATH)
    assert len(chunk_id) == 16, f"Expected 16 hex chars, got {len(chunk_id)}: {chunk_id!r}"
    int(chunk_id, 16)  # must be valid hex

def test_total_nav_equals_100_million():
    from src.ingestion.holdings_parser import parse_holdings
    records = parse_holdings(CSV_PATH)
    total = sum(r.market_value_sgd for r in records)
    assert total == Decimal("100000000")


# Fix 1: required-column validation
def test_missing_column_raises_valueerror_with_column_name():
    from src.ingestion.holdings_parser import parse_holdings
    csv_content = "instrument_id,instrument_name,asset_class\nSGS-01,Test,SGS\n"
    path = _write_csv(csv_content)
    try:
        with pytest.raises(ValueError, match="market_value_sgd"):
            parse_holdings(path)
    finally:
        os.unlink(path)


def test_completely_wrong_headers_raises_valueerror():
    from src.ingestion.holdings_parser import parse_holdings
    csv_content = "foo,bar,baz\n1,2,3\n"
    path = _write_csv(csv_content)
    try:
        with pytest.raises(ValueError):
            parse_holdings(path)
    finally:
        os.unlink(path)


# Fix 2: descriptive ValueError for bad numeric cells
def test_non_numeric_market_value_raises_valueerror_with_row_and_field():
    from src.ingestion.holdings_parser import parse_holdings
    csv_content = f"{VALID_CSV_HEADER}\n"
    csv_content += "SGS-01,Test Bond,SGS,Test Issuer,Sovereign,,AAA,,NOT_A_NUMBER,5.0\n"
    path = _write_csv(csv_content)
    try:
        with pytest.raises(ValueError, match=r"row 1") as exc_info:
            parse_holdings(path)
        assert "market_value_sgd" in str(exc_info.value)
    finally:
        os.unlink(path)


def test_non_numeric_duration_raises_valueerror_with_row_and_field():
    from src.ingestion.holdings_parser import parse_holdings
    csv_content = f"{VALID_CSV_HEADER}\n"
    csv_content += "SGS-01,Test Bond,SGS,Test Issuer,Sovereign,,AAA,,20000000,BAD\n"
    path = _write_csv(csv_content)
    try:
        with pytest.raises(ValueError, match=r"row 1") as exc_info:
            parse_holdings(path)
        assert "modified_duration" in str(exc_info.value)
    finally:
        os.unlink(path)


def test_bad_numeric_on_second_row_reports_row_2():
    from src.ingestion.holdings_parser import parse_holdings
    csv_content = f"{VALID_CSV_HEADER}\n"
    csv_content += f"{VALID_CSV_ROW}\n"
    csv_content += "SGS-02,Test Bond 2,SGS,Test Issuer,Sovereign,,AAA,,BAD,5.0\n"
    path = _write_csv(csv_content)
    try:
        with pytest.raises(ValueError, match=r"row 2"):
            parse_holdings(path)
    finally:
        os.unlink(path)


# Fix 3: UTF-8 BOM handling
def test_bom_prefixed_csv_parses_correctly():
    from src.ingestion.holdings_parser import parse_holdings
    csv_content = f"{VALID_CSV_HEADER}\n{VALID_CSV_ROW}\n"
    # Write with BOM
    tf = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    tf.write(b"\xef\xbb\xbf")  # UTF-8 BOM
    tf.write(csv_content.encode("utf-8"))
    tf.close()
    try:
        records = parse_holdings(tf.name)
        assert len(records) == 1
        assert records[0].instrument_id == "SGS-01"
    finally:
        os.unlink(tf.name)


# Fix 4: PositionRecord must be frozen (immutable)
def test_position_record_is_frozen():
    import dataclasses
    from src.ingestion.holdings_parser import PositionRecord
    assert dataclasses.fields(PositionRecord)  # is a dataclass
    with pytest.raises((AttributeError, TypeError)):
        rec = PositionRecord(
            instrument_id="X", instrument_name="X", asset_class="X",
            issuer_name="X", issuer_type="X", parent_issuer=None,
            credit_rating=None, downgraded_from=None,
            market_value_sgd=Decimal("1"), modified_duration=Decimal("1"),
        )
        rec.instrument_id = "mutated"  # must raise if frozen
