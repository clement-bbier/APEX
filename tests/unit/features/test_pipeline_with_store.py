"""Tests for FeaturePipeline.run() wiring with FeatureStore (Phase 3.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import polars as pl
import pytest

from features.base import FeatureCalculator
from features.labels import TripleBarrierLabelerAdapter
from features.pipeline import FeaturePipeline
from features.store.base import FeatureStore
from features.weights import SampleWeighter

# ── Helpers ──────────────────────────────────────────────────────────────


class _StubCalculator(FeatureCalculator):
    """Minimal calculator that adds a constant column."""

    def __init__(self, col_name: str = "feat_a") -> None:
        self._col = col_name

    def name(self) -> str:
        return self._col

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(pl.lit(1.0).alias(self._col))

    def required_columns(self) -> list[str]:
        return ["close"]

    def output_columns(self) -> list[str]:
        return [self._col]


# ── Tests ────────────────────────────────────────────────────────────────


class TestPipelineRunWithStore:
    """FeaturePipeline.run() computes and saves features."""

    @pytest.mark.asyncio
    async def test_run_calls_save_per_feature(self) -> None:
        mock_store = AsyncMock(spec=FeatureStore)
        calc_a = _StubCalculator("feat_a")
        calc_b = _StubCalculator("feat_b")
        pipeline = FeaturePipeline(
            [calc_a, calc_b],
            TripleBarrierLabelerAdapter(),
            SampleWeighter(),
            feature_store=mock_store,
        )
        bars = pl.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 1, tzinfo=UTC)],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000.0],
            }
        )
        aid = uuid4()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 1, tzinfo=UTC)

        result = await pipeline.run(aid, bars, start, end)

        # 2 calculators × 1 output_column each = 2 save calls
        assert mock_store.save.await_count == 2
        assert "feat_a" in result.columns
        assert "feat_b" in result.columns

    @pytest.mark.asyncio
    async def test_run_returns_augmented_df(self) -> None:
        mock_store = AsyncMock(spec=FeatureStore)
        pipeline = FeaturePipeline(
            [_StubCalculator("feat_a")],
            TripleBarrierLabelerAdapter(),
            SampleWeighter(),
            feature_store=mock_store,
        )
        bars = pl.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 1, tzinfo=UTC)],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000.0],
            }
        )
        result = await pipeline.run(
            uuid4(), bars, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 6, 1, tzinfo=UTC)
        )
        assert "feat_a" in result.columns
        assert result.shape[0] == 1

    @pytest.mark.asyncio
    async def test_run_without_store_raises(self) -> None:
        pipeline = FeaturePipeline(
            [],
            TripleBarrierLabelerAdapter(),
            SampleWeighter(),
        )
        bars = pl.DataFrame({"timestamp": [], "close": []})
        with pytest.raises(RuntimeError, match="requires a FeatureStore"):
            await pipeline.run(
                uuid4(), bars, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 6, 1, tzinfo=UTC)
            )

    @pytest.mark.asyncio
    async def test_run_with_as_of_backtest(self) -> None:
        """as_of is passed through to computed_at in the FeatureVersion."""
        mock_store = AsyncMock(spec=FeatureStore)
        pipeline = FeaturePipeline(
            [_StubCalculator("feat_a")],
            TripleBarrierLabelerAdapter(),
            SampleWeighter(),
            feature_store=mock_store,
        )
        bars = pl.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 1, tzinfo=UTC)],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000.0],
            }
        )
        as_of = datetime(2024, 3, 15, tzinfo=UTC)
        await pipeline.run(
            uuid4(),
            bars,
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 6, 1, tzinfo=UTC),
            as_of=as_of,
        )
        # Verify the version passed to save has computed_at == as_of
        save_call = mock_store.save.call_args
        version_arg = save_call[0][2]  # third positional: version
        assert version_arg.computed_at == as_of
