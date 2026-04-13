"""Probability of Backtest Overfitting calculator — Phase 3.11.

Rank-based PBO from Bailey, Borwein, López de Prado, Zhu (2014).
For each CSCV (Combinatorially Symmetric Cross-Validation) fold:

1. Rank features by in-sample performance.
2. Identify the IS-best.
3. Rank features by out-of-sample performance.
4. Record whether the IS-best lands below the OOS median (logit ≤ 0).

``PBO = (# folds where IS-best is below OOS median) / (# folds)``.

PBO close to 0 → genuine edge.
PBO close to 0.5 → noise.
PBO close to 1 → severe overfitting.

ADR-0004 threshold: PBO < 0.10 → strong evidence of genuine edge.

Reference
---------
Bailey, D. H., Borwein, J. M., López de Prado, M. & Zhu, Q. J. (2014).
"The Probability of Backtest Overfitting." *J. Computational Finance*.
Equations 11 (logit) and 12 (PBO definition).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats as scipy_stats

# ADR-0004 Step 6 thresholds
_PBO_OVERFIT_THRESHOLD: float = 0.50
_PBO_ADR0004_THRESHOLD: float = 0.10

# Minimum features for stable PBO (Bailey et al. 2014 recommendation)
_MIN_FEATURES_FOR_PBO: int = 2


@dataclass(frozen=True)
class PBOResult:
    """Probability of Backtest Overfitting result.

    Reference: Bailey et al. (2014). "The Probability of Backtest
    Overfitting." J. Computational Finance.
    """

    pbo: float
    n_folds: int
    n_features: int
    rank_logits: list[float]
    is_overfit: bool  # pbo > 0.50
    passes_adr0004: bool  # pbo < 0.10


class PBOCalculator:
    """Compute rank-based PBO from IS/OOS performance per CSCV fold.

    For each fold:
    1. Rank features by IS metric → find IS-best.
    2. Rank features by OOS metric → get IS-best's OOS rank.
    3. ``ω = (rank + 0.5) / (n_features + 1)``  (keeps ω ∈ (0, 1)).
    4. ``λ = log(ω / (1 − ω))``  (logit).
    5. ``PBO = fraction(λ ≤ 0)``.

    Reference: Bailey et al. (2014), Eq. 11-12.
    """

    def __init__(
        self,
        overfit_threshold: float = _PBO_OVERFIT_THRESHOLD,
        adr0004_threshold: float = _PBO_ADR0004_THRESHOLD,
    ) -> None:
        self._overfit_threshold = overfit_threshold
        self._adr0004_threshold = adr0004_threshold

    def compute(
        self,
        is_metrics: dict[str, list[float]],
        oos_metrics: dict[str, list[float]],
    ) -> PBOResult:
        """Compute rank-based PBO from IS and OOS fold-level metrics.

        Parameters
        ----------
        is_metrics : dict
            ``{feature_name: [metric_fold_0, metric_fold_1, …]}``
            In-sample performance metric (e.g. IC or Sharpe) per fold.
        oos_metrics : dict
            Same structure for out-of-sample performance per fold.

        Returns
        -------
        PBOResult

        Raises
        ------
        ValueError
            If fewer than 2 features, mismatched keys/lengths, or
            no folds.
        """
        self._validate(is_metrics, oos_metrics)

        features = sorted(is_metrics.keys())
        n_features = len(features)
        n_folds = len(is_metrics[features[0]])

        logits: list[float] = []
        n_le_zero = 0

        for fold_i in range(n_folds):
            # IS and OOS arrays for this fold
            is_arr = np.array([is_metrics[f][fold_i] for f in features], dtype=np.float64)
            oos_arr = np.array([oos_metrics[f][fold_i] for f in features], dtype=np.float64)

            # Find IS-best
            best_is_idx = int(np.argmax(is_arr))

            # Rank OOS performance
            oos_ranks = scipy_stats.rankdata(oos_arr, method="average")
            rank_best = float(oos_ranks[best_is_idx])

            # Logit transformation (ω bounded in (0,1))
            omega = (rank_best + 0.5) / (n_features + 1)
            lam = math.log(omega / (1.0 - omega))
            logits.append(lam)

            if lam <= 0.0:
                n_le_zero += 1

        pbo = n_le_zero / n_folds
        return PBOResult(
            pbo=pbo,
            n_folds=n_folds,
            n_features=n_features,
            rank_logits=logits,
            is_overfit=pbo > self._overfit_threshold,
            passes_adr0004=pbo < self._adr0004_threshold,
        )

    @staticmethod
    def _validate(
        is_metrics: dict[str, list[float]],
        oos_metrics: dict[str, list[float]],
    ) -> None:
        """Check shapes and constraints."""
        if set(is_metrics.keys()) != set(oos_metrics.keys()):
            msg = "is_metrics and oos_metrics must have the same feature keys"
            raise ValueError(msg)
        n_features = len(is_metrics)
        if n_features < _MIN_FEATURES_FOR_PBO:
            msg = f"PBO requires at least {_MIN_FEATURES_FOR_PBO} features, got {n_features}"
            raise ValueError(msg)
        features = list(is_metrics.keys())
        n_folds = len(is_metrics[features[0]])
        if n_folds == 0:
            msg = "No folds provided — cannot compute PBO"
            raise ValueError(msg)
        for f in features:
            if len(is_metrics[f]) != n_folds:
                msg = f"is_metrics['{f}'] has {len(is_metrics[f])} folds, expected {n_folds}"
                raise ValueError(msg)
            if len(oos_metrics[f]) != n_folds:
                msg = f"oos_metrics['{f}'] has {len(oos_metrics[f])} folds, expected {n_folds}"
                raise ValueError(msg)
