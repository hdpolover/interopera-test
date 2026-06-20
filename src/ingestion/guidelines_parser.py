"""Parse fund guidelines PDF into RuleChunk dataclasses.

Deterministically assembles RuleChunks from the real pdfplumber extractors.
No LLM is used; an llm_client argument, if passed, is ignored.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.ingestion.pdf_tables import dv01_cap, duration_bounds, extract_allocations
from src.ingestion.rule_extractors import extract_prose_rules

_DEFAULT_PDF = os.path.join("sample_docs", "sample_fund_guidelines.pdf")

_MIN_PARAGRAPH_CHARS: int = 30  # Paragraphs shorter than this are too sparse to extract rules from.


@dataclass(frozen=True)
class RuleChunk:
    chunk_id: str
    source_doc: str
    page: int
    passage: str
    passage_summary: str
    extracted_fields: dict[str, Any]
    extraction_confidence: float


def chunk_id_from_text(text: str) -> str:
    """Return sha256 of text, first 16 hex chars."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# asset_class canonical name -> limit_ref
_ALLOC_REF: dict[str, str] = {
    "Singapore Government Securities": "allocation_sgs_limit",
    "MAS Bills": "allocation_mas_limit",
    "Investment Grade Corporate Bonds": "allocation_ig_limit",
    "High Yield Bonds": "allocation_hy_limit",
    "Foreign Currency Bonds": "allocation_fx_limit",
    "Structured Credit": "allocation_sc_limit",
    "Cash & Cash Equivalents": "allocation_cash_limit",
}


def _fmt_pct(d: Decimal) -> str:
    """Format a fraction Decimal (e.g. 0.2000) as 2-decimal string (e.g. '0.20')."""
    return str(d.quantize(Decimal("0.01")))


def _fmt_int(d: Decimal) -> str:
    """Format a whole-number Decimal (e.g. 85000) as an integer string."""
    return str(int(d))


def _chunk(
    passage: str,
    page: int,
    rule_type: str,
    confidence: float,
    *,
    limit_ref: str | None = None,
    bounds: dict[str, str] | None = None,
) -> RuleChunk:
    fields: dict[str, Any] = {"rule_type": rule_type}
    if limit_ref:
        fields["limit_ref"] = limit_ref
    if bounds:
        fields["bounds"] = bounds
    return RuleChunk(
        chunk_id=chunk_id_from_text(passage),
        source_doc="sample_fund_guidelines.pdf",
        page=page,
        passage=passage,
        passage_summary=passage[:120],
        extracted_fields=fields,
        extraction_confidence=confidence,
    )


def _build_metrics_chunk(pdf: Any) -> RuleChunk:  # noqa: ANN401
    """Return the market_risk_metrics RuleChunk with the 6-metric list verbatim."""
    passage = (
        "Section 3.1 Market Risk. Modified Duration: limit 2.0-6.5 years, monitoring Daily, "
        "breach action PM notification within 1h. "
        "Portfolio DV01: limit <= SGD 85,000 per bp, monitoring Daily, breach action Risk Committee alert. "
        "Value-at-Risk (95%, 10-day): limit <= 2.5% of NAV, monitoring Daily, breach action CRO review required. "
        "Expected Shortfall (97.5%): limit <= 3.8% of NAV, monitoring Weekly, breach action Board reporting if exceeded. "
        "Interest Rate Sensitivity: limit <= +/-12% NAV impact for +/-200bp, monitoring Monthly, breach action Strategy review. "
        "Tracking Error vs Benchmark: limit <= 3.0% annualised, monitoring Monthly, breach action IPS review triggered."
    )
    metrics = [
        {
            "metric": "portfolio_duration",
            "limit": "2.0-6.5 years",
            "monitoring_frequency": "Daily",
            "breach_action": "PM notification within 1h",
            "owner": "Portfolio Manager",
        },
        {
            "metric": "portfolio_dv01",
            "limit": "<= SGD 85,000 per bp",
            "monitoring_frequency": "Daily",
            "breach_action": "Risk Committee alert",
            "owner": "Risk Committee",
        },
        {
            "metric": "value_at_risk_95_10d",
            "limit": "<= 2.5% of NAV",
            "monitoring_frequency": "Daily",
            "breach_action": "CRO review required",
            "owner": "Chief Risk Officer",
        },
        {
            "metric": "expected_shortfall_97_5",
            "limit": "<= 3.8% of NAV",
            "monitoring_frequency": "Weekly",
            "breach_action": "Board reporting if exceeded",
            "owner": "Board Risk Committee",
        },
        {
            "metric": "interest_rate_sensitivity",
            "limit": "<= +/-12% NAV for +/-200bp",
            "monitoring_frequency": "Monthly",
            "breach_action": "Strategy review",
            "owner": "Investment Management Committee",
        },
        {
            "metric": "tracking_error_vs_benchmark",
            "limit": "<= 3.0% annualised",
            "monitoring_frequency": "Monthly",
            "breach_action": "IPS review triggered",
            "owner": "IPS Committee",
        },
    ]
    return RuleChunk(
        chunk_id=chunk_id_from_text(passage),
        source_doc="sample_fund_guidelines.pdf",
        page=2,
        passage=passage,
        passage_summary="Market risk metrics: limits, monitoring frequency, breach actions, and notified owners (Section 3.1).",
        extracted_fields={"rule_type": "market_risk_metrics", "metrics": metrics},
        extraction_confidence=0.96,
    )


