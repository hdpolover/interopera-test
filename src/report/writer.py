# src/report/writer.py
"""Report writer — produces xlsx from computed figures list only.

Columns match sample_docs/report_template.xlsx exactly:
  Section | Metric | Value | Limit | Utilization | Status | Source (graph path → doc/page)

13 metric rows, one per figure spec in FIGURE_REGISTRY.
All cells sourced exclusively from the figures list — no narrative/LLM input.
"""
from __future__ import annotations

from src.compute.registry import Figure

# Ordered list of (section, metric_label, figure_id) matching report_template.xlsx row order.
# Inverse of reconciler._METRIC_TO_FIGURE_ID, using the canonical template metric names.
_TEMPLATE_ROWS: list[tuple[str, str, str]] = [
    ("Allocation",    "Singapore Government Securities",      "allocation_sgs"),
    ("Allocation",    "MAS Bills",                            "allocation_mas_bills"),
    ("Allocation",    "Investment Grade Corporate Bonds",     "allocation_ig_corp"),
    ("Allocation",    "High Yield Bonds",                     "allocation_high_yield"),
    ("Allocation",    "Foreign Currency Bonds (hedged)",      "allocation_fx_bonds"),
    ("Allocation",    "Structured Credit (ABS/MBS)",          "allocation_structured_credit"),
    ("Allocation",    "Cash & Cash Equivalents",              "allocation_cash"),
    ("Aggregate",     "Aggregate non-IG exposure",            "aggregate_non_ig_exposure"),
    ("Concentration", "Largest single corporate issuer",      "largest_single_corporate_issuer"),
    ("Concentration", "Largest GRE issuer",                   "largest_gre_issuer"),
    ("Liquidity",     "Liquid assets ratio",                  "liquid_assets_ratio"),
    ("Market risk",   "Portfolio modified duration",          "portfolio_duration"),
    ("Market risk",   "Portfolio DV01",                       "portfolio_dv01"),
]

_HEADERS: list[str] = [
    "Section",
    "Metric",
    "Value",
    "Limit",
    "Utilization",
    "Status",
    "Source (graph path → doc/page)",
]


def _build_source(fig: Figure) -> str:
    """Build the Source cell content from graph_path and citation fields only."""
    parts: list[str] = []
    if fig.graph_path:
        parts.append(fig.graph_path)
    citation = fig.citation or {}
    source_doc = citation.get("source_doc", "")
    page = citation.get("page", "")
    chunk_id = citation.get("chunk_id", "")
    citation_parts: list[str] = []
    if source_doc:
        page_str = f" p.{page}" if page != "" else ""
        citation_parts.append(f"{source_doc}{page_str}")
    if chunk_id:
        citation_parts.append(str(chunk_id))
    if citation_parts:
        parts.append(" ".join(citation_parts))
    return " | ".join(parts)


def write_report(figures: list[Figure], output_path: str) -> None:
    """Write compliance figures to xlsx following the report_template.xlsx structure.

    Reads only from the figures list — no narrative or LLM input.
    Produces exactly 13 data rows (one per template metric) plus a header row.

    Formatting applied:
    - Header row: bold + light gray fill (#EEEEEE)
    - BREACH rows: red background (#FF4444) + white text
    - AT LIMIT rows: amber background (#FFAA00) + white text
    - OK rows: green background (#00AA44) + white text
    - Auto-fit column widths based on max content length

    Args:
        figures: Computed Figure objects, keyed by figure.figure (figure_id).
        output_path: Destination .xlsx file path.
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment

    # Status → fill/font styles
    _STATUS_FILL = {
        "BREACH":   PatternFill(fill_type="solid", fgColor="FF4444"),
        "AT LIMIT": PatternFill(fill_type="solid", fgColor="FFAA00"),
        "OK":       PatternFill(fill_type="solid", fgColor="00AA44"),
    }
    _WHITE_FONT = Font(color="FFFFFF")
    _HEADER_FILL = PatternFill(fill_type="solid", fgColor="EEEEEE")
    _HEADER_FONT = Font(bold=True)

    # Build lookup: figure_id → Figure
    fig_map: dict[str, Figure] = {f.figure: f for f in figures}

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Report"

    # Write and style header row
    ws.append(_HEADERS)
    header_row = ws[1]
    for cell in header_row:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center")

    # Write data rows with status-based highlighting
    for section, metric, fig_id in _TEMPLATE_ROWS:
        fig = fig_map.get(fig_id)
        if fig is not None:
            row_data = [
                section,
                metric,
                fig.value,
                fig.limit,
                fig.utilization,
                fig.status,
                _build_source(fig),
            ]
            status = fig.status
        else:
            row_data = [section, metric, None, None, None, None, None]  # type: ignore[list-item]
            status = None
        ws.append(row_data)

        # Apply status highlight to the entire row
        if status in _STATUS_FILL:
            fill = _STATUS_FILL[status]
            font = _WHITE_FONT
            current_row = ws[ws.max_row]
            for cell in current_row:
                cell.fill = fill
                cell.font = font

    # Auto-fit column widths: max content length + 4 padding
    for col_cells in ws.columns:
        max_len = 0
        for cell in col_cells:
            cell_value = cell.value
            if cell_value is not None:
                max_len = max(max_len, len(str(cell_value)))
        col_letter = col_cells[0].column_letter
        ws.column_dimensions[col_letter].width = max_len + 4

    wb.save(output_path)
