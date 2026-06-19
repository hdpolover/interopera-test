# InterOpera Take-Home — System Design Spec

**Date:** 2026-06-19
**Author:** Hendra (with Claude)
**Status:** Approved design, pre-implementation
**Source brief:** `extracted/Software Engineer Homework/homework_brief.pdf`

---

## 0. Problem in one paragraph

Build a system that produces an **auditable fund-compliance report** from a guidelines
PDF + a holdings CSV. For every rule, state whether the portfolio is inside its limit, by
how much, and **where each figure came from**. The system must reproduce two firms' answer
keys, where the second firm computes several figures by different conventions — **switchable
by configuration only, no code edit**. The defining property is auditability: every number
must be reproducible, traceable through a knowledge graph to its source passage, and provably
**not produced by the language model**.

## 1. The five hard constraints (the spine)

| # | Constraint | How the design satisfies it |
|---|---|---|
| 1 | **Reproducible** — same input ⇒ identical figures | `Decimal` math, sorted traversals, NAV computed once, fixed rounding, `verify-determinism` double-run diff |
| 2 | **Traceable through the graph** — figure → graph path → source chunk | Selectors are graph traversals; `graph_path` generated from the *actual* matched path; citation = a real `SourceChunk` node reached via `DERIVED_FROM` |
| 3 | **No LLM numbers** — LLM writes narrative only | Six containment gates (§3.1): static import gate, DI gate, report-from-figures, output firewall, human-only approval, pure-code checks |
| 4 | **Reconcile Firm A** | `reconcile` parses `firm_A_answer_key.xlsx`, per-figure pass/fail + delta, exact match expected |
| 5 | **Reconfigure to Firm B, no code edit** | Engine has zero firm bias; both firms are equal config files; `grep` proves no `if firm==B` exists |

## 2. Tech stack (decided)

- **Language:** Python. Strongest data/numeric + xlsx + PDF tooling for an audit-compute task.
- **Knowledge graph:** **Neo4j** (Docker). Chosen because the brief grades "*is traceability
  through the graph*" hardest and will open the graph and trace a figure. Cypher *is* traversal
  in a separate visible store — undeniably "through the graph." Multi-hop queries are native.
  Neo4j Browser visualizes the graph free (serves the human-verify gate + bonus viewer).
