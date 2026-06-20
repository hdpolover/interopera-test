"""Shared constants for the compliance graph package."""
from __future__ import annotations

# Maps each AssetClass display name to its URL-safe slug used in graph_path
# serialization and AssetClass node properties.
ASSET_CLASS_SLUG: dict[str, str] = {
    "Singapore Government Securities": "sgs",
    "MAS Bills": "mas_bills",
    "Investment Grade Corporate Bonds": "ig_corp",
    "High Yield Bonds": "high_yield",
    "Foreign Currency Bonds": "fx_bonds",
    "Structured Credit": "structured_credit",
    "Cash & Cash Equivalents": "cash",
}
