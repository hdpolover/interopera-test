# RFC: LLM Boundary and Containment

**Status:** ACCEPTED
**Authors:** Platform Engineering
**Date:** 2026-06-19
**Replaces:** N/A

---

## Abstract

This RFC defines the boundary between deterministic computation and LLM-generated prose in the compliance reporting system. It establishes six structural gates that enforce LLM Containment — the guarantee that an LLM cannot write a number into a regulatory report — and explains the design decisions that follow from five core constraints.

---

## 1. Problem Statement

### The Tension

Compliance reports must be **auditable and reproducible**: given the same holdings and guidelines, the system must produce bit-for-bit identical figure values every time. Regulators and auditors must be able to trace every reported number back through the computation graph to a source document.

LLMs are **non-deterministic**: the same prompt may produce slightly different outputs across runs, temperatures, or model versions. An LLM that is allowed to write a number into a report cell introduces irreproducibility by design.

Yet LLM narrative has genuine value: a well-written prose summary of a compliance run is faster to review than a raw table of figures, and it can synthesise the key findings for a non-technical reader.

### The Resolution

The system resolves this tension by **structural separation**: the LLM path and the number path never share a write channel. The LLM may read computed figures (as context for narrative generation), but it has no write path back into the report cells or the compute layer. This is enforced not by convention but by module boundaries, dependency injection contracts, and static analysis tests.

---

## 2. The Five Constraints

These constraints were established by the compliance and engineering teams jointly and are non-negotiable. All architectural decisions below are derived from them.

**C1 — Reproducibility:** Given the same input files (holdings CSV, guidelines PDF) and the same firm configuration, the system must produce identical figure values on every run. No randomness, no LLM involvement in figure computation.

**C2 — Traceability:** Every figure must carry a `graph_path` (Cypher-style string built from the actual traversal) and a `citation` (dict: `{ "source_doc": str, "page": int, "chunk_id": str, "passage_summary": str }`). A regulator must be able to follow a figure from the xlsx cell, through the graph path, back to the exact sentence in the guidelines PDF.

**C3 — No LLM Numbers:** The LLM writes narrative prose only. It must not compute, estimate, or propose any figure value that ends up in a report cell.

**C4 — Reconcile Firm A:** The system must produce figures that exactly match Firm A's answer key (within configurable tolerance, default: exact match). This is verified by the automated reconciler at the end of every run.

**C5 — Firm B Config-Only:** To onboard a second firm (Firm B), no code changes should be required. Only a new YAML config file (`firm_b.yaml`) and a new answer key file should be needed.

---

## 3. Architecture Derived from Constraints

**From C1** → The compute engine (`engine.py`) uses `Decimal` arithmetic, topological graph traversal, and registered pure-function primitives. No floating-point arithmetic. No stochastic elements.

**From C2** → Every `Figure` object carries `graph_path: str` (Cypher-style string built from the actual traversal, e.g. `(AssetClass:high_yield)-[:CONTRIBUTES_TO]->(Aggregate:non_ig)<-[:CONTRIBUTES_TO]-(AssetClass:structured_credit)`) and `citation: dict` (`{ "source_doc": str, "page": int, "chunk_id": str, "passage_summary": str }`). These are populated by the engine during traversal. The `DERIVED_FROM` provenance edge in Neo4j is the machine-readable link from rule nodes to source chunks.

**From C3** → The LLM is excluded from `src/compute/` by static import gate. `ComputeEngine.__init__` accepts no LLM client. `report_writer.py` accepts only `list[Figure]`. See Section 4 (LLM Containment) for the full gate list.

**From C4** → `reconciler.py` loads the answer key and compares figures. The reconciliation result is written to the audit log as a `reconciliation` event. Runs that fail reconciliation are flagged and do not overwrite the previous accepted output.

**From C5** → The only firm-specific parameters are the three house-convention knobs (`include_fallen_angels`, `group_key`, `utilization_format`), declared in a per-firm YAML overlay. Figure definitions live in `registry.py` and limit values on graph `Threshold` nodes — neither is firm-specific. `config_loader.py` resolves a `FirmConfig` from the overlay. Switching firms requires only `--firm B` on the CLI.

---

## 4. LLM Containment

