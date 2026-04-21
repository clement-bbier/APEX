"""S07 Quant Analytics service for APEX Trading System."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from core.base_service import BaseService
from services.quant_analytics.market_stats import MarketStats
from services.quant_analytics.microstructure_adv import AdvancedMicrostructure
from services.quant_analytics.performance import PerformanceAnalyzer
from services.quant_analytics.realized_vol import RealizedVolEstimator
from services.quant_analytics.rough_vol import RoughVolAnalyzer


class QuantAnalyticsService(BaseService):
    """Service that periodically computes quant analytics and stores results in Redis."""

    service_id = "quant_analytics"

    def __init__(self) -> None:
        """Initialise analytics sub-modules."""
        super().__init__("quant_analytics")
        self._market_stats = MarketStats()
        self._microstructure = AdvancedMicrostructure()
        self._performance = PerformanceAnalyzer()
        self._rv_estimator = RealizedVolEstimator()
        self._rough_vol = RoughVolAnalyzer()

    async def on_message(self, topic: str, data: Any) -> None:  # noqa: ANN401
        """No-op message handler (service reads from Redis directly).

        Args:
            topic: ZMQ topic string.
            data: Deserialized message payload.
        """

    async def run(self) -> None:
        """Run fast (5-min) and slow (1-h) analytics loops concurrently."""
        await asyncio.gather(
            self._fast_loop(),
            self._slow_loop(),
        )

    async def _fast_loop(self) -> None:
        """Fast loop: every 5 minutes compute Hurst, GARCH, and Amihud metrics."""
        while True:
            try:
                await self._run_fast_analytics()
            except Exception as exc:
                self.logger.warning("fast_loop error: %s", exc)
            await asyncio.sleep(300)

    async def _slow_loop(self) -> None:
        """Slow loop: every 1 hour compute Sharpe, Sortino, and Calmar metrics."""
        while True:
            try:
                await self._run_slow_analytics()
            except Exception as exc:
                self.logger.warning("slow_loop error: %s", exc)
            await asyncio.sleep(3600)

    async def _run_fast_analytics(self) -> None:
        """Read recent ticks from Redis, compute and store Hurst, GARCH, Amihud."""
        raw = await self.state.get("ticks:recent")
        if not raw:
            return
        ticks: list[dict[str, Any]] = json.loads(raw)
        prices = [float(t["price"]) for t in ticks if "price" in t]
        returns = [float(t["return"]) for t in ticks if "return" in t]
        volumes = [float(t["volume"]) for t in ticks if "volume" in t]

        results: dict[str, Any] = {}
        if len(prices) >= 20:
            results["hurst"] = self._market_stats.hurst_exponent(prices)
        if returns:
            results["garch_vol"] = self._market_stats.garch_volatility(returns)
        if returns and volumes:
            results["amihud"] = self._microstructure.amihud_ratio(returns, volumes)

        # Jump detection and rough vol via new academic modules
        if len(returns) >= 5:
            import time as _time

            metrics = self._rv_estimator.jump_detection(returns)
            if metrics.has_significant_jump:
                await self.state.set(
                    "analytics:jump_detected",
                    {
                        "jump_ratio": metrics.jump_ratio,
                        "jump_component": metrics.jump_component,
                        "timestamp_ms": int(_time.time() * 1000),
                    },
                )
            results["rv_annualized_vol"] = metrics.annualized_vol
            results["jump_ratio"] = metrics.jump_ratio
            results["has_significant_jump"] = metrics.has_significant_jump

        if len(prices) >= 30:
            rough_sig = self._rough_vol.estimate_hurst_from_vol(prices)
            results["hurst_exponent"] = rough_sig.hurst_exponent
            results["vol_regime_rough"] = rough_sig.vol_regime
            results["scalping_edge_score"] = rough_sig.scalping_edge_score

        if results:
            await self.state.set("analytics:fast", json.dumps(results))

    async def _run_slow_analytics(self) -> None:
        """Read trade records from Redis, compute and store performance metrics."""
        raw = await self.state.get("trades:records")
        if not raw:
            return
        trades: list[dict[str, Any]] = json.loads(raw)
        returns = [float(t["return"]) for t in trades if "return" in t]
        if not returns:
            return

        equity_curve = [float(t["equity"]) for t in trades if "equity" in t]
        max_dd, _ = self._performance.max_drawdown(equity_curve) if equity_curve else (0.0, 0)
        annual_return = float(sum(returns)) if returns else 0.0

        perf = {
            "sharpe": self._performance.sharpe_ratio(returns),
            "sortino": self._performance.sortino_ratio(returns),
            "calmar": self._performance.calmar_ratio(annual_return, max_dd),
        }
        await self.state.set("analytics:performance", json.dumps(perf))


if __name__ == "__main__":
    from core.service_runner import run_service_module

    run_service_module(__file__)
