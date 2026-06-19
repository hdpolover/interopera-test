# src/firewall/checker.py
"""Output firewall: assert every numeric token in narrative ∈ computed figures set."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.compute.registry import Figure


@dataclass
class FirewallResult:
    passed: bool
    offending_numbers: list[str]
    checked_numbers: list[str]


_NUMBER_RE = re.compile(r"\b\d+(?:,\d{3})*(?:\.\d+)?%?")


def extract_numeric_tokens(text: str) -> list[str]:
    """Extract numeric tokens from text (integers, decimals, percentages, SGD amounts)."""
    return _NUMBER_RE.findall(text)


def normalize_token(token: str) -> str:
    """Normalize a token for comparison: remove commas, strip % suffix."""
    t = token.replace(",", "")
    return t


def _build_computed_set(figures: list[Figure]) -> set[str]:
    """Build set of normalized numeric strings from all figure values and limits."""
    computed = set()
    for fig in figures:
        for raw in extract_numeric_tokens(fig.value):
            computed.add(normalize_token(raw))
        for raw in extract_numeric_tokens(fig.limit):
            computed.add(normalize_token(raw))
    return computed


def check_firewall(narrative: str, figures: list[Figure]) -> FirewallResult:
    """Assert every numeric token in narrative is in computed figures set."""
    computed_set = _build_computed_set(figures)
    tokens = extract_numeric_tokens(narrative)
    offending = []
    for token in tokens:
        normalized = normalize_token(token)
        if normalized and normalized not in computed_set:
            offending.append(token)
    return FirewallResult(
        passed=len(offending) == 0,
        offending_numbers=offending,
        checked_numbers=tokens,
    )
