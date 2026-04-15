## Summary

Phase 4.4 implements the ADR-0005 D4 / `PHASE_4_SPEC.md` §3.4 contract: a nested CPCV grid search for the Meta-Labeler Random Forest. Outer CPCV = caller's splitter (15 folds by default); inner CPCV runs strictly inside each outer training slice. Selection criterion = inner-mean weighted ROC-AUC; OOS AUC on the outer test slice is **observed but never used to pick the winner** — the honest nested-CV premise of López de Prado (2018) §7.4 and the pre-condition for Phase 4.5's PBO (Bailey–Borwein–LdP–Zhu 2014).

## Deliverables

- `reports/phase_4_4/audit.md` — pre-implementation audit (~285 lines): reuse inventory, frozen API contract, explicit algorithm skeleton, 18-test plan, anti-leakage property obligation, budget, seed discipline, risk register.
- `features/meta_labeler/tuning.py` (~470 LOC) — `TuningSearchSpace`, `TuningResult`, `NestedCPCVTuner` with explicit nested loop (rationale: `GridSearchCV` routes `sample_weight` asymmetrically across sklearn versions and doesn't natively support CPCV — see audit §10).
- `tests/unit/features/meta_labeler/test_tuning.py` — **32 unit tests** (spec minimum = 14). Anti-leakage test uses a `RandomForestClassifier.fit` spy to prove no outer-test row ever enters an inner fit — replaces the naive global-permute probe which is unsound under CPCV (every row is test in some folds and train in others).
- `scripts/generate_phase_4_4_report.py` + `reports/phase_4_4/{tuning_report.md, tuning_trials.json}` — fast CI default (192 fits, ~22 s) plus `APEX_FULL_TUNING=1` gate for the spec 1,350-fit run.
- `docs/claude_memory/{CONTEXT.md, SESSIONS.md}` updated.

## Budget & Determinism

- **Default (CI)**: n=400, 8-trial grid × Outer C(4,2)=6 × Inner C(3,1)=3 ⇒ 144 inner fits + 48 outer refits, ~22 s.
- **Full (spec)**: n=1,200, 18-trial grid × Outer C(6,2)=15 × Inner C(4,1)=4 ⇒ 1,080 inner fits + 270 outer refits = **1,350 RF fits**, ~45 min single-core.
- Per-outer-fold seed: `random_state = seed + outer_idx × 7`. Determinism pinned by two tests (identical seeds → bit-identical `all_trials`; different seeds → divergence).
- Reserved RF keys (`random_state`, `class_weight`, `n_jobs`) are tuner-controlled; injection is rejected at construction.

## Report (fast config, APEX_SEED=42)

- Mean best-OOS AUC: `0.7324 ± 0.0229`
- Stability index: `0.333` (narrow grid → expected; full grid evaluated on demand)
- Wall-clock: `22.23 s`

## Quality Gates

- `ruff check` + `ruff format --check`: clean.
- `mypy --strict` on `features/meta_labeler/tuning.py` + `scripts/generate_phase_4_4_report.py`: 0 errors.
- `pytest tests/unit/features/meta_labeler/test_tuning.py`: **32/32 pass**.
- Coverage target ≥ 88% on `tuning.py` (CI will enforce).

## References (canonical, peer-reviewed only)

- `docs/phases/PHASE_4_SPEC.md` §3.4 — Nested Hyperparameter Tuning.
- `docs/adr/ADR-0005-meta-labeling-fusion-methodology.md` D4 — Nested CPCV rationale.
- López de Prado, M. (2018). *Advances in Financial Machine Learning*, §7.4 (purged / nested CV).

## Test plan

- [x] Unit tests green locally (32/32).
- [x] `mypy --strict` clean.
- [x] `ruff` + `ruff format` clean.
- [ ] CI `quality` job.
- [ ] CI `unit-tests` coverage ≥ 85%.
- [ ] CI `backtest-gate` remains ≥ 0.8 Sharpe / ≤ 8% DD (unaffected — 4.4 is additive).

Closes #128.
Refs ADR-0005 D4.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
