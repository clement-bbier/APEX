"""Phase 4.7 — IC-weighted fusion baseline per ADR-0005 D7.

Combines activated Phase 3 signals into a single scalar
``fusion_score`` per ``(symbol, timestamp)``:

.. code-block:: text

    fusion_score(symbol, t) = Σ_i  (w_i · signal_i(symbol, t))
        where  w_i = |IC_IR_i| / Σ_j |IC_IR_j|

Weights are **frozen at construction time** from a reference IC
measurement window. They are NOT re-calibrated per ``compute`` call
— that would introduce lookahead. The construction-time contract is
enforced by :class:`ICWeightedFusionConfig.__post_init__`: weights
live on the simplex (non-negative, sum to 1.0 within ``1e-9``).

Per PHASE_4_SPEC §3.7, this module is strictly additive. It ships
library code + unit tests only; the streaming S04 wiring is Phase 5
work (tracked by issue #123) and explicitly out of scope here.

References:
    ADR-0005 D7 — Fusion Engine: IC-weighted baseline.
    PHASE_4_SPEC §3.7.
    Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio
    Management* (2nd ed.), McGraw-Hill, §4 — IC-IR framework.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from features.ic.report import ICReport
    from features.integration.config import FeatureActivationConfig

__all__ = ["ICWeightedFusion", "ICWeightedFusionConfig"]

# Sum-to-one tolerance. ``from_ic_report`` does an explicit
# re-normalisation after float summation so Σ w_i is bit-close to
# 1.0; the tolerance exists so direct-construction callers (tests,
# downstream tooling) can pass rationals like ``(0.1, 0.2, 0.7)``
# without float-rounding false negatives.
_SIMPLEX_SUM_TOL: float = 1e-9

_OUTPUT_COLUMNS: tuple[str, str, str] = ("timestamp", "symbol", "fusion_score")


# ----------------------------------------------------------------------
# Config — frozen at construction
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ICWeightedFusionConfig:
    """Frozen IC-weight configuration for the fusion engine.

    Attributes:
        feature_names: Ordered tuple of signal column names. Order
            is significant: it determines the positional mapping to
            ``weights`` and the expected schema on
            :meth:`ICWeightedFusion.compute` input. ``from_ic_report``
            produces names sorted ascending so the order is
            deterministic regardless of ``ic_report`` insertion order.
        weights: Same-length tuple of non-negative floats summing to
            1.0 within ``1e-9``. Position ``i`` is the weight
            associated with ``feature_names[i]``.

    Raises:
        ValueError: On any violation of the simplex contract.
    """

    feature_names: tuple[str, ...]
    weights: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.feature_names) == 0:
            raise ValueError("feature_names must contain at least one entry")
        if len(self.feature_names) != len(self.weights):
            raise ValueError(
                f"feature_names and weights length mismatch: "
                f"{len(self.feature_names)} vs {len(self.weights)}"
            )
        if any(not isinstance(n, str) or not n for n in self.feature_names):
            raise ValueError("feature_names must be non-empty strings")
        dupes = [name for name, count in Counter(self.feature_names).items() if count > 1]
        if dupes:
            raise ValueError(f"feature_names contain duplicates: {sorted(dupes)}")
        if any(not math.isfinite(w) for w in self.weights):
            raise ValueError("weights must be finite floats")
        if any(w < 0.0 for w in self.weights):
            raise ValueError(f"weights must be non-negative (simplex); got {list(self.weights)}")
        total = math.fsum(self.weights)
        if abs(total - 1.0) > _SIMPLEX_SUM_TOL:
            raise ValueError(f"weights must sum to 1.0 (tol {_SIMPLEX_SUM_TOL}); got sum={total!r}")

    # ------------------------------------------------------------------
    # Constructor helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_ic_report(
        cls,
        ic_report: ICReport,
        activation_config: FeatureActivationConfig,
    ) -> ICWeightedFusionConfig:
        """Build an IC-weight config from a Phase 3 artifact pair.

        Reads ``ic_report.results`` and ``activation_config
        .activated_features``; computes
        ``w_i = |IC_IR_i| / Σ_j |IC_IR_j|`` over the intersection of
        the two sets. Entries of ``ic_report`` that are not in
        ``activated_features`` are silently dropped (Phase 3.12
        rejected them); an ``activated_features`` entry missing from
        ``ic_report`` is a hard error (incompatible artifacts).

        Feature ordering is locked to ``sorted(activated_features)``
        so the resulting config is deterministic regardless of
        ``ic_report`` insertion order.

        Args:
            ic_report: Phase 3.3 IC report.
            activation_config: Phase 3.12 activation decisions.

        Returns:
            Fully validated :class:`ICWeightedFusionConfig`.

        Raises:
            ValueError: If ``activated_features`` references a
                feature missing from ``ic_report``, if a feature
                name appears in ``ic_report`` with multiple entries,
                or if the summed ``|IC_IR|`` over the kept set is
                zero (degenerate — no uniform fallback).
        """
        activated = set(activation_config.activated_features)
        if not activated:
            raise ValueError("activation_config has no activated features")

        # Walk the report and build a name → |IC_IR| map, guarding
        # against duplicate entries per feature.
        abs_ir_by_name: dict[str, float] = {}
        for result in ic_report.results:
            name = result.feature_name
            if name is None:
                # Legacy ICResult with no feature_name cannot be
                # disambiguated; ignore silently rather than error —
                # we only care about activated entries.
                continue
            if name not in activated:
                continue
            if name in abs_ir_by_name:
                raise ValueError(
                    f"ic_report contains duplicate entries for activated "
                    f"feature {name!r}; pre-filter to a single horizon "
                    f"before building the fusion config"
                )
            abs_ir_by_name[name] = abs(float(result.ic_ir))

        missing = sorted(activated - abs_ir_by_name.keys())
        if missing:
            raise ValueError(
                f"ic_report is missing activated features: {missing}. "
                f"Phase 3.3 and Phase 3.12 artifacts are out of sync."
            )

        total = math.fsum(abs_ir_by_name.values())
        if total <= 0.0:
            raise ValueError(
                "Σ |IC_IR_i| over the activated set is zero; cannot build "
                "IC-weighted fusion (no silent uniform fallback per spec)"
            )

        feature_names = tuple(sorted(abs_ir_by_name))
        raw_weights = tuple(abs_ir_by_name[n] / total for n in feature_names)

        # Re-normalise after float division so Σ == 1.0 bit-close.
        renorm = math.fsum(raw_weights)
        weights = tuple(w / renorm for w in raw_weights)
        return cls(feature_names=feature_names, weights=weights)


# ----------------------------------------------------------------------
# Fusion engine
# ----------------------------------------------------------------------


class ICWeightedFusion:
    """Apply a frozen :class:`ICWeightedFusionConfig` to a signals frame.

    Stateless relative to ``compute`` inputs — every call re-reads the
    frozen config and produces the scalar fusion score via a single
    polars expression.
    """

    def __init__(self, config: ICWeightedFusionConfig) -> None:
        self._config = config

    @property
    def config(self) -> ICWeightedFusionConfig:
        """Return the frozen config (for introspection / reporting)."""
        return self._config

    def compute(self, signals: pl.DataFrame) -> pl.DataFrame:
        """Compute the IC-weighted fusion score per ``(timestamp, symbol)``.

        Args:
            signals: Polars DataFrame with columns ``timestamp``,
                ``symbol``, and one Float-convertible column per
                :attr:`ICWeightedFusionConfig.feature_names`. Extra
                columns are tolerated. Row order is preserved.

        Returns:
            DataFrame with exactly three columns in order:
            ``[timestamp, symbol, fusion_score]``. ``fusion_score``
            is ``pl.Float64``.

        Raises:
            ValueError: If any required column is missing, if any
                value in a feature column is null / NaN, or if the
                input has zero rows (no silent empty output).
        """
        cfg = self._config
        required = ("timestamp", "symbol", *cfg.feature_names)
        missing = [c for c in required if c not in signals.columns]
        if missing:
            raise ValueError(
                f"signals DataFrame is missing required columns: {missing}. "
                f"Expected at least: {list(required)}"
            )
        if signals.height == 0:
            raise ValueError(
                "signals DataFrame is empty (0 rows); refusing to emit a silent empty fusion output"
            )

        # Reject nulls / NaNs in any feature column explicitly. Polars
        # treats null and NaN separately; both are fatal here. NaN
        # checks are only valid for floating dtypes, while integer
        # columns are still acceptable because they are cast to
        # Float64 during the weighted sum below.
        for col in cfg.feature_names:
            null_count = int(signals.select(pl.col(col).is_null().sum()).item())
            if null_count > 0:
                raise ValueError(
                    f"signals column {col!r} contains {null_count} null "
                    f"value(s); Phase 3 pipeline must materialise before "
                    f"fusion (no silent zero-fill)"
                )
            col_dtype = signals.schema[col]
            if col_dtype in (pl.Float32, pl.Float64):
                nan_count = int(signals.select(pl.col(col).is_nan().sum()).item())
                if nan_count > 0:
                    raise ValueError(
                        f"signals column {col!r} contains {nan_count} NaN "
                        f"value(s); Phase 3 pipeline must materialise before "
                        f"fusion (no silent zero-fill)"
                    )

        # Single polars expression: Σ_i w_i · col(f_i). We explicitly
        # cast each feature column to Float64 to defend against
        # Float32-typed inputs (the sum would silently widen, but
        # this makes the contract explicit).
        weighted_terms = [
            pl.col(name).cast(pl.Float64) * float(w)
            for name, w in zip(cfg.feature_names, cfg.weights, strict=True)
        ]
        # ``pl.sum_horizontal`` sums a list of expressions element-wise.
        fusion_expr = pl.sum_horizontal(weighted_terms).alias("fusion_score")

        return signals.select(
            pl.col("timestamp"),
            pl.col("symbol"),
            fusion_expr.cast(pl.Float64),
        ).select(list(_OUTPUT_COLUMNS))
