"""End-to-end integration test for the Backfill Orchestrator.

Requires a running Redis instance and TimescaleDB.
Skipped unless ``APEX_NETWORK_TESTS=1`` is set.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from services.s01_data_ingestion.orchestrator.config import load_config_from_yaml

_SKIP_REASON = "Set APEX_NETWORK_TESTS=1 to run integration tests"


@pytest.fixture
def minimal_config(tmp_path: Path) -> Path:
    """Create a minimal config with a single FRED job."""
    data: dict[str, Any] = {
        "jobs": [
            {
                "name": "e2e_fred_test",
                "connector": "fred",
                "schedule": "0 6 * * *",
                "params": {"series_id": "FEDFUNDS"},
                "retry": {"max_attempts": 1, "backoff_seconds": 1},
                "timeout_seconds": 30,
            }
        ]
    }
    path = tmp_path / "e2e_jobs.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.mark.skipif(
    os.environ.get("APEX_NETWORK_TESTS") != "1",
    reason=_SKIP_REASON,
)
class TestOrchestratorE2E:
    """End-to-end orchestrator tests with real Redis + DB."""

    @pytest.mark.asyncio
    async def test_load_config_and_validate(self, minimal_config: Path) -> None:
        config = load_config_from_yaml(minimal_config)
        assert len(config.jobs) == 1
        assert config.jobs[0].name == "e2e_fred_test"

    @pytest.mark.asyncio
    async def test_cli_list_subcommand(self, minimal_config: Path) -> None:
        from services.s01_data_ingestion.orchestrator.cli import ListCommand

        cmd = ListCommand(minimal_config)
        await cmd.execute()  # should not raise
