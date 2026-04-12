"""Command Center API for APEX Trading System.

Provides a complete REST API for monitoring and controlling the system.
All READ endpoints are freely accessible.
WRITE/ACTION endpoints require explicit confirmation via X-Confirm header.

Architecture principle (per CLAUDE.md): the dashboard is READ-ONLY for
trading. It can trigger circuit breaker reset and configuration display,
but NEVER place orders or bypass the Risk Manager.

Mounted on the DashboardServer FastAPI app at /api/v1/.
"""

from __future__ import annotations

import json
import time
from typing import Any

import numpy as np
from fastapi import HTTPException
from pydantic import BaseModel

from core.logger import get_logger
from core.state import StateStore

logger = get_logger("s10_monitor.command_api")


# ── Response models ───────────────────────────────────────────────────────────


class ServiceHealth(BaseModel):
    service_id: str
    status: str  # "healthy" | "degraded" | "dead"
    last_seen_seconds: float
    is_alive: bool


class SystemStatus(BaseModel):
    all_healthy: bool
    services: list[ServiceHealth]
    circuit_breaker: str  # "CLOSED" | "OPEN" | "HALF_OPEN"
    trading_mode: str
    uptime_seconds: float


class PositionSummary(BaseModel):
    symbol: str
    direction: str
    entry_price: str
    size: str
    unrealized_pnl_pct: float
    session: str


class PnLSummary(BaseModel):
    realized_today: str
    unrealized_total: str
    daily_pnl_pct: float
    max_drawdown_pct: float
    win_rate_rolling: float
    trade_count_today: int
    sharpe_rolling: float


class RegimeSummary(BaseModel):
    vol_regime: str
    trend_regime: str
    risk_mode: str
    macro_mult: float
    session: str
    session_mult: float
    event_active: bool
    next_cb_event: str | None


class SignalSummary(BaseModel):
    symbol: str
    direction: str
    strength: float
    triggers: list[str]
    confidence: float
    age_seconds: float


class AlertEntry(BaseModel):
    timestamp: str
    level: str
    message: str


class PerformanceStats(BaseModel):
    sharpe_daily: float
    sortino_daily: float
    calmar: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    avg_win_usd: float
    avg_loss_usd: float
    total_trades: int
    best_session: str
    best_signal_type: str


class CBEventInfo(BaseModel):
    institution: str
    event_type: str
    scheduled_at: str
    minutes_until: float
    block_active: bool
    monitor_active: bool


class ActionResult(BaseModel):
    success: bool
    message: str
    timestamp: str


# ── Helper ────────────────────────────────────────────────────────────────────

_START_TIME = time.time()
_SERVICE_IDS_FULL = [
    "s01_data_ingestion",
    "s02_signal_engine",
    "s03_regime_detector",
    "s04_fusion_engine",
    "s05_risk_manager",
    "s06_execution",
    "s07_quant_analytics",
    "s08_macro_intelligence",
    "s09_feedback_loop",
    "s10_monitor",
]


def _require_confirmation(confirm: str | None) -> None:
    """Raise 403 if X-Confirm header is not 'YES'."""
    if confirm != "YES":
        raise HTTPException(
            status_code=403,
            detail="This action requires explicit confirmation. Add header: X-Confirm: YES",
        )


# ── System Status ─────────────────────────────────────────────────────────────


