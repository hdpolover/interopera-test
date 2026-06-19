"""Parse holdings CSV into PositionRecord dataclasses."""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass
class PositionRecord:
    instrument_id: str
    instrument_name: str
    asset_class: str
    issuer_name: str
    issuer_type: str
    parent_issuer: Optional[str]
    credit_rating: Optional[str]
    downgraded_from: Optional[str]
    market_value_sgd: Decimal
    modified_duration: Decimal


def get_csv_chunk_id(csv_path: str) -> str:
    """Return sha256 of CSV file content, first 8 hex chars."""
    with open(csv_path, "rb") as f:
        content = f.read()
    return hashlib.sha256(content).hexdigest()[:8]


def parse_holdings(csv_path: str) -> list[PositionRecord]:
    """Parse holdings CSV and return list of PositionRecord sorted by instrument_id."""
    records: list[PositionRecord] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
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
                    market_value_sgd=Decimal(row["market_value_sgd"].strip()),
                    modified_duration=Decimal(row["modified_duration"].strip()),
                )
            )
    return sorted(records, key=lambda r: r.instrument_id)
