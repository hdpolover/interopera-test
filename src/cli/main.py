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


def _make_audit_logger(run_id: str):
    """Return an AuditLogger bound to the current POSTGRES_DSN, or None.

    Graceful degradation: if POSTGRES_DSN is unset or the DB is unreachable,
    prints a warning to stderr and returns None.  Callers check for None before
    logging so the rest of the pipeline always succeeds.
    """
    from src.audit.log import AuditLogger
    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        typer.echo("Warning: POSTGRES_DSN not set — audit logging disabled", err=True)
        return None
    try:
        return AuditLogger(dsn)
    except Exception as exc:  # pragma: no cover
        typer.echo(f"Warning: audit DB unreachable ({exc}) — audit logging disabled", err=True)
        return None


def _audit_log(logger, run_id: str, event_type: str, actor: str, payload: dict, config_hash: Optional[str] = None) -> None:
    """Log an audit event, silently swallowing errors so the pipeline is never blocked."""
    if logger is None:
        return
    try:
        logger.log_event(run_id, event_type, actor, payload, config_hash=config_hash)
    except Exception as exc:  # pragma: no cover
        typer.echo(f"Warning: audit log write failed ({exc})", err=True)


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
    from src.graph.builder import load_positions, load_rules, load_risk_metrics
    from src.ingestion.holdings_parser import parse_holdings
    from src.ingestion.guidelines_parser import parse_guidelines
    run_id = str(uuid.uuid4())
    audit = _make_audit_logger(run_id)
    driver = _get_driver()
    apply_schema(driver)
    positions = parse_holdings(holdings)
    load_positions(driver, positions)
    console.print(f"Loaded {len(positions)} positions into graph")
    chunks = parse_guidelines(pdf_path=guidelines, llm_client=None)
    load_rules(driver, chunks)
    load_risk_metrics(driver, chunks)
    console.print(f"Loaded {len(chunks)} rule chunks into graph")
    driver.close()
    _audit_log(
        audit, run_id, "graph_construction", "cli",
        {"position_count": len(positions), "rule_chunk_count": len(chunks)},
    )
    if audit is not None:
        audit.close()


