"""InterOpera compliance CLI — all subcommands.

Heavy helper logic (replay data mappings, numeric parsing, config-knob
printing) is extracted to src.cli.commands.replay_helpers to keep this
file under 800 lines while preserving the module-level names required by
the test suite (OUT_DIR, SAMPLE_DOCS, CONFIG_DIR, command functions).
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from src.cli.commands.replay_helpers import (
    parse_numeric as _parse_numeric,
    print_delta_vs_answer_key as _print_delta,
    print_config_knobs as _print_config_knobs,
)

app = typer.Typer(name="interopera", help="InterOpera fund compliance reporting CLI")
console = Console()

REPO_ROOT = Path(__file__).parent.parent.parent
CONFIG_DIR = REPO_ROOT / "config"
SAMPLE_DOCS = REPO_ROOT / "sample_docs"
OUT_DIR = REPO_ROOT / "out"


def _get_driver() -> Any:  # neo4j.Driver; annotated Any to avoid top-level import of optional dep
    """Return an authenticated Neo4j driver from environment variables."""
    from neo4j import GraphDatabase  # type: ignore[import-untyped]

    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "password")
    return GraphDatabase.driver(uri, auth=(user, password))


def _make_audit_logger() -> Optional[Any]:  # Optional[AuditLogger]; imported lazily
    """Return an AuditLogger bound to POSTGRES_DSN, or None on failure.

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


def _audit_log(
    logger: Optional[Any],  # AuditLogger | None; typed as Any to avoid circular import
    run_id: str,
    event_type: str,
    actor: str,
    payload: dict,
    config_hash: Optional[str] = None,
) -> None:
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
) -> None:
    """Parse holdings CSV and guidelines PDF."""
    from src.ingestion.holdings_parser import parse_holdings
    from src.ingestion.guidelines_parser import parse_guidelines

    positions = parse_holdings(holdings)
    console.print(f"Parsed {len(positions)} positions from {holdings}")
    chunks = parse_guidelines(pdf_path=guidelines, llm_client=None)
    console.print(f"Parsed {len(chunks)} rule chunks")


@app.command(name="build-graph")
def build_graph(
    holdings: str = typer.Option(str(SAMPLE_DOCS / "sample_holdings.csv"), help="Holdings CSV path"),
    guidelines: Optional[str] = typer.Option(None, help="Guidelines PDF path (default: sample_docs/sample_fund_guidelines.pdf)"),
) -> None:
    """Build Neo4j knowledge graph from holdings and guidelines."""
    from src.graph.schema import apply_schema
    from src.graph.builder import load_positions, load_rules, load_risk_metrics
    from src.ingestion.holdings_parser import parse_holdings
    from src.ingestion.guidelines_parser import parse_guidelines

    run_id = str(uuid.uuid4())
    audit = _make_audit_logger()
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
    approve_all: bool = typer.Option(False, "--approve-all", help="Approve all PENDING_REVIEW nodes"),
    approve: Optional[str] = typer.Option(None, "--approve", help="Approve a single node by ID"),
    actor: str = typer.Option("cli_user", help="Actor name recorded in audit log"),
) -> None:
    """List PENDING_REVIEW nodes and optionally approve them."""
    from src.graph.queries import list_pending_nodes, approve_node

    run_id = str(uuid.uuid4())
    audit = _make_audit_logger()
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
        _audit_log(audit, run_id, "node_verified", actor, {"node_id": approve})
        console.print(f"[green]Approved {approve} as {actor}[/green]")
    driver.close()
    if audit is not None:
        audit.close()


