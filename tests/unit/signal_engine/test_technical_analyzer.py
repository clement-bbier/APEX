"""Unit tests for TechnicalAnalyzer.

Tests RSI, Bollinger Bands, EMA, VWAP, ATR by feeding synthetic ticks
at 5-minute intervals. Each tick at a new 5m boundary closes the prior bar.
No Redis, no ZMQ, no network.
"""

from __future__ import annotations

from decimal import Decimal

from core.models.tick import Market, NormalizedTick, TradeSide
from services.s02_signal_engine.technical import TechnicalAnalyzer

_5M_MS = 300_000  # milliseconds per 5-minute bar


def _tick(
    price: float,
    bar_index: int,
    volume: float = 100.0,
    symbol: str = "BTCUSDT",
) -> NormalizedTick:
    """Build a tick that starts a new 5m bar at bar_index."""
    return NormalizedTick(
        symbol=symbol,
        market=Market.CRYPTO,
        timestamp_ms=bar_index * _5M_MS + 1,  # +1 to land inside the bar
        price=Decimal(str(price)),
        volume=Decimal(str(volume)),
        side=TradeSide.BUY,
        bid=Decimal(str(price * 0.9999)),
        ask=Decimal(str(price * 1.0001)),
    )


def _feed_prices(ta: TechnicalAnalyzer, prices: list[float]) -> None:
    """Feed one tick per 5m bar to build bars for indicator computation."""
    for i, p in enumerate(prices):
        ta.update(_tick(p, bar_index=i))


class TestRSI:
    """RSI = 100 - 100/(1+RS), RS = avg_gain/avg_loss over 14 periods."""

    def test_returns_none_before_enough_bars(self) -> None:
        ta = TechnicalAnalyzer("BTCUSDT")
        # Feed only 10 bars — RSI(14) needs ≥ 15
        _feed_prices(ta, [100.0] * 10)
        assert ta.rsi(timeframe="5m") is None

    def test_high_rsi_on_consistent_rising_prices(self) -> None:
        ta = TechnicalAnalyzer("BTCUSDT")
        # 25 monotonically rising bars → RSI should be > 70
        prices = [100.0 + i * 0.5 for i in range(25)]
        _feed_prices(ta, prices)
        rsi = ta.rsi(timeframe="5m")
        assert rsi is not None
        assert rsi > 70.0, f"Expected RSI > 70 for rising prices, got {rsi}"

    def test_low_rsi_on_consistent_falling_prices(self) -> None:
        ta = TechnicalAnalyzer("BTCUSDT")
        # 25 monotonically falling bars → RSI should be < 30
        prices = [100.0 - i * 0.5 for i in range(25)]
        _feed_prices(ta, prices)
        rsi = ta.rsi(timeframe="5m")
        assert rsi is not None
        assert rsi < 30.0, f"Expected RSI < 30 for falling prices, got {rsi}"

    def test_rsi_always_in_valid_range(self) -> None:
        import numpy as np

        ta = TechnicalAnalyzer("BTCUSDT")
        rng = np.random.default_rng(42)
        # Feed 30 bars with random walk prices
        prices = [100.0]
        for _ in range(29):
            prices.append(prices[-1] * (1 + rng.normal(0, 0.01)))
        _feed_prices(ta, prices)
        rsi = ta.rsi(timeframe="5m")
        if rsi is not None:
            assert 0.0 <= rsi <= 100.0


class TestBollingerBands:
    """BB = SMA(20) ± 2σ(20)."""

    def test_returns_none_before_enough_bars(self) -> None:
        ta = TechnicalAnalyzer("BTCUSDT")
        _feed_prices(ta, [100.0] * 15)
        upper, _middle, lower = ta.bollinger_bands(timeframe="5m")
        assert upper is None or lower is None

    def test_upper_above_middle_above_lower(self) -> None:
        ta = TechnicalAnalyzer("BTCUSDT")
        # Feed 25 bars with slight random variation
        import numpy as np

        rng = np.random.default_rng(0)
        prices = [100.0 + rng.normal(0, 1.0) for _ in range(25)]
        _feed_prices(ta, prices)
        upper, middle, lower = ta.bollinger_bands(timeframe="5m")
        if upper is not None and middle is not None and lower is not None:
            assert upper >= middle >= lower

    def test_bands_squeeze_on_flat_prices(self) -> None:
        """Constant price -> std ~= 0 -> upper ~= middle ~= lower."""
        ta = TechnicalAnalyzer("BTCUSDT")
        _feed_prices(ta, [100.0] * 25)
        upper, _middle, lower = ta.bollinger_bands(timeframe="5m")
        if upper is not None and lower is not None:
            width = float(upper - lower)
            assert width < 1.0  # very narrow bands for flat prices


