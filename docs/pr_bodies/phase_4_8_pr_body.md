## Phase 4.8 — End-to-end Pipeline Test

Closes #132. Implements the composition-gate integration test
specified in PHASE_4_SPEC §3.8 and documented in
`reports/phase_4_8/audit.md`.

### What this PR delivers

A single, deterministic integration test that chains **every Phase 4
module already on `main`** on a controlled synthetic scenario:

```
4.1 labels → 4.2 weights → 4.3 RF train → 4.4 nested CPCV tuning →
4.5 gates → 4.6 persistence → 4.7 fusion
```

This PR is strictly **additive** and a pure composition gate:

- No new library API. No file under `features/`, `services/`, or
  `core/` is touched by this branch.
- Individual-module correctness stays the domain of the unit suites
  shipped in PRs #138 – #145.
- Any composition gap between those modules surfaces here.

| Concern | Guarantee |
| --- | --- |
| Deterministic | `APEX_SEED=42` produces bit-equal gate values, `fusion_score` arrays, and Sharpe trio across runs. |
| Self-contained | No Redis, no docker, no broker — pure in-process numpy/polars/sklearn. |
| No library mutation | Scope guard — `git diff --name-only main...HEAD` confined to `tests/integration/`, `scripts/generate_phase_4_8_report.py`, `reports/phase_4_8/**`, `docs/**`. |
| No-write scope guard | Runtime snapshot of `REPO_ROOT` before/after the test; any new file outside `reports/phase_4_*/`, `models/meta_labeler/`, `tests/integration/`, or `tmp_path` fails the test. |
| Fail-loud | See §14 of the audit — 8 enumerated failure conditions, each with a dedicated assertion message. |
| CI budget | Reduced 2×2×2 = 8-trial tuning grid; local dry-run ≈ 90 s on the `integration-tests` job (spec target ≤ 5 min). |

### New test assets

- `tests/integration/fixtures/__init__.py` — package marker for the
  new fixture directory.
- `tests/integration/fixtures/phase_4_synthetic.py` — deterministic
  scenario generator shared by the integration test and the
  diagnostic script. Public API:
  - `Scenario` frozen dataclass (bars, labels, events, weights,
    feature matrix, per-symbol bar frames, per-event signal snapshot).
  - `build_scenario(seed=42, *, bars_per_symbol=500, n_symbols=4) ->
    Scenario`.
  - `build_outer_cpcv()` — `CombinatoriallyPurgedKFold(n_splits=6,
    n_test_splits=2, embargo=0.02)` per ADR-0005 D4.
  - `build_inner_cpcv()` — `(4, 1, 0.0)`.
  - `REDUCED_TUNING_SEARCH_SPACE` — the 2×2×2 grid documented in
    §6 of the audit.
  - `SCENARIO_SYMBOLS`, `SCENARIO_SIGNAL_NAMES`,
    `SCENARIO_ALPHA_COEFFS = (0.5, 0.3, 0.2)`, `SCENARIO_KAPPA =
    0.002`, `SCENARIO_NOISE_SIGMA = 0.001`, `DEFAULT_SEED = 42`.
  - Fails loudly on `n_symbols != 4` and `bars_per_symbol < 100`.
- `tests/integration/test_phase_4_pipeline.py` —
  `pytestmark = pytest.mark.integration`; the single top-level
  `test_phase_4_pipeline_end_to_end` + 4 fixture micro-tests.

### New tests

#### Top-level composition gate (1)

`test_phase_4_pipeline_end_to_end(git_repo)` wires every Phase 4
module through the shared scenario and asserts PHASE_4_SPEC §3.8's
DoD point-by-point:

1. `BaselineMetaLabeler` trains on the pooled 4-symbol, ~376-event
   dataset under `outer_cpcv`.
2. `NestedCPCVTuner(search_space=REDUCED_TUNING_SEARCH_SPACE)` runs
   the 8-trial reduced grid (pool-level). Fold-0 hyperparameters
   are reused to refit the RF on each outer-fold training set for
   pooled bet-sized P&L.
3. A single-symbol `AAPL` slice is re-trained + re-tuned and passed
   to `MetaLabelerValidator` together with
   `bars_for_pnl = scenario.bars_for_symbol("AAPL")` — the validator
   requires a strictly monotonic, unique bar index per
   `pnl_simulation._validate_inputs`. **`report.all_passed is True`
   on `seed=42` deterministically.**
4. A three-signal `ICReport` is materialised from the scenario
   (Spearman IC + 20-chunk bootstrap IC-IR). Fused score via
   `ICWeightedFusion(ICWeightedFusionConfig.from_ic_report(...))`
   is joined onto `(t0, symbol)`.
5. Three P&L series are computed on the shared pooled event set:
   - `bet_sized_pnl = bet_i · r_i` (meta-labeler outputs via the
     per-fold RF refit, realistic costs);
   - `fusion_pnl = sign(fusion_score_i) · r_i`;
   - `random_pnl = sign(uniform − 0.5) · r_i` (seed-controlled).
6. Annualiser-agnostic centred Sharpe (`mean / std`) on each series,
   plus per-signal unit-sign Sharpe.
7. **Assertions (audit §8):**
   - `Sharpe(bet_sized) > Sharpe(fusion) > Sharpe(random)` **with
     each gap ≥ 1.0 Sharpe unit**.
   - `Sharpe(fusion) > max_i Sharpe(signal_i)` — the 4.7 fusion
     DoD holds on the integrated scenario.
   - `predict_proba` bit-exact on a 1000-row random fixture after
     `save_model → load_model` round-trip
     (`np.array_equal(..., ...)`, tolerance `0.0`).
   - No-write scope guard — no file written outside the allow-list.

