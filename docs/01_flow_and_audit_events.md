# Flow and Audit Events

## 1. AS-IS vs TO-BE Reporting Flow

### AS-IS (Current State)

The legacy compliance reporting process is entirely manual and spreadsheet-driven:

- Analysts download holdings data as CSV files and paste them into Excel workbooks.
- Compliance officers manually transcribe rule limits from PDF guidelines documents into a separate spreadsheet column.
- Figures (e.g., total notional by asset class, issuer concentration) are computed by hand using ad-hoc Excel formulas that vary between analysts.
- Reconciliation against the firm's answer key is done by visual inspection — a human compares the printed report with the answer key row by row.
- There is **no automated traceability**: no link between a reported figure and the rule text that justifies it, no record of who approved which data point, and no hash chain ensuring the output was not altered after the fact.
- Audit trail exists only as email threads and dated file versions, which are not machine-queryable and frequently incomplete.

Problems with the AS-IS state:
- Non-reproducible: two analysts running the same spreadsheet may produce different answers due to copy-paste errors or formula drift.
- Non-traceable: regulators cannot follow a figure back to a source document.
- No human-review gate: there is no enforceable checkpoint that forces a human to confirm extracted data before it is used in computation.
- LLM risk (if introduced ad-hoc): an LLM could silently generate a number that is placed in a report cell with no audit trail.

---

### TO-BE (Target State)

The TO-BE system is a fully automated pipeline with explicit human-review gates, a deterministic compute engine, and a continuous append-only audit log. The LLM is structurally confined to narrative generation only.

---

## 2. TO-BE Flow with Explicit Human/Autonomous Boundaries

The pipeline consists of seven stages. Each stage is labelled as either **AUTONOMOUS** (no human action required) or **HUMAN REVIEW REQUIRED** (the engine stops and waits for an authorised actor).

---

### Stage 1 — Ingestion (AUTONOMOUS)

**Inputs:** holdings CSV file + compliance guidelines PDF

**Processing:**
- `holdings_parser.py` reads the CSV and emits one `PositionRecord` object per row. Fields: `instrument_id`, `instrument_name`, `asset_class`, `issuer_name`, `issuer_type`, `parent_issuer`, `credit_rating`, `downgraded_from`, `market_value_sgd`, `modified_duration`.
- `guidelines_parser.py` produces one `RuleChunk` object per rule (by default from a deterministic, hand-verified transcription of the PDF; an LLM-assisted extraction path exists but is off by default — see `docs/DECISIONS.md §24`). Fields: `chunk_id` (sha256 of passage text, first 16 hex chars), `source_doc`, `page`, `passage`, `passage_summary` (prose summary — does NOT contain any figure), `extracted_fields`, `extraction_confidence` (float 0–1).

**Content-hash chunk_id:** `chunk_id = sha256(text.encode()).hexdigest()[:16]`. Two identical passages will always produce the same chunk_id, enabling deduplication across re-runs.

**Audit event emitted:** none at this stage (events are emitted from the graph layer onward).

---

### Stage 2 — Graph Construction (AUTONOMOUS)

**Processing:**
- `graph_builder.py` creates Neo4j nodes for every `PositionRecord` and `RuleChunk` plus derived nodes (AssetClass, Issuer, ParentIssuer, Limit, Aggregate, etc.).
- Provenance edges (`DERIVED_FROM`) link every rule-derived `Limit` and `RiskMetric` node back to the `SourceChunk` node that produced it.
- **Node `status` is set at creation:** deterministic nodes (positions, asset classes, issuers — derived from the authoritative CSV at `extraction_confidence = 1.0`) load `VERIFIED`; rule-derived `Limit`/`SourceChunk` nodes load `VERIFIED` when `extraction_confidence ≥ 0.85`, otherwise `PENDING_REVIEW`.
- `run_id` is assigned (UUID4) and recorded on each audit event for the run.

**Audit event emitted:** `graph_construction` (see catalogue below).

