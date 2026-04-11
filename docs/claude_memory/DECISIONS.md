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
