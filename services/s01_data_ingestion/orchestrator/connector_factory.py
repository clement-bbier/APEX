"""Registry-based ConnectorFactory for the Backfill Orchestrator.

Uses the Registry pattern to map connector names to lazy factory callables.
Respects OCP: adding a new connector = one ``register()`` call, no
modification to the factory itself.

Respects DIP: JobRunner depends on ConnectorFactory (abstraction),
never on concrete connector classes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

import structlog

from core.config import Settings
from services.s01_data_ingestion.connectors.base import DataConnector
from services.s01_data_ingestion.connectors.calendar_base import CalendarConnector
from services.s01_data_ingestion.connectors.fundamentals_base import (
    FundamentalsConnector,
)
from services.s01_data_ingestion.connectors.macro_base import MacroConnector

logger = structlog.get_logger(__name__)

# Union of all connector types returned by the factory.
ConnectorType = DataConnector | MacroConnector | CalendarConnector | FundamentalsConnector

# Factory callable signature: (Settings) -> ConnectorType
_FactoryFn = Callable[[Settings], ConnectorType]


class ConnectorFactory:
    """Registry-based factory for creating connector instances.

    Class-level registry maps connector names (str) to lazy factory
    callables ``(Settings) -> connector_instance``.

    Usage::

        ConnectorFactory.register("binance_historical", lambda s: ...)
        factory = ConnectorFactory()
        connector = factory.create("binance_historical", settings)
    """

    _registry: ClassVar[dict[str, _FactoryFn]] = {}

    @classmethod
    def register(cls, name: str, factory_fn: _FactoryFn) -> None:
        """Register a connector factory callable under *name*.

        Args:
            name: Unique connector identifier (e.g. ``"binance_historical"``).
            factory_fn: Callable that receives :class:`Settings` and returns
                a connector instance.

        Raises:
            ValueError: If *name* is already registered.
        """
        if name in cls._registry:
            msg = f"Connector {name!r} is already registered."
            raise ValueError(msg)
        cls._registry[name] = factory_fn
        logger.debug("connector_factory.registered", connector=name)

    @classmethod
    def registered_names(cls) -> list[str]:
        """Return sorted list of all registered connector names."""
        return sorted(cls._registry.keys())

    def create(self, name: str, settings: Settings) -> ConnectorType:
        """Instantiate a connector by its registered *name*.

        Args:
            name: Connector identifier previously passed to ``register()``.
            settings: Application settings forwarded to the factory callable.

        Returns:
            A connector instance (DataConnector, MacroConnector, etc.).

        Raises:
            ValueError: If *name* is not in the registry.
        """
        factory_fn = self._registry.get(name)
        if factory_fn is None:
            available = ", ".join(self.registered_names())
            msg = f"Unknown connector {name!r}. Available: {available}"
            raise ValueError(msg)
        return factory_fn(settings)


# ── Connector registrations (lazy imports to avoid circular dependencies) ────


def _register_binance_historical(settings: Settings) -> DataConnector:
    from services.s01_data_ingestion.connectors.binance_historical import (
        BinanceHistoricalConnector,
    )

    return BinanceHistoricalConnector()


def _register_alpaca_historical(settings: Settings) -> DataConnector:
    from services.s01_data_ingestion.connectors.alpaca_historical import (
        AlpacaHistoricalConnector,
    )

    return AlpacaHistoricalConnector(settings)


def _register_massive_historical(settings: Settings) -> DataConnector:
    from services.s01_data_ingestion.connectors.massive_historical import (
        MassiveHistoricalConnector,
    )

    return MassiveHistoricalConnector(settings)


def _register_yahoo_historical(settings: Settings) -> DataConnector:
    from services.s01_data_ingestion.connectors.yahoo_historical import (
        YahooHistoricalConnector,
    )

    return YahooHistoricalConnector()


def _register_fred(settings: Settings) -> MacroConnector:
    from services.s01_data_ingestion.connectors.fred_connector import FREDConnector

    api_key = settings.fred_api_key.get_secret_value() if settings.fred_api_key else None
    return FREDConnector(api_key=api_key)


def _register_ecb_sdw(settings: Settings) -> MacroConnector:
    from services.s01_data_ingestion.connectors.ecb_connector import ECBConnector

    return ECBConnector()


def _register_boj(settings: Settings) -> MacroConnector:
    from services.s01_data_ingestion.connectors.boj_connector import BoJConnector

    return BoJConnector()


def _register_fomc_scraper(settings: Settings) -> CalendarConnector:
    from services.s01_data_ingestion.connectors.fomc_scraper import FOMCScraper

    return FOMCScraper()


def _register_ecb_scraper(settings: Settings) -> CalendarConnector:
    from services.s01_data_ingestion.connectors.ecb_scraper import ECBScraper

    return ECBScraper()


def _register_boj_calendar_scraper(settings: Settings) -> CalendarConnector:
    from services.s01_data_ingestion.connectors.boj_calendar_scraper import (
        BoJCalendarScraper,
    )

    return BoJCalendarScraper()


def _register_fred_releases(settings: Settings) -> CalendarConnector:
    from services.s01_data_ingestion.connectors.fred_releases import (
        FREDReleasesConnector,
    )

    api_key = settings.fred_api_key.get_secret_value() if settings.fred_api_key else None
    return FREDReleasesConnector(api_key=api_key)


def _register_edgar(settings: Settings) -> FundamentalsConnector:
    from services.s01_data_ingestion.connectors.edgar_connector import EDGARConnector

    return EDGARConnector(user_agent=settings.edgar_user_agent)


def _register_simfin(settings: Settings) -> FundamentalsConnector:
    from services.s01_data_ingestion.connectors.simfin_connector import SimFinConnector

    api_key = settings.simfin_api_key.get_secret_value() if settings.simfin_api_key else None
    return SimFinConnector(api_key=api_key)


# Register all 13 connectors
ConnectorFactory.register("binance_historical", _register_binance_historical)
ConnectorFactory.register("alpaca_historical", _register_alpaca_historical)
ConnectorFactory.register("massive_historical", _register_massive_historical)
ConnectorFactory.register("yahoo_historical", _register_yahoo_historical)
ConnectorFactory.register("fred", _register_fred)
ConnectorFactory.register("ecb_sdw", _register_ecb_sdw)
ConnectorFactory.register("boj", _register_boj)
ConnectorFactory.register("fomc_scraper", _register_fomc_scraper)
ConnectorFactory.register("ecb_scraper", _register_ecb_scraper)
ConnectorFactory.register("boj_calendar_scraper", _register_boj_calendar_scraper)
ConnectorFactory.register("fred_releases", _register_fred_releases)
ConnectorFactory.register("edgar", _register_edgar)
ConnectorFactory.register("simfin", _register_simfin)
