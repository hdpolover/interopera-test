# src/report/writer.py
"""Report writer — produces xlsx from computed figures list only."""
from __future__ import annotations

from src.compute.registry import Figure


def write_report(figures: list[Figure], output_path: str) -> None:
    """Write compliance figures to xlsx. Reads only from figures list, not narrative."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Compliance Report"
    headers = ["Figure", "Value", "Status", "Limit", "GraphPath", "Citation"]
    ws.append(headers)
    for fig in figures:
        ws.append([
            fig.figure,
            fig.value,
            fig.status,
            fig.limit,
            fig.graph_path,
            str(fig.citation),
        ])
    wb.save(output_path)