---

### Stage 3 — Human-Verify Gate (HUMAN REVIEW REQUIRED)

This is the **only** stage where human action is required during a normal run.

**Auto-pass criterion:**
A node may be automatically promoted from `PENDING_REVIEW` to `VERIFIED` without human action if **both** of the following conditions are met:

1. `extraction_confidence ≥ 0.85`
2. Structural validation passes: numeric fields contain numbers, `min_value < max_value` where applicable, all required fields are present and non-null.

**Confidence by source type:**
- CSV-parsed `PositionRecord` nodes: the CSV is parsed deterministically, so `extraction_confidence = 1.0`. All position nodes auto-pass.
- PDF-extracted `RuleChunk` and derived `Limit`/`Threshold` nodes: confidence is variable (typically 0.7–0.95 depending on layout complexity). Nodes below the 0.85 threshold remain `PENDING_REVIEW`.

**Engine refusal:** The `ComputeEngine` checks the status of every node it intends to traverse before starting computation. If **any** node required for a figure is in `PENDING_REVIEW` status, the engine **refuses to proceed** and returns `{"status": "ERROR", "reason": "PENDING_REVIEW node: <node_id>"}`. It does **not** return a number.

**Human action:** An authorised human actor calls `approve_node(driver, node_id, actor)`. The `actor` parameter must be provided — the function signature rejects calls without it. The LLM cannot call this function autonomously.

**Audit event emitted:** `node_verified` for each node approved (see catalogue below).

---

### Stage 4 — Compute (AUTONOMOUS, DETERMINISTIC)

**Processing:**
- `engine.py` traverses the verified graph in topological order.
- Applies registered aggregators (sum, weighted-average, max, count-distinct) and comparators (≤, ≥, between, equals).
- Produces exactly **13 `Figure` objects**. Each Figure has: `figure_id`, `value` (Decimal, never float), `status` (`OK` / `BREACH` / `AT LIMIT`, or `ERROR` for an untraceable/blocked figure), `graph_path` (Cypher-style string built from the actual traversal, e.g. `(AssetClass:high_yield)-[:CONTRIBUTES_TO]->(Aggregate:non_ig)<-[:CONTRIBUTES_TO]-(AssetClass:structured_credit)`), `citation` (dict: `{ "source_doc": str, "page": int, "chunk_id": str, "passage_summary": str }`), `config_hash`.
- **Zero LLM involvement.** The compute layer has no import of `anthropic`, `openai`, `httpx`, or `requests`. This is enforced by a static import gate test.

**Audit event emitted:** `figure_computed` for each of the 13 figures (see catalogue below).

---

### Stage 5 — Reconcile (AUTONOMOUS)

**Processing:**
- `reconciler.py` loads the firm's answer key (xlsx or YAML format).
- Compares each computed Figure value against the corresponding answer-key entry.
- Produces a per-figure result: `{figure_id, computed, expected, delta, pass}`.
- Aggregates to overall pass/fail.

**Audit event emitted:** `reconciliation` (see catalogue below).

---

### Stage 6 — Report Export (AUTONOMOUS)

**Processing:**
- `report_writer.py` writes all 13 figures to an xlsx file (populating the provided `report_template.xlsx`). Column layout: Section, Metric, Value, Limit, Utilization, Status, Source (graph path → doc/page).
- The xlsx writer reads **exclusively from the list of `Figure` objects**. No narrative string is passed to the report writer (narrative is written to a separate file).
- Optionally, `narrator.py` generates a prose summary using the LLM. The narrative is firewalled: every numeric token in the narrative must appear in the computed figures set (enforced by `src/firewall/checker.py`).

**Audit event emitted:** `report_exported` (see catalogue below).

---

### Stage 7 — Audit (CONTINUOUS)

Every stage above emits events to the `audit_event` table in Postgres. The audit log is **append-only** (no UPDATE or DELETE). Events are chained by hash.

---

## 3. LLM Boundary