class TestEMA:
    """EMA(n) = price×α + EMA_prev×(1-α), α = 2/(n+1)."""

    def test_returns_none_before_enough_bars(self) -> None:
        ta = TechnicalAnalyzer("BTCUSDT")
        _feed_prices(ta, [100.0] * 3)
        assert ta.ema(period=8, timeframe="5m") is None

    def test_ema_follows_price_direction(self) -> None:
        ta_up = TechnicalAnalyzer("BTCUSDT")
        ta_down = TechnicalAnalyzer("BTCUSDT")
        rising = [100.0 + i * 0.5 for i in range(25)]
        falling = [100.0 - i * 0.5 for i in range(25)]
        _feed_prices(ta_up, rising)
        _feed_prices(ta_down, falling)
        ema_up = ta_up.ema(period=8, timeframe="5m")
        ema_down = ta_down.ema(period=8, timeframe="5m")
        if ema_up is not None and ema_down is not None:
            assert ema_up > ema_down

    def test_fast_ema_above_slow_ema_in_uptrend(self) -> None:
        ta = TechnicalAnalyzer("BTCUSDT")
        prices = [100.0 + i * 0.3 for i in range(30)]
        _feed_prices(ta, prices)
        ema_fast = ta.ema(period=8, timeframe="5m")
        ema_slow = ta.ema(period=21, timeframe="5m")
        if ema_fast is not None and ema_slow is not None:
            assert float(ema_fast) >= float(ema_slow)


class TestVWAP:
    """VWAP = Σ(P × V) / Σ(V), resets daily at midnight UTC."""

    def test_vwap_equals_price_when_uniform_volume(self) -> None:
        ta = TechnicalAnalyzer("BTCUSDT")
        # All ticks at same price, same volume → VWAP = that price
        for i in range(5):
            ta.update(_tick(price=100.0, bar_index=i))
        vwap = ta.vwap()
        assert vwap is not None
        assert abs(float(vwap) - 100.0) < 0.01

    def test_vwap_not_none_after_first_tick(self) -> None:
        ta = TechnicalAnalyzer("BTCUSDT")
        ta.update(_tick(price=42000.0, bar_index=0))
        vwap = ta.vwap()
        assert vwap is not None

    def test_vwap_weighted_toward_high_volume_price(self) -> None:
        """When volume is concentrated at one price, VWAP should be close to it."""
        ta = TechnicalAnalyzer("BTCUSDT")
        # Low volume at 100, very high volume at 110
        ta.update(
            NormalizedTick(
                symbol="BTCUSDT",
                market=Market.CRYPTO,
                timestamp_ms=1,
                price=Decimal("100"),
                volume=Decimal("1"),  # very low volume
                bid=Decimal("99.99"),
                ask=Decimal("100.01"),
            )
        )
        ta.update(
            NormalizedTick(
                symbol="BTCUSDT",
                market=Market.CRYPTO,
                timestamp_ms=2,
                price=Decimal("110"),
                volume=Decimal("1000"),  # very high volume
                bid=Decimal("109.99"),
                ask=Decimal("110.01"),
            )
        )
        vwap = ta.vwap()
        assert vwap is not None
        assert float(vwap) > 109.0  # VWAP should be close to 110


class TestATR:
    """ATR = EMA(TrueRange, 14), TR = max(H-L, |H-Cp|, |L-Cp|)."""

    def test_returns_none_before_enough_bars(self) -> None:
        ta = TechnicalAnalyzer("BTCUSDT")
        _feed_prices(ta, [100.0] * 10)
        assert ta.atr(timeframe="5m") is None

    def test_atr_not_none_after_enough_bars(self) -> None:
        ta = TechnicalAnalyzer("BTCUSDT")
        _feed_prices(ta, [100.0 + i * 0.1 for i in range(20)])
        atr = ta.atr(timeframe="5m")
        assert atr is not None

    def test_atr_non_negative(self) -> None:
        ta = TechnicalAnalyzer("BTCUSDT")
        _feed_prices(ta, [100.0 + i * 0.1 for i in range(20)])
        atr = ta.atr(timeframe="5m")
        if atr is not None:
            assert float(atr) >= 0.0
