"""Triple Barrier Method — Ground Truth Labels for Meta-Labeling.

The Triple Barrier Method (López de Prado 2018, Chapter 3) defines the
"outcome" of a trade using THREE barriers:

    1. UPPER BARRIER (Take Profit): price rises by +pt_sl[0] × vol × price
    2. LOWER BARRIER (Stop Loss):   price falls by -pt_sl[1] × vol × price
    3. VERTICAL BARRIER (Time Limit): position held for > max_holding_periods bars

Label mapping:
    +1  → Upper barrier touched first (TP hit → success)
     0  → Vertical barrier (time-out → inconclusive)
    -1  → Lower barrier touched first (SL hit → failure)

For SHORT trades, the upper/lower barriers are swapped:
    price FALLS to lower_barrier → label +1 (success for short)
    price RISES to upper_barrier → label -1 (failure for short)

Dynamic barrier sizing (vol-adaptive):
    barrier = multiplier × daily_vol × entry_price
    High-vol regime: wider barriers → fewer time-outs, cleaner labels
    Low-vol regime: tighter barriers → faster labeling

The labeled dataset feeds the MetaLabeler in OBJ-5:
    After 3 months of paper trading, ~5,000-15,000 (features, label) pairs
    are available to train a supervised binary classifier (MetaLabeler v2).

Reference:
    López de Prado, M. (2018). Advances in Financial Machine Learning.
    Wiley. Chapter 3, Sections 3.1-3.4.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class BarrierResult(Enum):
    """Which barrier was touched first."""

    UPPER = 1  # Take Profit → label +1
    LOWER = -1  # Stop Loss   → label -1
    VERTICAL = 0  # Time-out   → label 0


@dataclass(frozen=True)
class BarrierLabel:
    """Complete result of Triple Barrier labeling for one entry event."""

    entry_time: datetime
    exit_time: datetime
    entry_price: Decimal
    exit_price: Decimal
    barrier_hit: BarrierResult
    label: int  # +1, 0, or -1
    upper_barrier: Decimal  # Absolute TP price level
    lower_barrier: Decimal  # Absolute SL price level
    vertical_barrier: datetime  # Max hold deadline
    side: int  # +1 = LONG, -1 = SHORT
    vol_used: float  # Volatility used to size barriers
    holding_periods: int  # Bars held before exit


@dataclass
class TripleBarrierConfig:
    """Configuration for Triple Barrier labeling."""

    pt_multiplier: float = 2.0  # Upper barrier multiplier
    sl_multiplier: float = 1.0  # Lower barrier multiplier
    max_holding_periods: int = 60  # Vertical barrier in bars
    vol_lookback: int = 20  # Vol estimation lookback


class TripleBarrierLabeler:
    """Labels historical trades using the Triple Barrier Method.

    Used OFFLINE on historical data to generate ground truth labels.
    These labels are stored in meta_label_log.triple_barrier_label
    and used to train/validate MetaLabeler v2.

    Usage:
        labeler = TripleBarrierLabeler(config)
        label = labeler.label_event(
            entry_price=entry_px, entry_time=ts, side=+1,
            future_prices=[(ts1, p1), (ts2, p2), ...],
            daily_vol=0.015,
        )
    """

    def __init__(self, config: TripleBarrierConfig | None = None) -> None:
        self.config = config or TripleBarrierConfig()

    def compute_daily_vol(self, close_prices: list[Decimal]) -> float:
        """Estimate daily volatility from close-to-close log returns.

        Returns estimated vol as a fraction (e.g. 0.015 = 1.5% daily).
        Requires a strict minimum of 2 positive prices. ADR-0005 D1
        mandates fail-loud behaviour: insufficient data raises
        ``ValueError`` rather than returning a silent default.

        Zero-variance inputs (constant prices) are a legitimate signal
        of a dead market and return ``0.0``; the caller is expected to
        reject that volatility via ``label_event``'s own guard.

        Raises:
            ValueError: when fewer than 2 prices are provided or no
                valid log-return can be computed from the series.
        """
        if len(close_prices) < 2:
            raise ValueError(
                f"compute_daily_vol requires at least 2 prices, got {len(close_prices)}"
            )
        log_returns = [
            math.log(float(close_prices[i]) / float(close_prices[i - 1]))
            for i in range(1, len(close_prices))
            if float(close_prices[i - 1]) > 0
        ]
        if not log_returns:
            raise ValueError(
                "compute_daily_vol could not derive any log return; "
                "all prior prices are non-positive"
            )
        mean = sum(log_returns) / len(log_returns)
        variance = sum((r - mean) ** 2 for r in log_returns) / max(1, len(log_returns) - 1)
        return math.sqrt(max(0.0, variance))

    def label_event(
        self,
        entry_price: Decimal,
        entry_time: datetime,
        side: int,
        future_prices: list[tuple[datetime, Decimal]],
        daily_vol: float,
    ) -> BarrierLabel:
        """Apply Triple Barrier to one entry event.

        Args:
            entry_price: Price at the moment of entry signal.
            entry_time: Timestamp of the entry signal (UTC).
            side: +1 for LONG signal, -1 for SHORT signal.
            future_prices: Ordered list of (timestamp, price) bars after entry.
                           Length determines the vertical barrier width.
            daily_vol: Estimated daily volatility at entry time (e.g. 0.015).

        Returns:
            BarrierLabel with the outcome, exit price/time, holding periods.
        """
        if daily_vol <= 0:
            raise ValueError(
                f"daily_vol must be strictly positive at entry_time={entry_time}, "
                f"got {daily_vol}. ADR-0005 D1 forbids silent 1e-8 floors; "
                "the caller must either raise on zero-variance inputs or skip the event."
            )

        if not future_prices:
            return BarrierLabel(
                entry_time=entry_time,
                exit_time=entry_time,
                entry_price=entry_price,
                exit_price=entry_price,
                barrier_hit=BarrierResult.VERTICAL,
                label=0,
                upper_barrier=entry_price,
                lower_barrier=entry_price,
                vertical_barrier=entry_time,
                side=side,
                vol_used=daily_vol,
                holding_periods=0,
            )

        vol_move = Decimal(str(daily_vol * float(entry_price)))
        upper_barrier = entry_price + Decimal(str(self.config.pt_multiplier)) * vol_move
        lower_barrier = entry_price - Decimal(str(self.config.sl_multiplier)) * vol_move

        max_periods = min(self.config.max_holding_periods, len(future_prices))
        vertical_barrier_time = future_prices[max_periods - 1][0]

        for i, (ts, price) in enumerate(future_prices[:max_periods]):
            if side == 1:  # LONG
                if price >= upper_barrier:
                    return BarrierLabel(
                        entry_time=entry_time,
                        exit_time=ts,
                        entry_price=entry_price,
                        exit_price=price,
                        barrier_hit=BarrierResult.UPPER,
                        label=1,
                        upper_barrier=upper_barrier,
                        lower_barrier=lower_barrier,
                        vertical_barrier=vertical_barrier_time,
                        side=side,
                        vol_used=daily_vol,
                        holding_periods=i + 1,
                    )
                if price <= lower_barrier:
                    return BarrierLabel(
                        entry_time=entry_time,
                        exit_time=ts,
                        entry_price=entry_price,
                        exit_price=price,
                        barrier_hit=BarrierResult.LOWER,
                        label=-1,
                        upper_barrier=upper_barrier,
                        lower_barrier=lower_barrier,
                        vertical_barrier=vertical_barrier_time,
                        side=side,
                        vol_used=daily_vol,
                        holding_periods=i + 1,
                    )
            else:  # SHORT — barriers inverted
                if price <= lower_barrier:  # SHORT TP
                    return BarrierLabel(
                        entry_time=entry_time,
                        exit_time=ts,
                        entry_price=entry_price,
                        exit_price=price,
                        barrier_hit=BarrierResult.UPPER,
                        label=1,
                        upper_barrier=upper_barrier,
                        lower_barrier=lower_barrier,
                        vertical_barrier=vertical_barrier_time,
                        side=side,
                        vol_used=daily_vol,
                        holding_periods=i + 1,
                    )
                if price >= upper_barrier:  # SHORT SL
                    return BarrierLabel(
                        entry_time=entry_time,
                        exit_time=ts,
                        entry_price=entry_price,
                        exit_price=price,
                        barrier_hit=BarrierResult.LOWER,
                        label=-1,
                        upper_barrier=upper_barrier,
                        lower_barrier=lower_barrier,
                        vertical_barrier=vertical_barrier_time,
                        side=side,
                        vol_used=daily_vol,
                        holding_periods=i + 1,
                    )

        # Vertical barrier (time-out)
        exit_ts, exit_px = future_prices[max_periods - 1]
        return BarrierLabel(
            entry_time=entry_time,
            exit_time=exit_ts,
            entry_price=entry_price,
            exit_price=exit_px,
            barrier_hit=BarrierResult.VERTICAL,
            label=0,
            upper_barrier=upper_barrier,
            lower_barrier=lower_barrier,
            vertical_barrier=vertical_barrier_time,
            side=side,
            vol_used=daily_vol,
            holding_periods=max_periods,
        )


def to_binary_target(label: BarrierLabel) -> int:
    """Project a ternary ``BarrierLabel`` to the binary Meta-Labeler target.

    Per ADR-0005 D1, the Meta-Labeler consumes the binary projection
    ``y = 1 iff BarrierLabel.label == +1 else 0``. Vertical-barrier
    time-outs (``label == 0``) and lower-barrier hits (``label == -1``)
    both map to ``0`` — "no profitable edge taken".

    Intra-bar tie convention (upper wins): in the core ``label_event``
    loop, the upper-barrier condition is tested before the lower-barrier
    condition on every bar (see ``TripleBarrierLabeler.label_event``
    ~L161 and ~L193). When a single future bar touches both barriers,
    ``BarrierResult.UPPER`` is emitted and this helper returns ``1``.
    The convention is deliberate: long-only Meta-Labeler training
    favours the optimistic interpretation when the evidence is
    ambiguous, which aligns with the MetaLabelGate bet-sizing
    philosophy (gate on confidence, size via Kelly).

    Args:
        label: Any ``BarrierLabel`` from ``TripleBarrierLabeler``.

    Returns:
        ``1`` iff ``label.label == +1`` (upper barrier hit), else ``0``.

    References:
        López de Prado (2018), Advances in Financial Machine Learning,
        Chapter 3.6 (Meta-Labeling).
        ADR-0005 D1 — binary target projection.
    """
    return 1 if label.label == 1 else 0
