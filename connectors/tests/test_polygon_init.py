"""Polygon connector stub-contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from connectors.polygon import PolygonConfig, PolygonConnector


def _connector() -> PolygonConnector:
    return PolygonConnector(PolygonConfig(api_key=SecretStr("dummy")))


def test_config_key_is_secretstr() -> None:
    cfg = PolygonConfig(api_key=SecretStr("secret_key_abc"))
    assert "secret_key_abc" not in repr(cfg)


async def test_get_historical_bars_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="Phase B Gate 2A"):
        await _connector().get_historical_bars(
            "AAPL",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 2, 1, tzinfo=UTC),
            "1d",
        )


def test_polygon_has_no_execution_methods() -> None:
    # Polygon implements MarketDataProvider only -- no `submit_order` etc.
    conn = _connector()
    assert not hasattr(conn, "submit_order")
    assert not hasattr(conn, "cancel_order")
    assert not hasattr(conn, "get_positions")
    assert not hasattr(conn, "get_account")
