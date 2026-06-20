# tests/test_rule_extractors.py
import pdfplumber
from decimal import Decimal
from src.ingestion.rule_extractors import extract_prose_rules

_PDF = "sample_docs/sample_fund_guidelines.pdf"


def test_prose_rules_values_and_confidence():
    with pdfplumber.open(_PDF) as pdf:
        rules = extract_prose_rules(pdf)
    assert rules["non_ig"].value == Decimal("0.20")
    assert rules["corporate"].value == Decimal("0.08")
    assert rules["gre"].value == Decimal("0.12")
    assert rules["liquidity"].value == Decimal("0.25")
    assert rules["counterparty"].value == Decimal("0.05")
    # figure-anchoring prose rules are high confidence
    assert rules["liquidity"].confidence >= 0.85
    assert rules["non_ig"].confidence >= 0.85
    # counterparty is the genuine low-confidence extraction
    assert rules["counterparty"].confidence < 0.85
    assert rules["liquidity"].page == 2
