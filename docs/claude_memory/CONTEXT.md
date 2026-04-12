# APEX Project Context Snapshot

**Last updated**: 2026-04-12
**Updated by**: Session 005

---

## Current State

| Metric | Value |
|---|---|
| Active Phase | Phase 3 — Feature Validation Harness (DESIGN COMPLETE) |
| Previous Phase | Phase 2 — Universal Data Infrastructure (DONE) |
| Total tests | 1,283 (1,228 unit + 55 integration) |
| Production LOC | 31,149 |
| Test LOC | 17,501 |
| mypy strict | 0 errors (319 files) |
| Services scaffolded | 10/10 (S01-S10) |
| S01 fully implemented | Yes (78 files, 9,583 LOC) |
| ADRs accepted | 7 (ZMQ topology, Quant Methodology, Data Schema + 4 Sprint 4/5) |

## Audit Status

| Audit | Status | Findings | Issues |
|---|---|---|---|
| Whole-codebase (#55) | CLEARED | P0: 0, P1: 15, P2: 13, P3: 6 | #64-#77 |
| Meta-governance (#59) | CLEARED | P0: 3, P1: 8, P2: 7, P3: 5 | #78-#86 |

P1 issues (#64-#77) parallelizable with Phase 3.

## Phase 3 Design

Spec document: `docs/phases/PHASE_3_SPEC.md`
- 13 sub-phases (3.1--3.13)
- 6 candidate features: HAR-RV, Rough Vol, OFI, CVD+Kyle, GEX
- Key ABCs: FeatureCalculator, FeatureStore, ICMeasurer, CPCVSplitter
- Estimated 3-4 weeks execution

## Key Architecture Points for Phase 3

- S07 functions are PURE (stateless, no side effects) — safe to call from features/
- S02 signal pipeline: 5 weighted components (microstructure=0.35, bollinger=0.25,
  ema_mtf=0.20, rsi_divergence=0.15, vwap=0.05)
- Feature Store will use TimescaleDB (custom, not Feast)
- All features must produce SignalComponent-compatible output for S02 integration
- IC threshold for feature acceptance: |IC| > 0.02, IC_IR > 0.5
- CPCV mandatory (ADR-0002): C(6,2) = 15 folds, purging + embargo
- DSR + PBO mandatory for multiple testing correction

## Open Issues

- GEX validation requires options data (source TBD, may need paid API)
- Whether all 6 features will pass IC threshold is unknown
- Remaining P1 audit issues: S01 connector Decimal migration (MacroPoint/FundamentalPoint model types)

## Sprint Status

| Sprint | PR | Issues | Status |
|---|---|---|---|
| Sprint 1 — Docs quick wins | #100 | #67, #78, #79, #80 | MERGED |
| Sprint 2 — Security & Config | #101 | #66, #69, #71 | MERGED |
| Sprint 3 — CI hardening | #103 | #64, #65, #68, #70 | MERGED |
| Sprint 4 — Architecture refactors | TBD | #74, #75, #76, #77 | PR PENDING |

## P1 Issue Progress

| Issue | Sprint | Status |
|---|---|---|
| #64 CI coverage | Sprint 3 | CLOSED |
| #65 CI CVE | Sprint 3 | CLOSED |
| #66 SecretStr | Sprint 2 | CLOSED |
| #67 Docs | Sprint 1 | CLOSED |
| #68 CI backtest | Sprint 3 | CLOSED |
| #69 Decimal | Sprint 2 | CLOSED |
| #70 CI linting | Sprint 3 | CLOSED |
| #71 Config | Sprint 2 | CLOSED |
| #74 S03 dead code | Sprint 4 | PR PENDING |
| #75 S04 OCP | Sprint 4 | PR PENDING |
| #76 S05 DIP | Sprint 4 | PR PENDING |
| #77 S01 layering | Sprint 4 | PR PENDING |

11/14 P1 closed (will be 11/14 after Sprint 4 merge → remaining: #72, #73, #63).

## Branch Status

- `main` is clean, all tests passing (Sprint 3 merged)
- `sprint4/architecture-refactors` — PR pending
- Follow-up issue #102 created for backtest-gate continue-on-error removal
