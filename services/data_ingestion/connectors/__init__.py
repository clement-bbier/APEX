"""Data connectors for APEX S01 Data Ingestion.

Provides the abstract DataConnector interface and concrete implementations
for historical and live data ingestion from various exchanges.
"""

from __future__ import annotations

from .alpaca_historical import AlpacaFetchError, AlpacaHistoricalConnector
from .base import DataConnector
from .binance_historical import BinanceFetchError, BinanceHistoricalConnector
from .binance_live import BinanceLiveConnector
from .massive_historical import MassiveFetchError, MassiveHistoricalConnector

__all__ = [
    "AlpacaFetchError",
    "AlpacaHistoricalConnector",
    "BinanceFetchError",
    "BinanceHistoricalConnector",
    "BinanceLiveConnector",
    "DataConnector",
    "MassiveFetchError",
    "MassiveHistoricalConnector",
]