- **System-of-record / audit log:** **Postgres** (Docker). Chosen over SQLite because the
  assignment's identity is "defensible to an examiner": Postgres `REVOKE UPDATE,DELETE` at the
  role level is the most convincing immutability proof ("structurally cannot delete," not "a
  trigger I could drop"). Coherent split: Neo4j = knowledge graph, Postgres = immutable ledger.
- **Orchestration:** docker-compose, single command (`docker compose up`).
- **LLM:** optional Anthropic Claude with **graceful deterministic fallback**. Engine runs
  fully without a key (stub narrative); real narrative kicks in if `ANTHROPIC_API_KEY` is set.
  The firewall check runs either way. Rationale: "does it run" (#3 in evaluation) is graded —
  the engine must start with no key, since the evaluator may not set one. Narrative is garnish;
  numbers are not.
- **UI:** CLI-first. Neo4j Browser covers graph inspection. A thin read-only FastAPI replay
  viewer is built **last, only if Phases 3–5 land with time** (bonus +2–4). No heavy SPA — YAGNI.

### Rejected alternatives (and why)
- **Embedded graph (Kuzu/networkx):** real graph but loses the visible-store optic on the
  exact dimension graded hardest. Only worth it if we feared compose fragility; we want Docker
  anyway.
- **SQLite audit:** lower run-surface but weaker immutability story than role-level revoke.
- **Strategy/plugin class per firm:** Firm B logic would live *in code* — reads as a constraint-5
  fail-smell (a new firm = a new `.py`). Rejected for declarative config.
- **Rules-as-subgraph (computation rules stored in Neo4j):** elegant but overengineered for one
  week, hurts determinism + debuggability. Violates KISS / "quality over size."

## 3. Architecture & module boundaries

**Driving principle:** the LLM must be *structurally* incapable of touching a number. The
number-path and the prose-path are separate modules that meet only at the end, one-directionally
(prose reads numbers, never writes them).

```
ingestion/
  guidelines_parser   PDF → rule chunks (limit, threshold, breach action, owner, retention) + provenance
  holdings_parser     CSV → position records
  → emits "candidate graph": nodes/edges w/ source_doc, page, chunk_id, ingested_at, extraction_confidence

graph/
  schema              node/edge type definitions, Neo4j constraints
  builder             load candidate graph → Neo4j (provenance on every node + edge)
  queries             parameterized Cypher traversals (selectors live here)

compute/              ← the heart, fully deterministic, NO LLM
  config_loader       load + merge + validate firm YAML
  registry            declarative figure-specs
  primitives          selectors / aggregators / comparators / formatters
  engine              per figure: traverse → math → compare → format → Figure | Error

audit/                Postgres append-only (REVOKE + trigger + hash chain), every event logged
reconcile/            computed figures vs answer-key xlsx → pass/fail + delta
report/               populate report_template.xlsx
narrative/            LLM (optional) reads Figures, writes prose
firewall/             extract numbers from prose, assert ⊆ computed numbers
cli/                  entrypoint: ingest / build-graph / verify-graph / run / reconcile / evaluate / …
viewer/ (optional)    FastAPI read-only replay
```

**Data flow (one direction; numbers never loop back through the LLM):**
```
docs → ingest → candidate graph ──[human verify gate]──> Neo4j
                                                            │
                              firm config ──> compute engine (traverse + math)
                                                            │
                              ┌─────────────────────────────┼───────────────┐
                              ▼                             ▼               ▼
                        figures.json                  report.xlsx     reconcile vs key
                              │
                              └──> narrative (LLM, optional) ──> firewall check
            (audit log records every stage in Postgres, append-only)
```

## 3.1 LLM containment (defense-in-depth for constraint 3)

The LLM must be *structurally absent* from every number-and-verification path — not merely
firewalled at the output. Six gates, each enforced by code a reviewer can run:

**Producing numbers:**
1. **Static import gate (build-time, provable).** A test scans `src/compute/` and fails the build
   if it imports any LLM client (`anthropic`, `openai`, `httpx`, …). The number path cannot call
   an LLM because the import is not there. Provable by grep + test.
2. **Dependency-injection gate (runtime).** The compute engine constructor takes only
   `(graph, config)` — no LLM handle is ever passed in. There is no object to call. A test asserts
   the engine's dependency set contains no LLM client.
3. **Report cells come from `figures.json`, never narrative.** The xlsx writer reads computed
   figures; narrative is a separate text field. Even the report's numbers bypass the LLM entirely.
4. **Output firewall** (see §7): every narrative number ∈ computed set, else FAIL.

**Verifying / approving:**
5. **Human-only approval.** Flipping a node to `VERIFIED` is a human/CLI action; the LLM cannot
   approve its own extraction. `extraction_confidence` alone cannot auto-pass — **deterministic
   structural validation** (`min<max`, numeric, required fields) is a *hard* requirement, so an
   over-confident LLM extraction is blocked by code, not trust.
6. **All Phase 5 checks are pure code.** Reconciliation, traceability, and firewall are deterministic
   comparisons — never "ask the LLM if these match." LLM-judged verification would itself be a
   constraint-3 failure.

**Boundary, stated crisply:** the LLM may *propose graph structure* (human-gated) and *write prose*
(firewalled). It may **never** produce/round/alter a figure, populate a report cell, approve a node,
or judge a check. Constraint 3 is thereby a property enforced by tests, not an assertion.

## 4. Knowledge graph model (Phase 2)

### Node types
| Node | Key props | Source |
|---|---|---|
| `AssetClass` | name | guidelines §2 |
| `Limit` | kind (allocation/concentration/liquidity), min, max | §2 / §3.2 / §3.3 |
| `Aggregate` | name (`non_ig`), cap | §2 note |
| `RiskMetric` | name (duration, dv01…), frequency | §3.1 |
| `Threshold` | min, max, unit | §3.1 |
| `BreachAction` | text | §3.1 |
| `Owner` | role (PM, Risk Committee, CRO…) | §3.1 |
| `Issuer` | name, issuer_type | holdings |
| `Position` | instrument_id, market_value, modified_duration, credit_rating, downgraded_from | holdings rows |
| `SourceChunk` | doc, page, chunk_id, passage_summary | **traversal terminus for citations** |

### Edge types
`AssetClass-[:HAS_LIMIT]->Limit` · `AssetClass-[:CONTRIBUTES_TO]->Aggregate` ·
`RiskMetric-[:HAS_THRESHOLD]->Threshold` · `RiskMetric-[:HAS_BREACH_ACTION]->BreachAction-[:NOTIFIES]->Owner` ·
`Position-[:IN_ASSET_CLASS]->AssetClass` · `Position-[:ISSUED_BY]->Issuer-[:ROLLS_UP_TO]->ParentIssuer` ·
**every rule node `-[:DERIVED_FROM]->SourceChunk`**.

### Provenance — two deliberate layers
1. **Props on every node + edge:** `source_doc, page, chunk_id, ingested_at, extraction_confidence`
   (brief requires this).
2. **`SourceChunk` as real nodes:** so a figure's `graph_path` *terminates at a source node by
   traversal* — literally the `figure → graph path → source chunk` the examiner traces. Props
   alone would not be "through the graph."

**Why `Limit`/`Threshold`/`BreachAction` are separate nodes** (not props on `AssetClass`): the
multi-hop requirement. *"Breach action if duration exceeds limit, and who's notified?"* =
`(RiskMetric{duration})-[:HAS_BREACH_ACTION]->()-[:NOTIFIES]->(Owner)` — one traversal, no
document re-read. Folding into props kills that.

### Human-verify gate (enforced, not cosmetic)
- Each node carries `status`: `VERIFIED` or `PENDING_REVIEW`.
- **Auto-pass criterion:** `extraction_confidence ≥ 0.85` **AND** structural validation passes
  (numeric where expected, `min < max`, required fields present). CSV positions parse
  deterministically → confidence `1.0` → auto-pass. PDF-extracted rules → variable confidence.
- Below threshold or failing validation → `PENDING_REVIEW`.
- **The teeth:** the compute engine *refuses* any node not `VERIFIED`. A figure depending on an
  unverified node returns **ERROR**, not a number. CLI `verify-graph` lists pending nodes; a
  human approves → flip to `VERIFIED` → logged in audit.
- **Extraction vs constraint 3:** guidelines extraction is **LLM-assisted but human-gated**. The
  LLM may *propose* graph structure (not a number) — it never produces a *reported figure*, and
  everything it proposes is human-verified before the engine trusts it. This boundary is documented
  in the RFC because the reviewer will probe it.

## 5. Compute layer (Phase 3 ⭐ — the core)

A **figure registry** (declarative specs) over a **fixed primitive library**. Every figure is
spec + primitives; none hand-coded. That keeps Firm A/B as config, not code.

### Primitive library
- **Selectors** (parameterized Cypher, return nodes + provenance, `ORDER BY instrument_id`):
  `positions_in_asset_class(ac)` · `positions_matching(predicate)` · `positions_by_issuer(group_key)` ·
  `liquid_positions()` · `all_positions()` · `limit_node(ref)` · `aggregate_node(name)` · `threshold_node(metric)`.
- **Aggregators** (pure Python, `Decimal`): `nav` (denominator, computed once) · `sum_pct` ·
  `weighted_avg_duration` · `dv01` · `max_group_pct`.
- **Comparators:** `within_min_max` · `max_cap` · `min_floor` → `OK / BREACH / AT LIMIT` (`==` ⇒ AT LIMIT).
- **Formatters:** `percent_1dp` ("35.0%") · `truncated_bps` (`floor(util×100)` → "5833 bps") ·
  `years_2dp` · `sgd_dv01` ("SGD 38,790 / bp").

### Spec example
```yaml
- id: aggregate_non_ig_exposure
  selector:   positions_matching
  predicate:  { asset_class_in: [high_yield, structured_credit] }   # Firm A; Firm B adds include_fallen_angels
  aggregator: sum_pct
  limit_ref:  aggregate_node(non_ig).cap
  comparator: max_cap
  formatter:  percent_1dp
```

### Output shape (brief's exact contract)
```json
{ "figure": "aggregate_non_ig_exposure", "value": "15.0%", "status": "OK", "limit": "max 20%",
  "graph_path": "(AssetClass:high_yield)-[:CONTRIBUTES_TO]->(Aggregate:non_ig)<-[:CONTRIBUTES_TO]-(AssetClass:structured_credit)",
  "citation": { "source_doc": "sample_fund_guidelines.pdf", "page": 4, "chunk_id": "chunk_9c1a",
                "passage_summary": "Section 4.2 — aggregate non-investment-grade exposure cap" } }
```
- `graph_path` is **generated from the actual traversal**, never an authored string → it cannot
  lie about provenance.
- If a selector cannot reach a `SourceChunk`, or hits a `PENDING_REVIEW` node → `status: ERROR`,
  **returned not silently dropped** (brief requirement).

### The 13 figures (all hand-verified against the CSV)
NAV = SGD 100,000,000.

| # | Figure | Firm A value | Limit | Status |
|---|---|---|---|---|
| 1 | Allocation SGS | 35.0% | 20–60% | OK |
| 2 | Allocation MAS Bills | 8.0% | 0–40% | OK |
| 3 | Allocation IG Corp | 33.0% | 10–50% | OK |
| 4 | Allocation High Yield | 9.0% | 0–15% | OK |
| 5 | Allocation FX Bonds | 5.0% | 0–20% | OK |
| 6 | Allocation Structured Credit | 6.0% | 0–10% | OK |
| 7 | Allocation Cash | 4.0% | min 5% | **BREACH** |
| 8 | Aggregate non-IG | 15.0% | max 20% | OK |
| 9 | Largest single corporate issuer | 8.0% | max 8% | **AT LIMIT** |
| 10 | Largest GRE issuer | 7.0% | max 12% | OK |
| 11 | Liquid assets ratio | 47.0% | min 25% | OK |
| 12 | Portfolio modified duration | 3.88 yrs | 2.0–6.5 | OK |
| 13 | Portfolio DV01 | SGD 38,790/bp | max 85,000 | OK |

Hand-derivation of the two hardest:
- Duration = Σ(mv×dur)/NAV = 387.9M / 100M = **3.879 → 3.88 yrs**.
- DV01 = Σ(mv×dur×0.0001) = 387.9M × 0.0001 = **38,790 / bp**.

### Determinism, concretely
`Decimal` not float (no FP drift, defensible in audit); positions sorted by `instrument_id`; NAV
computed once and reused; fixed `ROUND_HALF_UP` at a stated scale. Re-run ⇒ byte-identical.

### graph_path fidelity (deliberate, documented)
The brief's sample path is **Firm A's** (asset-class selection). For Firm A the engine's generated
path equals that string (edges modeled to guarantee it) — exact reproduction. **Firm B's path
differs** because fallen angels are a *position-level rating fact*: Firm B's 21% must additionally
traverse `Position → rating`. Forcing Firm B's number under Firm A's path shape would be the actual
trap (a path that lies about how the number was made — the exact "graph built but numbers computed
elsewhere" failure the brief warns about). So `graph_path` reflects each firm's real method.

#### Concentration figure graph_path format
For `largest_single_corporate_issuer` and `largest_gre_issuer`, the `graph_path` is generated
from the **actual winning group** — the group name and member instrument_ids are threaded from
`_compute_group_value` into `_build_graph_path`. The format differs by `group_key`:

- **`group_key=issuer`** (Firm A GRE by immediate issuer):
  ```
  (Position:COR-03)-[:ISSUED_BY]->(Issuer:Redhill Power Pte Ltd)
  ```
- **`group_key=parent_issuer`** (Firm B GRE by parent, includes ROLLS_UP_TO):
  ```
  (Position:COR-03, COR-04)-[:ISSUED_BY]->(Issuer)-[:ROLLS_UP_TO]->(ParentIssuer:Redhill Holdings)
  ```
- **Single corporate issuer** (group_key=issuer, one instrument):
  ```
  (Position:COR-01)-[:ISSUED_BY]->(Issuer:Changi Logistics Pte Ltd)
  ```

The path is deterministic: instrument_ids are sorted alphabetically; `ROLLS_UP_TO` appears
only when `group_key == "parent_issuer"`.

## 6. Config system & firm switching (Phase 4 ⭐ — constraint 5)

**The engine has zero firm bias.** Both firms are equal config files; neither is "the default in
code." That is the strongest answer to "Firm A baked in cannot reproduce Firm B" — *neither* firm
is in the logic.

### Three-layer resolution
```
base.yaml      figure registry: all 13 figures, structure, limit↔source bindings,
               named "knobs" wherever method CAN differ — knobs left unset
firm_a.yaml    sets knobs to Firm A conventions (the "default reading")
firm_b.yaml    sets knobs to Firm B conventions
                 ↓
effective = deep_merge(base, firm_X)  →  validated by pydantic schema (fail fast)
```

### The 3 knobs that differ (exactly the 3 in `firm_B_brief.md`)
| Knob | Firm A | Firm B |
|---|---|---|
| `non_ig.include_fallen_angels` | `false` | `true` |
| `concentration.gre.group_key` | `issuer` | `parent_issuer` |
| `output.utilization_format` | `percent_1dp` | `truncated_bps` |

Everything else is identical → lives once in `base.yaml`, never duplicated.

### Switch mechanism
CLI `run --firm A` / `run --firm B` picks which firm YAML merges onto base. **The engine never
branches on firm name** — it reads resolved knob *values* only. Proof: `grep -ri "firm_b\|firm b\|==
['\"]B" src/compute/` returns nothing. Constraint 5 as a verifiable property, not a claim.

### Why unset knobs in base (vs base = Firm A)
If base *were* Firm A, a reviewer could say "Firm A is the default, baked in." Leaving knobs unset
in base and requiring each firm file to set them makes both firms symmetric config, and a firm file
that forgets a knob fails pydantic validation loudly instead of silently falling back to Firm A.

### Validation + audit
- pydantic models; unknown keys rejected; primitive references checked against the registry at load.
  A firm config naming a nonexistent selector → load error, never a silent wrong number.
- Loading a config emits a `config_loaded` audit event with **firm id + SHA-256 of the resolved
  effective config**. Switching A→B is visible in the log; the config hash is a reproducibility
  anchor (same hash + same inputs ⇒ same figures).

### Mini-DSL (bonus, deferred)
Knobs are already declarative; a tiny expression grammar for `predicate`
(`asset_class in [hy,sc] or rating < BBB-`) is a clean later add (+2–3). Not now — YAGNI.

## 7. Audit log + reconciliation + firewall (Phase 5)

### Audit log — Postgres, tamper-evident append-only
`audit_event(id serial, ts, run_id, event_type, actor, payload jsonb, config_hash, prev_hash, row_hash, retention_class)`

Immutability demonstrated in code via **three layers:**
1. App connects as a role with **`INSERT` + `SELECT` only** (`REVOKE UPDATE, DELETE` at role level).
2. `BEFORE UPDATE OR DELETE` trigger → `RAISE EXCEPTION` (blocks even a privileged path).
3. **Hash chain:** `row_hash = sha256(payload ‖ prev_hash)` → tamper-evident; any retro-edit breaks
   the chain and a verify routine detects it.

**Event catalogue** (also the Phase 1 table): `graph_construction` · `node_verified` ·
`figure_computed` (value + graph_path + citation + config_hash, per figure) · `reconciliation` ·
`config_loaded` · `report_exported`. Each carries `retention_class` per guidelines §5.1
(7yr txn / 10yr investor / permanent compliance) — modeled, not purged in a 1-week build.

`run_id` groups one execution → two runs = two ids; identical figures ⇒ determinism proof by diff.

### Reconciliation
- Parse `firm_A_answer_key.xlsx` → expected; compare computed vs expected **per figure** (value +
  status) with delta.
- **Tolerance (stated + justified):** we control rounding, so **exact** match on the formatted value
  is expected. Backstop band: ≤0.05% (percentages), ≤0.01 yrs (duration), ≤SGD 1 (DV01) — justified
  because the answer key is hand-derived at display scale. Report exact deltas regardless.
- **Firm B answer key gap + fix:** Firm B's key is not provided as xlsx — only the 3-row table in
  `firm_B_brief.md`. Generate `config/firm_b_expected.yaml`, **transcribed verbatim from the brief**
  (3 changed figures + Firm A values for the rest), header comment stating the transcription. The
  brief explicitly allows small mock docs "if you say why" — this is that, documented.

### Traceability check
For every figure, assert `graph_path` resolves *and* `citation` points to a real `SourceChunk` node.
Any `ERROR`/missing-citation figure → traceability FAIL, listed. Mechanically verifies constraint 2.

### Firewall check (constraint 3, verified not asserted)
- Extract all numeric tokens from the narrative (regex: integers, decimals, %, SGD).
- Computed set = every value + limit across figures, normalized to numeric value (`15.0%`≡`15%`).
- Assert **every narrative number ∈ computed set**. Any extra → **FAIL**, the offending number printed.
- Policy stated: numeric tokens only; LLM prompted to use figures verbatim; spelled-out numbers
  flagged, not silently passed.
- **False-positive scoping (documented):** the regex would catch years ("2024") and section refs
  ("§4.2"). Narrative is constrained to reference figures; a **documented allowlist** normalizes
  known non-figure tokens (dates, section refs) out — not a silent escape hatch.

### Phase 5 output
A script emitting a **table and JSON**: per-figure pass/fail + delta, traceability result, firewall
result. Plus `verify-determinism` (run twice, diff figures.json → identical).

## 8. Project layout, compose, CLI, build order

### Layout
```
interopera/
  docker-compose.yml      neo4j + postgres + app
  Dockerfile  requirements.txt  README.md  .env.example
  config/                 base.yaml  firm_a.yaml  firm_b.yaml  firm_b_expected.yaml
  sample_docs/            provided files (included, per brief)
  src/
    ingestion/ graph/ compute/ audit/ reconcile/
    report/ narrative/ firewall/ cli/ viewer(optional)/
  docs/
    01_flow_and_audit_events.md   02_architecture.md(+png)   03_rfc.md
  tests/
  out/                    figures_firmA.json, report_firmA.xlsx, …
```

### docker-compose — 3 services
- `neo4j`: official image, **healthcheck** (cypher-shell), volume.
- `postgres`: official, healthcheck (`pg_isready`), **`init.sql`** creates `audit_event` + trigger +
  `app_role` with `REVOKE UPDATE,DELETE`, volume.
- `app`: `depends_on: [neo4j, postgres]` **condition: service_healthy** (kills the startup race),
  env for connections + optional `ANTHROPIC_API_KEY`.

**Single command:** `docker compose up` → ingest → build graph → auto-verify clean nodes → compute
**both** firms → write reports + figures → run reconcile + firewall → print summary → exit 0.
Individual ops via `docker compose run app <cmd>`.

**Gate vs single-command tension (resolved):** clean sample auto-passes the 0.85 threshold so the
default run completes end-to-end (keeps "does it run" green). To prove the gate has teeth, include
**one deliberately low-confidence node** + show `verify-graph --approve` in the README, and a
`--strict` mode where the gate blocks. Documented both ways.

### CLI surface
`ingest` · `build-graph` · `verify-graph [--approve]` · `run --firm A|B` · `reconcile --firm A|B` ·
`evaluate --firm A|B` (Phase 5: reconcile+trace+firewall) · `verify-determinism` · `narrate` · `viewer`.

### CLI conventions (decided)
**Non-interactive and scriptable — interactive is an anti-goal.** The evaluator runs headless
(`docker compose up`) and runs scripted checks (run-twice-diff, trace a figure, switch firm). Prompts
or wizards would break non-TTY automation and reproducibility, which an audit tool must never do.

- **Library:** Typer (click-based) — typed subcommands, auto `--help`, tiny dep. `rich` optional for
  the reconciliation table, with a plain fallback in non-TTY so compose logs stay clean.
- **`--json` on every reporting command** — machine-parseable output alongside the human table.
- **Exit codes:** non-zero when reconcile or firewall fails → the evaluator can gate in CI.
- **Verify gate stays flag-based**, never a prompt: `verify-graph --approve <id>` / `--approve-all`.
  Reason: approval must be automatable and reproducible; an interactive "approve? y/n" would make a
  run non-deterministic and un-scriptable.
- **Polish ROI goes to the `evaluate`/`reconcile` table** (the surface the evaluator reads): clean
  per-figure `PASS/FAIL` + delta column. Everything else stays boring and legible.
- **Determinism boundary:** the determinism diff runs on `figures.json`, not stdout, so pretty
  terminal output is fine — artifacts (`figures.json`, `report.xlsx`) stay byte-stable and are never
  diffed against terminal output.

### Build order (TDD, one reviewable unit at a time)
| # | Step | Phase / constraint |
|---|---|---|
| 0 | Scaffold + compose + green skeleton | runs (#3) |
| 1 | **Docs first**: flow+audit catalogue, architecture, RFC | Phase 1 — guides the build |
| 2 | Ingestion + graph model + provenance | Phase 2 |
| 3 | Verify gate (teeth) | Phase 1 gate / Phase 2 |
| 4 | Compute primitives + registry + **Firm A figures → reconcile exact** | Phase 3 ⭐ (#1,#2,#4) |
| 5 | Config layering + **Firm B knobs → reconcile** | Phase 4 ⭐ (#5) |
| 6 | Audit log append-only + hash chain | append-only req |
| 7 | Phase 5 eval: reconcile + traceability + firewall + determinism | Phase 5 (#1,#2,#3) |
| 8 | Narrative + live firewall | #3 |
| 9 | README + polish | runs |
| 10 | Bonus viewer (if time) | +bonus |

**Why docs at step 1, not last:** Phase 1 is 20 pts and the brief calls the constraints "the spine."
Writing the RFC first forces the architecture honest before code.

### Testing (80% target, pragmatic for 1 week)
Unit (primitives, formatters, comparators, config-merge, hash-chain), integration (full pipeline both
firms reconcile exact), determinism (double-run diff), firewall (inject a bad number → FAIL). Coverage
weighted to compute + reconcile + firewall — the graded core.

## 9. Security / production notes (per brief: note, don't build)
- Secrets via env (`.env`, not committed); production would use a secret manager (Vault/SSM).
- No auth on the optional viewer in scope; production would add authn + RBAC + TLS.
- Neo4j/Postgres credentials default-dev in compose; production rotates + scopes them.

## 10. Failure modes covered (per brief: happy path + 1–2)
1. **Unresolvable extracted entity** → `PENDING_REVIEW`, blocked from reports until verified.
2. **Untraceable figure** (no path to `SourceChunk`) → returned as `status: ERROR`, not emitted.

## 11. Resolved decisions (formerly open items)
- **`chunk_id` scheme: content hash** (`sha256` of passage text, truncated) — stable across runs, so
  citations and the determinism diff stay byte-identical regardless of extraction order.
- **Optional viewer: deferred.** Built only after Phases 3–5 land, as the bonus. Not in the core plan.
- **PDF extraction: LLM-assisted proposal + human gate** (confirmed). The LLM *proposes* candidate
  rule nodes/edges from the guidelines text; deterministic structural validation + the human verify
  gate decide what the engine trusts (§3.1 gate 5, §4 gate). The LLM never sets a figure or approves a
  node. Prompt + confidence scoring locked in build step 2.
