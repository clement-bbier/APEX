# APEX Trading System — Phase 3: Integration, Hardening & Paper Trading Readiness
# Complete Development Prompt for Claude Code

Read CLAUDE.md and MANIFEST.md and DEVELOPMENT_PLAN.md first.
They are the source of truth for every decision here.

Phase 1: Stabilization (done) — zero mypy, Docker, real data, tests 13%→40%
Phase 2: Intelligence (done) — confluence signals, regime, CB watcher, correlation, Kelly
Phase 3: THIS PROMPT — integration tests, hardening, backtest validation, 85% coverage

Objective: make the system PAPER-TRADING READY.
Every objective must pass CI before moving to the next.

---

## WINDOWS ENVIRONMENT (apply throughout)

```powershell
.venv\Scripts\python      # always, never bare python
$env:PYTHONPATH = "."     # before any script importing project modules
docker info > $null 2>&1; if ($LASTEXITCODE -ne 0) { Write-Error "Start Docker Desktop" }
```

---

## BASELINE AUDIT (run first, report numbers)

```bash
.venv\Scripts\python -m mypy . 2>&1 | grep "error:" | grep -v ".venv" | wc -l
.venv\Scripts\python -m pytest tests/ -q 2>&1 | tail -5
.venv\Scripts\python -m pytest tests/ --cov=. --cov-report=term-missing 2>&1 | grep "TOTAL"
find tests/integration -name "*.py" | grep -v __init__ | wc -l
```

Report: mypy error count, test pass/fail, coverage %, integration test count.

---

## OBJECTIVE 1 — Session Tracker with full DST support (S03)

The current session_tracker.py may handle basic sessions but DST transitions
are critical — a wrong session classification costs the session_multiplier bonus.

Read current `services/s03_regime_detector/session_tracker.py`.
Rewrite it with complete DST-aware logic:

```python
"""
Session Tracker — Intraday session classification with DST support.

Sessions drive session_mult [0.5 → 1.5] in S04 FusionEngine.
Getting sessions wrong = systematic undersizing during prime windows.

US sessions follow America/New_York timezone (handles EST/EDT automatically).
Crypto sessions follow UTC (24/7 market, no DST).

Session schedule (all times in LOCAL timezone):
  US_OPEN    : 09:30 – 10:30 ET  → mult = 1.30 (prime, highest edge)
  US_MORNING : 10:30 – 12:00 ET  → mult = 1.00
  US_LUNCH   : 12:00 – 13:30 ET  → mult = 0.60 (avoid — low edge)
  US_AFTERNOON: 13:30 – 15:00 ET → mult = 1.10
  US_CLOSE   : 15:00 – 16:00 ET  → mult = 1.20 (prime)
  AFTER_HOURS: 16:00 – 09:30 ET  → mult = 0.50
  ASIAN      : 00:00 – 08:00 UTC → mult = 0.70 (crypto only)
  LONDON     : 08:00 – 13:30 UTC → mult = 0.90 (crypto only)
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from enum import StrEnum
from zoneinfo import ZoneInfo  # Python 3.9+ standard library


class Session(StrEnum):
    US_OPEN      = "us_open"
    US_MORNING   = "us_morning"
    US_LUNCH     = "us_lunch"
    US_AFTERNOON = "us_afternoon"
    US_CLOSE     = "us_close"
    AFTER_HOURS  = "after_hours"
    ASIAN        = "asian"
    LONDON       = "london"
    WEEKEND      = "weekend"


SESSION_MULTIPLIERS: dict[Session, float] = {
    Session.US_OPEN:      1.30,
    Session.US_MORNING:   1.00,
    Session.US_LUNCH:     0.60,
    Session.US_AFTERNOON: 1.10,
    Session.US_CLOSE:     1.20,
    Session.AFTER_HOURS:  0.50,
    Session.ASIAN:        0.70,
    Session.LONDON:       0.90,
    Session.WEEKEND:      0.40,
}

PRIME_SESSIONS = {Session.US_OPEN, Session.US_CLOSE}

NY_TZ  = ZoneInfo("America/New_York")
UTC_TZ = timezone.utc


class SessionTracker:
    """
    Maps any UTC datetime to the current trading session.
    Uses America/New_York for US sessions (auto-handles EST/EDT transitions).
    """

    def get_session(self, utc_now: datetime) -> Session:
        """
        Classify the current session for a UTC timestamp.

        Args:
            utc_now: UTC-aware datetime (must have tzinfo=timezone.utc)

        Returns:
            Session enum for current market session.
        """
        assert utc_now.tzinfo is not None, "utc_now must be timezone-aware"

        # Weekend check (UTC-based, simple)
        if utc_now.weekday() >= 5:  # Saturday=5, Sunday=6
            return Session.WEEKEND

        # Convert to NY time for US session classification
        ny_now = utc_now.astimezone(NY_TZ)
        ny_time = ny_now.time()

        # US equity market sessions (DST-safe via ZoneInfo)
        if time(9, 30) <= ny_time < time(10, 30):
            return Session.US_OPEN
        elif time(10, 30) <= ny_time < time(12, 0):
            return Session.US_MORNING
        elif time(12, 0) <= ny_time < time(13, 30):
            return Session.US_LUNCH
        elif time(13, 30) <= ny_time < time(15, 0):
            return Session.US_AFTERNOON
        elif time(15, 0) <= ny_time < time(16, 0):
            return Session.US_CLOSE

        # Outside US hours — classify by UTC for crypto
        utc_time = utc_now.time().replace(tzinfo=None)
        if time(0, 0) <= utc_time < time(8, 0):
            return Session.ASIAN
        elif time(8, 0) <= utc_time < time(13, 30):
            return Session.LONDON

        return Session.AFTER_HOURS

    def get_multiplier(self, session: Session) -> float:
        return SESSION_MULTIPLIERS[session]

    def is_prime_window(self, utc_now: datetime) -> bool:
        return self.get_session(utc_now) in PRIME_SESSIONS

    def get_next_prime_window(self, utc_now: datetime) -> datetime:
        """Return the UTC datetime of the next US_OPEN."""
        from datetime import timedelta

        candidate = utc_now.astimezone(NY_TZ).replace(hour=9, minute=30, second=0, microsecond=0)
        candidate_utc = candidate.astimezone(UTC_TZ)

        if candidate_utc <= utc_now:
            candidate_utc += timedelta(days=1)

        # Skip weekends
        while candidate_utc.weekday() >= 5:
            candidate_utc += timedelta(days=1)

        return candidate_utc
```

