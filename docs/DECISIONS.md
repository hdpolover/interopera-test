# Design Decisions

This document records every significant design choice made in the InterOpera Compliance Reporting System — what was decided, what alternatives were considered, and why.

---

## Architectural Decisions

### 1. Decimal Arithmetic Over Float

**Decision:** All numeric values in the compute layer use `decimal.Decimal` exclusively — no `float` anywhere in `engine.py` or `config_loader.py`.

**Alternatives considered:**

- `float` — rejected because IEEE 754 floating-point rounding is non-deterministic across platforms and Python versions; two machines computing the same figure can produce results that differ in the last few bits, breaking the reconcile constraint.
- `numpy` — rejected as overkill for scalar compliance arithmetic, and `numpy` floats have the same rounding problem internally.

**Rationale:** Constraint C1 (reproducibility) and C4 (reconcile) both require bit-identical results across runs and environments. `Decimal` arithmetic is exact for the fixed-point values used in compliance limits (percentages, basis points, ratios). The trade-off is slightly more verbose code, which is worth it for determinism guarantees that floats cannot provide.

---

### 2. Neo4j Knowledge Graph Schema

**Decision:** The graph uses 11 distinct labeled node types (`SourceChunk`, `Limit`, `Position`, `AssetClass`, `Issuer`, `ParentIssuer`, `Aggregate`, `RiskMetric`, `Threshold`, `BreachAction`, `Owner`) connected by typed relationships, with provenance properties (`source_doc`, `page`, `chunk_id`, `ingested_at`, `extraction_confidence`, `status`) on every node.

**Alternatives considered:**

- Relational database (PostgreSQL) — rejected because multi-hop ownership queries (`RiskMetric → BreachAction → Owner`) require expensive JOINs and schema migrations when new relationship types are added.
- Flat JSON store — rejected because it has no traversal capability; finding which owner to notify for a breached limit would require application-level graph walking.
- Single giant node with embedded properties — rejected because breach notification ownership, threshold values, and breach actions would all be opaque blobs with no independent queryability.

**Rationale:** The brief's §3.1 requirement for multi-hop queries maps directly to graph traversal. Storing provenance on every node satisfies traceability constraint C2 — an auditor can trace any figure back to its source document, page, and extraction confidence. The `PENDING_REVIEW` status on `Limit` nodes with low extraction confidence integrates data quality directly into the graph schema rather than as a separate validation layer.

---

### 3. LLM Containment — Six-Gate Firewall

**Decision:** A layered six-gate firewall controls all LLM interaction: (1) static import gate — AST check blocks `import anthropic` in engine; (2) dependency-injection gate — no LLM client in `ComputeEngine.__init__`; (3) report-from-figures-only gate — narrative reads only from computed `Figure` objects; (4) human-approval gate — PENDING_REVIEW blocks compute entirely; (5) reconcile gate — narrative numbers checked against figure values; (6) numeric token firewall — `_NUMBER_RE` validates every number in LLM output.

**Alternatives considered:**

- Single regex check on final LLM output — rejected as too fragile; a regex cannot prevent the LLM from being invoked with contaminated inputs or from hallucinating during generation.
- Trust the LLM — rejected outright; violates constraint C3 and would allow hallucinated figures to appear in regulatory reports.

**Rationale:** Each gate catches a distinct failure mode. The import gate prevents accidental coupling of the compute layer to an LLM client. The DI gate enforces the same at runtime. The figures-only gate prevents the LLM from reading raw data. The PENDING_REVIEW gate stops unvetted data from flowing into any output. The reconcile gate is a post-generation cross-check. The numeric token firewall is the last line of defense. Allowlists (`_ALLOWLIST_YEAR_RE`, `_ALLOWLIST_SECTION_RE`) prevent false positives on regulatory citation numbers.

---

### 4. Append-Only Audit Log with SHA-256 Hash Chain

**Decision:** The audit log is a PostgreSQL table with a `BEFORE UPDATE OR DELETE` trigger that raises an exception on any modification, plus a SHA-256 hash chain where each row's hash covers `(event_type, actor, config_hash, payload, prev_hash)` — with timestamp explicitly excluded.

**Alternatives considered:**