async def get_system_status(state: StateStore) -> SystemStatus:
    """Overall system health: all services, CB state, trading mode."""
    services: list[ServiceHealth] = []
    all_healthy = True
    now = time.time()

    for sid in _SERVICE_IDS_FULL:
        try:
            health = await state.get(f"service_health:{sid}")
            if health and isinstance(health, dict):
                ts = float(health.get("timestamp_ms", 0)) / 1000
                age = now - ts
                alive = age < 15.0
                status = "healthy" if age < 10 else ("degraded" if age < 30 else "dead")
            else:
                alive, age, status = False, 999.0, "dead"
        except Exception:
            alive, age, status = False, 999.0, "dead"

        if not alive:
            all_healthy = False
        services.append(
            ServiceHealth(
                service_id=sid, status=status, last_seen_seconds=round(age, 1), is_alive=alive
            )
        )

    try:
        cb_raw = await state.get("circuit_breaker:state")
        cb_state = str(cb_raw).upper() if cb_raw else "CLOSED"
    except Exception:
        cb_state = "UNKNOWN"

    from core.config import get_settings

    settings = get_settings()

    return SystemStatus(
        all_healthy=all_healthy,
        services=services,
        circuit_breaker=cb_state,
        trading_mode=settings.trading_mode.value.upper(),
        uptime_seconds=round(now - _START_TIME, 0),
    )


# ── Positions ─────────────────────────────────────────────────────────────────


async def get_positions(state: StateStore) -> list[PositionSummary]:
    """All open positions with unrealized PnL."""
    try:
        r = state.client
        keys = await r.keys("positions:*")
    except Exception:
        return []

    results: list[PositionSummary] = []
    for key in keys:
        try:
            k = key if isinstance(key, str) else key.decode()
            pos = await state.get(k)
            if not isinstance(pos, dict):
                continue
            symbol = k.replace("positions:", "")
            entry = float(pos.get("entry", 0) or 0)
            tick = await state.get(f"tick:{symbol}")
            current = float(tick.get("price", entry) if isinstance(tick, dict) else entry)
            direction = pos.get("direction", "long")
            pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0.0
            if direction == "short":
                pnl_pct = -pnl_pct
            results.append(
                PositionSummary(
                    symbol=symbol,
                    direction=direction,
                    entry_price=str(round(entry, 4)),
                    size=str(pos.get("size", "0")),
                    unrealized_pnl_pct=round(pnl_pct, 3),
                    session=str(pos.get("session", "unknown")),
                )
            )
        except Exception as exc:
            logger.debug("position_parse_failed", error=str(exc))
    return results


# ── PnL ───────────────────────────────────────────────────────────────────────


