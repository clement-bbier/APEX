"""Known-answer Sharpe regression tests for backtesting.metrics.

Exposes the sparse-day annualisation bias in
:func:`backtesting.metrics.daily_equity_curve_from_trades` (issue #102).

The broken implementation skips calendar days with no trades, so a
strategy firing on N << 252 days has its N daily returns annualised by
sqrt(252) as if each represented a full trading day. This structurally
inflates |Sharpe| as a function of trade density rather than of
risk-adjusted performance.

These tests must FAIL against the pre-fix implementation. The failure
output in the commit message of commit 2 is the SD-8 audit trail.
"""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from backtesting.metrics import (
    _ANNUAL_FACTOR_DAILY,
    daily_equity_curve_from_trades,
    daily_returns_from_equity,
    full_report,
    sharpe_ratio,
)
from core.models.order import TradeRecord
from core.models.signal import Direction

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# 2024-01-01 00:00:00 UTC in epoch seconds (a Monday).
_BASE_TS_S = 1_704_067_200
_DAY_MS = 86_400 * 1000


def _make_trade(net_pnl: float, day_offset: int) -> TradeRecord:
    """Construct a TradeRecord that closes at UTC midday on day `day_offset`."""
    pnl = Decimal(str(round(net_pnl, 4)))
    entry = Decimal("50000")
    size = Decimal("0.01")
    # Avoid division-by-zero when net_pnl == 0 by clamping size delta to 0.
    delta = pnl / size if pnl != 0 else Decimal("0")
    exit_p = entry + delta
    exit_ts_ms = (_BASE_TS_S + day_offset * 86_400 + 43_200) * 1000  # midday
    return TradeRecord(
        trade_id=f"t-{day_offset}-{net_pnl}",
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


# ---------------------------------------------------------------------------
# SD-1 — Analytically known Sharpe on sharpe_ratio() directly
# ---------------------------------------------------------------------------


class TestSharpeKnownAnswer:
    """Three analytically-known Sharpe scenarios on the bare helper."""

    def test_a_constant_positive_returns_infinite_sharpe(self) -> None:
        """Zero-variance positive series returns sign-aware +inf.

        The implementation documents this as the correct convention for a
        zero-variance series: consistent gains -> +inf, consistent losses
        -> -inf, flat -> 0.0.
        """
        returns = [0.001] * 100
        assert sharpe_ratio(returns, risk_free_rate=0.0) == float("inf")

    def test_b_mean_001_std_01_daily_gives_expected_annualised_sharpe(self) -> None:
        """252 daily returns with mean=0.001 and pop_std=0.01.

        Analytical Sharpe (rf=0) = (mean / sample_std) * sqrt(252)
        where sample_std = pop_std * sqrt(n / (n-1)).
        For n=252, sample_std = 0.01 * sqrt(252/251) ~ 0.01002.
        Expected annualised Sharpe ~ (0.001 / 0.01002) * sqrt(252) ~ 1.584.
        """
        mu, sigma = 0.001, 0.01
        returns = [mu + sigma if i % 2 == 0 else mu - sigma for i in range(252)]
        computed = sharpe_ratio(returns, risk_free_rate=0.0)
        sample_std = sigma * math.sqrt(252 / 251)
        expected = (mu / sample_std) * math.sqrt(252)
        assert abs(computed - expected) < 0.01, (
            f"Sharpe {computed:.4f} diverged from analytical {expected:.4f} beyond 0.01 tolerance"
        )

    def test_c_negative_mean_gives_negative_annualised_sharpe(self) -> None:
        """252 daily returns with mean=-0.0005 and pop_std=0.01.

        Expected annualised Sharpe (rf=0) ~ -0.792.
        """
        mu, sigma = -0.0005, 0.01
        returns = [mu + sigma if i % 2 == 0 else mu - sigma for i in range(252)]
        computed = sharpe_ratio(returns, risk_free_rate=0.0)
        sample_std = sigma * math.sqrt(252 / 251)
        expected = (mu / sample_std) * math.sqrt(252)
        assert computed < 0, f"expected negative Sharpe, got {computed}"
        assert abs(computed - expected) < 0.01, (
            f"Sharpe {computed:.4f} diverged from analytical {expected:.4f}"
        )


# ---------------------------------------------------------------------------
# SD-8 — Tests that MUST FAIL against the pre-fix implementation
# ---------------------------------------------------------------------------


class TestDenseGridContract:
    """Tests that pin down the dense calendar-day grid contract."""

    def test_full_report_calendar_day_grid_contract(self) -> None:
        """daily_equity_curve must span the full [first_day, last_day] grid.

        Seven calendar days are covered here: trades occur on days 0, 2,
        and 6, so the returned curve must have 8 entries (one seed + days
        0 through 6), not 4 (one seed + 3 active days) as the sparse-day
        impl returns.
        """
        trades = [
            _make_trade(+1000.0, 0),
            _make_trade(+1000.0, 2),
            _make_trade(+1000.0, 6),
        ]
        curve = daily_equity_curve_from_trades(100_000.0, trades)
        # Expected: initial_capital + 7 calendar days (day 0 through day 6).
        assert len(curve) == 8, (
            f"daily_equity_curve has {len(curve)} entries; expected 8 "
            f"(1 seed + 7 days from day 0 through day 6). Sparse-day "
            f"impl returns 4. Curve: {curve}"
        )

    def test_full_report_empty_days_carry_forward(self) -> None:
        """Silent days must carry the previous equity forward."""
        trades = [_make_trade(+1000.0, 0), _make_trade(+1000.0, 6)]
        curve = daily_equity_curve_from_trades(100_000.0, trades)
        # Grid: [seed, day0, day1, day2, day3, day4, day5, day6].
        # day0 closes at 101_000; days 1-5 are silent and carry forward;
        # day 6 closes at 102_000.
        assert curve[0] == pytest.approx(100_000.0)
        assert curve[1] == pytest.approx(101_000.0)
        for i in range(2, 7):
            assert curve[i] == pytest.approx(101_000.0), (
                f"day {i - 1} silent-day equity {curve[i]} did not carry "
                f"forward from day 0 equity 101000"
            )
        assert curve[7] == pytest.approx(102_000.0)

    def test_daily_returns_zero_on_silent_days(self) -> None:
        """daily_returns_from_equity must emit 0.0 for silent (flat) days."""
        trades = [_make_trade(+1000.0, 0), _make_trade(+1000.0, 6)]
        curve = daily_equity_curve_from_trades(100_000.0, trades)
        returns = daily_returns_from_equity(curve)
        # 8-entry curve -> 7 returns, one per calendar day in the span.
        assert len(returns) == 7, f"expected 7 daily returns, got {len(returns)}"
        # days 2..6 in the return list (indices 1..5) are silent carry-forward days.
        for i in range(1, 6):
            assert returns[i] == pytest.approx(0.0, abs=1e-12), (
                f"silent day {i + 1} return {returns[i]} != 0.0"
            )


class TestSharpeInvariantToTradeDensity:
    """A strategy's Sharpe must not be inflated by sparse firing alone."""

    def test_sparse_sharpe_not_inflated_vs_dense(self) -> None:
        """Same total PnL, sparser firing -> Sharpe must not explode.

        Under the BROKEN sparse-day impl, a 3-trade strategy over 30 days
        has 3 daily returns annualised by sqrt(252), producing a Sharpe
        that is inflated by roughly sqrt(252/N_active) relative to a
        dense strategy with the same total return. Under the FIX both are
        annualised on the full 30-day calendar grid.
        """
        dense = [_make_trade(+100.0, d) for d in range(30)]
        sparse = [_make_trade(+1000.0, d) for d in (0, 14, 29)]

        dense_total = sum(float(t.net_pnl) for t in dense)
        sparse_total = sum(float(t.net_pnl) for t in sparse)
        assert dense_total == pytest.approx(sparse_total, rel=1e-9), (
            "test setup: dense and sparse must have identical total PnL"
        )

        r_dense = full_report(dense, initial_capital=100_000.0, risk_free_rate=0.0)
        r_sparse = full_report(sparse, initial_capital=100_000.0, risk_free_rate=0.0)

        assert math.isfinite(r_sparse["sharpe"]), (
            f"sparse Sharpe is non-finite: {r_sparse['sharpe']}"
        )
        # Under the broken impl sparse Sharpe is several hundred due to
        # std collapsing on 3 nearly-identical returns. Under the fix it
        # is bounded by a small multiple of the dense Sharpe.
        assert r_sparse["sharpe"] < 50.0, (
            f"sparse Sharpe ({r_sparse['sharpe']:.2f}) is implausibly high; "
            f"indicates sparse-day annualisation bias. "
            f"Dense Sharpe for the same total PnL was {r_dense['sharpe']:.2f}."
        )

    def test_sparse_sharpe_bounded_by_dense_for_same_total_return(self) -> None:
        """Lumpier PnL (same total) must not produce higher Sharpe.

        Sharpe penalises lumpiness via the denominator; a sparser strategy
        with the same total return must have a Sharpe <= the dense one.
        """
        dense = [_make_trade(+100.0, d) for d in range(30)]
        sparse = [_make_trade(+1000.0, d) for d in (0, 14, 29)]

        r_dense = full_report(dense, initial_capital=100_000.0, risk_free_rate=0.0)
        r_sparse = full_report(sparse, initial_capital=100_000.0, risk_free_rate=0.0)

        if math.isfinite(r_dense["sharpe"]):
            assert r_sparse["sharpe"] <= r_dense["sharpe"] + 1e-6, (
                f"sparse Sharpe ({r_sparse['sharpe']:.4f}) > dense Sharpe "
                f"({r_dense['sharpe']:.4f}) for same total return "
                f"— sparse-day annualisation bias suspected"
            )


class TestKnownAnalyticalSharpeOnFullReport:
    """Direct analytical Sharpe on a full_report() pipeline."""

    def test_full_report_sharpe_matches_analytical_on_30_day_fixture(self) -> None:
        """Build a deterministic 30-day series, check Sharpe end-to-end.

        30 daily trades with alternating PnL that yields deterministic
        mean and std on the daily return series. The bare-helper Sharpe
        (computed on the same daily_returns) is the ground truth; full
        report must match that ground truth exactly (rel=1e-6).
        """
        # Alternating +500 / +100 PnL over 30 consecutive days.
        trades: list[TradeRecord] = []
        for d in range(30):
            pnl = 500.0 if d % 2 == 0 else 100.0
            trades.append(_make_trade(pnl, d))

        report = full_report(trades, initial_capital=100_000.0, risk_free_rate=0.05)

        curve = daily_equity_curve_from_trades(100_000.0, trades)
        returns = daily_returns_from_equity(curve)
        expected_sharpe = sharpe_ratio(
            returns,
            risk_free_rate=0.05,
            annual_factor=_ANNUAL_FACTOR_DAILY,
        )

        assert report["sharpe"] == pytest.approx(expected_sharpe, rel=1e-6), (
            f"full_report sharpe ({report['sharpe']:.6f}) diverged from "
            f"bare-helper ground truth ({expected_sharpe:.6f})"
        )


# ---------------------------------------------------------------------------
# SD-4 — Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge-case coverage: empty, singleton, all losers."""

    def test_empty_trade_list_returns_error(self) -> None:
        report = full_report([], initial_capital=100_000.0)
        assert report == {"error": "no trades"}

    def test_single_trade_sharpe_is_zero_or_sentinel(self) -> None:
        """A single trade -> single daily return -> len(returns) == 1.

        sharpe_ratio() guards len(returns) < 2 by returning 0.0. The
        fixed daily_equity_curve still emits only a 2-entry curve for a
        single-day fixture (first == last), so the guard fires and the
        report surfaces a Sharpe of 0.0.
        """
        trades = [_make_trade(+1000.0, 0)]
        report = full_report(trades, initial_capital=100_000.0)
        assert report["sharpe"] == pytest.approx(0.0)

    def test_all_losers_produce_negative_sharpe(self) -> None:
        """30 losing trades -> mean daily return < 0 -> Sharpe < 0."""
        trades = [_make_trade(-50.0, d) for d in range(30)]
        report = full_report(trades, initial_capital=100_000.0, risk_free_rate=0.0)
        assert report["sharpe"] < 0.0, (
            f"30 losing trades should yield negative Sharpe, got {report['sharpe']}"
        )
