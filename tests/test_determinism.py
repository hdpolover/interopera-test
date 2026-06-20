"""Determinism test (constraint 1): same inputs => byte-identical figures.

Runs the full compute twice on the same Neo4j graph for both Firm A and Firm B.
Serializes all 13 figures to JSON with stable ordering (registry order, sorted keys)
and asserts the two JSON strings are byte-identical.

Fields serialized: figure, value, utilization, status, limit, graph_path, citation.
citation is deterministic because chunk_id is a content hash (SHA-256 of passage).
No wall-clock timestamp or run_id appears in Figure output — those are audit-log
concerns only (see src/audit/log.py). If a timestamp were found here it would
be a constraint-1 violation.
"""
from __future__ import annotations

import json
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def populated_driver(driver):
    """Clear Neo4j, apply schema, and load the standard sample data once."""
    from src.graph.builder import load_positions, load_rules
    from src.graph.schema import apply_schema
    from src.ingestion.guidelines_parser import parse_guidelines
    from src.ingestion.holdings_parser import parse_holdings

    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

    apply_schema(driver)
    csv_path = os.path.join(REPO_ROOT, "sample_docs", "sample_holdings.csv")
    positions = parse_holdings(csv_path)
    load_positions(driver, positions)
    chunks = parse_guidelines(pdf_path=None, llm_client=None)
    load_rules(driver, chunks)
    return driver


@pytest.fixture(scope="module")
def firm_a_engine(populated_driver):
    from src.compute.config_loader import load_config
    from src.compute.engine import ComputeEngine

    config = load_config(
        os.path.join(REPO_ROOT, "config", "base.yaml"),
        os.path.join(REPO_ROOT, "config", "firm_a.yaml"),
    )
    return ComputeEngine(populated_driver, config)


@pytest.fixture(scope="module")
def firm_b_engine(populated_driver):
    from src.compute.config_loader import load_config
    from src.compute.engine import ComputeEngine

    config = load_config(
        os.path.join(REPO_ROOT, "config", "base.yaml"),
        os.path.join(REPO_ROOT, "config", "firm_b.yaml"),
    )
    return ComputeEngine(populated_driver, config)


# ---------------------------------------------------------------------------
# Serialization helper
# ---------------------------------------------------------------------------


def _figures_to_json(figures) -> str:
    """Stable JSON serialization of a Figure list.

    Includes ALL figure output fields: figure, value, utilization, status,
    limit, graph_path, and citation (chunk_id is a content hash — deterministic).
    Registry order is preserved (figures arrive in FIGURE_REGISTRY order).
    sort_keys=True makes the dict encoding order stable regardless of insertion order.

    NOTE: No wall-clock timestamp or run_id is included — those are audit-log
    concerns (src/audit/log.py) and must NOT appear in Figure output.
    """
    data = [
        {
            "figure": f.figure,
            "value": f.value,
            "utilization": f.utilization,
            "status": f.status,
            "limit": f.limit,
            "graph_path": f.graph_path,
            "citation": f.citation,
        }
        for f in figures
    ]
    return json.dumps(data, sort_keys=True, indent=2)


# ---------------------------------------------------------------------------
# Firm A determinism tests
# ---------------------------------------------------------------------------


def test_firm_a_double_run_figure_count(firm_a_engine):
    """Both runs of Firm A must produce exactly 13 figures."""
    run1 = firm_a_engine.run_all()
    run2 = firm_a_engine.run_all()
    assert len(run1) == 13, f"Firm A run 1 produced {len(run1)} figures, expected 13"
    assert len(run2) == 13, f"Firm A run 2 produced {len(run2)} figures, expected 13"


