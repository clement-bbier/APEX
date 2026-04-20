"""PSR/DSR excess-return consistency tests for :func:`full_report`.

Exercises issue #195 (part 2) and ADR-0002 mandatory evaluation
checklist item 5: PSR and DSR must be computed on the same
excess-return series as the headline Sharpe. If PSR/DSR use raw
returns while Sharpe uses excess returns, the reported PSR/DSR are
confidence statements about a *different* point estimate than the one
the gate compares to — the entire PSR gate becomes statistically
incoherent.

Companion file to
``tests/unit/backtesting/test_full_report_sharpe.py`` which landed in
PR #204 and covered the sparse-day annualisation bias (issue #102,
first half of #195).
"""

from __future__ import annotations

import math
from decimal import Decimal

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backtesting.metrics import (
    _ANNUAL_FACTOR_DAILY,
    daily_equity_curve_from_trades,
    daily_returns_from_equity,
    deflated_sharpe_ratio,
    full_report,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
)
from core.models.order import TradeRecord
from core.models.signal import Direction

# ---------------------------------------------------------------------------
# Fixture helpers (mirrors test_full_report_sharpe.py to keep the test style
# uniform across the two halves of issue #195).
# ---------------------------------------------------------------------------

_BASE_TS_S = 1_704_067_200  # 2024-01-01 00:00:00 UTC (Monday)


def _make_trade(net_pnl: float, day_offset: int) -> TradeRecord:
    """Construct a TradeRecord closing at UTC midday on ``day_offset``."""
    pnl = Decimal(str(round(net_pnl, 4)))
    entry = Decimal("50000")
    size = Decimal("0.01")
    delta = pnl / size if pnl != 0 else Decimal("0")
    exit_p = entry + delta
    exit_ts_ms = (_BASE_TS_S + day_offset * 86_400 + 43_200) * 1000
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


def _deterministic_pnls(n_days: int, mu: float, sigma: float, seed: int) -> list[float]:
    """Reproducible mean-positive daily PnL series (on $100k capital)."""
    rng = np.random.default_rng(seed)
    returns = rng.standard_normal(n_days) * sigma + mu
    # Convert fractional returns to PnL dollars on 100k capital.
    return [float(r * 100_000.0) for r in returns]


# ---------------------------------------------------------------------------
# Unit test (a) — PSR/DSR must be consistent with Sharpe at rf=0.
# ---------------------------------------------------------------------------


class TestRfZeroConsistency:
    """When rf=0, raw returns *are* excess returns — consistency is trivial."""

    def test_full_report_rf_zero_bootstrap_ci_brackets_sharpe(self) -> None:
        """sharpe_ci_95_low <= report['sharpe'] <= sharpe_ci_95_high."""
        pnls = _deterministic_pnls(60, mu=0.0015, sigma=0.012, seed=11)
        trades = [_make_trade(p, d) for d, p in enumerate(pnls)]
        report = full_report(
            trades,
            initial_capital=100_000.0,
            risk_free_rate_annual=Decimal("0"),
        )
        assert math.isfinite(report["sharpe"])
        assert math.isfinite(report["sharpe_ci_95_low"])
        assert math.isfinite(report["sharpe_ci_95_high"])
        assert report["sharpe_ci_95_low"] <= report["sharpe"] <= report["sharpe_ci_95_high"], (
            f"95% bootstrap CI [{report['sharpe_ci_95_low']:.4f}, "
            f"{report['sharpe_ci_95_high']:.4f}] does not bracket the "
            f"Sharpe point estimate {report['sharpe']:.4f}"
        )

    def test_full_report_rf_zero_psr_matches_helper_on_excess_series(self) -> None:
        """PSR inside full_report equals PSR recomputed from excess returns."""
        pnls = _deterministic_pnls(120, mu=0.001, sigma=0.01, seed=3)
        trades = [_make_trade(p, d) for d, p in enumerate(pnls)]
        report = full_report(
            trades,
            initial_capital=100_000.0,
            risk_free_rate_annual=Decimal("0"),
        )
        # rf=0 → excess == raw, so helper on raw matches the report.
        curve = daily_equity_curve_from_trades(100_000.0, trades)
        daily_ret = daily_returns_from_equity(curve)
        psr_helper = probabilistic_sharpe_ratio(
            daily_ret, benchmark_sharpe=0.0, annual_factor=_ANNUAL_FACTOR_DAILY
        )
        assert report["psr"] == pytest.approx(psr_helper, rel=1e-9, abs=1e-12)


