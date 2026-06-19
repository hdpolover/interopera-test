"""Smoke-tests that the README exists and covers required content."""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_readme_exists():
    assert os.path.exists(os.path.join(REPO_ROOT, "README.md"))


def test_readme_has_docker_compose_up():
    with open(os.path.join(REPO_ROOT, "README.md")) as f:
        content = f.read()
    assert "docker compose up" in content


def test_readme_has_firm_a_and_b():
    with open(os.path.join(REPO_ROOT, "README.md")) as f:
        content = f.read()
    assert "--firm A" in content
    assert "--firm B" in content


def test_readme_has_neo4j_trace_query():
    with open(os.path.join(REPO_ROOT, "README.md")) as f:
        content = f.read()
    assert "Neo4j" in content or "neo4j" in content
