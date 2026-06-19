"""Parse fund guidelines PDF into RuleChunk dataclasses.

When llm_client is None, returns deterministic stub chunks for the 6 known rule types.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class RuleChunk:
    chunk_id: str
    source_doc: str
    page: int
    passage: str
    passage_summary: str
    extracted_fields: dict[str, Any]
    extraction_confidence: float


def chunk_id_from_text(text: str) -> str:
    """Return sha256 of text, first 8 hex chars."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


# Deterministic stub passages for the 6 known rule types.
_STUB_PASSAGES: list[dict[str, Any]] = [
    {
        "rule_type": "allocation_limit",
        "passage": (
            "The Fund shall maintain allocations within the following ranges: "
            "Singapore Government Securities 20-60%, MAS Bills 0-40%, "
            "Investment Grade Corporate Bonds 10-50%, High Yield Bonds 0-15%, "
            "Foreign Currency Bonds 0-20%, Structured Credit 0-10%, Cash minimum 5%."
        ),
        "passage_summary": "Asset class allocation limits for all buckets.",
        "extracted_fields_extra": {
            "limits": {
                "Singapore Government Securities": {"min": "20%", "max": "60%"},
                "MAS Bills": {"min": "0%", "max": "40%"},
                "Investment Grade Corporate Bonds": {"min": "10%", "max": "50%"},
                "High Yield Bonds": {"min": "0%", "max": "15%"},
                "Foreign Currency Bonds": {"min": "0%", "max": "20%"},
                "Structured Credit": {"min": "0%", "max": "10%"},
                "Cash": {"min": "5%"},
            }
        },
        "page": 2,
        "extraction_confidence": 0.95,
    },
    {
        "rule_type": "non_ig_cap",
        "passage": (
            "Aggregate exposure to non-investment-grade securities shall not exceed 20% of NAV."
        ),
        "passage_summary": "Non-IG aggregate exposure cap of 20%.",
        "extracted_fields_extra": {"non_ig_max": "20%"},
        "page": 2,
        "extraction_confidence": 0.94,
    },
    {
        "rule_type": "duration_limit",
        "passage": (
            "The portfolio modified duration shall be maintained between 2.0 years and 6.5 years."
        ),
        "passage_summary": "Portfolio duration band of 2.0 to 6.5 years.",
        "extracted_fields_extra": {"duration_min": "2.0 yrs", "duration_max": "6.5 yrs"},
        "page": 3,
        "extraction_confidence": 0.97,
    },
    {
        "rule_type": "dv01_limit",
        "passage": (
            "The portfolio DV01 shall not exceed SGD 85,000 per basis point."
        ),
        "passage_summary": "Maximum DV01 of SGD 85,000 / bp.",
        "extracted_fields_extra": {"dv01_max_sgd": "85000"},
        "page": 3,
        "extraction_confidence": 0.96,
    },
    {
        "rule_type": "concentration_limit",
        "passage": (
            "No single corporate issuer shall exceed 8% of NAV. "
            "No single GRE issuer or GRE group shall exceed 12% of NAV."
        ),
        "passage_summary": "Single issuer and GRE concentration limits.",
        "extracted_fields_extra": {
            "corporate_issuer_cap": "8%",
            "gre_issuer_cap": "12%",
        },
        "page": 4,
        "extraction_confidence": 0.92,
    },
    {
        "rule_type": "liquidity_requirement",
        "passage": (
            "The Fund must maintain a minimum of 25% of NAV in liquid assets. "
            "Liquid assets are defined as Singapore Government Securities, MAS Bills, and Cash."
        ),
        "passage_summary": "Minimum 25% liquidity requirement in government securities and cash.",
        "extracted_fields_extra": {"liquid_assets_min": "25%"},
        "page": 4,
        "extraction_confidence": 0.93,
    },
]


def _make_stub_chunks() -> list[RuleChunk]:
    chunks = []
    for stub in _STUB_PASSAGES:
        passage = stub["passage"]
        extracted: dict[str, Any] = {"rule_type": stub["rule_type"]}
        extracted.update(stub["extracted_fields_extra"])
        chunks.append(
            RuleChunk(
                chunk_id=chunk_id_from_text(passage),
                source_doc="sample_fund_guidelines.pdf",
                page=stub["page"],
                passage=passage,
                passage_summary=stub["passage_summary"],
                extracted_fields=extracted,
                extraction_confidence=stub["extraction_confidence"],
            )
        )
    return chunks


def parse_guidelines(pdf_path: Optional[str], llm_client=None) -> list[RuleChunk]:
    """Parse fund guidelines PDF into RuleChunk list.

    If llm_client is None (or pdf_path is None), returns deterministic stub chunks.
    """
    if llm_client is None or pdf_path is None:
        return _make_stub_chunks()

    # LLM-assisted extraction path (when api key is available)
    try:
        import pdfplumber
    except ImportError:
        return _make_stub_chunks()

    chunks: list[RuleChunk] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if not text.strip():
                continue
            # Split into paragraphs
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            for para in paragraphs:
                if len(para) < 30:
                    continue
                # Call LLM to extract structured fields and confidence
                result = llm_client.extract_rule(para)
                if result is None:
                    continue
                chunks.append(
                    RuleChunk(
                        chunk_id=chunk_id_from_text(para),
                        source_doc=pdf_path,
                        page=page_num,
                        passage=para,
                        passage_summary=result.get("summary", ""),
                        extracted_fields=result.get("fields", {}),
                        extraction_confidence=float(result.get("confidence", 0.5)),
                    )
                )
    return chunks if chunks else _make_stub_chunks()