# ---------------------------------------------------------------------------
# Unit test (b) — With a non-zero rf, Sharpe AND PSR/DSR all shift in the
# same direction and the CI still brackets Sharpe.
# ---------------------------------------------------------------------------


class TestNonZeroRiskFreeRate:
    """A positive rate must deflate both Sharpe and PSR/DSR together."""

    def test_rf_four_percent_lowers_sharpe_and_psr_together(self) -> None:
        """Sharpe(rf=0) > Sharpe(rf=0.04); same for PSR and DSR."""
        pnls = _deterministic_pnls(200, mu=0.0012, sigma=0.01, seed=17)
        trades = [_make_trade(p, d) for d, p in enumerate(pnls)]
        report_zero = full_report(
            trades,
            initial_capital=100_000.0,
            risk_free_rate_annual=Decimal("0"),
            n_trials=10,
        )
        report_four = full_report(
            trades,
            initial_capital=100_000.0,
            risk_free_rate_annual=Decimal("0.04"),
            n_trials=10,
        )
        # Mean-positive returns: deflating by rf reduces Sharpe.
        assert report_zero["sharpe"] > report_four["sharpe"], (
            f"Sharpe at rf=0 ({report_zero['sharpe']:.4f}) must exceed "
            f"Sharpe at rf=0.04 ({report_four['sharpe']:.4f})"
        )
        # PSR/DSR must move in the same direction as Sharpe.
        assert report_zero["psr"] >= report_four["psr"] - 1e-9, (
            f"PSR at rf=0 ({report_zero['psr']:.4f}) must be >= "
            f"PSR at rf=0.04 ({report_four['psr']:.4f}) for a mean-positive series"
        )
        assert report_zero["dsr"] >= report_four["dsr"] - 1e-9, (
            f"DSR at rf=0 ({report_zero['dsr']:.4f}) must be >= "
            f"DSR at rf=0.04 ({report_four['dsr']:.4f}) for a mean-positive series"
        )

    def test_rf_four_percent_bootstrap_ci_brackets_sharpe(self) -> None:
        """Bracket property holds with rf > 0 — CI is built on excess series."""
        pnls = _deterministic_pnls(200, mu=0.0012, sigma=0.01, seed=17)
        trades = [_make_trade(p, d) for d, p in enumerate(pnls)]
        report = full_report(
            trades,
            initial_capital=100_000.0,
            risk_free_rate_annual=Decimal("0.04"),
        )
        assert report["sharpe_ci_95_low"] <= report["sharpe"] <= report["sharpe_ci_95_high"], (
            f"95% bootstrap CI [{report['sharpe_ci_95_low']:.4f}, "
            f"{report['sharpe_ci_95_high']:.4f}] does not bracket the "
            f"rf=0.04 Sharpe point estimate {report['sharpe']:.4f}"
        )

    def test_decimal_param_overrides_legacy_float(self) -> None:
        """risk_free_rate_annual wins over the legacy risk_free_rate kwarg."""
        pnls = _deterministic_pnls(100, mu=0.001, sigma=0.01, seed=5)
        trades = [_make_trade(p, d) for d, p in enumerate(pnls)]
        # Legacy float says 0.05, but the Decimal kwarg explicitly says 0.
        report_overridden = full_report(
            trades,
            initial_capital=100_000.0,
            risk_free_rate=0.05,
            risk_free_rate_annual=Decimal("0"),
        )
        report_zero_only = full_report(
            trades,
            initial_capital=100_000.0,
            risk_free_rate=0.0,
        )
        assert report_overridden["sharpe"] == pytest.approx(report_zero_only["sharpe"], rel=1e-9)
        assert report_overridden["psr"] == pytest.approx(report_zero_only["psr"], rel=1e-9)

    def test_legacy_float_still_works_when_decimal_is_none(self) -> None:
        """Default behaviour: omitting risk_free_rate_annual uses legacy float."""
        pnls = _deterministic_pnls(80, mu=0.0008, sigma=0.01, seed=7)
        trades = [_make_trade(p, d) for d, p in enumerate(pnls)]
        # Two equivalent call styles must agree.
        a = full_report(trades, initial_capital=100_000.0, risk_free_rate=0.03)
        b = full_report(
            trades,
            initial_capital=100_000.0,
            risk_free_rate_annual=Decimal("0.03"),
        )
        assert a["sharpe"] == pytest.approx(b["sharpe"], rel=1e-9)
        assert a["psr"] == pytest.approx(b["psr"], rel=1e-9)
        assert a["dsr"] == pytest.approx(b["dsr"], rel=1e-9)