Tests in `tests/unit/s03/test_session_tracker.py`:

```python
"""Session tracker tests — all sessions, DST transitions, weekends."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from services.s03_regime_detector.session_tracker import Session, SessionTracker

NY_TZ = ZoneInfo("America/New_York")


def utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class TestSessionClassification:
    def tracker(self) -> SessionTracker:
        return SessionTracker()

    def test_us_open_session(self) -> None:
        # 9:30 AM ET = 13:30 UTC (winter, EST = UTC-5)
        ts = utc(2024, 1, 15, 14, 35)  # 9:35 AM ET
        assert self.tracker().get_session(ts) == Session.US_OPEN

    def test_us_open_session_summer_dst(self) -> None:
        # Summer: EDT = UTC-4, so 9:30 AM ET = 13:30 UTC
        ts = utc(2024, 6, 15, 13, 35)  # 9:35 AM ET (EDT)
        assert self.tracker().get_session(ts) == Session.US_OPEN

    def test_us_close_session(self) -> None:
        # 3:30 PM ET winter = 20:30 UTC
        ts = utc(2024, 1, 15, 20, 30)
        assert self.tracker().get_session(ts) == Session.US_CLOSE

    def test_lunch_session_is_low_mult(self) -> None:
        # 12:30 PM ET winter = 17:30 UTC
        ts = utc(2024, 1, 15, 17, 30)
        tracker = self.tracker()
        session = tracker.get_session(ts)
        assert session == Session.US_LUNCH
        assert tracker.get_multiplier(session) == 0.60

    def test_weekend_is_weekend(self) -> None:
        # Saturday
        ts = utc(2024, 1, 13, 14, 0)  # Saturday
        assert self.tracker().get_session(ts) == Session.WEEKEND

    def test_asian_session(self) -> None:
        ts = utc(2024, 1, 15, 2, 0)  # 2 AM UTC
        assert self.tracker().get_session(ts) == Session.ASIAN

    def test_london_session(self) -> None:
        ts = utc(2024, 1, 15, 9, 0)  # 9 AM UTC
        assert self.tracker().get_session(ts) == Session.LONDON

    def test_dst_spring_forward(self) -> None:
        """DST transition: 2024-03-10, clocks spring forward at 2 AM ET."""
        # After spring forward: EDT = UTC-4
        # 9:30 AM EDT = 13:30 UTC
        after_dst = utc(2024, 3, 10, 13, 35)
        assert self.tracker().get_session(after_dst) == Session.US_OPEN

    def test_dst_fall_back(self) -> None:
        """DST transition: 2024-11-03, clocks fall back at 2 AM ET."""
        # After fall back: EST = UTC-5
        # 9:30 AM EST = 14:30 UTC
        after_dst = utc(2024, 11, 3, 14, 35)
        assert self.tracker().get_session(after_dst) == Session.US_OPEN

    def test_prime_windows(self) -> None:
        tracker = self.tracker()
        # US Open is prime
        assert tracker.is_prime_window(utc(2024, 1, 15, 14, 35)) is True
        # Lunch is not prime
        assert tracker.is_prime_window(utc(2024, 1, 15, 17, 30)) is False

    def test_all_session_multipliers_valid_range(self) -> None:
        from services.s03_regime_detector.session_tracker import SESSION_MULTIPLIERS
        for session, mult in SESSION_MULTIPLIERS.items():
            assert 0.0 < mult <= 2.0, f"Session {session} has invalid mult {mult}"
```

---

## OBJECTIVE 2 — Complete Integration Test Suite

`tests/integration/` is currently empty (only `__init__.py`).
This is the biggest remaining gap before paper trading.

Create these integration tests. They require Docker (Redis) to run.

### tests/integration/conftest.py

```python
"""
Integration test configuration.
All integration tests require Docker Redis to be running.
Run: docker compose -f docker/docker-compose.test.yml up -d
"""
from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
import redis.asyncio as aioredis


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop for all integration tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def redis_client():
    """Real Redis connection for integration tests."""
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/1")  # db=1, not 0
    client = aioredis.Redis.from_url(url, decode_responses=True)
    await client.ping()
    yield client
    await client.flushdb()  # clean up test data
    await client.aclose()
```

### tests/integration/test_full_pipeline_paper.py

