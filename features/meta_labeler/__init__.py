"""Phase 4.3 Baseline Meta-Labeler package.

Public surface:

- :class:`MetaLabelerFeatureBuilder` - assembles the 8-feature matrix
  from labels, Phase 3 signals, bars, and a regime history.
- :class:`MetaLabelerFeatureSet` - frozen ``(X, feature_names, t0, t1)``
  bundle returned by the builder.
- :data:`FEATURE_NAMES` - canonical ordering of the 8 features per
  ADR-0005 D6.
- :class:`BaselineMetaLabeler` - trains a RandomForest primary with a
  mandatory LogisticRegression baseline under CPCV.
- :class:`BaselineTrainingResult` - frozen bundle of per-fold metrics
  plus the final fitted models.
- :func:`fold_auc`, :func:`fold_brier`, :func:`calibration_bins` -
  diagnostic helpers wrapping :mod:`sklearn.metrics`.
"""

from __future__ import annotations

from features.meta_labeler.baseline import BaselineMetaLabeler, BaselineTrainingResult
from features.meta_labeler.feature_builder import (
    FEATURE_NAMES,
    MetaLabelerFeatureBuilder,
    MetaLabelerFeatureSet,
)
from features.meta_labeler.metrics import calibration_bins, fold_auc, fold_brier

__all__ = [
    "FEATURE_NAMES",
    "BaselineMetaLabeler",
    "BaselineTrainingResult",
    "MetaLabelerFeatureBuilder",
    "MetaLabelerFeatureSet",
    "calibration_bins",
    "fold_auc",
    "fold_brier",
]