async def get_pnl(state: StateStore) -> PnLSummary:
    """Real-time PnL dashboard: realized, unrealized, drawdown, win rate."""
    try:
        trades = await state.lrange("trades:all", 0, -1)
        today_start = int(time.time() // 86400 * 86400 * 1000)
        today_trades = [
            t
            for t in trades
            if isinstance(t, dict) and t.get("exit_timestamp_ms", 0) >= today_start
        ]

        realized = sum(float(t.get("net_pnl", 0) or 0) for t in today_trades)
        wins = sum(
            1 for t in trades[-50:] if isinstance(t, dict) and float(t.get("net_pnl", 0) or 0) > 0
        )
        win_rate = wins / min(len(trades), 50) if trades else 0.0

        from core.config import get_settings

        capital = float(get_settings().initial_capital)
        daily_pct = realized / capital * 100 if capital > 0 else 0.0

        # Drawdown from equity curve
        curve = await state.lrange("equity_curve", 0, 99)
        curve_vals = [
            float(e.get("equity", capital) if isinstance(e, dict) else capital) for e in curve
        ]
        max_dd = 0.0
        if len(curve_vals) >= 2:
            peak = curve_vals[0]
            for v in curve_vals:
                if v > peak:
                    peak = v
                if peak > 0:
                    dd = (peak - v) / peak * 100
                    max_dd = max(max_dd, dd)

        # Sharpe (rolling 20 trades)
        recent_pnls = [float(t.get("net_pnl", 0) or 0) for t in trades[-20:] if isinstance(t, dict)]
        sharpe = 0.0
        if len(recent_pnls) >= 5:
            arr = np.array(recent_pnls)
            std = float(np.std(arr, ddof=1))
            sharpe = float(np.mean(arr) / std * np.sqrt(252)) if std > 0 else 0.0

        return PnLSummary(
            realized_today=f"${realized:,.2f}",
            unrealized_total="$0.00",  # computed in positions endpoint
            daily_pnl_pct=round(daily_pct, 3),
            max_drawdown_pct=round(max_dd, 3),
            win_rate_rolling=round(win_rate, 3),
            trade_count_today=len(today_trades),
            sharpe_rolling=round(sharpe, 3),
        )
    except Exception as exc:
        logger.error("pnl_error", error=str(exc))
        return PnLSummary(
            realized_today="$0.00",
            unrealized_total="$0.00",
            daily_pnl_pct=0.0,
            max_drawdown_pct=0.0,
            win_rate_rolling=0.0,
            trade_count_today=0,
            sharpe_rolling=0.0,
        )


# ── Regime ────────────────────────────────────────────────────────────────────


async def get_regime(state: StateStore) -> RegimeSummary:
    """Current market regime: vol, trend, macro multipliers, CB events."""
    try:
        raw = await state.get("regime:current")
        if not isinstance(raw, dict):
            raw = {}
        macro = raw.get("macro", {}) or {}
        session = raw.get("session", {}) or {}
        next_cb = await state.get("macro:cb:next_event")
        next_str: str | None = None
        if isinstance(next_cb, dict):
            inst = next_cb.get("institution", "?")
            sched = next_cb.get("scheduled_at", "?")[:16]
            next_str = f"{inst} @ {sched}"
        return RegimeSummary(
            vol_regime=str(raw.get("vol_regime", "unknown")),
            trend_regime=str(raw.get("trend_regime", "unknown")),
            risk_mode=str(raw.get("risk_mode", "unknown")),
            macro_mult=float(raw.get("macro_mult", 1.0) or 1.0),
            session=str(session.get("session", "unknown")),
            session_mult=float(session.get("session_mult", 1.0) or 1.0),
            event_active=bool(macro.get("event_active", False)),
            next_cb_event=next_str,
        )
    except Exception as exc:
        logger.error("regime_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Signals ───────────────────────────────────────────────────────────────────


async def get_recent_signals(state: StateStore) -> list[SignalSummary]:
    """Latest signal for each tracked symbol."""
    try:
        r = state.client
        keys = await r.keys("signal:*")
    except Exception:
        return []

    now = time.time()
    results: list[SignalSummary] = []
    for key in keys[:20]:
        try:
            k = key if isinstance(key, str) else key.decode()
            sig = await state.get(k)
            if not isinstance(sig, dict):
                continue
            ts_ms = float(sig.get("timestamp_ms", 0) or 0)
            age = now - ts_ms / 1000.0
            results.append(
                SignalSummary(
                    symbol=str(sig.get("symbol", "?")),
                    direction=str(sig.get("direction", "?")),
                    strength=float(sig.get("strength", 0) or 0),
                    triggers=list(sig.get("triggers", [])),
                    confidence=float(sig.get("confidence", 0) or 0),
                    age_seconds=round(age, 1),
                )
            )
        except Exception as exc:
            logger.debug("signal_parse_failed", error=str(exc))
            continue
    return sorted(results, key=lambda x: x.age_seconds)


# ── Circuit Breaker ───────────────────────────────────────────────────────────


async def get_circuit_breaker(state: StateStore) -> dict[str, Any]:
    """Circuit breaker current status and trip history."""
    try:
        cb_state = await state.get("circuit_breaker:state")
        daily_pnl = await state.get("pnl:daily_pct")
        return {
            "state": str(cb_state or "CLOSED").upper(),
            "allows_new_orders": str(cb_state or "").upper() != "OPEN",
            "daily_pnl_pct": float(daily_pnl or 0),
            "threshold_pct": 3.0,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def reset_circuit_breaker(
    state: StateStore,
    x_confirm: str | None = None,
) -> ActionResult:
    """Manually reset circuit breaker to CLOSED (requires X-Confirm: YES).

    USE ONLY at start of new trading day after reviewing overnight risk.
    Cannot bypass Risk Manager — only allows new trades to resume.
    """
    _require_confirmation(x_confirm)
    try:
        await state.set("circuit_breaker:state", "closed", ttl=86400)
        logger.warning("circuit_breaker_manually_reset", action="dashboard_user")
        return ActionResult(
            success=True, message="Circuit breaker reset to CLOSED.", timestamp=str(time.time())
        )
    except Exception as exc:
        return ActionResult(success=False, message=str(exc), timestamp=str(time.time()))


# ── Performance ───────────────────────────────────────────────────────────────


async def get_performance(state: StateStore) -> PerformanceStats:
    """Full performance attribution: Sharpe, Sortino, Calmar, by session/signal."""
    try:
        perf_raw = await state.get("analytics:performance")
        quality_raw = await state.get("feedback:signal_quality")
        trades = await state.lrange("trades:all", 0, -1)

        sharpe = 0.0
        sortino = 0.0
        calmar = 0.0
        max_dd = 0.0
        wr = 0.0
        pf = 0.0
        avg_w = 0.0
        avg_l = 0.0

        if isinstance(perf_raw, dict):
            sharpe = float(perf_raw.get("sharpe", 0) or 0)
            sortino = float(perf_raw.get("sortino", 0) or 0)
            calmar = float(perf_raw.get("calmar", 0) or 0)

        # Best session and signal type from quality
        best_session = "us_prime"
        best_signal = "OFI"
        if isinstance(quality_raw, dict):
            by_ses: dict[str, Any] = quality_raw.get("by_session", {}) or {}
            by_sig: dict[str, Any] = quality_raw.get("by_type", {}) or {}
            if by_ses:
                best_session = max(by_ses, key=lambda k: by_ses[k].get("win_rate", 0))
            if by_sig:
                best_signal = max(by_sig, key=lambda k: by_sig[k].get("win_rate", 0))

        return PerformanceStats(
            sharpe_daily=round(sharpe, 3),
            sortino_daily=round(sortino, 3),
            calmar=round(calmar, 3),
            max_drawdown_pct=round(max_dd, 3),
            win_rate=round(wr, 3),
            profit_factor=round(pf, 3),
            avg_win_usd=round(avg_w, 2),
            avg_loss_usd=round(avg_l, 2),
            total_trades=len(trades),
            best_session=best_session,
            best_signal_type=best_signal,
        )
    except Exception as exc:
        logger.error("performance_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── CB Events ─────────────────────────────────────────────────────────────────


async def get_cb_events(state: StateStore) -> list[CBEventInfo]:
    """Upcoming central bank events with block/monitor window status."""
    try:
        events_raw = await state.get("cb:calendar")
        block_raw = await state.get("macro:cb:block_active")
        monitor_raw = await state.get("macro:cb:monitor_active")
        block_active = bool(isinstance(block_raw, dict) and block_raw.get("active", False))
        monitor_active = bool(isinstance(monitor_raw, dict) and monitor_raw.get("active", False))

        results: list[CBEventInfo] = []
        if not isinstance(events_raw, list):
            return results

        now = time.time()
        for ev in events_raw[:10]:
            if not isinstance(ev, dict):
                continue
            try:
                from datetime import datetime

                scheduled_str = str(ev.get("scheduled_at", ""))
                scheduled = datetime.fromisoformat(scheduled_str.replace("Z", "+00:00"))
                minutes_until = (scheduled.timestamp() - now) / 60
                if minutes_until < -120:  # skip events 2h in the past
                    continue
                results.append(
                    CBEventInfo(
                        institution=str(ev.get("institution", "?")),
                        event_type=str(ev.get("event_type", "?")),
                        scheduled_at=scheduled_str[:16],
                        minutes_until=round(minutes_until, 1),
                        block_active=block_active,
                        monitor_active=monitor_active,
                    )
                )
            except Exception as ev_exc:
                logger.debug("cb_event_parse_failed", error=str(ev_exc))
                continue
        return sorted(results, key=lambda x: x.minutes_until)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Config ────────────────────────────────────────────────────────────────────


async def get_config() -> dict[str, Any]:
    """Current system configuration (read-only, no secrets exposed)."""
    from core.config import get_settings

    s = get_settings()
    return {
        "trading_mode": s.trading_mode.value,
        "initial_capital": str(s.initial_capital),
        "max_daily_drawdown_pct": s.max_daily_drawdown_pct,
        "max_position_risk_pct": s.max_position_risk_pct,
        "max_simultaneous_positions": s.max_simultaneous_positions,
        "max_total_exposure_pct": s.max_total_exposure_pct,
        "min_risk_reward": s.min_risk_reward,
        "kelly_divisor": s.kelly_divisor,
        "min_signal_strength": s.min_signal_strength,
        "min_confluence_triggers": s.min_confluence_triggers,
        "cb_event_pre_block_minutes": s.cb_event_pre_block_minutes,
    }


# ── Alerts ────────────────────────────────────────────────────────────────────


async def get_recent_alerts(state: StateStore) -> list[AlertEntry]:
    """Last 50 system alerts."""
    try:
        alerts = await state.lrange("alerts:log", 0, 49)
        results: list[AlertEntry] = []
        for a in alerts:
            if isinstance(a, dict):
                results.append(
                    AlertEntry(
                        timestamp=str(a.get("timestamp", "")),
                        level=str(a.get("level", "INFO")),
                        message=str(a.get("message", "")),
                    )
                )
        return results
    except Exception:
        return []


async def get_risk_status(state: StateStore) -> dict[str, Any]:
    """Risk Manager real-time status for S10 Dashboard.

    Aggregates:
    - Circuit breaker state + daily P&L (from Redis circuit_breaker snapshot)
    - Portfolio capital and total exposure (from Redis portfolio key)
    - Last 100 risk decisions: approval rate, block reason breakdown
    - Kelly fraction distribution of approved orders (for sparkline)
    """
    cb_raw = await state.get("risk:circuit_breaker:state") or {}
    portfolio = await state.get("portfolio:capital") or {}

    raw_decisions = await state.lrange("risk:decision_history", 0, 99) or []
    decisions: list[dict[str, Any]] = []
    for item in raw_decisions:
        try:
            decisions.append(json.loads(item) if isinstance(item, str) else item)
        except Exception as exc:
            logger.debug("decision_decode_failed", error=str(exc))

    approved = [d for d in decisions if d.get("approved") is True]
    blocked = [d for d in decisions if d.get("approved") is False]

    kelly_finals = [float(d.get("kelly_fraction_final", 0)) for d in approved]
    avg_kelly = sum(kelly_finals) / len(kelly_finals) if kelly_finals else 0.0

    block_reasons: dict[str, int] = {}
    for d in blocked:
        r = str(d.get("first_failure", "unknown"))
        block_reasons[r] = block_reasons.get(r, 0) + 1

    cb = cb_raw if isinstance(cb_raw, dict) else {}
    pf = portfolio if isinstance(portfolio, dict) else {}

    return {
        "circuit_breaker": {
            "state": cb.get("state", "CLOSED"),
            "daily_pnl": str(cb.get("daily_pnl", "0")),
            "daily_loss_pct": round(float(cb.get("daily_loss_pct", 0.0)), 4),
            "tripped_reason": cb.get("tripped_reason"),
            "consecutive_losses": int(cb.get("consecutive_losses", 0)),
            "recovery_attempts": int(cb.get("recovery_attempts", 0)),
        },
        "portfolio": {
            "available_capital": str(pf.get("available", "0")),
            "total_exposure_pct": round(float(pf.get("exposure_pct", 0.0)), 4),
            "open_positions": int(pf.get("n_positions", 0)),
        },
        "decisions_last_100": {
            "total": len(decisions),
            "approved": len(approved),
            "blocked": len(blocked),
            "approval_rate_pct": (
                round(len(approved) / len(decisions) * 100, 1) if decisions else 0.0
            ),
        },
        "kelly_stats": {
            "avg_kelly_final": round(avg_kelly, 4),
            "sparkline": kelly_finals[:20],
        },
        "block_reasons": block_reasons,
    }
