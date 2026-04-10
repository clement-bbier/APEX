"""Shared CLI helpers for APEX backfill scripts.

Extracted from backfill_binance.py to avoid duplication across
backfill_binance.py and backfill_equities.py.
"""

from __future__ import annotations

from datetime import UTC, datetime


def _parse_utc_datetime(s: str) -> datetime:
    """Parse ISO datetime string and ensure UTC tz.

    Args:
        s: An ISO-format datetime string (e.g. ``2024-01-01``).

    Returns:
        A UTC-aware :class:`datetime`.
    """
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
