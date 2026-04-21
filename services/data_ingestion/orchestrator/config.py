"""Configuration models for the Backfill Orchestrator.

Loads job definitions from a YAML file and validates them using Pydantic v2.
Each job maps to a registered connector with cron scheduling, retry policy,
and optional dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = structlog.get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_MAX_ATTEMPTS: int = 3
_DEFAULT_BACKOFF_SECONDS: float = 30.0
_DEFAULT_TIMEOUT_SECONDS: int = 3600
_ON_FAILURE_SKIP: str = "skip"
_ON_FAILURE_RAISE: str = "raise"


# ── Models ───────────────────────────────────────────────────────────────────


class RetryConfig(BaseModel):
    """Retry policy for a backfill job."""

    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(
        default=_DEFAULT_MAX_ATTEMPTS,
        ge=1,
        le=20,
        description="Maximum number of attempts before giving up.",
    )
    backoff_seconds: float = Field(
        default=_DEFAULT_BACKOFF_SECONDS,
        gt=0.0,
        description="Base backoff delay between retries (exponential).",
    )


class JobConfig(BaseModel):
    """Single backfill job definition."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Unique job identifier.")
    connector: str = Field(description="Registered connector name in ConnectorFactory.")
    enabled: bool = Field(default=True, description="Whether this job is active.")
    schedule: str = Field(description="Cron expression (5-field) for scheduling.")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Connector-specific parameters (symbol, series_id, bar_size, …).",
    )
    retry: RetryConfig = Field(
        default_factory=RetryConfig,
        description="Retry policy.",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="Job names that must succeed before this job runs.",
    )
    timeout_seconds: int = Field(
        default=_DEFAULT_TIMEOUT_SECONDS,
        gt=0,
        description="Maximum wall-clock seconds per run.",
    )
    on_failure: str = Field(
        default=_ON_FAILURE_SKIP,
        description="Action on failure: 'skip' or 'raise'.",
    )


class OrchestratorConfig(BaseModel):
    """Top-level orchestrator configuration loaded from YAML."""

    model_config = ConfigDict(frozen=True)

    jobs: list[JobConfig] = Field(
        default_factory=list,
        description="List of backfill job definitions.",
    )

    @model_validator(mode="after")
    def _validate_unique_names(self) -> OrchestratorConfig:
        """Reject duplicate job names."""
        seen: set[str] = set()
        for job in self.jobs:
            if job.name in seen:
                msg = f"Duplicate job name: {job.name!r}"
                raise ValueError(msg)
            seen.add(job.name)
        return self

    @model_validator(mode="after")
    def _validate_dependencies_exist(self) -> OrchestratorConfig:
        """Ensure all dependency references point to existing job names."""
        known: set[str] = {j.name for j in self.jobs}
        for job in self.jobs:
            for dep in job.dependencies:
                if dep not in known:
                    msg = f"Job {job.name!r} depends on {dep!r}, which is not defined."
                    raise ValueError(msg)
        return self


def load_config_from_yaml(path: Path) -> OrchestratorConfig:
    """Parse a YAML file into an OrchestratorConfig.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        Validated OrchestratorConfig instance.

    Raises:
        FileNotFoundError: If the YAML file does not exist.
        ValueError: If the YAML content is invalid.
    """
    if not path.exists():
        msg = f"Configuration file not found: {path}"
        raise FileNotFoundError(msg)

    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        msg = (
            f"Invalid YAML content in {path}: "
            f"top-level must be a mapping, got {type(data).__name__}"
        )
        raise ValueError(msg)

    logger.info("orchestrator.config_loaded", path=str(path), job_count=len(data.get("jobs", [])))
    return OrchestratorConfig.model_validate(data)
