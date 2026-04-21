"""IBKR connector stub-contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from connectors.ibkr import IBKRConfig, IBKRConnector
from connectors.types import OrderRequest


def _connector() -> IBKRConnector:
    return IBKRConnector(IBKRConfig())


def test_default_config_is_paper_safe() -> None:
    cfg = IBKRConfig()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 7497  # paper TWS
    assert cfg.read_only is True  # safe default


async def test_submit_order_not_implemented() -> None:
    order = OrderRequest(
        client_order_id="abc",
        symbol="AAPL",
        side="buy",
        quantity=Decimal("10"),
        order_type="market",
    )
    with pytest.raises(NotImplementedError, match="Phase B Gate 3"):
        await _connector().submit_order(order)


async def test_cancel_order_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="Phase B Gate 3"):
        await _connector().cancel_order("id")


async def test_get_positions_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="Phase B Gate 3"):
        await _connector().get_positions()


async def test_get_account_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="Phase B Gate 3"):
        await _connector().get_account()


async def test_get_historical_bars_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="Phase B Gate 3"):
        await _connector().get_historical_bars(
            "AAPL",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 2, 1, tzinfo=UTC),
            "1d",
        )
