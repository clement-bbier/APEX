"""JobRunner — Template Method for executing a single backfill job.

Implements the run lifecycle: lock → retry loop → fetch → insert → state.
The fetch-specific logic is delegated to the connector via ConnectorFactory.
JobRunner depends only on abstractions (factory, repo, state), never on
concrete connector classes.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog

from core.config import Settings
from core.data.timescale_repository import TimescaleRepository
from core.models.data import BarSize
from services.s01_data_ingestion.connectors.base import DataConnector
from services.s01_data_ingestion.connectors.calendar_base import CalendarConnector
from services.s01_data_ingestion.connectors.fundamentals_base import (
    FundamentalsConnector,
)
from services.s01_data_ingestion.connectors.macro_base import MacroConnector

from .config import JobConfig
from .connector_factory import ConnectorFactory
from .state import JobRunResult, JobStateManager

logger = structlog.get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_LOOKBACK_DAYS: int = 30
_STATUS_SUCCESS: str = "success"
_STATUS_FAILED: str = "failed"
_STATUS_LOCKED: str = "locked"
_STATUS_TIMEOUT: str = "timeout"

# Connector type groups for dispatch
_BAR_CONNECTORS: frozenset[str] = frozenset(
    {
        "binance_historical",
        "alpaca_historical",
        "massive_historical",
        "yahoo_historical",
    }
)

_MACRO_CONNECTORS: frozenset[str] = frozenset(
    {
        "fred",
        "ecb_sdw",
        "boj",
    }
)

_CALENDAR_CONNECTORS: frozenset[str] = frozenset(
    {
        "fomc_scraper",
        "ecb_scraper",
        "boj_calendar_scraper",
        "fred_releases",
    }
)

_FUNDAMENTALS_CONNECTORS: frozenset[str] = frozenset(
    {
        "edgar",
        "simfin",
    }
)


class JobRunner:
    """Execute a single backfill job with retry, lock, and state tracking.

    Uses the Template Method pattern: ``run()`` orchestrates the lifecycle,
    while ``_execute_fetch_and_insert()`` dispatches to the correct connector
    method based on connector type.
    """

    def __init__(
        self,
        config: JobConfig,
        factory: ConnectorFactory,
        repo: TimescaleRepository,
        state: JobStateManager,
        settings: Settings,
    ) -> None:
        self._config = config
        self._factory = factory
        self._repo = repo
        self._state = state
        self._settings = settings

    async def run(self) -> JobRunResult:
        """Execute the backfill job with full lifecycle management.

        Returns:
            A :class:`JobRunResult` with the outcome.
        """
        started_at = datetime.now(UTC)
        job_name = self._config.name

        if not await self._state.acquire_lock(job_name, self._config.timeout_seconds):
            return self._build_result(started_at, _STATUS_LOCKED)

        try:
            result = await self._run_with_timeout(started_at)
        finally:
            await self._state.release_lock(job_name)

        await self._state.append_run_history(job_name, result)
        return result

    async def _run_with_timeout(self, started_at: datetime) -> JobRunResult:
        """Wrap the retry loop with an asyncio timeout."""
        try:
            return await asyncio.wait_for(
                self._run_with_retry(started_at),
                timeout=self._config.timeout_seconds,
            )
        except TimeoutError:
            logger.error(
                "job_runner.timeout",
                job=self._config.name,
                timeout=self._config.timeout_seconds,
            )
            return self._build_result(started_at, _STATUS_TIMEOUT)

    async def _run_with_retry(self, started_at: datetime) -> JobRunResult:
        """Retry the fetch-and-insert loop up to max_attempts times."""
        last_error: str | None = None
        max_attempts = self._config.retry.max_attempts
        backoff = self._config.retry.backoff_seconds

        for attempt in range(1, max_attempts + 1):
            try:
                rows = await self._execute_fetch_and_insert()
                await self._state.set_last_success(self._config.name, datetime.now(UTC))
                logger.info(
                    "job_runner.success",
                    job=self._config.name,
                    rows=rows,
                    attempt=attempt,
                )
                return self._build_result(started_at, _STATUS_SUCCESS, rows=rows)
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "job_runner.attempt_failed",
                    job=self._config.name,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    error=last_error,
                )
                if attempt < max_attempts:
                    delay = backoff * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)

        logger.error(
            "job_runner.retries_exhausted",
            job=self._config.name,
            max_attempts=max_attempts,
            last_error=last_error,
        )
        return self._build_result(started_at, _STATUS_FAILED, error_message=last_error)

    async def _execute_fetch_and_insert(self) -> int:
        """Dispatch to the correct connector type and insert results."""
        connector_name = self._config.connector
        connector = self._factory.create(connector_name, self._settings)
        start, end = await self._compute_window()

        if connector_name in _BAR_CONNECTORS:
            return await self._fetch_and_insert_bars(
                connector, start, end  # type: ignore[arg-type]
            )
        if connector_name in _MACRO_CONNECTORS:
            return await self._fetch_and_insert_macro(
                connector, start, end  # type: ignore[arg-type]
            )
        if connector_name in _CALENDAR_CONNECTORS:
            return await self._fetch_and_insert_calendar(
                connector, start, end  # type: ignore[arg-type]
            )
        if connector_name in _FUNDAMENTALS_CONNECTORS:
            return await self._fetch_and_insert_fundamentals(
                connector, start, end  # type: ignore[arg-type]
            )

        msg = f"No dispatch handler for connector {connector_name!r}"
        raise ValueError(msg)

    async def _compute_window(self) -> tuple[datetime, datetime]:
        """Compute the fetch window: [last_success or lookback, now)."""
        last_success = await self._state.get_last_success(self._config.name)
        end = datetime.now(UTC)
        if last_success is not None:
            start = last_success
        else:
            start = end - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
        return start, end

    async def _fetch_and_insert_bars(
        self,
        connector: DataConnector,
        start: datetime,
        end: datetime,
    ) -> int:
        """Fetch bars from a DataConnector and insert into the repository."""
        params = self._config.params
        symbol: str = params.get("symbol", "")
        bar_size_str: str = params.get("bar_size", "D1")
        bar_size = BarSize(bar_size_str)

        total = 0
        async for batch in connector.fetch_bars(symbol, bar_size, start, end):
            if batch:
                total += await self._repo.insert_bars(batch)
        return total

    async def _fetch_and_insert_macro(
        self,
        connector: MacroConnector,
        start: datetime,
        end: datetime,
    ) -> int:
        """Fetch macro series from a MacroConnector and insert."""
        series_id: str = self._config.params.get("series_id", "")

        total = 0
        async for batch in connector.fetch_series(series_id, start, end):
            if batch:
                total += await self._repo.insert_macro_points(batch)
        return total

    async def _fetch_and_insert_calendar(
        self,
        connector: CalendarConnector,
        start: datetime,
        end: datetime,
    ) -> int:
        """Fetch calendar events from a CalendarConnector and insert."""
        total = 0
        async for batch in connector.fetch_events(start, end):
            if batch:
                total += await self._repo.insert_economic_events(batch)
        return total

    async def _fetch_and_insert_fundamentals(
        self,
        connector: FundamentalsConnector,
        start: datetime,
        end: datetime,
    ) -> int:
        """Fetch fundamentals from a FundamentalsConnector and insert."""
        params = self._config.params
        ticker: str = params.get("ticker", "")
        filing_types: list[str] = params.get("filing_types", ["10-K", "10-Q"])

        total = 0
        async for batch in connector.fetch_fundamentals(ticker, filing_types, start, end):
            if batch:
                total += await self._repo.insert_fundamentals(batch)
        return total

    def _build_result(
        self,
        started_at: datetime,
        status: str,
        rows: int = 0,
        error_message: str | None = None,
    ) -> JobRunResult:
        """Build a JobRunResult with current timestamp as finished_at."""
        return JobRunResult(
            job_name=self._config.name,
            status=status,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            rows_inserted=rows,
            error_message=error_message,
        )