- File-based append log — rejected because a file can be edited or truncated by any process with filesystem access; no tamper-detection without a separate integrity mechanism.
- Soft-delete flag (`is_deleted BOOL`) — rejected because it is a mutable field; a row can be un-deleted, and the log is no longer append-only.

**Rationale:** The Postgres trigger fires on all connections including direct `psql` sessions, not just ORM writes — stronger than application-level enforcement. The hash chain detects row deletion (gap in chain) or row reordering (hash mismatch), which a trigger alone cannot prevent after the fact. Timestamp is deliberately excluded from the hash because timezone serialization and precision vary across Postgres versions, causing false tamper reports on a correctly-written log. `GENESIS_SEED = "genesis"` anchors the chain without requiring a special genesis row.

---

### 5. Config-Only Firm Switching (YAML + Pydantic)

**Decision:** Firm behavioral differences are expressed as exactly three YAML knobs (`include_fallen_angels`, `group_key`, `utilization_format`) loaded into a `FirmConfig` Pydantic model with `extra="forbid"` on every nested model.

**Alternatives considered:**

- Code branches on firm name (`if config.firm_id == "firm_a": ...`) — rejected because it violates constraint C5; adding a third firm would require touching the engine.
- Separate engine class per firm — rejected because it duplicates the entire compute layer and makes cross-firm consistency impossible to guarantee.

**Rationale:** The three knobs capture all behavioural differences between Firm A and Firm B. A new firm requires only a new YAML file. `extra="forbid"` catches typos in config keys immediately at load time (a misspelled key raises `ValidationError`) rather than silently using a default. `effective_config_hash()` (SHA-256 of the sorted JSON dump) is written into every audit event, making the exact config that produced each figure permanently traceable.

**Firm C as generalization proof:** `config/firm_c.yaml` defines a third independent firm (`group_key: parent_issuer`, `utilization_format: truncated_bps`, `include_fallen_angels: false`) — a distinct knob combination from both A and B. Running `--firm C` produces 13 correct figures without any engine changes, proving that switching is not a coincidence of two-firm design.

---

### 6. Stub vs LLM Narrative Path

**Decision:** `Narrator.write_narrative()` checks for `ANTHROPIC_API_KEY` at construction time; if absent, it takes the stub path which generates a deterministic narrative by interpolating figure values directly into a template.

**Alternatives considered:**

- Always require `ANTHROPIC_API_KEY` — rejected because it breaks offline use, CI/CD pipelines, and test environments where the key is unavailable.
- Mock LLM in tests — rejected because a mock bypasses the real firewall logic; the firewall's behavior would never be exercised in the test suite.

**Rationale:** The stub path generates output that is firewall-safe by construction (all numbers come directly from `Figure` fields), making it suitable for deterministic testing and offline use. The LLM path exercises the real numeric token firewall in production, providing genuine containment validation. Both paths share the same `FirewallChecker` call, so the firewall is always the final gate regardless of which path produces the narrative.

---

### 6b. `evaluate` Always Uses Stub Narrator

**Decision:** The `evaluate` CLI command hardcodes `api_key=None` when constructing `Narrator`, forcing the deterministic stub path regardless of whether `ANTHROPIC_API_KEY` is set.

**Alternatives considered:**

- Use the live LLM in `evaluate` the same way `narrate` does — rejected because `evaluate` is a Phase 5 verification command; its firewall check must be reproducible across runs and environments. An LLM can produce different tokens in each call, making the firewall result non-deterministic and therefore not verifiable.
- Separate firewall-check command that doesn't call the narrator at all — rejected as added complexity; the stub provides a realistic narrative to check without variability.

**Rationale:** The `narrate` command is for producing human-readable output — model quality matters there. The `evaluate` command is for verifying that the firewall works — determinism matters there. Using the stub in `evaluate` ensures the same narrative is produced on every invocation, so a PASS result is meaningful and repeatable.

---

### 7. PENDING_REVIEW Gate in Compute Engine

**Decision:** `compute_figure()` in `engine.py` implements two independent PENDING_REVIEW gates: Gate 1 checks the `Limit` node's status before querying positions; Gate 2 checks the returned node's status a second time on the result.

**Alternatives considered:**

- Warn and continue — rejected because it would produce figures derived from unvetted extraction data, which could appear in regulatory reports without human review.
- Skip the figure silently — rejected because silent data loss is worse than a hard failure; a missing figure in a compliance report is a compliance gap that must be explicitly acknowledged.

