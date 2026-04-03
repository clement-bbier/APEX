"""Microstructure analysis for the APEX Trading System Signal Engine.

Computes real-time microstructure metrics - OFI, CVD, Kyle's Lambda,
spread evolution, trade intensity, and absorption detection - from a
rolling window of normalized tick data.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from core.models.tick import NormalizedTick, TradeSide


class MicrostructureAnalyzer:
    """Computes real-time microstructure metrics from a rolling tick window.

    All metrics operate on fixed-size deque buffers populated by
    :meth:`update`.  Values are normalized to [-1, 1] where possible so
    that downstream signal scoring can treat them uniformly.
    """

    def __init__(self, symbol: str, window: int = 100) -> None:
        """Initialize rolling buffers.

        Args:
            symbol: Uppercase trading symbol, e.g. ``'BTCUSDT'``.
            window: Maximum number of ticks to retain in each buffer.
        """
        self.symbol = symbol
        self.window = window

        self.prices: deque[float] = deque(maxlen=window)
        self.volumes: deque[float] = deque(maxlen=window)
        # bid_vols / ask_vols store best-bid and best-ask *prices* as the
        # closest available proxy for queue-level volumes in NormalizedTick.
        self.bid_vols: deque[float] = deque(maxlen=window)
        self.ask_vols: deque[float] = deque(maxlen=window)
        self.buy_vols: deque[float] = deque(maxlen=window)
        self.sell_vols: deque[float] = deque(maxlen=window)
        self.timestamps: deque[int] = deque(maxlen=window)

    # ── Public interface ──────────────────────────────────────────────────────

    def update(self, tick: NormalizedTick) -> None:
        """Update all rolling buffers with a new incoming tick.

        Args:
            tick: Freshly normalized tick from the data-ingestion layer.
        """
        self.prices.append(float(tick.price))
        self.volumes.append(float(tick.volume))
        self.bid_vols.append(float(tick.bid) if tick.bid is not None else 0.0)
        self.ask_vols.append(float(tick.ask) if tick.ask is not None else 0.0)
        self.buy_vols.append(float(tick.volume) if tick.side == TradeSide.BUY else 0.0)
        self.sell_vols.append(float(tick.volume) if tick.side == TradeSide.SELL else 0.0)
        self.timestamps.append(tick.timestamp_ms)

    def ofi(self) -> float:
        """Order Flow Imbalance: Σ(ΔBid − ΔAsk) normalised by total volume.

        Uses consecutive changes in best-bid and best-ask prices as a proxy
        for changes in queue volume at each level.

        Returns:
            OFI in the range [-1, 1], or ``0.0`` if fewer than 2 ticks have
            been recorded.
        """
        if len(self.bid_vols) < 2:
            return 0.0

        bids = np.array(self.bid_vols)
        asks = np.array(self.ask_vols)
        imbalance = float(np.sum(np.diff(bids) - np.diff(asks)))

        total_vol = float(np.sum(self.volumes))
        if total_vol == 0.0:
            return 0.0
        return imbalance / total_vol

    def cvd(self) -> float:
        """Cumulative Volume Delta: Σ(buy_vol − sell_vol) normalised by total.

        Returns:
            CVD in the range [-1, 1], or ``0.0`` if fewer than 2 ticks have
            been recorded.
        """
        if len(self.buy_vols) < 2:
            return 0.0

        total_vol = float(np.sum(self.volumes))
        if total_vol == 0.0:
            return 0.0

        delta = float(np.sum(np.array(self.buy_vols) - np.array(self.sell_vols)))
        return delta / total_vol

    def kyle_lambda(self) -> float:
        """Kyle's Lambda: price-impact coefficient Cov(ΔP, Q) / Var(Q).

        *Q* is signed volume - positive for buyer-initiated trades, negative
        for seller-initiated trades.  Pairs Q[t] with ΔP[t] = P[t+1] − P[t].

        Returns:
            Lambda as a float, or ``0.0`` if fewer than 3 ticks are available
            or if variance of signed volume is zero.
        """
        if len(self.prices) < 3:
            return 0.0

        prices = np.array(self.prices)
        delta_p = np.diff(prices)  # length N-1

        buys = np.array(self.buy_vols)
        sells = np.array(self.sell_vols)
        # Q[:-1] are the orders that *cause* ΔP; pair by dropping the last Q.
        signed_vol = (buys - sells)[:-1]

        var_q = float(np.var(signed_vol, ddof=1)) if len(signed_vol) > 1 else 0.0
        if var_q == 0.0:
            return 0.0

        cov_matrix = np.cov(delta_p, signed_vol, ddof=1)
        return float(cov_matrix[0, 1] / var_q)

    def spread_evolution(self) -> float:
        """Average bid-ask spread in basis points over the current window.

        Skips ticks where either bid or ask is zero (unavailable).

        Returns:
            Mean spread in bps, or ``0.0`` if no valid bid/ask pairs exist.
        """
        if len(self.bid_vols) < 2:
            return 0.0

        bids = np.array(self.bid_vols)
        asks = np.array(self.ask_vols)
        valid = (bids > 0.0) & (asks > 0.0) & (asks > bids)
        if not np.any(valid):
            return 0.0

        mid = (bids[valid] + asks[valid]) / 2.0
        spreads_bps = ((asks[valid] - bids[valid]) / mid) * 10_000.0
        return float(np.mean(spreads_bps))

    def trade_intensity(self) -> float:
        """Trades per second recorded in the current rolling window.

        Returns:
            Trades-per-second as a float, or ``0.0`` if fewer than 2 ticks.
        """
        if len(self.timestamps) < 2:
            return 0.0

        elapsed_ms = self.timestamps[-1] - self.timestamps[0]
        if elapsed_ms <= 0:
            return 0.0

        return float(len(self.timestamps)) / (elapsed_ms / 1_000.0)

    def absorption_detected(self) -> bool:
        """Detect potential buying absorption of heavy sell pressure.

        A large sell event (> mean + 2σ of the sell-volume distribution) is
        flagged as *absorbed* when the concurrent price move is smaller than
        the mean absolute price change over the window - suggesting the sell
        flow was met by willing buyers without moving price.

        Returns:
            ``True`` if a large sell volume coincides with price stability.
        """
        if len(self.sell_vols) < 10 or len(self.prices) < 10:
            return False

        sell_arr = np.array(self.sell_vols)
        sell_mean = float(np.mean(sell_arr))
        sell_std = float(np.std(sell_arr, ddof=1))
        threshold = sell_mean + 2.0 * sell_std

        if sell_arr[-1] <= threshold:
            return False

        price_arr = np.array(self.prices)
        lookback = min(5, len(price_arr) - 1)
        recent_move = abs(float(price_arr[-1]) - float(price_arr[-1 - lookback]))
        atr_proxy = float(np.mean(np.abs(np.diff(price_arr))))

        if atr_proxy == 0.0:
            return False

        return (recent_move / atr_proxy) < 1.0
