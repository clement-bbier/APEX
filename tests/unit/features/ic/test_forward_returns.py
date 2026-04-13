"""Tests for features.ic.forward_returns — forward return computation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from features.ic.forward_returns import compute_forward_returns


def _make_bars(n: int, base_price: float = 100.0) -> pl.DataFrame:
    """Create a simple synthetic bar DataFrame."""
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    return pl.DataFrame(
        {
            "timestamp": [base_time + timedelta(minutes=5 * i) for i in range(n)],
            "close": [base_price + i * 1.0 for i in range(n)],
        }
    )


class TestComputeForwardReturns:
    """compute_forward_returns correctness."""

    def test_length_and_nan_tail(self) -> None:
        """Output has same length as input; last h rows are null."""
        bars = _make_bars(50)
        h = 5
        result = compute_forward_returns(bars, horizon_bars=h)
        assert len(result) == 50
        fwd = result["forward_return"].to_numpy()
        # Last h values must be NaN.
        assert np.all(np.isnan(fwd[-h:]))
        # First n-h values must be finite.
        assert np.all(np.isfinite(fwd[:-h]))

    def test_manual_computation(self) -> None:
        """Forward return matches log(price[t+h] / price[t])."""
        prices = [100.0, 110.0, 121.0, 133.1, 146.41]
        bars = pl.DataFrame(
            {
                "timestamp": [
                    datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(5)
                ],
                "close": prices,
            }
        )
        result = compute_forward_returns(bars, horizon_bars=2)
        fwd = result["forward_return"].to_numpy()
        # fwd[0] = log(121/100), fwd[1] = log(133.1/110), fwd[2] = log(146.41/121)
        assert fwd[0] == pytest.approx(np.log(121.0 / 100.0), abs=1e-10)
        assert fwd[1] == pytest.approx(np.log(133.1 / 110.0), abs=1e-10)
        assert fwd[2] == pytest.approx(np.log(146.41 / 121.0), abs=1e-10)
        assert np.isnan(fwd[3])
        assert np.isnan(fwd[4])

    def test_horizon_1_is_simple_log_return(self) -> None:
        """h=1 forward return = log(price[t+1] / price[t])."""
        bars = _make_bars(20)
        result = compute_forward_returns(bars, horizon_bars=1)
        fwd = result["forward_return"].to_numpy()
        prices = bars["close"].to_numpy()
        for t in range(19):
            expected = np.log(prices[t + 1] / prices[t])
            assert fwd[t] == pytest.approx(expected, abs=1e-12)
        assert np.isnan(fwd[19])

    def test_invalid_horizon_raises(self) -> None:
        bars = _make_bars(10)
        with pytest.raises(ValueError, match="horizon_bars must be >= 1"):
            compute_forward_returns(bars, horizon_bars=0)

    def test_missing_column_raises(self) -> None:
        df = pl.DataFrame({"timestamp": [datetime(2024, 1, 1, tzinfo=UTC)], "price": [100.0]})
        with pytest.raises(ValueError, match="Missing required columns"):
            compute_forward_returns(df, horizon_bars=1)