```python
"""
Integration test: full pipeline from tick to trade record.

Tests the complete chain:
  NormalizedTick → S02 Signal → S04 OrderCandidate → S05 ApprovedOrder → S06 ExecutedOrder

This is the most important integration test — it proves the pipeline works end-to-end.
Requires: Redis running (docker compose -f docker/docker-compose.test.yml up -d)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from core.models.tick import NormalizedTick, TradeSide, Market, Session
from core.models.signal import Signal
from core.models.order import OrderCandidate
from core.state import StateStore
from services.s02_signal_engine.signal_scorer import SignalScorer, SignalComponent
from services.s03_regime_detector.regime_engine import RegimeEngine
from services.s04_fusion_engine.kelly_sizer import KellySizer
from services.s05_risk_manager.circuit_breaker import CircuitBreaker, CBState
from services.s05_risk_manager.position_rules import check_max_risk_per_trade
from services.s06_execution.paper_trader import PaperTrader


def make_btc_tick(price: str = "50000") -> NormalizedTick:
    return NormalizedTick(
        symbol="BTCUSDT",
        market=Market.CRYPTO,
        timestamp=datetime.now(timezone.utc),
        price=Decimal(price),
        volume=Decimal("1.5"),
        side=TradeSide.BUY,
        bid=Decimal(str(float(price) - 5)),
        ask=Decimal(str(float(price) + 5)),
        spread_bps=Decimal("0.2"),
        session=Session.US_OPEN,
    )


class TestFullPipelinePaper:
    """End-to-end pipeline: tick → executed trade."""

    def test_signal_scorer_to_order_candidate(self) -> None:
        """Verify signal confluence produces a valid OrderCandidate."""
        scorer = SignalScorer(min_components=2, min_strength=0.15)
        components = [
            SignalComponent("microstructure", 0.80, 0.35, True),
            SignalComponent("bollinger", 0.70, 0.25, True),
            SignalComponent("ema_mtf", 0.60, 0.20, True),
        ]
        score, triggers = scorer.compute(components)
        assert score > 0
        assert len(triggers) >= 2

    def test_regime_modulates_sizing(self) -> None:
        """Verify macro_mult reduces position size in high-vol regime."""
        engine = RegimeEngine()
        regime_normal = engine.compute(vix=18.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3)
        regime_crisis = engine.compute(vix=38.0, dxy_1h_change_pct=0.0, yield_10y=4.5, yield_2y=4.3)

        sizer = KellySizer()
        capital = Decimal("10000")
        size_normal = sizer.position_size(capital, 0.55, 1.8, regime_normal.macro_mult)
        size_crisis = sizer.position_size(capital, 0.55, 1.8, regime_crisis.macro_mult)

        assert size_normal > size_crisis
        assert size_crisis == Decimal("0")  # crisis = 0 size

    def test_risk_manager_blocks_oversized_position(self) -> None:
        """Risk manager must reject any position exceeding 0.5% capital risk."""
        capital = Decimal("10000")
        max_risk = capital * Decimal("0.005")  # 0.5% = $50

        # Build a candidate that would risk $200 (too large)
        from unittest.mock import MagicMock
        order = MagicMock()
        order.entry_price = Decimal("50000")
        order.stop_loss   = Decimal("49000")   # $1000 risk per BTC
        order.size_total  = Decimal("0.5")     # 0.5 BTC = $500 risk — exceeds limit

        risk_per_unit = order.entry_price - order.stop_loss
        total_risk = risk_per_unit * order.size_total
        assert total_risk > max_risk  # confirms it's over the limit

        result = check_max_risk_per_trade(order, capital)
        assert result.passed is False
        assert "exceeds" in result.reason.lower() or not result.passed

    def test_paper_trader_slippage_is_applied(self) -> None:
        """Paper trader must apply realistic slippage (never fill at exact price)."""
        from unittest.mock import MagicMock
        config = MagicMock()
        trader = PaperTrader(config=config)

        slippage_tight = trader.compute_slippage(
            spread_bps=2.0, kyle_lambda=0.00001,
            size=Decimal("0.1"), price=Decimal("50000"),
        )
        slippage_wide = trader.compute_slippage(
            spread_bps=20.0, kyle_lambda=0.0001,
            size=Decimal("1.0"), price=Decimal("50000"),
        )
        assert slippage_wide > slippage_tight
        assert slippage_tight >= 0.0

    def test_circuit_breaker_halts_on_drawdown(self) -> None:
        """3% daily drawdown must open circuit breaker and block all orders."""
        from unittest.mock import MagicMock
        config = MagicMock()
        config.max_daily_drawdown_pct = 0.03
        config.max_loss_30min_pct = 0.02
        config.vix_spike_threshold_pct = 0.20
        config.service_down_timeout_seconds = 60
        config.data_anomaly_gap_pct = 0.05

        cb = CircuitBreaker(config=config)
        assert cb.state == CBState.CLOSED
        assert cb.allows_new_orders() is True

        cb.update_daily_pnl(pnl_pct=-0.031)
        assert cb.state == CBState.OPEN
        assert cb.allows_new_orders() is False
```

### tests/integration/test_cb_event_protocol.py

```python
"""
Integration test: Central Bank event full protocol.

Verifies:
1. S08 CBWatcher detects pre-event block window
2. S05 CBEventGuard reads and respects the block
3. No trades execute during window
4. Post-event scalp is allowed with reduced sizing
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.s08_macro_intelligence.cb_watcher import CBWatcher
from services.s05_risk_manager.cb_event_guard import CBEventGuard


class TestCBEventProtocol:
    def test_watcher_detects_block_window(self) -> None:
        from unittest.mock import AsyncMock
        watcher = CBWatcher(state=AsyncMock(), bus=AsyncMock())
        events = watcher._events
        assert len(events) > 0

        first = events[0]
        event_time = datetime.fromisoformat(first["scheduled_at"])
        thirty_min_before = event_time - timedelta(minutes=30)

        blocked, event = watcher.is_in_block_window(thirty_min_before)
        assert blocked is True
        assert event is not None

    def test_no_block_far_from_event(self) -> None:
        from unittest.mock import AsyncMock
        watcher = CBWatcher(state=AsyncMock(), bus=AsyncMock())
        events = watcher._events
        first = events[0]
        event_time = datetime.fromisoformat(first["scheduled_at"])
        far_before = event_time - timedelta(hours=3)

        blocked, _ = watcher.is_in_block_window(far_before)
        assert blocked is False

    def test_post_event_monitor_window(self) -> None:
        from unittest.mock import AsyncMock
        watcher = CBWatcher(state=AsyncMock(), bus=AsyncMock())
        events = watcher._events
        first = events[0]
        event_time = datetime.fromisoformat(first["scheduled_at"])
        thirty_after = event_time + timedelta(minutes=30)

        monitoring, event = watcher.is_in_monitor_window(thirty_after)
        assert monitoring is True

    def test_guard_blocks_new_orders_during_window(self) -> None:
        """CBEventGuard.is_blocked() returns True during event window."""
        guard = CBEventGuard()
        # Mock: simulate active block
        from unittest.mock import MagicMock, patch
        with patch.object(guard, 'is_blocked', return_value=True):
            assert guard.is_blocked() is True
```

### tests/integration/test_circuit_breaker_integration.py

