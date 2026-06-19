"""InterOpera compliance CLI — all subcommands."""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="interopera", help="InterOpera fund compliance reporting CLI")
console = Console()

REPO_ROOT = Path(__file__).parent.parent.parent
CONFIG_DIR = REPO_ROOT / "config"
SAMPLE_DOCS = REPO_ROOT / "sample_docs"
OUT_DIR = REPO_ROOT / "out"


def _get_driver():
    from neo4j import GraphDatabase
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "password")
    return GraphDatabase.driver(uri, auth=(user, password))


@app.command()
def ingest(
    holdings: str = typer.Option(str(SAMPLE_DOCS / "sample_holdings.csv"), help="Holdings CSV path"),
    guidelines: Optional[str] = typer.Option(None, help="Guidelines PDF path"),
):
    """Parse holdings CSV and guidelines PDF."""
    from src.ingestion.holdings_parser import parse_holdings
    from src.ingestion.guidelines_parser import parse_guidelines
    positions = parse_holdings(holdings)
    console.print(f"Parsed {len(positions)} positions from {holdings}")
    chunks = parse_guidelines(pdf_path=guidelines, llm_client=None)
    console.print(f"Parsed {len(chunks)} rule chunks")


@app.command(name="build-graph")
def build_graph(
    holdings: str = typer.Option(str(SAMPLE_DOCS / "sample_holdings.csv")),
    guidelines: Optional[str] = typer.Option(None),
):
    """Build Neo4j knowledge graph from holdings and guidelines."""
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions, load_rules
    from src.ingestion.holdings_parser import parse_holdings
    from src.ingestion.guidelines_parser import parse_guidelines
    driver = _get_driver()
    apply_schema(driver)
    positions = parse_holdings(holdings)
    load_positions(driver, positions)
    console.print(f"Loaded {len(positions)} positions into graph")
    chunks = parse_guidelines(pdf_path=guidelines, llm_client=None)
    load_rules(driver, chunks)
    console.print(f"Loaded {len(chunks)} rule chunks into graph")
    driver.close()


@app.command(name="verify-graph")
def verify_graph(
    approve_all: bool = typer.Option(False, "--approve-all"),
    approve: Optional[str] = typer.Option(None, "--approve"),
    actor: str = typer.Option("cli_user", help="Actor name for approval"),
):
    """List PENDING_REVIEW nodes and optionally approve them."""
    from src.graph.queries import list_pending_nodes, approve_node
    driver = _get_driver()
    pending = list_pending_nodes(driver)
    if not pending:
        console.print("[green]All nodes are VERIFIED.[/green]")
        driver.close()
        return
    table = Table("Node ID", "Labels", "Confidence")
    for n in pending:
        table.add_row(str(n["node_id"]), str(n["labels"]), str(n.get("confidence", "?")))
    console.print(table)
    if approve_all:
        for n in pending:
            approve_node(driver, n["node_id"], actor=actor)
        console.print(f"[green]Approved {len(pending)} nodes as {actor}[/green]")
    elif approve:
        approve_node(driver, approve, actor=actor)
        console.print(f"[green]Approved {approve} as {actor}[/green]")
    driver.close()


@app.command(name="run")
def run_cmd(
    firm: str = typer.Option(..., help="Firm ID: A or B"),
    output_json: bool = typer.Option(False, "--json"),
):
    """Compute all 13 compliance figures and write report."""
    from src.compute.config_loader import load_config, effective_config_hash
    from src.compute.engine import ComputeEngine
    from src.report.writer import write_report

    firm_id = f"firm_{firm.lower()}"
    config = load_config(
        str(CONFIG_DIR / "base.yaml"),
        str(CONFIG_DIR / f"{firm_id}.yaml"),
    )
    driver = _get_driver()
    engine = ComputeEngine(driver, config)
    run_id = str(uuid.uuid4())
    figures = engine.run_all()

    OUT_DIR.mkdir(exist_ok=True)
    figures_data = [
        {"figure": f.figure, "value": f.value, "status": f.status,
         "limit": f.limit, "graph_path": f.graph_path, "citation": f.citation}
        for f in figures
    ]
    figures_path = OUT_DIR / f"figures_{firm_id}.json"
    figures_path.write_text(json.dumps(figures_data, indent=2, sort_keys=True))

    report_path = OUT_DIR / f"report_{firm_id}.xlsx"
    write_report(figures, str(report_path))

    if output_json:
        console.print(json.dumps(figures_data, indent=2))
    else:
        table = Table("Figure", "Value", "Status", "Limit")
        for f in figures:
            color = "red" if f.status == "BREACH" else ("yellow" if f.status == "AT LIMIT" else "green")
            table.add_row(f.figure, f.value, f"[{color}]{f.status}[/{color}]", f.limit)
        console.print(table)
        console.print(f"Report written to {report_path}")

    driver.close()