@app.command(name="run")
def run_cmd(
    firm: str = typer.Option(..., help="Firm ID: A, B, or C"),
    output_json: bool = typer.Option(False, "--json", help="Print results as JSON to stdout"),
) -> None:
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
        config = load_config(str(CONFIG_DIR / "base.yaml"), str(firm_yaml))
    except Exception as exc:
        typer.echo(f"Error: failed to load config for firm '{firm}': {exc}", err=True)
        raise typer.Exit(code=1)

    run_id = str(uuid.uuid4())
    audit = _make_audit_logger()
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
    _audit_log(audit, run_id, "report_exported", "cli", {"output_path": str(report_path)}, config_hash=cfg_hash)

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
    firm: str = typer.Option(..., help="Firm ID: A, B, or C"),
    output_json: bool = typer.Option(False, "--json", help="Print results as JSON to stdout"),
) -> None:
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
        config = load_config(str(CONFIG_DIR / "base.yaml"), str(firm_yaml))
    except Exception as exc:
        typer.echo(f"Error: failed to load config for firm '{firm}': {exc}", err=True)
        raise typer.Exit(code=1)

    run_id = str(uuid.uuid4())
    audit = _make_audit_logger()

    driver = _get_driver()
    figures = ComputeEngine(driver, config).run_all()
    driver.close()

    if firm.upper() == "A":
        expected = parse_answer_key_xlsx(str(SAMPLE_DOCS / "firm_A_answer_key.xlsx"))
    else:
        expected = parse_expected_yaml(str(CONFIG_DIR / "firm_b_expected.yaml"))

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
    firm: str = typer.Option(..., help="Firm ID: A, B, or C"),
    output_json: bool = typer.Option(False, "--json", help="Print results as JSON to stdout"),
) -> None:
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
        config = load_config(str(CONFIG_DIR / "base.yaml"), str(firm_yaml))
    except Exception as exc:
        typer.echo(f"Error: failed to load config for firm '{firm}': {exc}", err=True)
        raise typer.Exit(code=1)

    run_id = str(uuid.uuid4())
    audit = _make_audit_logger()

    driver = _get_driver()
    figures = ComputeEngine(driver, config).run_all()
    driver.close()

    exit_code = 0

    if firm.upper() == "A":
        expected = parse_answer_key_xlsx(str(SAMPLE_DOCS / "firm_A_answer_key.xlsx"))
    else:
        expected = parse_expected_yaml(str(CONFIG_DIR / "firm_b_expected.yaml"))
    recon_results = do_reconcile(figures, expected)
    recon_failed = [r for r in recon_results if not r.passed]
    if recon_failed:
        exit_code = 1
        console.print(f"[red]Reconcile FAIL: {len(recon_failed)} figures mismatch[/red]")

    trace_failed = [f for f in figures if not f.graph_path or not f.citation.get("chunk_id")]
    if trace_failed:
        exit_code = 1
        console.print(f"[red]Traceability FAIL: {[f.figure for f in trace_failed]}[/red]")

    # evaluate uses the deterministic stub — firewall check must be reproducible
    # regardless of whether an API key is present. Use `narrate` for LLM narrative.
    narrator = Narrator(api_key=None)
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
        {"firm": firm_id, "pass_count": len(recon_results) - len(recon_failed), "fail_count": len(recon_failed)},
    )
    if audit is not None:
        audit.close()

    raise typer.Exit(code=exit_code)


@app.command(name="verify-determinism")
def verify_determinism(
    firm: str = typer.Option(..., help="Firm ID: A, B, or C"),
) -> None:
    """Run engine twice and assert byte-identical figures.json output."""
    import difflib
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

    def to_json(figs: list) -> str:
        return json.dumps(
            [{"figure": f.figure, "value": f.value, "utilization": f.utilization,
              "status": f.status, "limit": f.limit, "graph_path": f.graph_path,
              "citation": f.citation} for f in figs],
            sort_keys=True, indent=2
        )

    j1 = to_json(run1)
    j2 = to_json(run2)

    if j1 == j2:
        console.print("[green]DETERMINISM PASS: both runs are identical[/green]")
    else:
        console.print("[red]DETERMINISM FAIL: runs differ[/red]")
        diff = list(difflib.unified_diff(j1.splitlines(), j2.splitlines(), lineterm=""))
        for line in diff[:40]:
            console.print(line)
        raise typer.Exit(code=1)


@app.command()
def narrate(
    firm: str = typer.Option(..., help="Firm ID: A, B, or C"),
) -> None:
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

    with console.status("[cyan]Computing figures…[/cyan]", spinner="dots"):
        figures = ComputeEngine(driver, config).run_all()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    spinner_label = f"[cyan]Generating narrative with {model}…[/cyan]" if api_key else "[cyan]Generating narrative (stub mode)…[/cyan]"

    narrator = Narrator(api_key=api_key, driver=driver)
    with console.status(spinner_label, spinner="dots"):
        narrative = narrator.write_narrative(figures, firm_id=firm_id)

    with console.status("[cyan]Running firewall check…[/cyan]", spinner="dots"):
        fw_result = check_firewall(narrative, figures)

    driver.close()

    console.print(narrative)
    if fw_result.passed:
        console.print("[green]Firewall PASS[/green]")
    else:
        console.print(f"[red]Firewall FAIL: {fw_result.offending_numbers}[/red]")
        raise typer.Exit(code=1)


