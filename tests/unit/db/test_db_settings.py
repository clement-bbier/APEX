"""Pure unit tests for ``core.db.DBSettings`` (no DB needed).

These tests exercise the environment-variable parsing and the DSN
builder. They do not touch asyncpg or TimescaleDB, so they always run
on every environment — no Docker, no ``testcontainers``.
"""

from __future__ import annotations

import pytest

from core.db import DBSettings


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """``DBSettings.from_env`` falls back to documented dev defaults."""
    for key in (
        "DB_HOST",
        "DB_PORT",
        "DB_USER",
        "DB_PASSWORD",
        "DB_NAME",
        "DB_POOL_MIN",
        "DB_POOL_MAX",
        "DB_COMMAND_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = DBSettings.from_env()
    assert settings.host == "localhost"
    assert settings.port == 5432
    assert settings.user == "apex"
    assert settings.database == "apex"
    assert settings.pool_min == 2
    assert settings.pool_max == 10
    assert settings.command_timeout == 30.0


def test_from_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variables override the defaults end-to-end."""
    monkeypatch.setenv("DB_HOST", "db.internal")
    monkeypatch.setenv("DB_PORT", "6543")
    monkeypatch.setenv("DB_USER", "reader")
    monkeypatch.setenv("DB_PASSWORD", "hunter2")
    monkeypatch.setenv("DB_NAME", "apex_prod")
    monkeypatch.setenv("DB_POOL_MIN", "4")
    monkeypatch.setenv("DB_POOL_MAX", "16")
    monkeypatch.setenv("DB_COMMAND_TIMEOUT", "5")
    settings = DBSettings.from_env()
    assert settings.host == "db.internal"
    assert settings.port == 6543
    assert settings.user == "reader"
    assert settings.database == "apex_prod"
    assert settings.pool_min == 4
    assert settings.pool_max == 16
    assert settings.command_timeout == 5.0


def test_dsn_is_valid_postgres_uri() -> None:
    """DSN round-trips to the expected ``postgresql://`` URI shape."""
    settings = DBSettings(
        host="localhost",
        port=5432,
        user="apex",
        password="apex_secret",
        database="apex",
    )
    assert settings.dsn == "postgresql://apex:apex_secret@localhost:5432/apex"