**Containment** is the property that the LLM cannot — through any sequence of calls, even if it were to produce adversarial output — cause a number to be written into a report cell or to influence a reconciliation outcome.

Containment is implemented through six structural gates:

### Gate 1: Static Import Gate

`src/compute/` (all Python files under that directory) must not import `anthropic`, `openai`, `httpx`, or `requests`. This is enforced by a pytest test that fails the build if any such import is found. The test runs in CI on every commit.

```python
# tests/test_compute_isolation.py (illustrative)
import ast, pathlib
BANNED = {"anthropic", "openai", "httpx", "requests"}
for path in pathlib.Path("src/compute").rglob("*.py"):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) \
                    else ([node.module] if node.module else [])
            for name in names:
                assert name.split(".")[0] not in BANNED, f"LLM import in {path}: {name}"
```

### Gate 2: Dependency-Injection Gate

`ComputeEngine.__init__` has the signature:

```python
def __init__(self, driver: neo4j.Driver, config: FirmConfig) -> None:
```

It accepts only a Neo4j driver and a `FirmConfig`. There is no LLM client parameter, no `**kwargs` escape hatch, and no global LLM client that the engine could access. Code review and type checking enforce this.

### Gate 3: Report From Figures Only

`report_writer.py` has the signature:

```python
def write_report(figures: list[Figure], output_path: Path) -> None:
```

It accepts only the Figure list and an output path. No narrative string is passed to it, no LLM context, no raw text. The xlsx writer cannot write prose-derived content into report cells because it has no access to prose.

### Gate 4: Output Firewall

Every numeric token in LLM-generated narrative must appear in the set of computed figure values. This is enforced by `src/firewall/checker.py`. The real signature and behaviour (simplified here; see the module for the full implementation):

```python
def check_firewall(narrative: str, figures: list[Figure]) -> FirewallResult:
    # Computed set covers value, utilization, AND limit fields of every figure.
    computed = _build_computed_set(figures)        # symmetric normalization applied
    stripped = _HEX_TOKEN_RE.sub(" ", narrative)   # drop chunk-ID/hex tokens first
    offending = []
    for raw in extract_numeric_tokens(stripped):
        if _is_allowlisted(raw, stripped):         # calendar years, section refs
            continue
        if normalize_token(raw) not in computed:   # currency/comma/unit-normalized
            offending.append(raw)
    return FirewallResult(passed=not offending, offending_numbers=offending, ...)
```

Two details matter for soundness and are easy to get wrong: (a) the computed set is built with the *same* `normalize_token()` applied to the figure fields, so `"SGD 38,790 / bp"` and a narrative `"38,790"` compare equal; and (b) hex/chunk-ID tokens are stripped *before* extraction so an identifier's digit prefix (e.g. `"827726"` from `"827726a0"`) can never be smuggled in as a fabricated number.

The firewall is the only point where the prose path and the number path intersect. The firewall reads numbers from Figures (source of truth). It never writes numbers to Figures. If `firewall_passed = False`, the narrative is rejected and an audit event is logged.

The output firewall (`src/firewall/checker.py`) is the primary mechanism for detecting LLM hallucination of numbers in prose. It is a last-resort safety net; the structural gates above prevent LLM numbers from reaching report cells even before the firewall runs.

### Gate 5: Human-Only Approval

`approve_node` has the signature:

```python
def approve_node(driver: neo4j.Driver, node_id: str, actor: str,
                 node_label: str | None = None) -> None:
```

The `actor` parameter is required and must be a non-empty string identifying the human who approved the node. The function raises `ValueError` if `actor` is empty or whitespace-only. (The optional `node_label` lets a caller disambiguate by label so a same-valued property on a different node type cannot be approved by accident.) The `node_verified` audit event recording the approval is written by the CLI caller, not by `approve_node` itself. There is no code path by which the LLM can call this function — it has no reference to the Neo4j driver, and even if it did, the audit event would record the actor as the LLM identifier, which would be rejected by the compliance review process.

### Gate 6: Pure-Code Phase 5 Checks

`reconciler.py` and `checker.py` contain no LLM imports. All reconciliation and firewall logic is deterministic Python. This is verifiable by inspection and enforced by the same static import gate test applied to `src/reconcile/` and `src/firewall/`.