# ---------------------------------------------------------------------------
# Hypothesis property test (c) — 1000 examples, bracket property holds.
# ---------------------------------------------------------------------------


class TestBracketPropertyUnderRandomness:
    """The bootstrap CI must bracket the Sharpe point estimate by construction.

    With Sharpe, PSR, DSR and the bootstrap CI all built on the SAME
    excess-return series, ``sharpe_ci_95_low <= sharpe <= sharpe_ci_95_high``
    is a by-construction property modulo two caveats:

    * Fewer than two observations -> CI collapses to ``(0.0, 0.0)`` while
      Sharpe itself also collapses to ``0.0`` (guarded by ``len < 2`` in
      ``sharpe_ratio``).
    * Zero-variance series -> CI collapses to ``(point, point)``.

    Both edge cases still satisfy the bracket trivially.
    """

    @given(
        n_days=st.integers(min_value=10, max_value=100),
        mu_bp=st.integers(min_value=-50, max_value=50),  # basis points per day
        sigma_bp=st.integers(min_value=25, max_value=300),
        rf_bp=st.integers(min_value=0, max_value=1000),  # 0% to 10% annual
        seed=st.integers(min_value=0, max_value=10_000),
    )
    @settings(
        max_examples=1000,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.data_too_large,
            HealthCheck.function_scoped_fixture,
        ],
    )
    def test_bootstrap_ci_brackets_sharpe(
        self,
        n_days: int,
        mu_bp: int,
        sigma_bp: int,
        rf_bp: int,
        seed: int,
    ) -> None:
        mu = mu_bp / 10_000.0
        sigma = max(sigma_bp / 10_000.0, 1e-6)
        rng = np.random.default_rng(seed)
        pnls = (rng.standard_normal(n_days) * sigma + mu) * 100_000.0
        trades = [_make_trade(float(p), d) for d, p in enumerate(pnls)]

        rf_annual = Decimal(str(rf_bp / 10_000.0))
        report = full_report(
            trades,
            initial_capital=100_000.0,
            risk_free_rate_annual=rf_annual,
        )
        if "error" in report:
            return  # empty trades guard never triggers for n_days>=10, but be safe.

        sharpe = report["sharpe"]
        ci_low = report["sharpe_ci_95_low"]
        ci_high = report["sharpe_ci_95_high"]

        # Handle the infinity / zero-variance sentinels documented on
        # sharpe_ratio. They all satisfy the bracket trivially.
        if math.isinf(sharpe) or math.isnan(sharpe):
            return

        # Small numerical slack for the bootstrap percentile: the point
        # Sharpe may sit *on* the percentile rather than strictly inside
        # when the bootstrap distribution is very concentrated.
        tol = 1e-6 + 1e-6 * abs(sharpe)
        assert ci_low - tol <= sharpe <= ci_high + tol, (
            f"bracket violated: ci_low={ci_low:.6f}, sharpe={sharpe:.6f}, "
            f"ci_high={ci_high:.6f}, n_days={n_days}, mu_bp={mu_bp}, "
            f"sigma_bp={sigma_bp}, rf_bp={rf_bp}, seed={seed}"
        )

        # PSR/DSR must remain well-defined probabilities.
        assert 0.0 <= report["psr"] <= 1.0
        assert 0.0 <= report["dsr"] <= 1.0