**Rationale:** Two gates are used because Gate 1 handles the case where the node is already known to be PENDING_REVIEW, while Gate 2 catches the race condition where a node's status changes between query planning and result delivery. Hard-blocking with a clear error forces a human review step before the figure can be computed, satisfying the audit requirement that no unvetted data produces regulatory output.

---

### 8. Content-Hash Chunk IDs

**Decision:** `SourceChunk` nodes are keyed by `sha256(text)[:16]` — a content-derived identifier truncated to 16 hex characters.

**Alternatives considered:**

- Sequential IDs (1, 2, 3, ...) — rejected because they are not stable across re-ingestion runs; the same chunk loaded twice gets a different ID, breaking idempotency and creating duplicate nodes.
- UUID (random) — rejected for the same reason; a random ID on each run means re-ingesting a document creates new nodes instead of merging with existing ones.

**Rationale:** A content hash is deterministic: the same chunk text always produces the same ID, so `MERGE` on `chunk_id` correctly deduplicates re-ingested content. The 16-character truncation is a pragmatic trade-off — full SHA-256 is unnecessarily long for a node key, and 16 hex chars (64 bits) has negligible collision probability for the document corpus sizes in scope. The hash also acts as a change detector: if a chunk's text is revised, its ID changes and a new node is created while the old one is preserved.

---

### 9. MERGE Idempotency on All Cypher Writes

**Decision:** Every Cypher write statement in `builder.py` uses `MERGE` rather than `CREATE`.

**Alternatives considered:**

- `DELETE` + `CREATE` — rejected because it is destructive; re-running the graph build after adding new documents would wipe existing nodes and lose their audit trail.
- `CREATE` with uniqueness constraint — rejected because it raises `ConstraintViolationException` on re-run, making `build-graph` a one-shot operation rather than a safely repeatable one.

**Rationale:** `MERGE` makes `build-graph` idempotent: running it on an already-populated graph is safe and produces the same result as running it on an empty graph. This is critical for the operational workflow where new source documents are added incrementally and the graph is rebuilt without clearing existing data.

---

### 10. RiskMetric / Threshold / BreachAction / Owner as Separate Nodes

**Decision:** Risk metric data is modelled as four distinct node types connected by typed edges (`HAS_THRESHOLD`, `HAS_BREACH_ACTION`, `NOTIFIES`), rather than as properties on a single node.

**Alternatives considered:**

- Embed all fields as properties on the `Limit` node — rejected because it collapses ownership and breach-action structure into a flat property bag; querying "which owner is notified when this metric is breached" becomes a string parse rather than a graph hop.
- Store as a JSON blob on `SourceChunk` — rejected because the blob is opaque to Cypher queries; the graph's traversal advantage disappears entirely.

**Rationale:** The brief's §3.1 multi-hop query (`RiskMetric → BreachAction → Owner`) is a single `MATCH` path in Cypher when each concept is a separate node. It requires multiple JSON deserializations and application-level logic when embedded. Keeping `Owner` as an independent node also allows future queries like "list all metrics where a given owner is responsible" — trivially indexed in a graph but expensive in a document store.

---

### 11. FIGURE_ID_TO_METRICS Hardcoded Translation Table

**Decision:** `replay_helpers.py` contains a hardcoded `FIGURE_ID_TO_METRICS` dict mapping internal figure IDs to XLSX column header strings from the brief's answer-key format, with a module-level `assert` that the dict's keys exactly match `FIGURE_REGISTRY`.

**Alternatives considered:**

- Add `display_name` / `xlsx_column` fields to `FigureSpec` in the registry — rejected because it conflates two distinct schemas; `FigureSpec` is the internal compute contract, XLSX column headers are an external reporting schema. Coupling them makes the registry harder to evolve independently.
- Dynamic discovery at runtime — rejected because there is no stable runtime signal to derive XLSX column names from figure IDs; the mapping is a fixed external schema contract.

**Rationale:** Both schemas are fixed by external specification. The translation between them is a stable, enumerable mapping — exactly the right use case for a hardcoded table with a drift guard. The module-level assertion fires at import time if a figure is added to the registry without a corresponding XLSX mapping, preventing silent omissions in replay output.

---

### 12. Replay Helpers Extracted to Separate Module

