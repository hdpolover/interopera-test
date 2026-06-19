"""Six LLM containment gate tests (spec §3.1)."""
import ast
import inspect
import os
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORBIDDEN_IMPORTS = {"anthropic", "openai", "httpx", "requests"}


def _scan_imports(filepath: str) -> set[str]:
    """Return set of top-level module names imported in a Python file."""
    with open(filepath) as f:
        tree = ast.parse(f.read())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module.split(".")[0])
    return found


def _scan_directory(dirpath: str) -> dict[str, set[str]]:
    """Walk a directory and return {filepath: set_of_imports} for all .py files."""
    results = {}
    for root, _dirs, files in os.walk(dirpath):
        for fname in files:
            if fname.endswith(".py"):
                fpath = os.path.join(root, fname)
                results[fpath] = _scan_imports(fpath)
    return results


def test_static_import_gate():
    """Gate 1: No file in src/compute/ imports anthropic, openai, httpx, or requests."""
    compute_dir = os.path.join(REPO_ROOT, "src", "compute")
    file_imports = _scan_directory(compute_dir)
    violations = {}
    for fpath, imports in file_imports.items():
        bad = imports & FORBIDDEN_IMPORTS
        if bad:
            violations[fpath] = bad
    assert not violations, (
        f"LLM imports found in src/compute/: {violations}"
    )


def test_di_gate():
    """Gate 2: ComputeEngine.__init__ has no LLM client parameter."""
    from src.compute.engine import ComputeEngine
    sig = inspect.signature(ComputeEngine.__init__)
    param_names = set(sig.parameters.keys())
    forbidden_params = {"llm", "llm_client", "anthropic_client", "openai_client",
                        "api_key", "client"}
    found = param_names & forbidden_params
    assert not found, (
        f"ComputeEngine.__init__ has LLM parameter(s): {found}"
    )


def test_report_from_figures_not_narrative():
    """Gate 3: write_report accepts list[Figure] and does not accept a narrative string param."""
    from src.report.writer import write_report
    sig = inspect.signature(write_report)
    param_names = list(sig.parameters.keys())
    # Must accept figures
    assert "figures" in param_names, "write_report must accept 'figures' parameter"
    # Must not accept narrative
    assert "narrative" not in param_names, (
        "write_report must not accept a 'narrative' parameter — "
        "report cells come from figures only"
    )


def test_firewall_rejects_injected_number():
    """Gate 4: firewall returns FAIL when narrative contains a number not in figures."""
    from src.compute.registry import Figure
    from src.firewall.checker import check_firewall
    figures = [
        Figure(figure="allocation_sgs", value="35.0%", utilization="58.3%", status="OK",
               limit="20–60%", graph_path="...", citation={}),
        Figure(figure="allocation_cash", value="4.0%", utilization="n/a", status="BREACH",
               limit="min 5%", graph_path="...", citation={}),
    ]
    # 99.9% is not in any figure
    bad_narrative = (
        "The portfolio allocation to SGS is 35.0%. "
        "However, the risk exposure has reached 99.9% of tolerance."
    )
    result = check_firewall(bad_narrative, figures)
    assert result.passed is False
    assert any("99.9" in token for token in result.offending_numbers)


def test_human_only_approval():
    """Gate 5: approve_node requires non-empty actor; no auto-approve code path in engine."""
    from src.graph.queries import approve_node
    import inspect as insp
    # approve_node must require actor
    sig = insp.signature(approve_node)
    assert "actor" in sig.parameters, "approve_node must have an 'actor' parameter"

    # Calling with empty actor raises ValueError
    with pytest.raises(ValueError):
        approve_node(None, "SGS-01", actor="")

    # The engine module must not call approve_node
    from src.compute import engine as engine_module
    engine_src = inspect.getsource(engine_module)
    assert "approve_node" not in engine_src, (
        "ComputeEngine must not call approve_node — no auto-approval code path"
    )


def test_phase5_checks_are_pure_code():
    """Gate 6: reconciler.py and checker.py must not import any LLM library."""
    reconciler_path = os.path.join(REPO_ROOT, "src", "reconcile", "reconciler.py")
    checker_path = os.path.join(REPO_ROOT, "src", "firewall", "checker.py")

    for fpath in [reconciler_path, checker_path]:
        assert os.path.exists(fpath), f"Missing file: {fpath}"
        imports = _scan_imports(fpath)
        bad = imports & FORBIDDEN_IMPORTS
        assert not bad, f"LLM imports {bad} found in {fpath}"
