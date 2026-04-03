"""Crowd behaviour analysis for the APEX Trading System Signal Engine.

Tracks options Gamma Exposure (GEX), stop-loss clusters, perpetual funding
rates, open interest, and builds a liquidation heatmap to surface crowd
positioning extremes.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Optional

import numpy as np


class CrowdBehaviorAnalyzer:
    """Analyses crowd-positioning extremes and dealer hedging flows.

    Data is fed incrementally via the ``update_*`` methods; query methods
    derive signals on demand.
    """

    def __init__(self, symbol: str) -> None:
        """Initialize internal state for the given symbol.

        Args:
            symbol: Uppercase trading symbol, e.g. ``'BTCUSDT'``.
        """
        self.symbol = symbol
        # Maps option strike (as float) → net GEX contribution
        self._gex_by_strike: dict[float, float] = {}
        # Rolling funding-rate history (crypto perpetuals)
        self._funding_history: deque[float] = deque(maxlen=200)
        self._latest_funding: float = 0.0
        # Open-interest history (last 10 readings)
        self._oi_history: deque[float] = deque(maxlen=10)
        # Price history used for liquidation level estimation
        self._price_history: deque[float] = deque(maxlen=200)

    # ── GEX ───────────────────────────────────────────────────────────────────

    def update_gex(self, options_data: list[dict]) -> float:
        """Compute and cache GEX from a fresh options chain snapshot.

        Each entry in *options_data* must contain at least the keys
        ``strike`` (float), ``gamma`` (float), and ``open_interest`` (float).
        Calls and puts are distinguished via an optional ``type`` key;
        if absent, the sign of ``gamma`` is used.

        Formula: GEX_i = Gamma_i × OI_i × 100 (dealer-convention sign).

        Args:
            options_data: List of option contract dicts from market data.

        Returns:
            Net GEX value (positive = dealer long gamma, price-stabilising).
        """
        if not options_data:
            return 0.0

        self._gex_by_strike.clear()
        net_gex = 0.0

        for contract in options_data:
            try:
                strike = float(contract["strike"])
                gamma = float(contract["gamma"])
                oi = float(contract["open_interest"])
                # Puts contribute negative GEX (dealer short gamma on puts)
                opt_type = str(contract.get("type", "call")).lower()
                sign = -1.0 if opt_type == "put" else 1.0
                contribution = sign * gamma * oi * 100.0
                self._gex_by_strike[strike] = (
                    self._gex_by_strike.get(strike, 0.0) + contribution
                )
                net_gex += contribution
            except (KeyError, ValueError, TypeError):
                continue

        return net_gex

    def gex_magnet_levels(self) -> list[Decimal]:
        """Return price levels with the largest absolute GEX concentration.

        Dealers hedge aggressively at these strikes, acting as price magnets
        when spot approaches them.

        Returns:
            Strike prices sorted by absolute GEX magnitude (descending),
            as :class:`~decimal.Decimal` instances.
        """
        if not self._gex_by_strike:
            return []

        sorted_strikes = sorted(
            self._gex_by_strike.items(),
            key=lambda item: abs(item[1]),
            reverse=True,
        )
        return [Decimal(str(round(strike, 8))) for strike, _ in sorted_strikes[:10]]

    # ── Stop clusters ─────────────────────────────────────────────────────────

    def stop_cluster_detection(self, prices: list[float]) -> list[float]:
        """Detect price levels where stop-loss orders are likely clustered.

        Uses histogram peak detection on the supplied price series.  Local
        maxima in the distribution represent crowd-consensus support /
        resistance levels where stop orders accumulate.

        Args:
            prices: List of recent trade prices or bar close prices.

        Returns:
            Sorted list of cluster centre prices.
        """
        if len(prices) < 10:
            return []

        arr = np.array(prices)
        n_bins = min(50, max(10, len(prices) // 5))
        counts, edges = np.histogram(arr, bins=n_bins)
        centers = (edges[:-1] + edges[1:]) / 2.0

        peaks: list[float] = []
        for i in range(1, len(counts) - 1):
            if counts[i] > counts[i - 1] and counts[i] > counts[i + 1]:
                peaks.append(float(centers[i]))

        return sorted(peaks)

    # ── Funding rate ──────────────────────────────────────────────────────────

    def update_funding_rate(self, funding_rate: float, symbol: str) -> None:
        """Record the latest perpetual funding rate for a symbol.

        Args:
            funding_rate: Funding rate as a decimal (e.g. ``0.0001`` = 0.01%).
            symbol: Symbol being updated (stored for reference only).
        """
        self._latest_funding = funding_rate
        self._funding_history.append(funding_rate)

    def funding_extreme(self) -> Optional[str]:
        """Classify the current funding rate as a crowd extreme.

        Returns:
            ``'long_crowded'`` when funding > +0.01% (longs paying),
            ``'short_crowded'`` when funding < -0.01% (shorts paying),
            ``None`` otherwise.
        """
        if self._latest_funding > 0.0001:
            return "long_crowded"
        if self._latest_funding < -0.0001:
            return "short_crowded"
        return None

    # ── Open interest ─────────────────────────────────────────────────────────

    def update_open_interest(self, oi: float) -> None:
        """Append a new open-interest reading to the rolling history.

        Args:
            oi: Current open interest (notional or contract count).
        """
        self._oi_history.append(oi)

    def oi_trend(self) -> Optional[str]:
        """Classify the recent open-interest trend from the last 5 readings.

        Returns:
            ``'rising'`` if OI has increased monotonically over the last
            5 readings, ``'falling'`` if it has decreased monotonically,
            ``None`` if trend is mixed or fewer than 5 readings exist.
        """
        if len(self._oi_history) < 5:
            return None

        readings = list(self._oi_history)[-5:]
        if all(readings[i] < readings[i + 1] for i in range(len(readings) - 1)):
            return "rising"
        if all(readings[i] > readings[i + 1] for i in range(len(readings) - 1)):
            return "falling"
        return None

    # ── Liquidation heatmap ───────────────────────────────────────────────────

    def liquidation_heatmap(self) -> dict[str, list[float]]:
        """Estimate price levels where leveraged positions face liquidation.

        Uses the running price history to identify where clustered long and
        short positions are likely to be underwater.  Longs accumulate below
        the current price (liquidated on drops); shorts accumulate above it
        (liquidated on rallies).

        Returns:
            Dict with keys ``'longs'`` and ``'shorts'``, each containing a
            list of price levels sorted nearest-to-price first.
        """
        if len(self._price_history) < 20:
            return {"longs": [], "shorts": []}

        prices = np.array(self._price_history)
        current_price = float(prices[-1])
        price_std = float(np.std(prices, ddof=1))

        # Multipliers represent ±½σ through ±2½σ bands around the current
        # price.  These correspond roughly to common exchange leverage tiers
        # (5×–20×) where isolated-margin positions face liquidation, providing
        # five granular levels per side without overwhelming the consumer.
        multipliers = [0.5, 1.0, 1.5, 2.0, 2.5]
        longs = sorted(
            [round(current_price - m * price_std, 8) for m in multipliers
             if current_price - m * price_std > 0],
            reverse=True,  # nearest first
        )
        shorts = sorted(
            [round(current_price + m * price_std, 8) for m in multipliers],
        )
        return {"longs": longs, "shorts": shorts}

    def update_price(self, price: float) -> None:
        """Append a price observation used for liquidation heatmap estimation.

        Args:
            price: Latest trade price.
        """
        self._price_history.append(price)
