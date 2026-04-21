"""Tests for Broker ABC, concrete broker conformance, and BrokerFactory routing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.execution.broker_alpaca import AlpacaBroker
from services.execution.broker_base import Broker, BrokerConnectionError, BrokerRejectedError
from services.execution.broker_binance import BinanceBroker
from services.execution.paper_trader import PaperTrader

# ── ABC contract tests ───────────────────────────────────────────────────────


class TestBrokerABC:
    def test_broker_abc_cannot_be_instantiated(self) -> None:
        with pytest.raises(TypeError):
            Broker()  # type: ignore[abstract]

    def test_all_concrete_brokers_implement_abc(self) -> None:
        for broker_cls in [AlpacaBroker, BinanceBroker, PaperTrader]:
            assert issubclass(broker_cls, Broker)

    def test_broker_connection_error_is_runtime_error(self) -> None:
        assert issubclass(BrokerConnectionError, RuntimeError)

    def test_broker_rejected_error_is_runtime_error(self) -> None:
        assert issubclass(BrokerRejectedError, RuntimeError)


# ── is_connected property tests ──────────────────────────────────────────────


class TestIsConnected:
    def test_alpaca_not_connected_initially(self) -> None:
        broker = AlpacaBroker(api_key="k", secret_key="s")
        assert broker.is_connected is False

    def test_binance_not_connected_initially(self) -> None:
        broker = BinanceBroker(api_key="k", secret_key="s", base_url="http://localhost")
        assert broker.is_connected is False

    def test_paper_always_connected(self) -> None:
        trader = PaperTrader()
        assert trader.is_connected is True


# ── PaperTrader Broker ABC compliance ────────────────────────────────────────


class TestPaperTraderBrokerInterface:
    @pytest.mark.asyncio
    async def test_connect_is_noop(self) -> None:
        trader = PaperTrader()
        await trader.connect()  # should not raise

    @pytest.mark.asyncio
    async def test_disconnect_is_noop(self) -> None:
        trader = PaperTrader()
        await trader.disconnect()  # should not raise

    @pytest.mark.asyncio
    async def test_cancel_order_returns_true(self) -> None:
        trader = PaperTrader()
        assert await trader.cancel_order("any-id") is True


# ── BrokerFactory tests ──────────────────────────────────────────────────────


class TestBrokerFactory:
    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        settings = MagicMock()
        settings.trading_mode = MagicMock()
        settings.alpaca_api_key.get_secret_value.return_value = "ak"
        settings.alpaca_api_secret.get_secret_value.return_value = "as"
        settings.alpaca_base_url = "http://localhost"
        settings.binance_api_key.get_secret_value.return_value = "bk"
        settings.binance_secret_key.get_secret_value.return_value = "bs"
        settings.binance_rest_url = "http://localhost"
        return settings

    def test_paper_mode_returns_paper_trader(self, mock_settings: MagicMock) -> None:
        from core.config import TradingMode
        from core.state import StateStore

        mock_settings.trading_mode = TradingMode.PAPER
        state = MagicMock(spec=StateStore)

        from services.execution.broker_factory import BrokerFactory

        factory = BrokerFactory(mock_settings, state)
        broker = factory.for_symbol("BTCUSDT")
        assert isinstance(broker, PaperTrader)

    def test_paper_mode_for_equity_returns_paper_trader(self, mock_settings: MagicMock) -> None:
        from core.config import TradingMode
        from core.state import StateStore

        mock_settings.trading_mode = TradingMode.PAPER
        state = MagicMock(spec=StateStore)

        from services.execution.broker_factory import BrokerFactory

        factory = BrokerFactory(mock_settings, state)
        broker = factory.for_symbol("AAPL")
        assert isinstance(broker, PaperTrader)

    def test_live_crypto_returns_binance(self, mock_settings: MagicMock) -> None:
        from core.config import TradingMode
        from core.state import StateStore

        mock_settings.trading_mode = TradingMode.LIVE
        state = MagicMock(spec=StateStore)

        from services.execution.broker_factory import BrokerFactory

        factory = BrokerFactory(mock_settings, state)
        broker = factory.for_symbol("BTCUSDT")
        assert isinstance(broker, BinanceBroker)

    def test_live_equity_returns_alpaca(self, mock_settings: MagicMock) -> None:
        from core.config import TradingMode
        from core.state import StateStore

        mock_settings.trading_mode = TradingMode.LIVE
        state = MagicMock(spec=StateStore)

        from services.execution.broker_factory import BrokerFactory

        factory = BrokerFactory(mock_settings, state)
        broker = factory.for_symbol("AAPL")
        assert isinstance(broker, AlpacaBroker)

    def test_factory_returns_same_instance_on_repeated_calls(
        self, mock_settings: MagicMock
    ) -> None:
        from core.config import TradingMode
        from core.state import StateStore

        mock_settings.trading_mode = TradingMode.LIVE
        state = MagicMock(spec=StateStore)

        from services.execution.broker_factory import BrokerFactory

        factory = BrokerFactory(mock_settings, state)
        b1 = factory.for_symbol("AAPL")
        b2 = factory.for_symbol("MSFT")
        assert b1 is b2  # same AlpacaBroker singleton
