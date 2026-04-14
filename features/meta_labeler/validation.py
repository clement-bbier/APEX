"""Phase 4.5 - Meta-Labeler statistical validation (gates G1-G7).

Wires the seven ADR-0005 D5 deployment gates to the artefacts emitted
by Phase 4.3 (:class:`BaselineTrainingResult`) and Phase 4.4
(:class:`TuningResult`). All statistical heavy lifting is delegated
to the battle-tested ``features/hypothesis/`` calculators (DSR, PBO);
this module is a thin orchestrator that:

1. Re-fits the tuned RF per outer CPCV fold and collects per-label
   OOS predicted probabilities.
2. Runs :func:`~features.meta_labeler.pnl_simulation.simulate_meta_labeler_pnl`
   under the realistic cost scenario (ADR-0002 D7 / ADR-0005 D8) to
   produce the per-label net-return series feeding the G3 DSR gate.
3. Reshapes ``TuningResult.all_trials`` into the IS / OOS dicts
   expected by :class:`~features.hypothesis.pbo.PBOCalculator` for G4.
4. Computes G1, G2 (mean/min OOS AUC) directly from
   :class:`BaselineTrainingResult`.
5. Computes G5 (Brier score) as a sample-weight-aware mean across
   folds.
6. Computes G6 (minority-class frequency) on the training labels.
7. Computes G7 (RF − LogReg mean OOS AUC) from the two per-fold AUC
   tuples in :class:`BaselineTrainingResult`.
8. Emits a :class:`MetaLabelerValidationReport` with per-gate
   pass/fail and the three aggregate scalars required by §3.5.

The validator is **fail-loud**: any missing evidence (no LogReg
baseline, empty trial ledger, fewer than two distinct trial
hyperparameters, length mismatches) raises ``ValueError`` rather than
silently passing the corresponding gate. This is non-negotiable per
ADR-0005 D5 G7 footnote and PHASE_4_SPEC §3.5 algorithm note.

References:
    ADR-0005 D5 (gates G1-G7), D8 (cost scenarios for G3).
    ADR-0002 Section A item 7 (three-scenario cost model).
    PHASE_4_SPEC §3.5.
    López de Prado, M. (2018). *Advances in Financial Machine
    Learning*, Wiley.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl
from sklearn.ensemble import RandomForestClassifier

from features.cv.cpcv import CombinatoriallyPurgedKFold
from features.hypothesis.dsr import DeflatedSharpeCalculator
from features.hypothesis.pbo import PBOCalculator
from features.meta_labeler.baseline import BaselineTrainingResult
from features.meta_labeler.feature_builder import MetaLabelerFeatureSet
from features.meta_labeler.pnl_simulation import (
    CostScenario,
    PnLSimulationResult,
    simulate_meta_labeler_pnl,
)
from features.meta_labeler.tuning import TuningResult

__all__ = [
    "GateResult",
    "MetaLabelerValidationReport",
    "MetaLabelerValidator",
]


# ADR-0005 D5 gate thresholds. Sourced verbatim from the ADR table.
_G1_MEAN_AUC_THRESHOLD: float = 0.55
_G2_MIN_AUC_THRESHOLD: float = 0.52
_G3_DSR_THRESHOLD: float = 0.95
_G4_PBO_THRESHOLD: float = 0.10
_G5_BRIER_THRESHOLD: float = 0.25
_G6_MINORITY_REJECT: float = 0.05
_G6_MINORITY_WARN: float = 0.10
_G7_RF_OVER_LOGREG_THRESHOLD: float = 0.03

# Annualisation factor used by ``sharpe_ratio`` for the realised
# Meta-Labeler P&L. We compute it from the median spacing of t0 in the
# fold-aggregated label set rather than hard-coding √252; see
# ``_annualisation_factor_from_t0``.
_SECONDS_PER_TRADING_YEAR: float = 252.0 * 6.5 * 3600.0  # 252 days × 6.5h


@dataclass(frozen=True)
class GateResult:
    """Per-gate measurement and verdict.

    Attributes:
        name:
            Canonical gate name in the ``"G{n}_<short>"`` form (e.g.
            ``"G1_mean_auc"``). Stable for downstream JSON consumers.
        value:
            The measured statistic (e.g. mean OOS AUC for G1).
        threshold:
            The pass/fail threshold from ADR-0005 D5.
        passed:
            ``True`` iff the gate's pass condition is satisfied.
            Pass conditions: ``value >= threshold`` for G1, G2, G3, G7;
            ``value < threshold`` for G4 (PBO is overfitting-direction);
            ``value <= threshold`` for G5 (Brier is loss-direction);
            for G6 see :meth:`MetaLabelerValidator._gate_g6`.
    """

    name: str
    value: float
    threshold: float
    passed: bool


@dataclass(frozen=True)
class MetaLabelerValidationReport:
    """Full ADR-0005 D5 verdict for one Meta-Labeler candidate.

    Attributes:
        gates:
            Tuple of seven :class:`GateResult` ordered G1 → G7.
        all_passed:
            ``True`` iff every gate passed.
        failing_gate_names:
            Tuple of gate names whose ``passed`` is ``False``, in
            canonical order. Empty when ``all_passed`` is ``True``.
        pnl_realistic_sharpe:
            Annualised realised Sharpe under the realistic cost
            scenario (5 bps per side per ADR-0005 D8).
        pnl_realistic_sharpe_ci:
            95 % stationary-bootstrap CI on
            ``pnl_realistic_sharpe`` (Politis & Romano 1994).
        dsr:
            Deflated Sharpe Ratio of the realistic-cost P&L.
        pbo:
            Probability of Backtest Overfitting computed from the
            tuning trial ledger (4.4).
        scenario_realistic_round_trip_bps:
            Round-trip cost (10 bps) used for G3, recorded for the
            report so the cost regime is auditable from the artefact.
    """

    gates: tuple[GateResult, ...]
    all_passed: bool
    failing_gate_names: tuple[str, ...]
    pnl_realistic_sharpe: float
    pnl_realistic_sharpe_ci: tuple[float, float]
    dsr: float
    pbo: float
    scenario_realistic_round_trip_bps: float


class MetaLabelerValidator:
    """Run the seven ADR-0005 D5 gates and emit a validation report.

    Parameters
    ----------
    cpcv:
        The same outer :class:`CombinatoriallyPurgedKFold` used by 4.3
        :class:`BaselineMetaLabeler`. The validator re-walks
        ``cpcv.split(...)`` to recover per-fold OOS proba for the P&L
        simulator. Passing the same instance - not a re-constructed
        one with a different RNG state - guarantees the partition is
        identical.
    cost_scenario:
        Which :class:`CostScenario` feeds the G3 DSR gate. Defaults to
        :attr:`CostScenario.REALISTIC` per ADR-0005 D8 contract; only
        :attr:`CostScenario.REALISTIC` is a deployment gate, the
        others are informational and may be requested for sensitivity
        reports.
    seed:
        Deterministic seed used by the bootstrap CI on the realised
        Sharpe. Defaults to ``42`` (mirrors ``APEX_SEED``).
    """

    def __init__(
        self,
        cpcv: CombinatoriallyPurgedKFold,
        cost_scenario: CostScenario = CostScenario.REALISTIC,
        seed: int = 42,
    ) -> None:
        self._cpcv = cpcv
        self._scenario = cost_scenario
        self._seed = int(seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(
        self,
        training_result: BaselineTrainingResult,
        tuning_result: TuningResult,
        features: MetaLabelerFeatureSet,
        y: npt.NDArray[np.int_],
        sample_weights: npt.NDArray[np.float64],
        bars_for_pnl: pl.DataFrame,
    ) -> MetaLabelerValidationReport:
        """Run gates G1-G7 and emit the validation report.

        Args:
            training_result:
                Output of :meth:`features.meta_labeler.baseline
                .BaselineMetaLabeler.train`. Provides
                ``rf_auc_per_fold``, ``logreg_auc_per_fold``,
                ``rf_brier_per_fold`` for G1, G2, G5, G7 and the
                tuned RF hyperparameters via ``rf_model.get_params``.
            tuning_result:
                Output of :meth:`features.meta_labeler.tuning
                .NestedCPCVTuner.tune`. Provides the trial ledger for
                G4 PBO computation.
            features:
                Same feature set used for training. Used to reconstruct
                per-fold OOS predicted probabilities under the tuned
                hyperparameters.
            y:
                Binary target vector - same one passed to 4.3 trainer.
            sample_weights:
                Per-sample weights - same array as 4.3.
            bars_for_pnl:
                Polars DataFrame with ``timestamp`` + ``close`` columns
                covering the union ``[min(t0), max(t1)]``. Same series
                used for Triple Barrier in 4.1.

        Returns:
            :class:`MetaLabelerValidationReport`.

        Raises:
            ValueError: on any missing evidence, length mismatch,
                degenerate fold, or out-of-contract input. See the
                module docstring "fail-loud" section.
        """
        self._validate_inputs(training_result, tuning_result, features, y, sample_weights)

        # G1 / G2 / G7: read directly from the 4.3 baseline result.
        rf_aucs = np.asarray(training_result.rf_auc_per_fold, dtype=np.float64)
        logreg_aucs = np.asarray(training_result.logreg_auc_per_fold, dtype=np.float64)
        g1 = self._gate_g1(rf_aucs)
        g2 = self._gate_g2(rf_aucs)
        g7 = self._gate_g7(rf_aucs, logreg_aucs)

        # G5: weighted-mean Brier across folds. ``BaselineMetaLabeler``
        # already computes ``fold_brier`` with sample weights.
        g5 = self._gate_g5(np.asarray(training_result.rf_brier_per_fold, dtype=np.float64))

        # G6: minority class frequency on the training labels.
        g6 = self._gate_g6(np.asarray(y))

        # G4: PBO from the tuning trial ledger.
        g4, pbo_value = self._gate_g4(tuning_result)

        # G3: rebuild per-fold OOS proba with the tuned hparams,
        # simulate the realistic-cost P&L, then compute DSR.
        pnl, sharpe, sharpe_ci = self._compute_pnl_and_sharpe(
            tuning_result, features, y, sample_weights, bars_for_pnl
        )
        g3, dsr_value = self._gate_g3(pnl, sharpe)

        gates = (g1, g2, g3, g4, g5, g6, g7)
        all_passed = all(g.passed for g in gates)
        failing = tuple(g.name for g in gates if not g.passed)

        return MetaLabelerValidationReport(
            gates=gates,
            all_passed=all_passed,
            failing_gate_names=failing,
            pnl_realistic_sharpe=float(sharpe),
            pnl_realistic_sharpe_ci=sharpe_ci,
            dsr=float(dsr_value),
            pbo=float(pbo_value),
            scenario_realistic_round_trip_bps=float(self._scenario.round_trip_bps),
        )

    # ------------------------------------------------------------------
    # Per-gate helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _gate_g1(rf_aucs: npt.NDArray[np.float64]) -> GateResult:
        value = float(np.mean(rf_aucs))
        return GateResult(
            name="G1_mean_auc",
            value=value,
            threshold=_G1_MEAN_AUC_THRESHOLD,
            passed=value >= _G1_MEAN_AUC_THRESHOLD,
        )

    @staticmethod
    def _gate_g2(rf_aucs: npt.NDArray[np.float64]) -> GateResult:
        value = float(np.min(rf_aucs))
        return GateResult(
            name="G2_min_auc",
            value=value,
            threshold=_G2_MIN_AUC_THRESHOLD,
            passed=value >= _G2_MIN_AUC_THRESHOLD,
        )

    def _gate_g3(
        self,
        pnl: PnLSimulationResult,
        realised_sharpe: float,
    ) -> tuple[GateResult, float]:
        """G3 DSR on the realistic-cost realised P&L.

        DSR is computed via :class:`DeflatedSharpeCalculator` on the
        single-strategy series. ``n_trials`` defaults to 1 (single
        Meta-Labeler candidate at this stage); multi-strategy DSR
        correction across the Fusion Engine ensemble is Phase 4.7+.
        """
        ret_series = pl.Series("meta_labeler_realistic", pnl.all_net_returns.tolist())
        calc = DeflatedSharpeCalculator(significance_threshold=_G3_DSR_THRESHOLD)
        results = calc.compute(
            feature_sharpes={"meta_labeler_realistic": realised_sharpe},
            returns_data={"meta_labeler_realistic": ret_series},
            benchmark_sharpe=0.0,
        )
        if not results:  # pragma: no cover - defensive
            raise ValueError("DSR calculator returned no result for the realistic P&L")
        dsr = float(results[0].dsr)
        return (
            GateResult(
                name="G3_dsr",
                value=dsr,
                threshold=_G3_DSR_THRESHOLD,
                passed=dsr >= _G3_DSR_THRESHOLD,
            ),
            dsr,
        )

    @staticmethod
    def _gate_g4(tuning_result: TuningResult) -> tuple[GateResult, float]:
        """G4 PBO from the trial ledger.

        ``TuningResult.all_trials`` is a flat tuple of length
        ``n_outer_folds * cardinality``. We pivot it into the two
        dicts expected by :class:`PBOCalculator`: keys = trial-id
        (deterministic ``"n=...d=...min=..."`` string), values =
        per-outer-fold metric.
        """
        if not tuning_result.all_trials:
            raise ValueError(
                "G4: tuning_result.all_trials is empty - cannot compute PBO. "
                "Re-run Phase 4.4 with a non-empty search space."
            )

        # Recover the trial-grid ordering. Every outer fold evaluates
        # the same grid in the same order, so we deduce the
        # cardinality from the first occurrence of any trial.
        first_hp = tuning_result.all_trials[0][0]
        trial_ids: list[str] = []
        for hp, _, _ in tuning_result.all_trials:
            tid = _trial_id(hp)
            if tid in trial_ids:
                break
            trial_ids.append(tid)
        cardinality = len(trial_ids)
        n_outer = len(tuning_result.all_trials) // cardinality
        if cardinality * n_outer != len(tuning_result.all_trials):  # pragma: no cover
            raise ValueError(
                "G4: trial ledger length is not a multiple of the recovered "
                "grid cardinality; tuning_result is malformed."
            )
        if cardinality < 2:
            raise ValueError(
                f"G4: PBO requires at least 2 distinct trial hyperparameters, "
                f"got {cardinality}. Widen the Phase 4.4 search space."
            )

        is_metrics: dict[str, list[float]] = {tid: [] for tid in trial_ids}
        oos_metrics: dict[str, list[float]] = {tid: [] for tid in trial_ids}
        for outer_idx in range(n_outer):
            offset = outer_idx * cardinality
            for j, tid in enumerate(trial_ids):
                hp, mean_inner, oos = tuning_result.all_trials[offset + j]
                if _trial_id(hp) != tid:  # pragma: no cover
                    raise ValueError(
                        f"G4: trial ledger ordering broken at outer={outer_idx}, "
                        f"slot={j}: expected {tid}, got {_trial_id(hp)}."
                    )
                is_metrics[tid].append(float(mean_inner))
                oos_metrics[tid].append(float(oos))

        pbo_result = PBOCalculator(
            adr0004_threshold=_G4_PBO_THRESHOLD
        ).compute(is_metrics=is_metrics, oos_metrics=oos_metrics)

        # Suppress the unused-first_hp lint: we keep it bound for
        # debuggability; downstream branches do not consume it.
        del first_hp

        return (
            GateResult(
                name="G4_pbo",
                value=float(pbo_result.pbo),
                threshold=_G4_PBO_THRESHOLD,
                passed=pbo_result.pbo < _G4_PBO_THRESHOLD,
            ),
            float(pbo_result.pbo),
        )

    @staticmethod
    def _gate_g5(rf_briers: npt.NDArray[np.float64]) -> GateResult:
        value = float(np.mean(rf_briers))
        return GateResult(
            name="G5_brier",
            value=value,
            threshold=_G5_BRIER_THRESHOLD,
            passed=value <= _G5_BRIER_THRESHOLD,
        )

    @staticmethod
    def _gate_g6(y: npt.NDArray[np.int_]) -> GateResult:
        """G6 minority-class frequency.

        The pass condition is **not** symmetric:
        - ``freq < 0.05`` → reject (passed=False).
        - ``0.05 <= freq < 0.10`` → warn but pass (passed=True). The
          warning is non-blocking per ADR-0005 D5 G6 rationale; it is
          recorded in the report under ``threshold`` so the consumer
          sees the warn boundary.
        - ``freq >= 0.10`` → ok (passed=True).
        """
        # Frequency of the rarer of the two classes.
        zeros = float(np.sum(y == 0))
        ones = float(np.sum(y == 1))
        n = zeros + ones
        if n == 0:  # pragma: no cover - guarded by validate_inputs
            raise ValueError("G6: empty y vector")
        freq = min(zeros, ones) / n
        passed = freq >= _G6_MINORITY_REJECT
        return GateResult(
            name="G6_minority_freq",
            value=freq,
            threshold=_G6_MINORITY_WARN,
            passed=passed,
        )

    @staticmethod
    def _gate_g7(
        rf_aucs: npt.NDArray[np.float64],
        logreg_aucs: npt.NDArray[np.float64],
    ) -> GateResult:
        """G7 RF − LogReg mean OOS AUC.

        ADR-0005 D5 G7 footnote: this gate must fail loudly if the
        LogReg baseline is missing; silent pass is forbidden. The
        ``ValueError`` for an empty ``logreg_aucs`` is raised in
        :meth:`_validate_inputs` upstream.
        """
        delta = float(np.mean(rf_aucs) - np.mean(logreg_aucs))
        return GateResult(
            name="G7_rf_minus_logreg",
            value=delta,
            threshold=_G7_RF_OVER_LOGREG_THRESHOLD,
            passed=delta >= _G7_RF_OVER_LOGREG_THRESHOLD,
        )

    # ------------------------------------------------------------------
    # P&L + Sharpe machinery
    # ------------------------------------------------------------------

    def _compute_pnl_and_sharpe(
        self,
        tuning_result: TuningResult,
        features: MetaLabelerFeatureSet,
        y: npt.NDArray[np.int_],
        sample_weights: npt.NDArray[np.float64],
        bars_for_pnl: pl.DataFrame,
    ) -> tuple[PnLSimulationResult, float, tuple[float, float]]:
        """Re-fit per-fold RFs with tuned hparams and run the simulator."""
        x = features.X
        t0 = features.t0
        t1 = features.t1
        n = x.shape[0]
        if y.shape[0] != n or sample_weights.shape[0] != n:
            raise ValueError(
                f"y / sample_weights length must match features.X "
                f"({n}); got {y.shape[0]} and {sample_weights.shape[0]}"
            )

        per_fold_t0: list[npt.NDArray[np.datetime64]] = []
        per_fold_t1: list[npt.NDArray[np.datetime64]] = []
        per_fold_proba: list[npt.NDArray[np.float64]] = []

        best_hp_per_fold = tuning_result.best_hyperparameters_per_fold
        n_folds = len(best_hp_per_fold)
        observed = 0
        for outer_idx, (train_idx, test_idx) in enumerate(
            self._cpcv.split(x, t1, t0)
        ):
            if outer_idx >= n_folds:  # pragma: no cover - shape guarded below
                raise ValueError(
                    "outer CPCV produced more folds than tuning_result has "
                    "best_hyperparameters_per_fold entries."
                )
            if len(train_idx) == 0 or len(test_idx) == 0:
                raise ValueError(
                    f"outer CPCV produced an empty split at fold {outer_idx}: "
                    f"|train|={len(train_idx)}, |test|={len(test_idx)}."
                )
            hp = best_hp_per_fold[outer_idx]
            rf = _build_rf(hp, seed=self._seed + outer_idx * 7)
            rf.fit(x[train_idx], y[train_idx], sample_weight=sample_weights[train_idx])
            proba = rf.predict_proba(x[test_idx])[:, 1].astype(np.float64)

            per_fold_t0.append(np.asarray(t0)[test_idx])
            per_fold_t1.append(np.asarray(t1)[test_idx])
            per_fold_proba.append(proba)
            observed += 1

        if observed != n_folds:
            raise ValueError(
                f"outer CPCV yielded {observed} folds but tuning_result "
                f"declares {n_folds}; partitions disagree."
            )

        pnl = simulate_meta_labeler_pnl(
            bars=bars_for_pnl,
            t0_per_fold=tuple(per_fold_t0),
            t1_per_fold=tuple(per_fold_t1),
            proba_per_fold=tuple(per_fold_proba),
            scenario=self._scenario,
        )
        if pnl.all_net_returns.size < 2:
            raise ValueError(
                "G3: realised return series has fewer than 2 observations; "
                "cannot compute Sharpe / DSR."
            )

        ann = _annualisation_factor_from_t0(per_fold_t0)
        sharpe = _sharpe(pnl.all_net_returns, annual_factor=ann)
        ci = _stationary_bootstrap_sharpe_ci(
            pnl.all_net_returns,
            annual_factor=ann,
            n_resamples=1000,
            confidence=0.95,
            seed=self._seed,
        )
        return pnl, sharpe, ci

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_inputs(
        training_result: BaselineTrainingResult,
        tuning_result: TuningResult,
        features: MetaLabelerFeatureSet,
        y: npt.NDArray[np.int_],
        sample_weights: npt.NDArray[np.float64],
    ) -> None:
        if len(training_result.rf_auc_per_fold) == 0:
            raise ValueError(
                "training_result.rf_auc_per_fold is empty - Phase 4.3 must "
                "run at least one outer fold before validation."
            )
        if len(training_result.logreg_auc_per_fold) == 0:
            raise ValueError(
                "G7 baseline missing: training_result.logreg_auc_per_fold "
                "is empty. ADR-0005 D5 G7 forbids silent pass."
            )
        if len(training_result.rf_auc_per_fold) != len(
            training_result.logreg_auc_per_fold
        ):
            raise ValueError(
                "rf_auc_per_fold and logreg_auc_per_fold must have the same "
                f"length; got {len(training_result.rf_auc_per_fold)} vs "
                f"{len(training_result.logreg_auc_per_fold)}."
            )
        if len(training_result.rf_brier_per_fold) != len(
            training_result.rf_auc_per_fold
        ):
            raise ValueError(
                "rf_brier_per_fold and rf_auc_per_fold must have the same "
                f"length; got {len(training_result.rf_brier_per_fold)} vs "
                f"{len(training_result.rf_auc_per_fold)}."
            )
        if not tuning_result.best_hyperparameters_per_fold:
            raise ValueError("tuning_result.best_hyperparameters_per_fold is empty")
        if features.X.shape[0] != y.shape[0]:
            raise ValueError(
                f"features.X has {features.X.shape[0]} rows but y has "
                f"{y.shape[0]} entries"
            )
        if features.X.shape[0] != sample_weights.shape[0]:
            raise ValueError(
                f"features.X has {features.X.shape[0]} rows but "
                f"sample_weights has {sample_weights.shape[0]} entries"
            )


# ----------------------------------------------------------------------
# Module-private helpers
# ----------------------------------------------------------------------


def _trial_id(hp: dict[str, Any]) -> str:
    """Deterministic, JSON-safe identifier for a hparam dict.

    The key order is fixed: ``n_estimators``, ``max_depth``,
    ``min_samples_leaf`` - matching :class:`TuningSearchSpace.grid`.
    Used as the trial-key in the PBO IS / OOS dicts.
    """
    return (
        f"n={hp.get('n_estimators')}_"
        f"d={hp.get('max_depth')}_"
        f"min={hp.get('min_samples_leaf')}"
    )


def _build_rf(hp: dict[str, Any], *, seed: int) -> RandomForestClassifier:
    """Construct an RF with caller hparams + tuner-controlled keys.

    Mirrors :class:`features.meta_labeler.baseline.BaselineMetaLabeler._make_rf`
    so the per-fold OOS proba reproduce 4.4's contract exactly.
    """
    return RandomForestClassifier(
        **hp,
        random_state=seed,
        class_weight="balanced",
        n_jobs=1,
    )


def _annualisation_factor_from_t0(
    per_fold_t0: list[npt.NDArray[np.datetime64]],
) -> float:
    """Estimate the annualisation factor from the median t0 spacing.

    Returns ``√(seconds_per_year / median_seconds_between_t0)``.
    Uses 252×6.5h = 5,896,800 s per trading year per ADR-0002 D7 (US
    equities session). For 24/7 series the same formula applies and
    yields a slightly different but consistent factor - the goal is
    a reproducible scaling, not an exact regulatory one.

    Falls back to ``√252`` (≈ daily) when there are fewer than 2
    timestamps to estimate the spacing.
    """
    flat = np.concatenate(per_fold_t0) if per_fold_t0 else np.empty(0, dtype="datetime64[us]")
    if flat.size < 2:
        return float(np.sqrt(252.0))
    flat_sorted = np.sort(flat)
    diffs = np.diff(flat_sorted).astype("timedelta64[us]").astype(np.int64) / 1e6
    diffs_pos = diffs[diffs > 0]
    if diffs_pos.size == 0:
        return float(np.sqrt(252.0))
    median_seconds = float(np.median(diffs_pos))
    if median_seconds <= 0.0:  # pragma: no cover - guarded above
        return float(np.sqrt(252.0))
    periods_per_year = _SECONDS_PER_TRADING_YEAR / median_seconds
    return float(np.sqrt(max(periods_per_year, 1.0)))


def _sharpe(
    returns: npt.NDArray[np.float64],
    *,
    annual_factor: float,
) -> float:
    """Annualised Sharpe with risk-free rate = 0.

    Wrapper over a numpy-only implementation (avoids the
    ``backtesting.metrics.sharpe_ratio`` list-of-floats interface so
    we keep the validator allocation-light).
    """
    if returns.size < 2:
        return 0.0
    std = float(np.std(returns, ddof=1))
    if std < 1e-12:
        mean = float(np.mean(returns))
        if abs(mean) < 1e-12:
            return 0.0
        return float("inf") if mean > 0 else float("-inf")
    return float(np.mean(returns)) / std * annual_factor


def _stationary_bootstrap_sharpe_ci(
    returns: npt.NDArray[np.float64],
    *,
    annual_factor: float,
    n_resamples: int = 1000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float, float]:
    """Politis-Romano (1994) stationary bootstrap CI on the Sharpe.

    Block length ``L = max(1, round(n^(1/3)))`` per the Politis-Romano
    rule of thumb. Geometric block lengths preserve weak dependence
    so the resampled series remains stationary.

    Returns a ``(low, high)`` tuple at the requested confidence level.
    Returns ``(0.0, 0.0)`` for fewer than 2 observations and
    ``(point, point)`` for a zero-variance series.

    Reference: Politis, D. N., & Romano, J. P. (1994). "The stationary
    bootstrap." JASA 89(428), 1303-1313.
    """
    n = int(returns.size)
    if n < 2:
        return 0.0, 0.0
    point = _sharpe(returns, annual_factor=annual_factor)
    if float(np.std(returns, ddof=1)) < 1e-12:
        return point, point

    rng = np.random.default_rng(seed)
    block_len = max(1, round(n ** (1.0 / 3.0)))
    p = 1.0 / block_len
    alpha = 1.0 - confidence
    lo_pct = 100.0 * (alpha / 2.0)
    hi_pct = 100.0 * (1.0 - alpha / 2.0)

    sharpes = np.empty(n_resamples, dtype=np.float64)
    for b in range(n_resamples):
        idx = np.empty(n, dtype=np.int64)
        i = 0
        while i < n:
            start = int(rng.integers(0, n))
            length = int(rng.geometric(p))
            length = min(length, n - i)
            for k in range(length):
                idx[i + k] = (start + k) % n
            i += length
        sharpes[b] = _sharpe(returns[idx], annual_factor=annual_factor)

    lo = float(np.percentile(sharpes, lo_pct))
    hi = float(np.percentile(sharpes, hi_pct))
    return lo, hi
