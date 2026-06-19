# src/reconcile/reconciler.py
"""Reconcile computed figures against firm answer keys."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from src.compute.registry import Figure


@dataclass
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
    """Parse Firm A answer key xlsx → {figure_id: {value, status}}."""
    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb.active
    result: dict[str, dict] = {}
    headers = None
    for row in ws.iter_rows(values_only=True):
        if headers is None:
            headers = [str(c).strip() if c else "" for c in row]
            continue
        if row[0] is None:
            continue
        row_dict = dict(zip(headers, row))
        fig_id = str(row_dict.get("figure_id", "")).strip()
        if fig_id:
            result[fig_id] = {
                "value": str(row_dict.get("value", "")).strip(),
                "status": str(row_dict.get("status", "")).strip(),
            }
    return result


def parse_expected_yaml(yaml_path: str) -> dict[str, dict]:
    """Parse firm_b_expected.yaml → {figure_id: {value, status}}."""
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    return data.get("figures", {})


def reconcile(figures: list[Figure], expected: dict[str, dict]) -> list[ReconcileResult]:
    """Per-figure exact match on value+utilization+status. Returns list of ReconcileResult."""
    results: list[ReconcileResult] = []
    computed_map = {f.figure: f for f in figures}
    all_ids = set(expected.keys()) | set(computed_map.keys())
    for fig_id in sorted(all_ids):
        exp = expected.get(fig_id, {})
        comp = computed_map.get(fig_id)
        exp_val = exp.get("value", "MISSING")
        exp_util = exp.get("utilization", "MISSING")
        exp_status = exp.get("status", "MISSING")
        comp_val = comp.value if comp else "MISSING"
        comp_util = comp.utilization if comp else "MISSING"
        comp_status = comp.status if comp else "MISSING"
        passed = (exp_val == comp_val and exp_util == comp_util and exp_status == comp_status)
        delta = ""
        if not passed:
            delta = f"expected ({exp_val}, {exp_util}, {exp_status}), got ({comp_val}, {comp_util}, {comp_status})"
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
