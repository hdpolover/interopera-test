"""Firewall checker tests."""
import pytest
from src.compute.registry import Figure


@pytest.fixture
def firm_a_figures():
    return [
        Figure(figure="allocation_sgs",                  value="35.0%",            utilization="58.3%",    status="OK",       limit="20–60%",            graph_path="", citation={}),
        Figure(figure="allocation_mas_bills",            value="8.0%",             utilization="20.0%",    status="OK",       limit="0–40%",             graph_path="", citation={}),
        Figure(figure="allocation_ig_corp",              value="33.0%",            utilization="66.0%",    status="OK",       limit="10–50%",            graph_path="", citation={}),
        Figure(figure="allocation_high_yield",           value="9.0%",             utilization="60.0%",    status="OK",       limit="0–15%",             graph_path="", citation={}),
        Figure(figure="allocation_fx_bonds",             value="5.0%",             utilization="25.0%",    status="OK",       limit="0–20%",             graph_path="", citation={}),
        Figure(figure="allocation_structured_credit",    value="6.0%",             utilization="60.0%",    status="OK",       limit="0–10%",             graph_path="", citation={}),
        Figure(figure="allocation_cash",                 value="4.0%",             utilization="n/a",      status="BREACH",   limit="min 5%",            graph_path="", citation={}),
        Figure(figure="aggregate_non_ig_exposure",       value="15.0%",            utilization="75.0%",    status="OK",       limit="max 20%",           graph_path="", citation={}),
        Figure(figure="largest_single_corporate_issuer", value="8.0%",             utilization="100.0%",   status="AT LIMIT", limit="max 8%",            graph_path="", citation={}),
        Figure(figure="largest_gre_issuer",              value="7.0%",             utilization="58.3%",    status="OK",       limit="max 12%",           graph_path="", citation={}),
        Figure(figure="liquid_assets_ratio",             value="47.0%",            utilization="188.0%",   status="OK",       limit="min 25%",           graph_path="", citation={}),
        Figure(figure="portfolio_duration",              value="3.88 yrs",         utilization="n/a",      status="OK",       limit="2.0–6.5 yrs",       graph_path="", citation={}),
        Figure(figure="portfolio_dv01",                  value="SGD 38,790 / bp",  utilization="45.6%",    status="OK",       limit="max SGD 85,000 / bp", graph_path="", citation={}),
    ]


def test_firewall_passes_clean_narrative(firm_a_figures):
    """(b) A clean narrative that only references computed values → PASS."""
    from src.firewall.checker import check_firewall
    narrative = (
        "The portfolio allocates 35.0% to Singapore Government Securities, "
        "within the 20–60% limit. Cash is 4.0%, below the minimum 5% floor. "
        "Duration is 3.88 yrs. DV01 is SGD 38,790 / bp, well below the 85,000 cap. "
        "Non-IG exposure is 15.0%, under the 20% maximum."
    )
    result = check_firewall(narrative, firm_a_figures)
    assert result.passed is True
    assert result.offending_numbers == []


def test_firewall_fails_injected_number(firm_a_figures):
    """(a) A narrative containing a fabricated number (99.9%) not in figures → FAIL."""
    from src.firewall.checker import check_firewall
    narrative = "The risk exposure reached 99.9% of the tolerance band."
    result = check_firewall(narrative, firm_a_figures)
    assert result.passed is False
    assert any("99.9" in t for t in result.offending_numbers)


def test_firewall_passes_allowlisted_year(firm_a_figures):
    """(c) A narrative mentioning a 4-digit year → PASS (allowlist works)."""
    from src.firewall.checker import check_firewall
    narrative = (
        "As of 2024, the portfolio allocates 35.0% to Singapore Government Securities. "
        "The fund was established in 2020."
    )
    result = check_firewall(narrative, firm_a_figures)
    assert result.passed is True
    assert result.offending_numbers == []


def test_firewall_passes_allowlisted_section_ref(firm_a_figures):
    """(c) A narrative mentioning a section reference like §4.2 → PASS (allowlist works)."""
    from src.firewall.checker import check_firewall
    narrative = (
        "Per Section 4.2, the portfolio allocates 35.0% to SGS. "
        "See §3.1 for compliance details."
    )
    result = check_firewall(narrative, firm_a_figures)
    assert result.passed is True
    assert result.offending_numbers == []


def test_firewall_symmetric_normalization_no_false_positive(firm_a_figures):
    """(d) Symmetric normalization: '35.0' in narrative vs '35.0%' figure → PASS, no false positive."""
    from src.firewall.checker import check_firewall
    narrative = "The allocation is 35.0 percent of the portfolio."
    result = check_firewall(narrative, firm_a_figures)
    assert result.passed is True
    assert result.offending_numbers == []


def test_firewall_symmetric_normalization_with_percent(firm_a_figures):
    """(d) Symmetric: '35.0%' in narrative vs '35.0%' figure → PASS."""
    from src.firewall.checker import check_firewall
    narrative = "SGS allocation stands at 35.0%."
    result = check_firewall(narrative, firm_a_figures)
    assert result.passed is True
    assert result.offending_numbers == []


