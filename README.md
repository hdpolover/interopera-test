# InterOpera Compliance Reporting

Auditable, reproducible fund-compliance reporting backed by a Neo4j knowledge graph.
Produces two firms' reports by config switch alone — no code edits, no LLM-generated
numbers, every figure traceable to a graph path and a source-document chunk.

---

## Prerequisites

- **Docker** (with Compose v2 — `docker compose` not `docker-compose`)
- **Optional:** `ANTHROPIC_API_KEY` — the system runs fully without a key; the narrative
  step falls back to a deterministic stub so all 13 figures and the firewall check still pass.

---

## Quick Start

```bash
docker compose up --build
```

`--build` is required (Task 19 pinned `typer==0.25.1` and `rich==15.0.0`; a stale cached
image from a previous pull would silently use the wrong versions).

This single command:
1. Builds the `app` image from the local `Dockerfile`
2. Starts **Neo4j 5.18** (with APOC) and **Postgres 16**
3. Waits for both database health-checks to pass
4. Mounts the repo into `/app` and sets `NEO4J_URI`, `POSTGRES_DSN`, etc.

The app container exits after the build step — it is the worker; you invoke pipeline
commands via `docker compose run` (see below).

If host ports 5432 or 7687 are already taken, set overrides in a `.env` file (see
`.env.example`).

---

## Running Both Firms

No code changes are required to switch firms. The entire behavioural difference lives in
`config/firm_a.yaml` vs `config/firm_b.yaml`; the engine has no firm-specific branches.

```bash
# Firm A — percent_1dp format, group by issuer, exclude fallen angels
docker compose run --rm app python -m src.cli.main run --firm A

# Firm B — truncated_bps format, group by parent_issuer, include fallen angels
docker compose run --rm app python -m src.cli.main run --firm B
```

Both commands compute all 13 compliance figures and write:
- `out/figures_firm_{a,b}.json` — machine-readable figure array
- `out/report_firm_{a,b}.xlsx` — formatted xlsx report

**Verification that switching is config-only (no engine edits):**

```bash
grep -r "firm_a\|firm_b\|firm_A\|firm_B" src/compute/engine.py
# Expected: zero matches — the engine contains no firm branches
```

### Config knobs

| Config file | `include_fallen_angels` | `group_key` | `utilization_format` |
|---|---|---|---|
| `config/firm_a.yaml` | `false` | `issuer` | `percent_1dp` |
| `config/firm_b.yaml` | `true` | `parent_issuer` | `truncated_bps` |

---

## CLI Reference

All subcommands are invoked as:

```bash
docker compose run --rm app python -m src.cli.main <subcommand> [options]
```

| Subcommand | Description |
|---|---|
| `ingest` | Parse `sample_docs/sample_holdings.csv` (13 rows) and the guidelines PDF into in-memory records |
| `build-graph` | Load parsed holdings and rule chunks into Neo4j (applies schema, CONTRIBUTES_TO edges, provenance) |
| `verify-graph` | List `PENDING_REVIEW` nodes; optionally approve with `--approve <node_id> --actor <name>` or `--approve-all` |
| `run --firm {A,B}` | Compute all 13 compliance figures and write report + JSON |
| `reconcile --firm {A,B}` | Reconcile computed figures against the answer key (xlsx for Firm A, YAML for Firm B); exits 1 on mismatch |
| `evaluate --firm {A,B}` | Full Phase 5: reconcile + traceability check + firewall check; exits 1 on any failure |
| `verify-determinism --firm {A,B}` | Run the engine twice and assert byte-identical JSON output |
| `narrate --firm {A,B}` | Generate narrative (LLM or stub) and run the firewall check |

---

## Running Tests

The test suite requires both databases running. Run inside the Compose network so the
container DNS names (`neo4j`, `postgres`) resolve:

```bash
docker compose run --rm --no-deps \
  -e NEO4J_TEST_URI=bolt://neo4j:7687 \
  -e NEO4J_TEST_USER=neo4j \
  -e NEO4J_TEST_PASSWORD=password \
  -e POSTGRES_DSN=postgresql://interopera:interopera@postgres:5432/interopera \
  app python -m pytest
```

The `evaluate` subcommand is the live end-to-end proof: it runs the full pipeline for
both firms and exits 0 only when reconcile + traceability + firewall all pass.

---

## Five Constraints and How Each is Verified

