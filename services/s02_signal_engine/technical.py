"""Technical analysis for the APEX Trading System Signal Engine.

Builds multi-timeframe OHLCV bars from a raw tick stream and exposes
RSI (Wilder's method), Bollinger Bands, EMA, VWAP, ATR, and volume-
profile indicators.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal

import numpy as np

from core.models.tick import NormalizedTick

# Timeframe labels and their durations in milliseconds.
_TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}
_MAX_BARS = 500  # Maximum completed bars retained per timeframe.


class TechnicalAnalyzer:
    """Constructs multi-timeframe OHLCV bars and computes technical indicators.

    Bars are assembled in real time as ticks arrive via :meth:`update`.
    Indicator methods read from the completed bars plus the in-progress
    current bar for each timeframe.
    """

    def __init__(self, symbol: str) -> None:
        """Initialize per-timeframe bar storage and VWAP accumulators.

        Args:
            symbol: Uppercase trading symbol, e.g. ``'AAPL'``.
        """
        self.symbol = symbol

        # Completed bars per timeframe.  Each bar is a dict:
        # {open, high, low, close, volume, timestamp_ms}
        self._bars: dict[str, deque[dict]] = {tf: deque(maxlen=_MAX_BARS) for tf in _TIMEFRAME_MS}
        # In-progress (current) bar per timeframe.
        self._current: dict[str, dict | None] = dict.fromkeys(_TIMEFRAME_MS)

        # Daily VWAP accumulators (reset at midnight UTC).
        self._vwap_day: int = -1
        self._vwap_cum_pv: float = 0.0
        self._vwap_cum_v: float = 0.0

    # ── Bar construction ──────────────────────────────────────────────────────

    def update(self, tick: NormalizedTick) -> None:
        """Ingest a tick and advance all timeframe bars.

        When a tick's timestamp falls outside the current bar's period, the
        current bar is closed and a new one is opened.

        Args:
            tick: Incoming normalized tick.
        """
        price = float(tick.price)
        volume = float(tick.volume)
        ts = tick.timestamp_ms

        for tf, period_ms in _TIMEFRAME_MS.items():
            bar_start = (ts // period_ms) * period_ms
            current = self._current[tf]

            if current is None or current["timestamp_ms"] != bar_start:
                if current is not None:
                    self._bars[tf].append(current)
                self._current[tf] = {
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": volume,
                    "timestamp_ms": bar_start,
                }
            else:
                current["high"] = max(current["high"], price)
                current["low"] = min(current["low"], price)
                current["close"] = price
                current["volume"] += volume

        # Daily VWAP accumulators - reset at midnight UTC.
        day_start = (ts // 86_400_000) * 86_400_000
        if self._vwap_day != day_start:
            self._vwap_day = day_start
            self._vwap_cum_pv = 0.0
            self._vwap_cum_v = 0.0
        self._vwap_cum_pv += price * volume
        self._vwap_cum_v += volume

    # ── Helper ────────────────────────────────────────────────────────────────

    def _all_bars(self, timeframe: str) -> list[dict]:
        """Return completed bars plus the current in-progress bar.

        Args:
            timeframe: Timeframe label such as ``'5m'``.

        Returns:
            Chronologically ordered list of bar dicts.
        """
        result = list(self._bars[timeframe])
        current = self._current[timeframe]
        if current is not None:
            result.append(current)
        return result

    def _compute_rsi_from_closes(self, closes: list[float], period: int) -> float | None:
        """Compute RSI via Wilder's smoothing from a list of close prices.

        Args:
            closes: Sequence of close prices (oldest first).
            period: RSI smoothing period.

        Returns:
            RSI value in [0, 100], or ``None`` if fewer than *period* + 1
            prices are supplied.
        """
        if len(closes) < period + 1:
            return None

        changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [max(0.0, c) for c in changes[:period]]
        losses = [max(0.0, -c) for c in changes[:period]]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        for change in changes[period:]:
            avg_gain = (avg_gain * (period - 1) + max(0.0, change)) / period
            avg_loss = (avg_loss * (period - 1) + max(0.0, -change)) / period

        if avg_loss == 0.0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    # ── Indicators ────────────────────────────────────────────────────────────

    def rsi(self, period: int = 14, timeframe: str = "1m") -> float | None:
        """RSI using Wilder's exponential smoothing method.

        Args:
            period: Smoothing period (default 14).
            timeframe: Bar timeframe to use (default ``'1m'``).

        Returns:
            RSI in [0, 100], or ``None`` if insufficient bars exist.
        """
        bars = self._all_bars(timeframe)
        closes = [b["close"] for b in bars]
        return self._compute_rsi_from_closes(closes, period)

    def rsi_divergence(self, timeframe: str = "5m") -> str | None:
        """Detect bullish or bearish RSI divergence over recent bars.

        Compares the direction of price trend with the direction of RSI
        trend across two consecutive windows of 14 bars each.

        * Price falling + RSI rising → bullish divergence
        * Price rising  + RSI falling → bearish divergence

        Args:
            timeframe: Bar timeframe to analyse (default ``'5m'``).

        Returns:
            ``'bullish'``, ``'bearish'``, or ``None``.
        """
        bars = self._all_bars(timeframe)
        if len(bars) < 28:
            return None

        # Two non-overlapping windows of 14 bars, plus 14 bars of seed context.
        all_closes = [b["close"] for b in bars[-42:]]
        if len(all_closes) < 28:
            return None

        # RSI at end of each window uses full history up to that window.
        mid = len(all_closes) // 2
        rsi_older = self._compute_rsi_from_closes(all_closes[:mid], 14)
        rsi_newer = self._compute_rsi_from_closes(all_closes, 14)

        if rsi_older is None or rsi_newer is None:
            return None

        # Average close for each half as the price-trend proxy.
        older_closes = all_closes[:mid]
        newer_closes = all_closes[mid:]
        price_up = (sum(newer_closes) / len(newer_closes)) > (sum(older_closes) / len(older_closes))
        rsi_up = rsi_newer > rsi_older

        if not price_up and rsi_up:
            return "bullish"
        if price_up and not rsi_up:
            return "bearish"
        return None

    def bollinger_bands(
        self,
        period: int = 20,
        std: float = 2.0,
        timeframe: str = "5m",
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        """Compute Bollinger Bands (upper, middle, lower).

        Args:
            period: Moving average period (default 20).
            std: Standard-deviation multiplier (default 2.0).
            timeframe: Bar timeframe to use (default ``'5m'``).

        Returns:
            Tuple of ``(upper, middle, lower)`` as :class:`~decimal.Decimal`
            instances, or ``(None, None, None)`` if insufficient data.
        """
        bars = self._all_bars(timeframe)
        closes = [b["close"] for b in bars]
        if len(closes) < period:
            return None, None, None

        arr = np.array(closes[-period:])
        sma = float(np.mean(arr))
        std_val = float(np.std(arr, ddof=1))

        upper = Decimal(str(round(sma + std * std_val, 8)))
        middle = Decimal(str(round(sma, 8)))
        lower = Decimal(str(round(sma - std * std_val, 8)))
        return upper, middle, lower

    def bb_squeeze(self, timeframe: str = "5m") -> bool:
        """Detect a Bollinger Band squeeze - BB width at its 6-period minimum.

        A squeeze occurs when the current Bollinger Band width is at or below
        the minimum width seen over the prior 5 bar-windows.  This signals
        low volatility preceding a potential breakout.

        Args:
            timeframe: Bar timeframe to analyse (default ``'5m'``).

        Returns:
            ``True`` when the current BB width is at its 6-period minimum.
        """
        bars = self._all_bars(timeframe)
        if len(bars) < 26:
            return False

        widths: list[float] = []
        for i in range(6):
            end = len(bars) - i
            start = end - 20
            if start < 0:
                return False
            arr = np.array([b["close"] for b in bars[start:end]])
            widths.append(4.0 * float(np.std(arr, ddof=1)))

        # A squeeze is confirmed when the current period's width is at or below
        # the minimum of all 6 periods (i.e. it is the 6-period minimum itself).
        return widths[0] <= min(widths)

    def ema(self, period: int, timeframe: str = "5m") -> Decimal | None:
        """Exponential moving average of bar close prices.

        Seeded from a simple average of the first *period* values, then
        smoothed with multiplier k = 2 / (period + 1).

        Args:
            period: EMA period.
            timeframe: Bar timeframe to use (default ``'5m'``).

        Returns:
            Current EMA as a :class:`~decimal.Decimal`, or ``None`` if fewer
            than *period* bars are available.
        """
        bars = self._all_bars(timeframe)
        closes = [b["close"] for b in bars]
        if len(closes) < period:
            return None

        k = 2.0 / (period + 1.0)
        ema_val = sum(closes[:period]) / period
        for price in closes[period:]:
            ema_val = price * k + ema_val * (1.0 - k)
        return Decimal(str(round(ema_val, 8)))

    def vwap(self) -> Decimal | None:
        """Daily Volume-Weighted Average Price.

        Accumulates price × volume and total volume from the first tick of
        each UTC calendar day.  Resets automatically at midnight.

        Returns:
            Current VWAP as a :class:`~decimal.Decimal`, or ``None`` if no
            volume has been recorded today.
        """
        if self._vwap_cum_v == 0.0:
            return None
        vwap_val = self._vwap_cum_pv / self._vwap_cum_v
        return Decimal(str(round(vwap_val, 8)))

    def atr(self, period: int = 14, timeframe: str = "5m") -> Decimal | None:
        """Average True Range using Wilder's exponential smoothing.

        True Range = max(H − L, |H − prev_C|, |L − prev_C|).

        Args:
            period: ATR smoothing period (default 14).
            timeframe: Bar timeframe to use (default ``'5m'``).

        Returns:
            ATR as a :class:`~decimal.Decimal`, or ``None`` if insufficient
            bars exist.
        """
        bars = self._all_bars(timeframe)
        if len(bars) < period + 1:
            return None

        recent = bars[-(period + 1) :]
        trs: list[float] = []
        for i in range(1, len(recent)):
            h = recent[i]["high"]
            lo = recent[i]["low"]
            prev_c = recent[i - 1]["close"]
            trs.append(max(h - lo, abs(h - prev_c), abs(lo - prev_c)))

        if not trs:
            return None

        atr_val = sum(trs[:period]) / period
        for tr in trs[period:]:
            atr_val = (atr_val * (period - 1) + tr) / period
        return Decimal(str(round(atr_val, 8)))

    def volume_profile(self, bins: int = 50) -> dict[str, Decimal | None]:
        """Compute volume-profile metrics: POC, VAH, VAL.

        Volume is distributed across *bins* equally-spaced price levels.

        * **POC** (Point of Control): price level with the highest volume.
        * **VAH** (Value Area High) / **VAL** (Value Area Low): outer bounds
          of the contiguous region containing 70% of total volume, sorted by
          volume from the busiest bin outward.

        Args:
            bins: Number of price buckets (default 50).

        Returns:
            Dict with keys ``'poc'``, ``'vah'``, ``'val'``, each being a
            :class:`~decimal.Decimal` or ``None``.
        """
        all_bars = self._all_bars("5m")
        if not all_bars:
            return {"poc": None, "vah": None, "val": None}

        prices = np.array([(b["high"] + b["low"]) / 2.0 for b in all_bars], dtype=float)
        volumes = np.array([b["volume"] for b in all_bars], dtype=float)

        price_min, price_max = float(prices.min()), float(prices.max())
        if price_min == price_max:
            poc = Decimal(str(round(price_min, 8)))
            return {"poc": poc, "vah": poc, "val": poc}

        bin_edges = np.linspace(price_min, price_max, bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0
        bin_volumes = np.zeros(bins, dtype=float)

        for price, vol in zip(prices, volumes, strict=False):
            idx = min(int(np.searchsorted(bin_edges[1:], price)), bins - 1)
            bin_volumes[idx] += vol

        poc_idx = int(np.argmax(bin_volumes))
        poc_price = float(bin_centers[poc_idx])

        total_vol = float(bin_volumes.sum())
        if total_vol == 0.0:
            poc = Decimal(str(round(poc_price, 8)))
            return {"poc": poc, "vah": poc, "val": poc}

        target_vol = total_vol * 0.70
        sorted_indices = np.argsort(bin_volumes)[::-1]
        cumulative = 0.0
        included: list[int] = []
        for idx in sorted_indices:
            cumulative += bin_volumes[idx]
            included.append(int(idx))
            if cumulative >= target_vol:
                break

        va_prices = bin_centers[included]
        return {
            "poc": Decimal(str(round(poc_price, 8))),
            "vah": Decimal(str(round(float(va_prices.max()), 8))),
            "val": Decimal(str(round(float(va_prices.min()), 8))),
        }
