"""Deterministic compute primitives for compliance figure calculation.

IMPORTANT: This module must never import anthropic, openai, httpx, or requests.
All arithmetic uses decimal.Decimal with ROUND_HALF_UP.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, ROUND_FLOOR, Decimal
from typing import Any


def _mv(position: dict[str, Any]) -> Decimal:
    """Extract market_value_sgd as Decimal."""
    return Decimal(str(position["market_value_sgd"]))


def _dur(position: dict[str, Any]) -> Decimal:
    """Extract modified_duration as Decimal."""
    return Decimal(str(position["modified_duration"]))


def _guard_nav(nav_value: Decimal) -> None:
    """Raise ValueError if nav_value is zero, preventing division-by-zero."""
    if nav_value == Decimal("0"):
        raise ValueError("NAV is zero; cannot compute percentage")


def nav(positions: list[dict[str, Any]]) -> Decimal:
    """Sum of all market_value_sgd. Returns Decimal."""
    return sum((_mv(p) for p in positions), Decimal("0"))


def sum_pct(positions: list[dict[str, Any]], nav_value: Decimal) -> Decimal:
    """Sum of market values as fraction of NAV. Rounded ROUND_HALF_UP to 4dp."""
    _guard_nav(nav_value)
    total = sum((_mv(p) for p in positions), Decimal("0"))
    result = total / nav_value
    return result.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def weighted_avg_duration(positions: list[dict[str, Any]], nav_value: Decimal) -> Decimal:
    """Market-value-weighted average duration. Rounded ROUND_HALF_UP to 4dp."""
    _guard_nav(nav_value)
    numerator = sum((_mv(p) * _dur(p) for p in positions), Decimal("0"))
    result = numerator / nav_value
    return result.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def dv01(positions: list[dict[str, Any]], nav_value: Decimal) -> Decimal:
    """Portfolio DV01 = sum(mv * dur) * 0.0001. Rounded to 0 decimal places."""
    numerator = sum((_mv(p) * _dur(p) for p in positions), Decimal("0"))
    result = numerator * Decimal("0.0001")
    return result.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def max_group_pct(
    groups: dict[str, list[dict[str, Any]]], nav_value: Decimal
) -> tuple[str, Decimal]:
    """Return (group_name, pct) for the group with the highest total market value.

    Tie-break rule: when two groups have equal rounded pct, the group with the
    lexicographically smaller name wins. Iteration is alphabetical (sorted keys),
    and we update best_name only on strict improvement (>), so the first (smallest)
    name among equals is retained — making the result fully deterministic.
    """
    _guard_nav(nav_value)
    best_name = ""
    best_pct = Decimal("0")
    for name in sorted(groups.keys()):  # alphabetical order → deterministic tie-break
        group_total = sum((_mv(p) for p in groups[name]), Decimal("0"))
        pct = (group_total / nav_value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if pct > best_pct:
            best_pct = pct
            best_name = name
    return best_name, best_pct


def within_min_max(value: Decimal, min_val: Decimal, max_val: Decimal) -> str:
    """Return OK/BREACH/AT LIMIT for a value within a min-max band.

    Returns:
        "BREACH"   — value is strictly outside the band (< min or > max)
        "AT LIMIT" — value equals min_val or max_val exactly
        "OK"       — value is strictly within the band
    """
    if value < min_val or value > max_val:
        return "BREACH"
    if value == min_val or value == max_val:
        return "AT LIMIT"
    return "OK"


def max_cap(value: Decimal, cap: Decimal) -> str:
    """Return OK/AT LIMIT/BREACH for a value vs a maximum cap."""
    if value > cap:
        return "BREACH"
    if value == cap:
        return "AT LIMIT"
    return "OK"


def min_floor(value: Decimal, floor_val: Decimal) -> str:
    """Return OK/BREACH for a value vs a minimum floor."""
    if value < floor_val:
        return "BREACH"
    return "OK"


def percent_1dp(value: Decimal) -> str:
    """Format a fraction (0.35) as '35.0%'."""
    pct = (value * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{pct}%"


def truncated_bps(value: Decimal) -> str:
    """Format a fraction as truncated basis points. 0.58333 -> '5833 bps'."""
    bps_raw = value * Decimal("10000")
    bps_int = int(bps_raw.to_integral_value(rounding=ROUND_FLOOR))
    return f"{bps_int} bps"


def years_2dp(value: Decimal) -> str:
    """Format a duration as '3.88 yrs' (ROUND_HALF_UP 2dp)."""
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{rounded} yrs"


def sgd_dv01(value: Decimal) -> str:
    """Format a DV01 as 'SGD 38,790 / bp' (integer, with thousands comma, no decimal)."""
    int_val = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"SGD {int_val:,} / bp"
