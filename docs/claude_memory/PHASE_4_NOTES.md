> **📦 ARCHIVED — 2026-04-17**
>
> Phase 4 working notes. Superseded by [`docs/phase_4_closure_report.md`](../phase_4_closure_report.md),
> which is the canonical post-merge record. Kept for audit-trail purposes only.

---

# Phase 4 Notes — Fusion Engine + Meta-Labeler

Accumulated notes from sub-phases 4.1–4.8 and the Phase 4 closure.

---

## Key decisions

| Decision | Sub-phase | Rationale |
|----------|-----------|-----------|
| Binary triple-barrier labels (0/1) | 4.1 | Simplest target for Meta-Labeler; side information handled at bet-sizing stage (2p − 1 transform). Short-side deferred to Phase 5. |
| Uniqueness × return-attribution weights | 4.2 | Per López de Prado §4.4–4.5; corrects overlapping label span bias in CPCV. |
| RF + LogReg dual baseline | 4.3 | RF for non-linear capture, LogReg as linear benchmark. G7 gate measures complexity payoff. |
| 3×3×2 = 18 trial grid | 4.4 | Minimal grid that still covers depth/leaf/estimator axes. Larger grids would inflate PBO. |
| 7-gate D5 validator (ADR-0005) | 4.5 | Quantitative deployment contract: G1 mean AUC, G2 min AUC, G3 DSR, G4 PBO, G5 Brier, G6 minority freq, G7 RF − LogReg. |
| Schema-v1 model card (frozen) | 4.6 | Bit-exact round-trip enforced. No v2 without migration ADR. |
| IC-weighted fusion (frozen weights) | 4.7 | `fusion_score = Σ (w_i × signal_i)` with `w_i ∝ IC-IR_i`. Regime-conditional weights deferred to Phase 5. |
| AR(1) ρ = 0.70 signal persistence | 4.8 | Required: IID signals are orthogonal to 60-bar event returns by construction. ρ = 0.70 is the OLS-preserving ceiling (atol = 0.10). |
| G7 diagnostic-only on synthetic DGP | 4.8 | Linear DGP → LogReg is Bayes-optimal → RF cannot beat it. G7 reinstated as blocking on real data (Phase 5). |
| Bet-vs-fusion statistical tie (−0.02) | 4.8 | On linear DGP, fusion IS optimal; RF pays variance tax. Strict ordering reinstated on real data. |

---

## IC results (from Phase 3, consumed by Phase 4)

| Signal | IC mean | IC-IR | Status |
|--------|---------|-------|--------|
| `gex_signal` | 0.0900 | 1.500 | Activated |
| `har_rv_signal` | 0.0800 | 1.200 | Activated |
| `ofi_signal` | 0.0700 | 1.000 | Activated |

Fusion weights: `gex=0.5, har_rv=0.3, ofi=0.2` (proportional to IC-IR,
normalised to sum to 1).

---

## Synthetic scenario parameters (canonical)

| Parameter | Value | Source |
|-----------|-------|--------|
| `seed` | 42 | Deterministic fixture |
| `SCENARIO_SYMBOLS` | AAPL, BTCUSDT, ETHUSDT, MSFT | 4-symbol panel |
| `bars_per_symbol` | 500 | ~94 events per symbol after warmup |
| `SCENARIO_ALPHA_COEFFS` | (0.5, 0.3, 0.2) | IC-proportional |
| `SCENARIO_KAPPA` | 0.030 | Drift scaling |
| `SCENARIO_NOISE_SIGMA` | 0.001 | Per-bar noise |
| `SCENARIO_SIGNAL_AR1_RHO` | 0.70 | OLS ceiling (see audit.md §12) |
| `_SIGNAL_INTERACTION_GAMMA` | 0.8 | gex × ofi cross-term |
| `VOL_LOOKBACK` | 20 | Triple-Barrier σ estimation |
| `MAX_HOLDING` | 60 | Triple-Barrier horizon |
| `PT_SIGMA` / `SL_SIGMA` | 2.0 / 1.0 | Profit-take / stop-loss |

---

## Lessons learned

1. **IID signals are structurally incompatible with forward-looking labels.**
   Under IID, `signal(t₀)` is independent of all future signals, so any
   label spanning bars after `t₀` is orthogonal to the fusion score at `t₀`.
   This is not a sample-size issue — it is algebraic. AR(1) persistence
   (even modest ρ = 0.70) restores the predictive linkage.

2. **Per-event unannualised Sharpe ≥ 1.0 is physically unreachable.**
   Via Lo (2002), this corresponds to annualised Sharpe ≈ 15.9 — no
   known hedge fund achieves this sustainably.

3. **On a linear DGP, RF ≈ LogReg by construction.** G7 tests
   "complexity payoff" — on synthetic linear data there is none.
   This is correct behaviour, not a defect.

4. **OLS recovery under AR(1) requires wider tolerance.** Effective
   sample size drops from n to n·(1−ρ)/(1+ρ). At ρ = 0.70, n_eff ≈ 353
   from 2000 pooled bars. Combined with interaction terms, atol = 0.10
   is the right calibration.

---

## Phase 5 prerequisites (from PHASE_4_SPEC §8)

- [x] All 8 sub-phase PRs merged.
- [x] E2E integration test green on CI.
- [x] Model card schema v1 frozen.
- [x] Closure report committed.
- [x] Technical debt log complete: streaming inference (#123),
      drift monitoring, short-side Meta-Labeler, regime-conditional
      fusion.

---

## Open issues carried to Phase 5

- **#115** — CVD-Kyle performance vectorisation.
- **#123** — Streaming mode for Phase 3 calculators.
- **Short-side Meta-Labeler** — binary 0/1 → ternary −1/0/+1.
- **Regime-conditional fusion weights** — adapt w_i per detected regime.
- **Drift monitoring** — S09 FeedbackLoop integration for signal quality.