@app.command()
def reconcile(
    firm: str = typer.Option(..., help="Firm ID: A or B"),
    output_json: bool = typer.Option(False, "--json"),
):
    """Reconcile computed figures against firm answer key."""
    from src.compute.config_loader import load_config
    from src.compute.engine import ComputeEngine
    from src.reconcile.reconciler import reconcile as do_reconcile, parse_answer_key_xlsx, parse_expected_yaml

    firm_id = f"firm_{firm.lower()}"
    config = load_config(
        str(CONFIG_DIR / "base.yaml"),
        str(CONFIG_DIR / f"{firm_id}.yaml"),
    )
    driver = _get_driver()
    figures = ComputeEngine(driver, config).run_all()
    driver.close()

    if firm.upper() == "A":
        xlsx_path = str(SAMPLE_DOCS / "firm_A_answer_key.xlsx")
        expected = parse_answer_key_xlsx(xlsx_path)
    else:
        yaml_path = str(CONFIG_DIR / "firm_b_expected.yaml")
        expected = parse_expected_yaml(yaml_path)

    results = do_reconcile(figures, expected)
    failed = [r for r in results if not r.passed]

    if output_json:
        console.print(json.dumps([r.__dict__ for r in results], indent=2))
    else:
        table = Table("Figure", "Expected", "Computed", "Status", "Delta")
        for r in results:
            color = "green" if r.passed else "red"
            table.add_row(r.figure, r.expected_value, r.computed_value,
                         f"[{color}]{'PASS' if r.passed else 'FAIL'}[/{color}]",
                         r.delta)
        console.print(table)

    if failed:
        console.print(f"[red]{len(failed)} reconcile failure(s)[/red]")
        raise typer.Exit(code=1)


@app.command()
def evaluate(
    firm: str = typer.Option(..., help="Firm ID: A or B"),
    output_json: bool = typer.Option(False, "--json"),
):
    """Full Phase 5: reconcile + traceability + firewall + determinism."""
    from src.compute.config_loader import load_config
    from src.compute.engine import ComputeEngine
    from src.reconcile.reconciler import reconcile as do_reconcile, parse_answer_key_xlsx, parse_expected_yaml
    from src.firewall.checker import check_firewall
    from src.narrative.narrator import Narrator

    firm_id = f"firm_{firm.lower()}"
    config = load_config(
        str(CONFIG_DIR / "base.yaml"),
        str(CONFIG_DIR / f"{firm_id}.yaml"),
    )
    driver = _get_driver()
    figures = ComputeEngine(driver, config).run_all()
    driver.close()

    exit_code = 0

    # 1. Reconcile
    if firm.upper() == "A":
        expected = parse_answer_key_xlsx(str(SAMPLE_DOCS / "firm_A_answer_key.xlsx"))
    else:
        expected = parse_expected_yaml(str(CONFIG_DIR / "firm_b_expected.yaml"))
    recon_results = do_reconcile(figures, expected)
    recon_failed = [r for r in recon_results if not r.passed]
    if recon_failed:
        exit_code = 1
        console.print(f"[red]Reconcile FAIL: {len(recon_failed)} figures mismatch[/red]")

    # 2. Traceability
    trace_failed = [f for f in figures if not f.graph_path or not f.citation.get("chunk_id")]
    if trace_failed:
        exit_code = 1
        console.print(f"[red]Traceability FAIL: {[f.figure for f in trace_failed]}[/red]")

    # 3. Firewall
    narrator = Narrator(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    narrative = narrator.write_narrative(figures, firm_id=firm_id)
    fw_result = check_firewall(narrative, figures)
    if not fw_result.passed:
        exit_code = 1
        console.print(f"[red]Firewall FAIL: {fw_result.offending_numbers}[/red]")

    if output_json:
        OUT_DIR.mkdir(exist_ok=True)
        report = {
            "firm_id": firm_id,
            "reconcile": {
                "passed": len(recon_failed) == 0,
                "total": len(recon_results),
                "failed": [r.__dict__ for r in recon_failed],
                "results": [r.__dict__ for r in recon_results],
            },
            "traceability": {
                "passed": len(trace_failed) == 0,
                "failed_figures": [f.figure for f in trace_failed],
            },
            "firewall": {
                "passed": fw_result.passed,
                "offending_numbers": fw_result.offending_numbers,
            },
            "overall_passed": exit_code == 0,
        }
        report_path = OUT_DIR / f"evaluate_{firm_id}.json"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True))
        console.print(json.dumps(report, indent=2))
    else:
        # Emit table and JSON summary
        table = Table("Check", "Result", "Details")
        recon_status = "PASS" if not recon_failed else f"FAIL ({len(recon_failed)} mismatches)"
        trace_status = "PASS" if not trace_failed else f"FAIL ({[f.figure for f in trace_failed]})"
        fw_status = "PASS" if fw_result.passed else f"FAIL ({fw_result.offending_numbers})"
        table.add_row("Reconcile", f"[{'green' if not recon_failed else 'red'}]{recon_status}[/]",
                      f"{len(recon_results) - len(recon_failed)}/{len(recon_results)} figures match")
        table.add_row("Traceability", f"[{'green' if not trace_failed else 'red'}]{trace_status}[/]",
                      "graph_path + chunk_id present for all figures")
        table.add_row("Firewall", f"[{'green' if fw_result.passed else 'red'}]{fw_status}[/]",
                      "narrative contains only computed numbers")
        console.print(table)

        if exit_code == 0:
            console.print("[green]All Phase 5 checks PASSED[/green]")
        else:
            console.print("[red]Phase 5 FAILED — see above[/red]")

    raise typer.Exit(code=exit_code)