# ---------------------------------------------------------------------------
# Negative test (d) — Documents the pre-fix bug.
# ---------------------------------------------------------------------------


class TestPreFixBugDocumented:
    """If PSR is called on raw returns with rf != 0, its result drifts away
    from the PSR the report would emit on the correct excess series.

    This test is a regression anchor: it fails if someone reverts the fix
    or pipes raw returns into PSR inside full_report.
    """

    def test_psr_on_raw_vs_excess_differs_when_rf_nonzero(self) -> None:
        pnls = _deterministic_pnls(252, mu=0.0012, sigma=0.01, seed=99)
        trades = [_make_trade(p, d) for d, p in enumerate(pnls)]
        curve = daily_equity_curve_from_trades(100_000.0, trades)
        daily_ret = daily_returns_from_equity(curve)

        rf_annual = 0.05
        rf_per_period = rf_annual / (_ANNUAL_FACTOR_DAILY**2)
        excess = [r - rf_per_period for r in daily_ret]

        psr_raw = probabilistic_sharpe_ratio(daily_ret)
        psr_excess = probabilistic_sharpe_ratio(excess)

        # The bug: PSR on raw vs excess diverges when rf != 0. Require a
        # visible gap so a revert to the pre-fix path would fail this test.
        assert abs(psr_raw - psr_excess) > 1e-4, (
            "PSR on raw and on excess series collapsed to the same value — "
            "the pre-fix bug path would not be detectable. Adjust the "
            "fixture until the divergence is material."
        )

        # And the report must track the excess-series PSR, NOT the raw one.
        report = full_report(
            trades,
            initial_capital=100_000.0,
            risk_free_rate_annual=Decimal(str(rf_annual)),
        )
        assert report["psr"] == pytest.approx(psr_excess, rel=1e-9, abs=1e-12), (
            f"full_report PSR ({report['psr']:.6f}) must match the "
            f"excess-series helper ({psr_excess:.6f}), NOT the raw-series "
            f"value ({psr_raw:.6f})."
        )

    def test_sharpe_report_equals_helper_on_excess_series(self) -> None:
        """Cross-check: report['sharpe'] matches sharpe_ratio on raw returns
        with the resolved rf — i.e. the two code paths agree by construction.
        """
        pnls = _deterministic_pnls(180, mu=0.0009, sigma=0.01, seed=31)
        trades = [_make_trade(p, d) for d, p in enumerate(pnls)]
        rf_annual = 0.03
        report = full_report(
            trades,
            initial_capital=100_000.0,
            risk_free_rate_annual=Decimal(str(rf_annual)),
        )
        curve = daily_equity_curve_from_trades(100_000.0, trades)
        daily_ret = daily_returns_from_equity(curve)
        expected = sharpe_ratio(
            daily_ret,
            risk_free_rate=rf_annual,
            annual_factor=_ANNUAL_FACTOR_DAILY,
        )
        assert report["sharpe"] == pytest.approx(expected, rel=1e-9, abs=1e-12)

    def test_dsr_report_equals_helper_on_excess_series(self) -> None:
        """Cross-check the DSR wiring end-to-end."""
        pnls = _deterministic_pnls(180, mu=0.0009, sigma=0.01, seed=57)
        trades = [_make_trade(p, d) for d, p in enumerate(pnls)]
        rf_annual = 0.04
        n_trials = 25
        report = full_report(
            trades,
            initial_capital=100_000.0,
            risk_free_rate_annual=Decimal(str(rf_annual)),
            n_trials=n_trials,
        )
        curve = daily_equity_curve_from_trades(100_000.0, trades)
        daily_ret = daily_returns_from_equity(curve)
        rf_per_period = rf_annual / (_ANNUAL_FACTOR_DAILY**2)
        excess = [r - rf_per_period for r in daily_ret]
        expected_dsr = deflated_sharpe_ratio(
            excess,
            n_trials=n_trials,
            annual_factor=_ANNUAL_FACTOR_DAILY,
            benchmark_sharpe=0.0,
        )
        assert report["dsr"] == pytest.approx(expected_dsr, rel=1e-9, abs=1e-12)