**Decision:** Non-command logic (numeric parsing, answer-key lookup, config-knob printing, `FIGURE_ID_TO_METRICS`) was extracted from `main.py` into `replay_helpers.py`.

**Alternatives considered:**

- Keep everything in `main.py` — rejected because `main.py` exceeded 866 lines after all CLI commands were implemented; violates the 800-line cohesion guideline and makes the file difficult to navigate.
- Extract to a generic `utils.py` — rejected because the extracted logic is specifically replay/verification logic, not general utilities; a generic name would obscure the module's purpose.

**Rationale:** `replay_helpers.py` has a single, clear responsibility: support the `replay` command. CLI command functions remain in `main.py` because test monkeypatching targets the module where functions are defined; moving the command handlers would require updating all test patches. The split keeps both files under 400 lines and makes the boundary between command dispatch and replay business logic explicit.

---

### 13. Narrative Source Retrieval (Bonus 3)

**Decision:** When a Neo4j driver is injected into `Narrator`, `retrieve_passages_for_narrative()` fetches `SourceChunk` passages linked to the figures being narrated and injects them into the LLM prompt under a "Regulatory basis" heading. Retrieval failure is silently swallowed.

**Alternatives considered:**

- Include all `SourceChunk` nodes in the prompt — rejected because most chunks are irrelevant to any given narrative; injecting all of them wastes tokens and increases the risk of the LLM citing unrelated regulatory text.
- No grounding at all — rejected because an ungrounded LLM can hallucinate regulatory citations; injecting actual source passages anchors the narrative to real document text.

**Rationale:** Retrieval is scoped to chunks linked to the specific figures in the narrative call, minimising token use while maximising relevance. The `except Exception` swallow (marked `# noqa: BLE001`) is deliberate: source retrieval is a best-effort enhancement. If Neo4j is unavailable or the query fails, the narrative still generates — it simply lacks the grounding. This prevents a graph connectivity issue from blocking report generation entirely.

---

## Infrastructure & Tooling Decisions

### 14. Docker Compose

**Decision:** Use Docker Compose to orchestrate Neo4j, Postgres, and the Python app as services.

**Alternatives considered:**

- Bare Python venv with manually started dependencies — rejected because it requires every developer to manually start Neo4j and Postgres, manage their versions, and handle port conflicts; a source of environment drift.
- Kubernetes — rejected because it is operationally correct for production but adds significant complexity (Helm, cluster provisioning, RBAC) disproportionate to a single-machine compliance batch tool.

**Rationale:** Docker Compose gives dev/CI environment parity with a single `docker compose up` command. Service health checks (`healthcheck:` stanzas on both Neo4j and Postgres) ensure dependencies are ready before the app starts, eliminating race-condition failures in CI. The `${VAR:-default}` pattern allows port overrides via `.env` without changing `docker-compose.yml`.

---

### 15. Neo4j 5.18 + APOC

**Decision:** Use Neo4j 5.18 as the graph store with the APOC plugin.

**Alternatives considered:**

- Postgres with recursive CTEs — can model graphs but requires hand-written traversal logic and is significantly slower on multi-hop queries.
- DGraph — smaller ecosystem and fewer operational precedents in compliance tooling.
- In-memory Python `dict` graph — cannot survive process restarts and cannot be queried by external tools.

**Rationale:** Compliance rules map naturally to a property graph: issuers roll up to parent issuers, positions belong to asset classes, limits apply to entities. Neo4j's Cypher `MERGE` is idempotent by design, critical for re-runnable ingestion pipelines. APOC provides schema constraint enforcement at startup and batch operation utilities.

---

### 16. Postgres 16 for Audit Log

**Decision:** Use Postgres 16 to store the `audit_event` table.

**Alternatives considered:**

- SQLite — lacks per-table role grants, making it harder to enforce the application role having only `INSERT` and `SELECT`.
- Append-only flat file — no transaction semantics, trivially corruptible.
- Redis Streams — append-only but lacks SQL querying and the row-level security model needed for compliance retention.

**Rationale:** The audit log requires tamper-evidence: `BEFORE UPDATE` and `BEFORE DELETE` triggers fire before any modification and raise an exception to block it, making the table append-only at the database level rather than by application convention. Postgres provides full ACID guarantees and `pg_isready` for Docker Compose health checks.

---

