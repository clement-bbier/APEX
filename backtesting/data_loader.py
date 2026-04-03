"""Historical data loader for APEX backtesting.

Downloads and caches OHLCV and tick data from:
- Binance REST API (crypto: BTC/USDT, ETH/USDT)
- Alpaca historical API via ``alpaca-py`` (equities: top S&P500)

Saves to ``data/historical/*.parquet``.  Resamples from 1m to any timeframe.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from core.logger import get_logger
from core.models.tick import Market, NormalizedTick, Session, TradeSide

logger = get_logger("backtesting.data_loader")

_DATA_DIR = Path("data/historical")


def _ensure_data_dir() -> None:
    """Create the data directory if it does not exist."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def resample_ticks_to_ohlcv(ticks: list[NormalizedTick], timeframe: str = "1min") -> pd.DataFrame:
    """Resample a tick list to OHLCV bars at the given frequency.

    Args:
        ticks:     List of :class:`NormalizedTick` sorted by timestamp.
        timeframe: Pandas offset string, e.g. ``"1min"``, ``"5min"``, ``"1h"``.

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume.
    """
    if not ticks:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    data = {
        "timestamp": [pd.Timestamp(t.timestamp_ms, unit="ms", tz="UTC") for t in ticks],
        "price": [float(t.price) for t in ticks],
        "volume": [float(t.volume) for t in ticks],
    }
    df = pd.DataFrame(data).set_index("timestamp")
    ohlcv = df["price"].resample(timeframe).ohlc()
    ohlcv["volume"] = df["volume"].resample(timeframe).sum()
    ohlcv = ohlcv.dropna()
    ohlcv = ohlcv.reset_index()
    ohlcv.columns = ["timestamp", "open", "high", "low", "close", "volume"]
    return ohlcv


def load_parquet(path: str | Path) -> list[NormalizedTick]:
    """Load a Parquet file and return a list of NormalizedTick objects.

    Args:
        path: Path to a ``.parquet`` file saved by :func:`save_parquet`.

    Returns:
        List of :class:`NormalizedTick` sorted by timestamp ascending.
    """
    df = pd.read_parquet(str(path))
    df = df.sort_values("timestamp_ms")
    ticks: list[NormalizedTick] = []
    for row in df.itertuples(index=False):
        try:
            tick = NormalizedTick(
                symbol=row.symbol,
                market=Market(row.market),
                timestamp_ms=int(row.timestamp_ms),
                price=Decimal(str(row.price)),
                volume=Decimal(str(row.volume)),
                side=TradeSide(str(getattr(row, "side", "unknown"))),
                bid=Decimal(str(getattr(row, "bid", row.price))),
                ask=Decimal(str(getattr(row, "ask", row.price))),
                spread_bps=Decimal(str(getattr(row, "spread_bps", "1.0"))),
                session=Session(getattr(row, "session", "after_hours")),
            )
            ticks.append(tick)
        except Exception as exc:
            logger.warning("Skipping malformed row", error=str(exc))
    return ticks


def save_parquet(ticks: list[NormalizedTick], path: str | Path) -> None:
    """Serialise tick data to Parquet format.

    Args:
        ticks: Tick list to serialise.
        path:  Output file path.
    """
    rows = [
        {
            "symbol": t.symbol,
            "market": t.market.value,
            "timestamp_ms": t.timestamp_ms,
            "price": float(t.price),
            "volume": float(t.volume),
            "side": t.side,
            "bid": float(t.bid) if t.bid is not None else 0.0,
            "ask": float(t.ask) if t.ask is not None else 0.0,
            "spread_bps": t.spread_bps,
            "session": t.session.value,
        }
        for t in ticks
    ]
    df = pd.DataFrame(rows)
    pq.write_table(pa.Table.from_pandas(df), str(path))
    logger.info("Saved parquet", path=str(path), rows=len(rows))


