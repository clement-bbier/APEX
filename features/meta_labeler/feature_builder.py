"""Phase 4.3 - Feature matrix builder for the Baseline Meta-Labeler.

Assembles the **8-feature** contextual matrix specified in ADR-0005 D6
and PHASE_4_SPEC section 3.3 from three inputs produced earlier in the
pipeline:

- ``labels``   - the Triple Barrier output (``t0``, ``t1``, ``binary_target``).
- ``signals``  - the three authorized Phase 3 signals (``gex_signal``,
  ``har_rv_signal``, ``ofi_signal``), bar-indexed.
- ``bars``     - the underlying close series (for realized vol).
- ``regime_history`` - the S03 regime snapshots (held on the builder).

Anti-leakage contract (strict ``<`` on everything except ``t0``-derived
time encodings):

- **Features 1-3 (Phase 3 signals)** - joined via ``asof`` *strictly*
  before ``t0_i`` (``strategy="backward"`` with tolerance "just-before").
- **Features 4-5 (regime)** - ``regime_history`` row with largest
  ``timestamp <= t0_i`` (inclusive, because regime at ``t0`` *is* the
  state the sample enters with). Fail-loud if no regime snapshot is
  available at or before ``t0_i``.
- **Feature 6 (realized vol 28d)** - per-bar log-returns computed from
  ``bars`` where we take bars with ``timestamp <= t0_i - 1 bar``.
  Operationally: select the last ``realized_vol_window + 1`` bars
  strictly before ``t0_i``, compute log-returns, then standard deviation.
  Fail-loud if fewer than ``realized_vol_window`` usable returns exist.
- **Features 7-8 (time encodings)** - ``sin(2pi * hour/24)`` and
  ``sin(2pi * weekday/7)`` of ``t0_i``. No look-ahead possible.

All outputs are aligned and returned as a :class:`MetaLabelerFeatureSet`
whose ``X`` array is ``(n_samples, 8)`` ``float64``, ready to feed
:class:`~features.meta_labeler.baseline.BaselineMetaLabeler`.

References:
    ADR-0005 D6 - feature set.
    PHASE_4_SPEC section 3.3 - feature builder API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import numpy.typing as npt
import polars as pl

from core.models.regime import TrendRegime, VolRegime
from features.integration.config import FeatureActivationConfig

__all__ = [
    "FEATURE_NAMES",
    "MetaLabelerFeatureBuilder",
    "MetaLabelerFeatureSet",
]

# ADR-0005 D6 canonical ordering - MUST match the column order of
# :attr:`MetaLabelerFeatureSet.X`. Do not alphabetize: downstream
# ``feature_importances_`` arrays are positional.
FEATURE_NAMES: tuple[str, ...] = (
    "gex_signal",
    "har_rv_signal",
    "ofi_signal",
    "regime_vol_code",
    "regime_trend_code",
    "realized_vol_28d",
    "hour_of_day_sin",
    "day_of_week_sin",
)

_PHASE3_SIGNAL_NAMES: frozenset[str] = frozenset({"gex_signal", "har_rv_signal", "ofi_signal"})

# Ordinal encodings per PHASE_4_SPEC section 3.3.
_VOL_CODE: dict[str, int] = {
    VolRegime.LOW.value: 0,
    VolRegime.NORMAL.value: 1,
    VolRegime.HIGH.value: 2,
    VolRegime.CRISIS.value: 3,
}
_TREND_CODE: dict[str, int] = {
    TrendRegime.TRENDING_DOWN.value: -1,
    TrendRegime.RANGING.value: 0,
    TrendRegime.TRENDING_UP.value: 1,
    # BREAKOUT is reported by S03 but not explicitly listed in ADR-0005 D6.
    # We treat it as a strong upward bias (+1) by convention; this keeps
    # the encoding ordinal without inventing a new level. Documented here
    # so the Phase 4.5 DSR audit does not flag it as a silent mapping.
    TrendRegime.BREAKOUT.value: 1,
}


@dataclass(frozen=True)
class MetaLabelerFeatureSet:
    """Frozen, fully-aligned feature matrix for the Baseline Meta-Labeler.

    Attributes:
        X: Dense float64 matrix, shape ``(n_samples, 8)``. Column order
            matches :data:`FEATURE_NAMES`.
        feature_names: Canonical feature-name tuple; always equal to
            :data:`FEATURE_NAMES` (bundled for self-describing consumers).
        t0: Per-sample label-start timestamps, ``datetime64[us]`` UTC.
        t1: Per-sample label-end timestamps, ``datetime64[us]`` UTC.
    """

    X: npt.NDArray[np.float64]
    feature_names: tuple[str, ...]
    t0: npt.NDArray[np.datetime64]
    t1: npt.NDArray[np.datetime64]

    def __post_init__(self) -> None:
        if self.X.ndim != 2:
            raise ValueError(f"X must be 2-D; got shape {self.X.shape}")
        if self.X.dtype != np.float64:
            raise ValueError(
                f"X must be np.float64 (the downstream sklearn trainers expect "
                f"a contiguous float64 matrix); got dtype {self.X.dtype}"
            )
        if self.X.shape[1] != len(FEATURE_NAMES):
            raise ValueError(
                f"X has {self.X.shape[1]} columns but expected {len(FEATURE_NAMES)} "
                f"(ADR-0005 D6 contract)"
            )
        if self.X.shape[0] != len(self.t0) or self.X.shape[0] != len(self.t1):
            raise ValueError(
                f"X/t0/t1 lengths disagree: "
                f"X={self.X.shape[0]}, t0={len(self.t0)}, t1={len(self.t1)}"
            )
        if self.feature_names != FEATURE_NAMES:
            raise ValueError(f"feature_names must equal FEATURE_NAMES; got {self.feature_names}")
        # ``t0`` / ``t1`` must be datetime64 arrays so downstream CPCV (which
        # calls ``searchsorted`` on them) has comparable ordering semantics.
        if self.t0.dtype.kind != "M":
            raise ValueError(f"t0 must be a datetime64 array; got dtype {self.t0.dtype}")
        if self.t1.dtype.kind != "M":
            raise ValueError(f"t1 must be a datetime64 array; got dtype {self.t1.dtype}")


def _validate_utc_column(df: pl.DataFrame, col: str, where: str) -> None:
    if col not in df.columns:
        raise ValueError(f"{where} missing required column: {col!r}")
    dtype = df.schema[col]
    if dtype != pl.Datetime("us", "UTC"):
        raise ValueError(
            f"{where}.{col} must be Datetime('us', 'UTC'); got {dtype}. "
            "Phase 4.3 requires UTC-aware timestamps."
        )


def _encode_vol(value: str | None, t0: datetime) -> int:
    if value is None:
        raise ValueError(f"regime_history has null vol_regime at or before t0={t0}")
    if value not in _VOL_CODE:
        raise ValueError(
            f"Unknown vol_regime value {value!r} at t0={t0}; expected one of {sorted(_VOL_CODE)}"
        )
    return _VOL_CODE[value]


def _encode_trend(value: str | None, t0: datetime) -> int:
    if value is None:
        raise ValueError(f"regime_history has null trend_regime at or before t0={t0}")
    if value not in _TREND_CODE:
        raise ValueError(
            f"Unknown trend_regime value {value!r} at t0={t0}; "
            f"expected one of {sorted(_TREND_CODE)}"
        )
    return _TREND_CODE[value]


class MetaLabelerFeatureBuilder:
    """Build the :class:`MetaLabelerFeatureSet` from aligned inputs.

    The builder is stateless after ``__init__``: every ``build()`` call is
    independent and safe to invoke concurrently from CPCV orchestration
    code (there is no hidden cache).

    Parameters
    ----------
    activation_config:
        Phase 3.12 feature activation report loaded as
        :class:`FeatureActivationConfig`. ``build()`` fails loud if the
        three required Phase 3 signals
        (``gex_signal``, ``har_rv_signal``, ``ofi_signal``) are not all
        flagged as activated - Phase 4 MVP enforces the 3.12 decision
        contract.
    regime_history:
        Polars DataFrame with columns ``timestamp`` (UTC), ``vol_regime``
        (StrEnum value), ``trend_regime`` (StrEnum value). Sorted
        strictly monotonic on ``timestamp``.
    realized_vol_window:
        Number of per-bar log-returns to use for the rolling standard
        deviation (feature 6). Default ``28`` per ADR-0005 D6.
    """

    def __init__(
        self,
        activation_config: FeatureActivationConfig,
        regime_history: pl.DataFrame,
        realized_vol_window: int = 28,
    ) -> None:
        if realized_vol_window < 2:
            raise ValueError(f"realized_vol_window must be >= 2; got {realized_vol_window}")

        missing = _PHASE3_SIGNAL_NAMES - activation_config.activated_features
        if missing:
            raise ValueError(
                f"FeatureActivationConfig is missing required Phase 3 signals: {sorted(missing)}. "
                "Phase 4.3 requires gex_signal, har_rv_signal, and ofi_signal to be activated."
            )

        self._regime = self._validate_regime_history(regime_history)
        self._realized_vol_window = realized_vol_window

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        labels: pl.DataFrame,
        signals: pl.DataFrame,
        bars: pl.DataFrame,
    ) -> MetaLabelerFeatureSet:
        """Build the ``(n_samples, 8)`` feature matrix.

        Parameters
        ----------
        labels:
            Triple Barrier output. Required columns: ``t0``, ``t1``
            (UTC Datetime). Values outside ``[regime_history.min,
            regime_history.max]`` still produce features as long as a
            regime snapshot exists at or before ``t0_i``; otherwise the
            method fails loud.
        signals:
            Bar-indexed Phase 3 signal frame. Required columns:
            ``timestamp`` (UTC Datetime), ``gex_signal``,
            ``har_rv_signal``, ``ofi_signal``. No nulls allowed.
        bars:
            Bar series for realized vol. Required columns:
            ``timestamp`` (UTC Datetime), ``close`` (strictly positive).

        Returns
        -------
        MetaLabelerFeatureSet
            Dense float64 feature matrix plus aligned metadata.

        Raises
        ------
        ValueError
            On any contract violation - missing columns, wrong dtypes,
            orphan ``t0``, regime snapshot unavailable at or before
            ``t0_i``, or insufficient bar history for realized vol.
        """
        self._validate_labels(labels)
        self._validate_signals(signals)
        self._validate_bars(bars)

        n = len(labels)
        if n == 0:
            empty_x = np.empty((0, len(FEATURE_NAMES)), dtype=np.float64)
            empty_ts = np.array([], dtype="datetime64[us]")
            return MetaLabelerFeatureSet(
                X=empty_x,
                feature_names=FEATURE_NAMES,
                t0=empty_ts,
                t1=empty_ts,
            )

        # Columns 1-3: Phase 3 signals, asof-backward strict before t0.
        signals_mat = self._phase3_signals(labels, signals)

        # Columns 4-5: regime ordinal encoding.
        regime_mat = self._regime_codes(labels)

        # Column 6: realized vol 28-bar, window strictly before t0.
        realized_vol_col = self._realized_vol(labels, bars)

        # Columns 7-8: cyclical time encoding of t0 itself.
        cyclical_mat = self._cyclical_time(labels)

        x = np.hstack(
            [
                signals_mat,
                regime_mat.astype(np.float64),
                realized_vol_col.reshape(-1, 1),
                cyclical_mat,
            ]
        )
        if x.shape != (n, len(FEATURE_NAMES)):
            raise ValueError(
                f"internal shape error: expected ({n}, {len(FEATURE_NAMES)}), got {x.shape}"
            )
        if not np.isfinite(x).all():
            bad = np.argwhere(~np.isfinite(x))[0]
            raise ValueError(
                f"non-finite value in feature matrix at row={bad[0]}, col={FEATURE_NAMES[bad[1]]}"
            )

        t0_np = labels["t0"].to_numpy().astype("datetime64[us]")
        t1_np = labels["t1"].to_numpy().astype("datetime64[us]")
        return MetaLabelerFeatureSet(
            X=x,
            feature_names=FEATURE_NAMES,
            t0=t0_np,
            t1=t1_np,
        )

    @property
    def realized_vol_window(self) -> int:
        """The rolling window size used for feature 6."""
        return self._realized_vol_window

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_regime_history(df: pl.DataFrame) -> pl.DataFrame:
        _validate_utc_column(df, "timestamp", "regime_history")
        for col in ("vol_regime", "trend_regime"):
            if col not in df.columns:
                raise ValueError(f"regime_history missing required column: {col!r}")
        if len(df) == 0:
            raise ValueError("regime_history is empty; cannot project any t0 to a regime snapshot")

        ts_np = df["timestamp"].to_numpy().astype("datetime64[us]")
        if len(ts_np) > 1 and not np.all(ts_np[1:] > ts_np[:-1]):
            raise ValueError("regime_history.timestamp must be strictly monotonic increasing")

        return df.select(["timestamp", "vol_regime", "trend_regime"])

    @staticmethod
    def _validate_labels(labels: pl.DataFrame) -> None:
        _validate_utc_column(labels, "t0", "labels")
        _validate_utc_column(labels, "t1", "labels")
        if len(labels) == 0:
            return
        t0_np = labels["t0"].to_numpy().astype("datetime64[us]")
        t1_np = labels["t1"].to_numpy().astype("datetime64[us]")
        if np.any(t1_np < t0_np):
            bad = int(np.argmax(t1_np < t0_np))
            raise ValueError(
                f"labels.t1 < labels.t0 at row {bad}: t0={t0_np[bad]}, t1={t1_np[bad]}"
            )

    @staticmethod
    def _validate_signals(signals: pl.DataFrame) -> None:
        _validate_utc_column(signals, "timestamp", "signals")
        for col in _PHASE3_SIGNAL_NAMES:
            if col not in signals.columns:
                raise ValueError(f"signals missing required column: {col!r}")
            if signals[col].null_count() > 0:
                raise ValueError(f"signals.{col} contains nulls; Phase 4.3 forbids silent ffill")
        if len(signals) == 0:
            return
        ts_np = signals["timestamp"].to_numpy().astype("datetime64[us]")
        if len(ts_np) > 1 and not np.all(ts_np[1:] > ts_np[:-1]):
            raise ValueError("signals.timestamp must be strictly monotonic increasing")

    @staticmethod
    def _validate_bars(bars: pl.DataFrame) -> None:
        _validate_utc_column(bars, "timestamp", "bars")
        if "close" not in bars.columns:
            raise ValueError("bars missing required column: 'close'")
        if bars["close"].null_count() > 0:
            raise ValueError("bars.close contains nulls; Phase 4.3 forbids silent ffill")
        if len(bars) == 0:
            return
        ts_np = bars["timestamp"].to_numpy().astype("datetime64[us]")
        if len(ts_np) > 1 and not np.all(ts_np[1:] > ts_np[:-1]):
            raise ValueError("bars.timestamp must be strictly monotonic increasing")
        close_np = bars["close"].to_numpy().astype(np.float64)
        if np.any(close_np <= 0.0) or not np.isfinite(close_np).all():
            raise ValueError("bars.close must be strictly positive and finite")

    def _phase3_signals(
        self, labels: pl.DataFrame, signals: pl.DataFrame
    ) -> npt.NDArray[np.float64]:
        """Join Phase 3 signals strictly before each ``t0_i``.

        We sidestep ``polars.join_asof`` edge cases by computing the join
        index ourselves via ``np.searchsorted`` with ``side='left'``:
        the insertion index points to the first signal row whose
        timestamp is ``>= t0_i``, so ``idx - 1`` is the last row
        ``strictly before`` ``t0_i``. A negative ``idx - 1`` means no
        signal row exists before ``t0_i`` and we fail loudly.
        """
        n = len(labels)
        if n == 0:
            return np.empty((0, 3), dtype=np.float64)

        sig_ts = signals["timestamp"].to_numpy().astype("datetime64[us]")
        if len(sig_ts) == 0:
            raise ValueError("signals is empty but labels is not; cannot build Phase 3 columns")

        t0_np = labels["t0"].to_numpy().astype("datetime64[us]")
        # searchsorted returns an int64 array; side='left' => idx is the
        # insertion index preserving sort order, so idx-1 is the last
        # timestamp STRICTLY less than t0 (which is what we need).
        idx = np.searchsorted(sig_ts, t0_np, side="left").astype(np.int64) - 1
        if np.any(idx < 0):
            bad = int(np.argmax(idx < 0))
            raise ValueError(
                f"no Phase 3 signal row strictly before t0={t0_np[bad]} "
                "(signals must include history ending before the earliest label)"
            )

        gex = signals["gex_signal"].to_numpy().astype(np.float64)[idx]
        har = signals["har_rv_signal"].to_numpy().astype(np.float64)[idx]
        ofi = signals["ofi_signal"].to_numpy().astype(np.float64)[idx]
        return np.column_stack([gex, har, ofi]).astype(np.float64)

    def _regime_codes(self, labels: pl.DataFrame) -> npt.NDArray[np.int64]:
        """Encode (vol, trend) at ``t0_i`` inclusive via asof-backward."""
        n = len(labels)
        if n == 0:
            return np.empty((0, 2), dtype=np.int64)

        reg_ts = self._regime["timestamp"].to_numpy().astype("datetime64[us]")
        t0_np = labels["t0"].to_numpy().astype("datetime64[us]")

        # side='right' => insertion keeps sort order, so idx-1 is the
        # last regime row with timestamp <= t0_i (inclusive).
        idx = np.searchsorted(reg_ts, t0_np, side="right").astype(np.int64) - 1
        if np.any(idx < 0):
            bad = int(np.argmax(idx < 0))
            raise ValueError(
                f"regime_history has no snapshot at or before t0={t0_np[bad]}; "
                "extend the regime history or drop the offending labels"
            )

        vol_vals = self._regime["vol_regime"].to_list()
        trend_vals = self._regime["trend_regime"].to_list()
        vol_codes = np.empty(n, dtype=np.int64)
        trend_codes = np.empty(n, dtype=np.int64)
        for i in range(n):
            t0_i = labels["t0"][i]
            vol_codes[i] = _encode_vol(vol_vals[int(idx[i])], t0_i)
            trend_codes[i] = _encode_trend(trend_vals[int(idx[i])], t0_i)
        return np.column_stack([vol_codes, trend_codes]).astype(np.int64)

    def _realized_vol(self, labels: pl.DataFrame, bars: pl.DataFrame) -> npt.NDArray[np.float64]:
        """Compute per-label rolling realized volatility strictly before t0.

        For each label we take the bars whose timestamp is strictly less
        than ``t0_i``, keep the last ``realized_vol_window + 1`` of them,
        compute consecutive log-returns, then the standard deviation
        (``ddof=0``). If fewer than ``realized_vol_window`` log-returns
        are available, we fail loud.
        """
        n = len(labels)
        if n == 0:
            return np.empty((0,), dtype=np.float64)

        bars_ts = bars["timestamp"].to_numpy().astype("datetime64[us]")
        bars_close = bars["close"].to_numpy().astype(np.float64)
        if len(bars_ts) == 0:
            raise ValueError("bars is empty but labels is not; cannot compute realized vol")

        t0_np = labels["t0"].to_numpy().astype("datetime64[us]")
        # side='left' => idx is the first bar with timestamp >= t0_i, so
        # bars[:idx] is STRICTLY before t0_i.
        idx = np.searchsorted(bars_ts, t0_np, side="left").astype(np.int64)

        out = np.empty(n, dtype=np.float64)
        w = self._realized_vol_window
        for i in range(n):
            end = int(idx[i])
            # Need w+1 closes to build w log-returns.
            start = end - (w + 1)
            if start < 0:
                raise ValueError(
                    f"insufficient bar history before t0={t0_np[i]}: need {w + 1} bars, have {end}"
                )
            close_window = bars_close[start:end]
            # Log-returns: diff of log(close).
            log_ret = np.diff(np.log(close_window))
            if len(log_ret) != w:
                raise ValueError(
                    f"internal: expected {w} log-returns at sample {i}, got {len(log_ret)}"
                )
            out[i] = float(np.std(log_ret, ddof=0))
        return out

    @staticmethod
    def _cyclical_time(labels: pl.DataFrame) -> npt.NDArray[np.float64]:
        """Sin-encoded hour-of-day and day-of-week of ``t0_i``.

        We use only the sine component per ADR-0005 D6 MVP (8 total
        features). The cosine pair can be added in Phase 4.4 ablation.
        """
        n = len(labels)
        if n == 0:
            return np.empty((0, 2), dtype=np.float64)

        hours = np.array([t.hour for t in labels["t0"].to_list()], dtype=np.float64)
        weekdays = np.array([t.weekday() for t in labels["t0"].to_list()], dtype=np.float64)
        hod = np.sin(2.0 * np.pi * hours / 24.0)
        dow = np.sin(2.0 * np.pi * weekdays / 7.0)
        return np.column_stack([hod, dow]).astype(np.float64)
