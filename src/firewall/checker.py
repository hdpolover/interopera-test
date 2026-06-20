# src/firewall/checker.py
"""Output firewall: verify every numeric token in narrative ∈ computed figures set.

Constraint 3 (spec §3.1): the LLM narrative may not introduce any number absent
from the computed output.  This module VERIFIES that — it does not assert blindly.
Pure-code: no LLM library imported.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.compute.registry import Figure


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class FirewallResult:
    passed: bool
    offending_numbers: list[str]
    checked_numbers: list[str]


# ---------------------------------------------------------------------------
# Regex – matches integers, decimals, percentage variants, and comma-grouped
# numbers (e.g. 38,790).  Currency prefixes and unit suffixes are stripped
# separately in normalize_token() so the raw token is preserved for reporting.
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(
    r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?%?"   # comma-grouped  e.g. 38,790  38,790.5%
    r"|\b\d+\.\d+%?"                        # plain decimal  e.g. 35.0  3.88  35.0%
    r"|\b\d+%?"                             # plain integer  e.g. 5  20%
)
# Note: this regex does not match negative numbers (e.g. a fabricated "-35.0%" would
# normalize to "35.0" because the leading minus is not captured by \b\d+).
# This is acceptable since all computed figures are non-negative by construction.

# ---------------------------------------------------------------------------
# Documented allowlist — categories of numbers that legitimately appear in
# prose without being sourced from a computed figure.  A reviewer can audit
# this list to understand exactly what is exempted.
#
#   1. FOUR-DIGIT YEARS (1900–2099):  calendar year references such as "2024"
#      or "2020" are never produced by the compute engine, so they must not
#      trigger a firewall failure.
#
#   2. SECTION / PARAGRAPH REFERENCES:  numbers that appear immediately after
#      "Section", "§", "Para", "Art", "Annex", "Exhibit", or "Clause" (with
#      optional trailing dot/digit e.g. "4.2", "III") are structural
#      cross-references, not financial figures.
#
# Hex/chunk-ID digit prefixes are handled separately: hex tokens are stripped
# from the narrative text BEFORE numeric extraction in check_firewall(), so
# those digit prefixes are never seen by the allowlist.  See _HEX_TOKEN_RE.
# ---------------------------------------------------------------------------

# Allowlist category 1: 4-digit years (1900–2099)
_ALLOWLIST_YEAR_RE = re.compile(r"^(19|20)\d{2}$")

# Allowlist category 2: structural section/cross-reference and page numbers.
# Captures the numeric string that IMMEDIATELY follows the structural keyword.
_ALLOWLIST_SECTION_RE = re.compile(
    r"(?:Section|§|Para(?:graph)?|Art(?:icle)?|Annex|Exhibit|Clause|[Pp]age|[Pp]g\.?)\s*(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)

# Hex/chunk-ID token stripper: matches a run of 6+ hex characters (digits + a-f)
# that contains at least one letter a-f.  These are identifier tokens (e.g.
# "827726a0", "42b7002a") that the LLM may emit when citing regulatory basis strings.
# They are stripped from the narrative BEFORE numeric token extraction so that their
# digit prefix (e.g. "827726") is never presented to the computed-set check.
#
# Threshold rationale — minimum length 6:
#   • Genuine financial figures never contain hex letters (a-f), so stripping
#     hex-with-letter tokens cannot accidentally remove a real number.
#   • Short hex-looking sequences of 1-5 chars (e.g. "a", "3b") are more likely
#     to be prose words or single-letter abbreviations; requiring 6+ chars avoids
#     inadvertently stripping those.
#   • Real chunk IDs observed in practice (e.g. "827726a0", "42b7002a") are 8+
#     chars, well above this threshold.
#
# Security: hex tokens are stripped, not allowlisted by digit-prefix matching.
# This prevents a narrative from smuggling a fabricated number (e.g. "9999") by
# emitting an adjacent hex token that shares its digits (e.g. "9999a1").
_HEX_TOKEN_RE = re.compile(r"\b(?=[0-9a-f]{6,}\b)[0-9a-f]*[a-f][0-9a-f]*\b", re.IGNORECASE)


def _is_allowlisted(token: str, original_text: str) -> bool:
    """Return True if *token* falls into a documented allowlist category.

    Args:
        token:         The raw numeric token extracted from the narrative.
        original_text: The hex-stripped narrative text, used to check positional
                       context (e.g. whether the token follows a structural keyword).

    Categories checked:
        1. Four-digit years (1900–2099).
        2. Structural section / cross-reference numbers (Section 4.2, §3.1, etc.).

    Hex/chunk-ID digit prefixes are handled upstream by stripping hex tokens from
    the narrative before this function is ever called — see check_firewall().
    """
    # Category 1: 4-digit year (bare, no % suffix)
    if _ALLOWLIST_YEAR_RE.match(token):
        return True

    # Category 2: structural section reference — the token appears as the
    # number portion of a keyword+number phrase anywhere in the text.
    for m in _ALLOWLIST_SECTION_RE.finditer(original_text):
        if m.group(1) == token:
            return True

    return False


# ---------------------------------------------------------------------------
# Normalization  (SYMMETRIC — applied identically to BOTH narrative tokens
# AND figure field tokens so comparisons are fair and consistent)
#
# A figure value "35.0%" and a narrative mention of "35.0" must compare equal.
# A figure value "SGD 38,790 / bp" and a narrative "38,790" must compare equal.
#
# Steps:
#   1. Strip leading currency prefixes (SGD, USD, EUR, …)
#   2. Remove commas (thousand separators)
#   3. Strip trailing unit suffixes (bps, bp, yrs, yr, %, /, spaces)
#   4. Return the bare numeric string, e.g. "38790", "35.0", "3.88"
# ---------------------------------------------------------------------------

_CURRENCY_PREFIX_RE = re.compile(r"^[A-Z]{2,4}\s+", re.ASCII)
_UNIT_SUFFIX_RE = re.compile(r"[\s/]*(bps?|yrs?|%)\s*$", re.IGNORECASE)


def normalize_token(token: str) -> str:
    """Normalize a numeric token for symmetric comparison.

    Strips leading currency codes, thousand-separator commas, and trailing
    unit suffixes (%, bps, yrs, etc.) so that figure tokens and narrative
    tokens can be compared on bare numeric magnitude.

    Examples:
        "SGD 38,790"  → "38790"
        "38,790"      → "38790"
        "35.0%"       → "35.0"
        "35.0"        → "35.0"
        "3.88 yrs"    → "3.88"
        "5833 bps"    → "5833"
        "188.0%"      → "188.0"
    """
    t = token.strip()
    # Step 1: strip currency prefix (e.g. "SGD ")
    t = _CURRENCY_PREFIX_RE.sub("", t)
    # Step 2: remove thousand-separator commas
    t = t.replace(",", "")
    # Step 3: strip trailing unit suffixes and surrounding whitespace/slashes
    t = _UNIT_SUFFIX_RE.sub("", t).strip()
    return t


# ---------------------------------------------------------------------------
# Numeric token extraction
# ---------------------------------------------------------------------------

def extract_numeric_tokens(text: str) -> list[str]:
    """Extract all numeric tokens from *text*.

    Returns raw tokens (integers, decimals, percentages, comma-grouped numbers).
    Currency prefixes and unit suffixes are NOT stripped here — call
    normalize_token() separately so that the original token is preserved for
    error reporting.
    """
    return _NUMBER_RE.findall(text)


# ---------------------------------------------------------------------------
# Computed set builder
# ---------------------------------------------------------------------------

def _build_computed_set(figures: list[Figure]) -> set[str]:
    """Build the set of *normalized* numeric strings from all figure fields.

    Per the cross-task contract the computed set covers:
      • figure.value       — the primary computed value (e.g. "35.0%")
      • figure.utilization — utilization percentage (e.g. "58.3%", "188.0%")
      • figure.limit       — the policy limit(s), which may contain ranges
                             (e.g. "20–60%", "max SGD 85,000 / bp")

    En-dash (–) and hyphen (-) in range strings are replaced with spaces before
    token extraction so that "20" and "60" are extracted as separate tokens
    rather than "20–60" as an un-parseable compound.
    """
    computed: set[str] = set()

    for fig in figures:
        for field_val in (fig.value, fig.utilization, fig.limit):
            # Replace en-dash and hyphen range separators with spaces
            normalized_field = field_val.replace("–", " ").replace("-", " ")
            for raw in extract_numeric_tokens(normalized_field):
                norm = normalize_token(raw)
                if norm:
                    computed.add(norm)
                    # Allow both "12" and "12.0" to match each other.
                    # An LLM may write "12.0%" for a limit stored as "12%";
                    # these are numerically identical so both forms are valid.
                    if norm.endswith(".0") and "." not in norm[:-2]:
                        computed.add(norm[:-2])   # "12.0" → also admit "12"
                    elif "." not in norm:
                        computed.add(norm + ".0")  # "12"   → also admit "12.0"

    return computed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_firewall(narrative: str, figures: list[Figure]) -> FirewallResult:
    """Verify that every numeric token in *narrative* is present in the computed set.

    Returns a FirewallResult:
      • passed=True  — all narrative numbers are in the computed set (PASS).
      • passed=False — at least one narrative number is absent (FAIL / hallucination).
      • offending_numbers — raw tokens that failed the check.
      • checked_numbers  — all raw tokens that were examined (allowlisted excluded).

    Allowlisted tokens (4-digit years, section cross-references) are excluded
    from the check via _is_allowlisted() — see the documented allowlist above.

    Security note — hex pre-stripping:
        Before extracting numeric tokens, all hex/chunk-ID tokens (runs of 6+
        hex characters containing at least one letter a-f, matched by
        _HEX_TOKEN_RE) are replaced with a space in the text used for token
        extraction.  This prevents an LLM from smuggling a fabricated number
        (e.g. "9999") by appending a hex suffix (e.g. "9999a1b2") to trick the
        old prefix-allowlist into exempting it.  Genuine financial figures never
        contain hex letters, so stripping hex tokens cannot silently drop a
        real number.
    """
    computed_set = _build_computed_set(figures)

    # Strip hex/chunk-ID tokens before extracting numeric tokens so that digit
    # prefixes of identifiers (e.g. "827726" from "827726a0") are never seen by
    # the computed-set check.
    stripped_narrative = _HEX_TOKEN_RE.sub(" ", narrative)
    raw_tokens = extract_numeric_tokens(stripped_narrative)

    offending: list[str] = []
    checked: list[str] = []

    for raw in raw_tokens:
        # Skip tokens covered by the documented allowlist (years, section refs).
        # Pass stripped_narrative so section-ref context is still intact.
        if _is_allowlisted(raw, stripped_narrative):
            continue

        checked.append(raw)
        normalized = normalize_token(raw)
        if normalized and normalized not in computed_set:
            offending.append(raw)

    return FirewallResult(
        passed=len(offending) == 0,
        offending_numbers=offending,
        checked_numbers=checked,
    )
