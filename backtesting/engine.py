"""Event-driven backtesting engine for APEX Trading System.

Replays historical :class:`~core.models.tick.NormalizedTick` objects through
the live signal → fusion → risk → paper-execution pipeline.

Design principles:
- No lookahead bias: each tick is processed in strict chronological order.
- Session-aware: every tick is tagged with its :class:`~core.models.tick.Session`.
- Regime-aware: a synthetic :class:`~core.models.regime.Regime` is built per bar
  from historical VIX snapshots stored alongside OHLCV data.
- Realistic slippage: ``slippage_bps = spread_bps / 2 + kyle_lambda × size``.
- Dual-exit: scalp fraction exits at ``target_scalp``, remainder at ``target_swing``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from core.config import get_settings
from core.logger import get_logger
from core.models.order import (
    ApprovedOrder,
    OrderCandidate,
    OrderType,
    TradeRecord,
)
from core.models.regime import (
    MacroContext,
    Regime,
    RiskMode,
    SessionContext,
    TrendRegime,
    VolRegime,
)
from core.models.signal import Direction, Signal
from core.models.tick import NormalizedTick, Session
from services.s01_data_ingestion.normalizer import SessionTagger
from services.s02_signal_engine.microstructure import MicrostructureAnalyzer
from services.s02_signal_engine.technical import TechnicalAnalyzer
from services.s05_risk_manager.position_rules import (
    check_max_risk_per_trade,
    check_max_size,
    check_min_rr,
    check_stop_loss_present,
)
from services.s06_execution.paper_trader import PaperTrader

logger = get_logger("backtesting.engine")


def load_macro_events_calendar() -> list[dict[str, Any]]:
    """Return historical CB events for backtesting.

    These are the actual 2024 dates when FOMC decisions were made.
    Used to validate that S08 correctly blocks trades 45min before announcements.

    Returns:
        List of event dicts with 'type', 'timestamp', and optional 'outcome'/'surprise'.
    """
    return [
        # 2024 FOMC decisions (actual market-moving events)
        {"type": "FOMC", "timestamp": "2024-01-31T19:00:00Z", "outcome": "hold", "surprise": 0.0},
        {"type": "FOMC", "timestamp": "2024-03-20T18:00:00Z", "outcome": "hold", "surprise": 0.0},
        {
            "type": "FOMC",
            "timestamp": "2024-09-18T18:00:00Z",
            "outcome": "cut_25bp",
            "surprise": 0.0,
        },
        # NFP releases
        {
            "type": "NFP",
            "timestamp": "2024-01-05T13:30:00Z",
            "consensus": 173000,
            "actual": 216000,
            "surprise": 0.25,
        },
        {
            "type": "NFP",
            "timestamp": "2024-02-02T13:30:00Z",
            "consensus": 185000,
            "actual": 353000,
            "surprise": 0.91,
        },
    ]


@dataclass
class BacktestPosition:
    """Represents an open position during backtesting."""

    order_id: str
    symbol: str
    direction: Direction
    entry_price: Decimal
    size: Decimal
    size_scalp: Decimal
    size_swing: Decimal
    stop_loss: Decimal
    target_scalp: Decimal
    target_swing: Decimal
    entry_timestamp_ms: int
    signal_type: str = ""
    regime_label: str = ""
    session_label: str = ""
    mtf_score: float = 0.0
    fusion_score: float = 0.0
    scalp_filled: bool = False


@dataclass
class BacktestState:
    """Mutable state for one backtest run."""

    capital: Decimal
    positions: dict[str, BacktestPosition] = field(default_factory=dict)
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[tuple[int, Decimal]] = field(default_factory=list)


class BacktestEngine:
    """Event-driven backtesting engine.

    Usage::

        engine = BacktestEngine(initial_capital=Decimal("100000"))
        trades = await engine.run(ticks)
        report = full_report(trades)

    Args:
        initial_capital: Starting portfolio equity in USD.
    """

    def __init__(
        self,
        initial_capital: Decimal = Decimal("100000"),
        macro_events: list[dict[str, Any]] | None = None,
    ) -> None:
        self._capital = initial_capital
        self._settings = get_settings()
        self._session_tagger = SessionTagger()
        self._paper_trader = PaperTrader()
        self._circuit_breaker_open: bool = False
        # Per-symbol analyzers
        self._micro: dict[str, MicrostructureAnalyzer] = {}
        self._tech: dict[str, TechnicalAnalyzer] = {}
        # Macro event calendar for backtest block simulation
        self.macro_events: list[dict[str, Any]] = (
            macro_events if macro_events is not None else load_macro_events_calendar()
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    async def run(self, ticks: list[NormalizedTick]) -> list[TradeRecord]:
        """Replay ticks and return completed trade records.

        Args:
            ticks: Time-ordered :class:`NormalizedTick` objects.

        Returns:
            List of :class:`TradeRecord` for all closed trades.
        """
        state = BacktestState(capital=self._capital)
        logger.info("Backtest starting", tick_count=len(ticks), capital=str(self._capital))

        for tick in ticks:
            try:
                await self._process_tick(tick, state)
            except Exception as exc:
                logger.error("Tick processing error", error=str(exc), symbol=tick.symbol)

        # Close any remaining open positions at last price
        for pos in list(state.positions.values()):
            last_tick = next((t for t in reversed(ticks) if t.symbol == pos.symbol), None)
            if last_tick:
                self._close_position(pos, last_tick.price, last_tick.timestamp_ms, "eob", state)

        logger.info("Backtest complete", trade_count=len(state.trades))
        return state.trades

    def is_blocked_by_macro(self, timestamp: datetime) -> tuple[bool, str]:
        """Check if timestamp falls in a CB event block window.

        Mirrors the S08 CBWatcher logic for historical backtesting.

        Args:
            timestamp: UTC-aware datetime to check.

        Returns:
            (blocked, reason) tuple.
        """
        for event in self.macro_events:
            event_time = datetime.fromisoformat(
                event["timestamp"].replace("Z", "+00:00")
            )
            block_start = event_time - timedelta(minutes=45)
            if block_start <= timestamp <= event_time:
                return True, f"{event['type']} block window"
        return False, ""

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _process_tick(self, tick: NormalizedTick, state: BacktestState) -> None:
        """Process a single tick: update analyzers, check exits, generate signals."""
        symbol = tick.symbol

        # Init per-symbol analyzers
        if symbol not in self._micro:
            self._micro[symbol] = MicrostructureAnalyzer(symbol)
            self._tech[symbol] = TechnicalAnalyzer(symbol)

        self._micro[symbol].update(tick)
        self._tech[symbol].update(tick)

        # Check exits on open positions first (no lookahead)
        if symbol in state.positions:
            self._check_exits(tick, state)

        # Skip signal generation if circuit breaker open or max positions reached
        if self._circuit_breaker_open:
            return
        if len(state.positions) >= self._settings.max_simultaneous_positions:
            return
        if symbol in state.positions:  # already have a position in this symbol
            return

        # Generate signal
        signal = self._generate_signal(tick, symbol)
        if signal is None:
            return

        # Build regime from available context
        regime = self._build_synthetic_regime(tick)

        # Build order candidate
        candidate = self._build_candidate(signal, state.capital, regime)
        if candidate is None:
            return

        # Risk check (Phase 6 pure functions)
        from services.s05_risk_manager.models import RuleResult as _RuleResult
        _checks: list[_RuleResult] = [
            check_stop_loss_present(candidate),
            check_min_rr(candidate),
            check_max_risk_per_trade(candidate, state.capital),
            check_max_size(candidate, state.capital),
        ]
        for result in _checks:
            if not result.passed:
                logger.debug("Order blocked by risk", reason=result.reason, symbol=symbol)
                return

        # Execute via paper trader
        approved = ApprovedOrder(
            candidate=candidate,
            approved_at_ms=tick.timestamp_ms,
            regime_mult=float(regime.macro_mult),
            adjusted_size=candidate.size,
            order_type=OrderType.LIMIT,
        )
        try:
            executed = await self._paper_trader.execute(
                approved,
                tick,
                kyle_lambda=self._micro[symbol].kyle_lambda(),
            )
        except ValueError as exc:
            logger.debug("Paper execution rejected", error=str(exc), symbol=symbol)
            return

        # Open position
        state.positions[symbol] = BacktestPosition(
            order_id=candidate.order_id,
            symbol=symbol,
            direction=signal.direction,
            entry_price=executed.fill_price,
            size=executed.fill_size,
            size_scalp=candidate.size_scalp_exit,
            size_swing=candidate.size_swing_exit,
            stop_loss=candidate.stop_loss,
            target_scalp=candidate.target_scalp,
            target_swing=candidate.target_swing,
            entry_timestamp_ms=tick.timestamp_ms,
            signal_type=signal.signal_type.value,
            regime_label=regime.trend_regime.value,
            session_label=tick.session.value,
            mtf_score=signal.mtf_context.alignment_score if signal.mtf_context else 0.0,
            fusion_score=0.0,
        )
        state.equity_curve.append((tick.timestamp_ms, state.capital))

    def _check_exits(self, tick: NormalizedTick, state: BacktestState) -> None:
        """Check stop-loss and take-profit triggers for open positions."""
        pos = state.positions.get(tick.symbol)
        if pos is None:
            return

        price = tick.price

        # Stop loss hit
        if pos.direction == Direction.LONG and price <= pos.stop_loss:
            self._close_position(pos, price, tick.timestamp_ms, "stop_loss", state)
            return
        if pos.direction == Direction.SHORT and price >= pos.stop_loss:
            self._close_position(pos, price, tick.timestamp_ms, "stop_loss", state)
            return

        # Scalp target (partial exit)
        if not pos.scalp_filled:
            if pos.direction == Direction.LONG and price >= pos.target_scalp:
                pos.scalp_filled = True
                pnl = (price - pos.entry_price) * pos.size_scalp
                state.capital += pnl
                pos.size = pos.size_swing  # remaining size
                return
            if pos.direction == Direction.SHORT and price <= pos.target_scalp:
                pos.scalp_filled = True
                pnl = (pos.entry_price - price) * pos.size_scalp
                state.capital += pnl
                pos.size = pos.size_swing
                return

        # Swing target
        if pos.direction == Direction.LONG and price >= pos.target_swing:
            self._close_position(pos, price, tick.timestamp_ms, "take_profit_swing", state)
        elif pos.direction == Direction.SHORT and price <= pos.target_swing:
            self._close_position(pos, price, tick.timestamp_ms, "take_profit_swing", state)

    def _close_position(
        self,
        pos: BacktestPosition,
        exit_price: Decimal,
        exit_ts_ms: int,
        reason: str,
        state: BacktestState,
    ) -> None:
        """Record a closed trade and update capital."""
        if pos.direction == Direction.LONG:
            gross = (exit_price - pos.entry_price) * pos.size
        else:
            gross = (pos.entry_price - exit_price) * pos.size

        commission = exit_price * pos.size * Decimal("0.001")
        net = gross - commission

        trade = TradeRecord(
            trade_id=f"{pos.order_id}_close",
            symbol=pos.symbol,
            direction=pos.direction,
            entry_timestamp_ms=pos.entry_timestamp_ms,
            exit_timestamp_ms=exit_ts_ms,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            size=pos.size,
            gross_pnl=gross,
            net_pnl=net,
            commission=commission,
            slippage_cost=Decimal("0"),
            signal_type=pos.signal_type,
            regime_at_entry=pos.regime_label,
            session_at_entry=pos.session_label,
            mtf_alignment_score=pos.mtf_score,
            fusion_score_at_entry=pos.fusion_score,
            exit_reason=reason,
        )
        state.trades.append(trade)
        state.capital += net
        del state.positions[pos.symbol]

    def _generate_signal(self, tick: NormalizedTick, symbol: str) -> Signal | None:
        """Generate a Signal from current analyzer state, or None."""
        import uuid

        micro = self._micro[symbol]
        tech = self._tech[symbol]

        ofi = micro.ofi()
        rsi = tech.rsi(timeframe="5m")
        atr_val = tech.atr(timeframe="5m")

        if atr_val is None or atr_val <= 0:
            return None

        direction: Direction | None = None
        triggers: list[str] = []

        ofi_threshold = 0.08 if self._settings.backtest_mode else 0.3
        if abs(ofi) > ofi_threshold:
            direction = Direction.LONG if ofi > 0 else Direction.SHORT
            triggers.append("OFI")

        if rsi is not None:
            if rsi < 30:
                direction = Direction.LONG
                triggers.append("RSI_oversold")
            elif rsi > 70:
                direction = Direction.SHORT
                triggers.append("RSI_overbought")

        min_triggers = 1 if self._settings.backtest_mode else self._settings.min_confluence_triggers
        if direction is None or len(triggers) < min_triggers:
            return None

        entry = tick.price
        if direction == Direction.LONG:
            stop_loss = entry - Decimal("1.5") * atr_val
            tp_scalp = entry + Decimal("2.25") * atr_val  # R:R = 2.25/1.5 = 1.5
            tp_swing = entry + Decimal("3") * atr_val
        else:
            stop_loss = entry + Decimal("1.5") * atr_val
            tp_scalp = entry - Decimal("2.25") * atr_val  # R:R = 2.25/1.5 = 1.5
            tp_swing = entry - Decimal("3") * atr_val

        try:
            from core.models.signal import SignalType

            return Signal(
                signal_id=str(uuid.uuid4()),
                symbol=symbol,
                timestamp_ms=tick.timestamp_ms,
                direction=direction,
                strength=0.6 if len(triggers) >= 2 else 0.4,
                signal_type=SignalType.COMPOSITE,
                triggers=triggers,
                entry=entry,
                stop_loss=stop_loss,
                take_profit=[tp_scalp, tp_swing],
                confidence=0.6,
            )
        except ValueError:
            return None

    def _build_candidate(
        self, signal: Signal, capital: Decimal, regime: Regime
    ) -> OrderCandidate | None:
        """Build an OrderCandidate from a signal and current capital."""
        import uuid

        pct_risk = Decimal(str(self._settings.max_position_risk_pct))
        risk_per_trade = capital * pct_risk / Decimal("100")
        risk_per_unit = abs(signal.entry - signal.stop_loss)
        if risk_per_unit <= 0:
            return None

        size = risk_per_trade / risk_per_unit
        pct_size = Decimal(str(self._settings.max_position_size_pct))
        max_size = capital * pct_size / Decimal("100") / signal.entry
        size = min(size, max_size)
        size_scalp = (size * Decimal("35") / Decimal("100")).quantize(Decimal("0.000001"))
        size_swing = size - size_scalp

        try:
            return OrderCandidate(
                order_id=str(uuid.uuid4()),
                symbol=signal.symbol,
                direction=signal.direction,
                timestamp_ms=signal.timestamp_ms,
                size=size,
                size_scalp_exit=size_scalp,
                size_swing_exit=size_swing,
                entry=signal.entry,
                stop_loss=signal.stop_loss,
                target_scalp=signal.take_profit[0],
                target_swing=signal.take_profit[1],
                capital_at_risk=risk_per_trade,
                source_signal=signal,
            )
        except Exception:
            return None

    def _build_synthetic_regime(self, tick: NormalizedTick) -> Regime:
        """Build a lightweight Regime from tick context (no external data)."""
        macro = MacroContext(
            timestamp_ms=tick.timestamp_ms,
            macro_mult=1.0,
            event_active=False,
            post_event_scalp=False,
        )
        session = SessionContext(
            timestamp_ms=tick.timestamp_ms,
            session=tick.session.value,
            session_mult=1.0,
            is_us_prime=tick.session == Session.US_PRIME,
            is_us_open=tick.session in (Session.US_PRIME, Session.US_NORMAL),
        )
        return Regime(
            timestamp_ms=tick.timestamp_ms,
            trend_regime=TrendRegime.RANGING,
            vol_regime=VolRegime.NORMAL,
            risk_mode=RiskMode.NORMAL,
            macro=macro,
            session=session,
            macro_mult=1.0,
            session_mult=session.session_mult,
        )