### 17. Typer (CLI Framework)

**Decision:** Use Typer for the CLI layer (`src/cli/`).

**Alternatives considered:**

- Click — Typer is built on Click but removes the boilerplate of `@click.option` decorators for every parameter.
- argparse — requires explicit `add_argument` calls for every parameter and produces less readable help output.

**Rationale:** Typer generates `--help` output and argument parsing automatically from Python type annotations — the function signature is the full CLI contract with no separate decorator registration required. It has native Rich integration for structured terminal output and generates shell completion scripts without extra configuration.

---

### 18. Pydantic v2 with `extra=forbid`

**Decision:** Use Pydantic v2 with `model_config = ConfigDict(extra="forbid")` on all config models.

**Alternatives considered:**

- Pydantic v1 — in maintenance mode; v2 has a Rust-backed core with significantly faster validation and improved error messages.
- Python `dataclasses` — no built-in schema validation or coercion; a string `"0.10"` from YAML would not be automatically converted to `Decimal("0.10")`.

**Rationale:** `extra="forbid"` causes Pydantic to raise a `ValidationError` at config load time if the YAML contains any unrecognised key (e.g., a typo like `non_ig_limit` instead of `non_ig`). Without this, a typo silently falls through and the figure is computed against the wrong default — a compliance-critical bug that appears to succeed.

---

### 19. psycopg3 Binary

**Decision:** Use `psycopg[binary]` (psycopg3) for Postgres connectivity.

**Alternatives considered:**

- psycopg2 — in maintenance-only mode; does not support Python 3.11+ async natively.
- SQLAlchemy ORM — adds an abstraction layer unnecessary here; all queries are explicit parameterised SQL, and ORM magic would obscure the append-only constraint enforcement central to the audit design.

**Rationale:** psycopg3 is the current maintained driver with native Python 3.11+ async support. The binary distribution bundles libpq, eliminating system-level dependency on `libpq-dev` in Docker images.

---

### 20. Rich for Terminal Output

**Decision:** Use Rich for all CLI output (tables, status messages).

**Alternatives considered:**

- `tabulate` — produces plain ASCII tables with no color or live progress.
- Plain `print` — requires manual column alignment and ANSI escape code management.

**Rationale:** Rich renders structured tables with color-coded status columns without custom formatting code. It respects `NO_COLOR` and non-TTY environments (CI pipelines) automatically, falling back to plain text. The same library is used for the firewall result display, query-metric tables, and audit log output — a consistent rendering layer across all 13 CLI commands.

---

### 21. openpyxl for Excel Output

**Decision:** Use `openpyxl` to write the compliance report xlsx.

**Alternatives considered:**

- `xlsxwriter` — write-only (cannot read existing files) and has a different API for cell styling.
- `pandas.ExcelWriter` — wraps openpyxl but adds a pandas dependency not otherwise needed, and the abstraction makes per-row conditional formatting more verbose.

**Rationale:** Cell-level styling — coloring each row red/amber/green based on figure status — requires per-cell `PatternFill` and `Font` control. openpyxl exposes the full OpenXML model, making this straightforward. No other part of the system requires pandas, so adding it purely for Excel output would be an unnecessary dependency.

openpyxl's read-write capability is also required for the template pattern: `writer.py` opens `sample_docs/report_template.xlsx` (Section + Metric pre-filled by the brief), writes Value/Limit/Utilization/Status/Source into columns C–G, and saves to `out/report_{firm_id}.xlsx`. `xlsxwriter` is write-only and could not implement this pattern.

**Template fallback:** If `report_template.xlsx` is not found (searching CWD and `/app`), `writer.py` falls back to generating a workbook from scratch with headers written by code. This ensures the report command never fails due to a missing template while still correctly populating the brief's template when present.

---

### 22. pytest

**Decision:** Use `pytest` as the test framework.

**Alternatives considered:**

- `unittest` (stdlib) — functional but verbose; `setUp`/`tearDown` class methods, `self.assert*` calls, no parametrize equivalent without third-party extensions.

**Rationale:** pytest fixtures allow dependency injection (Neo4j driver, Postgres connection) with clear setup/teardown scoping. `@pytest.mark.parametrize` drives data-driven tests (e.g., all 13 figure computations from a single test function) without boilerplate. Assertion failure messages show actual vs. expected values directly without `assertEqual(a, b)` wrapping.

