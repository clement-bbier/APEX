"""Tick normalizers for the APEX Trading System Data Ingestion Service.

Provides :class:`SessionTagger` for UTC-timestamp-to-session mapping,
:class:`BinanceNormalizer` for Binance trade-stream payloads, and
:class:`AlpacaNormalizer` for Alpaca trade-stream payloads.
All normalizers produce :class:`~core.models.tick.NormalizedTick` instances.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from core.logger import get_logger
from core.models.tick import Market, NormalizedTick, RawTick, Session, TradeSide

logger = get_logger("s01_data_ingestion.normalizer")


class SessionTagger:
    """Tags a UTC :class:`datetime` with the appropriate :class:`Session` value.

    Session windows (all times UTC):

    * **Weekend**   – Saturday or Sunday (weekday >= 5)
    * **US Prime**  – 14:30–15:30 (open prime) *or* 20:00–21:00 (close prime)
    * **US Normal** – 14:30–21:00 outside the prime windows
    * **London**    – 08:00–10:00
    * **Asian**     – 00:00–02:00
    * **After Hours / Unknown** – everything else
    """

    # Boundaries expressed as (hour, minute) tuples (UTC, inclusive start).
    _US_OPEN_HM = (14, 30)
    _US_CLOSE_HM = (21, 0)
    _PRIME_OPEN_START_HM = (14, 30)
    _PRIME_OPEN_END_HM = (15, 30)
    _PRIME_CLOSE_START_HM = (20, 0)
    _PRIME_CLOSE_END_HM = (21, 0)
    _LONDON_START_HM = (8, 0)
    _LONDON_END_HM = (10, 0)
    _ASIAN_START_HM = (0, 0)
    _ASIAN_END_HM = (2, 0)

    @staticmethod
    def _to_minutes(hour: int, minute: int) -> int:
        """Convert (hour, minute) to total minutes since midnight."""
        return hour * 60 + minute

    def tag(self, ts: datetime) -> Session:
        """Return the :class:`Session` for *ts* (must be UTC-aware or naive UTC).

        Args:
            ts: UTC timestamp to classify.

        Returns:
            The matching :class:`Session` value.
        """
        # Normalise to UTC if timezone info is present.
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc)

        # Weekend check: Python weekday() is 0=Mon … 6=Sun.
        if ts.weekday() >= 5:
            return Session.WEEKEND

        total = self._to_minutes(ts.hour, ts.minute)

        prime_open_start = self._to_minutes(*self._PRIME_OPEN_START_HM)
        prime_open_end = self._to_minutes(*self._PRIME_OPEN_END_HM)
        prime_close_start = self._to_minutes(*self._PRIME_CLOSE_START_HM)
        prime_close_end = self._to_minutes(*self._PRIME_CLOSE_END_HM)
        us_open = self._to_minutes(*self._US_OPEN_HM)
        us_close = self._to_minutes(*self._US_CLOSE_HM)
        london_start = self._to_minutes(*self._LONDON_START_HM)
        london_end = self._to_minutes(*self._LONDON_END_HM)
        asian_start = self._to_minutes(*self._ASIAN_START_HM)
        asian_end = self._to_minutes(*self._ASIAN_END_HM)

        if (prime_open_start <= total < prime_open_end) or (
            prime_close_start <= total < prime_close_end
        ):
            return Session.US_PRIME

        if us_open <= total < us_close:
            return Session.US_NORMAL

        if london_start <= total < london_end:
            return Session.LONDON

        if asian_start <= total < asian_end:
            return Session.ASIAN

        return Session.AFTER_HOURS


class BinanceNormalizer:
    """Normalizes Binance combined-stream trade payloads to :class:`NormalizedTick`.

    Expected raw-data keys (Binance trade stream ``data`` object):

    * ``s`` – symbol (str)
    * ``t`` – trade ID (not used directly)
    * ``T`` – trade timestamp UTC ms (int) — use ``T`` not ``t``
    * ``p`` – price (str)
    * ``q`` – quantity / volume (str)
    * ``m`` – is buyer the market maker (bool); ``True`` → aggressor is SELL

    Optional book-ticker keys (merged from a separate subscription if present):

    * ``b`` – best bid price (str)
    * ``a`` – best ask price (str)
    """

    _tagger = SessionTagger()

    def normalize(self, raw_data: dict) -> NormalizedTick:
        """Convert a Binance trade ``data`` dict to a :class:`NormalizedTick`.

        Args:
            raw_data: The ``data`` field from a Binance combined-stream message.

        Returns:
            A fully populated :class:`NormalizedTick` for the crypto market.
        """
        symbol: str = str(raw_data.get("s", "")).upper()

        # Binance uses capital ``T`` for the actual trade execution timestamp (ms).
        raw_ts = raw_data.get("T") or raw_data.get("t")
        if not raw_ts:
            raise ValueError(
                f"Binance trade payload is missing timestamp fields 'T'/'t': {raw_data}"
            )
        timestamp_ms: int = int(raw_ts)

        price = Decimal(str(raw_data["p"]))
        volume = Decimal(str(raw_data["q"]))

        # ``m=True``  → buyer is the market maker → trade was a SELL aggression.
        # ``m=False`` → seller is the market maker → trade was a BUY aggression.
        is_maker_buy: bool = bool(raw_data.get("m", False))
        side = TradeSide.SELL if is_maker_buy else TradeSide.BUY

        bid: Optional[Decimal] = (
            Decimal(str(raw_data["b"])) if raw_data.get("b") else None
        )
        ask: Optional[Decimal] = (
            Decimal(str(raw_data["a"])) if raw_data.get("a") else None
        )

        ts_utc = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
        session = self._tagger.tag(ts_utc)

        raw_tick = RawTick(
            symbol=symbol,
            market=Market.CRYPTO,
            timestamp_ms=timestamp_ms,
            price=price,
            volume=volume,
            side=side,
            bid=bid,
            ask=ask,
            raw_data=raw_data,
        )

        return NormalizedTick(
            symbol=symbol,
            market=Market.CRYPTO,
            timestamp_ms=timestamp_ms,
            price=price,
            volume=volume,
            side=side,
            bid=bid,
            ask=ask,
            session=session,
            source_tick=raw_tick,
        )


class AlpacaNormalizer:
    """Normalizes Alpaca trade-stream payloads to :class:`NormalizedTick`.

    Expected raw-data keys (Alpaca ``T="t"`` trade message):

    * ``S`` – symbol (str)
    * ``t`` – ISO 8601 timestamp string (e.g. ``"2024-01-15T14:30:00.123456789Z"``)
    * ``p`` – price (float)
    * ``s`` – size / volume (float)
    * ``c`` – conditions list (list[str]); not reliably buy/sell, default UNKNOWN
    """

    _tagger = SessionTagger()

    def normalize(self, raw_data: dict) -> NormalizedTick:
        """Convert an Alpaca trade message dict to a :class:`NormalizedTick`.

        Args:
            raw_data: A single Alpaca trade event dict.

        Returns:
            A fully populated :class:`NormalizedTick` for the equity market.
        """
        symbol: str = str(raw_data.get("S", "")).upper()

        # Alpaca sends ISO 8601 strings; strip sub-second nanos beyond 6 digits.
        raw_ts: str = str(raw_data.get("t", ""))
        ts_utc = self._parse_alpaca_timestamp(raw_ts)
        timestamp_ms: int = int(ts_utc.timestamp() * 1000)

        price = Decimal(str(raw_data["p"]))
        volume = Decimal(str(raw_data["s"]))

        # Alpaca trade conditions do not reliably encode aggressor side.
        side = TradeSide.UNKNOWN

        session = self._tagger.tag(ts_utc)

        raw_tick = RawTick(
            symbol=symbol,
            market=Market.EQUITY,
            timestamp_ms=timestamp_ms,
            price=price,
            volume=volume,
            side=side,
            raw_data=raw_data,
        )

        return NormalizedTick(
            symbol=symbol,
            market=Market.EQUITY,
            timestamp_ms=timestamp_ms,
            price=price,
            volume=volume,
            side=side,
            session=session,
            source_tick=raw_tick,
        )

    @staticmethod
    def _parse_alpaca_timestamp(raw: str) -> datetime:
        """Parse an Alpaca ISO 8601 timestamp to a UTC-aware :class:`datetime`.

        Handles nanosecond precision by truncating to microseconds.

        Args:
            raw: ISO timestamp string, e.g. ``"2024-01-15T14:30:00.123456789Z"``.

        Returns:
            UTC-aware :class:`datetime`.
        """
        # Replace trailing Z with +00:00 for fromisoformat compatibility.
        normalised = raw.replace("Z", "+00:00")

        # Truncate sub-second component to at most 6 digits (microseconds).
        if "." in normalised:
            dot_idx = normalised.index(".")
            tz_idx = normalised.index("+", dot_idx) if "+" in normalised[dot_idx:] else len(normalised)
            sub_second = normalised[dot_idx + 1 : tz_idx]
            truncated_sub = sub_second[:6].ljust(6, "0")
            normalised = normalised[: dot_idx + 1] + truncated_sub + normalised[tz_idx:]

        return datetime.fromisoformat(normalised)


class NormalizerFactory:
    """Factory that returns the appropriate normalizer for a given market.

    Usage::

        normalizer = NormalizerFactory.create(Market.CRYPTO)
        tick = normalizer.normalize(raw_data)
    """

    @staticmethod
    def create(market: Market) -> BinanceNormalizer | AlpacaNormalizer:
        """Return the normalizer for *market*.

        Args:
            market: The :class:`~core.models.tick.Market` to normalise for.

        Returns:
            A :class:`BinanceNormalizer` for crypto or
            :class:`AlpacaNormalizer` for equity.

        Raises:
            ValueError: If *market* is not supported.
        """
        if market == Market.CRYPTO:
            return BinanceNormalizer()
        if market == Market.EQUITY:
            return AlpacaNormalizer()
        raise ValueError(f"No normalizer registered for market: {market!r}")
