"""Phase 4.4 - Nested CPCV hyperparameter tuning for the Meta-Labeler.

Implements the ADR-0005 D4 contract and PHASE_4_SPEC section 3.4:

- **Outer loop**: the caller-supplied :class:`CombinatoriallyPurgedKFold`
  produces ``C(n_splits, n_test_splits)`` outer folds (Phase 4.3 uses
  ``C(6, 2) = 15``). For each outer fold we have a training slice and a
  disjoint out-of-sample test slice.
- **Inner loop**: a second :class:`CombinatoriallyPurgedKFold`, strictly
  inside the outer training slice, performs grid search over
  :class:`TuningSearchSpace`. No outer test index is ever passed to an
  inner fit - this is the core anti-leakage invariant verified by a
  property test.
- **Selection**: the inner-CV-mean weighted ROC-AUC is the selection
  criterion. The OOS-AUC on the outer test slice is *observed*, never
  used to pick the winner, so the nested CV remains honest in the
  Lopez de Prado (2018) section 7.4 sense and Phase 4.5's PBO
  computation on the full trial ledger is well-defined.
- **Stability index**: the fraction of outer folds whose best
  hyperparameters equal the mode across outer folds. A stability index
  of 1.0 means every outer fold selected the same hyperparameters.
- **Determinism**: every Random Forest is seeded with
  ``random_state = seed + outer_fold_index * 7``; the same
  ``(data, seed)`` pair produces bit-identical tuples of best
  hyperparameters per outer fold and the same ``all_trials`` ledger.

The module deliberately implements the nested loop explicitly rather
than delegating to :class:`sklearn.model_selection.GridSearchCV`.
``GridSearchCV`` routes ``sample_weight`` through ``fit_params``
asymmetrically across sklearn versions and does not support a
CPCV-aware splitter without a wrapper, so the explicit implementation
gives full control over sample-weight routing, per-fold seeding and
the shape of ``TuningResult.all_trials``. See
``reports/phase_4_4/audit.md`` section 10 for the decision log.

References:
    PHASE_4_SPEC section 3.4 - Nested Hyperparameter Tuning.
    ADR-0005 D4 - Nested CPCV methodology.
    Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*,
    section 7.4 (purged CV / nested CV).
"""

from __future__ import annotations

import itertools
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from sklearn.ensemble import RandomForestClassifier

from features.cv.cpcv import CombinatoriallyPurgedKFold
from features.meta_labeler.feature_builder import MetaLabelerFeatureSet
from features.meta_labeler.metrics import fold_auc

__all__ = [
    "NestedCPCVTuner",
    "TuningResult",
    "TuningSearchSpace",
]

# Hyperparameters that the tuner controls internally. A search space
# that tries to override any of these is rejected at construction time.
_RESERVED_HP_KEYS: frozenset[str] = frozenset({"random_state", "class_weight", "n_jobs"})


@dataclass(frozen=True)
class TuningSearchSpace:
    """Grid definition for the nested RF search.

    The default grid is ``3 x 3 x 2 = 18`` trials per outer fold, per
    PHASE_4_SPEC section 3.4. Callers can narrow the grid for CI (the
    report generator uses a smaller grid) but must keep at least one
    value per axis.
    """

    n_estimators: tuple[int, ...] = (100, 300, 500)
    max_depth: tuple[int | None, ...] = (5, 10, None)
    min_samples_leaf: tuple[int, ...] = (5, 20)

    def __post_init__(self) -> None:
        if not self.n_estimators:
            raise ValueError("n_estimators must contain at least one value")
        if not self.max_depth:
            raise ValueError("max_depth must contain at least one value")
        if not self.min_samples_leaf:
            raise ValueError("min_samples_leaf must contain at least one value")
        for n in self.n_estimators:
            if not isinstance(n, int) or n <= 0:
                raise ValueError(f"n_estimators values must be positive int; got {n!r}")
        for d in self.max_depth:
            if d is not None and (not isinstance(d, int) or d <= 0):
                raise ValueError(f"max_depth values must be None or positive int; got {d!r}")
        for m in self.min_samples_leaf:
            if not isinstance(m, int) or m <= 0:
                raise ValueError(f"min_samples_leaf values must be positive int; got {m!r}")

    def grid(self) -> tuple[dict[str, Any], ...]:
        """Return the Cartesian product of the axes as a tuple of dicts.

        Order is deterministic: outermost loop is ``n_estimators``,
        then ``max_depth``, then ``min_samples_leaf``. Determinism
        matters because ``TuningResult.all_trials`` preserves this
        ordering and Phase 4.5's PBO computation consumes it.
        """
        combos = [
            {"n_estimators": n, "max_depth": d, "min_samples_leaf": m}
            for n, d, m in itertools.product(
                self.n_estimators, self.max_depth, self.min_samples_leaf
            )
        ]
        return tuple(combos)

    @property
    def cardinality(self) -> int:
        """Number of trials per outer fold."""
        return len(self.n_estimators) * len(self.max_depth) * len(self.min_samples_leaf)


