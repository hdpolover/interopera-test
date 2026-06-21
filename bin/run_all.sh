#!/usr/bin/env bash
set -euo pipefail

# Resolve repo root regardless of working directory
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "========================================================"
echo "  InterOpera Compliance Reporting — Full Pipeline Run"
echo "========================================================"
echo ""

echo ">>> [1/7] Building Neo4j knowledge graph..."
python -m src.cli.main build-graph

echo ""
echo ">>> [2/7] Running compute + report for Firm A..."
python -m src.cli.main run --firm A

echo ""
echo ">>> [3/7] Evaluating Firm A (reconcile + traceability + firewall)..."
python -m src.cli.main evaluate --firm A --json

echo ""
echo ">>> [4/7] Running compute + report for Firm B..."
python -m src.cli.main run --firm B

echo ""
echo ">>> [5/7] Evaluating Firm B (reconcile + traceability + firewall)..."
python -m src.cli.main evaluate --firm B --json

echo ""
echo ">>> [6/7] Running compute + report for Firm C..."
python -m src.cli.main run --firm C

echo ""
echo ">>> [7/7] Evaluating Firm C (reconcile + traceability + firewall)..."
python -m src.cli.main evaluate --firm C --json

echo ""
echo "========================================================"
echo "  Pipeline complete. Output files:"
echo "========================================================"
ls -1 out/report_firm_*.xlsx out/figures_firm_*.json out/evaluate_firm_*.json 2>/dev/null || echo "  (no output files found under out/)"
