"""S03 Regime Detector service for APEX Trading System.

Polls Redis for macro data every 30 seconds, computes the current market
regime, writes the result back to Redis, and publishes it on ZMQ.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from core.base_service import BaseService
from core.models.regime import (
    MacroContext,
    Regime,
    RiskMode,
    SessionContext,
    TrendRegime,
    VolRegime,
)
from services.s03_regime_detector.cb_calendar import CBCalendar
from services.s03_regime_detector.regime_engine import RegimeEngine
from services.s03_regime_detector.session_tracker import (
    PRIME_SESSIONS,
    Session,
    SessionTracker,
)

_POLL_INTERVAL_S: int = 30
_REGIME_KEY = "regime:current"
_CB_KEY = "cb:calendar"
_REGIME_ZMQ_TOPIC = "regime.update"


class RegimeDetectorService(BaseService):
    """Periodically computes and publishes the market regime.

    Every 30 seconds the service:
    1. Reads ``macro:vix``, ``macro:dxy``, ``macro:yield_spread`` from Redis.
    2. Calls :class:`~.regime_engine.RegimeEngine` and
       :class:`~.session_tracker.SessionTracker` to build a
       :class:`~core.models.regime.Regime` snapshot.
    3. Persists the regime to Redis as ``regime:current``.
    4. Publishes it on the ZMQ topic ``regime.update``.
    5. Refreshes the CB calendar in Redis as ``cb:calendar``.
    """

    service_id = "s03_regime_detector"

    def __init__(self) -> None:
        """Initialize regime components (PUB socket created by BaseService.start)."""
        super().__init__(self.service_id)
        self._engine = RegimeEngine()
        self._session = SessionTracker()
        self._calendar = CBCalendar()

    # ── BaseService interface ─────────────────────────────────────────────────

    async def on_message(self, topic: str, data: dict[str, Any]) -> None:
        """No-op - the regime detector does not subscribe to any topics.

        Args:
            topic: Incoming ZMQ topic (unused).
            data:  Message payload (unused).
        """

    async def run(self) -> None:
        """Main loop: compute and publish the regime every 30 seconds."""
        self.logger.info("RegimeDetectorService starting", service=self.service_id)
        await self._calendar.load_schedule()

        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                self.logger.error(
                    "Regime tick error",
                    service=self.service_id,
                    error=str(exc),
                    exc_info=exc,
                )
            await asyncio.sleep(_POLL_INTERVAL_S)

    # ── Internal pipeline ─────────────────────────────────────────────────────

    async def _tick(self) -> None:
        """Execute one regime-detection cycle."""
        now = datetime.now(UTC)
        now_ms = int(now.timestamp() * 1000)

        # ── Read macro inputs ─────────────────────────────────────────────────
        vix_raw = await self.state.get("macro:vix")
        dxy_raw = await self.state.get("macro:dxy")
        spread_raw = await self.state.get("macro:yield_spread")

        vix: float | None = float(vix_raw) if vix_raw is not None else None
        dxy: float | None = float(dxy_raw) if dxy_raw is not None else None
        yield_spread: float | None = float(spread_raw) if spread_raw is not None else None

        # ── Session context (DST-aware) ────────────────────────────────────────
        session: Session = self._session.get_session(now)
        session_mult = self._session.get_multiplier(session)
        us_sessions = {
            Session.US_OPEN,
            Session.US_MORNING,
            Session.US_LUNCH,
            Session.US_AFTERNOON,
            Session.US_CLOSE,
        }
        session_ctx = SessionContext(
            timestamp_ms=now_ms,
            session=session.value,
            session_mult=session_mult,
            is_us_prime=session in PRIME_SESSIONS,
            is_us_open=session in us_sessions,
        )

        # ── CB calendar ────────────────────────────────────────────────────────
        event_active = self._calendar.active_block()
        post_event_scalp = self._calendar.post_event_scalp_active()
        next_event = self._calendar.next_event()
        upcoming = self._calendar.events_within_hours(24)

        # ── Macro context ─────────────────────────────────────────────────────
        macro_mult = self._engine.compute_macro_mult(vix, dxy, yield_spread)
        macro_ctx = MacroContext(
            timestamp_ms=now_ms,
            vix=vix,
            dxy=dxy,
            yield_spread_10y2y=yield_spread,
            macro_mult=macro_mult,
            event_active=event_active,
            post_event_scalp=post_event_scalp,
        )

        # ── Regime values ─────────────────────────────────────────────────────
        vol_regime: VolRegime = self._engine.compute_vol_regime(vix)
        circuit_open = await self._is_circuit_open()
        risk_mode: RiskMode = self._engine.compute_risk_mode(vol_regime, event_active, circuit_open)

        # Trend requires price history; default to RANGING when unavailable.
        trend_regime: TrendRegime = TrendRegime.RANGING

        # ── Assemble Regime snapshot ───────────────────────────────────────────
        regime = Regime(
            timestamp_ms=now_ms,
            trend_regime=trend_regime,
            vol_regime=vol_regime,
            risk_mode=risk_mode,
            macro=macro_ctx,
            session=session_ctx,
            cb_calendar=upcoming,
            next_cb_event=next_event,
            macro_mult=macro_mult,
            session_mult=session_ctx.session_mult,
        )

        regime_dict = regime.model_dump(mode="json")

        # ── Persist and publish ────────────────────────────────────────────────
        cb_events_dicts = [e.model_dump(mode="json") for e in upcoming]

        await asyncio.gather(
            self.state.set(_REGIME_KEY, regime_dict),
            self.state.set(_CB_KEY, cb_events_dicts),
            self.bus.publish(_REGIME_ZMQ_TOPIC, regime_dict),
        )

        self.logger.info(
            "Regime updated",
            vol_regime=vol_regime.value,
            risk_mode=risk_mode.value,
            session=session_ctx.session,
            macro_mult=macro_mult,
            event_active=event_active,
        )

    async def _update_regime(self) -> None:
        """Recompute regime using Phase-2 engine with live macro data from Redis.

        Reads VIX, DXY, and yield data published by S08 MacroIntelligence
        and writes the result to Redis for all downstream services.
        """
        from core.topics import Topics

        vix_data = await self.state.get("macro:vix:current")
        dxy_data = await self.state.get("macro:dxy:1h_change")
        yield_data = await self.state.get("macro:yields:current")

        vix = float(vix_data.get("value", 20.0)) if isinstance(vix_data, dict) else 20.0
        dxy_change = float(dxy_data.get("pct_change", 0.0)) if isinstance(dxy_data, dict) else 0.0
        yield_10y = float(yield_data.get("y10", 4.5)) if isinstance(yield_data, dict) else 4.5
        yield_2y = float(yield_data.get("y2", 5.0)) if isinstance(yield_data, dict) else 5.0

        regime = self._engine.compute(
            vix=vix,
            dxy_1h_change_pct=dxy_change,
            yield_10y=yield_10y,
            yield_2y=yield_2y,
        )

        await self.state.set(
            "regime:current:v2",
            {
                "vol_regime": regime.vol_regime,
                "risk_mode": regime.risk_mode,
                "macro_mult": regime.macro_mult,
                "vix": regime.vix,
                "yield_inverted": regime.yield_curve_inverted,
                "reasoning": regime.reasoning,
            },
        )

        await self.bus.publish(
            Topics.REGIME_UPDATE,
            {
                "macro_mult": regime.macro_mult,
                "vol_regime": regime.vol_regime,
            },
        )

        self.logger.info(
            "regime_updated_v2",
            macro_mult=regime.macro_mult,
            vol_regime=regime.vol_regime,
            reasoning=regime.reasoning,
        )

    async def _is_circuit_open(self) -> bool:
        """Check whether the circuit breaker flag is set in Redis.

        Returns:
            ``True`` if the circuit breaker is tripped.
        """
        val = await self.state.get("circuit_breaker:state")
        return str(val).lower() == "open" if val is not None else False


if __name__ == "__main__":
    from core.service_runner import run_service_module

    run_service_module(__file__)