@dataclass(frozen=True)
class TuningResult:
    """Frozen container for the Phase 4.4 tuning outputs.

    Attributes:
        best_hyperparameters_per_fold:
            One ``dict[str, Any]`` per outer CPCV fold. Ordering
            matches ``outer_cpcv.split(...)``.
        best_oos_auc_per_fold:
            Weighted OOS ROC-AUC on the outer test slice, evaluated
            with the RF re-fit on the full outer-train slice using the
            inner-selected hyperparameters. Same ordering as
            ``best_hyperparameters_per_fold``.
        all_trials:
            Flat tuple of length ``n_outer_folds *
            search_space.cardinality``. Each entry is
            ``(hyperparameters, mean_inner_cv_auc, oos_auc_on_outer_test)``.
            Trials are grouped by outer fold in the outer-fold order;
            inside each group, trials follow
            :meth:`TuningSearchSpace.grid` order.
        stability_index:
            Fraction of outer folds whose best hyperparameters equal
            the mode across outer folds. ``1.0`` = perfect agreement.
        wall_clock_seconds:
            Wall-clock time for the whole ``tune`` call.
    """

    best_hyperparameters_per_fold: tuple[dict[str, Any], ...]
    best_oos_auc_per_fold: tuple[float, ...]
    all_trials: tuple[tuple[dict[str, Any], float, float], ...]
    stability_index: float
    wall_clock_seconds: float


