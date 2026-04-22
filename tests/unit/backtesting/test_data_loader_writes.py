"""Round-trip smoke test for ``backtesting.data_loader`` parquet I/O.

Guards against pyarrow API drift. The module pins ``pq.write_table`` with a
targeted ``# type: ignore[no-untyped-call]`` (see issue #240) because
pyarrow 24.0 ships ``py.typed`` without annotations for that symbol. If
pyarrow ever changes its public signature or return semantics, this test
will fail loudly instead of silently shipping a broken writer.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from backtesting.data_loader import load_parquet, save_parquet
from core.models.tick import Market, NormalizedTick, Session, TradeSide


def _make_tick(ts_ms: int, price: str) -> NormalizedTick:
    return NormalizedTick(
        symbol="BTC/USDT",
        market=Market.CRYPTO,
        timestamp_ms=ts_ms,
        price=Decimal(price),
        volume=Decimal("0.5"),
        side=TradeSide.UNKNOWN,
        bid=Decimal(price),
        ask=Decimal(price),
        spread_bps=Decimal("1.0"),
        session=Session.AFTER_HOURS,
    )


def test_save_parquet_round_trip(tmp_path: Path) -> None:
    ticks = [
        _make_tick(1_700_000_000_000, "42000.00"),
        _make_tick(1_700_000_060_000, "42010.50"),
        _make_tick(1_700_000_120_000, "42005.25"),
    ]
    out = tmp_path / "ticks.parquet"

    save_parquet(ticks, out)
    assert out.exists()
    assert out.stat().st_size > 0

    loaded = load_parquet(out)
    assert len(loaded) == len(ticks)
    for original, back in zip(ticks, loaded, strict=True):
        assert back.symbol == original.symbol
        assert back.market == original.market
        assert back.timestamp_ms == original.timestamp_ms
        assert back.price == original.price
        assert back.volume == original.volume
        assert back.session == original.session
