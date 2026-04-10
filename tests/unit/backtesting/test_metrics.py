"""Property tests for backtesting.metrics.full_report().

Regression coverage for issue #8: Sharpe must be computed on the
daily-resampled equity curve, not on per-trade returns. A strategy with
WR > 80% and PF > 2 must yield a strictly positive Sharpe.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

import numpy as np
import pytest

from backtesting.metrics import (
    backtest_overfitting_probability,
    cost_sensitivity_report,
    full_report,
    probability_of_backtest_overfitting_cpcv,
)
from backtesting.walk_forward import CombinatorialPurgedCV
from core.models.order import TradeRecord
from core.models.signal import Direction


def _make_trade(net_pnl: float, exit_ts_ms: int) -> TradeRecord:
    pnl = Decimal(str(round(net_pnl, 2)))
    entry = Decimal("50000")
    size = Decimal("0.01")
    exit_p = entry + pnl / size
    return TradeRecord(
        trade_id=f"t-{exit_ts_ms}",
        symbol="BTC/USDT",
        direction=Direction.LONG,
        entry_timestamp_ms=exit_ts_ms - 1000,
        exit_timestamp_ms=exit_ts_ms,
        entry_price=entry,
        exit_price=exit_p,
        size=size,
        gross_pnl=pnl,
        net_pnl=pnl,
        commission=Decimal("0"),
        slippage_cost=Decimal("0"),
        signal_type="OFI",
        regime_at_entry="TRENDING",
        session_at_entry="us_normal",
    )


def test_profitable_strategy_has_positive_sharpe() -> None:
    """A strategy with WR>80% and PF>2 must yield positive Sharpe.

    Regression test for issue #8. The previous implementation computed
    Sharpe on per-trade returns minus an annualised 5% risk-free rate,
    yielding catastrophically negative Sharpe (down to -3709) for HFT
    strategies with WR=93% and PF=15. The fix routes Sharpe through the
    daily-resampled equity curve.
    """
    rng = np.random.default_rng(42)
    n_days = 30
    # Mostly winners (~85%) with bounded losers (~ -0.3%) and winners
    # of ~ +1.0%. PF = (0.85*30*1.0) / (0.15*30*0.3) ≈ 5.7, well above 2.
    coin = rng.random(n_days)
    daily_returns = np.where(coin < 0.15, -0.003, 0.010)
    equity = 100_000.0 * np.cumprod(1.0 + daily_returns)

    # One trade per day at UTC midnight, PnL = day's equity delta.
    base_ts_s = 1_704_067_200  # 2024-01-01 00:00:00 UTC
    trades: list[TradeRecord] = []
    prev_equity = 100_000.0
    for i in range(n_days):
        day_pnl = float(equity[i]) - prev_equity
        prev_equity = float(equity[i])
        # Skew towards winners to satisfy WR>80% and PF>2: shift sign
        # so that ~85% of days are wins. The synthetic returns above
        # are already mostly positive (mean 0.5%, std 1%).
        ts_ms = (base_ts_s + i * 86_400) * 1000
        trades.append(_make_trade(day_pnl, ts_ms))

    wins = sum(1 for t in trades if t.net_pnl > 0)
    win_rate_obs = wins / len(trades)
    gross_win = sum(float(t.net_pnl) for t in trades if t.net_pnl > 0)
    gross_loss = abs(sum(float(t.net_pnl) for t in trades if t.net_pnl < 0))
    pf_obs = gross_win / gross_loss if gross_loss > 0 else float("inf")

    assert win_rate_obs > 0.80, f"fixture WR={win_rate_obs:.2f} should be >0.80"
    assert pf_obs > 2.0, f"fixture PF={pf_obs:.2f} should be >2.0"

    report = full_report(trades=trades, initial_capital=100_000.0)

    assert report["sharpe"] > 0.0, (
        f"Profitable strategy (WR={win_rate_obs:.2f}, PF={pf_obs:.2f}) "
        f"should have positive Sharpe, got {report['sharpe']}"
    )


# ---------------------------------------------------------------------------
# Property tests for PSR / DSR / stationary-bootstrap CI wiring (issue #19).
# References:
#   Bailey & López de Prado (2012) — PSR
#   Bailey & López de Prado (2014) — DSR
#   Politis & Romano (1994)         — stationary bootstrap
#   ADR-0002 Quant Methodology Charter
# ---------------------------------------------------------------------------


def _seeded_equity_curve(
    n_days: int = 60,
    win_rate: float = 0.6,
    mean_return: float = 0.003,
    loss_size: float = 0.003,
    seed: int = 42,
) -> tuple[list[TradeRecord], float]:
    """Build a synthetic seeded daily equity curve and matching trades."""
    rng = np.random.default_rng(seed)
    coin = rng.random(n_days)
    daily_returns = np.where(coin < win_rate, mean_return, -loss_size)
    base_ts_s = 1_704_067_200  # 2024-01-01 UTC
    initial = 100_000.0
    equity = initial * np.cumprod(1.0 + daily_returns)
    trades: list[TradeRecord] = []
    prev = initial
    for i in range(n_days):
        day_pnl = float(equity[i]) - prev
        prev = float(equity[i])
        ts_ms = (base_ts_s + i * 86_400) * 1000
        trades.append(_make_trade(day_pnl, ts_ms))
    return trades, initial


def _full_report_from_seeded_strategy(
    n_days: int = 60,
    win_rate: float = 0.6,
    mean_return: float = 0.003,
    loss_size: float = 0.003,
    seed: int = 42,
    n_trials: int = 1,
    risk_free_rate: float = 0.05,
) -> dict[str, Any]:
    trades, initial = _seeded_equity_curve(
        n_days=n_days,
        win_rate=win_rate,
        mean_return=mean_return,
        loss_size=loss_size,
        seed=seed,
    )
    return full_report(
        trades=trades,
        initial_capital=initial,
        risk_free_rate=risk_free_rate,
        n_trials=n_trials,
    )


def test_psr_in_unit_interval() -> None:
    """PSR is a probability so it must live in [0, 1]."""
    report = _full_report_from_seeded_strategy(win_rate=0.6, seed=42)
    psr = float(report["psr"])
    assert 0.0 <= psr <= 1.0


def test_psr_monotonic_in_sharpe() -> None:
    """Higher Sharpe ⇒ higher PSR, ceteris paribus."""
    weak = _full_report_from_seeded_strategy(mean_return=0.001, seed=42)
    strong = _full_report_from_seeded_strategy(mean_return=0.005, seed=42)
    assert float(strong["sharpe"]) > float(weak["sharpe"])
    assert float(strong["psr"]) >= float(weak["psr"])


def test_dsr_strictly_less_than_psr_under_multiple_trials() -> None:
    """DSR deflates PSR when multiple trials are tested."""
    single = _full_report_from_seeded_strategy(seed=42, n_trials=1)
    multi = _full_report_from_seeded_strategy(seed=42, n_trials=50)
    assert float(multi["dsr"]) < float(single["psr"])


def test_bootstrap_ci_contains_point_sharpe() -> None:
    """The 95% bootstrap CI must straddle the point estimate."""
    report = _full_report_from_seeded_strategy(seed=42)
    lo = float(report["sharpe_ci_95_low"])
    hi = float(report["sharpe_ci_95_high"])
    sharpe = float(report["sharpe"])
    assert lo <= sharpe <= hi


def test_bootstrap_ci_width_shrinks_with_sample_size() -> None:
    """Law of large numbers: larger samples yield tighter CIs."""
    short = _full_report_from_seeded_strategy(n_days=30, seed=42)
    long = _full_report_from_seeded_strategy(n_days=300, seed=42)
    short_w = float(short["sharpe_ci_95_high"]) - float(short["sharpe_ci_95_low"])
    long_w = float(long["sharpe_ci_95_high"]) - float(long["sharpe_ci_95_low"])
    assert long_w < short_w


def test_profitable_strategy_has_high_psr() -> None:
    """An 85% winrate strategy with mean daily return 0.5% must get PSR > 0.90."""
    report = _full_report_from_seeded_strategy(
        n_days=120,
        win_rate=0.85,
        mean_return=0.005,
        loss_size=0.003,
        seed=42,
    )
    psr = float(report["psr"])
    assert psr > 0.90, f"got PSR={psr}"


def test_psr_and_sharpe_are_mutually_consistent_at_nonzero_rf() -> None:
    """PSR and Sharpe must both see the same excess-return series.

    Regression test for a bug discovered in PR #20 Copilot review: PSR
    was computed on raw daily returns while Sharpe was computed on
    excess returns, making them silently inconsistent whenever
    risk_free_rate > 0.
    """
    report_rf0 = _full_report_from_seeded_strategy(
        win_rate=0.70, mean_return=0.004, seed=42, risk_free_rate=0.0
    )
    report_rf5 = _full_report_from_seeded_strategy(
        win_rate=0.70, mean_return=0.004, seed=42, risk_free_rate=0.05
    )
    # Sharpe must drop when rf increases.
    assert report_rf5["sharpe"] < report_rf0["sharpe"]
    # PSR must also drop (not stay constant — that was the bug).
    assert report_rf5["psr"] < report_rf0["psr"]


# ---------------------------------------------------------------------------
# Rank-PBO via CPCV (issue #21) — Bailey, Borwein, Lopez de Prado, Zhu (2014)
# ---------------------------------------------------------------------------


class _MockCV:
    """Minimal CV stub yielding hand-crafted (train_idx, test_idx) splits."""

    def __init__(self, splits: list[tuple[list[int], list[int]]]) -> None:
        self._splits = splits

    def split(self, n_samples: int) -> list[tuple[list[int], list[int]]]:
        del n_samples
        return self._splits


def test_pbo_perfect_overfit_returns_one() -> None:
    """When IS-best is always OOS-worst, PBO must equal 1.0.

    Two designed splits over 20 observations and 3 strategies. In each
    split the strategy that wins on training is constructed to lose on
    test, so its OOS rank is 1, omega = 1.5/4 = 0.375 and lambda < 0.
    """
    n_obs = 20
    half = n_obs // 2
    # strat 0: high in [0..9], low in [10..19] → wins train A, loses test A
    # strat 1: low in [0..9], high in [10..19] → wins train B, loses test B
    # strat 2: flat — never IS-best, irrelevant for the assertion
    returns = np.zeros((n_obs, 3), dtype=float)
    returns[:half, 0] = 0.02
    returns[half:, 0] = -0.02
    returns[:half, 1] = -0.02
    returns[half:, 1] = 0.02
    returns[:, 2] = 0.0001  # tiny constant noise floor
    splits = [
        (list(range(0, half)), list(range(half, n_obs))),
        (list(range(half, n_obs)), list(range(0, half))),
    ]
    cv = _MockCV(splits)
    pbo = probability_of_backtest_overfitting_cpcv(returns, cv)  # type: ignore[arg-type]
    assert pbo == 1.0, f"expected PBO=1.0 for perfect overfit, got {pbo}"


def test_pbo_no_overfit_returns_zero() -> None:
    """When the IS-best is also the OOS-best on every split, PBO = 0.0.

    Strategy 0 has uniformly positive returns; all other strategies have
    flat or strictly worse returns. On every CPCV split strategy 0 is
    both IS-best and OOS-best, so its OOS rank is N (top), omega is
    close to 1 and lambda > 0 — never counted in PBO.
    """
    rng = np.random.default_rng(7)
    n_obs, n_strats = 60, 5
    returns = rng.normal(0.0, 0.001, size=(n_obs, n_strats))
    returns[:, 0] = 0.01  # strategy 0 dominates uniformly
    cv = CombinatorialPurgedCV(n_splits=6, n_test_splits=2, embargo_pct=0.0)
    pbo = probability_of_backtest_overfitting_cpcv(returns, cv)
    assert pbo == 0.0, f"expected PBO=0.0 for no overfit, got {pbo}"


def test_pbo_random_strategies_around_half() -> None:
    """20 uncorrelated random strategies should yield PBO ~ 0.5."""
    rng = np.random.default_rng(42)
    n_obs, n_strats = 500, 20
    returns = rng.normal(0.0, 0.01, size=(n_obs, n_strats))
    cv = CombinatorialPurgedCV(n_splits=10, n_test_splits=2, embargo_pct=0.0)
    pbo = probability_of_backtest_overfitting_cpcv(returns, cv)
    assert 0.35 <= pbo <= 0.65, f"expected ~0.5, got {pbo}"


def test_pbo_logit_handles_boundary_ranks() -> None:
    """omega at the rank-1 and rank-N extremes must yield finite logits.

    With ``omega = (rank + 0.5) / (N + 1)`` the boundary values are
    ``1.5/(N+1)`` and ``(N+0.5)/(N+1)`` — both strictly inside (0, 1)
    so the logit is finite (no inf, no nan) regardless of N.
    """
    # rank=1 case (worst): build a matrix where strat 0 is always worst.
    rng = np.random.default_rng(123)
    n_obs, n_strats = 60, 4
    returns = rng.normal(0.005, 0.001, size=(n_obs, n_strats))
    returns[:, 0] = -0.01  # strategy 0 strictly worst (and lowest IS too)
    cv = CombinatorialPurgedCV(n_splits=6, n_test_splits=2, embargo_pct=0.0)
    pbo = probability_of_backtest_overfitting_cpcv(returns, cv)
    assert math.isfinite(pbo)
    assert 0.0 <= pbo <= 1.0


def test_pbo_raises_on_single_strategy() -> None:
    """PBO is undefined for fewer than 2 strategies."""
    returns = np.ones((50, 1), dtype=float) * 0.01
    cv = CombinatorialPurgedCV(n_splits=6, n_test_splits=2, embargo_pct=0.0)
    with pytest.raises(ValueError, match="at least 2 strategies"):
        probability_of_backtest_overfitting_cpcv(returns, cv)


def test_pbo_deprecated_scalar_still_callable() -> None:
    """Old scalar API still works but emits DeprecationWarning."""
    with pytest.warns(DeprecationWarning, match="deprecated"):
        result = backtest_overfitting_probability(1.5, 0.8, 10)
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0


def test_full_report_pbo_field_present_when_matrix_provided() -> None:
    """full_report() exposes a `pbo` field iff a returns matrix is given."""
    trades, initial = _seeded_equity_curve(n_days=60, win_rate=0.65, seed=11)
    rng = np.random.default_rng(11)
    returns_matrix = rng.normal(0.0, 0.01, size=(120, 5))
    report_no_matrix = full_report(trades=trades, initial_capital=initial)
    report_with = full_report(
        trades=trades,
        initial_capital=initial,
        strategy_returns_matrix=returns_matrix,
        n_cv_splits=6,
        n_cv_test_splits=2,
    )
    assert "pbo" not in report_no_matrix
    assert "pbo" in report_with
    assert 0.0 <= float(report_with["pbo"]) <= 1.0


# ---------------------------------------------------------------------------
# Drawdown / tail-risk metrics (issue #23 — ADR-0002 Section A item 6)
# Martin & McCann (1989) Ulcer Index, Sortino & Price (1994), Young (1991).
# ---------------------------------------------------------------------------


def test_ulcer_index_zero_on_monotonic_equity() -> None:
    """A strictly increasing equity curve has Ulcer Index = 0."""
    report = _full_report_from_seeded_strategy(
        n_days=60, win_rate=1.0, mean_return=0.005, loss_size=0.0, seed=42
    )
    assert report["ulcer_index"] == pytest.approx(0.0, abs=1e-9)
    # Martin ratio is also 0 by convention when Ulcer is 0.
    assert report["martin_ratio"] == 0.0


def test_ulcer_index_positive_on_drawdown() -> None:
    """Any drawdown produces a strictly positive Ulcer Index."""
    report = _full_report_from_seeded_strategy(
        n_days=60, win_rate=0.55, mean_return=0.004, loss_size=0.005, seed=7
    )
    assert report["ulcer_index"] > 0.0
    assert report["max_drawdown"] > 0.0
    # max_drawdown_absolute is a non-negative monetary magnitude.
    assert report["max_drawdown_absolute"] > 0.0


def test_calmar_matches_manual_computation() -> None:
    """Reported Calmar equals hand-computed CAGR / |maxDD|."""
    report = _full_report_from_seeded_strategy(seed=42)
    manual = report["cagr"] / abs(report["max_drawdown"])
    assert report["calmar"] == pytest.approx(manual, rel=1e-9)


def test_sortino_greater_than_sharpe_when_returns_right_skewed() -> None:
    """Right-skewed returns mean Sortino > Sharpe.

    Construct a strategy with rare large gains and frequent small
    losses (right skew). The downside semi-deviation only sees the
    small losses, while full std also captures the large positive
    excursions, so Sortino > Sharpe.
    """
    report = _full_report_from_seeded_strategy(
        n_days=180,
        win_rate=0.30,  # rare wins
        mean_return=0.020,  # large gains
        loss_size=0.005,  # small losses
        seed=11,
    )
    assert report["return_skewness"] > 0.0  # confirm right-skew
    assert report["sortino"] > report["sharpe"]


def test_tail_ratio_greater_than_one_on_right_skewed_returns() -> None:
    """Right-tail dominance gives tail_ratio > 1."""
    report = _full_report_from_seeded_strategy(
        n_days=180,
        win_rate=0.30,
        mean_return=0.020,
        loss_size=0.005,
        seed=11,
    )
    assert report["tail_ratio"] > 1.0


def test_return_distribution_stats_present_and_finite() -> None:
    """All 3 distribution fields are present and finite (or +inf)."""
    report = _full_report_from_seeded_strategy(seed=42)
    assert isinstance(report["return_skewness"], float)
    assert np.isfinite(report["return_skewness"])
    assert np.isfinite(report["return_excess_kurtosis"])
    tail = report["tail_ratio"]
    assert np.isfinite(tail) or tail == float("inf")


def test_martin_ratio_handles_zero_ulcer() -> None:
    """Monotonic equity → Ulcer = 0 → Martin defined as 0.0, not raise."""
    report = _full_report_from_seeded_strategy(
        n_days=60, win_rate=1.0, mean_return=0.003, loss_size=0.0, seed=1
    )
    assert report["ulcer_index"] == 0.0
    assert report["martin_ratio"] == 0.0
    assert math.isfinite(report["martin_ratio"])


def test_ulcer_and_martin_ratio_share_fractional_units() -> None:
    """Regression: Ulcer Index must be in the same unit system as CAGR.

    Bug discovered in PR #24 Copilot review: Ulcer was in percent
    while CAGR / risk_free_rate are fractions, making martin_ratio
    silently off by ~100x. Realistic strategies have drawdowns of a
    few percent, so the Ulcer Index in fractional units must stay
    well below 1.0.
    """
    report = _full_report_from_seeded_strategy(n_days=60, win_rate=0.6, seed=42)
    assert 0.0 <= report["ulcer_index"] < 1.0, (
        f"Ulcer Index {report['ulcer_index']} looks like percent, "
        f"not fraction — did the 100x multiplier come back?"
    )


# ---------------------------------------------------------------------------
# Cost sensitivity report (issue #25 — ADR-0002 Section A item 7)
# ---------------------------------------------------------------------------


def test_cost_sensitivity_zero_scenario_matches_bare_full_report() -> None:
    """Zero cost scenario must equal a bare full_report() call."""
    trades, initial = _seeded_equity_curve(seed=42)
    cost_report = cost_sensitivity_report(
        trades=trades, initial_capital=initial, realistic_cost_bps=10.0
    )
    bare = full_report(trades=trades, initial_capital=initial)
    assert cost_report["zero"]["sharpe"] == pytest.approx(bare["sharpe"], rel=1e-9)
    assert cost_report["zero"]["total_pnl"] == pytest.approx(bare["total_pnl"], rel=1e-9)


def test_cost_sensitivity_realistic_sharpe_less_than_zero_cost() -> None:
    """Adding costs must reduce (or keep equal) the Sharpe ratio."""
    trades, initial = _seeded_equity_curve(n_days=60, win_rate=0.7, mean_return=0.004, seed=42)
    cost_report = cost_sensitivity_report(
        trades=trades, initial_capital=initial, realistic_cost_bps=20.0
    )
    assert cost_report["realistic"]["sharpe"] <= cost_report["zero"]["sharpe"]


def test_cost_sensitivity_stress_sharpe_less_than_realistic() -> None:
    """Stress (2x) cost must degrade further than realistic."""
    trades, initial = _seeded_equity_curve(n_days=60, win_rate=0.7, mean_return=0.004, seed=42)
    cost_report = cost_sensitivity_report(
        trades=trades, initial_capital=initial, realistic_cost_bps=20.0
    )
    assert cost_report["stress"]["sharpe"] <= cost_report["realistic"]["sharpe"]


def test_cost_sensitivity_profitability_flags_consistent() -> None:
    """Profitability flag must agree with Sharpe sign and total_pnl sign."""
    trades, initial = _seeded_equity_curve(n_days=60, win_rate=0.7, mean_return=0.005, seed=42)
    cost_report = cost_sensitivity_report(
        trades=trades, initial_capital=initial, realistic_cost_bps=15.0
    )
    flag_r = cost_report["profitable_under_realistic"]
    sharpe_r = cost_report["realistic"]["sharpe"]
    pnl_r = cost_report["realistic"]["total_pnl"]
    assert flag_r == (sharpe_r > 0 and pnl_r > 0)


def test_cost_sensitivity_sharpe_degradation_non_negative() -> None:
    """Degradation % must be non-negative when zero-cost Sharpe is positive."""
    trades, initial = _seeded_equity_curve(n_days=60, win_rate=0.7, mean_return=0.005, seed=42)
    cost_report = cost_sensitivity_report(
        trades=trades, initial_capital=initial, realistic_cost_bps=10.0
    )
    if cost_report["zero"]["sharpe"] > 0:
        assert cost_report["sharpe_degradation_zero_to_realistic"] >= 0.0
        assert cost_report["sharpe_degradation_zero_to_stress"] >= 0.0


def test_cost_sensitivity_does_not_mutate_input_trades() -> None:
    """The original trades list and its frozen records must be untouched."""
    trades, initial = _seeded_equity_curve(seed=42)
    snapshot_pnls = [t.net_pnl for t in trades]
    snapshot_ids = [id(t) for t in trades]
    _ = cost_sensitivity_report(trades=trades, initial_capital=initial, realistic_cost_bps=10.0)
    assert [t.net_pnl for t in trades] == snapshot_pnls
    assert [id(t) for t in trades] == snapshot_ids


def test_cost_sensitivity_empty_trades_returns_error_dict() -> None:
    """Regression: empty trades must not raise KeyError.

    Bug from PR #26 Copilot review: full_report() early-returns an
    error dict on empty trades, so reading report_zero["sharpe"] would
    raise KeyError. cost_sensitivity_report now mirrors the error path.
    """
    report = cost_sensitivity_report(trades=[], initial_capital=100_000.0, realistic_cost_bps=10.0)
    assert "error" in report
    assert report["profitable_under_realistic"] is False
    assert report["profitable_under_stress"] is False


def test_cost_sensitivity_rejects_invalid_bps() -> None:
    """Regression: negative / NaN / inf bps must raise ValueError."""
    trades, initial = _seeded_equity_curve(seed=42)
    with pytest.raises(ValueError, match="finite and non-negative"):
        cost_sensitivity_report(trades=trades, initial_capital=initial, realistic_cost_bps=-5.0)
    with pytest.raises(ValueError, match="finite and non-negative"):
        cost_sensitivity_report(
            trades=trades,
            initial_capital=initial,
            realistic_cost_bps=float("nan"),
        )
    with pytest.raises(ValueError, match="finite and non-negative"):
        cost_sensitivity_report(
            trades=trades,
            initial_capital=initial,
            realistic_cost_bps=float("inf"),
        )


# ---------------------------------------------------------------------------
# Regime decomposition (ADR-0002 Section A item 10)
# ---------------------------------------------------------------------------


def test_regime_breakdown_has_all_fields_per_regime() -> None:
    """Every regime must have the 8 fields."""
    trades, initial = _seeded_equity_curve(seed=42)
    half = len(trades) // 2
    trades_tagged = [t.model_copy(update={"regime_at_entry": "low_vol"}) for t in trades[:half]] + [
        t.model_copy(update={"regime_at_entry": "high_vol"}) for t in trades[half:]
    ]
    report = full_report(trades=trades_tagged, initial_capital=initial)
    by_regime = report["by_regime"]
    assert "low_vol" in by_regime
    assert "high_vol" in by_regime
    for regime_stats in by_regime.values():
        for field in [
            "trade_count",
            "win_rate",
            "hit_rate",
            "total_pnl",
            "avg_pnl",
            "sharpe",
            "max_drawdown",
            "ulcer_index",
        ]:
            assert field in regime_stats, f"missing {field}"


def test_regime_concentration_one_on_single_regime() -> None:
    """All PnL in one regime -> HHI = 1.0."""
    trades, initial = _seeded_equity_curve(seed=42)
    trades_tagged = [t.model_copy(update={"regime_at_entry": "only"}) for t in trades]
    report = full_report(trades=trades_tagged, initial_capital=initial)
    assert report["regime_concentration"] == pytest.approx(1.0, abs=1e-9)


def test_regime_concentration_balanced_three_regimes() -> None:
    """Three regimes with approximately equal PnL -> HHI near 1/3."""
    trades, initial = _seeded_equity_curve(seed=42, n_days=90, win_rate=0.7, mean_return=0.004)
    third = len(trades) // 3
    trades_tagged = (
        [t.model_copy(update={"regime_at_entry": "a"}) for t in trades[:third]]
        + [t.model_copy(update={"regime_at_entry": "b"}) for t in trades[third : 2 * third]]
        + [t.model_copy(update={"regime_at_entry": "c"}) for t in trades[2 * third :]]
    )
    report = full_report(trades=trades_tagged, initial_capital=initial)
    hhi = report["regime_concentration"]
    assert 0.20 <= hhi <= 0.60, f"HHI={hhi} outside expected range for ~balanced 3 regimes"


def test_regime_with_one_trade_returns_zero_sharpe() -> None:
    """A regime with a single trade gets zero Sharpe (needs variance) but DD/Ulcer are computed.

    Sharpe requires >= 2 daily returns for standard-deviation estimation,
    so a single-trade regime correctly zero-fills it. DD and Ulcer only
    need >= 2 equity-curve points (initial + 1 trade), so they are
    computed from the real curve.
    """
    trades, initial = _seeded_equity_curve(seed=42)
    tagged = [
        (
            t.model_copy(update={"regime_at_entry": "singleton"})
            if i == 0
            else t.model_copy(update={"regime_at_entry": "bulk"})
        )
        for i, t in enumerate(trades)
    ]
    report = full_report(trades=tagged, initial_capital=initial)
    singleton = report["by_regime"]["singleton"]
    assert singleton["trade_count"] == 1
    assert singleton["sharpe"] == 0.0
    # DD and Ulcer are computed (curve has 2 points), not zero-filled
    assert isinstance(singleton["max_drawdown"], float)
    assert isinstance(singleton["ulcer_index"], float)


def test_regime_sharpe_preserved_under_reordering() -> None:
    """Shuffling trades within a regime doesn't change its per-regime Sharpe."""
    import random as _random

    trades, initial = _seeded_equity_curve(seed=42)
    tagged = [t.model_copy(update={"regime_at_entry": "only"}) for t in trades]
    report1 = full_report(trades=tagged, initial_capital=initial)
    shuffled = list(tagged)
    _random.Random(99).shuffle(shuffled)
    report2 = full_report(trades=shuffled, initial_capital=initial)
    assert report1["by_regime"]["only"]["sharpe"] == pytest.approx(
        report2["by_regime"]["only"]["sharpe"], rel=1e-9
    )


def test_regime_sharpe_uses_caller_risk_free_rate() -> None:
    """Regression: per-regime Sharpe must use the same rf as headline Sharpe.

    Bug from PR #28 Copilot review: _regime_stats() called
    sharpe_ratio() without forwarding risk_free_rate, silently using
    the default 0.05 even when the caller specified a different rate.
    """
    trades, initial = _seeded_equity_curve(seed=42)
    tagged = [t.model_copy(update={"regime_at_entry": "only"}) for t in trades]
    report_rf0 = full_report(trades=tagged, initial_capital=initial, risk_free_rate=0.0)
    report_rf10 = full_report(trades=tagged, initial_capital=initial, risk_free_rate=0.10)
    # Per-regime Sharpe must change when rf changes
    sharpe_rf0 = report_rf0["by_regime"]["only"]["sharpe"]
    sharpe_rf10 = report_rf10["by_regime"]["only"]["sharpe"]
    assert sharpe_rf0 != pytest.approx(sharpe_rf10, abs=1e-6), (
        "Per-regime Sharpe did not change with risk_free_rate — "
        "rf is not being forwarded to _regime_stats()"
    )