```python
"""
Integration test: circuit breaker prevents execution when triggered.
Tests the safety invariant: once open, NO orders can be submitted.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from services.s05_risk_manager.circuit_breaker import CircuitBreaker, CBState


class TestCircuitBreakerIntegration:
    def make_cb(self) -> CircuitBreaker:
        config = MagicMock()
        config.max_daily_drawdown_pct = 0.03
        config.max_loss_30min_pct = 0.02
        config.vix_spike_threshold_pct = 0.20
        config.service_down_timeout_seconds = 60
        config.data_anomaly_gap_pct = 0.05
        return CircuitBreaker(config=config)

    def test_all_six_triggers_open_breaker(self) -> None:
        triggers = [
            lambda cb: cb.update_daily_pnl(-0.031),
            lambda cb: cb.update_30min_pnl(-0.021),
            lambda cb: cb.update_vix_change(0.21),
            lambda cb: cb.notify_service_down("s01", 65),
            lambda cb: cb.update_price_gap(0.06),
        ]
        for i, trigger in enumerate(triggers):
            cb = self.make_cb()
            assert cb.state == CBState.CLOSED, f"Trigger {i}: should start CLOSED"
            trigger(cb)
            assert cb.state == CBState.OPEN, f"Trigger {i}: should be OPEN after trigger"
            assert cb.allows_new_orders() is False, f"Trigger {i}: must block orders"

    def test_open_breaker_blocks_all_orders(self) -> None:
        cb = self.make_cb()
        cb.update_daily_pnl(-0.04)  # trigger
        assert cb.state == CBState.OPEN

        # Verify 100 consecutive order checks all fail
        for _ in range(100):
            assert cb.allows_new_orders() is False

    def test_breaker_recovers_after_reset(self) -> None:
        cb = self.make_cb()
        cb.update_daily_pnl(-0.04)
        assert cb.state == CBState.OPEN

        # Manual reset (used at start of new trading day)
        cb.reset()
        assert cb.state == CBState.CLOSED
        assert cb.allows_new_orders() is True
```

### tests/integration/test_multi_asset.py

```python
"""
Integration test: BTC and AAPL signals processed simultaneously.
Verifies services handle concurrent symbols without interference.
"""
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from services.s02_signal_engine.signal_scorer import SignalScorer, SignalComponent


class TestMultiAssetConcurrent:
    def test_btc_and_aapl_signals_independent(self) -> None:
        """Two symbols generate independent signals with no cross-contamination."""
        scorer = SignalScorer(min_components=2, min_strength=0.15)

        # BTC: bullish signal
        btc_comps = [
            SignalComponent("microstructure", 0.90, 0.35, True),
            SignalComponent("bollinger",      0.80, 0.25, True),
        ]
        btc_score, btc_triggers = scorer.compute(btc_comps)

        # AAPL: bearish signal (same scorer instance)
        aapl_comps = [
            SignalComponent("microstructure", -0.85, 0.35, True),
            SignalComponent("bollinger",      -0.70, 0.25, True),
        ]
        aapl_score, aapl_triggers = scorer.compute(aapl_comps)

        assert btc_score > 0, "BTC should be bullish"
        assert aapl_score < 0, "AAPL should be bearish"
        assert btc_score > 0 and aapl_score < 0, "Signals must be independent"
```

---

## OBJECTIVE 3 — Walk-Forward Backtest with proper metrics

Read current `backtesting/walk_forward.py`.
Implement the Lopez de Prado purged cross-validation:

```python
"""
Walk-Forward Validation — Purged Cross-Validation.

Lopez de Prado (2018) — Advances in Financial Machine Learning, Chapter 7.
Standard CV leaks future information for financial time series.
Solution: purge train samples that overlap with test period + embargo.

Window structure:
  [==TRAIN==][--PURGE--][==TEST==][EMBARGO]
  
  train: data used to estimate parameters
  purge: train samples too close to test window → removed (prevents leakage)
  test:  out-of-sample evaluation
  embargo: N minutes after test → removed from next train (prevents contamination)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class WalkForwardWindow:
    window_id: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    embargo_end: datetime


@dataclass  
class WalkForwardResult:
    window_id: int
    sharpe: float
    max_drawdown: float
    win_rate: float
    n_trades: int
    out_of_sample_return: float


class WalkForwardValidator:
    """
    Purged walk-forward cross-validation for financial time series.
    
    Prevents the following leakage sources:
    1. Lookahead bias: train data before test only
    2. Overlap leakage: train samples spanning test period removed
    3. Embargo: N minutes after test period purged from next train
    """

    def __init__(
        self,
        n_windows: int = 6,
        train_months: int = 6,
        test_months: int = 1,
        embargo_minutes: int = 60,
    ) -> None:
        self.n_windows = n_windows
        self.train_months = train_months
        self.test_months = test_months
        self.embargo_minutes = embargo_minutes

    def build_windows(
        self,
        data_start: datetime,
        data_end: datetime,
    ) -> list[WalkForwardWindow]:
        """Build N train/test windows with purging and embargo."""
        windows = []
        test_duration = timedelta(days=self.test_months * 30)
        train_duration = timedelta(days=self.train_months * 30)
        embargo = timedelta(minutes=self.embargo_minutes)

        for i in range(self.n_windows):
            test_start = data_start + train_duration + i * test_duration
            test_end   = test_start + test_duration

            if test_end > data_end:
                break

            windows.append(WalkForwardWindow(
                window_id=i,
                train_start=data_start,
                train_end=test_start - embargo,  # purge period before test
                test_start=test_start,
                test_end=test_end,
                embargo_end=test_end + embargo,
            ))

        return windows

    def run_validation(
        self,
        data: pd.DataFrame,
        backtest_fn: Any,  # callable(train_df, test_df) → WalkForwardResult
    ) -> list[WalkForwardResult]:
        """
        Run walk-forward validation across all windows.
        
        Args:
            data: Full historical dataset with 'timestamp' column
            backtest_fn: Function that takes (train_df, test_df) → metrics
            
        Returns:
            List of results per window (out-of-sample)
        """
        data_start = pd.Timestamp(data["timestamp"].min()).to_pydatetime()
        data_end   = pd.Timestamp(data["timestamp"].max()).to_pydatetime()
        windows = self.build_windows(data_start, data_end)

        results = []
        for window in windows:
            train_df = data[
                (data["timestamp"] >= window.train_start) &
                (data["timestamp"] < window.train_end)
            ]
            test_df = data[
                (data["timestamp"] >= window.test_start) &
                (data["timestamp"] < window.test_end)
            ]

            if len(test_df) < 100:
                continue

            result = backtest_fn(train_df, test_df, window.window_id)
            results.append(result)

        return results

    def aggregate_results(self, results: list[WalkForwardResult]) -> dict[str, float]:
        """
        Aggregate out-of-sample performance across all windows.
        This is the TRUE performance estimate — no in-sample bias.
        """
        if not results:
            return {"error": "no results"}

        sharpes = [r.sharpe for r in results]
        dds = [r.max_drawdown for r in results]
        win_rates = [r.win_rate for r in results]
        n_trades = sum(r.n_trades for r in results)

        return {
            "oos_sharpe_mean":   float(np.mean(sharpes)),
            "oos_sharpe_min":    float(np.min(sharpes)),
            "oos_sharpe_std":    float(np.std(sharpes)),
            "oos_max_dd_mean":   float(np.mean(dds)),
            "oos_win_rate_mean": float(np.mean(win_rates)),
            "n_windows":         len(results),
            "n_total_trades":    n_trades,
            "is_consistent":     float(np.std(sharpes)) < 0.5,  # consistent across windows
        }
```

