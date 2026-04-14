"""Tests for features.labels — TripleBarrierLabelerAdapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest

from core.math.labeling import TripleBarrierConfig, TripleBarrierLabeler
from features.labels import TripleBarrierLabelerAdapter


class TestTripleBarrierLabelerAdapter:
    """Adapter wraps core labeler and returns Polars DataFrame.

    Phase 4.1 contract: adapter honours ADR-0005 D1 strict vol window
    (``[t - N, t - 1]``), fail-loud on insufficient history, and emits
    one labeled row per bar with enough prior history
    (``i >= vol_lookback``).
    """

    def test_output_columns(self) -> None:
        adapter = TripleBarrierLabelerAdapter()
        df = self._make_bars(40)
        result = adapter.label(df)
        assert set(result.columns) == {"t0", "t1", "label", "pt_touch", "sl_touch"}

    def test_output_length_skips_warmup_bars(self) -> None:
        """len(result) == len(df) - vol_lookback (full lookback warmup)."""
        adapter = TripleBarrierLabelerAdapter()
        df = self._make_bars(40)
        result = adapter.label(df)
        assert len(result) == len(df) - adapter.config.vol_lookback

    def test_labels_are_valid_values(self) -> None:
        adapter = TripleBarrierLabelerAdapter()
        df = self._make_bars(50)
        result = adapter.label(df)
        labels = set(result["label"].to_list())
        assert labels.issubset({-1, 0, 1})

    def test_parity_with_core_labeler_single_event(self) -> None:
        """Adapter produces the same label as the core labeler with strict window.

        ADR-0005 D1: vol window is ``closes[i - N : i]`` strict, so no
        look-ahead into bar ``i``. We replicate that slicing here.
        """
        config = TripleBarrierConfig(
            pt_multiplier=2.0, sl_multiplier=1.0, max_holding_periods=10, vol_lookback=5
        )
        adapter = TripleBarrierLabelerAdapter(config)
        core_labeler = TripleBarrierLabeler(config)

        n = 30
        df = self._make_bars(n)
        closes = [Decimal(str(v)) for v in df["close"].to_list()]
        timestamps = df["timestamp"].to_list()

        idx = 10  # any index with full prior window
        vol_window = closes[idx - config.vol_lookback : idx]  # strict [t-N, t-1]
        vol = core_labeler.compute_daily_vol(vol_window)
        future_prices = [(timestamps[j], closes[j]) for j in range(idx + 1, n)]
        core_result = core_labeler.label_event(
            entry_price=closes[idx],
            entry_time=timestamps[idx],
            side=1,
            future_prices=future_prices,
            daily_vol=vol,
        )

        adapter_result = adapter.label(df, side=1)
        # adapter skips the full vol_lookback warmup; adjust index accordingly
        out_idx = idx - config.vol_lookback
        assert adapter_result["label"][out_idx] == core_result.label

    def test_config_passthrough(self) -> None:
        config = TripleBarrierConfig(pt_multiplier=3.0, sl_multiplier=2.0)
        adapter = TripleBarrierLabelerAdapter(config)
        assert adapter.config.pt_multiplier == 3.0

    def test_short_side(self) -> None:
        adapter = TripleBarrierLabelerAdapter()
        df = self._make_bars(50)  # > vol_lookback=20 warmup
        result = adapter.label(df, side=-1)
        labels = set(result["label"].to_list())
        assert labels.issubset({-1, 0, 1})

    def test_invalid_side_raises(self) -> None:
        adapter = TripleBarrierLabelerAdapter()
        df = self._make_bars(10)
        with pytest.raises(ValueError, match="side must be"):
            adapter.label(df, side=0)

    def test_insufficient_rows_raises(self) -> None:
        """Fewer rows than vol_lookback+1 cannot produce any label."""
        adapter = TripleBarrierLabelerAdapter()
        df = self._make_bars(adapter.config.vol_lookback)
        with pytest.raises(ValueError, match="at least"):
            adapter.label(df)

    def test_tz_naive_timestamps_raise(self) -> None:
        """Phase 4.1 fail-loud: tz-naive datetimes must raise."""
        adapter = TripleBarrierLabelerAdapter()
        base = datetime(2024, 1, 1)  # tz-naive
        timestamps = [base + timedelta(minutes=5 * i) for i in range(40)]
        closes = [30_000.0 + i * 50.0 for i in range(40)]
        df = pl.DataFrame({"timestamp": timestamps, "close": closes})
        with pytest.raises(ValueError, match="tz-naive"):
            adapter.label(df)

    # -- Helpers --

    @staticmethod
    def _make_bars(n: int) -> pl.DataFrame:
        """Build a small bar DataFrame with trending prices."""
        base = datetime(2024, 1, 1, tzinfo=UTC)
        timestamps = [base + timedelta(minutes=5 * i) for i in range(n)]
        # Simple uptrend with volatility
        closes = [30_000.0 + i * 50.0 + (i % 3) * 20.0 for i in range(n)]
        return pl.DataFrame({"timestamp": timestamps, "close": closes})


class TestLabelEvents:
    """New ``label_events()`` batch API — Phase 4.1 extension."""

    @staticmethod
    def _bars(n: int) -> pl.DataFrame:
        base = datetime(2024, 6, 1, tzinfo=UTC)
        timestamps = [base + timedelta(minutes=5 * i) for i in range(n)]
        closes = [100.0 + i * 0.1 + (i % 5) * 0.2 for i in range(n)]
        return pl.DataFrame({"timestamp": timestamps, "close": closes})

    def test_empty_events_returns_empty_list(self) -> None:
        adapter = TripleBarrierLabelerAdapter()
        bars = self._bars(50)
        events = pl.DataFrame({"timestamp": []}, schema={"timestamp": pl.Datetime("us", "UTC")})
        assert adapter.label_events(events, bars) == []

    def test_orphan_event_raises(self) -> None:
        adapter = TripleBarrierLabelerAdapter()
        bars = self._bars(50)
        orphan = datetime(2030, 1, 1, tzinfo=UTC)
        events = pl.DataFrame({"timestamp": [orphan]})
        with pytest.raises(ValueError, match="not found in bars"):
            adapter.label_events(events, bars)

    def test_short_direction_raises(self) -> None:
        adapter = TripleBarrierLabelerAdapter()
        bars = self._bars(50)
        events = pl.DataFrame(
            {"timestamp": [bars["timestamp"][30]], "direction": [-1]},
        )
        with pytest.raises(NotImplementedError, match="long-only"):
            adapter.label_events(events, bars)
