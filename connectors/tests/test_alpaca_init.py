"""Alpaca connector stub-contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import SecretStr

from connectors.alpaca import AlpacaConfig, AlpacaConnector
from connectors.types import OrderRequest


def _connector() -> AlpacaConnector:
    return AlpacaConnector(
        AlpacaConfig(
            api_key=SecretStr("dummy_key"),
            api_secret=SecretStr("dummy_secret"),
        )
    )


def test_config_secrets_are_secretstr() -> None:
    cfg = AlpacaConfig(
        api_key=SecretStr("live_key_zzz_aaa"),
        api_secret=SecretStr("live_secret_zzz_bbb"),
    )
    # SecretStr prevents accidental logging of keys.
    assert "live_key_zzz_aaa" not in repr(cfg)
    assert "live_secret_zzz_bbb" not in repr(cfg)


async def test_submit_order_not_implemented() -> None:
    conn = _connector()
    order = OrderRequest(
        client_order_id="abc",
        symbol="AAPL",
        side="buy",
        quantity=Decimal("10"),
        order_type="market",
    )
    with pytest.raises(NotImplementedError, match="Phase B Gate 2A"):
        await conn.submit_order(order)


async def test_cancel_order_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="Phase B Gate 2A"):
        await _connector().cancel_order("id")


async def test_get_positions_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="Phase B Gate 2A"):
        await _connector().get_positions()


async def test_get_account_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="Phase B Gate 2A"):
        await _connector().get_account()


async def test_get_historical_bars_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="Phase B Gate 2A"):
        await _connector().get_historical_bars(
            "AAPL",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 2, 1, tzinfo=UTC),
            "1d",
        )
