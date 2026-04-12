"""Tests for features.labels — TripleBarrierLabelerAdapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl

from core.math.labeling import TripleBarrierConfig, TripleBarrierLabeler
from features.labels import TripleBarrierLabelerAdapter


class TestTripleBarrierLabelerAdapter:
    """Adapter wraps core labeler and returns Polars DataFrame."""

    def test_output_columns(self) -> None:
        adapter = TripleBarrierLabelerAdapter()
        df = self._make_bars(20)
        result = adapter.label(df)
        assert set(result.columns) == {"label", "t1", "pt_touch", "sl_touch"}

    def test_output_length_matches_input(self) -> None:
        adapter = TripleBarrierLabelerAdapter()
        df = self._make_bars(30)
        result = adapter.label(df)
        assert len(result) == len(df)

    def test_labels_are_valid_values(self) -> None:
        adapter = TripleBarrierLabelerAdapter()
        df = self._make_bars(50)
        result = adapter.label(df)
        labels = set(result["label"].to_list())
        assert labels.issubset({-1, 0, 1})

    def test_parity_with_core_labeler_single_event(self) -> None:
        """Adapter produces the same label as the core labeler for one event.

        We test at index 5 (not 0) so the vol window has enough data
        to match the adapter's internal computation exactly.
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

        # Match the adapter's vol computation at index idx
        idx = 5
        vol_window = closes[max(0, idx - config.vol_lookback) : idx + 1]
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
        assert adapter_result["label"][idx] == core_result.label

    def test_config_passthrough(self) -> None:
        config = TripleBarrierConfig(pt_multiplier=3.0, sl_multiplier=2.0)
        adapter = TripleBarrierLabelerAdapter(config)
        assert adapter.config.pt_multiplier == 3.0

    def test_short_side(self) -> None:
        adapter = TripleBarrierLabelerAdapter()
        df = self._make_bars(30)
        result = adapter.label(df, side=-1)
        labels = set(result["label"].to_list())
        assert labels.issubset({-1, 0, 1})

    # ── Helpers ───────────────────────────────────────��──────────────

    @staticmethod
    def _make_bars(n: int) -> pl.DataFrame:
        """Build a small bar DataFrame with trending prices."""
        base = datetime(2024, 1, 1, tzinfo=UTC)
        timestamps = [base + timedelta(minutes=5 * i) for i in range(n)]
        # Simple uptrend with volatility
        closes = [30_000.0 + i * 50.0 + (i % 3) * 20.0 for i in range(n)]
        return pl.DataFrame({"timestamp": timestamps, "close": closes})