The test uses a throwaway `git_repo` pytest fixture
(`tmp_path/"repo"` + `monkeypatch.chdir` + `git init --initial-
branch=main` + `user.email` + `user.name` + `commit.gpgsign=false`
+ initial `README.md` commit) to satisfy
`persistence.save_model`'s clean-working-tree + `HEAD`-SHA contract
without polluting the host repo.

#### Fixture micro-tests (4)

- `test_scenario_is_deterministic_under_same_seed` — two
  `build_scenario(seed=42)` invocations return byte-identical bars,
  feature matrices, labels, and sample weights.
- `test_scenario_respects_warmup_window` — every event `t0_i` lies
  on or after the Triple-Barrier volatility warmup cutoff
  (`vol_lookback + 10` bars, per symbol).
- `test_scenario_bar_and_label_schemas_match_phase_4_contracts` —
  bars schema is `{timestamp: Datetime('us', 'UTC'), symbol: Utf8,
  close: Float64}`, strictly monotonic per symbol; `close > 0`;
  labels from `label_events_binary` carry `binary_target ∈ {0, 1}`
  and the event frame has `t0 < t1`.
- `test_scenario_alpha_coefficients_are_recoverable_via_ols` — OLS
  of `log_ret / κ` on `[gex, har_rv, ofi]` recovers
  `(0.5, 0.3, 0.2)` within `atol=0.05` on `n=2000`. Regression guard
  for the latent-alpha construction that underpins the 3.0-ish
  Sharpe of the meta-labeler.

### Supporting artefacts

- `reports/phase_4_8/audit.md` — pre-implementation design contract
  (16 sections: objective, deliverables, reuse inventory, synthetic-
  scenario design, feature-matrix column map, tuning-grid reduction
  rationale, fusion + Sharpe trio recipe, §8 assertion list,
  anti-leakage checks, no-write scope guard, determinism contract,
  test inventory, CI integration, fail-loud inventory, out-of-scope,
  references).
- `scripts/generate_phase_4_8_report.py` — env-var-driven
  diagnostic generator mirroring the 4.3 / 4.4 / 4.5 / 4.6 / 4.7
  contract (`APEX_SEED`, `APEX_REPORT_NOW`,
  `APEX_REPORT_WALLCLOCK_MODE`). Runs the full pipeline in-process
  and emits `reports/phase_4_8/pipeline_diagnostics.{md,json}` with:
  - Scenario summary (symbols, bars, events, per-signal IC + IR).
  - Frozen fusion weights (name → weight, sorted).
  - Per-gate verdicts table (G1 – G7: value, threshold, passed) +
    `all_passed` + failing-gate names when not all green.
  - Sharpe trio (`bet_sized`, `fusion`, `random`) + both gaps +
    per-signal Sharpe + `fusion_beats_best_individual` flag.
  - Validator-side DSR, PBO, realistic round-trip bps, Sharpe CI.
  - Tuner `stability_index` + trials-per-outer-fold.
  - Optional `wall_clock_seconds` (opt-in via
    `APEX_REPORT_WALLCLOCK_MODE=record`).
- `docs/claude_memory/CONTEXT.md` + `SESSIONS.md` updates.

### Fail-loud inventory

| Condition | Exception |
| --- | --- |
| Any Phase-4 module import fails | `ImportError` (CI surfaces at collection) |
| `build_scenario(n_symbols != 4)` | `ValueError` |
| `build_scenario(bars_per_symbol < 100)` | `ValueError` |
| `label_events_binary` returns empty for any symbol | `ValueError` |
| `report.all_passed is False` on `seed=42` | assertion fails with failing-gate names |
| Sharpe trio ordering or ≥ 1.0 gap violated | assertion fails with the three values + gaps |
| `Sharpe(fusion) ≤ max_i Sharpe(signal_i)` | assertion fails with the per-signal table |
| `predict_proba` not bit-exact on reload | assertion fails with max `|Δp|` |
| Any new file written outside the allow-list | assertion fails naming the offending path |

### Out of scope (deferred)

- Real data integration (Phase 5).
- Multi-scenario sweeps (Phase 4.X parameter sweeps).
- Regime-conditional fusion weights (already deferred in 4.7).
- Feature-builder path through `MetaLabelerFeatureBuilder` (unit-
  tested in `tests/unit/features/meta_labeler/`).
- Streaming single-row fusion / bet-sizing APIs (Phase 5, issue
  #123).

### How to verify locally

```bash
make lint
pytest tests/integration/test_phase_4_pipeline.py -q

# End-to-end diagnostic (needs the project installed):
APEX_SEED=42 \
  APEX_REPORT_NOW=2026-04-15T00:00:00+00:00 \
  APEX_REPORT_WALLCLOCK_MODE=omit \
  python3 scripts/generate_phase_4_8_report.py
```

### References

- ADR-0005 (Meta-Labeling and Fusion Methodology), D1 – D8.
- PHASE_4_SPEC §3.8 — End-to-end Pipeline Test.
- `tests/integration/test_phase_3_pipeline.py` — structural
  precedent for Phase 3's integration gate.
- Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio
  Management* (2nd ed.), McGraw-Hill, §4.
- López de Prado, M. (2018). *Advances in Financial Machine
  Learning*, Wiley, §3 – §11.