def test_firm_a_double_run_fields_identical(firm_a_engine):
    """Each individual Figure field must be identical across two Firm A runs."""
    run1 = firm_a_engine.run_all()
    run2 = firm_a_engine.run_all()
    for f1, f2 in zip(run1, run2):
        assert f1.figure == f2.figure, (
            f"Firm A figure name mismatch: {f1.figure!r} vs {f2.figure!r}"
        )
        assert f1.value == f2.value, (
            f"Firm A [{f1.figure}] value nondeterminism: {f1.value!r} vs {f2.value!r}"
        )
        assert f1.utilization == f2.utilization, (
            f"Firm A [{f1.figure}] utilization nondeterminism: "
            f"{f1.utilization!r} vs {f2.utilization!r}"
        )
        assert f1.status == f2.status, (
            f"Firm A [{f1.figure}] status nondeterminism: {f1.status!r} vs {f2.status!r}"
        )
        assert f1.limit == f2.limit, (
            f"Firm A [{f1.figure}] limit nondeterminism: {f1.limit!r} vs {f2.limit!r}"
        )
        assert f1.graph_path == f2.graph_path, (
            f"Firm A [{f1.figure}] graph_path nondeterminism:\n"
            f"  run1: {f1.graph_path!r}\n"
            f"  run2: {f2.graph_path!r}"
        )
        assert f1.citation == f2.citation, (
            f"Firm A [{f1.figure}] citation nondeterminism:\n"
            f"  run1: {f1.citation!r}\n"
            f"  run2: {f2.citation!r}"
        )


def test_firm_a_json_byte_identical(firm_a_engine):
    """Serialized Firm A figures.json must be byte-identical across two runs."""
    run1 = firm_a_engine.run_all()
    run2 = firm_a_engine.run_all()
    j1 = _figures_to_json(run1)
    j2 = _figures_to_json(run2)
    assert j1 == j2, (
        "Firm A figures.json is NOT byte-identical across two runs.\n"
        "This is a constraint-1 violation — a genuine nondeterminism bug.\n"
        f"Diff summary: first differing character at index "
        f"{next((i for i, (a, b) in enumerate(zip(j1, j2)) if a != b), len(j1))}"
    )


# ---------------------------------------------------------------------------
# Firm B determinism tests
# ---------------------------------------------------------------------------


def test_firm_b_double_run_figure_count(firm_b_engine):
    """Both runs of Firm B must produce exactly 13 figures."""
    run1 = firm_b_engine.run_all()
    run2 = firm_b_engine.run_all()
    assert len(run1) == 13, f"Firm B run 1 produced {len(run1)} figures, expected 13"
    assert len(run2) == 13, f"Firm B run 2 produced {len(run2)} figures, expected 13"


def test_firm_b_double_run_fields_identical(firm_b_engine):
    """Each individual Figure field must be identical across two Firm B runs."""
    run1 = firm_b_engine.run_all()
    run2 = firm_b_engine.run_all()
    for f1, f2 in zip(run1, run2):
        assert f1.figure == f2.figure, (
            f"Firm B figure name mismatch: {f1.figure!r} vs {f2.figure!r}"
        )
        assert f1.value == f2.value, (
            f"Firm B [{f1.figure}] value nondeterminism: {f1.value!r} vs {f2.value!r}"
        )
        assert f1.utilization == f2.utilization, (
            f"Firm B [{f1.figure}] utilization nondeterminism: "
            f"{f1.utilization!r} vs {f2.utilization!r}"
        )
        assert f1.status == f2.status, (
            f"Firm B [{f1.figure}] status nondeterminism: {f1.status!r} vs {f2.status!r}"
        )
        assert f1.limit == f2.limit, (
            f"Firm B [{f1.figure}] limit nondeterminism: {f1.limit!r} vs {f2.limit!r}"
        )
        assert f1.graph_path == f2.graph_path, (
            f"Firm B [{f1.figure}] graph_path nondeterminism:\n"
            f"  run1: {f1.graph_path!r}\n"
            f"  run2: {f2.graph_path!r}"
        )
        assert f1.citation == f2.citation, (
            f"Firm B [{f1.figure}] citation nondeterminism:\n"
            f"  run1: {f1.citation!r}\n"
            f"  run2: {f2.citation!r}"
        )


def test_firm_b_json_byte_identical(firm_b_engine):
    """Serialized Firm B figures.json must be byte-identical across two runs."""
    run1 = firm_b_engine.run_all()
    run2 = firm_b_engine.run_all()
    j1 = _figures_to_json(run1)
    j2 = _figures_to_json(run2)
    assert j1 == j2, (
        "Firm B figures.json is NOT byte-identical across two runs.\n"
        "This is a constraint-1 violation — a genuine nondeterminism bug.\n"
        f"Diff summary: first differing character at index "
        f"{next((i for i, (a, b) in enumerate(zip(j1, j2)) if a != b), len(j1))}"
    )
