"""Hedge trigger logic for APEX Trading System - S04 Fusion Engine.

Determines whether a counter-directional hedge should accompany the primary
signal, the direction of the hedge, and its size as a fraction of the
reference position.
"""

from __future__ import annotations

from decimal import Decimal

from core.models.regime import Regime
from core.models.signal import Direction, Signal, TechnicalFeatures

# Fraction of the reference size used for the hedge position.
_HEDGE_FRACTION = Decimal("0.3")

# Threshold below which OFI is considered "close to zero" (GEX pinning).
_OFI_PIN_THRESHOLD = 0.1


class HedgeTrigger:
    """Evaluates conditions that warrant a counter-directional hedge order.

    Hedge is recommended when **any** of the following conditions is met:

    - RSI divergence on the 1-minute timeframe (``features.rsi_1m``
      disagrees with signal direction).
    - Price is at a Bollinger Band extreme (upper for LONG, lower for SHORT).
    - GEX pinning: OFI magnitude below :data:`_OFI_PIN_THRESHOLD`.
    - Pre-CB event block is active (``regime.macro.event_active``).
    """

    def should_hedge(
        self,
        signal: Signal,
        features: TechnicalFeatures,
        regime: Regime,
        reference_size: Decimal,
    ) -> tuple[bool, Direction | None, Decimal | None]:
        """Decide whether a hedge order should be placed alongside the signal.

        Args:
            signal:         The primary trade signal.
            features:       Technical indicator snapshot at signal time.
            regime:         Current market regime snapshot.
            reference_size: The primary position size in quote-currency units.
                            The hedge size is computed as a fraction of this value.

        Returns:
            A three-tuple ``(hedge_bool, hedge_direction, hedge_size)``:

            - ``hedge_bool``      : ``True`` if a hedge is warranted.
            - ``hedge_direction`` : Opposite of the signal direction, or ``None``.
            - ``hedge_size``      : Size of the hedge in quote-currency units,
                                    or ``None`` if no hedge.
        """
        reasons: list[str] = []

        # ── RSI divergence (1m) ───────────────────────────────────────────────
        if features.rsi_1m is not None:
            if signal.direction == Direction.LONG and features.rsi_1m > 70.0:
                reasons.append("rsi_1m_divergence")
            elif signal.direction == Direction.SHORT and features.rsi_1m < 30.0:
                reasons.append("rsi_1m_divergence")

        # ── Bollinger Band extreme ─────────────────────────────────────────────
        if features.bb_upper is not None and features.bb_lower is not None:
            price = signal.entry
            if signal.direction == Direction.LONG and price >= features.bb_upper:
                reasons.append("bb_extreme")
            elif signal.direction == Direction.SHORT and price <= features.bb_lower:
                reasons.append("bb_extreme")

        # ── GEX pinning (OFI near zero) ────────────────────────────────────────
        if features.ofi is not None and abs(features.ofi) < _OFI_PIN_THRESHOLD:
            reasons.append("gex_pin")

        # ── Pre-CB event block ────────────────────────────────────────────────
        if regime.macro.event_active:
            reasons.append("cb_event_active")

        if not reasons:
            return False, None, None

        hedge_direction = Direction.SHORT if signal.direction == Direction.LONG else Direction.LONG
        hedge_size = reference_size * _HEDGE_FRACTION
        return True, hedge_direction, hedge_size
