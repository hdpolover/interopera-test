# Implementation Progress Tracker

Live status of the build. One row per plan task ([implementation plan](superpowers/plans/2026-06-19-interopera-implementation.md)).
Updated as each task lands. Step-level checkboxes live in the plan; this is the task-level rollup.

**Legend:** ⬜ not started · 🟡 in progress · ✅ done · ⚠️ blocked

| # | Task | Phase | Status | Commit | Tests / reconcile result | Notes |
|---|------|-------|--------|--------|--------------------------|-------|
| 0 | Repo scaffold + docker-compose + Postgres init.sql | infra | ✅ | 0d257e8 | 7/7 | reviewer Approved; out/ fix; APOC verify at boot |
| 1 | Phase 1 docs (flow + audit catalogue, architecture, RFC) | 1 | ✅ | a442480 | 6/6 | Approved; fixed status vocab, citation dict, graph_path string, 3-knob overlay, Firm B figures |
| 2 | Holdings parser (CSV → PositionRecord) | 2 | ✅ | bc2959e | 10/10 | Approved; real value+Decimal+sort+NAV asserts; 4 Minor (dead import etc.) |
| 3 | Guidelines parser (PDF → RuleChunk) | 2 | ✅ | 04a299d | 11/11 | Approved+fix; content-hash id pinned, 6 distinct chunks, keyless stub |
| 4 | Graph schema + builder | 2 | ✅ | 24d6ec7 | 14/14 | Approved+fix; provenance on nodes+edges tested, slug/CONTRIBUTES_TO/distinct-chunk asserted, status on all nodes |
| 5 | Graph queries (selectors) | 2/3 | ✅ | 4bad2f8 | 15/15 (+1 skip) | Approved; fallen-angel={COR-05} proven (BBB- excl/BB+ incl); 2 obligations → Task 10 |
| 6 | Compute primitives | 3 | ✅ | 78d04a4 | 23/23 | Approved; Decimal-only, exact formatters, real AST import-gate; 4 Minor → final triage |
| 7 | Figure dataclass + registry | 3 | ✅ | c79ec1b | 8/8 | Verified by controller; exact field order + all 13 utilization_basis correct |
| 8 | Config loader + pydantic validation | 3/4 | ✅ | 28a2011 | 7/7 | Needs-fixes→Approved; extra=forbid added, fail-fast 3-knob, deterministic hash, both firms load |
| 9 | Compute engine — Firm A figures | 3 ⭐ | ✅ | e8ecfe4 | 19/19 | Approved+fix; 13 figures exact, non-IG path exact, citations PROVEN populated+distinct, DI gate; I-2→Task10 |
| 10 | Verify gate | 1/2 | ✅ | 8379f09 | 42/42 | Approved; gate ERROR on pending, approve→VERIFIED end-to-end, missing-citation→ERROR (I-2 closed); I-A test-fragility → final triage |
| 11 | Config engine — Firm B figures | 4 ⭐ | ✅ | 0aaa517 | 14/14 (+19 A) | Approved+fix; all 13 Firm B figures (21%/13%/bps) by config only, no firm branch (grep-proven); engine bug fix (fallen-angel over-select) firm-agnostic |
| 12 | LLM containment gates (6 tests) | 3 | ✅ | 03781f8 | 6/6 | Approved; all gates genuinely effective (AST scans, live sig inspect, behavioral); created stubs writer/checker/reconciler → 14/15/16 replace |
| 13 | Audit log (append-only + hash chain) | audit | ✅ | 15fc398 | 9/9 | Approved+fix; UPDATE/DELETE blocked by trigger, hash now covers event_type/actor/config_hash/payload (actor-tamper detected), 5 event types |
| 14 | Reconciler (Firm A exact + Firm B config-only) | 3/4/5 | ✅ | 064e6fb | 12/12 | Approved+fix; 3-field compare, parses all 13 real xlsx rows, immutable result, Gate 6 clean; I-1 e2e reconcile → Task 18 |
| 15 | Firewall checker | 5 | ✅ | fcffe9f | 22/22 | Approved; doesn't fail open — narrow allowlist, symmetric non-lossy normalization, covers value+util+limit, real FAIL path, no LLM import |
| 16 | Report writer (xlsx) | 3 | ✅ | 7d31251 | 15/15 | Approved+fix; 13 template rows, Source=graph_path+citation, figures-only (Gate 3), cell-placement verified, deterministic |
| 17 | Narrative writer (LLM-optional) | 3 | ✅ | e895345 | 23/23 | Approved+fix; keyless stub passes firewall, blank-key fallback, anthropic guarded, deterministic, no fabricated numbers |
| 18 | Phase 5 evaluate command | 5 | ✅ | 36689ea | 20/20 | Approved+fix; ⭐ GENUINE e2e: Firm A 13/13 + Firm B 13/13 reconcile vs real answer keys (dual count guards), traceability + firewall pass both firms |
| 19 | CLI wiring tests | infra | ✅ | cfd9718 | 29/29 | Approved+fix; 8 subcommands, non-interactive, --json, exit 0/1 tested (incl failure path), deps pinned (typer 0.25.1/rich 15.0.0), image rebuilt |
| 20 | Determinism double-run test | 1 | ✅ | 4989e3d | 6/6 | Verified by controller; two independent run_all(), byte-identical figures.json incl citation, both firms, no timestamp leak (constraint 1 proven) |
| 21 | Full pipeline integration test | all | ✅ | 566d1ff | 16/16 | Approved+fix; both firms full pipeline (ingest→graph→compute→reconcile 13/13→report→audit chain→firewall), firms provably differ, real modules no shortcuts |
| 22 | README + polish | runs | ✅ | 2526a0b | 4/4 | README (start `docker compose up --build`, both firms, CLI table, constraint→test map), .env.example, obsolete compose version key removed |
| B | Bonus: replay viewer (FastAPI) | bonus | ⬜ | — | — | only if Phases 3–5 land with time |

## Constraint coverage (re-checked at each ⭐ task)
- **C1 Reproducible** — Task 20
- **C2 Traceable through graph** — Tasks 9, 14, 18
- **C3 No LLM numbers** — Tasks 12, 15
- **C4 Reconcile Firm A** — Tasks 9, 14
- **C5 Firm B config-only** — Tasks 11, 14

## Status: ✅ COMPLETE — all 22 tasks done, merge-ready

**Final whole-branch review (opus): READY-WITH-FIXES → all fixes applied.**
- Concentration `graph_path` made real (winning issuer/parent from actual traversal); firewall/audit hardening; spec §5 consistency.
- CLI test-isolation flakiness found + fixed → suite is order-independent.

**Final test suite: 274 passed, 0 failed, 0 skipped** — verified in both definition order and random order (Neo4j + Postgres live, in-container).

**All 5 constraints verified end-to-end:**
- **C1 Reproducible** — `test_determinism.py` double-run byte-identical (both firms)
- **C2 Traceable through graph** — graph_path from real Cypher traversal + `DERIVED_FROM` citation; missing-citation→ERROR
- **C3 No LLM numbers** — 6 containment gates + output firewall (symmetric, non-failing-open)
- **C4 Reconcile Firm A** — `test_evaluate.py` real engine→answer-key, 13/13
- **C5 Firm B config-only** — 13/13 by config, grep-proven no firm branch
- **Append-only audit** — REVOKE + trigger + tamper-evident hash chain

## Run log
_(append one line per task completion: date · task · commit · result)_
- 2026-06-19 · Tasks 0–22 all complete + reviewed · final suite 274/274 green · merge-ready