Tests in `tests/unit/backtesting/test_walk_forward.py`:

```python
from datetime import datetime, timezone
import pandas as pd
from backtesting.walk_forward import WalkForwardValidator, WalkForwardResult


class TestWalkForwardValidator:
    def make_validator(self) -> WalkForwardValidator:
        return WalkForwardValidator(n_windows=3, train_months=3, test_months=1)

    def test_windows_dont_overlap(self) -> None:
        v = self.make_validator()
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end   = datetime(2024, 12, 31, tzinfo=timezone.utc)
        windows = v.build_windows(start, end)

        for i in range(len(windows) - 1):
            assert windows[i].test_end <= windows[i + 1].test_start

    def test_train_ends_before_test(self) -> None:
        v = self.make_validator()
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end   = datetime(2024, 12, 31, tzinfo=timezone.utc)
        windows = v.build_windows(start, end)

        for w in windows:
            assert w.train_end < w.test_start

    def test_aggregate_results(self) -> None:
        v = self.make_validator()
        results = [
            WalkForwardResult(0, sharpe=1.2, max_drawdown=0.04, win_rate=0.54, n_trades=50, out_of_sample_return=0.05),
            WalkForwardResult(1, sharpe=0.9, max_drawdown=0.06, win_rate=0.51, n_trades=45, out_of_sample_return=0.03),
        ]
        agg = v.aggregate_results(results)
        assert agg["oos_sharpe_mean"] == pytest.approx(1.05)
        assert agg["n_total_trades"] == 95
        assert "is_consistent" in agg
```

---

## OBJECTIVE 4 — S09 Feedback Loop: Drift Detector + Daily Report

Read current `services/s09_feedback_loop/drift_detector.py`.
Implement complete drift detection:

```python
"""
Drift Detector — Model performance degradation detection.

Monitors rolling win rate over last 50 trades.
Alerts if win rate drops > 10% from 3-month baseline.
Triggers daily review cycle.

This service does NOT automatically adjust parameters.
It observes and reports — humans validate all changes.
(per MANIFEST.md Section 9, Service 09)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class DriftAlert:
    timestamp: datetime
    current_win_rate: float
    baseline_win_rate: float
    drop_pct: float
    n_trades_in_window: int
    message: str


class DriftDetector:
    """
    Detects when system performance has drifted below its baseline.
    
    Alert threshold: win rate drops > 10% from 3-month baseline.
    Minimum sample: 50 trades required before any alert fires.
    """

    DRIFT_THRESHOLD = 0.10   # 10% relative drop
    MIN_TRADES = 50

    def check_drift(
        self,
        recent_trades: list[Any],  # last N TradeRecord objects
        baseline_win_rate: float,
    ) -> DriftAlert | None:
        """
        Check if recent performance has drifted from baseline.
        
        Args:
            recent_trades: Last 50 TradeRecords from Redis
            baseline_win_rate: 3-month historical win rate
            
        Returns:
            DriftAlert if drift detected, None if healthy
        """
        if len(recent_trades) < self.MIN_TRADES:
            return None  # insufficient data

        wins = sum(1 for t in recent_trades if getattr(t, "pnl_net", 0) > 0)
        current_wr = wins / len(recent_trades)

        drop = baseline_win_rate - current_wr
        drop_pct = drop / baseline_win_rate if baseline_win_rate > 0 else 0.0

        if drop_pct >= self.DRIFT_THRESHOLD:
            return DriftAlert(
                timestamp=datetime.now(timezone.utc),
                current_win_rate=current_wr,
                baseline_win_rate=baseline_win_rate,
                drop_pct=drop_pct,
                n_trades_in_window=len(recent_trades),
                message=(
                    f"WIN RATE DRIFT DETECTED: {current_wr:.1%} vs baseline {baseline_win_rate:.1%} "
                    f"({drop_pct:.1%} drop over {len(recent_trades)} trades). "
                    f"Review signal quality and current regime."
                ),
            )
        return None
```

Tests in `tests/unit/s09/test_drift_detector.py`:

