"""Broker factory — instantiates the right Broker based on config and symbol.

Centralises broker construction so that adding a new venue (e.g. IBKR) is a
single registration rather than a multi-file change.

References:
    Gang of Four (1994) — Factory Method Pattern
"""

from __future__ import annotations

from core.config import Settings, TradingMode
from core.state import StateStore
from services.execution.broker_alpaca import AlpacaBroker
from services.execution.broker_base import Broker
from services.execution.broker_binance import BinanceBroker
from services.execution.paper_trader import PaperTrader

# Crypto symbols share a common suffix pattern.
_CRYPTO_SUFFIXES = ("USDT", "BUSD", "BTC", "ETH", "USDC")


def _is_crypto_symbol(symbol: str) -> bool:
    """Return ``True`` if the symbol appears to be a crypto pair."""
    return any(symbol.endswith(s) for s in _CRYPTO_SUFFIXES)


class BrokerFactory:
    """Creates :class:`~.broker_base.Broker` instances based on execution mode + asset class.

    Usage::

        factory = BrokerFactory(settings, state)
        broker = factory.for_symbol("BTCUSDT")
        await broker.connect()
        executed = await broker.place_order(approved_order)
    """

    def __init__(self, settings: Settings, state: StateStore) -> None:
        self._settings = settings
        self._state = state

        # Pre-built singletons for each venue (created lazily or eagerly).
        self._paper: PaperTrader | None = None
        self._alpaca: AlpacaBroker | None = None
        self._binance: BinanceBroker | None = None

    def for_symbol(self, symbol: str) -> Broker:
        """Return the appropriate broker for a given symbol.

        Routing logic:

        - ``TradingMode.PAPER`` → :class:`PaperTrader`
        - ``TradingMode.LIVE`` + crypto suffix → :class:`BinanceBroker`
        - ``TradingMode.LIVE`` + equity → :class:`AlpacaBroker`

        Args:
            symbol: Uppercase trading symbol.

        Returns:
            A :class:`Broker` instance ready for use.

        Raises:
            RuntimeError: If a required live broker is not configured.
        """
        if self._settings.trading_mode == TradingMode.PAPER:
            return self._get_paper()

        if _is_crypto_symbol(symbol):
            return self._get_binance()

        return self._get_alpaca()

    # ── Lazy singleton getters ───────────────────────────────────────────────

    def _get_paper(self) -> PaperTrader:
        if self._paper is None:
            self._paper = PaperTrader(state=self._state)
        return self._paper

    def _get_alpaca(self) -> AlpacaBroker:
        if self._alpaca is None:
            self._alpaca = AlpacaBroker(
                api_key=self._settings.alpaca_api_key.get_secret_value(),
                secret_key=self._settings.alpaca_api_secret.get_secret_value(),
                base_url=self._settings.alpaca_base_url,
                paper=False,
            )
        return self._alpaca

    def _get_binance(self) -> BinanceBroker:
        if self._binance is None:
            self._binance = BinanceBroker(
                api_key=self._settings.binance_api_key.get_secret_value(),
                secret_key=self._settings.binance_secret_key.get_secret_value(),
                base_url=self._settings.binance_rest_url,
                testnet=self._settings.binance_testnet,
            )
        return self._binance

    async def connect_all(self) -> None:
        """Connect all pre-built broker instances."""
        if self._alpaca is not None:
            await self._alpaca.connect()
        if self._binance is not None:
            await self._binance.connect()
        # PaperTrader.connect() is a no-op but call for consistency.
        if self._paper is not None:
            await self._paper.connect()

    async def disconnect_all(self) -> None:
        """Disconnect all pre-built broker instances."""
        if self._alpaca is not None:
            await self._alpaca.disconnect()
        if self._binance is not None:
            await self._binance.disconnect()
        if self._paper is not None:
            await self._paper.disconnect()