@app.command()
def replay(
    figure: str = typer.Option(..., help="Figure name, e.g. allocation_sgs"),
    firm: str = typer.Option(..., help="Firm ID: A, B, or C"),
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

    console.print(f"\n[bold]Figure:[/bold] {figure}")
    console.print(f"[bold]Graph path:[/bold] {match.get('graph_path', 'N/A')}")
    citation: dict = match.get("citation") or {}
    console.print(f"[bold]Source passage:[/bold] {citation.get('passage_summary', 'N/A')}")
    console.print(f"[bold]Chunk ID:[/bold]       {citation.get('chunk_id', 'N/A')}")

    _print_delta(firm, figure, match, SAMPLE_DOCS)
    _print_config_knobs(firm_id, figure, CONFIG_DIR)


@app.command(name="query-metric")
def query_metric(
    metric: Optional[str] = typer.Option(None, "--metric", help="RiskMetric name to look up"),
    all_metrics: bool = typer.Option(False, "--all", help="Show all 6 risk metrics"),
) -> None:
    """Query RiskMetric → BreachAction → Owner for one metric or all metrics."""
    from src.graph.queries import breach_action_for_metric, list_all_breach_actions

    if not all_metrics and not metric:
        typer.echo("Error: specify --metric <name> or --all", err=True)
        raise typer.Exit(code=1)

    driver = _get_driver()
    try:
        if all_metrics:
            rows = list_all_breach_actions(driver)
            if not rows:
                console.print("[yellow]No RiskMetric nodes found. Run build-graph first.[/yellow]")
                raise typer.Exit(code=1)
            table = Table("Metric", "Limit", "Monitoring", "Breach Action", "Owner")
            for row in rows:
                table.add_row(
                    row.get("metric", ""),
                    row.get("limit", "") or "",
                    row.get("monitoring_frequency", "") or "",
                    row.get("breach_action", "") or "",
                    row.get("owner", "") or "",
                )
            console.print(table)
        else:
            assert metric is not None  # guaranteed by the early-exit guard above
            result = breach_action_for_metric(driver, metric)
            if not result:
                typer.echo(f"No RiskMetric node found for: {metric}", err=True)
                raise typer.Exit(code=1)
            console.print(f"Metric:        {result.get('metric', '')}")
            console.print(f"Limit:         {result.get('limit', '') or 'N/A'}")
            console.print(f"Monitoring:    {result.get('monitoring_frequency', '') or 'N/A'}")
            console.print(f"Breach Action: {result.get('breach_action', '') or 'N/A'}")
            console.print(f"Owner:         {result.get('owner', '') or 'N/A'}")
    finally:
        driver.close()


@app.command(name="show-audit-log")
def show_audit_log(
    last: int = typer.Option(20, "--last", help="Number of most recent events to show"),
    verify: bool = typer.Option(False, "--verify", help="Verify hash chain integrity"),
) -> None:
    """Display audit log events and optionally verify the hash chain."""
    from src.audit.log import AuditLogger

    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        typer.echo("Error: POSTGRES_DSN not set — cannot access audit log", err=True)
        raise typer.Exit(code=1)

    try:
        logger = AuditLogger(dsn)
    except Exception as exc:
        typer.echo(f"Error: cannot connect to audit DB: {exc}", err=True)
        raise typer.Exit(code=1)

    try:
        events = logger.list_events(limit=last)
        if not events:
            console.print("[yellow]No audit events found.[/yellow]")
        else:
            table = Table("#", "Event Type", "Actor", "Timestamp", "Hash (first 12)")
            for i, ev in enumerate(events, start=1):
                ts_str = str(ev.get("ts", "")) if ev.get("ts") is not None else ""
                row_hash = ev.get("row_hash", "") or ""
                table.add_row(str(i), ev.get("event_type", ""), ev.get("actor", ""), ts_str, row_hash[:12])
            console.print(table)

        if verify:
            valid = logger.verify_chain()
            total = len(logger.list_events(limit=10_000))
            if valid:
                console.print(f"[green]Chain integrity: VALID ({total} events verified)[/green]")
            else:
                console.print("[red]Chain integrity: INVALID — chain has been tampered with[/red]")
                raise typer.Exit(code=1)
    finally:
        logger.close()


@app.command(name="generate-dsl")
def generate_dsl(
    firm: str = typer.Option(..., help="Firm ID: A, B, or C"),
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

    dsl_firm_id = dsl_dict.get("firm_id", "custom")
    include_fallen_angels = dsl_dict.get("include_fallen_angels")
    group_key = dsl_dict.get("group_key")
    utilization_format = dsl_dict.get("utilization_format")

    base_yaml = CONFIG_DIR / "base.yaml"
    base_dict: dict = {}
    if base_yaml.exists():
        with open(base_yaml) as fh:
            base_dict = _yaml.safe_load(fh) or {}

    merged: dict = dict(base_dict)
    override: dict = {"firm_id": dsl_firm_id}
    if include_fallen_angels is not None:
        override["non_ig"] = {"include_fallen_angels": include_fallen_angels}
    if group_key is not None:
        override["concentration"] = {"gre": {"group_key": group_key}}
    if utilization_format is not None:
        override["output"] = {"utilization_format": utilization_format}
    merged = _deep_merge(merged, override)

    try:
        config = FirmConfig(**merged)
    except Exception as exc:
        typer.echo(f"Error: DSL validation failed: {exc}", err=True)
        raise typer.Exit(code=1)

    baseline_path = OUT_DIR / "figures_firm_a.json"
    baseline_map: dict[str, dict] = {}
    if baseline_path.exists():
        try:
            baseline_data = json.loads(baseline_path.read_text())
            baseline_map = {f["figure"]: f for f in baseline_data}
        except (json.JSONDecodeError, KeyError):
            pass
    else:
        console.print("[yellow]Note: Firm A baseline not found — run 'run --firm A' for comparison.[/yellow]")

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