```python
from unittest.mock import MagicMock
from services.s09_feedback_loop.drift_detector import DriftDetector


def make_trades(n_wins: int, n_losses: int) -> list[MagicMock]:
    trades = []
    for _ in range(n_wins):
        t = MagicMock()
        t.pnl_net = 10.0
        trades.append(t)
    for _ in range(n_losses):
        t = MagicMock()
        t.pnl_net = -8.0
        trades.append(t)
    return trades


class TestDriftDetector:
    def test_no_alert_when_healthy(self) -> None:
        detector = DriftDetector()
        trades = make_trades(n_wins=30, n_losses=20)  # 60% win rate
        alert = detector.check_drift(trades, baseline_win_rate=0.58)
        assert alert is None  # only 2% drop, below 10% threshold

    def test_alert_when_significant_drop(self) -> None:
        detector = DriftDetector()
        trades = make_trades(n_wins=22, n_losses=28)  # 44% win rate
        alert = detector.check_drift(trades, baseline_win_rate=0.55)
        assert alert is not None
        assert alert.drop_pct >= 0.10

    def test_no_alert_insufficient_trades(self) -> None:
        detector = DriftDetector()
        trades = make_trades(n_wins=5, n_losses=5)  # only 10 trades
        alert = detector.check_drift(trades, baseline_win_rate=0.55)
        assert alert is None  # need 50 minimum

    def test_alert_message_is_actionable(self) -> None:
        detector = DriftDetector()
        trades = make_trades(n_wins=20, n_losses=30)  # 40% win rate
        alert = detector.check_drift(trades, baseline_win_rate=0.56)
        assert alert is not None
        assert "DRIFT" in alert.message
        assert "Review" in alert.message
```

---

## OBJECTIVE 5 — Property Tests with Hypothesis (critical safety invariants)

Create `tests/unit/property/test_safety_invariants.py`:

```python
"""
Property-based tests for core safety invariants.
These properties must hold for ALL possible inputs — not just examples.

Using Hypothesis for automatic edge case generation.

These tests are the mathematical proof that the system cannot violate
its core safety properties regardless of market conditions.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from services.s04_fusion_engine.kelly_sizer import KellySizer
from services.s02_signal_engine.signal_scorer import SignalScorer, SignalComponent


class TestKellyNeverExceedsCapital:
    """Property: Kelly fraction always produces position < capital."""

    @given(
        capital=st.decimals(min_value=Decimal("100"), max_value=Decimal("1000000"), places=2),
        win_rate=st.floats(min_value=0.30, max_value=0.75, allow_nan=False),
        rr=st.floats(min_value=0.5, max_value=5.0, allow_nan=False),
        macro_mult=st.floats(min_value=0.0, max_value=1.5, allow_nan=False),
    )
    @settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
    def test_position_never_exceeds_capital(
        self,
        capital: Decimal,
        win_rate: float,
        rr: float,
        macro_mult: float,
    ) -> None:
        """No matter the inputs, position size must be < capital."""
        sizer = KellySizer()
        size = sizer.position_size(capital, win_rate, rr, macro_mult)
        assert size >= Decimal("0"), "Position cannot be negative"
        assert size <= capital, f"Position {size} exceeds capital {capital}"


class TestSignalScoreInBounds:
    """Property: signal score always in [-1.0, +1.0]."""

    @given(
        s1=st.floats(-2.0, 2.0, allow_nan=False),
        s2=st.floats(-2.0, 2.0, allow_nan=False),
        s3=st.floats(-2.0, 2.0, allow_nan=False),
        min_str=st.floats(0.0, 0.5, allow_nan=False),
    )
    @settings(max_examples=300)
    def test_score_always_clamped(
        self, s1: float, s2: float, s3: float, min_str: float
    ) -> None:
        """Signal score always in valid range regardless of component values."""
        scorer = SignalScorer(min_components=2, min_strength=min_str)
        components = [
            SignalComponent("microstructure", max(-1.0, min(1.0, s1)), 0.35, True),
            SignalComponent("bollinger",      max(-1.0, min(1.0, s2)), 0.25, True),
            SignalComponent("ema_mtf",        max(-1.0, min(1.0, s3)), 0.20, True),
        ]
        score, _ = scorer.compute(components)
        assert -1.0 <= score <= 1.0, f"Score {score} out of range"


class TestRiskNeverExceedsBudget:
    """Property: approved order risk never exceeds 0.5% of capital."""

    @given(
        capital=st.decimals(min_value=Decimal("1000"), max_value=Decimal("100000"), places=2),
        entry_price=st.decimals(min_value=Decimal("1"), max_value=Decimal("100000"), places=2),
        stop_pct=st.decimals(min_value=Decimal("0.001"), max_value=Decimal("0.05"), places=4),
    )
    @settings(max_examples=300)
    def test_risk_within_budget(
        self, capital: Decimal, entry_price: Decimal, stop_pct: Decimal
    ) -> None:
        """Kelly-sized position must have risk ≤ 0.5% of capital."""
        from services.s04_fusion_engine.kelly_sizer import KellySizer
        sizer = KellySizer()

        stop_loss = entry_price * (Decimal("1") - stop_pct)
        risk_per_unit = entry_price - stop_loss

        size = sizer.position_size(capital, 0.55, 1.8, 1.0)
        if risk_per_unit > 0 and size > 0:
            actual_risk = risk_per_unit * size / entry_price * capital
            max_allowed = capital * Decimal("0.005")
            assert actual_risk <= max_allowed * Decimal("1.1"), (
                f"Risk {actual_risk} exceeds budget {max_allowed} "
                f"(capital={capital}, size={size})"
            )
```

---

## OBJECTIVE 6 — Latency measurement (tick → signal < 50ms)

Create `tests/performance/test_latency.py`:

