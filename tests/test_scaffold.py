# tests/test_scaffold.py
import yaml
import os
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def test_docker_compose_is_valid_yaml():
    path = os.path.join(REPO_ROOT, "docker-compose.yml")
    assert os.path.exists(path), "docker-compose.yml missing"
    with open(path) as f:
        data = yaml.safe_load(f)
    assert data is not None

def test_docker_compose_has_neo4j_service():
    path = os.path.join(REPO_ROOT, "docker-compose.yml")
    with open(path) as f:
        data = yaml.safe_load(f)
    services = data.get("services", {})
    assert "neo4j" in services, "neo4j service missing"
    neo4j = services["neo4j"]
    assert "healthcheck" in neo4j, "neo4j missing healthcheck"

def test_docker_compose_has_postgres_service():
    path = os.path.join(REPO_ROOT, "docker-compose.yml")
    with open(path) as f:
        data = yaml.safe_load(f)
    services = data.get("services", {})
    assert "postgres" in services, "postgres service missing"
    pg = services["postgres"]
    assert "healthcheck" in pg, "postgres missing healthcheck"

def test_init_sql_has_audit_table():
    path = os.path.join(REPO_ROOT, "init.sql")
    assert os.path.exists(path), "init.sql missing"
    with open(path) as f:
        content = f.read()
    assert "CREATE TABLE audit_event" in content

def test_init_sql_has_revoke():
    path = os.path.join(REPO_ROOT, "init.sql")
    with open(path) as f:
        content = f.read()
    assert "REVOKE UPDATE" in content
    assert "REVOKE DELETE" in content or "REVOKE UPDATE, DELETE" in content or "REVOKE UPDATE,DELETE" in content

def test_init_sql_has_trigger():
    path = os.path.join(REPO_ROOT, "init.sql")
    with open(path) as f:
        content = f.read()
    assert "BEFORE UPDATE OR DELETE" in content or "BEFORE UPDATE" in content
    assert "RAISE EXCEPTION" in content

def test_requirements_txt_exists():
    path = os.path.join(REPO_ROOT, "requirements.txt")
    assert os.path.exists(path)
    with open(path) as f:
        content = f.read()
    for pkg in ["neo4j", "psycopg", "pydantic", "typer", "openpyxl", "pytest", "pyyaml"]:
        assert pkg in content, f"{pkg} missing from requirements.txt"
