"""Tests for ConnectorFactory registry pattern."""

from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest

from services.s01_data_ingestion.orchestrator.connector_factory import ConnectorFactory


class _IsolatedFactory:
    """A factory with an isolated registry for testing without side effects."""

    _registry: ClassVar[dict[str, Any]] = {}

    @classmethod
    def register(cls, name: str, factory_fn: Any) -> None:
        if name in cls._registry:
            msg = f"Connector {name!r} is already registered."
            raise ValueError(msg)
        cls._registry[name] = factory_fn

    @classmethod
    def registered_names(cls) -> list[str]:
        return sorted(cls._registry.keys())

    def create(self, name: str, settings: Any) -> Any:
        factory_fn = self._registry.get(name)
        if factory_fn is None:
            available = ", ".join(self.registered_names())
            msg = f"Unknown connector {name!r}. Available: {available}"
            raise ValueError(msg)
        return factory_fn(settings)

    @classmethod
    def reset(cls) -> None:
        cls._registry = {}


class TestConnectorFactoryRegistry:
    """Tests for the registry pattern."""

    def setup_method(self) -> None:
        _IsolatedFactory.reset()

    def test_register_and_create(self) -> None:
        sentinel = object()
        _IsolatedFactory.register("test_conn", lambda s: sentinel)
        factory = _IsolatedFactory()
        result = factory.create("test_conn", MagicMock())
        assert result is sentinel

    def test_create_unknown_raises(self) -> None:
        _IsolatedFactory.reset()
        factory = _IsolatedFactory()
        with pytest.raises(ValueError, match="Unknown connector"):
            factory.create("nonexistent", MagicMock())

    def test_duplicate_register_raises(self) -> None:
        _IsolatedFactory.register("dup", lambda s: None)
        with pytest.raises(ValueError, match="already registered"):
            _IsolatedFactory.register("dup", lambda s: None)

    def test_registered_names_sorted(self) -> None:
        _IsolatedFactory.register("zebra", lambda s: None)
        _IsolatedFactory.register("alpha", lambda s: None)
        assert _IsolatedFactory.registered_names() == ["alpha", "zebra"]

    def test_factory_receives_settings(self) -> None:
        captured: list[Any] = []
        _IsolatedFactory.register("capture", lambda s: captured.append(s))
        settings = MagicMock()
        _IsolatedFactory().create("capture", settings)
        assert captured[0] is settings


class TestConnectorFactoryGlobalRegistry:
    """Tests that the global ConnectorFactory has all 13 connectors registered."""

    def test_all_13_connectors_registered(self) -> None:
        names = ConnectorFactory.registered_names()
        assert len(names) == 13

    def test_expected_connectors_present(self) -> None:
        names = set(ConnectorFactory.registered_names())
        expected = {
            "binance_historical",
            "alpaca_historical",
            "massive_historical",
            "yahoo_historical",
            "fred",
            "ecb_sdw",
            "boj",
            "fomc_scraper",
            "ecb_scraper",
            "boj_calendar_scraper",
            "fred_releases",
            "edgar",
            "simfin",
        }
        assert names == expected
