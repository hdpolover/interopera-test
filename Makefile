.PHONY: build up down clean test coverage graph \
        run-a run-b run-c evaluate-a evaluate-b narrate-a \
        query-metric audit-log lint typecheck security

# ── Services ──────────────────────────────────────────────────────────────────

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

clean:
	docker compose down -v

# ── Tests ─────────────────────────────────────────────────────────────────────

TEST_FLAGS = \
	-e NEO4J_TEST_URI=bolt://neo4j:7687 \
	-e NEO4J_TEST_USER=neo4j \
	-e NEO4J_TEST_PASSWORD=password \
	-e POSTGRES_DSN=postgresql://interopera:interopera@postgres:5432/interopera

test:
	docker compose run --rm $(TEST_FLAGS) app python -m pytest -v --tb=short

coverage:
	docker compose run --rm $(TEST_FLAGS) app \
	  python -m pytest --cov=src --cov-report=term-missing --cov-report=html:out/htmlcov -q

# ── Pipeline ──────────────────────────────────────────────────────────────────

graph:
	docker compose run --rm app python -m src.cli.main build-graph

run-a:
	docker compose run --rm app python -m src.cli.main run --firm A

run-b:
	docker compose run --rm app python -m src.cli.main run --firm B

run-c:
	docker compose run --rm app python -m src.cli.main run --firm C

evaluate-a:
	docker compose run --rm app python -m src.cli.main evaluate --firm A

evaluate-b:
	docker compose run --rm app python -m src.cli.main evaluate --firm B

narrate-a:
	docker compose run --rm app python -m src.cli.main narrate --firm A

# ── Inspection ────────────────────────────────────────────────────────────────

query-metric:
	docker compose run --rm app python -m src.cli.main query-metric --all

audit-log:
	docker compose run --rm app python -m src.cli.main show-audit-log --last 20 --verify

# ── Code quality ──────────────────────────────────────────────────────────────

lint:
	docker compose run --rm app python -m ruff check src/ tests/

typecheck:
	docker compose run --rm app python -m mypy src/ --ignore-missing-imports

security:
	docker compose run --rm app python -m bandit -r src/ -ll
