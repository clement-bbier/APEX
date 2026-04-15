## Phase 4.7 — Fusion Engine (IC-weighted baseline)

Closes #131. Implements the IC-weighted fusion contract from
ADR-0005 D7 and PHASE_4_SPEC §3.7.

### What this PR delivers

A library-level fusion module that combines the activated Phase 3
signals into a scalar `fusion_score` per `(symbol, timestamp)` via
an IC-IR-weighted linear combination:

```
fusion_score(symbol, t) = Σ_i  (w_i · signal_i(symbol, t))
    where  w_i = |IC_IR_i| / Σ_j |IC_IR_j|
```

Weights are **frozen at construction time** from a reference IC
measurement window. They are NOT re-calibrated per `compute` call —
that would introduce lookahead. The construction-time contract is
enforced by `ICWeightedFusionConfig.__post_init__`: weights live on
the simplex (non-negative, sum to 1.0 within `1e-9`).

This PR is strictly **additive**: it ships library code + unit
tests + diagnostic report. `services/s04_fusion_engine/` is
untouched; the streaming wiring is Phase 5 work (issue #123),
enforced at PR time by a `git diff --name-only main...HEAD` scope-
guard test.

| Concern | Guarantee |
| --- | --- |
| Weights on the simplex | `all(w ≥ 0)`, `|sum(w) - 1.0| < 1e-9`, non-empty, unique feature names |
| Deterministic ordering | `feature_names = tuple(sorted(activated))` — independent of `ICReport` insertion order |
| Silent-drop extras | `ICResult` entries not in `activated_features` are dropped (Phase 3.12 already rejected them) |
| Hard-error artefacts out of sync | `activated_feature` missing from `ic_report` → `ValueError`; duplicate `feature_name` in `ic_report` → `ValueError` |
| No silent uniform fallback | `Σ|IC_IR_i| = 0` on the kept set → `ValueError` |
| Anti-leakage | Weights frozen — property test permutes future rows; past `fusion_score` must not move |
| Output schema | `[timestamp, symbol, fusion_score]` Float64 in that exact order |
| Null / NaN handling | Explicit `ValueError` naming the offending column; no silent zero-fill |
| Empty input | `ValueError` — refuses silent empty output |

### New modules

- `features/fusion/__init__.py` — public re-exports
  (`ICWeightedFusion`, `ICWeightedFusionConfig`).
- `features/fusion/ic_weighted.py` —
  - `ICWeightedFusionConfig` (`@dataclass(frozen=True)`):
    `feature_names: tuple[str, ...]` + `weights: tuple[float, ...]`.
    `__post_init__` validates simplex contract + duplicate names +
    finite floats.
  - `ICWeightedFusionConfig.from_ic_report(ic_report,
    activation_config)` — computes `w_i` over the intersection of
    Phase 3.3 `ICReport.results` and Phase 3.12
    `FeatureActivationConfig.activated_features`; re-normalises
    after float summation so `Σw` is bit-close to 1.0.
  - `ICWeightedFusion(config).compute(signals: pl.DataFrame)` —
    stateless per-call. Validates required columns, rejects
    null/NaN/empty, emits `[timestamp, symbol, fusion_score]`
    Float64 via a single `pl.sum_horizontal(weighted_terms)` polars
    expression. No Python row loops.

### New tests

`tests/unit/features/fusion/test_ic_weighted.py` — ~30 unit tests
covering every bullet of PHASE_4_SPEC §3.7's test list plus the DoD
Sharpe assertion, an anti-leakage property test, and a scope-guard
test. Organised into 10 sections:

1. **Simplex contract** — weights sum to 1.0; weights are
   proportional to `|IC_IR|`; negative `IC_IR` contributes via its
   magnitude.
2. **Linear-combination sanity** — single feature equals that
   feature; equal `IC_IR` → equal weights; arbitrary weights
   produce the expected linear combination.
3. **Mismatch handling** — extras in report dropped; missing
   activated feature raises; duplicate in report raises; all-zero
   `IC_IR` raises; empty activation raises.
4. **Determinism** — feature names sorted alphabetically regardless
   of `ICReport` insertion order; two `compute` calls on the same
   frame produce byte-identical output.
5. **Compute input validation** — missing column / missing
   `timestamp` / null / NaN / empty frame all raise `ValueError`
   with messages naming the offending column.
6. **Output contract** — `timestamp` preserved; `symbol` preserved;
   schema is `["timestamp", "symbol", "fusion_score"]` Float64;
   extra input columns tolerated.
7. **Direct-construction invariants** — negative weight /
   non-summing weights / length mismatch / empty names / duplicate
   names / non-finite weight all raise `ValueError`.
8. **Anti-leakage property** — perturbing future rows after
   construction must not change any already-computed past
   `fusion_score`. Regression guard for the "weights frozen at
   construction" rule (ADR-0005 D7).
9. **DoD Sharpe assertion** — on the textbook Grinold-Kahn §4
   scenario (3 noisy observations of the same latent alpha, σ =
   (0.4, 0.8, 1.2), `n=4000`, 10-seed panel), fusion must dominate
   the best individual signal **in expectation**: mean Sharpe
   uplift > `1e-3` across the panel AND fusion must win on ≥ 60%
   of panel seeds. Both checks together — because the ADR-0005 D7
   weighting `w_i ∝ |IC_IR_i|` is not Markowitz-optimal on
   heteroscedastic noise, strict per-seed dominance is not what
   the ADR actually claims; it holds under LLN / in expectation.
10. **Scope guard** — asserts `services/s04_fusion_engine/` is
    untouched by the 4.7 branch via `git diff --name-only
    main...HEAD`. Skipped when run outside a git checkout or when
    `main` is not resolvable (shallow sandbox clones).

### Supporting artefacts

- `reports/phase_4_7/audit.md` — pre-implementation design contract
  (13 sections: objective, deliverables, reuse inventory, public
  API contract, construction semantics, compute semantics,
  anti-leakage contract, test plan, synthetic scenario for DoD
  Sharpe, report contract, fail-loud inventory, out-of-scope,
  references). Mirrors the style of `reports/phase_4_6/audit.md`.
- `scripts/generate_phase_4_7_report.py` — env-var-driven
  diagnostic generator following the 4.3/4.4/4.5/4.6 contract
  (`APEX_SEED`, `APEX_REPORT_NOW`, `APEX_REPORT_WALLCLOCK_MODE`).
  Builds the synthetic scenario, measures per-signal IC/IC_IR,
  materialises an `ICReport`, builds the frozen config via
  `from_ic_report`, runs `compute`, and emits
  `reports/phase_4_7/fusion_diagnostics.{md,json}` with:
  - frozen weights vector (name → weight),
  - score distribution percentiles (P05/P25/P50/P75/P95),
  - per-signal Pearson correlations vs `fusion_score`,
  - Sharpe comparison table (fusion vs each individual signal,
    annualiser-agnostic centred-mean/std),
  - `fusion_beats_best_individual` boolean — the diagnostic mirror
    of the DoD Sharpe assertion.

### Fail-loud inventory

| Condition | Exception |
| --- | --- |
| `ic_report` missing an activated feature | `ValueError` |
| `ic_report` has duplicate entry for an activated feature | `ValueError` |
| `Σ|IC_IR|` = 0 over the kept set | `ValueError` |
| Direct `ICWeightedFusionConfig` with negative / non-finite weight | `ValueError` |
| Direct construction with `Σw ≠ 1.0` (tol 1e-9) | `ValueError` |
| `len(feature_names) != len(weights)` | `ValueError` |
| Duplicate or empty feature name | `ValueError` |
| `compute(signals)` missing required column | `ValueError` |
| `compute(signals)` has null or NaN in required column | `ValueError` |
| `compute(signals)` with 0 rows | `ValueError` |

### Out of scope (deferred)

- Regime-conditional weights.
- Rolling re-calibration.
- Hierarchical Risk Parity (HRP).
- Shrinkage / robust IC_IR estimators.
- Wiring into `services/s04_fusion_engine/_compute_fusion_score()`
  (Phase 5, issue #123).
- Streaming single-row `compute` API (Phase 5, issue #123).

### How to verify locally

```bash
make lint
pytest tests/unit/features/fusion/ -q

# End-to-end diagnostic (needs the module installed):
APEX_SEED=42 \
  APEX_REPORT_NOW=2026-04-15T00:00:00+00:00 \
  APEX_REPORT_WALLCLOCK_MODE=omit \
  python3 scripts/generate_phase_4_7_report.py
```

### References

- ADR-0005 (Meta-Labeling and Fusion Methodology), D7 — Fusion
  Engine IC-weighted baseline.
- PHASE_4_SPEC §3.7 — Fusion Engine.
- Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio
  Management* (2nd ed.), McGraw-Hill, §4 — IC-IR framework.
