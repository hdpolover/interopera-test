"""Deterministic pdfplumber extraction + numeric cleaning helpers.

No LLM imports. All numeric outputs use decimal.Decimal.
"""
from __future__ import annotations

import re
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
