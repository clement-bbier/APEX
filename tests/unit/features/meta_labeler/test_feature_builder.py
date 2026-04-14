"""Unit tests for :mod:`features.meta_labeler.feature_builder`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import numpy as np
import polars as pl
import pytest

from features.integration.config import FeatureActivationConfig
from features.meta_labeler.feature_builder import (
    FEATURE_NAMES,
    MetaLabelerFeatureBuilder,
    MetaLabelerFeatureSet,
)

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

BAR_LEN = timedelta(minutes=5)
T_EPOCH = datetime(2025, 1, 6, 14, 30, tzinfo=UTC)  # Monday 14:30 UTC


def _ts(i: int) -> datetime:
    return T_EPOCH + i * BAR_LEN


def _make_activation_config() -> FeatureActivationConfig:
    return FeatureActivationConfig(
        activated_features=frozenset({"gex_signal", "har_rv_signal", "ofi_signal"}),
        rejected_features=frozenset(),
        generated_at=T_EPOCH,
        pbo_of_final_set=0.05,
    )


def _make_bars(n: int, seed: int = 0) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    # log-normal close path: log-returns ~ N(0, 0.001)
    logret = rng.normal(0.0, 0.001, size=n)
    close = 100.0 * np.exp(np.cumsum(logret))
    return pl.DataFrame(
        {
            "timestamp": [_ts(i) for i in range(n)],
            "close": close.tolist(),
        },
        schema={"timestamp": pl.Datetime("us", "UTC"), "close": pl.Float64},
    )


def _make_signals(n: int, seed: int = 1) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    return pl.DataFrame(
        {
            "timestamp": [_ts(i) for i in range(n)],
            "gex_signal": rng.normal(0.0, 1.0, size=n).tolist(),
            "har_rv_signal": rng.normal(0.0, 1.0, size=n).tolist(),
            "ofi_signal": rng.normal(0.0, 1.0, size=n).tolist(),
        },
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "gex_signal": pl.Float64,
            "har_rv_signal": pl.Float64,
            "ofi_signal": pl.Float64,
        },
    )


def _make_regime_history(starts: list[int], vol: list[str], trend: list[str]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "timestamp": [_ts(i) for i in starts],
            "vol_regime": vol,
            "trend_regime": trend,
        },
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "vol_regime": pl.Utf8,
            "trend_regime": pl.Utf8,
        },
    )


def _make_labels(event_indices: list[int], horizon: int = 10) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "t0": [_ts(i) for i in event_indices],
            "t1": [_ts(i + horizon) for i in event_indices],
            "binary_target": [i % 2 for i in event_indices],
        },
        schema={
            "t0": pl.Datetime("us", "UTC"),
            "t1": pl.Datetime("us", "UTC"),
            "binary_target": pl.Int8,
        },
    )


# --------------------------------------------------------------------
# Group A: happy-path shape and alignment
# --------------------------------------------------------------------


def test_feature_set_has_expected_shape_and_feature_names() -> None:
    n_bars = 200
    event_ids = [40, 60, 80, 100, 120]
    labels = _make_labels(event_ids)
    builder = MetaLabelerFeatureBuilder(
        activation_config=_make_activation_config(),
        regime_history=_make_regime_history(
            starts=[0, 50], vol=["normal", "high"], trend=["ranging", "trending_up"]
        ),
        realized_vol_window=28,
    )
    fs = builder.build(labels, _make_signals(n_bars), _make_bars(n_bars))
    assert isinstance(fs, MetaLabelerFeatureSet)
    assert fs.X.shape == (len(event_ids), 8)
    assert fs.feature_names == FEATURE_NAMES
    assert fs.X.dtype == np.float64
    assert len(fs.t0) == len(event_ids)
    assert len(fs.t1) == len(event_ids)


def test_empty_labels_returns_empty_feature_matrix() -> None:
    builder = MetaLabelerFeatureBuilder(
        activation_config=_make_activation_config(),
        regime_history=_make_regime_history([0], ["normal"], ["ranging"]),
    )
    labels = _make_labels([])
    fs = builder.build(labels, _make_signals(100), _make_bars(100))
    assert fs.X.shape == (0, 8)
    assert len(fs.t0) == 0
    assert len(fs.t1) == 0


# --------------------------------------------------------------------
# Group B: regime as-of encoding (feature columns 4-5)
# --------------------------------------------------------------------


def test_regime_asof_at_t0_is_inclusive() -> None:
    # Regime snapshot lands exactly at t0: should be picked up.
    builder = MetaLabelerFeatureBuilder(
        activation_config=_make_activation_config(),
        regime_history=_make_regime_history(starts=[50], vol=["crisis"], trend=["trending_down"]),
    )
    labels = _make_labels([50])
    fs = builder.build(labels, _make_signals(200), _make_bars(200))
    vol_col = FEATURE_NAMES.index("regime_vol_code")
    trend_col = FEATURE_NAMES.index("regime_trend_code")
    assert fs.X[0, vol_col] == 3.0  # CRISIS
    assert fs.X[0, trend_col] == -1.0  # TRENDING_DOWN


def test_regime_asof_picks_last_snapshot_before_t0() -> None:
    builder = MetaLabelerFeatureBuilder(
        activation_config=_make_activation_config(),
        regime_history=_make_regime_history(
            starts=[0, 30, 80],
            vol=["low", "high", "crisis"],
            trend=["ranging", "trending_up", "trending_down"],
        ),
    )
    # Event at bar 50: expect regime taken from snapshot at bar 30 (high / up).
    labels = _make_labels([50])
    fs = builder.build(labels, _make_signals(200), _make_bars(200))
    vol_col = FEATURE_NAMES.index("regime_vol_code")
    trend_col = FEATURE_NAMES.index("regime_trend_code")
    assert fs.X[0, vol_col] == 2.0  # HIGH
    assert fs.X[0, trend_col] == 1.0  # TRENDING_UP


def test_regime_missing_at_t0_fails_loud() -> None:
    builder = MetaLabelerFeatureBuilder(
        activation_config=_make_activation_config(),
        regime_history=_make_regime_history([100], ["normal"], ["ranging"]),
    )
    labels = _make_labels([40])  # event BEFORE the only regime snapshot
    with pytest.raises(ValueError, match=r"no snapshot at or before"):
        builder.build(labels, _make_signals(200), _make_bars(200))


def test_unknown_vol_regime_value_fails_loud() -> None:
    regime = pl.DataFrame(
        {
            "timestamp": [_ts(0)],
            "vol_regime": ["HYPERCRISIS"],
            "trend_regime": ["ranging"],
        },
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "vol_regime": pl.Utf8,
            "trend_regime": pl.Utf8,
        },
    )
    builder = MetaLabelerFeatureBuilder(_make_activation_config(), regime)
    labels = _make_labels([40])
    with pytest.raises(ValueError, match=r"Unknown vol_regime value 'HYPERCRISIS'"):
        builder.build(labels, _make_signals(200), _make_bars(200))


# --------------------------------------------------------------------
# Group C: Phase 3 signals - strictly before t0
# --------------------------------------------------------------------


def test_phase3_signals_strictly_before_t0() -> None:
    # Build a signals frame where the signal at bar i is equal to i.
    n = 200
    signals = pl.DataFrame(
        {
            "timestamp": [_ts(i) for i in range(n)],
            "gex_signal": [float(i) for i in range(n)],
            "har_rv_signal": [float(i) + 0.5 for i in range(n)],
            "ofi_signal": [float(i) - 0.5 for i in range(n)],
        },
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "gex_signal": pl.Float64,
            "har_rv_signal": pl.Float64,
            "ofi_signal": pl.Float64,
        },
    )
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
    )
    labels = _make_labels([50])
    fs = builder.build(labels, signals, _make_bars(n))
    # strictly before t0=50 => pick bar 49
    gex_col = FEATURE_NAMES.index("gex_signal")
    har_col = FEATURE_NAMES.index("har_rv_signal")
    ofi_col = FEATURE_NAMES.index("ofi_signal")
    assert fs.X[0, gex_col] == 49.0
    assert fs.X[0, har_col] == 49.5
    assert fs.X[0, ofi_col] == 48.5


def test_phase3_signals_missing_before_earliest_t0_fails_loud() -> None:
    # Signal history begins at bar 100, event at bar 40 cannot find a
    # signal strictly before its t0.
    n = 200
    signals_small = pl.DataFrame(
        {
            "timestamp": [_ts(i) for i in range(100, n)],
            "gex_signal": [0.0] * (n - 100),
            "har_rv_signal": [0.0] * (n - 100),
            "ofi_signal": [0.0] * (n - 100),
        },
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "gex_signal": pl.Float64,
            "har_rv_signal": pl.Float64,
            "ofi_signal": pl.Float64,
        },
    )
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
    )
    labels = _make_labels([40])
    with pytest.raises(ValueError, match="strictly before"):
        builder.build(labels, signals_small, _make_bars(n))


# --------------------------------------------------------------------
# Group D: realized vol 28d (column 6)
# --------------------------------------------------------------------


def test_realized_vol_window_uses_bars_before_t0() -> None:
    # Build a deterministic close series: log-returns constant 0.002.
    # Then std(log_returns) = 0 exactly.
    n = 100
    close = 100.0 * np.exp(np.arange(n) * 0.002)
    bars = pl.DataFrame(
        {
            "timestamp": [_ts(i) for i in range(n)],
            "close": close.tolist(),
        },
        schema={"timestamp": pl.Datetime("us", "UTC"), "close": pl.Float64},
    )
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
        realized_vol_window=28,
    )
    labels = _make_labels([50])
    fs = builder.build(labels, _make_signals(n), bars)
    rv_col = FEATURE_NAMES.index("realized_vol_28d")
    assert fs.X[0, rv_col] == pytest.approx(0.0, abs=1e-12)


def test_realized_vol_insufficient_history_raises() -> None:
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
        realized_vol_window=28,
    )
    # Event at bar 10 but window needs 29 prior bars.
    labels = _make_labels([10])
    with pytest.raises(ValueError, match="insufficient bar history"):
        builder.build(labels, _make_signals(100), _make_bars(100))


# --------------------------------------------------------------------
# Group E: cyclical time encodings (columns 7-8)
# --------------------------------------------------------------------


def test_cyclical_time_encoding_is_sin_of_hour_and_weekday() -> None:
    # Event at bar 0 => T_EPOCH = Mon 14:30 UTC.
    # hour=14 => sin(2pi*14/24); weekday=0 (Monday) => sin(0) = 0.
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
    )
    labels = _make_labels([40])  # bar 40 => +40*5min = Mon 17:50 UTC
    fs = builder.build(labels, _make_signals(100), _make_bars(100))
    hod_col = FEATURE_NAMES.index("hour_of_day_sin")
    dow_col = FEATURE_NAMES.index("day_of_week_sin")
    expected_hod = float(np.sin(2.0 * np.pi * 17 / 24.0))
    expected_dow = 0.0  # Monday
    assert fs.X[0, hod_col] == pytest.approx(expected_hod, abs=1e-12)
    assert fs.X[0, dow_col] == pytest.approx(expected_dow, abs=1e-12)


# --------------------------------------------------------------------
# Group F: activation config contract
# --------------------------------------------------------------------


def test_missing_required_phase3_signal_in_activation_config_fails_loud() -> None:
    # ofi_signal not in activated set: builder must reject.
    bad_cfg = FeatureActivationConfig(
        activated_features=frozenset({"gex_signal", "har_rv_signal"}),
        rejected_features=frozenset({"ofi_signal"}),
        generated_at=T_EPOCH,
        pbo_of_final_set=None,
    )
    with pytest.raises(ValueError, match="missing required Phase 3 signals"):
        MetaLabelerFeatureBuilder(
            bad_cfg,
            _make_regime_history([0], ["normal"], ["ranging"]),
        )


# --------------------------------------------------------------------
# Group G: UTC / dtype validation
# --------------------------------------------------------------------


def test_labels_with_naive_t0_rejected() -> None:
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
    )
    labels_naive = pl.DataFrame(
        {
            "t0": [datetime(2025, 1, 6, 14, 30)],
            "t1": [datetime(2025, 1, 6, 15, 30)],
            "binary_target": [1],
        },
    )
    with pytest.raises(ValueError, match="Datetime"):
        builder.build(labels_naive, _make_signals(100), _make_bars(100))


def test_non_utc_t0_rejected() -> None:
    ny = timezone(timedelta(hours=-5))
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
    )
    labels_ny = pl.DataFrame(
        {
            "t0": [datetime(2025, 1, 6, 14, 30, tzinfo=ny)],
            "t1": [datetime(2025, 1, 6, 15, 30, tzinfo=ny)],
            "binary_target": [1],
        },
        schema={
            "t0": pl.Datetime("us", time_zone="America/New_York"),
            "t1": pl.Datetime("us", time_zone="America/New_York"),
            "binary_target": pl.Int8,
        },
    )
    with pytest.raises(ValueError, match=r"Datetime\('us', 'UTC'\)"):
        builder.build(labels_ny, _make_signals(100), _make_bars(100))


# --------------------------------------------------------------------
# Group H: anti-leakage invariant (post-t1 permutation does not change X)
# --------------------------------------------------------------------


def test_permuting_bars_after_max_t1_does_not_change_feature_matrix() -> None:
    n = 200
    horizon = 10
    event_ids = [40, 60, 80, 100]
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
        realized_vol_window=28,
    )
    bars = _make_bars(n, seed=7)
    signals = _make_signals(n, seed=11)
    labels = _make_labels(event_ids, horizon=horizon)

    fs_baseline = builder.build(labels, signals, bars)

    # Permute bars and signals strictly AFTER max(t1).
    max_t1_idx = max(event_ids) + horizon
    cutoff = max_t1_idx + 1

    rng = np.random.default_rng(99)
    perm = np.concatenate([np.arange(cutoff), cutoff + rng.permutation(n - cutoff)])
    bars_perm = bars.with_columns(
        pl.Series(
            "close",
            bars["close"].to_numpy()[perm],
            dtype=pl.Float64,
        )
    )
    signals_perm = signals.with_columns(
        [
            pl.Series("gex_signal", signals["gex_signal"].to_numpy()[perm], dtype=pl.Float64),
            pl.Series("har_rv_signal", signals["har_rv_signal"].to_numpy()[perm], dtype=pl.Float64),
            pl.Series("ofi_signal", signals["ofi_signal"].to_numpy()[perm], dtype=pl.Float64),
        ]
    )

    fs_perm = builder.build(labels, signals_perm, bars_perm)
    # Per-label values for cols 1-6 must be byte-for-byte identical; cols
    # 7-8 are derived from t0 only.
    np.testing.assert_array_equal(fs_perm.X, fs_baseline.X)


# --------------------------------------------------------------------
# Group I: Further validation branches (coverage tightening)
# --------------------------------------------------------------------


def test_realized_vol_window_less_than_two_rejected() -> None:
    with pytest.raises(ValueError, match=r"realized_vol_window must be >= 2"):
        MetaLabelerFeatureBuilder(
            _make_activation_config(),
            _make_regime_history([0], ["normal"], ["ranging"]),
            realized_vol_window=1,
        )


def test_regime_history_missing_column_rejected() -> None:
    bad = pl.DataFrame(
        {"timestamp": [_ts(0)], "vol_regime": ["normal"]},
        schema={"timestamp": pl.Datetime("us", "UTC"), "vol_regime": pl.Utf8},
    )
    with pytest.raises(ValueError, match="regime_history missing required column: 'trend_regime'"):
        MetaLabelerFeatureBuilder(_make_activation_config(), bad)


def test_regime_history_empty_rejected() -> None:
    empty = pl.DataFrame(
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "vol_regime": pl.Utf8,
            "trend_regime": pl.Utf8,
        },
    )
    with pytest.raises(ValueError, match="regime_history is empty"):
        MetaLabelerFeatureBuilder(_make_activation_config(), empty)


def test_regime_history_non_monotonic_rejected() -> None:
    bad = pl.DataFrame(
        {
            "timestamp": [_ts(10), _ts(5)],
            "vol_regime": ["normal", "high"],
            "trend_regime": ["ranging", "ranging"],
        },
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "vol_regime": pl.Utf8,
            "trend_regime": pl.Utf8,
        },
    )
    with pytest.raises(ValueError, match="strictly monotonic"):
        MetaLabelerFeatureBuilder(_make_activation_config(), bad)


def test_labels_t1_before_t0_rejected() -> None:
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
    )
    bad_labels = pl.DataFrame(
        {"t0": [_ts(50)], "t1": [_ts(40)], "binary_target": [1]},
        schema={
            "t0": pl.Datetime("us", "UTC"),
            "t1": pl.Datetime("us", "UTC"),
            "binary_target": pl.Int8,
        },
    )
    with pytest.raises(ValueError, match=r"labels\.t1 < labels\.t0"):
        builder.build(bad_labels, _make_signals(100), _make_bars(100))


def test_signals_missing_required_column_rejected() -> None:
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
    )
    bad = pl.DataFrame(
        {
            "timestamp": [_ts(i) for i in range(100)],
            "gex_signal": [0.0] * 100,
            "har_rv_signal": [0.0] * 100,
            # ofi_signal missing
        },
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "gex_signal": pl.Float64,
            "har_rv_signal": pl.Float64,
        },
    )
    with pytest.raises(ValueError, match="signals missing required column"):
        builder.build(_make_labels([50]), bad, _make_bars(100))


def test_signals_with_nulls_rejected() -> None:
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
    )
    sig = _make_signals(100).with_columns(
        pl.when(pl.arange(0, 100) == 5)
        .then(None)
        .otherwise(pl.col("ofi_signal"))
        .alias("ofi_signal")
    )
    with pytest.raises(ValueError, match=r"signals\.ofi_signal contains nulls"):
        builder.build(_make_labels([50]), sig, _make_bars(100))


def test_signals_non_monotonic_rejected() -> None:
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
    )
    bad = pl.DataFrame(
        {
            "timestamp": [_ts(10), _ts(5)],
            "gex_signal": [0.0, 0.0],
            "har_rv_signal": [0.0, 0.0],
            "ofi_signal": [0.0, 0.0],
        },
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "gex_signal": pl.Float64,
            "har_rv_signal": pl.Float64,
            "ofi_signal": pl.Float64,
        },
    )
    with pytest.raises(ValueError, match=r"signals\.timestamp must be strictly monotonic"):
        builder.build(_make_labels([50]), bad, _make_bars(100))


def test_bars_missing_close_rejected() -> None:
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
    )
    bad = pl.DataFrame(
        {"timestamp": [_ts(i) for i in range(100)]},
        schema={"timestamp": pl.Datetime("us", "UTC")},
    )
    with pytest.raises(ValueError, match="bars missing required column"):
        builder.build(_make_labels([50]), _make_signals(100), bad)


def test_bars_non_monotonic_rejected() -> None:
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
    )
    bad = pl.DataFrame(
        {"timestamp": [_ts(10), _ts(5)], "close": [100.0, 100.0]},
        schema={"timestamp": pl.Datetime("us", "UTC"), "close": pl.Float64},
    )
    with pytest.raises(ValueError, match=r"bars\.timestamp must be strictly monotonic"):
        builder.build(_make_labels([50]), _make_signals(100), bad)


def test_bars_non_positive_close_rejected() -> None:
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
    )
    bad = pl.DataFrame(
        {
            "timestamp": [_ts(i) for i in range(100)],
            "close": [0.0] + [100.0] * 99,
        },
        schema={"timestamp": pl.Datetime("us", "UTC"), "close": pl.Float64},
    )
    with pytest.raises(ValueError, match="strictly positive"):
        builder.build(_make_labels([50]), _make_signals(100), bad)


def test_bars_null_close_rejected() -> None:
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
    )
    bad = pl.DataFrame(
        {
            "timestamp": [_ts(i) for i in range(100)],
            "close": [None] + [100.0] * 99,
        },
        schema={"timestamp": pl.Datetime("us", "UTC"), "close": pl.Float64},
    )
    with pytest.raises(ValueError, match=r"bars\.close contains nulls"):
        builder.build(_make_labels([50]), _make_signals(100), bad)


def test_unknown_trend_regime_value_fails_loud() -> None:
    regime = pl.DataFrame(
        {
            "timestamp": [_ts(0)],
            "vol_regime": ["normal"],
            "trend_regime": ["SIDEWAYS_SQUEEZE"],
        },
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "vol_regime": pl.Utf8,
            "trend_regime": pl.Utf8,
        },
    )
    builder = MetaLabelerFeatureBuilder(_make_activation_config(), regime)
    with pytest.raises(ValueError, match="Unknown trend_regime"):
        builder.build(_make_labels([50]), _make_signals(100), _make_bars(100))


def test_feature_set_rejects_wrong_feature_names() -> None:
    with pytest.raises(ValueError, match="feature_names must equal FEATURE_NAMES"):
        MetaLabelerFeatureSet(
            X=np.zeros((2, len(FEATURE_NAMES)), dtype=np.float64),
            feature_names=tuple(f"f{i}" for i in range(len(FEATURE_NAMES))),
            t0=np.array(["2025-01-01", "2025-01-02"], dtype="datetime64[us]"),
            t1=np.array(["2025-01-02", "2025-01-03"], dtype="datetime64[us]"),
        )


def test_feature_set_rejects_wrong_column_count() -> None:
    with pytest.raises(ValueError, match=r"expected \d+"):
        MetaLabelerFeatureSet(
            X=np.zeros((2, len(FEATURE_NAMES) - 1), dtype=np.float64),
            feature_names=FEATURE_NAMES,
            t0=np.array(["2025-01-01", "2025-01-02"], dtype="datetime64[us]"),
            t1=np.array(["2025-01-02", "2025-01-03"], dtype="datetime64[us]"),
        )


def test_feature_set_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="lengths disagree"):
        MetaLabelerFeatureSet(
            X=np.zeros((2, len(FEATURE_NAMES)), dtype=np.float64),
            feature_names=FEATURE_NAMES,
            t0=np.array(["2025-01-01"], dtype="datetime64[us]"),
            t1=np.array(["2025-01-02"], dtype="datetime64[us]"),
        )


def test_feature_set_rejects_1d_x() -> None:
    with pytest.raises(ValueError, match="must be 2-D"):
        MetaLabelerFeatureSet(
            X=np.zeros(8, dtype=np.float64),
            feature_names=FEATURE_NAMES,
            t0=np.array(["2025-01-01"], dtype="datetime64[us]"),
            t1=np.array(["2025-01-02"], dtype="datetime64[us]"),
        )


def test_realized_vol_window_property_is_readable() -> None:
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
        realized_vol_window=14,
    )
    assert builder.realized_vol_window == 14


def test_empty_signals_with_nonempty_labels_rejected() -> None:
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
    )
    empty_sig = pl.DataFrame(
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "gex_signal": pl.Float64,
            "har_rv_signal": pl.Float64,
            "ofi_signal": pl.Float64,
        },
    )
    with pytest.raises(ValueError, match="signals is empty but labels"):
        builder.build(_make_labels([50]), empty_sig, _make_bars(100))


def test_empty_bars_with_nonempty_labels_rejected() -> None:
    builder = MetaLabelerFeatureBuilder(
        _make_activation_config(),
        _make_regime_history([0], ["normal"], ["ranging"]),
    )
    empty_bars = pl.DataFrame(
        schema={"timestamp": pl.Datetime("us", "UTC"), "close": pl.Float64},
    )
    with pytest.raises(ValueError, match="bars is empty"):
        builder.build(_make_labels([50]), _make_signals(100), empty_bars)


def test_breakout_trend_regime_encoded_as_plus_one() -> None:
    regime = pl.DataFrame(
        {
            "timestamp": [_ts(0)],
            "vol_regime": ["normal"],
            "trend_regime": ["breakout"],
        },
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "vol_regime": pl.Utf8,
            "trend_regime": pl.Utf8,
        },
    )
    builder = MetaLabelerFeatureBuilder(_make_activation_config(), regime)
    fs = builder.build(_make_labels([50]), _make_signals(100), _make_bars(100))
    trend_col = FEATURE_NAMES.index("regime_trend_code")
    assert fs.X[0, trend_col] == 1.0