The LLM is permitted to generate prose and summaries only. It is structurally incapable of writing to report cells or compute engine outputs.

| Concern | LLM MAY | LLM MAY NOT |
|---------|---------|-------------|
| Narrative text | Generate narrative prose for the report summary section | Write to any xlsx report cell that contains a Figure value |
| Rule chunk summary | Generate `passage_summary` field in `RuleChunk` (descriptive only, no figures) | Compute a `value` for any `Figure` object |
| Graph structure | Propose graph node/edge structure (must be human-gated before use) | Directly create, modify, or delete Neo4j nodes |
| Verification | Provide supporting commentary (logged, not actioned) | Call `approve_node()` or flip a node's status to VERIFIED |
| Reconciliation | None — LLM is not involved in reconciliation | Evaluate pass/fail status for any figure |
| Report cells | None | Populate any numeric cell in the xlsx output |

---

## 4. Audit Event Catalogue

All events are written to the `audit_event` table. Each row has: `id` (SERIAL PRIMARY KEY), `event_type`, `run_id`, `actor` (system or human), `config_hash`, `payload` (JSONB), `row_hash`, `prev_hash`, `retention_class`, `ts` (TIMESTAMPTZ).

These events are emitted by the live CLI pipeline on every real run (not only in tests).

| Event | Trigger | Data Captured | Retention |
|-------|---------|---------------|-----------|
| `config_loaded` | When `load_config` is called | firm_id, SHA-256 of resolved effective config, knob values | operational |
| `graph_construction` | After `load_positions` and `load_rules` complete | position_count, rule_chunk_count | compliance |
| `node_verified` | When `approve_node` is called | node_id, labels, actor | compliance |
| `figure_computed` | After each Figure produced by engine | figure, value, status, graph_path, chunk_id, config_hash | compliance |
| `reconciliation` | After `reconcile()` produces results | firm_id, pass_count, fail_count | compliance |
| `report_exported` | After `write_report` completes | output_path, config_hash | compliance |

---

## 5. Retention Class Values

Each audit event row carries a `retention_class` field (string enum). The value controls how long the event is retained and under what deletion policy.

| retention_class | Period | Description |
|----------------|--------|-------------|
| `compliance` | **Permanent** | Long-term, immutable, regulatory retention. These rows may never be deleted or modified. Used for all events that affect reported figures, node approvals, or reconciliation outcomes. |
| `operational` | **7 years** (operational/transaction data) | Retained for operational diagnostics, still append-only. Used for events that do not directly affect regulatory outputs — e.g., config loads. |

The `retention_class` field is set at event-emit time and stored in the `audit_event` row. It cannot be changed after insertion.

---

## 6. Hash Chain

The audit log is tamper-evident via a hash chain. Each row's `row_hash` covers both the event payload and the previous row's hash, so altering any historical row breaks all subsequent hashes.

**Algorithm:**

```python
import hashlib, json

def compute_row_hash(
    event_type: str, actor: str, config_hash: str | None, payload: dict, prev_hash: str
) -> str:
    canonical = json.dumps(
        {"event_type": event_type, "actor": actor, "config_hash": config_hash, "payload": payload},
        sort_keys=True,
        default=str,
    )
    serialized = (canonical + prev_hash).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()
```

- `prev_hash` for the **first row** is the sentinel string `"genesis"`.
- Every subsequent row uses the `row_hash` of the immediately preceding row as `prev_hash`.
- The timestamp (`ts`) is intentionally excluded from the hash to avoid round-trip precision issues.

**Verification:**

Call `AuditLogger.verify_chain()` — it re-derives all row hashes in insertion order and returns `True` if the chain is intact, `False` if any row has been tampered with:

```python
from src.audit.log import AuditLogger
logger = AuditLogger(dsn)
assert logger.verify_chain(), "Audit chain integrity check failed"
logger.close()
```

Any inserted, deleted, or modified row causes the check to fail at that row and all rows after it.
