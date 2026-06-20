"""Helpers for the replay CLI command.

Extracted from main.py to reduce file size while keeping the command
function itself in main.py (required for monkeypatching in tests).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()

# Mapping from figure_id → list of metric names in the answer key.
# Inverse of reconciler._METRIC_TO_FIGURE_ID, using canonical template metric names.
#
# Why hardcoded: translation table between two fixed external schemas —
# internal figure IDs (FIGURE_REGISTRY) and XLSX column headers from the brief.
# Neither side is user-defined; both are fixed by spec. Deriving dynamically
# would require embedding display_names in FigureSpec (coupling presentation
# into compute layer) or fuzzy-matching XLSX headers at runtime — both add
# complexity for no benefit on a fixed 13-figure set.
#
# To make it dynamic: add `display_names: list[str]` to FigureSpec in
# registry.py, then build here:
#   {spec.id: spec.display_names for spec in FIGURE_REGISTRY}
FIGURE_ID_TO_METRICS: dict[str, list[str]] = {
    "allocation_sgs":                    ["Singapore Government Securities"],
    "allocation_mas_bills":              ["MAS Bills"],
    "allocation_ig_corp":                ["Investment Grade Corporate Bonds"],
    "allocation_high_yield":             ["High Yield Bonds"],
    "allocation_fx_bonds":               ["Foreign Currency Bonds (hedged)", "Foreign Currency Bonds"],
    "allocation_structured_credit":      ["Structured Credit (ABS/MBS)", "Structured Credit"],
    "allocation_cash":                   ["Cash & Cash Equivalents"],
    "aggregate_non_ig_exposure":         ["Aggregate non-IG exposure"],
    "largest_single_corporate_issuer":   ["Largest single corporate issuer"],
    "largest_gre_issuer":                ["Largest GRE issuer"],
    "liquid_assets_ratio":               ["Liquid assets ratio"],
    "portfolio_duration":                ["Portfolio modified duration", "Portfolio duration"],
    "portfolio_dv01":                    ["Portfolio DV01"],
}

# Guard: fail loudly if FIGURE_REGISTRY grows but this mapping isn't updated.
from src.compute.registry import FIGURE_REGISTRY as _REGISTRY  # noqa: E402

_REGISTRY_IDS = {spec.id for spec in _REGISTRY}
if set(FIGURE_ID_TO_METRICS.keys()) != _REGISTRY_IDS:
    raise ValueError(
        f"FIGURE_ID_TO_METRICS out of sync with FIGURE_REGISTRY.\n"
        f"  Missing from mapping : {_REGISTRY_IDS - set(FIGURE_ID_TO_METRICS.keys())}\n"
        f"  Stale in mapping     : {set(FIGURE_ID_TO_METRICS.keys()) - _REGISTRY_IDS}"
    )

# Config knobs that affect each figure.
FIGURE_CONFIG_KNOBS: dict[str, list[str]] = {
    "aggregate_non_ig_exposure": ["non_ig.include_fallen_angels"],
    "largest_gre_issuer":        ["concentration.gre.group_key"],
}


def parse_numeric(value_str: str) -> Optional[float]:
    """Strip common units and return a float, or None if parsing fails."""
    if value_str is None:
        return None
    cleaned = (
        str(value_str)
        .replace("%", "")
        .replace("yrs", "")
        .replace("SGD", "")
        .replace(",", "")
        .replace("/bp", "")
        .strip()
    )
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def print_delta_vs_answer_key(firm: str, figure: str, match: dict, sample_docs: Path) -> None:
    """Print delta vs answer key section of the replay output."""
    if firm.upper() == "A":
        xlsx_path = sample_docs / "firm_A_answer_key.xlsx"
        if xlsx_path.exists():
            _print_delta_firm_a(figure, match, xlsx_path)
        else:
            console.print(f"\n[yellow]Answer key file not found at {xlsx_path}[/yellow]")
    else:
        console.print("\n[dim]Note: no answer key available for Firm B — delta comparison skipped.[/dim]")


def _print_delta_firm_a(figure: str, match: dict, xlsx_path: Path) -> None:
    """Compute and print delta for a Firm A figure against the xlsx answer key."""
    import openpyxl

    wb = openpyxl.load_workbook(str(xlsx_path), read_only=True)
    try:
        ws = wb.active
        headers: Optional[list[str]] = None
        metric_names = FIGURE_ID_TO_METRICS.get(figure, [])
        expected_value: Optional[str] = None
        for row in ws.iter_rows(values_only=True):
            if headers is None:
                headers = [str(c).strip() if c is not None else "" for c in row]
                continue
            if all(c is None for c in row):
                continue
            row_dict = dict(zip(headers, row))
            metric = str(row_dict.get("Metric", "") or "").strip()
            if metric in metric_names:
                expected_value = str(row_dict.get("Value", "") or "").strip()
                break
    finally:
        wb.close()
    if expected_value is not None:
        computed_value = match.get("value", "N/A")
        exp_num = parse_numeric(expected_value)
        comp_num = parse_numeric(computed_value)
        delta_str = f"{comp_num - exp_num:+.4g}" if (exp_num is not None and comp_num is not None) else "N/A"
        console.print(
            f"\n[bold]Delta vs answer key:[/bold]\n"
            f"  Expected: {expected_value}\n"
            f"  Computed: {computed_value}\n"
            f"  Delta:    {delta_str}"
        )
    else:
        console.print(f"\n[yellow]No answer key row found for figure '{figure}'[/yellow]")


def print_config_knobs(firm_id: str, figure: str, config_dir: Path) -> None:
    """Print config rules affecting the given figure."""
    import yaml as _yaml

    firm_yaml = config_dir / f"{firm_id}.yaml"
    config_dict: dict = {}
    if firm_yaml.exists():
        with open(firm_yaml) as fh:
            config_dict = _yaml.safe_load(fh) or {}

    base_yaml = config_dir / "base.yaml"
    base_dict: dict = {}
    if base_yaml.exists():
        with open(base_yaml) as fh:
            base_dict = _yaml.safe_load(fh) or {}

    knobs = FIGURE_CONFIG_KNOBS.get(figure, [])
    all_knobs = knobs + ["output.utilization_format"]

    console.print("\n[bold]Config rules affecting this figure:[/bold]")
    for knob in all_knobs:
        parts = knob.split(".")
        val: object = config_dict
        for p in parts:
            val = val.get(p, {}) if isinstance(val, dict) else None
        console.print(f"  {knob} = {val}")

    limits = base_dict.get("limits", {})
    fig_limit = limits.get(figure)
    if fig_limit:
        console.print(f"  limit ({figure}) = {fig_limit}")