@app.command(name="verify-graph")
def verify_graph(
    approve_all: bool = typer.Option(False, "--approve-all"),
    approve: Optional[str] = typer.Option(None, "--approve"),
    actor: str = typer.Option("cli_user", help="Actor name for approval"),
):
    """List PENDING_REVIEW nodes and optionally approve them."""
    from src.graph.queries import list_pending_nodes, approve_node
    run_id = str(uuid.uuid4())
    audit = _make_audit_logger(run_id)
    driver = _get_driver()
    pending = list_pending_nodes(driver)
    if not pending:
        console.print("[green]All nodes are VERIFIED.[/green]")
        driver.close()
        if audit is not None:
            audit.close()
        return
    table = Table("Node ID", "Labels", "Confidence")
    for n in pending:
        table.add_row(str(n["node_id"]), str(n["labels"]), str(n.get("confidence", "?")))
    console.print(table)
    if approve_all:
        for n in pending:
            approve_node(driver, n["node_id"], actor=actor)
            _audit_log(
                audit, run_id, "node_verified", actor,
                {"node_id": n["node_id"], "labels": n.get("labels")},
            )
        console.print(f"[green]Approved {len(pending)} nodes as {actor}[/green]")
    elif approve:
        approve_node(driver, approve, actor=actor)
        _audit_log(
            audit, run_id, "node_verified", actor,
            {"node_id": approve},
        )
        console.print(f"[green]Approved {approve} as {actor}[/green]")
    driver.close()
    if audit is not None:
        audit.close()


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
    firm_yaml = CONFIG_DIR / f"{firm_id}.yaml"
    if not firm_yaml.exists():
        typer.echo(f"Error: no config found for firm '{firm}' (expected {firm_yaml})", err=True)
        raise typer.Exit(code=1)
    try:
        config = load_config(
            str(CONFIG_DIR / "base.yaml"),
            str(firm_yaml),
        )
    except Exception as exc:
        typer.echo(f"Error: failed to load config for firm '{firm}': {exc}", err=True)
        raise typer.Exit(code=1)

    run_id = str(uuid.uuid4())
    audit = _make_audit_logger(run_id)
    cfg_hash = effective_config_hash(config)

    _audit_log(
        audit, run_id, "config_loaded", "cli",
        {"firm_id": firm_id, "config_hash": cfg_hash},
        config_hash=cfg_hash,
    )

    driver = _get_driver()
    engine = ComputeEngine(driver, config)
    figures = engine.run_all()

    OUT_DIR.mkdir(exist_ok=True)
    figures_data = [
        {"figure": f.figure, "value": f.value, "utilization": f.utilization,
         "status": f.status, "limit": f.limit, "graph_path": f.graph_path,
         "citation": f.citation}
        for f in figures
    ]
    figures_path = OUT_DIR / f"figures_{firm_id}.json"
    figures_path.write_text(json.dumps(figures_data, indent=2, sort_keys=True))

    # Log one figure_computed event per figure
    for f in figures:
        _audit_log(
            audit, run_id, "figure_computed", "cli",
            {
                "figure": f.figure,
                "value": f.value,
                "status": f.status,
                "graph_path": f.graph_path,
                "chunk_id": f.citation.get("chunk_id") if isinstance(f.citation, dict) else None,
            },
            config_hash=cfg_hash,
        )

    report_path = OUT_DIR / f"report_{firm_id}.xlsx"
    write_report(figures, str(report_path))

    _audit_log(
        audit, run_id, "report_exported", "cli",
        {"output_path": str(report_path)},
        config_hash=cfg_hash,
    )

    if audit is not None:
        audit.close()

    if output_json:
        typer.echo(json.dumps(figures_data, indent=2))
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
    firm_yaml = CONFIG_DIR / f"{firm_id}.yaml"
    if not firm_yaml.exists():
        typer.echo(f"Error: no config found for firm '{firm}' (expected {firm_yaml})", err=True)
        raise typer.Exit(code=1)
    try:
        config = load_config(
            str(CONFIG_DIR / "base.yaml"),
            str(firm_yaml),
        )
    except Exception as exc:
        typer.echo(f"Error: failed to load config for firm '{firm}': {exc}", err=True)
        raise typer.Exit(code=1)

    run_id = str(uuid.uuid4())
    audit = _make_audit_logger(run_id)

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

    _audit_log(
        audit, run_id, "reconciliation", "cli",
        {"firm": firm_id, "pass_count": len(results) - len(failed), "fail_count": len(failed)},
    )
    if audit is not None:
        audit.close()

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
    firm_yaml = CONFIG_DIR / f"{firm_id}.yaml"
    if not firm_yaml.exists():
        typer.echo(f"Error: no config found for firm '{firm}' (expected {firm_yaml})", err=True)
        raise typer.Exit(code=1)
    try:
        config = load_config(
            str(CONFIG_DIR / "base.yaml"),
            str(firm_yaml),
        )
    except Exception as exc:
        typer.echo(f"Error: failed to load config for firm '{firm}': {exc}", err=True)
        raise typer.Exit(code=1)

    run_id = str(uuid.uuid4())
    audit = _make_audit_logger(run_id)

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

    _audit_log(
        audit, run_id, "reconciliation", "cli",
        {
            "firm": firm_id,
            "pass_count": len(recon_results) - len(recon_failed),
            "fail_count": len(recon_failed),
        },
    )
    if audit is not None:
        audit.close()

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
            [{"figure": f.figure, "value": f.value, "utilization": f.utilization,
              "status": f.status, "limit": f.limit, "graph_path": f.graph_path,
              "citation": f.citation} for f in figures],
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

    narrator = Narrator(api_key=os.environ.get("ANTHROPIC_API_KEY"), driver=driver)
    narrative = narrator.write_narrative(figures, firm_id=firm_id)
    fw_result = check_firewall(narrative, figures)
    driver.close()

    console.print(narrative)
    if fw_result.passed:
        console.print("[green]Firewall PASS[/green]")
    else:
        console.print(f"[red]Firewall FAIL: {fw_result.offending_numbers}[/red]")
        raise typer.Exit(code=1)


def _parse_numeric(value_str: str) -> Optional[float]:
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