---

## 5. LLM Boundary Table

| Concern | Permitted | Forbidden |
|---------|-----------|-----------|
| Narrative prose generation | Yes — `narrator.py` calls LLM with Figure list as read-only context | N/A |
| `passage_summary` in `RuleChunk` | Yes — descriptive prose summary of a PDF passage | Must not contain numeric figure values |
| Graph structure proposal | Yes — LLM may propose node/edge structure in a separate design step | Must be human-gated before loading into Neo4j |
| Figure value computation | **FORBIDDEN** | LLM must never compute or estimate a figure value |
| Node status change | **FORBIDDEN** | LLM must never call `approve_node` or change node `status` |
| Report cell population | **FORBIDDEN** | LLM has no write path to xlsx report cells |
| Reconciliation evaluation | **FORBIDDEN** | Pass/fail determination is pure Python only |
| Answer key comparison | **FORBIDDEN** | `reconciler.py` has no LLM import |

---

## 6. Traceability Requirement

Every `Figure` object must satisfy the following traceability invariant:

```
figure.value
    ← computed by engine.py traversing figure.graph_path
    ← graph_path is a Cypher-style string of all nodes/edges traversed, all status=VERIFIED
    ← each Limit/Threshold node has a DERIVED_FROM edge
    ← DERIVED_FROM points to SourceChunk whose chunk_id matches figure.citation["chunk_id"]
    ← SourceChunk.passage is the raw PDF passage that justified the limit
      (SourceChunk.passage_summary + .page give the human-readable citation)
```

A regulator with access to the Neo4j database and the source PDF can reconstruct this chain from the xlsx report cell to the PDF sentence in under five minutes. This chain is also captured in the `figure_computed` audit event (`graph_path` and `citation` are stored in the event payload).

---

## 7. Config System and Firm B

The 13 figure definitions (selector, aggregator, comparator, formatter, `limit_ref`) live in code, in `src/compute/registry.py:FIGURE_REGISTRY`. The **limit values** themselves are not in config at all — they are parsed from the guidelines PDF into graph `Threshold` nodes and read at compute time via `(Limit {ref})-[:HAS_THRESHOLD]->(Threshold)`. Config therefore carries only the three house-convention knobs; firm-specific files set those, and `base.yaml` holds nothing else.

```yaml
# config/base.yaml  — shared by all firms; holds no limit values
# (limit values live on graph Threshold nodes, parsed from the PDF — see §6 Traceability)
# firm overlays supply the three knobs below.
```

```yaml
# config/firm_a.yaml  — Firm A overlay (3 knobs only)
firm_id: firm_a

non_ig:
  include_fallen_angels: false

concentration:
  gre:
    group_key: issuer

output:
  utilization_format: percent_1dp
```

```yaml
# config/firm_b.yaml  — Firm B overlay (3 knobs only)
firm_id: firm_b

non_ig:
  include_fallen_angels: true

concentration:
  gre:
    group_key: parent_issuer

output:
  utilization_format: truncated_bps
```

`config_loader.py` resolves the effective config as:

```python
effective = deep_merge(base, firm_overlay)
```

Figure definitions come from `registry.py`; limit values come from graph `Threshold` nodes (parsed from the PDF). `base.yaml` holds no limit values — only the three knobs listed above are touched by firm overlays.

Answer keys live in:
- Firm A: `sample_docs/firm_A_answer_key.xlsx` (XLSX, loaded by `reconciler.py`)
- Firm B: `config/firm_b_expected.yaml` (YAML, loaded by `reconciler.py`)
- Firm C: `config/firm_c_expected.yaml` (YAML, loaded by `reconciler.py`)

To onboard a new firm:

1. Create `config/firm_{x}.yaml` (three knobs only, as shown above).
2. Supply the answer key in XLSX or YAML format.
3. Run: `bin/fundra run --firm X` (or `python -m src.cli.main run --firm X`)

No code changes required. The `config_loader.py` hashes the resolved effective config. The hash is stored in every audit event (`config_hash`) so the exact config version used for a run is permanently recorded.

**Constraint C5 is satisfied** when Firm B produces a correct reconciliation result using only its YAML overlay and data files.

### Firm B: Expected Figure Changes

