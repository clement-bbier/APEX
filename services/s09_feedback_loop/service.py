"""APEX Trading System - S09 Feedback Loop Service."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from core.base_service import BaseService
from core.logger import get_logger
from core.models.order import TradeRecord
from services.s09_feedback_loop.drift_detector import DriftDetector
from services.s09_feedback_loop.signal_quality import SignalQuality
from services.s09_feedback_loop.trade_analyzer import TradeAnalyzer

logger = get_logger("s09_feedback_loop")

KELLY_DEFAULT_WIN_RATE = 0.5
KELLY_DEFAULT_AVG_RR = 1.5
KELLY_ROLLING_WINDOW = 100


class FeedbackLoopService(BaseService):
    """S09 Feedback Loop Service.

    Reads TradeRecord history from Redis, runs post-trade analysis,
    detects performance drift, and updates Kelly statistics.
    Does NOT auto-adjust system parameters.
    """

    def __init__(self) -> None:
        super().__init__("s09_feedback_loop")
        self._analyzer = TradeAnalyzer()
        self._quality = SignalQuality()
        self._drift = DriftDetector()

    async def on_message(self, topic: str, data: dict[str, Any]) -> None:
        """No-op: feedback loop reads from Redis, does not subscribe."""

    async def run(self) -> None:
        """Run feedback analysis loop."""
        logger.info("Feedback loop service starting")
        while self._running:
            try:
                await self._fast_analysis()
                # Check if it's post-market time (21:00-22:00 UTC)
                now = datetime.now(UTC)
                if 21 <= now.hour < 22:
                    await self._slow_analysis()
            except Exception as exc:
                logger.error("Feedback loop error", error=str(exc), exc_info=exc)
            await asyncio.sleep(300)  # 5 minutes

    async def _fast_analysis(self) -> None:
        """Fast analysis every 5 minutes: drift detection and Kelly update."""
        try:
            raw_trades = await self.state.lrange("trades:all", 0, KELLY_ROLLING_WINDOW - 1)
            if not raw_trades:
                return
            trades = [TradeRecord(**t) for t in raw_trades if isinstance(t, dict)]
            if not trades:
                return

            win_rate = self._drift.rolling_win_rate(trades, window=KELLY_ROLLING_WINDOW)
            baseline = await self.state.get("feedback:baseline_win_rate") or KELLY_DEFAULT_WIN_RATE

            if self._drift.is_drifting(win_rate, float(baseline)):
                logger.warning(
                    "Performance drift detected",
                    current_win_rate=win_rate,
                    baseline=baseline,
                )
                await self.bus.publish(
                    "feedback.drift_alert",
                    {"win_rate": win_rate, "baseline": float(baseline)},
                )

            # Update Kelly stats per symbol
            symbols: set[str] = {t.symbol for t in trades}
            for symbol in symbols:
                sym_trades = [t for t in trades if t.symbol == symbol]
                if len(sym_trades) < 5:
                    continue
                sym_win_rate = sum(1 for t in sym_trades if t.is_winner) / len(sym_trades)
                winners = [
                    float(t.r_multiple or 0) for t in sym_trades if t.is_winner and t.r_multiple
                ]
                [
                    abs(float(t.r_multiple or 0))
                    for t in sym_trades
                    if not t.is_winner and t.r_multiple
                ]
                avg_rr = (sum(winners) / len(winners)) if winners else KELLY_DEFAULT_AVG_RR
                await self.state.hset(
                    f"kelly:{symbol}",
                    "win_rate",
                    round(sym_win_rate, 4),
                )
                await self.state.hset(
                    f"kelly:{symbol}",
                    "avg_rr",
                    round(avg_rr, 4),
                )

        except Exception as exc:
            logger.error("Fast analysis error", error=str(exc))

    async def _slow_analysis(self) -> None:
        """Slow post-market analysis: signal quality and attribution."""
        try:
            raw_trades = await self.state.lrange("trades:all", 0, -1)
            if not raw_trades:
                return
            trades = [TradeRecord(**t) for t in raw_trades if isinstance(t, dict)]
            if not trades:
                return

            quality_by_type = self._quality.compute_by_type(trades)
            quality_by_regime = self._quality.compute_by_regime(trades)
            quality_by_session = self._quality.compute_by_session(trades)
            best_configs = self._quality.best_configurations(trades)

            await self.state.set(
                "feedback:signal_quality",
                {
                    "by_type": quality_by_type,
                    "by_regime": quality_by_regime,
                    "by_session": quality_by_session,
                    "best_configs": best_configs,
                },
            )

            attribution = self._analyzer.batch_analyze(trades)
            await self.state.set("feedback:attribution", attribution)

            logger.info(
                "Post-market analysis complete",
                trade_count=len(trades),
                config_count=len(best_configs),
            )

        except Exception as exc:
            logger.error("Slow analysis error", error=str(exc))


import sys
import os
import asyncio
from pathlib import Path

# Fix sys.path for direct module runs
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

if __name__ == '__main__':
    import importlib
    
    # We expect the class name to be XxxService (e.g. DataIngestionService, SignalEngineService...)
    # But to make it generic without inspecting the AST, we can just find subclasses of BaseService
    from core.base_service import BaseService
    import inspect
    
    module_name = 'services.' + Path(__file__).parent.name + '.service'
    module = importlib.import_module(module_name)
    
    service_class = None
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, BaseService) and obj is not BaseService:
            service_class = obj
            break
            
    if not service_class:
        print(f'Error: Could not find a BaseService subclass in {module_name}')
        sys.exit(1)
        
    async def main():
        service = service_class()
        try:
            await service.start()
            while service._running:
                await asyncio.sleep(1.0)
        except KeyboardInterrupt:
            print('Interrupted by user...')
        finally:
            await service.stop()

    asyncio.run(main())

