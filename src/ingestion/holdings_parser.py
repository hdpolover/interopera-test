"""Parse holdings CSV into PositionRecord dataclasses."""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {
        "instrument_id",
        "instrument_name",
        "asset_class",
        "issuer_name",
        "issuer_type",
        "parent_issuer",
        "credit_rating",
        "downgraded_from",
        "market_value_sgd",
        "modified_duration",
    }
)


@dataclass(frozen=True)
class PositionRecord:
    instrument_id: str
    instrument_name: str
    asset_class: str
    issuer_name: str
    issuer_type: str
    parent_issuer: str | None
    credit_rating: str | None
    downgraded_from: str | None
    market_value_sgd: Decimal
    modified_duration: Decimal


def get_csv_chunk_id(csv_path: str) -> str:
    """Return sha256 of CSV file content, first 16 hex chars."""
    with open(csv_path, "rb") as f:
        content = f.read()
    return hashlib.sha256(content).hexdigest()[:16]


def _to_decimal(raw: str, field: str, row_num: int) -> Decimal:
    """Convert raw string to Decimal, raising ValueError with row and field context on failure."""
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"row {row_num}: invalid numeric value for {field}: {raw!r}")


def _validate_columns(fieldnames: Sequence[str] | None) -> None:
    """Raise ValueError listing missing columns when the CSV header is incomplete."""
    actual = frozenset(fieldnames or [])
    missing = REQUIRED_COLUMNS - actual
    if missing:
        raise ValueError(
            f"CSV is missing required columns: {', '.join(sorted(missing))}"
        )


def parse_holdings(csv_path: str) -> list[PositionRecord]:
    """Parse holdings CSV and return list of PositionRecord sorted by instrument_id."""
    records: list[PositionRecord] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        _validate_columns(reader.fieldnames)
        for row_num, row in enumerate(reader, start=1):
            records.append(
                PositionRecord(
                    instrument_id=row["instrument_id"].strip(),
                    instrument_name=row["instrument_name"].strip(),
                    asset_class=row["asset_class"].strip(),
                    issuer_name=row["issuer_name"].strip(),
                    issuer_type=row["issuer_type"].strip(),
                    parent_issuer=row["parent_issuer"].strip() or None,
                    credit_rating=row["credit_rating"].strip() or None,
                    downgraded_from=row["downgraded_from"].strip() or None,
                    market_value_sgd=_to_decimal(
                        row["market_value_sgd"].strip(), "market_value_sgd", row_num
                    ),
                    modified_duration=_to_decimal(
                        row["modified_duration"].strip(), "modified_duration", row_num
                    ),
                )
            )
    return sorted(records, key=lambda r: r.instrument_id)