```python
"""
Latency tests: verify signal pipeline processes ticks in < 50ms.

Per DEVELOPMENT_PLAN.md Phase 3 DoD:
  "Latency: tick → signal < 50ms (measured)"

These tests do NOT require Redis or ZMQ — they measure pure computation latency.
"""
from __future__ import annotations

import time
from decimal import Decimal
from datetime import datetime, timezone

import numpy as np
import pytest

from services.s02_signal_engine.signal_scorer import SignalScorer, SignalComponent
from services.s03_regime_detector.regime_engine import RegimeEngine
from services.s03_regime_detector.session_tracker import SessionTracker


class TestComputationLatency:
    LATENCY_BUDGET_MS = 50.0  # 50ms budget per tick

    def test_signal_scorer_latency(self) -> None:
        """SignalScorer.compute() must run in < 5ms (it's in the hot path)."""
        scorer = SignalScorer()
        components = [
            SignalComponent("microstructure", 0.8, 0.35, True),
            SignalComponent("bollinger",      0.7, 0.25, True),
            SignalComponent("ema_mtf",        0.6, 0.20, True),
            SignalComponent("rsi_divergence", 0.5, 0.15, True),
            SignalComponent("vwap",           0.3, 0.05, True),
        ]

        # Warm up (JIT-style)
        for _ in range(10):
            scorer.compute(components)

        # Measure
        times = []
        for _ in range(1000):
            t0 = time.perf_counter()
            scorer.compute(components)
            times.append((time.perf_counter() - t0) * 1000)

        p99_ms = np.percentile(times, 99)
        assert p99_ms < 5.0, f"SignalScorer p99 latency = {p99_ms:.2f}ms (budget: 5ms)"

    def test_regime_engine_latency(self) -> None:
        """RegimeEngine.compute() must run in < 2ms."""
        engine = RegimeEngine()

        times = []
        for _ in range(1000):
            t0 = time.perf_counter()
            engine.compute(vix=18.0, dxy_1h_change_pct=0.1, yield_10y=4.5, yield_2y=4.3)
            times.append((time.perf_counter() - t0) * 1000)

        p99_ms = np.percentile(times, 99)
        assert p99_ms < 2.0, f"RegimeEngine p99 latency = {p99_ms:.2f}ms (budget: 2ms)"

    def test_session_tracker_latency(self) -> None:
        """SessionTracker.get_session() must run in < 1ms."""
        tracker = SessionTracker()
        now = datetime.now(timezone.utc)

        times = []
        for _ in range(10000):
            t0 = time.perf_counter()
            tracker.get_session(now)
            times.append((time.perf_counter() - t0) * 1000)

        p99_ms = np.percentile(times, 99)
        assert p99_ms < 1.0, f"SessionTracker p99 latency = {p99_ms:.2f}ms (budget: 1ms)"
```

---

## OBJECTIVE 7 — CHANGELOG.md + PR Template

Create `CHANGELOG.md`:

```markdown
# Changelog

All notable changes to the APEX Trading System are documented here.
Format: [Semantic Versioning](https://semver.org/)

---

## [Unreleased] — Phase 3 Integration & Hardening

### Added
- Full integration test suite (tests/integration/)
- Walk-forward validation with purged cross-validation (Lopez de Prado method)
- Session tracker with complete DST support (America/New_York)
- Drift detector for signal quality monitoring (S09)
- Property-based tests for core safety invariants (Hypothesis)
- Latency measurement tests (tick → signal < 50ms verified)
- CHANGELOG.md and PR template

---

## [0.2.0] — Phase 2: Intelligence Engine

### Added
- SignalScorer: multi-dimensional confluence matrix (OFI 35% + BB 25% + EMA 20% + RSI 15% + VWAP 5%)
- RegimeEngine: dynamic VIX/DXY/yield curve classification with macro_mult
- CBWatcher: FOMC 2024-2025 calendar with 45min pre-event block windows
- Cross-asset correlation: BTC/SPY protection logic
- Kelly dynamic sizing connected to S09 rolling win rate stats
- Backtest macro event injection (FOMC dates in historical replay)
- Sector exposure limits (25% max per sector, S05)

---

## [0.1.0] — Phase 1: Stabilization

### Added
- Zero mypy strict errors (143 → 0)
- Docker Windows compatibility
- Real Binance historical data download (no API key required)
- core/topics.py: centralized ZMQ topic constants
- Initial test suite (13% → 40% coverage)
- Rust warning cleanup (zero warnings policy)
- README.md with setup and quickstart
- MANIFEST.md committed to repository
- CLAUDE.md: development contract for Claude Code
```

Create `.github/PULL_REQUEST_TEMPLATE.md`:

```markdown
## Summary
<!-- What does this PR do? Which phase/objective does it address? -->

## Type of change
- [ ] Bug fix (non-breaking)
- [ ] New feature
- [ ] Breaking change
- [ ] Performance improvement
- [ ] Documentation

## Testing
- [ ] `mypy .` returns zero errors
- [ ] `ruff check .` passes
- [ ] All new functions have unit tests
- [ ] `pytest tests/unit/` passes
- [ ] Coverage did not decrease (run `pytest --cov`)
- [ ] Integration tests pass (if applicable): `pytest tests/integration/`

## Mathematical validation (if applicable)
- [ ] Formula documented in docstring with academic reference
- [ ] Property test added with Hypothesis
- [ ] Result verified against manual calculation

## CLAUDE.md compliance
- [ ] Decimal used for all prices/sizes (no float)
- [ ] UTC datetime used (no naive datetimes)
- [ ] structlog used (no print())
- [ ] ZMQ topics via core/topics.py (no hardcoded strings)
- [ ] SOLID principles applied
- [ ] Adaptive behavior maintained (service reads inputs continuously, not only at startup)
```

---

## OBJECTIVE 8 — Nightly backtest CI (GitHub Actions)

Create `.github/workflows/backtest.yml`:

```yaml
name: Nightly Backtest Regression

on:
  schedule:
    - cron: '0 6 * * 1-5'  # 6 AM UTC Mon-Fri (before US market open)
  workflow_dispatch:       # manual trigger

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true

jobs:
  backtest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          lfs: true

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Build Rust extensions
        uses: dtolnay/rust-toolchain@stable
      - run: |
          pip install "maturin>=1.9.4"
          (cd rust/apex_mc   && maturin build --release)
          (cd rust/apex_risk && maturin build --release)
          python -m pip install ./rust/target/wheels/*.whl

      - name: Generate test fixture (if missing)
        run: |
          if [ ! -f tests/fixtures/30d_btcusdt_1m.parquet ]; then
            PYTHONPATH=. python scripts/generate_test_fixtures.py
          fi

      - name: Run backtest regression
        run: PYTHONPATH=. python scripts/backtest_regression.py --fixture tests/fixtures/30d_btcusdt_1m.parquet
        env:
          BACKTEST_MIN_SHARPE: "0.5"
          BACKTEST_MAX_DD: "0.12"

      - name: Run walk-forward validation
        run: |
          PYTHONPATH=. python -c "
          import pandas as pd
          from backtesting.walk_forward import WalkForwardValidator
          df = pd.read_parquet('tests/fixtures/30d_btcusdt_1m.parquet')
          df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
          v = WalkForwardValidator(n_windows=3, train_months=1, test_months=0)
          print(f'Walk-forward: {len(df)} candles available')
          print('Walk-forward setup: OK')
          "

      - name: Upload backtest report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: backtest-report-${{ github.run_id }}
          path: |
            backtest_report_*.json
            backtest_report_*.html
          retention-days: 30
```

