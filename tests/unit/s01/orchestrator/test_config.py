"""Tests for orchestrator configuration loading and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from services.s01_data_ingestion.orchestrator.config import (
    JobConfig,
    OrchestratorConfig,
    RetryConfig,
    load_config_from_yaml,
)


@pytest.fixture
def valid_yaml(tmp_path: Path) -> Path:
    """Write a minimal valid jobs.yaml and return its path."""
    data: dict[str, Any] = {
        "jobs": [
            {
                "name": "job_a",
                "connector": "binance_historical",
                "schedule": "0 */4 * * *",
                "params": {"symbol": "BTCUSDT", "bar_size": "M1"},
            },
            {
                "name": "job_b",
                "connector": "fred",
                "schedule": "0 6 * * *",
                "params": {"series_id": "FEDFUNDS"},
                "dependencies": ["job_a"],
            },
        ]
    }
    path = tmp_path / "jobs.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


class TestLoadConfigFromYaml:
    """Tests for load_config_from_yaml."""

    def test_load_valid_yaml(self, valid_yaml: Path) -> None:
        config = load_config_from_yaml(valid_yaml)
        assert len(config.jobs) == 2
        assert config.jobs[0].name == "job_a"
        assert config.jobs[1].name == "job_b"

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_config_from_yaml(tmp_path / "nonexistent.yaml")

    def test_empty_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        config = load_config_from_yaml(path)
        assert config.jobs == []

    def test_non_dict_yaml_raises_value_error(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="top-level must be a mapping"):
            load_config_from_yaml(path)


class TestOrchestratorConfig:
    """Tests for OrchestratorConfig validation."""

    def test_duplicate_names_raise(self) -> None:
        with pytest.raises(ValueError, match="Duplicate job name"):
            OrchestratorConfig(
                jobs=[
                    JobConfig(name="dup", connector="fred", schedule="0 * * * *"),
                    JobConfig(name="dup", connector="boj", schedule="0 * * * *"),
                ]
            )

    def test_missing_dependency_raises(self) -> None:
        with pytest.raises(ValueError, match="not defined"):
            OrchestratorConfig(
                jobs=[
                    JobConfig(
                        name="child",
                        connector="fred",
                        schedule="0 * * * *",
                        dependencies=["nonexistent"],
                    ),
                ]
            )


class TestJobConfig:
    """Tests for JobConfig defaults and validation."""

    def test_defaults(self) -> None:
        job = JobConfig(name="test", connector="fred", schedule="0 * * * *")
        assert job.enabled is True
        assert job.timeout_seconds == 3600
        assert job.on_failure == "skip"
        assert job.params == {}
        assert job.dependencies == []

    def test_retry_defaults(self) -> None:
        retry = RetryConfig()
        assert retry.max_attempts == 3
        assert retry.backoff_seconds == 30.0