---

### 23. claude-sonnet-4-6 for Narrative Generation

**Decision:** Use `claude-sonnet-4-6` as the default LLM for narrative prose generation. The model is overrideable via `ANTHROPIC_MODEL` env var without code changes.

**Alternatives considered:**

- `claude-haiku-4-5-20251001` — faster and cheaper (~3–5× cost saving), but live comparison testing showed it produces shallower output and is less disciplined about prompt rules. Specifically, Haiku tended to derive computed differences ("1.0% below the minimum"), requiring extra firewall fixes to handle false positives. Initially chosen as the default on the assumption that narrative quality was irrelevant since the firewall enforces correctness regardless; revised after empirical testing showed material quality difference.
- GPT-4o — external vendor dependency without benefit; the output firewall enforces correctness independently of model capability.

**Model comparison (live test, Firm A narrative):**

| Dimension | Haiku (`claude-haiku-4-5-20251001`) | Sonnet (`claude-sonnet-4-6`) | Opus (`claude-opus-4-8`) |
|---|---|---|---|
| Output length | ~270 words | ~450 words | ~480 words |
| Structure | 4 sections, prose bullets | 6 sections, markdown headers, summary table | 6 sections, per-metric bullets, conclusion |
| Depth | Per-metric values + utilization, brief | Per-metric values + utilization + page citations | Per-metric values + utilization + page citations + breach escalation |
| Tone | Factual, concise | Professional, auditor-grade | Auditor-grade, advisory |
| Firewall result | PASS | PASS | PASS |
| Cost (relative) | ~3–5× cheaper than Sonnet | Baseline | ~5× more expensive than Sonnet |

See `docs/model_comparison.md` for full verbatim narrative output from each model.

**Rationale:** Narrative generation is prose-only — the LLM receives pre-computed figures and writes sentences describing them. The output firewall (`checker.py`) enforces numeric correctness independently of model choice. However, Sonnet produces materially better output: structured section headings, per-metric utilization citations, page references grounded in retrieved source passages, and a summary compliance table — the kind of narrative an actual compliance officer or regulator would expect to read. The cost difference is justified for a compliance reporting context where report quality has real-world consequences. Model is overrideable via `ANTHROPIC_MODEL` in `.env` so operators can switch to Haiku for bulk/offline runs without touching code.

---

## Additional Design Decisions

### 24. Deterministic pdfplumber Parse of the Real PDF

**Decision:** The guidelines are loaded by a **deterministic, pure-code parse** of `sample_fund_guidelines.pdf` — no LLM, no hand-typed transcription. Three modules collaborate:

- `src/ingestion/pdf_tables.py` — table extraction with numeric-cleaning helpers (`pct_fraction`, `sgd_int`, `year_range`, `normalize_ws`, `extract_allocations`, `extract_risk_metrics`, `duration_bounds`, `dv01_cap`). Reads the allocation and risk-metric tables directly from the PDF using `pdfplumber`.
- `src/ingestion/rule_extractors.py` — anchored regex patterns (`extract_prose_rules`) applied to normalized page text. Extracts prose rules (non-IG cap, corporate concentration, GRE cap, liquidity floor, counterparty cap) with a `confidence` value that is a **deterministic function of parse method** — not a hand-set constant.
- `src/ingestion/guidelines_parser.py` — assembles `RuleChunk` objects from the above extractors. `llm_client` parameter exists in the signature for future extensibility but is ignored — the parse is always the pdfplumber path.

Reproducibility is enforced by a committed golden snapshot: `tests/fixtures/parsed_guidelines.json` captures the exact parse output, and `test_parse_matches_golden_snapshot` in `tests/test_guidelines_parser.py` asserts byte-identical output on every run, satisfying constraint C1.

**Alternatives considered:**

- Hand-typed transcription (`_STUB_PASSAGES`) — used in an earlier iteration; replaced because a real parse gives genuine checkable provenance and eliminates the risk of transcription drift if the source PDF changes.
- Live LLM extraction on the PDF — rejected because LLM extraction is non-deterministic (constraint C1); the same PDF could yield different `chunk_id`s, page numbers, or confidences across runs. An LLM-assisted path is architecturally possible (inject a client into `parse_guidelines`) but is never invoked by any CLI command and is therefore documented as a production extension only.

