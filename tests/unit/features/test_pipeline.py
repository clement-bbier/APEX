"""Tests for features.pipeline — FeaturePipeline orchestrator."""

from __future__ import annotations

import polars as pl
import pytest

from features.base import FeatureCalculator
from features.labels import TripleBarrierLabelerAdapter
from features.pipeline import FeaturePipeline
from features.weights import SampleWeighter

# -- Helpers --


class _IdentityCalculator(FeatureCalculator):
    """Calculator that adds a constant column — for pipeline tests."""

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


# -- Tests --


class TestFeaturePipelineConstruction:
    """FeaturePipeline constructor injection."""

    def test_constructor_stores_components(self) -> None:
        calcs = [_IdentityCalculator()]
        labeler = TripleBarrierLabelerAdapter()
        weighter = SampleWeighter()
        pipeline = FeaturePipeline(calcs, labeler, weighter)
        assert len(pipeline.calculators) == 1

    def test_calculators_returns_copy(self) -> None:
        calcs = [_IdentityCalculator()]
        pipeline = FeaturePipeline(calcs, TripleBarrierLabelerAdapter(), SampleWeighter())
        # Mutating the returned list should not affect the pipeline
        pipeline.calculators.append(_IdentityCalculator("extra"))
        assert len(pipeline.calculators) == 1


class TestRunOnFrame:
    """FeaturePipeline.run_on_frame processes a DataFrame."""

    def test_single_calculator(self, synthetic_bars: pl.DataFrame) -> None:
        calc = _IdentityCalculator()
        pipeline = FeaturePipeline([calc], TripleBarrierLabelerAdapter(), SampleWeighter())
        result = pipeline.run_on_frame(synthetic_bars, symbol="BTCUSD")
        assert "feat_a" in result.columns

    def test_multiple_calculators(self, synthetic_bars: pl.DataFrame) -> None:
        calcs = [_IdentityCalculator("feat_a"), _IdentityCalculator("feat_b")]
        pipeline = FeaturePipeline(calcs, TripleBarrierLabelerAdapter(), SampleWeighter())
        result = pipeline.run_on_frame(synthetic_bars, symbol="BTCUSD")
        assert "feat_a" in result.columns
        assert "feat_b" in result.columns

    def test_empty_calculator_list(self, synthetic_bars: pl.DataFrame) -> None:
        pipeline = FeaturePipeline([], TripleBarrierLabelerAdapter(), SampleWeighter())
        result = pipeline.run_on_frame(synthetic_bars, symbol="BTCUSD")
        assert result.shape == synthetic_bars.shape


class TestRunRequiresStore:
    """FeaturePipeline.run requires a FeatureStore (Phase 3.2)."""

    @pytest.mark.asyncio
    async def test_run_without_store_raises(self) -> None:
        from datetime import UTC, datetime
        from uuid import uuid4

        pipeline = FeaturePipeline([], TripleBarrierLabelerAdapter(), SampleWeighter())
        bars = pl.DataFrame({"timestamp": [], "close": []})
        with pytest.raises(RuntimeError, match=r"requires a FeatureStore"):
            await pipeline.run(uuid4(), bars, datetime.now(UTC), datetime.now(UTC))