# Mapping from figure_id → list of metric names in the answer key
_FIGURE_ID_TO_METRICS: dict[str, list[str]] = {
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

# Config knobs that affect each figure
_FIGURE_CONFIG_KNOBS: dict[str, list[str]] = {
    "aggregate_non_ig_exposure": ["non_ig.include_fallen_angels"],
    "largest_gre_issuer":        ["concentration.gre.group_key"],
}


@app.command()
def replay(
    figure: str = typer.Option(..., help="Figure name, e.g. allocation_sgs"),
    firm: str = typer.Option(..., help="Firm ID: A or B"),
) -> None:
    """Replay a figure: show graph path, citation, delta vs answer key, and config rule."""
    firm_id = f"firm_{firm.lower()}"
    figures_path = OUT_DIR / f"figures_{firm_id}.json"

    if not figures_path.exists():
        typer.echo(
            f"Error: figures file not found at {figures_path}. "
            f"Run 'run --firm {firm.upper()}' first to compute figures.",
            err=True,
        )
        raise typer.Exit(code=1)

    figures_data: list[dict] = json.loads(figures_path.read_text())
    match = next((f for f in figures_data if f.get("figure") == figure), None)

    if match is None:
        available = [f.get("figure", "") for f in figures_data]
        typer.echo(
            f"Error: figure '{figure}' not found in {figures_path}. "
            f"Available figures: {available}",
            err=True,
        )
        raise typer.Exit(code=1)

    # --- Graph path ---
    console.print(f"\n[bold]Figure:[/bold] {figure}")
    console.print(f"[bold]Graph path:[/bold] {match.get('graph_path', 'N/A')}")

    # --- Source passage ---
    citation: dict = match.get("citation") or {}
    console.print(f"[bold]Source passage:[/bold] {citation.get('passage_summary', 'N/A')}")
    console.print(f"[bold]Chunk ID:[/bold]       {citation.get('chunk_id', 'N/A')}")

    # --- Delta vs answer key ---
    if firm.upper() == "A":
        import openpyxl
        xlsx_path = SAMPLE_DOCS / "firm_A_answer_key.xlsx"
        if xlsx_path.exists():
            wb = openpyxl.load_workbook(str(xlsx_path), read_only=True)
            ws = wb.active
            headers: Optional[list[str]] = None
            metric_names = _FIGURE_ID_TO_METRICS.get(figure, [])
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
            if expected_value is not None:
                computed_value = match.get("value", "N/A")
                exp_num = _parse_numeric(expected_value)
                comp_num = _parse_numeric(computed_value)
                if exp_num is not None and comp_num is not None:
                    delta_str = f"{comp_num - exp_num:+.4g}"
                else:
                    delta_str = "N/A"
                console.print(
                    f"\n[bold]Delta vs answer key:[/bold]\n"
                    f"  Expected: {expected_value}\n"
                    f"  Computed: {computed_value}\n"
                    f"  Delta:    {delta_str}"
                )
            else:
                console.print(f"\n[yellow]No answer key row found for figure '{figure}'[/yellow]")
        else:
            console.print(f"\n[yellow]Answer key file not found at {xlsx_path}[/yellow]")
    else:
        console.print("\n[dim]Note: no answer key available for Firm B — delta comparison skipped.[/dim]")

    # --- Config rule ---
    firm_yaml = CONFIG_DIR / f"{firm_id}.yaml"
    import yaml as _yaml
    config_dict: dict = {}
    if firm_yaml.exists():
        with open(firm_yaml) as fh:
            config_dict = _yaml.safe_load(fh) or {}

    base_yaml = CONFIG_DIR / "base.yaml"
    base_dict: dict = {}
    if base_yaml.exists():
        with open(base_yaml) as fh:
            base_dict = _yaml.safe_load(fh) or {}

    knobs = _FIGURE_CONFIG_KNOBS.get(figure, [])
    # All figures are affected by utilization_format
    all_knobs = knobs + ["output.utilization_format"]

    console.print("\n[bold]Config rules affecting this figure:[/bold]")
    for knob in all_knobs:
        parts = knob.split(".")
        val = config_dict
        for p in parts:
            val = val.get(p, {}) if isinstance(val, dict) else None
        console.print(f"  {knob} = {val}")

    # Show relevant limit from base.yaml
    limits = base_dict.get("limits", {})
    fig_limit = limits.get(figure)
    if fig_limit:
        console.print(f"  limit ({figure}) = {fig_limit}")


@app.command(name="generate-dsl")
def generate_dsl(
    firm: str = typer.Option(..., help="Firm ID: A or B"),
) -> None:
    """Write the current firm config as a DSL file to stdout with comments."""
    import yaml as _yaml

    firm_id = f"firm_{firm.lower()}"
    firm_yaml = CONFIG_DIR / f"{firm_id}.yaml"

    if not firm_yaml.exists():
        typer.echo(f"Error: no config found for firm '{firm}' (expected {firm_yaml})", err=True)
        raise typer.Exit(code=1)

    with open(firm_yaml) as fh:
        config_dict = _yaml.safe_load(fh) or {}

    firm_id_val = config_dict.get("firm_id", firm_id)
    include_fallen_angels = config_dict.get("non_ig", {}).get("include_fallen_angels", False)
    group_key = config_dict.get("concentration", {}).get("gre", {}).get("group_key", "issuer")
    utilization_format = config_dict.get("output", {}).get("utilization_format", "percent_1dp")

    dsl_lines = [
        "# InterOpera Config DSL",
        f"firm_id: {firm_id_val}",
        f"include_fallen_angels: {str(include_fallen_angels).lower()}"
        "   # adds fallen angels to non-IG aggregate",
        f"group_key: {group_key}"
        "              # groups GRE issuers by issuer or parent_issuer",
        f"utilization_format: {utilization_format}"
        "  # percent_1dp | truncated_bps",
    ]
    typer.echo("\n".join(dsl_lines))


@app.command(name="preview-config")
def preview_config(
    dsl: str = typer.Option(..., help="Path to .dsl file"),
) -> None:
    """Parse DSL, validate, run compute engine, print figures vs Firm A baseline."""
    import yaml as _yaml
    from src.compute.config_loader import FirmConfig, _deep_merge
    from src.compute.engine import ComputeEngine

    dsl_path = Path(dsl)
    if not dsl_path.exists():
        typer.echo(f"Error: DSL file not found at {dsl}", err=True)
        raise typer.Exit(code=1)

    with open(dsl_path) as fh:
        dsl_dict = _yaml.safe_load(fh) or {}

    # Extract knobs from DSL and build a FirmConfig-compatible dict
    dsl_firm_id = dsl_dict.get("firm_id", "custom")
    include_fallen_angels = dsl_dict.get("include_fallen_angels")
    group_key = dsl_dict.get("group_key")
    utilization_format = dsl_dict.get("utilization_format")

    # Load base limits
    base_yaml = CONFIG_DIR / "base.yaml"
    base_dict: dict = {}
    if base_yaml.exists():
        with open(base_yaml) as fh:
            base_dict = _yaml.safe_load(fh) or {}

    merged: dict = dict(base_dict)

    # Build the override dict from DSL knobs
    override: dict = {"firm_id": dsl_firm_id}
    if include_fallen_angels is not None:
        override["non_ig"] = {"include_fallen_angels": include_fallen_angels}
    if group_key is not None:
        override["concentration"] = {"gre": {"group_key": group_key}}
    if utilization_format is not None:
        override["output"] = {"utilization_format": utilization_format}

    merged = _deep_merge(merged, override)

    # Validate with Pydantic
    try:
        config = FirmConfig(**merged)
    except Exception as exc:
        typer.echo(f"Error: DSL validation failed: {exc}", err=True)
        raise typer.Exit(code=1)

    # Load baseline figures from Firm A (if available)
    baseline_path = OUT_DIR / "figures_firm_a.json"
    baseline_map: dict[str, dict] = {}
    if baseline_path.exists():
        try:
            baseline_data = json.loads(baseline_path.read_text())
            baseline_map = {f["figure"]: f for f in baseline_data}
        except Exception:
            pass
    else:
        console.print("[yellow]Note: Firm A baseline not found — run 'run --firm A' for comparison.[/yellow]")

    # Run compute engine with custom config
    driver = _get_driver()
    try:
        figures = ComputeEngine(driver, config).run_all()
    finally:
        driver.close()

    table = Table("Figure", "Custom Value", "Baseline Value", "Delta", "Status")
    for f in figures:
        baseline = baseline_map.get(f.figure, {})
        baseline_val = baseline.get("value", "—")
        custom_num = _parse_numeric(f.value)
        baseline_num = _parse_numeric(baseline_val)
        if custom_num is not None and baseline_num is not None:
            diff = custom_num - baseline_num
            delta_str = f"{diff:+.4g}" if diff != 0 else "—"
        else:
            delta_str = "—"
        changed = delta_str not in ("—", "N/A")
        color = "yellow" if changed else "default"
        status_color = "red" if f.status == "BREACH" else ("yellow" if f.status == "AT LIMIT" else "green")
        table.add_row(
            f"[{color}]{f.figure}[/{color}]",
            f.value,
            baseline_val,
            f"[{color}]{delta_str}[/{color}]",
            f"[{status_color}]{f.status}[/{status_color}]",
        )

    console.print(f"\n[bold]Preview for config: {dsl_path.name}[/bold] (firm_id={dsl_firm_id})")
    console.print(table)


if __name__ == "__main__":
    app()
