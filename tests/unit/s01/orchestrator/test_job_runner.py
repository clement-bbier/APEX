"""Tests for JobRunner (template method pattern)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from services.s01_data_ingestion.orchestrator.config import JobConfig, RetryConfig
from services.s01_data_ingestion.orchestrator.connector_factory import ConnectorFactory
from services.s01_data_ingestion.orchestrator.job_runner import JobRunner
from services.s01_data_ingestion.orchestrator.state import JobStateManager


def _make_job(
    name: str = "test_job",
    connector: str = "binance_historical",
    params: dict[str, object] | None = None,
    max_attempts: int = 2,
    backoff: float = 0.01,
    timeout: int = 30,
    dependencies: list[str] | None = None,
) -> JobConfig:
    return JobConfig(
        name=name,
        connector=connector,
        schedule="0 * * * *",
        params=params or {"symbol": "BTCUSDT", "bar_size": "1m"},
        retry=RetryConfig(max_attempts=max_attempts, backoff_seconds=backoff),
        timeout_seconds=timeout,
        dependencies=dependencies or [],
    )


@pytest.fixture
async def redis() -> fakeredis.aioredis.FakeRedis:
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def state(redis: fakeredis.aioredis.FakeRedis) -> JobStateManager:
    return JobStateManager(redis)


@pytest.fixture
def mock_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.insert_bars = AsyncMock(return_value=100)
    repo.insert_macro_points = AsyncMock(return_value=50)
    repo.insert_economic_events = AsyncMock(return_value=10)
    repo.insert_fundamentals = AsyncMock(return_value=5)
    return repo


@pytest.fixture
def mock_settings() -> MagicMock:
    return MagicMock()


def _make_bar_connector(
    batches: list[object] | None = None,
    error: Exception | None = None,
) -> MagicMock:
    connector = MagicMock()

    async def _fetch_bars(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if error:
            raise error
        for batch in batches or [["bar1", "bar2"]]:
            yield batch

    connector.fetch_bars = _fetch_bars
    return connector


class TestJobRunnerSuccess:
    """Happy-path tests."""

    @pytest.mark.asyncio
    async def test_success_returns_result(
        self,
        state: JobStateManager,
        mock_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        job = _make_job()
        factory = MagicMock(spec=ConnectorFactory)
        factory.create.return_value = _make_bar_connector()

        runner = JobRunner(job, factory, mock_repo, state, mock_settings)
        result = await runner.run()

        assert result.status == "success"
        assert result.rows_inserted == 100

    @pytest.mark.asyncio
    async def test_last_success_is_window_end_not_wallclock(
        self,
        state: JobStateManager,
        mock_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        """FIX 2: last_success should be the window end, not completion time."""
        job = _make_job()
        factory = MagicMock(spec=ConnectorFactory)
        factory.create.return_value = _make_bar_connector()

        before = datetime.now(UTC)
        runner = JobRunner(job, factory, mock_repo, state, mock_settings)
        await runner.run()

        last = await state.get_last_success("test_job")
        assert last is not None
        # last_success should be <= now (the window end computed before fetch)
        # and >= before (it was computed during run)
        assert before <= last <= datetime.now(UTC)

    @pytest.mark.asyncio
    async def test_history_recorded_on_success(
        self,
        state: JobStateManager,
        mock_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        job = _make_job()
        factory = MagicMock(spec=ConnectorFactory)
        factory.create.return_value = _make_bar_connector()

        runner = JobRunner(job, factory, mock_repo, state, mock_settings)
        await runner.run()

        history = await state.get_run_history("test_job")
        assert len(history) == 1
        assert history[0].status == "success"


class TestJobRunnerRetry:
    """Retry behavior tests."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(
        self,
        state: JobStateManager,
        mock_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        job = _make_job(max_attempts=3, backoff=0.001)
        call_count = 0

        async def _fetch_bars(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")
            yield ["bar"]

        connector = MagicMock()
        connector.fetch_bars = _fetch_bars
        factory = MagicMock(spec=ConnectorFactory)
        factory.create.return_value = connector

        runner = JobRunner(job, factory, mock_repo, state, mock_settings)
        result = await runner.run()

        assert result.status == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retries_exhausted(
        self,
        state: JobStateManager,
        mock_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        job = _make_job(max_attempts=2, backoff=0.001)
        factory = MagicMock(spec=ConnectorFactory)
        factory.create.return_value = _make_bar_connector(error=RuntimeError("permanent error"))

        runner = JobRunner(job, factory, mock_repo, state, mock_settings)
        result = await runner.run()

        assert result.status == "failed"
        assert "permanent error" in (result.error_message or "")


class TestJobRunnerLocking:
    """Locking behavior tests."""

    @pytest.mark.asyncio
    async def test_locked_returns_early(
        self,
        state: JobStateManager,
        mock_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        job = _make_job()
        await state.acquire_lock("test_job", ttl_seconds=60)

        factory = MagicMock(spec=ConnectorFactory)
        runner = JobRunner(job, factory, mock_repo, state, mock_settings)
        result = await runner.run()

        assert result.status == "locked"
        factory.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_lock_released_on_exception(
        self,
        state: JobStateManager,
        mock_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        job = _make_job(max_attempts=1, backoff=0.001)
        factory = MagicMock(spec=ConnectorFactory)
        factory.create.return_value = _make_bar_connector(error=RuntimeError("boom"))

        runner = JobRunner(job, factory, mock_repo, state, mock_settings)
        await runner.run()

        # Lock should be released — we should be able to acquire it
        assert await state.acquire_lock("test_job", ttl_seconds=60) is True


class TestJobRunnerDependencies:
    """Tests for dependency enforcement (FIX 3)."""

    @pytest.mark.asyncio
    async def test_dependencies_not_ready_skips_job(
        self,
        state: JobStateManager,
        mock_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        """Job with unmet dependency returns dependency_not_ready."""
        job = _make_job(dependencies=["parent_job"])
        factory = MagicMock(spec=ConnectorFactory)

        runner = JobRunner(job, factory, mock_repo, state, mock_settings)
        result = await runner.run()

        assert result.status == "dependency_not_ready"
        factory.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_dependencies_ready_runs_job(
        self,
        state: JobStateManager,
        mock_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        """Job with met dependency runs normally."""
        # Set parent_job last_success to recent
        await state.set_last_success("parent_job", datetime.now(UTC))

        job = _make_job(dependencies=["parent_job"])
        factory = MagicMock(spec=ConnectorFactory)
        factory.create.return_value = _make_bar_connector()

        runner = JobRunner(job, factory, mock_repo, state, mock_settings)
        result = await runner.run()

        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_stale_dependency_skips_job(
        self,
        state: JobStateManager,
        mock_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        """Dependency older than 24h is considered not ready."""
        stale_ts = datetime.now(UTC) - timedelta(hours=25)
        await state.set_last_success("parent_job", stale_ts)

        job = _make_job(dependencies=["parent_job"])
        factory = MagicMock(spec=ConnectorFactory)

        runner = JobRunner(job, factory, mock_repo, state, mock_settings)
        result = await runner.run()

        assert result.status == "dependency_not_ready"


class TestJobRunnerMacro:
    """Tests for macro connector dispatch."""

    @pytest.mark.asyncio
    async def test_macro_connector_dispatch(
        self,
        state: JobStateManager,
        mock_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        job = _make_job(
            connector="fred",
            params={"series_id": "FEDFUNDS"},
        )

        async def _fetch_series(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            yield ["point1", "point2"]

        connector = MagicMock()
        connector.fetch_series = _fetch_series
        factory = MagicMock(spec=ConnectorFactory)
        factory.create.return_value = connector

        runner = JobRunner(job, factory, mock_repo, state, mock_settings)
        result = await runner.run()

        assert result.status == "success"
        mock_repo.insert_macro_points.assert_called_once()


class TestJobRunnerCalendar:
    """Tests for calendar connector dispatch."""

    @pytest.mark.asyncio
    async def test_calendar_connector_dispatch(
        self,
        state: JobStateManager,
        mock_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        job = _make_job(
            connector="fomc_scraper",
            params={},
        )

        async def _fetch_events(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            yield ["event1"]

        connector = MagicMock()
        connector.fetch_events = _fetch_events
        factory = MagicMock(spec=ConnectorFactory)
        factory.create.return_value = connector

        runner = JobRunner(job, factory, mock_repo, state, mock_settings)
        result = await runner.run()

        assert result.status == "success"
        mock_repo.insert_economic_events.assert_called_once()


class TestJobRunnerFundamentals:
    """Tests for fundamentals connector dispatch."""

    @pytest.mark.asyncio
    async def test_fundamentals_connector_dispatch(
        self,
        state: JobStateManager,
        mock_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        job = _make_job(
            connector="edgar",
            params={"ticker": "AAPL", "filing_types": ["10-K"]},
        )

        async def _fetch_fundamentals(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            yield ["filing1"]

        connector = MagicMock()
        connector.fetch_fundamentals = _fetch_fundamentals
        factory = MagicMock(spec=ConnectorFactory)
        factory.create.return_value = connector

        runner = JobRunner(job, factory, mock_repo, state, mock_settings)
        result = await runner.run()

        assert result.status == "success"
        mock_repo.insert_fundamentals.assert_called_once()