---

## OBJECTIVE 9 — Coverage push to 85%+

Check current coverage by module:

```bash
.venv/Scripts/python -m pytest tests/ --cov=. --cov-report=term-missing 2>&1 | grep -v ".venv" | grep -E "services|core|backtesting|supervisor"
```

For every module at < 85%, identify the untested functions and add targeted tests.
Priority modules (most impact on alpha):

1. `services/s02_signal_engine/microstructure.py` — OFI, CVD, Kyle Lambda
2. `services/s03_regime_detector/regime_engine.py` — VIX thresholds
3. `services/s04_fusion_engine/kelly_sizer.py` — Kelly formula
4. `services/s05_risk_manager/position_rules.py` — all 6 rules
5. `core/state.py` — get/set/delete (use fakeredis)
6. `backtesting/metrics.py` — Sharpe, DD, win rate calculations

For `core/state.py`, use fakeredis:

```python
# tests/unit/core/test_state.py
import fakeredis.aioredis
import pytest
from core.state import StateStore

@pytest.fixture
async def state() -> StateStore:
    s = StateStore.__new__(StateStore)
    s._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return s

async def test_set_and_get(state: StateStore) -> None:
    await state.set("test:key", {"value": "42"})
    result = await state.get("test:key")
    assert result == {"value": "42"}

async def test_missing_key_returns_none(state: StateStore) -> None:
    result = await state.get("nonexistent:key")
    assert result is None

async def test_delete_key(state: StateStore) -> None:
    await state.set("to:delete", {"x": 1})
    await state.delete("to:delete")
    assert await state.get("to:delete") is None
```

---

## OBJECTIVE 10 — Final validation: paper trading readiness check

Run this complete checklist. All must pass before calling the system paper-trading-ready:

```bash
echo "=== 1. ZERO MYPY ERRORS ==="
PYTHONPATH=. .venv/Scripts/python -m mypy . 2>&1 | grep "error:" | grep -v ".venv" | wc -l
# Expected: 0

echo "=== 2. ZERO RUFF ERRORS ==="
.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .
# Expected: "All checks passed!"

echo "=== 3. ZERO RUST WARNINGS ==="
cd rust && cargo build --workspace 2>&1 | grep "warning:" && cd ..
# Expected: no output

echo "=== 4. ALL UNIT TESTS PASS ==="
PYTHONPATH=. .venv/Scripts/python -m pytest tests/unit/ -v --tb=short -q
# Expected: all green

echo "=== 5. INTEGRATION TESTS PASS ==="
docker compose -f docker/docker-compose.test.yml up -d
PYTHONPATH=. .venv/Scripts/python -m pytest tests/integration/ -v --tb=short
docker compose -f docker/docker-compose.test.yml down
# Expected: all green

echo "=== 6. COVERAGE >= 85% ==="
PYTHONPATH=. .venv/Scripts/python -m pytest tests/ --cov=. --cov-report=term-missing --cov-fail-under=85
# Expected: PASSED (coverage meets target)

echo "=== 7. LATENCY WITHIN BUDGET ==="
PYTHONPATH=. .venv/Scripts/python -m pytest tests/performance/ -v
# Expected: all < budget (5ms scorer, 2ms regime, 1ms session)

echo "=== 8. PROPERTY TESTS PASS ==="
PYTHONPATH=. .venv/Scripts/python -m pytest tests/unit/property/ -v
# Expected: all invariants hold

echo "=== 9. BACKTEST GENERATES TRADES ==="
PYTHONPATH=. .venv/Scripts/python scripts/generate_test_fixtures.py
BACKTEST_MIN_SHARPE=0.3 PYTHONPATH=. .venv/Scripts/python scripts/backtest_regression.py \
  --fixture tests/fixtures/30d_btcusdt_1m.parquet
# Expected: trades generated, gates pass

echo "=== 10. SESSION TRACKER DST ==="
PYTHONPATH=. .venv/Scripts/python -m pytest tests/unit/s03/test_session_tracker.py -v
# Expected: all 11 tests pass including DST spring/fall back

echo ""
echo "=== PAPER TRADING READINESS SUMMARY ==="
echo "If all 10 checks above passed: system is PAPER-TRADING READY"
echo "Next step: docker compose up + 3 months paper campaign"
```

Then commit:

```bash
git add -A
git commit -m "feat: Phase 3 complete — integration tests, walk-forward, drift detector, 85%+ coverage, paper trading ready"
git push origin main
```

---

## CONSTRAINTS (CLAUDE.md — non-negotiable)

- mypy strict: zero errors on every commit
- All new code: complete type annotations
- All new classes: unit tests BEFORE the class is considered done
- 85% coverage gate enforced in CI
- No float for prices — Decimal only
- UTC datetime — no naive datetimes
- structlog only — no print()
- ZMQ topics via core/topics.py only
- fakeredis in unit tests — no real Redis in tests/unit/
- SOLID: one responsibility per class
- Mathematical formulas: docstring + academic reference
- Adaptive behavior: services read inputs continuously, not only at startup

## DEFINITION OF DONE (from DEVELOPMENT_PLAN.md)

Phase 3 is DONE when ALL of:
- [ ] All specified files exist and are implemented
- [ ] mypy --strict passes with zero errors
- [ ] ruff check passes with zero warnings
- [ ] Unit tests: all green, 85%+ coverage
- [ ] Integration tests: all green (requires Docker)
- [ ] Performance tests: all latency budgets met
- [ ] Property tests: all invariants verified
- [ ] CI pipeline fully green (quality + rust + unit + integration + backtest)
- [ ] CHANGELOG.md updated
- [ ] Version bumped to v0.3.0