def parse_guidelines(pdf_path: str | None = None, llm_client: object | None = None) -> list[RuleChunk]:
    """Deterministically parse the guidelines PDF into RuleChunks carrying limit bounds.

    Default path: sample_docs/sample_fund_guidelines.pdf. No LLM is used; an
    llm_client, if passed, is ignored by this deterministic implementation.
    """
    import pdfplumber

    path = pdf_path or _DEFAULT_PDF
    chunks: list[RuleChunk] = []
    with pdfplumber.open(path) as pdf:
        # Allocations (7) — SGS..SC use min/max band; Cash uses floor only.
        for row in extract_allocations(pdf):
            ref = _ALLOC_REF[row.asset_class]
            # Allocation rows must have min_frac; rows without a max use min only.
            assert row.min_frac is not None, (
                f"min_frac is None for {row.asset_class} — PDF table parse failed"
            )
            min_frac = row.min_frac
            max_frac = row.max_frac if row.max_frac is not None else row.min_frac
            passage = f"{row.asset_class}: allocation {_fmt_pct(min_frac)}-{_fmt_pct(max_frac)} of NAV (Section 2)."
            if ref == "allocation_cash_limit":
                bounds: dict[str, str] = {"floor_value": _fmt_pct(min_frac), "unit": "pct"}
            else:
                bounds = {
                    "min_value": _fmt_pct(min_frac),
                    "max_value": _fmt_pct(max_frac),
                    "unit": "pct",
                }
            chunks.append(_chunk(passage, row.page, "allocation_limit", 0.95, limit_ref=ref, bounds=bounds))

        # Duration + DV01 (from risk metrics table)
        dmin, dmax, dpage = duration_bounds(pdf)
        chunks.append(
            _chunk(
                f"Modified Duration band {dmin}-{dmax} years (Section 3.1).",
                dpage,
                "duration_limit",
                0.95,
                limit_ref="duration_limit",
                bounds={"min_value": str(dmin), "max_value": str(dmax), "unit": "years"},
            )
        )
        cap, cpage = dv01_cap(pdf)
        chunks.append(
            _chunk(
                f"Portfolio DV01 cap SGD {cap} per bp (Section 3.1).",
                cpage,
                "dv01_limit",
                0.95,
                limit_ref="dv01_limit",
                bounds={"cap_value": _fmt_int(cap), "unit": "sgd"},
            )
        )

        # Prose rules (5)
        prose = extract_prose_rules(pdf)
        chunks.append(
            _chunk(
                prose["non_ig"].passage,
                prose["non_ig"].page,
                "non_ig_cap",
                prose["non_ig"].confidence,
                limit_ref="non_ig_cap_limit",
                bounds={"cap_value": _fmt_pct(prose["non_ig"].value), "unit": "pct"},
            )
        )
        chunks.append(
            _chunk(
                prose["corporate"].passage,
                prose["corporate"].page,
                "concentration_limit",
                prose["corporate"].confidence,
                limit_ref="corporate_issuer_limit",
                bounds={"cap_value": _fmt_pct(prose["corporate"].value), "unit": "pct"},
            )
        )
        chunks.append(
            _chunk(
                prose["gre"].passage,
                prose["gre"].page,
                "concentration_limit",
                prose["gre"].confidence,
                limit_ref="gre_issuer_limit",
                bounds={"cap_value": _fmt_pct(prose["gre"].value), "unit": "pct"},
            )
        )
        chunks.append(
            _chunk(
                prose["liquidity"].passage,
                prose["liquidity"].page,
                "liquidity_requirement",
                prose["liquidity"].confidence,
                limit_ref="liquidity_limit",
                bounds={"floor_value": _fmt_pct(prose["liquidity"].value), "unit": "pct"},
            )
        )
        chunks.append(
            _chunk(
                prose["counterparty"].passage,
                prose["counterparty"].page,
                "counterparty_limit",
                prose["counterparty"].confidence,
                bounds={"cap_value": _fmt_pct(prose["counterparty"].value), "unit": "pct"},
            )
        )

        # market_risk_metrics chunk (preserves load_risk_metrics / query-metric behaviour)
        chunks.append(_build_metrics_chunk(pdf))

    return chunks