def test_firewall_normalized_large_number(firm_a_figures):
    """38,790 in narrative (figure is 'SGD 38,790 / bp') → PASS after normalization."""
    from src.firewall.checker import check_firewall
    narrative = "The DV01 is 38,790 basis points per dollar."
    result = check_firewall(narrative, firm_a_figures)
    assert result.passed is True
    assert result.offending_numbers == []


def test_firewall_fails_close_but_not_matching(firm_a_figures):
    """A number close to but not in figures → FAIL (no false negatives)."""
    from src.firewall.checker import check_firewall
    narrative = "The allocation is 36.0% of the portfolio."
    result = check_firewall(narrative, firm_a_figures)
    assert result.passed is False
    assert any("36" in t for t in result.offending_numbers)


def test_firewall_bps_normalization(firm_a_figures):
    """5833 bps should normalize to 5833 and match if present in figures."""
    from src.firewall.checker import normalize_token
    # Verify "5833" normalizes cleanly
    assert normalize_token("5833") == "5833"
    assert normalize_token("5833 bps") == "5833"


def test_firewall_188_percent_normalization(firm_a_figures):
    """188.0% utilization from liquid_assets_ratio in narrative → PASS."""
    from src.firewall.checker import check_firewall
    narrative = "The liquid assets ratio utilization is 188.0%."
    result = check_firewall(narrative, firm_a_figures)
    assert result.passed is True


def test_firewall_sgd_normalization():
    """SGD 38,790 / bp normalizes to 38790."""
    from src.firewall.checker import normalize_token
    assert normalize_token("SGD 38,790") == "38790"
    assert normalize_token("38,790") == "38790"


def test_extract_numeric_tokens():
    from src.firewall.checker import extract_numeric_tokens
    text = "35.0% of NAV with SGD 38,790 / bp DV01 and 3.88 yrs duration"
    tokens = extract_numeric_tokens(text)
    assert "35.0%" in tokens


def test_normalize_token_strips_commas():
    from src.firewall.checker import normalize_token
    assert normalize_token("38,790") == "38790"


def test_normalize_token_preserves_pct():
    from src.firewall.checker import normalize_token
    result = normalize_token("35.0%")
    assert result == "35.0"


def test_firewall_result_dataclass():
    from src.firewall.checker import FirewallResult
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(FirewallResult)}
    assert field_names == {"passed", "offending_numbers", "checked_numbers"}


def test_firewall_no_llm_imports():
    import ast
    import os
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, "src", "firewall", "checker.py")
    with open(path) as f:
        tree = ast.parse(f.read())
    forbidden = {"anthropic", "openai", "httpx", "requests"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for name in names:
                assert name.split(".")[0] not in forbidden


def test_firewall_hex_suffix_bypass_is_blocked(firm_a_figures):
    """Security regression: fabricated number adjacent to a hex suffix must NOT be allowlisted.

    An attacker (or hallucinating LLM) could emit '9999' (not in figures) alongside
    a hex-looking token '9999a1b2' to exploit the old prefix-allowlist in category 3.
    The fixed firewall strips hex tokens BEFORE extracting numeric tokens, so '9999'
    is still present in the stripped text and must be flagged as offending.
    """
    from src.firewall.checker import check_firewall
    # 9999 is NOT in firm_a_figures; '9999a1b2' is a hex token whose digit prefix
    # was previously used to smuggle the fabricated value through the firewall.
    narrative = "Exposure is 9999% (basis 9999a1b2)."
    result = check_firewall(narrative, firm_a_figures)
    assert result.passed is False, (
        "Firewall must FAIL: '9999' is fabricated and must not be allowlisted via "
        "its hex suffix '9999a1b2'."
    )
    assert any("9999" in t for t in result.offending_numbers), (
        f"Expected '9999%' or '9999' in offending_numbers; got {result.offending_numbers}"
    )


def test_firewall_real_chunk_id_no_false_positive(firm_a_figures):
    """No false positive: a genuine chunk ID like '827726a0' must not cause a firewall failure.

    The digit prefix '827726' extracted from the chunk ID is NOT a financial figure,
    so it must be ignored.  The fix strips hex tokens from the narrative before
    numeric extraction, so '827726' never appears in the token list at all.
    """
    from src.firewall.checker import check_firewall
    # All numeric tokens in this narrative are either in firm_a_figures or covered
    # by other allowlists (years).  '827726a0' is a hex chunk ID — its digit prefix
    # '827726' must NOT be checked against the computed set (which doesn't contain it).
    narrative = (
        "The portfolio allocates 35.0% to SGS per chunk 827726a0. "
        "Cash is 4.0%, below the minimum 5% floor. "
        "Liquid assets ratio utilization is 188.0% (established 2020)."
    )
    result = check_firewall(narrative, firm_a_figures)
    assert result.passed is True, (
        f"Firewall must PASS: '827726' is a chunk-ID digit prefix, not a fabricated figure. "
        f"offending_numbers={result.offending_numbers}"
    )
