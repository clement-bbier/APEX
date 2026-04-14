"""Unit tests for :mod:`features.meta_labeler.pnl_simulation`.

Coverage target: ≥ 92 % on ``pnl_simulation.py`` per Phase 4.5 audit.
The two anti-leakage property tests pin the contract that
``r_i`` depends only on ``(C(t0_i), C(t1_i), p_i)`` - perturbing any
other bar must leave every per-label P&L untouched.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from features.meta_labeler.pnl_simulation import (
    CostScenario,
    FoldPnL,
    PnLSimulationResult,
    simulate_meta_labeler_pnl,
)

# --------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------


def _make_bars(n: int = 200, seed: int = 7) -> pl.DataFrame:
    """Hourly bars over ``2025-01-01`` with a positive geometric walk."""
    rng = np.random.default_rng(seed)
    timestamps = np.array(
        [np.datetime64("2025-01-01") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[us]",
    )
    log_ret = rng.normal(0.0, 0.005, size=n)
    log_ret[0] = 0.0
    close = 100.0 * np.exp(np.cumsum(log_ret))
    return pl.DataFrame(
        {
            "timestamp": pl.Series("timestamp", timestamps, dtype=pl.Datetime("us", "UTC")),
            "close": pl.Series("close", close.astype(np.float64), dtype=pl.Float64),
        }
    )


def _make_labels(
    bars: pl.DataFrame,
    event_indices: list[int],
    horizon: int = 5,
) -> tuple[np.ndarray, np.ndarray]:
    ts = bars["timestamp"].to_numpy().astype("datetime64[us]")
    t0 = ts[event_indices]
    t1 = ts[[i + horizon for i in event_indices]]
    return t0, t1


# --------------------------------------------------------------------
# CostScenario behaviour
# --------------------------------------------------------------------


def test_cost_scenario_per_side_and_round_trip_match_adr_0002_d7() -> None:
    assert CostScenario.ZERO.per_side_bps == 0.0
    assert CostScenario.REALISTIC.per_side_bps == 5.0
    assert CostScenario.STRESS.per_side_bps == 15.0
    assert CostScenario.ZERO.round_trip_bps == 0.0
    assert CostScenario.REALISTIC.round_trip_bps == 10.0
    assert CostScenario.STRESS.round_trip_bps == 30.0


def test_cost_scenario_str_value_is_lowercase_name() -> None:
    # ``str`` mixin makes JSON serialisation trivial.
    assert CostScenario.REALISTIC.value == "realistic"
    assert CostScenario.STRESS.value == "stress"


# --------------------------------------------------------------------
# Happy path: bet sizing and cost arithmetic
# --------------------------------------------------------------------


def test_bet_sizing_is_2p_minus_1_in_minus_one_to_plus_one() -> None:
    bars = _make_bars()
    t0, t1 = _make_labels(bars, [10, 20, 30])
    proba = np.array([0.0, 0.5, 1.0], dtype=np.float64)
    result = simulate_meta_labeler_pnl(
        bars=bars,
        t0_per_fold=(t0,),
        t1_per_fold=(t1,),
        proba_per_fold=(proba,),
        scenario=CostScenario.ZERO,
    )
    assert result.per_fold[0].bets.tolist() == [-1.0, 0.0, 1.0]


def test_zero_cost_gross_equals_net_log_return_times_bet() -> None:
    bars = _make_bars()
    t0, t1 = _make_labels(bars, [10, 20, 30])
    proba = np.array([0.7, 0.3, 0.6], dtype=np.float64)
    result = simulate_meta_labeler_pnl(
        bars=bars,
        t0_per_fold=(t0,),
        t1_per_fold=(t1,),
        proba_per_fold=(proba,),
        scenario=CostScenario.ZERO,
    )
    bars_close = bars["close"].to_numpy().astype(np.float64)
    expected = []
    bars_ts = bars["timestamp"].to_numpy().astype("datetime64[us]")
    for i, p in enumerate(proba):
        i0 = int(np.searchsorted(bars_ts, t0[i]))
        i1 = int(np.searchsorted(bars_ts, t1[i]))
        bet = 2 * p - 1
        expected.append(np.log(bars_close[i1] / bars_close[i0]) * bet)
    np.testing.assert_allclose(result.per_fold[0].gross_returns, expected)
    np.testing.assert_allclose(result.per_fold[0].net_returns, result.per_fold[0].gross_returns)


def test_realistic_cost_deduction_scales_with_absolute_bet() -> None:
    """Half-conviction bets pay half cost (ADR-0005 D8)."""
    bars = _make_bars()
    t0, t1 = _make_labels(bars, [10, 20, 30, 40])
    # bets: -1.0, -0.5, +0.5, +1.0
    proba = np.array([0.0, 0.25, 0.75, 1.0], dtype=np.float64)
    result = simulate_meta_labeler_pnl(
        bars=bars,
        t0_per_fold=(t0,),
        t1_per_fold=(t1,),
        proba_per_fold=(proba,),
        scenario=CostScenario.REALISTIC,
    )
    fold = result.per_fold[0]
    rt_cost = CostScenario.REALISTIC.round_trip_bps / 1e4
    expected_cost = rt_cost * np.abs(fold.bets)
    np.testing.assert_allclose(fold.gross_returns - fold.net_returns, expected_cost)


def test_stress_scenario_costs_three_times_realistic() -> None:
    bars = _make_bars()
    t0, t1 = _make_labels(bars, [10, 20])
    proba = np.array([0.8, 0.2], dtype=np.float64)
    base_kwargs = {
        "t0_per_fold": (t0,),
        "t1_per_fold": (t1,),
        "proba_per_fold": (proba,),
    }
    realistic = simulate_meta_labeler_pnl(bars=bars, scenario=CostScenario.REALISTIC, **base_kwargs)
    stress = simulate_meta_labeler_pnl(bars=bars, scenario=CostScenario.STRESS, **base_kwargs)
    diff_realistic = realistic.per_fold[0].gross_returns - realistic.per_fold[0].net_returns
    diff_stress = stress.per_fold[0].gross_returns - stress.per_fold[0].net_returns
    np.testing.assert_allclose(diff_stress, 3.0 * diff_realistic)


def test_result_contains_scenario_and_concatenated_returns() -> None:
    bars = _make_bars()
    t0_a, t1_a = _make_labels(bars, [10, 20])
    t0_b, t1_b = _make_labels(bars, [40, 50, 60])
    proba_a = np.array([0.6, 0.4], dtype=np.float64)
    proba_b = np.array([0.7, 0.3, 0.55], dtype=np.float64)
    result = simulate_meta_labeler_pnl(
        bars=bars,
        t0_per_fold=(t0_a, t0_b),
        t1_per_fold=(t1_a, t1_b),
        proba_per_fold=(proba_a, proba_b),
        scenario=CostScenario.REALISTIC,
    )
    assert isinstance(result, PnLSimulationResult)
    assert result.scenario == CostScenario.REALISTIC
    assert result.all_net_returns.shape == (5,)
    np.testing.assert_array_equal(
        result.all_net_returns,
        np.concatenate([result.per_fold[0].net_returns, result.per_fold[1].net_returns]),
    )
    assert isinstance(result.per_fold[0], FoldPnL)
    assert result.per_fold[0].fold_index == 0
    assert result.per_fold[1].fold_index == 1


def test_empty_fold_yields_empty_arrays() -> None:
    bars = _make_bars()
    empty_t = np.empty(0, dtype="datetime64[us]")
    empty_p = np.empty(0, dtype=np.float64)
    result = simulate_meta_labeler_pnl(
        bars=bars,
        t0_per_fold=(empty_t,),
        t1_per_fold=(empty_t,),
        proba_per_fold=(empty_p,),
        scenario=CostScenario.REALISTIC,
    )
    assert result.per_fold[0].net_returns.size == 0
    assert result.all_net_returns.size == 0


# --------------------------------------------------------------------
# Anti-leakage property tests (Phase 4.5 audit §5)
# --------------------------------------------------------------------


def test_pnl_unchanged_when_prices_after_max_t1_permuted() -> None:
    """Permuting closes strictly after ``max(t1)`` must not move any r_i."""
    bars = _make_bars(n=200)
    t0, t1 = _make_labels(bars, [10, 30, 50, 70])
    proba = np.array([0.6, 0.3, 0.55, 0.8], dtype=np.float64)

    base = simulate_meta_labeler_pnl(
        bars=bars,
        t0_per_fold=(t0,),
        t1_per_fold=(t1,),
        proba_per_fold=(proba,),
        scenario=CostScenario.REALISTIC,
    )

    rng = np.random.default_rng(99)
    bars_ts = bars["timestamp"].to_numpy().astype("datetime64[us]")
    cutoff = int(np.searchsorted(bars_ts, np.max(t1), side="right"))
    perm = np.arange(bars.height)
    perm[cutoff:] = rng.permutation(perm[cutoff:])
    closes = bars["close"].to_numpy()
    permuted = bars.with_columns(pl.Series("close", closes[perm]))

    after = simulate_meta_labeler_pnl(
        bars=permuted,
        t0_per_fold=(t0,),
        t1_per_fold=(t1,),
        proba_per_fold=(proba,),
        scenario=CostScenario.REALISTIC,
    )
    np.testing.assert_array_equal(after.per_fold[0].net_returns, base.per_fold[0].net_returns)


def test_pnl_unchanged_when_prices_outside_t0_t1_set_permuted() -> None:
    """Permuting closes strictly outside ``U{t0_i, t1_i}`` is invisible.

    This is the strict-leakage invariant: ``r_i`` must depend only on
    ``(C(t0_i), C(t1_i), p_i)``, never on any other bar in the series.
    """
    bars = _make_bars(n=200)
    t0, t1 = _make_labels(bars, [10, 30, 50, 70])
    proba = np.array([0.4, 0.7, 0.55, 0.65], dtype=np.float64)

    base = simulate_meta_labeler_pnl(
        bars=bars,
        t0_per_fold=(t0,),
        t1_per_fold=(t1,),
        proba_per_fold=(proba,),
        scenario=CostScenario.ZERO,
    )

    bars_ts = bars["timestamp"].to_numpy().astype("datetime64[us]")
    used_idx = set()
    for ts in np.concatenate([t0, t1]):
        used_idx.add(int(np.searchsorted(bars_ts, ts)))
    free_idx = np.array([i for i in range(bars.height) if i not in used_idx], dtype=np.int64)

    rng = np.random.default_rng(123)
    perm_free = rng.permutation(free_idx)
    new_perm = np.arange(bars.height)
    new_perm[free_idx] = perm_free
    closes = bars["close"].to_numpy()
    permuted = bars.with_columns(pl.Series("close", closes[new_perm]))

    after = simulate_meta_labeler_pnl(
        bars=permuted,
        t0_per_fold=(t0,),
        t1_per_fold=(t1,),
        proba_per_fold=(proba,),
        scenario=CostScenario.ZERO,
    )
    np.testing.assert_array_equal(after.per_fold[0].net_returns, base.per_fold[0].net_returns)


# --------------------------------------------------------------------
# Fail-loud validation
# --------------------------------------------------------------------


def test_missing_timestamp_raises_value_error() -> None:
    bars = _make_bars()
    bars_ts = bars["timestamp"].to_numpy().astype("datetime64[us]")
    # Synthesize a timestamp not present in the bar grid.
    fake_t0 = np.array([bars_ts[10] + np.timedelta64(13, "m")], dtype="datetime64[us]")
    fake_t1 = np.array([bars_ts[15]], dtype="datetime64[us]")
    proba = np.array([0.5], dtype=np.float64)
    with pytest.raises(ValueError, match="exact-matching bar"):
        simulate_meta_labeler_pnl(
            bars=bars,
            t0_per_fold=(fake_t0,),
            t1_per_fold=(fake_t1,),
            proba_per_fold=(proba,),
        )


def test_t1_after_last_bar_raises() -> None:
    bars = _make_bars(n=50)
    bars_ts = bars["timestamp"].to_numpy().astype("datetime64[us]")
    # t1 is one hour past the last bar.
    t0 = np.array([bars_ts[40]], dtype="datetime64[us]")
    t1 = np.array([bars_ts[-1] + np.timedelta64(1, "h")], dtype="datetime64[us]")
    proba = np.array([0.5], dtype=np.float64)
    with pytest.raises(ValueError, match="exceeds last bar timestamp"):
        simulate_meta_labeler_pnl(
            bars=bars,
            t0_per_fold=(t0,),
            t1_per_fold=(t1,),
            proba_per_fold=(proba,),
        )


def test_proba_outside_unit_interval_raises() -> None:
    bars = _make_bars()
    t0, t1 = _make_labels(bars, [10])
    bad_proba = np.array([1.5], dtype=np.float64)
    with pytest.raises(ValueError, match=r"proba must lie in \[0, 1\]"):
        simulate_meta_labeler_pnl(
            bars=bars,
            t0_per_fold=(t0,),
            t1_per_fold=(t1,),
            proba_per_fold=(bad_proba,),
        )


def test_non_finite_proba_raises() -> None:
    bars = _make_bars()
    t0, t1 = _make_labels(bars, [10])
    bad_proba = np.array([np.nan], dtype=np.float64)
    with pytest.raises(ValueError, match="non-finite"):
        simulate_meta_labeler_pnl(
            bars=bars,
            t0_per_fold=(t0,),
            t1_per_fold=(t1,),
            proba_per_fold=(bad_proba,),
        )


def test_t1_before_t0_raises() -> None:
    bars = _make_bars()
    bars_ts = bars["timestamp"].to_numpy().astype("datetime64[us]")
    t0 = np.array([bars_ts[20]], dtype="datetime64[us]")
    t1 = np.array([bars_ts[10]], dtype="datetime64[us]")
    proba = np.array([0.5], dtype=np.float64)
    with pytest.raises(ValueError, match="t1_i must be >= t0_i"):
        simulate_meta_labeler_pnl(
            bars=bars,
            t0_per_fold=(t0,),
            t1_per_fold=(t1,),
            proba_per_fold=(proba,),
        )


def test_per_fold_shape_disagreement_raises() -> None:
    bars = _make_bars()
    t0, t1 = _make_labels(bars, [10, 20, 30])
    proba = np.array([0.5, 0.5], dtype=np.float64)  # length 2 vs 3
    with pytest.raises(ValueError, match="t0/t1/proba shapes disagree"):
        simulate_meta_labeler_pnl(
            bars=bars,
            t0_per_fold=(t0,),
            t1_per_fold=(t1,),
            proba_per_fold=(proba,),
        )


def test_per_fold_tuple_length_mismatch_raises() -> None:
    bars = _make_bars()
    t0, t1 = _make_labels(bars, [10])
    proba = np.array([0.5], dtype=np.float64)
    with pytest.raises(ValueError, match="per-fold tuples must have the same length"):
        simulate_meta_labeler_pnl(
            bars=bars,
            t0_per_fold=(t0, t0),
            t1_per_fold=(t1,),
            proba_per_fold=(proba,),
        )


def test_non_monotonic_bars_raise() -> None:
    bars = _make_bars()
    closes = bars["close"].to_numpy()
    timestamps = bars["timestamp"].to_numpy().astype("datetime64[us]")
    timestamps[5], timestamps[6] = timestamps[6], timestamps[5]
    bad = pl.DataFrame(
        {
            "timestamp": pl.Series("timestamp", timestamps, dtype=pl.Datetime("us", "UTC")),
            "close": pl.Series("close", closes, dtype=pl.Float64),
        }
    )
    t0, t1 = _make_labels(bars, [10])
    proba = np.array([0.5], dtype=np.float64)
    with pytest.raises(ValueError, match="strictly monotonic"):
        simulate_meta_labeler_pnl(
            bars=bad,
            t0_per_fold=(t0,),
            t1_per_fold=(t1,),
            proba_per_fold=(proba,),
        )


def test_non_positive_close_raises() -> None:
    bars = _make_bars()
    closes = bars["close"].to_numpy()
    closes[42] = 0.0
    timestamps = bars["timestamp"].to_numpy().astype("datetime64[us]")
    bad = pl.DataFrame(
        {
            "timestamp": pl.Series("timestamp", timestamps, dtype=pl.Datetime("us", "UTC")),
            "close": pl.Series("close", closes, dtype=pl.Float64),
        }
    )
    t0, t1 = _make_labels(bars, [10])
    proba = np.array([0.5], dtype=np.float64)
    with pytest.raises(ValueError, match="strictly positive"):
        simulate_meta_labeler_pnl(
            bars=bad,
            t0_per_fold=(t0,),
            t1_per_fold=(t1,),
            proba_per_fold=(proba,),
        )


def test_missing_columns_raise() -> None:
    bars = pl.DataFrame({"ts": [1], "px": [100.0]})
    t0 = np.array([np.datetime64("2025-01-01")], dtype="datetime64[us]")
    t1 = np.array([np.datetime64("2025-01-01T05")], dtype="datetime64[us]")
    proba = np.array([0.5], dtype=np.float64)
    with pytest.raises(ValueError, match="must contain columns"):
        simulate_meta_labeler_pnl(
            bars=bars,
            t0_per_fold=(t0,),
            t1_per_fold=(t1,),
            proba_per_fold=(proba,),
        )


def test_empty_bars_raise() -> None:
    empty = pl.DataFrame(
        {
            "timestamp": pl.Series("timestamp", [], dtype=pl.Datetime("us", "UTC")),
            "close": pl.Series("close", [], dtype=pl.Float64),
        }
    )
    t0 = np.array([np.datetime64("2025-01-01")], dtype="datetime64[us]")
    t1 = np.array([np.datetime64("2025-01-01T05")], dtype="datetime64[us]")
    proba = np.array([0.5], dtype=np.float64)
    with pytest.raises(ValueError, match="bars is empty"):
        simulate_meta_labeler_pnl(
            bars=empty,
            t0_per_fold=(t0,),
            t1_per_fold=(t1,),
            proba_per_fold=(proba,),
        )
