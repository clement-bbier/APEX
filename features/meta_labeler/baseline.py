"""Phase 4.3 - Baseline Meta-Labeler training (Random Forest + LogReg).

Implements the ADR-0005 D3 contract:

- **Primary model**: :class:`~sklearn.ensemble.RandomForestClassifier`
  with default hyperparameters (untuned at this phase - tuning is
  deferred to 4.4).
- **Mandatory baseline**: :class:`~sklearn.linear_model.LogisticRegression`
  always trained alongside the RF on the same fold partitions, same
  ``sample_weight``, same class balancing. A trained-model output is
  rejected downstream (Phase 4.5, gate G7) if its OOS AUC does not
  beat the LogReg baseline by at least 3 pp on average across folds.
- **Cross-validation**: outer :class:`CombinatoriallyPurgedKFold` passed
  by the caller (Phase 4.4 will wrap this in a nested CV, but 4.3 is
  single-level only).

Both models are trained with ``class_weight="balanced"`` so the
optimiser cannot collapse onto the majority class in imbalanced label
distributions (Triple Barrier produces 0 / 1 distributions anywhere in
``[0.3, 0.7]`` depending on the barrier calibration).

Outputs are packed into a frozen :class:`BaselineTrainingResult` so the
Phase 4.3 diagnostic report can be generated without re-running training.

References:
    ADR-0005 D3 - primary and baseline classifier choice.
    ADR-0005 D4 - nested CPCV (outer only at this phase).
    PHASE_4_SPEC section 3.3 - trainer API and diagnostic invariants.
    Lopez de Prado (2018), *Advances in Financial Machine Learning*,
    section 6.1 (Strategy Ensembles).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from features.cv.cpcv import CombinatoriallyPurgedKFold
from features.meta_labeler.feature_builder import FEATURE_NAMES, MetaLabelerFeatureSet
from features.meta_labeler.metrics import calibration_bins, fold_auc, fold_brier

__all__ = [
    "BaselineMetaLabeler",
    "BaselineTrainingResult",
]


@dataclass(frozen=True)
class BaselineTrainingResult:
    """Frozen container for the Phase 4.3 training outputs.

    Attributes:
        rf_model:
            The final Random Forest fitted on *all* training data
            (after per-fold OOS diagnostics have been collected). This
            is the artefact Phase 4.6 will persist.
        logreg_model:
            The baseline Logistic Regression, also fitted on all data.
        rf_auc_per_fold:
            Tuple of per-fold OOS ROC-AUC values for the RF; length
            equals ``cpcv.get_n_splits()``.
        logreg_auc_per_fold:
            Per-fold OOS ROC-AUC for the LogReg baseline, same
            ordering as ``rf_auc_per_fold``.
        rf_brier_per_fold:
            Per-fold OOS Brier score for the RF, same ordering.
        rf_calibration_bins:
            Aggregate 10-bin reliability diagram on the concatenated
            OOS predictions of the RF. Tuple of
            ``(mean_predicted, observed_positive_rate)`` pairs; length
            ``<= n_bins`` because empty bins are dropped.
        feature_importances:
            ``{feature_name: importance}`` dictionary for the final RF;
            keys match :data:`features.meta_labeler.feature_builder.FEATURE_NAMES`
            and values sum to ``~1.0``.
    """

    rf_model: RandomForestClassifier
    logreg_model: LogisticRegression
    rf_auc_per_fold: tuple[float, ...]
    logreg_auc_per_fold: tuple[float, ...]
    rf_brier_per_fold: tuple[float, ...]
    rf_calibration_bins: tuple[tuple[float, float], ...]
    feature_importances: dict[str, float]


class BaselineMetaLabeler:
    """Train the Phase 4.3 baseline (RandomForest + LogReg) with CPCV.

    Workflow:

    1. For each of ``cpcv.get_n_splits()`` outer folds:
       a. Extract ``(train_idx, test_idx)`` from ``cpcv.split(X, t1, t0)``.
       b. Fit a fresh RF and LogReg on the training subset using the
          caller-provided ``sample_weights``.
       c. Score OOS predictions on the test subset, collect AUC (both
          models), Brier (RF only), and predicted probabilities.
    2. Fit one final RF and LogReg on **all** data for downstream
       persistence (Phase 4.6) and feature-importance analysis.
    3. Aggregate the concatenated OOS RF probabilities into a
       reliability diagram.
    4. Pack everything into :class:`BaselineTrainingResult`.

    Parameters
    ----------
    cpcv:
        Pre-constructed :class:`CombinatoriallyPurgedKFold`. The caller
        controls ``n_splits``, ``n_test_splits`` and ``embargo_pct`` -
        Phase 4.3 defaults to ``(6, 2, 0.02)`` per ADR-0005 D4.
    rf_hyperparameters:
        Optional override for the default RF hyperparameters. The keys
        ``random_state``, ``class_weight``, and ``n_jobs`` always take
        the trainer's values (seed-determinism and balanced weighting
        are non-negotiable). Defaults to Phase 4.3 reference:
        ``{n_estimators=200, max_depth=10, min_samples_leaf=5}``.
    seed:
        Deterministic seed propagated to both models. Default ``42``.
    """

    _DEFAULT_RF_HP: ClassVar[dict[str, Any]] = {
        "n_estimators": 200,
        "max_depth": 10,
        "min_samples_leaf": 5,
    }

    def __init__(
        self,
        cpcv: CombinatoriallyPurgedKFold,
        rf_hyperparameters: dict[str, Any] | None = None,
        seed: int = 42,
    ) -> None:
        self._cpcv = cpcv
        self._seed = int(seed)

        # Caller-provided hyperparameters override the defaults for
        # everything except the three reserved keys.
        hp = dict(self._DEFAULT_RF_HP)
        if rf_hyperparameters:
            reserved = {"random_state", "class_weight", "n_jobs"}
            overlap = reserved & rf_hyperparameters.keys()
            if overlap:
                raise ValueError(
                    f"rf_hyperparameters cannot override reserved keys {sorted(overlap)}; "
                    "seed, class_weight and n_jobs are trainer-controlled."
                )
            hp.update(rf_hyperparameters)
        self._rf_hp = hp

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def train(
        self,
        features: MetaLabelerFeatureSet,
        y: npt.NDArray[np.int_],
        sample_weights: npt.NDArray[np.float64],
    ) -> BaselineTrainingResult:
        """Run the Phase 4.3 training loop.

        Parameters
        ----------
        features:
            Output of :class:`MetaLabelerFeatureBuilder.build`.
        y:
            Binary target vector, shape ``(n_samples,)``, dtype int /
            ``np.int_``. Values must be in ``{0, 1}``.
        sample_weights:
            Per-sample training weight, shape ``(n_samples,)``, dtype
            ``float64``. Normalised or unnormalised - sklearn handles
            both.

        Returns
        -------
        BaselineTrainingResult
            Frozen bundle with per-fold metrics and the final models.

        Raises
        ------
        ValueError
            If shapes disagree, if ``y`` contains a value outside
            ``{0, 1}``, or if the OOS AUC cannot be computed on some
            fold (constant ``y_true`` on the test subset - a symptom of
            a pathological CPCV partition that callers should address).
        """
        x, y_arr, w_arr = self._validate_inputs(features, y, sample_weights)

        rf_aucs: list[float] = []
        logreg_aucs: list[float] = []
        rf_briers: list[float] = []
        oos_prob_parts: list[npt.NDArray[np.float64]] = []
        oos_true_parts: list[npt.NDArray[np.int_]] = []

        for train_idx, test_idx in self._cpcv.split(x, features.t1, features.t0):
            if len(train_idx) == 0 or len(test_idx) == 0:
                raise ValueError(
                    f"CPCV produced an empty split: "
                    f"|train|={len(train_idx)}, |test|={len(test_idx)}. "
                    "Check n_splits / n_test_splits / embargo_pct against n_samples."
                )

            rf_fold = self._make_rf()
            logreg_fold = self._make_logreg()

            rf_fold.fit(x[train_idx], y_arr[train_idx], sample_weight=w_arr[train_idx])
            logreg_fold.fit(x[train_idx], y_arr[train_idx], sample_weight=w_arr[train_idx])

            rf_prob = rf_fold.predict_proba(x[test_idx])[:, 1].astype(np.float64)
            logreg_prob = logreg_fold.predict_proba(x[test_idx])[:, 1].astype(np.float64)
            y_test = y_arr[test_idx]
            w_test = w_arr[test_idx]

            rf_aucs.append(fold_auc(y_test, rf_prob, sample_weight=w_test))
            logreg_aucs.append(fold_auc(y_test, logreg_prob, sample_weight=w_test))
            rf_briers.append(fold_brier(y_test, rf_prob, sample_weight=w_test))

            oos_prob_parts.append(rf_prob)
            oos_true_parts.append(y_test)

        # Final models fit on all data for persistence and global
        # feature-importance extraction.
        rf_final = self._make_rf()
        logreg_final = self._make_logreg()
        rf_final.fit(x, y_arr, sample_weight=w_arr)
        logreg_final.fit(x, y_arr, sample_weight=w_arr)

        importances_arr = np.asarray(rf_final.feature_importances_, dtype=np.float64)
        importances = {
            name: float(val) for name, val in zip(FEATURE_NAMES, importances_arr, strict=True)
        }

        # Concatenate OOS probabilities to build the aggregate calibration
        # curve. This aggregates information across folds and smooths
        # out noise in any single fold's 10-bin estimate.
        oos_prob_all = np.concatenate(oos_prob_parts)
        oos_true_all = np.concatenate(oos_true_parts)
        calibration = tuple(calibration_bins(oos_true_all, oos_prob_all, n_bins=10))

        return BaselineTrainingResult(
            rf_model=rf_final,
            logreg_model=logreg_final,
            rf_auc_per_fold=tuple(rf_aucs),
            logreg_auc_per_fold=tuple(logreg_aucs),
            rf_brier_per_fold=tuple(rf_briers),
            rf_calibration_bins=calibration,
            feature_importances=importances,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_rf(self) -> RandomForestClassifier:
        return RandomForestClassifier(
            **self._rf_hp,
            random_state=self._seed,
            class_weight="balanced",
            n_jobs=1,
        )

    def _make_logreg(self) -> LogisticRegression:
        # max_iter raised above the sklearn default of 100 so convergence
        # is reliable on standardised features - Phase 4.3 feature matrix
        # is not standardised per-fold (deferred to 4.4); a higher
        # ``max_iter`` compensates without introducing a leakage-prone
        # per-fold scaler.
        return LogisticRegression(
            random_state=self._seed,
            class_weight="balanced",
            solver="liblinear",
            max_iter=1000,
        )

    @staticmethod
    def _validate_inputs(
        features: MetaLabelerFeatureSet,
        y: npt.NDArray[np.int_],
        sample_weights: npt.NDArray[np.float64],
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.int_], npt.NDArray[np.float64]]:
        x = np.asarray(features.X, dtype=np.float64)
        if x.ndim != 2:
            raise ValueError(f"features.X must be 2-D; got shape {x.shape}")
        if x.shape[0] == 0:
            raise ValueError("cannot train on an empty feature matrix")
        if not np.isfinite(x).all():
            raise ValueError("features.X contains non-finite values (NaN/Inf)")
        y_arr = np.asarray(y)
        if y_arr.ndim != 1:
            raise ValueError(f"y must be 1-D; got shape {y_arr.shape}")
        if y_arr.shape[0] != x.shape[0]:
            raise ValueError(f"y length ({y_arr.shape[0]}) != n_samples ({x.shape[0]})")
        if y_arr.dtype.kind not in ("i", "u"):
            raise ValueError(f"y must be an integer array; got dtype {y_arr.dtype}")
        unique = np.unique(y_arr)
        extra = set(unique.tolist()) - {0, 1}
        if extra:
            raise ValueError(f"y must be binary in {{0, 1}}; found extra labels {sorted(extra)}")
        if len(unique) < 2:
            raise ValueError(
                "y contains only one class; cannot train a binary classifier on a "
                "degenerate target."
            )
        w_arr = np.asarray(sample_weights, dtype=np.float64)
        if w_arr.ndim != 1:
            raise ValueError(f"sample_weights must be 1-D; got shape {w_arr.shape}")
        if w_arr.shape[0] != x.shape[0]:
            raise ValueError(
                f"sample_weights length ({w_arr.shape[0]}) != n_samples ({x.shape[0]})"
            )
        if not np.isfinite(w_arr).all():
            raise ValueError("sample_weights contains non-finite values (NaN/Inf)")
        if np.any(w_arr < 0.0):
            raise ValueError("sample_weights must be non-negative")
        return x, y_arr, w_arr
