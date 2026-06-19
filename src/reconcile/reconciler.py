# src/reconcile/reconciler.py
"""Reconcile computed figures against firm answer keys.

Pure deterministic code — no LLM library imports (Gate 6).
"""
from __future__ import annotations

from dataclasses import dataclass

import yaml

from src.compute.registry import Figure


# Mapping from Metric column value in firm_A_answer_key.xlsx → figure_id
_METRIC_TO_FIGURE_ID: dict[str, str] = {
    "Singapore Government Securities":       "allocation_sgs",
    "MAS Bills":                             "allocation_mas_bills",
    "Investment Grade Corporate Bonds":      "allocation_ig_corp",
    "High Yield Bonds":                      "allocation_high_yield",
    "Foreign Currency Bonds (hedged)":       "allocation_fx_bonds",
    "Foreign Currency Bonds":               "allocation_fx_bonds",
    "Structured Credit (ABS/MBS)":          "allocation_structured_credit",
    "Structured Credit":                    "allocation_structured_credit",
    "Cash & Cash Equivalents":              "allocation_cash",
    "Aggregate non-IG exposure":            "aggregate_non_ig_exposure",
    "Largest single corporate issuer":      "largest_single_corporate_issuer",
    "Largest GRE issuer":                   "largest_gre_issuer",
    "Liquid assets ratio":                  "liquid_assets_ratio",
    "Portfolio modified duration":          "portfolio_duration",
    "Portfolio duration":                   "portfolio_duration",
    "Portfolio DV01":                       "portfolio_dv01",
}


@dataclass(frozen=True)
class ReconcileResult:
    figure: str
    expected_value: str
    computed_value: str
    expected_utilization: str
    computed_utilization: str
    expected_status: str
    computed_status: str
    delta: str
    passed: bool


def parse_answer_key_xlsx(xlsx_path: str) -> dict[str, dict]:
    """Parse Firm A answer key xlsx → {figure_id: {value, utilization, status}}.

    Handles columns: Section, Metric, Value, Limit, Utilization, Status, Source.
    Maps Metric names to figure_ids via _METRIC_TO_FIGURE_ID.
    Treats None/empty Utilization cell as 'n/a'.
    """
    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb.active
    result: dict[str, dict] = {}
    headers: list[str] | None = None

    for row in ws.iter_rows(values_only=True):
        if headers is None:
            headers = [str(c).strip() if c is not None else "" for c in row]
            continue
        if all(c is None for c in row):
            continue
        row_dict = dict(zip(headers, row))
        metric = str(row_dict.get("Metric", "") or "").strip()
        fig_id = _METRIC_TO_FIGURE_ID.get(metric)
        if not fig_id:
            continue

        raw_util = row_dict.get("Utilization")
        if raw_util is None or str(raw_util).strip().lower() in ("", "none", "n/a"):
            utilization = "n/a"
        else:
            utilization = str(raw_util).strip()

        result[fig_id] = {
            "value":       str(row_dict.get("Value", "") or "").strip(),
            "utilization": utilization,
            "status":      str(row_dict.get("Status", "") or "").strip(),
        }
    return result


def parse_expected_yaml(yaml_path: str) -> dict[str, dict]:
    """Parse firm_b_expected.yaml → {figure_id: {value, utilization, status}}.

    Expects YAML structure:
      figures:
        <figure_id>:
          value: "..."
          utilization: "..."
          status: "..."
    """
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    return data.get("figures", {})


def reconcile(figures: list[Figure], expected: dict[str, dict]) -> list[ReconcileResult]:
    """Per-figure exact match on value + utilization + status.

    Args:
        figures: Computed Figure objects from ComputeEngine.run_all().
        expected: Dict mapping figure_id → {value, utilization, status}.
                  utilization key is optional; missing → treated as 'n/a'.

    Returns:
        List of ReconcileResult, one per figure_id in expected (sorted).
        Passed when computed value == expected value AND
                    computed utilization == expected utilization AND
                    computed status == expected status.
        Delta string contains mismatch details when not passed.
    """
    results: list[ReconcileResult] = []
    computed_map: dict[str, Figure] = {f.figure: f for f in figures}

    for fig_id in sorted(expected.keys()):
        exp = expected[fig_id]
        comp = computed_map.get(fig_id)

        exp_val = str(exp.get("value", "MISSING")).strip()
        exp_util = str(exp.get("utilization", "n/a")).strip()
        exp_status = str(exp.get("status", "MISSING")).strip()

        comp_val = comp.value if comp is not None else "MISSING"
        comp_util = comp.utilization if comp is not None else "MISSING"
        comp_status = comp.status if comp is not None else "MISSING"

        value_match = exp_val == comp_val
        util_match = exp_util == comp_util
        status_match = exp_status == comp_status
        passed = value_match and util_match and status_match

        delta = ""
        if not passed:
            parts = []
            if not value_match:
                parts.append(f"value: expected={exp_val!r} got={comp_val!r}")
            if not util_match:
                parts.append(f"utilization: expected={exp_util!r} got={comp_util!r}")
            if not status_match:
                parts.append(f"status: expected={exp_status!r} got={comp_status!r}")
            delta = "; ".join(parts)

        results.append(ReconcileResult(
            figure=fig_id,
            expected_value=exp_val,
            computed_value=comp_val,
            expected_utilization=exp_util,
            computed_utilization=comp_util,
            expected_status=exp_status,
            computed_status=comp_status,
            delta=delta,
            passed=passed,
        ))

    return results
