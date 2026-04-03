"""Advanced market microstructure metrics for APEX Trading System."""

from __future__ import annotations

import numpy as np


class AdvancedMicrostructure:
    """Advanced market microstructure analysis including illiquidity and order flow."""

    def amihud_ratio(self, returns: list[float], volumes: list[float]) -> float:
        """Compute the Amihud (2002) illiquidity ratio.

        ILLIQ_t = mean(|r_t| / volume_t)

        Args:
            returns: List of period return values.
            volumes: List of corresponding traded volumes.

        Returns:
            Mean illiquidity ratio as a float, or 0.0 if volumes are empty or zero.
        """
        if not returns or not volumes:
            return 0.0
        n = min(len(returns), len(volumes))
        ratios = []
        for i in range(n):
            if volumes[i] > 0.0:
                ratios.append(abs(returns[i]) / volumes[i])
        if not ratios:
            return 0.0
        return float(np.mean(ratios))

    def pin_estimate(self, buy_trades: list[float], sell_trades: list[float]) -> float:
        """Compute a simplified Probability of Informed Trading (PIN) estimate.

        PIN = α×μ / (α×μ + 2×ε)
        where:
          α  = std(imbalance) / mean(total)   (fraction of informed trading)
          μ  = mean(|buy - sell|)              (informed order arrival rate)
          ε  = mean(min(buy, sell))            (uninformed order arrival rate)

        Args:
            buy_trades: Sequence of buy-side trade sizes or counts.
            sell_trades: Sequence of sell-side trade sizes or counts.

        Returns:
            PIN estimate in [0, 1], or 0.0 if input data is insufficient.
        """
        if not buy_trades or not sell_trades:
            return 0.0
        n = min(len(buy_trades), len(sell_trades))
        if n == 0:
            return 0.0

        buys = np.array(buy_trades[:n], dtype=float)
        sells = np.array(sell_trades[:n], dtype=float)
        total = buys + sells
        imbalance = buys - sells

        mean_total = float(np.mean(total))
        if mean_total == 0.0:
            return 0.0

        alpha = float(np.std(imbalance)) / mean_total
        mu = float(np.mean(np.abs(imbalance)))
        epsilon = float(np.mean(np.minimum(buys, sells)))

        denominator = alpha * mu + 2.0 * epsilon
        if denominator == 0.0:
            return 0.0
        return float(alpha * mu / denominator)

    def hawkes_intensity(
        self,
        event_times: list[float],
        mu: float = 0.1,
        alpha: float = 0.5,
        beta: float = 1.0,
    ) -> float:
        """Compute the current Hawkes process intensity λ(t).

        λ(t) = μ + Σ_{t_i < t} α × exp(-β × (t - t_i))

        Args:
            event_times: Sorted list of event timestamps.
            mu: Background intensity (μ).
            alpha: Excitation coefficient (α).
            beta: Decay rate (β).

        Returns:
            Current intensity evaluated at the last timestamp in event_times.
            Returns mu if event_times has fewer than two entries.
        """
        if not event_times:
            return mu
        if len(event_times) == 1:
            return mu

        t = event_times[-1]
        prior_times = event_times[:-1]
        excitation = sum(alpha * float(np.exp(-beta * (t - t_i))) for t_i in prior_times if t_i < t)
        return mu + excitation
