"""Deterministic pdfplumber extraction + numeric cleaning helpers.

No LLM imports. All numeric outputs use decimal.Decimal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_SGD_RE = re.compile(r"(\d[\d,]*)")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def normalize_ws(text: str) -> str:
    """Collapse all whitespace (incl. newlines) to single spaces and unescape &amp;."""
    return re.sub(r"\s+", " ", (text or "").replace("&amp;", "&")).strip()


def pct_fraction(cell: str) -> Decimal | None:
    """Return the first percentage in *cell* as a 0-1 fraction, else None."""
    m = _PCT_RE.search(cell or "")
    if not m:
        return None
    return (Decimal(m.group(1)) / Decimal("100")).quantize(Decimal("0.0001"))


def sgd_int(cell: str) -> Decimal | None:
    """Return the first comma-grouped integer in *cell* as Decimal, else None."""
    m = _SGD_RE.search((cell or "").replace("SGD", " "))
    if not m:
        return None
    return Decimal(m.group(1).replace(",", ""))


def year_range(cell: str) -> tuple[Decimal, Decimal] | None:
    """Return (min, max) years from a 'X - Y years' cell, else None."""
    nums = _NUM_RE.findall(cell or "")
    if len(nums) < 2:
        return None
    return Decimal(nums[0]), Decimal(nums[1])


# ---------------------------------------------------------------------------
# Allocation table extractor
# ---------------------------------------------------------------------------

# Canonical asset-class names keyed by a distinctive prefix found in the raw cell.
_ALLOC_CANON: tuple[tuple[str, str], ...] = (
    ("Singapore Government Securities", "Singapore Government Securities"),
    ("MAS Bills", "MAS Bills"),
    ("Investment Grade Corporate Bonds", "Investment Grade Corporate Bonds"),
    ("High Yield Bonds", "High Yield Bonds"),
    ("Foreign Currency Bonds", "Foreign Currency Bonds"),
    ("Structured Credit", "Structured Credit"),
    ("Cash & Cash Equivalents", "Cash & Cash Equivalents"),
)


@dataclass(frozen=True)
class AllocationRow:
    asset_class: str
    min_frac: Decimal | None
    max_frac: Decimal | None
    page: int


def _canon_asset_class(raw: str) -> str | None:
    norm = normalize_ws(raw)
    for prefix, canon in _ALLOC_CANON:
        if norm.startswith(prefix):
            return canon
    return None


# ---------------------------------------------------------------------------
# Risk-metrics table extractor (Section 3.1)
# ---------------------------------------------------------------------------

_RISK_LABELS = (
    "Modified Duration",
    "Portfolio DV01",
    "Value-at-Risk",
    "Expected Shortfall",
    "Interest Rate Sensitivity",
    "Tracking Error",
)


def extract_risk_metrics(pdf) -> dict[str, dict]:
    """Return the 6 Section 3.1 market-risk rows keyed by metric label."""
    out: dict[str, dict] = {}
    for page_idx, page in enumerate(pdf.pages, start=1):
        for table in page.extract_tables():
            for cells in table:
                if not cells:
                    continue
                label = normalize_ws(cells[0] or "")
                match = next((lbl for lbl in _RISK_LABELS if label.startswith(lbl)), None)
                if match is None:
                    continue
                out[match] = {
                    "limit_text": normalize_ws(cells[1] if len(cells) > 1 else ""),
                    "monitoring": normalize_ws(cells[2] if len(cells) > 2 else ""),
                    "breach_action": normalize_ws(cells[3] if len(cells) > 3 else ""),
                    "page": page_idx,
                }
    return out


def duration_bounds(pdf) -> tuple[Decimal, Decimal, int]:
    """Return (min_years, max_years, page) for Modified Duration."""
    m = extract_risk_metrics(pdf)["Modified Duration"]
    rng = year_range(m["limit_text"])
    if rng is None:
        raise ValueError(f"could not parse duration band from {m['limit_text']!r}")
    return rng[0], rng[1], m["page"]


def dv01_cap(pdf) -> tuple[Decimal, int]:
    """Return (cap_sgd, page) for Portfolio DV01."""
    m = extract_risk_metrics(pdf)["Portfolio DV01"]
    cap = sgd_int(m["limit_text"])
    if cap is None:
        raise ValueError(f"could not parse DV01 cap from {m['limit_text']!r}")
    return cap, m["page"]


# ---------------------------------------------------------------------------
# Allocation table extractor
# ---------------------------------------------------------------------------

def extract_allocations(pdf) -> list[AllocationRow]:
    """Merge the Section 2 allocation table across pages 1-2 into 7 canonical rows.

    The table fragments are detected by row shape (4 cells, first cell is a known
    asset class, second cell contains a percentage). Header rows are skipped.
    """
    rows: list[AllocationRow] = []
    for page_idx, page in enumerate(pdf.pages, start=1):
        for table in page.extract_tables():
            for cells in table:
                if not cells or len(cells) < 3:
                    continue
                canon = _canon_asset_class(cells[0] or "")
                if canon is None:
                    continue
                rows.append(
                    AllocationRow(
                        asset_class=canon,
                        min_frac=pct_fraction(cells[1] or ""),
                        max_frac=pct_fraction(cells[2] or ""),
                        page=page_idx,
                    )
                )
    return rows
