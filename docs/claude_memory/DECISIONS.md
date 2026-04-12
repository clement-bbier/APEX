# APEX Architectural Decisions Log

Mini-ADR format for decisions made during Claude Code sessions.
Each entry follows the template in `templates/DECISION_TEMPLATE.md`.

---

## D001 — Custom Feature Store over Feast (2026-04-11)

| Field | Value |
|---|---|
| Date | 2026-04-11 |
| Session | 001 |
| Decision | Build a custom lightweight Feature Store using TimescaleDB + Polars |
| Status | ACCEPTED |

### Context

Phase 3.2 requires a Feature Store for versioned, reproducible feature persistence
with point-in-time queries.

### Alternatives Considered

1. **Feast (Tecton open-source)**: Full-featured but heavy deployment, designed for
   multi-team ML platforms. Overkill for single-operator APEX.
2. **Tecton (paid)**: Enterprise-grade, far too expensive for personal project.
3. **Custom on TimescaleDB + Polars**: Lightweight, uses existing infra (Phase 2),
   supports point-in-time queries natively via SQL.

### Justification

- APEX is single-operator; Feast's collaboration features add no value.
- TimescaleDB already deployed in Phase 2 with hypertable compression.
- Polars is already in the stack for data transformation.
- Custom store estimated at ~200 LOC; Feast deployment estimated at ~2 days of config.

### References

- Sculley et al. (2015). "Hidden Technical Debt in ML Systems". NeurIPS.
- Kleppmann (2017). Designing Data-Intensive Applications, Ch. 11.

---

## D002 — vectorbt PRO Deferred to Phase 5 (2026-04-11)

| Field | Value |
|---|---|
| Date | 2026-04-11 |
| Session | 001 |
| Decision | Do not purchase vectorbt PRO for Phase 3; re-evaluate for Phase 5 |
| Status | ACCEPTED |

### Context

vectorbt PRO ($400/year) provides vectorized backtesting. Phase 3 validates features
via IC measurement, not strategy backtesting.

### Justification

- Phase 3 measures Information Coefficient, not strategy performance.
- IC measurement requires Polars + NumPy + scipy.stats.spearmanr, all free.
- vectorbt's value proposition is backtesting, which is Phase 5's scope.
- $400/year is significant for a personal project; defer until ROI is clearer.

---

## D003 — Coverage Gate Incremental Raise to 75% (2026-04-12)

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Session | 004 |
| Decision | Raise CI coverage gate from 40% to 75% (not directly to 85%) |
| Status | ACCEPTED |

### Context

CLAUDE.md documents an 85% coverage target. The CI gate was at 40% — a significant
drift. After narrowing the overly broad omit list (removing S01 and S10 wildcards),
the true baseline coverage measured at 80% on 6,861 LOC.

### Justification

- Jumping directly to 85% would make CI fragile — any new file without tests would break it
- 75% gives 5% headroom below the 80% baseline, absorbing normal fluctuation
- Incremental progression is safer: 40% → 75% → 80% → 85% over future sprints
- Each bump should coincide with a test-writing sprint, not just gate increases

---

## D004 — Backtest Thresholds Deferred to Phase 5 (2026-04-12)

| Field | Value |
|---|---|
| Date | 2026-04-12 |
| Session | 004 |
| Decision | Keep backtest thresholds at Sharpe 0.5 / DD 12% and continue-on-error: true |
| Status | ACCEPTED |

### Context

CLAUDE.md specifies Sharpe >= 0.8 and DD <= 8%. The CI backtest-gate uses relaxed
thresholds (0.5/12%) and is non-blocking due to a known Sharpe calculation bug in
full_report().

### Justification

- Raising thresholds without fixing the Sharpe bug would create false failures
- Making the gate blocking while full_report() is buggy would break CI
- Follow-up issue #102 created to track the fix
- Thresholds should be raised in Phase 5 after feature validation confirms data quality
