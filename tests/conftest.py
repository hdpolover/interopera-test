"""Shared pytest fixtures for the test suite."""
from __future__ import annotations

import os

import pytest

NEO4J_URI = os.environ.get("NEO4J_TEST_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_TEST_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_TEST_PASSWORD", "password")


@pytest.fixture(scope="module")
def driver():
    """Connect to Neo4j; skip module if unavailable."""
    try:
        from neo4j import GraphDatabase

        drv = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
        drv.verify_connectivity()
        yield drv
        drv.close()
    except Exception as exc:
        pytest.skip(f"Neo4j not available: {exc}")
