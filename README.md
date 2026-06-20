# InterOpera Compliance Reporting

![CI](https://github.com/hdpolover/interopera-test/actions/workflows/ci.yml/badge.svg)

Auditable, reproducible fund-compliance reporting backed by a Neo4j knowledge graph.
Produces two firms' reports by config switch alone — no code edits, no LLM-generated
numbers, every figure traceable to a graph path and a source-document chunk.

---

## Prerequisites

- **Docker** (with Compose v2 — `docker compose` not `docker-compose`)
- **Optional:** `ANTHROPIC_API_KEY` — the system runs fully without a key; the narrative
  step falls back to a deterministic stub so all 13 figures and the firewall check still pass.
- **Optional:** `ANTHROPIC_MODEL` — override the LLM model without touching source code
  (default: `claude-sonnet-4-6`). Set in `.env` to switch tiers — e.g. `claude-haiku-4-5-20251001`
  for faster/cheaper batch runs. See `docs/DECISIONS.md §23` for a live model comparison.

---

## Quick Start

```bash
docker compose up --build
```

`--build` is required — a stale cached image from a previous pull would silently use the
wrong package versions (`typer==0.25.1`, `rich==15.0.0` are pinned in `requirements.txt`).

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

## `fundra` — Short-Form CLI

> **Skip typing `docker compose run --rm app python -m src.cli.main ...` every time.**

`bin/fundra` is a thin shell wrapper that forwards all arguments to the CLI inside the
container. One-time setup:

```bash
# Add to ~/.zshrc (or ~/.bashrc)
export PATH="/path/to/interopera-test/bin:$PATH"

# Reload
source ~/.zshrc
```

After that, from **any directory**:

```bash
fundra --help
fundra build-graph
fundra verify-graph --approve-all
fundra run --firm A
fundra run --firm B
fundra evaluate --firm A
fundra evaluate --firm B
fundra narrate --firm A
fundra verify-determinism --firm A
fundra show-audit-log --last 20 --verify
fundra query-metric --all
fundra replay --figure allocation_cash --firm A
fundra generate-dsl --firm A
```

> **Prerequisite:** services must be running — `docker compose up -d` or `make up` once
> before using `fundra`. The wrapper does not start services automatically.

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
- `out/figures_firm_{a,b}.json` — machine-readable figure array; each entry: `figure`, `value`, `utilization`, `status`, `limit`, `graph_path`, `citation`
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
| `config/firm_c.yaml` | `false` | `parent_issuer` | `truncated_bps` |

Firm C is a third independent configuration — distinct knob combination from both A and B — proving switching is not a two-firm coincidence. Run it with `--firm C`.

---

## CLI Reference

With `fundra` installed (see above):

```bash
fundra <subcommand> [options]
```

Or the full form without the wrapper:

```bash
docker compose run --rm app python -m src.cli.main <subcommand> [options]
```

| Subcommand | Description |
|---|---|
| `ingest` | Parse `sample_docs/sample_holdings.csv` (13 rows) and the guidelines PDF into in-memory records |
| `build-graph` | Load parsed holdings and rule chunks into Neo4j (applies schema, CONTRIBUTES_TO edges, provenance) |
| `verify-graph` | List `PENDING_REVIEW` nodes; optionally approve with `--approve <node_id> --actor <name>` or `--approve-all` |
| `run --firm {A,B,C}` | Compute all 13 compliance figures and write report + JSON |
| `reconcile --firm {A,B,C}` | Reconcile computed figures against the answer key (xlsx for Firm A, YAML for Firm B); exits 1 on mismatch |
| `evaluate --firm {A,B,C}` | Full Phase 5: reconcile + traceability check + firewall check; exits 1 on any failure; writes `out/evaluate_{firm}.json` |
| `verify-determinism --firm {A,B,C}` | Run the engine twice and assert byte-identical JSON output |
| `narrate --firm {A,B,C}` | Generate narrative (LLM or stub) and run the firewall check; shows live spinners for compute / generate / firewall stages |
| `query-metric --metric <name>` / `--all` | Multi-hop graph traversal: RiskMetric → BreachAction → Owner for any §3.1 metric |
| `show-audit-log [--last N] [--verify]` | Print audit event table and verify SHA-256 hash chain integrity |
| `replay --figure <name> --firm {A,B,C}` | Show graph_path, citation, delta vs answer key, and config knobs for a figure |
| `generate-dsl --firm {A,B,C}` | Emit annotated YAML config DSL to stdout |
| `preview-config --dsl <path>` | Validate DSL, run engine, show diff table vs Firm A baseline |

---

## Code Quality

Dev tools (`pytest-cov`, `mypy`, `bandit`, `ruff`) are included in `requirements.txt` and
available inside the container. Run them via Make:

```bash
# Run tests with coverage report (86% total)
make coverage

# Type-check all source files (0 errors)
make typecheck

# Security scan — medium/high severity only (0 issues)
make security

# Lint with ruff
make lint
```

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

## How Rules Are Ingested (transcription vs. LLM)

By design, the default pipeline does **not** parse the guidelines PDF at run time. Rule
content is loaded from a deterministic, hand-verified transcription of
`sample_fund_guidelines.pdf` (`_STUB_PASSAGES` in `src/ingestion/guidelines_parser.py`).
Each chunk's `source_doc`, `page`, and section label were checked against the actual PDF, so
tracing `figure → graph path → SourceChunk → page` lands on the correct section of the
source document.

This is a deliberate choice for **reproducibility** (constraint 1): an LLM extracting the
same PDF could yield different chunk IDs, pages, or confidences across runs, breaking
byte-identical output. An LLM-assisted extraction path exists in the same module
(`parse_guidelines(pdf_path, llm_client=...)`, using `pdfplumber` + an injected client) to
show how the same `RuleChunk` contract is populated at scale — it is off by default.
See `docs/DECISIONS.md §24`.

The transcription includes one **deliberately low-confidence** chunk (the §3.2
single-counterparty 5% cap, `extraction_confidence = 0.78`) so the human-verification gate
is demonstrable: it loads `PENDING_REVIEW` and surfaces in `verify-graph` for a human to
approve. It anchors none of the 13 reported figures, so the figures compute regardless
(`docs/DECISIONS.md §25`).

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

Every real pipeline run writes an append-only, hash-chained audit trail to Postgres
`audit_event`. The CLI emits these event types during a full run:

| Event type | Emitted by |
|---|---|
| `config_loaded` | `run` — after config is resolved |
| `graph_construction` | `build-graph` — after positions + rules loaded |
| `node_verified` | `verify-graph --approve / --approve-all` — one event per approved node |
| `figure_computed` | `run` — one event per figure (13 events per run) |
| `reconciliation` | `reconcile` / `evaluate` |
| `report_exported` | `run` — after xlsx report written |

**Graceful degradation:** if `POSTGRES_DSN` is unset or the database is unreachable,
the CLI prints a warning to stderr and continues — the pipeline is never blocked by
audit failures.

**Inspecting the log:**

```sql
-- View all events for the latest run
SELECT event_type, actor, payload, ts
FROM audit_event
ORDER BY id DESC
LIMIT 50;
```

```python
# Verify the hash chain is intact
from src.audit.log import AuditLogger
logger = AuditLogger(dsn)
assert logger.verify_chain()
```

**Tamper protection:**

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
│   ├── firm_b.yaml            # Firm B overrides (3 knobs)
│   └── firm_c.yaml            # Firm C overrides (third independent config)
├── docs/
│   ├── 01_flow_and_audit_events.md   # Phase 1: event catalogue
│   ├── 02_architecture.md            # Phase 1: layer diagram
│   ├── 03_rfc.md                     # Phase 1: LLM containment RFC
│   ├── DECISIONS.md                  # Architecture + tooling decisions with rationale
│   └── VERIFICATION.md              # Live verification results + requirements traceability
├── sample_docs/
│   ├── sample_holdings.csv    # 13-row portfolio (input)
│   ├── firm_A_answer_key.xlsx # Expected Firm A figures (reconcile target)
│   └── report_template.xlsx   # Brief-provided template (Section+Metric pre-filled);
│                              #   system populates cols C–G and saves to out/report_*.xlsx
├── src/
│   ├── cli/main.py            # Typer CLI — 13 subcommands
│   ├── compute/               # Engine, config loader, primitives, registry
│   ├── firewall/              # LLM containment checker (6 gates)
│   ├── graph/                 # Neo4j schema, builder, queries
│   ├── ingestion/             # Holdings CSV + guidelines PDF parsers
│   ├── narrative/             # Narrative writer (LLM-optional stub)
│   ├── reconcile/             # Reconciler against answer keys
│   └── report/                # xlsx report writer
├── bin/
│   └── fundra                 # Shell wrapper — use instead of full docker compose run
├── tests/                     # Full test suite (348 tests across 27 files)
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
- **Viewer auth** — a web-based replay viewer would require at minimum read-only token
  auth before exposing audit events (the `replay` CLI command is implemented; a web UI is not).
- **Neo4j auth** — use a strong password and disable the Neo4j browser endpoint in production.
- **Audit append-only caveats** — (1) Append-only is enforced by the `enforce_audit_append_only`
  BEFORE UPDATE/DELETE trigger, which fires even for superusers running ad-hoc SQL. (2) The app
  currently connects as the Postgres superuser (`interopera`) so the `REVOKE UPDATE, DELETE` on
  `app_role` is belt-and-suspenders only — production must use a non-superuser `app_role`
  connection to enforce the INSERT-only constraint at the connection level. (3) `TRUNCATE`
  bypasses row-level DELETE triggers, so production should also `REVOKE TRUNCATE` on
  `audit_event` from all roles and restrict table ownership to a dedicated schema owner.