class NestedCPCVTuner:
    """Nested CPCV grid search for the Random Forest Meta-Labeler.

    Workflow:

    1. For each outer fold ``i``:
       a. Partition the outer training slice via ``inner_cpcv``.
       b. For each hyperparameter combination in
          ``search_space.grid()``:
          - Fit one RF per inner fold on the inner-train slice.
          - Compute the weighted AUC on the inner-test slice.
          - Average inner-fold AUCs into ``mean_inner_cv_auc``.
          - Re-fit an RF on the full outer-train slice with the
            same hparams and score OOS AUC on the outer-test slice.
          - Record the ``(hparams, mean_inner_cv_auc, oos_auc)`` tuple.
       c. The winner for outer fold ``i`` is the hparams dict with the
          highest ``mean_inner_cv_auc``.

    2. Aggregate the per-fold winners into a stability index and pack
       everything into :class:`TuningResult`.

    Parameters
    ----------
    search_space:
        Pre-validated :class:`TuningSearchSpace`.
    outer_cpcv:
        Outer CPCV. Must yield at least one fold.
    inner_cpcv:
        Inner CPCV. Runs inside each outer training slice.
    seed:
        Deterministic seed. Per-fold RFs use
        ``random_state = seed + outer_fold_index * 7``.
    """

    def __init__(
        self,
        search_space: TuningSearchSpace,
        outer_cpcv: CombinatoriallyPurgedKFold,
        inner_cpcv: CombinatoriallyPurgedKFold,
        seed: int = 42,
    ) -> None:
        if not isinstance(search_space, TuningSearchSpace):  # pragma: no cover - defensive
            raise TypeError("search_space must be a TuningSearchSpace")
        # Detect an attempted override of the trainer-controlled RF keys
        # in any grid dict. The dataclass shape prevents this at the
        # type level, but keep a runtime guard for forward compatibility
        # with custom subclasses.
        for trial in search_space.grid():
            overlap = _RESERVED_HP_KEYS & trial.keys()
            if overlap:
                raise ValueError(
                    f"search_space cannot include reserved keys {sorted(overlap)}; "
                    "random_state, class_weight and n_jobs are tuner-controlled."
                )
        self._space = search_space
        self._outer = outer_cpcv
        self._inner = inner_cpcv
        self._seed = int(seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tune(
        self,
        features: MetaLabelerFeatureSet,
        y: npt.NDArray[np.int_],
        sample_weights: npt.NDArray[np.float64],
    ) -> TuningResult:
        """Run the nested CPCV search.

        Parameters
        ----------
        features:
            Output of
            :class:`~features.meta_labeler.feature_builder.MetaLabelerFeatureBuilder`.
        y:
            Binary target vector, ``(n_samples,)``, dtype int.
        sample_weights:
            Per-sample weights, ``(n_samples,)``, dtype ``float64``.

        Returns
        -------
        TuningResult
            Frozen bundle with per-fold best hparams, OOS AUC, trial
            ledger, stability index and wall-clock timing.

        Raises
        ------
        ValueError
            On shape / dtype / value contract violations in the inputs,
            on pathological CPCV partitions (empty train or test
            indices), or if the outer CPCV yields zero folds.
        """
        x, y_arr, w_arr = _validate_inputs(features, y, sample_weights)
        t0 = features.t0
        t1 = features.t1

        start = time.perf_counter()

        trials_grouped: list[list[tuple[dict[str, Any], float, float]]] = []
        best_hparams_per_fold: list[dict[str, Any]] = []
        best_oos_per_fold: list[float] = []

        for outer_idx, (train_idx, test_idx) in enumerate(self._outer.split(x, t1, t0)):
            if len(train_idx) == 0 or len(test_idx) == 0:
                raise ValueError(
                    f"outer CPCV produced an empty split at fold {outer_idx}: "
                    f"|train|={len(train_idx)}, |test|={len(test_idx)}."
                )

            fold_seed = self._seed + outer_idx * 7

            # --- Inner search over the hparam grid -------------------
            fold_trials: list[tuple[dict[str, Any], float, float]] = []
            best_inner_auc = -np.inf
            best_hparams: dict[str, Any] | None = None

            x_train = x[train_idx]
            y_train = y_arr[train_idx]
            w_train = w_arr[train_idx]
            t0_train = np.asarray(t0)[train_idx]
            t1_train = np.asarray(t1)[train_idx]

            for hparams in self._space.grid():
                mean_inner_auc = self._inner_mean_auc(
                    x_train, y_train, w_train, t0_train, t1_train, hparams, fold_seed
                )
                oos_auc = self._outer_refit_and_score(
                    x_train,
                    y_train,
                    w_train,
                    x[test_idx],
                    y_arr[test_idx],
                    w_arr[test_idx],
                    hparams,
                    fold_seed,
                )
                fold_trials.append((dict(hparams), mean_inner_auc, oos_auc))
                if mean_inner_auc > best_inner_auc:
                    best_inner_auc = mean_inner_auc
                    best_hparams = dict(hparams)

            if best_hparams is None:  # pragma: no cover - grid non-empty invariant
                raise RuntimeError(f"no hparams evaluated in outer fold {outer_idx}")

            trials_grouped.append(fold_trials)
            best_hparams_per_fold.append(best_hparams)
            # OOS AUC for the winning hparams is already in fold_trials;
            # pick the first (and only) matching record.
            best_oos = next(oos for (hp, _, oos) in fold_trials if hp == best_hparams)
            best_oos_per_fold.append(best_oos)

        if not best_hparams_per_fold:
            raise ValueError("outer CPCV yielded zero folds")

        flat_trials = tuple(t for group in trials_grouped for t in group)
        stability = _stability_index(best_hparams_per_fold)
        elapsed = time.perf_counter() - start

        return TuningResult(
            best_hyperparameters_per_fold=tuple(best_hparams_per_fold),
            best_oos_auc_per_fold=tuple(best_oos_per_fold),
            all_trials=flat_trials,
            stability_index=stability,
            wall_clock_seconds=float(elapsed),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _inner_mean_auc(
        self,
        x_train: npt.NDArray[np.float64],
        y_train: npt.NDArray[np.int_],
        w_train: npt.NDArray[np.float64],
        t0_train: npt.NDArray[np.datetime64],
        t1_train: npt.NDArray[np.datetime64],
        hparams: dict[str, Any],
        fold_seed: int,
    ) -> float:
        aucs: list[float] = []
        for inner_idx, (in_train_idx, in_test_idx) in enumerate(
            self._inner.split(x_train, t1_train, t0_train)
        ):
            if len(in_train_idx) == 0 or len(in_test_idx) == 0:
                raise ValueError(
                    f"inner CPCV produced an empty split at fold {inner_idx}: "
                    f"|train|={len(in_train_idx)}, |test|={len(in_test_idx)}."
                )
            y_in_test = y_train[in_test_idx]
            # AUC is undefined on a constant target - fall back to 0.5
            # (chance) for that inner fold rather than aborting the
            # whole tune() call. The caller is expected to configure
            # inner CPCV so this does not dominate, but defensive.
            if len(np.unique(y_in_test)) < 2:
                aucs.append(0.5)
                continue
            rf = RandomForestClassifier(
                **hparams,
                random_state=fold_seed,
                class_weight="balanced",
                n_jobs=1,
            )
            rf.fit(
                x_train[in_train_idx],
                y_train[in_train_idx],
                sample_weight=w_train[in_train_idx],
            )
            prob = rf.predict_proba(x_train[in_test_idx])[:, 1].astype(np.float64)
            aucs.append(fold_auc(y_in_test, prob, sample_weight=w_train[in_test_idx]))
        if not aucs:
            raise ValueError("inner CPCV yielded zero folds")
        return float(np.mean(aucs))

    def _outer_refit_and_score(
        self,
        x_train: npt.NDArray[np.float64],
        y_train: npt.NDArray[np.int_],
        w_train: npt.NDArray[np.float64],
        x_test: npt.NDArray[np.float64],
        y_test: npt.NDArray[np.int_],
        w_test: npt.NDArray[np.float64],
        hparams: dict[str, Any],
        fold_seed: int,
    ) -> float:
        if len(np.unique(y_test)) < 2:
            # OOS AUC undefined on constant y - log-neutral 0.5 matches
            # the inner fallback so the per-trial record is consistent.
            return 0.5
        rf = RandomForestClassifier(
            **hparams,
            random_state=fold_seed,
            class_weight="balanced",
            n_jobs=1,
        )
        rf.fit(x_train, y_train, sample_weight=w_train)
        prob = rf.predict_proba(x_test)[:, 1].astype(np.float64)
        return float(fold_auc(y_test, prob, sample_weight=w_test))


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _validate_inputs(
    features: MetaLabelerFeatureSet,
    y: npt.NDArray[np.int_],
    sample_weights: npt.NDArray[np.float64],
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.int_],
    npt.NDArray[np.float64],
]:
    """Shape / dtype / value contract identical to the Phase 4.3 trainer."""
    x = np.asarray(features.X, dtype=np.float64)
    if x.ndim != 2:
        raise ValueError(f"features.X must be 2-D; got shape {x.shape}")
    if x.shape[0] == 0:
        raise ValueError("cannot tune on an empty feature matrix")
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
            "y contains only one class; cannot tune a binary classifier on a degenerate target."
        )
    w_arr = np.asarray(sample_weights, dtype=np.float64)
    if w_arr.ndim != 1:
        raise ValueError(f"sample_weights must be 1-D; got shape {w_arr.shape}")
    if w_arr.shape[0] != x.shape[0]:
        raise ValueError(f"sample_weights length ({w_arr.shape[0]}) != n_samples ({x.shape[0]})")
    if not np.isfinite(w_arr).all():
        raise ValueError("sample_weights contains non-finite values (NaN/Inf)")
    if np.any(w_arr < 0.0):
        raise ValueError("sample_weights must be non-negative")
    return x, y_arr.astype(np.int_, copy=False), w_arr


def _stability_index(best_hparams_per_fold: list[dict[str, Any]]) -> float:
    """Fraction of outer folds whose best hparams match the mode.

    Hyperparameter dicts are hashed as a sorted tuple of ``(key, value)``
    pairs so ``max_depth=None`` and ordering differences are handled
    deterministically. If multiple hparam dicts tie for first place on
    frequency, the tie is broken by the first occurrence in
    ``best_hparams_per_fold`` - consistent with
    :class:`collections.Counter.most_common`.
    """
    if not best_hparams_per_fold:
        raise ValueError("cannot compute stability index on zero folds")
    keys = [tuple(sorted(hp.items())) for hp in best_hparams_per_fold]
    _modal_key, modal_count = Counter(keys).most_common(1)[0]
    return float(modal_count) / float(len(keys))