@app.command(name="verify-determinism")
def verify_determinism(
    firm: str = typer.Option(..., help="Firm ID: A or B"),
):
    """Run engine twice and assert byte-identical figures.json output."""
    from src.compute.config_loader import load_config
    from src.compute.engine import ComputeEngine

    firm_id = f"firm_{firm.lower()}"
    config = load_config(
        str(CONFIG_DIR / "base.yaml"),
        str(CONFIG_DIR / f"{firm_id}.yaml"),
    )
    driver = _get_driver()
    engine = ComputeEngine(driver, config)

    run1 = engine.run_all()
    run2 = engine.run_all()
    driver.close()

    def to_json(figures) -> str:
        return json.dumps(
            [{"figure": f.figure, "value": f.value, "status": f.status,
              "limit": f.limit, "graph_path": f.graph_path, "citation": f.citation} for f in figures],
            sort_keys=True, indent=2
        )

    j1 = to_json(run1)
    j2 = to_json(run2)

    if j1 == j2:
        console.print("[green]DETERMINISM PASS: both runs are identical[/green]")
    else:
        console.print("[red]DETERMINISM FAIL: runs differ[/red]")
        import difflib
        diff = list(difflib.unified_diff(j1.splitlines(), j2.splitlines(), lineterm=""))
        for line in diff[:40]:
            console.print(line)
        raise typer.Exit(code=1)


@app.command()
def narrate(
    firm: str = typer.Option(..., help="Firm ID: A or B"),
):
    """Generate narrative and run firewall check."""
    from src.compute.config_loader import load_config
    from src.compute.engine import ComputeEngine
    from src.narrative.narrator import Narrator
    from src.firewall.checker import check_firewall

    firm_id = f"firm_{firm.lower()}"
    config = load_config(
        str(CONFIG_DIR / "base.yaml"),
        str(CONFIG_DIR / f"{firm_id}.yaml"),
    )
    driver = _get_driver()
    figures = ComputeEngine(driver, config).run_all()
    driver.close()

    narrator = Narrator(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    narrative = narrator.write_narrative(figures, firm_id=firm_id)
    fw_result = check_firewall(narrative, figures)

    console.print(narrative)
    if fw_result.passed:
        console.print("[green]Firewall PASS[/green]")
    else:
        console.print(f"[red]Firewall FAIL: {fw_result.offending_numbers}[/red]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