| # | Constraint | Verification |
|---|---|---|
| 1 | **Reproducible** — identical outputs on every run | `tests/test_determinism.py` runs the engine twice and asserts byte-identical `figures.json`; `verify-determinism --firm A` does the same interactively |
| 2 | **Traceable** — every figure carries a `graph_path` and a `DERIVED_FROM` citation | `tests/test_engine_firm_a.py` asserts `graph_path` is non-empty and `citation["chunk_id"]` is populated for all 13 figures |
| 3 | **No LLM numbers** — six containment gates prevent the LLM from injecting values into computed figures | `tests/test_llm_containment.py` (6 gates) + `tests/test_firewall.py` verify the firewall rejects any narrative number not in the computed set |
| 4 | **Reconcile Firm A** — 13/13 figures match the answer key | `tests/test_evaluate.py` end-to-end; also `docker compose run --rm app python -m src.cli.main evaluate --firm A` |
| 5 | **Firm B config-only** — no engine code edit required | `tests/test_engine_firm_b.py` + grep gate in `tests/test_llm_containment.py` assert no firm branch in `src/compute/engine.py` |

---

## Tracing a Figure Through the Graph

Open Neo4j Browser at **http://localhost:7474** (user: `neo4j` / password: `password`):

```cypher
-- Trace allocation_sgs: Position → AssetClass
MATCH (p:Position)-[:IN_ASSET_CLASS]->(a:AssetClass {name: 'Singapore Government Securities'})
RETURN p.instrument_id, p.market_value_sgd, a.name

-- Follow provenance: Limit rule → source chunk
MATCH (l:Limit)-[:DERIVED_FROM]->(sc:SourceChunk)
RETURN l.ref, l.rule_type, sc.chunk_id, sc.passage_summary, sc.extraction_confidence
```

Every figure carries `graph_path` (the Neo4j traversal that produced the value) and
`citation` (the `SourceChunk` from which the rule was extracted), making the chain
from raw document to final report fully auditable.

---

## Append-Only Audit Log

All pipeline events are written to Postgres `audit_event` with:

- **`REVOKE UPDATE, DELETE`** on the table — the role `app_role` has `INSERT + SELECT` only
- **A trigger** (`enforce_audit_append_only`) that raises an exception on any `UPDATE` or `DELETE` attempt, even by a superuser running ad-hoc SQL
- **Hash chain** — `row_hash` covers `event_type`, `actor`, `config_hash`, and `payload`; `prev_hash` links to the previous row, so any tampering of a historical row invalidates all subsequent hashes

> Production note: the Docker Compose stack connects as the `interopera` superuser for
> schema creation. In production, the application should connect as `app_role` (defined
> in `init.sql`) to enforce the INSERT-only constraint at the connection level.

---

## Project Structure

```
.
├── config/
│   ├── base.yaml              # Shared defaults
│   ├── firm_a.yaml            # Firm A overrides (3 knobs)
│   └── firm_b.yaml            # Firm B overrides (3 knobs)
├── docs/
│   ├── 01_flow_and_audit_events.md   # Phase 1: event catalogue
│   ├── 02_architecture.md            # Phase 1: layer diagram
│   ├── 03_rfc.md                     # Phase 1: LLM containment RFC
│   ├── PROGRESS.md                   # Per-task status + commit log
│   └── superpowers/
│       ├── specs/2026-06-19-interopera-design.md          # Original design spec
│       └── plans/2026-06-19-interopera-implementation.md  # 23-task implementation plan
├── sample_docs/
│   ├── sample_holdings.csv    # 13-row portfolio (input)
│   └── firm_A_answer_key.xlsx # Expected Firm A figures (reconcile target)
├── src/
│   ├── cli/main.py            # Typer CLI — 8 subcommands
│   ├── compute/               # Engine, config loader, primitives, registry
│   ├── firewall/              # LLM containment checker (6 gates)
│   ├── graph/                 # Neo4j schema, builder, queries
│   ├── ingestion/             # Holdings CSV + guidelines PDF parsers
│   ├── narrative/             # Narrative writer (LLM-optional stub)
│   ├── reconcile/             # Reconciler against answer keys
│   └── report/                # xlsx report writer
├── tests/                     # Full test suite (200+ tests across 20 files)
├── docker-compose.yml
├── init.sql                   # Postgres schema + append-only trigger
└── .env.example               # Port override documentation
```

---

## Configurable Host Ports

If host ports 5432 or 7687 are already in use, override them in a `.env` file:

```bash
cp .env.example .env
# Edit .env to change POSTGRES_HOST_PORT and/or NEO4J_BOLT_PORT
docker compose up --build
```

See `.env.example` for all available variables.

---

## Security / Production Notes

These are noted but not wired in the Docker Compose demo stack:

- **Secrets** — `NEO4J_PASSWORD` and `POSTGRES_DSN` should come from a secret manager
  (AWS Secrets Manager, Vault, etc.) rather than environment variables in compose files.
- **DB role** — the app should connect as `app_role` (INSERT + SELECT only), not as the
  superuser `interopera`. The role is already defined in `init.sql`.
- **Viewer auth** — the FastAPI replay viewer (bonus task, not implemented) would require
  at minimum read-only token auth before exposing audit events.
- **Neo4j auth** — use a strong password and disable the Neo4j browser endpoint in production.
