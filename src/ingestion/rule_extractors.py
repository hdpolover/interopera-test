# src/ingestion/rule_extractors.py
"""Deterministic prose-rule extraction from the guidelines PDF. No LLM imports."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from src.ingestion.pdf_tables import normalize_ws

_HIGH = 0.92   # prose value isolated by a unique, specific anchor phrase
_LOW = 0.80    # value disambiguated by a single keyword in a crowded paragraph


@dataclass(frozen=True)
class ProseRule:
    value: Decimal
    confidence: float
    page: int
    passage: str


# Each rule: (key, anchored regex on normalized page text, confidence).
_PATTERNS: tuple[tuple[str, "re.Pattern[str]", float], ...] = (
    ("non_ig", re.compile(r"non-investment-grade instruments[^.]*?exceed\s*(\d+)%"), _HIGH),
    ("corporate", re.compile(r"no single issuer[^.]*?than\s*(\d+)%\s*of NAV", re.IGNORECASE), _HIGH),
    ("gre", re.compile(r"capped at\s*(\d+)%\s*per issuer", re.IGNORECASE), _HIGH),
    ("liquidity", re.compile(r"minimum of\s*(\d+)%\s*of NAV", re.IGNORECASE), _HIGH),
    ("counterparty", re.compile(r"counterparty must not exceed\s*(\d+)%\s*of NAV", re.IGNORECASE), _LOW),
)


def _passage_for(text: str, match: "re.Match[str]") -> str:
    """Return the sentence-ish window around the match for the chunk passage."""
    start = text.rfind(".", 0, match.start()) + 1
    end = text.find(".", match.end())
    end = len(text) if end == -1 else end + 1
    return text[start:end].strip()


def extract_prose_rules(pdf) -> dict[str, "ProseRule"]:
    """Extract the 5 prose limits with deterministic, method-based confidence."""
    out: dict[str, ProseRule] = {}
    for page_idx, page in enumerate(pdf.pages, start=1):
        text = normalize_ws(page.extract_text() or "")
        for key, pattern, conf in _PATTERNS:
            if key in out:
                continue
            m = pattern.search(text)
            if m:
                out[key] = ProseRule(
                    value=(Decimal(m.group(1)) / Decimal("100")).quantize(Decimal("0.0001")),
                    confidence=conf,
                    page=page_idx,
                    passage=_passage_for(text, m),
                )
    missing = {"non_ig", "corporate", "gre", "liquidity", "counterparty"} - set(out)
    if missing:
        raise ValueError(f"prose extraction failed for: {sorted(missing)}")
    return out
