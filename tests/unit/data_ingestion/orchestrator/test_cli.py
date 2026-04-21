"""Tests for the orchestrator CLI (Command pattern)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest
import yaml

from services.data_ingestion.orchestrator.cli import (
    GapsCommand,
    ListCommand,
    ResetCommand,
    RunCommand,
    StatusCommand,
    build_parser,
    resolve_command,
)


@pytest.fixture
def valid_yaml_path(tmp_path: Path) -> Path:
    """Write a minimal valid jobs.yaml and return its path."""
    data: dict[str, Any] = {
        "jobs": [
            {
                "name": "test_job",
                "connector": "fred",
                "schedule": "0 6 * * *",
                "params": {"series_id": "FEDFUNDS"},
            },
        ]
    }
    path = tmp_path / "jobs.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


class TestBuildParser:
    """Tests for CLI parser construction."""

    def test_list_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["list"])
        assert args.command == "list"

    def test_run_subcommand_requires_job(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["run"])

    def test_run_subcommand_with_job(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "--job", "my_job"])
        assert args.command == "run"
        assert args.job == "my_job"

    def test_status_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["status", "--job", "test"])
        assert args.command == "status"

    def test_reset_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["reset", "--job", "test"])
        assert args.command == "reset"

    def test_gaps_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["gaps"])
        assert args.command == "gaps"


class TestResolveCommand:
    """Tests for mapping args to Command objects."""

    def test_list_resolves(self) -> None:
        args = argparse.Namespace(command="list", config=Path("jobs.yaml"))
        cmd = resolve_command(args)
        assert isinstance(cmd, ListCommand)

    def test_run_resolves(self) -> None:
        args = argparse.Namespace(command="run", config=Path("jobs.yaml"), job="x")
        cmd = resolve_command(args)
        assert isinstance(cmd, RunCommand)

    def test_status_resolves(self) -> None:
        args = argparse.Namespace(command="status", config=Path("jobs.yaml"), job="x")
        cmd = resolve_command(args)
        assert isinstance(cmd, StatusCommand)

    def test_reset_resolves(self) -> None:
        args = argparse.Namespace(command="reset", config=Path("jobs.yaml"), job="x")
        cmd = resolve_command(args)
        assert isinstance(cmd, ResetCommand)

    def test_gaps_resolves(self) -> None:
        args = argparse.Namespace(command="gaps", config=Path("jobs.yaml"))
        cmd = resolve_command(args)
        assert isinstance(cmd, GapsCommand)

    def test_unknown_raises(self) -> None:
        args = argparse.Namespace(command="bogus", config=Path("jobs.yaml"))
        with pytest.raises(ValueError, match="Unknown command"):
            resolve_command(args)


class TestListCommand:
    """Tests for the list command execution."""

    @pytest.mark.asyncio
    async def test_list_prints_jobs(
        self, valid_yaml_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd = ListCommand(valid_yaml_path)
        await cmd.execute()
        output = capsys.readouterr().out
        assert "test_job" in output
        assert "fred" in output
        assert "Total: 1 jobs" in output