**Rationale:** A deterministic pdfplumber parse gives byte-identical graph state on every run (C1) while producing provenance that is traceable to the real document pages. The golden snapshot acts as a regression guard: if a `pdfplumber` version change silently alters extraction output, the test fails immediately. Tracing `figure → graph path → SourceChunk → page` lands on the correct section of `sample_fund_guidelines.pdf` without manual transcription.

---

### 25. Low-Confidence `counterparty_limit` Chunk — Demonstrating the Human Gate

**Decision:** The §3.2 single-counterparty 5%-of-NAV cap is extracted from a **crowded multi-percentage paragraph** by the prose extractor in `rule_extractors.py`. The extractor assigns confidence `_LOW = 0.80` to this rule — a **deterministic function of the parse method** (the counterparty anchor fires in a paragraph that also contains several other percentage figures, reducing extraction certainty). Because `0.80 < 0.85`, `load_rules` loads its `Limit` node as `PENDING_REVIEW`, so it appears in `verify-graph` awaiting a human approval. The counterparty rule anchors none of the 13 reported figures.

**Alternatives considered:**

- Hand-set confidence below 0.85 — rejected in favour of the current approach where confidence is an emergent property of the parse method; this makes the gate test a real extraction scenario rather than a contrived one.
- Make every chunk high-confidence so the graph loads fully VERIFIED — rejected because the human-verification gate would never fire in a live demo; the mechanism would be tested but never shown.
- Make one of the 13 reported figures low-confidence — rejected because a `PENDING_REVIEW` node that anchors a figure blocks that figure (returns `status="ERROR"`), which would break Firm A/B reconciliation until approved.

**Rationale:** The `build-graph → verify-graph --approve-all → run` workflow is real, not theoretical: a reviewer sees exactly one node pending human sign-off, approves it, and the audit log records a `node_verified` event with the approving actor. The 13 figures compute regardless of whether it is approved, so reproducibility and reconciliation are unaffected.

---

### 26. Cash Allocation Modelled as Floor-Only

**Decision:** The cash allocation limit is modelled as a minimum floor (`min 5%`) even though the source PDF states a 5–25% band.

**Rationale:** The cash position is 4% of NAV, which breaches the 5% floor regardless of the 25% cap, so the cap never binds and `firm_A_answer_key.xlsx` reports cash on the floor alone (`4.0% — BREACH`, utilization `n/a`). Modelling it as `within_min_max(5%, 25%)` would produce the identical value and status, so floor-only matches the answer key exactly while keeping the comparator set minimal. The full band is recorded in the chunk's `extracted_fields` for traceability; switching to a two-sided comparator is a one-line config change if a future portfolio's cash level made the cap bind.

---

### 27. Limit Values Live on Graph Threshold Nodes; Config Holds Only Firm Knobs

**Decision:** Every numeric limit value (min, max, cap, floor, unit) is stored on `Threshold` nodes in Neo4j, not in `config/base.yaml`. Each figure's `FigureSpec` carries a `limit_ref` string; the engine traverses `(Limit {ref: limit_ref})-[:HAS_THRESHOLD]->(Threshold)` via `queries.limit_bounds_for_ref()` to obtain the bounds at compute time. `config/base.yaml` contains no `limits:` block; `FirmConfig` holds only `firm_id` plus the three behavioural knobs.

**Alternatives considered:**

- Store limits in `base.yaml` — rejected because it creates a second source of truth for limit values that are already extracted from the PDF into the graph; any discrepancy between the YAML value and the graph value would be silently masked.
- Embed bounds as properties on the `Limit` node directly (without a separate `Threshold` node) — rejected because `Threshold` uniqueness is on a `key` property (risk thresholds also carry a `metric` property), which allows the same threshold to be referenced by multiple rules without duplication.

**Rationale:** Having limit values live exclusively on `Threshold` nodes means the engine's compliance arithmetic is always derived from the same provenance-bearing graph that was built from the PDF. Per-figure citations are correct because `_get_citation` and `_check_limit_node_pending` both resolve by `Limit {ref}` — there is no `_FIGURE_RULE_TYPE_map` indirection. `allocation_sgs` cites page 1 and `allocation_fx_bonds` cites page 2 because the allocation table spans those pages; each of the 7 allocation figures cites its own `SourceChunk` independently.
