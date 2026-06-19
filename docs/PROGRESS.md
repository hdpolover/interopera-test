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
| 5 | Graph queries (selectors) | 2/3 | ⬜ | — | — | fallen-angel filter → only COR-05 |
| 6 | Compute primitives | 3 | ⬜ | — | — | Decimal, comparators, formatters |
| 7 | Figure dataclass + registry | 3 | ⬜ | — | — | fields incl. utilization + utilization_basis |
| 8 | Config loader + pydantic validation | 3/4 | ⬜ | — | — | base + firm merge, fail-fast |
| 9 | Compute engine — Firm A figures | 3 ⭐ | ⬜ | — | — | 13 figures reconcile exact; non-IG path == brief |
| 10 | Verify gate | 1/2 | ⬜ | — | — | blocks on PENDING_REVIEW rule node |
| 11 | Config engine — Firm B figures | 4 ⭐ | ⬜ | — | — | 3 knobs, no firm hardcoding (grep-proven) |
| 12 | LLM containment gates (6 tests) | 3 | ⬜ | — | — | static import, DI, report-from-figures, etc. |
| 13 | Audit log (append-only + hash chain) | audit | ⬜ | — | — | REVOKE + trigger + chain verify |
| 14 | Reconciler (Firm A exact + Firm B config-only) | 3/4/5 | ⬜ | — | — | compares value + utilization + status |
| 15 | Firewall checker | 5 | ⬜ | — | — | narrative numbers ⊆ computed; allowlist documented |
| 16 | Report writer (xlsx) | 3 | ⬜ | — | — | populates template from figures.json |
| 17 | Narrative writer (LLM-optional) | 3 | ⬜ | — | — | graceful fallback w/o key |
| 18 | Phase 5 evaluate command | 5 | ⬜ | — | — | reconcile + traceability + firewall, table+JSON |
| 19 | CLI wiring tests | infra | ⬜ | — | — | Typer, non-interactive, exit codes |
| 20 | Determinism double-run test | 1 | ⬜ | — | — | diff figures.json → identical |
| 21 | Full pipeline integration test | all | ⬜ | — | — | both firms end-to-end |
| 22 | README + polish | runs | ⬜ | — | — | single-command start |
| B | Bonus: replay viewer (FastAPI) | bonus | ⬜ | — | — | only if Phases 3–5 land with time |

## Constraint coverage (re-checked at each ⭐ task)
- **C1 Reproducible** — Task 20
- **C2 Traceable through graph** — Tasks 9, 14, 18
- **C3 No LLM numbers** — Tasks 12, 15
- **C4 Reconcile Firm A** — Tasks 9, 14
- **C5 Firm B config-only** — Tasks 11, 14

## Run log
_(append one line per task completion: date · task · commit · result)_