class BinanceHistoricalLoader:
    """Download historical Binance OHLCV data and convert to NormalizedTick list.

    Args:
        symbol: Binance trading pair, e.g. ``"BTCUSDT"``.
    """

    def __init__(self, symbol: str = "BTCUSDT") -> None:
        self._symbol = symbol

    async def load_klines(
        self,
        start_dt: datetime,
        end_dt: datetime,
        interval: str = "1m",
    ) -> list[NormalizedTick]:
        """Fetch 1-minute klines and unpack as NormalizedTick objects.

        Args:
            start_dt: Start datetime (UTC).
            end_dt:   End datetime (UTC).
            interval: Binance kline interval string (default ``"1m"``).

        Returns:
            List of :class:`NormalizedTick` in chronological order.
        """
        import aiohttp

        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        ticks: list[NormalizedTick] = []

        url = "https://api.binance.com/api/v3/klines"
        async with aiohttp.ClientSession() as session:
            cursor = start_ms
            while cursor < end_ms:
                params: dict[str, str] = {
                    "symbol": self._symbol,
                    "interval": interval,
                    "startTime": str(cursor),
                    "endTime": str(end_ms),
                    "limit": "1000",
                }
                async with session.get(url, params=params) as resp:
                    resp.raise_for_status()
                    klines: list[Any] = await resp.json()

                if not klines:
                    break

                for kline in klines:
                    ts_ms = int(kline[0])
                    close_price = Decimal(str(kline[4]))
                    volume = Decimal(str(kline[5]))
                    tick = NormalizedTick(
                        symbol=self._symbol.replace("USDT", "/USDT"),
                        market=Market.CRYPTO,
                        timestamp_ms=ts_ms,
                        price=close_price,
                        volume=volume,
                        side=TradeSide.UNKNOWN,
                        bid=close_price,
                        ask=close_price,
                        spread_bps=Decimal("1.0"),
                        session=Session.AFTER_HOURS,
                    )
                    ticks.append(tick)

                cursor = int(klines[-1][0]) + 1
                logger.debug("Loaded klines", symbol=self._symbol, count=len(ticks))

        return ticks


class AlpacaHistoricalLoader:
    """Download historical Alpaca equity OHLCV data using alpaca-py.

    Args:
        api_key:    Alpaca API key.
        secret_key: Alpaca secret key.
    """

    def __init__(self, api_key: str, secret_key: str) -> None:
        self._api_key = api_key
        self._secret_key = secret_key

    def load_bars(
        self,
        symbol: str,
        start_dt: datetime,
        end_dt: datetime,
        timeframe: str = "1Min",
    ) -> list[NormalizedTick]:
        """Fetch equity bars from Alpaca and return as NormalizedTick list.

        Args:
            symbol:    Equity ticker, e.g. ``"AAPL"``.
            start_dt:  Start datetime (UTC).
            end_dt:    End datetime (UTC).
            timeframe: Alpaca TimeFrame string (``"1Min"``, ``"5Min"``, etc.).

        Returns:
            List of :class:`NormalizedTick`.
        """
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        client = StockHistoricalDataClient(api_key=self._api_key, secret_key=self._secret_key)
        tf_map = {
            "1Min": TimeFrame.Minute,
            "5Min": TimeFrame(5, TimeFrame.Minute.unit)
            if hasattr(TimeFrame, "Minute")
            else TimeFrame.Minute,
        }
        tf = tf_map.get(timeframe, TimeFrame.Minute)

        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start_dt,
            end=end_dt,
        )
        bars = client.get_stock_bars(req)
        ticks: list[NormalizedTick] = []

        for bar in bars[symbol]:
            ts = bar.timestamp
            ts_ms = int(ts.timestamp() * 1000)
            close = Decimal(str(bar.close))
            vol = Decimal(str(bar.volume))
            tick = NormalizedTick(
                symbol=symbol,
                market=Market.EQUITY,
                timestamp_ms=ts_ms,
                price=close,
                volume=vol,
                side=TradeSide.UNKNOWN,
                bid=close,
                ask=close,
                spread_bps=Decimal("2.0"),
                session=Session.US_NORMAL,
            )
            ticks.append(tick)

        return ticks