With the three knobs set as above, exactly three figures change between Firm A and Firm B. All figure *values* remain in percent/years/SGD units in both firms; only the *utilization* column formatting changes for Firm B.

Firm A renders utilization as a 1-decimal percentage (`percent_1dp`); Firm B renders the *same* underlying ratio as truncated basis points (`truncated_bps`). The value/status changes below come from the `include_fallen_angels` and `group_key` knobs; the format change comes from the `utilization_format` knob.

| Figure | Firm A | Firm B |
|--------|--------|--------|
| Aggregate non-IG exposure | 15.0% → **OK**; utilization **75.0%** | 21.0% → **BREACH** (fallen angels now included); utilization **10500 bps** |
| Largest GRE issuer (concentration) | 7.0% → **OK**; issuer-level grouping; utilization **58.3%** | 13.0% → **BREACH** (Redhill Holdings = Redhill Power 7M + Redhill Transport 6M, grouped at parent_issuer); utilization **10833 bps** |
| SGS utilization (representative) | 58.3% → **OK**; rendered "58.3%" | **5833 bps** (same 0.5833 ratio, truncated-bps format) |

Note: GRE issuer exposure is **13.0%** under Firm B's `parent_issuer` grouping — not 8.0%. The 8.0% figure applies only at the individual-issuer level (Firm A's `group_key: issuer`).

---

## 8. Determinism Guarantee

The following properties together guarantee that the system is deterministic (same input → identical output):

1. **CSV parsing is deterministic.** `holdings_parser.py` uses the standard `csv` module with a fixed dialect. Row order is preserved. No sampling or random selection.

2. **Graph traversal is topologically ordered.** `engine.py` processes nodes in a stable topological order derived from the graph structure. Two runs on the same graph always traverse in the same order.

3. **Arithmetic uses `Decimal`.** All figure values are computed using `decimal.Decimal` with a fixed precision context (`prec=28`). No floating-point rounding drift.

4. **LLM is excluded from the compute path.** LLM non-determinism cannot affect figure values because the LLM has no write path to the compute or report layers (see Section 4).

5. **Config is hashed.** Any change to the firm YAML config produces a different `config_hash`, which appears in the audit log. Identical `config_hash` values across two runs guarantee identical configuration.

6. **Graph state is deterministic given identical inputs.** Given the same `PositionRecord` and `RuleChunk` lists, `builder.py` produces the same graph structure (same nodes, same edges, same properties) on every run.

---

## 9. graph_path Fidelity

The `graph_path` field on each `Figure` is not a summary or approximation. It is the Cypher-style string built from the actual traversal path (e.g. `(AssetClass:high_yield)-[:CONTRIBUTES_TO]->(Aggregate:non_ig)<-[:CONTRIBUTES_TO]-(AssetClass:structured_credit)`), encoding every node and relationship the engine visited to produce the figure value. Fidelity requirements:

- **Completeness:** every node and relationship visited during the computation of a figure must appear in `graph_path`, in traversal order, encoded as a Cypher-style path string.
- **No phantom nodes:** `graph_path` must reference only nodes that exist in the Neo4j database at the time of the run.
- **Stable across re-runs:** given identical graph state, `graph_path` for a given figure must be identical across runs (follows from determinism guarantee above).
- **Stored in audit log:** the `figure_computed` audit event stores `graph_path` in the event payload. This makes the traversal path tamper-evident (it is covered by the row hash).
- **Used for traceability:** the `graph_path` is the machine-readable bridge between the xlsx figure value and the graph nodes. Any automated traceability tool (e.g., a future regulatory reporting portal) can parse `graph_path` to reconstruct and display the full computation chain.

---

## 10. Rejection Criteria

This RFC would be rejected (and the architecture revisited) if any of the following were true:

- A code path exists by which a string returned from an LLM could be parsed into a number and written to a Figure's `value` field.
- `approve_node` can be called without an `actor` argument or with an empty `actor`.
- `src/compute/engine.py` imports any HTTP client library.
- The reconciler uses LLM output to determine pass/fail.
- Figures cannot be traced to source chunks via `citation` + `DERIVED_FROM` edges.

None of the above are true in the accepted implementation. Each of the six containment gates addresses at least one rejection criterion.
