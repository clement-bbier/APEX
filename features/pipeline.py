"""FeaturePipeline — orchestrates feature computation from raw data.

Constructor injection pattern (PHASE_3_SPEC Section 3.4): the pipeline
receives its calculators, labeler, and weighter at construction time.

Phase 3.2 wires ``run()`` to fetch bars from TimescaleDB, compute
features, and persist them to the FeatureStore.

Reference:
    Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*.
    Wiley, Ch. 3-5.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import UUID

import polars as pl
import structlog

from features.base import FeatureCalculator
from features.labels import TripleBarrierLabelerAdapter
from features.store.base import FeatureStore
from features.versioning import (
    FeatureVersion,
    compute_content_hash,
    compute_version_string,
)
from features.weights import SampleWeighter

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class FeaturePipeline:
    """Orchestrates feature computation from raw data to feature matrix.

    Follows the Constructor Injection pattern (Martin, 2008):
    all dependencies are provided at construction, not discovered at
    runtime.

    Phase 3.2: ``feature_store`` is optional — if not provided,
    ``run_on_frame()`` remains functional as in 3.1 but ``run()``
    raises a clear error.

    Reference:
        Lopez de Prado, M. (2018). *Advances in Financial Machine
        Learning*. Wiley, Ch. 3 (Labels), Ch. 4 (Weights), Ch. 5
        (Fractional Differentiation).
    """

    def __init__(
        self,
        calculators: list[FeatureCalculator],
        labeler: TripleBarrierLabelerAdapter,
        weighter: SampleWeighter,
        feature_store: FeatureStore | None = None,
    ) -> None:
        self._calculators = list(calculators)
        self._labeler = labeler
        self._weighter = weighter
        self._feature_store = feature_store

    @property
    def calculators(self) -> list[FeatureCalculator]:
        """Injected feature calculators."""
        return list(self._calculators)

    async def run(
        self,
        asset_id: UUID,
        bars: pl.DataFrame,
        start: datetime,
        end: datetime,
        as_of: datetime | None = None,
    ) -> pl.DataFrame:
        """Compute features on bars and persist them to the store.

        If ``as_of`` is provided, backtest mode: features are persisted
        with ``computed_at=as_of``.  This guarantees point-in-time
        correctness for historical backtests.

        Args:
            asset_id: Asset UUID.
            bars: Polars DataFrame with bar data (OHLCV + timestamp).
            start: Start of the computation range.
            end: End of the computation range.
            as_of: Wall-clock time of computation for PIT semantics.
                Defaults to ``datetime.now(UTC)`` if not provided.

        Returns:
            Augmented DataFrame with all feature columns added.

        Raises:
            RuntimeError: If ``feature_store`` was not injected.
        """
        if self._feature_store is None:
            raise RuntimeError(
                "FeaturePipeline.run() requires a FeatureStore. "
                "Inject via constructor or use run_on_frame() for testing."
            )

        computed_at = as_of if as_of is not None else datetime.now(UTC)
        result = self.run_on_frame(bars, str(asset_id))

        for calc in self._calculators:
            feature_df = result.select(["timestamp", *calc.output_columns()])
            calc_params: dict[str, object] = getattr(calc, "params", {})
            for col_name in calc.output_columns():
                single_feature = feature_df.select(["timestamp", col_name])
                version_meta = {
                    "version": calc.version,
                    "params": calc_params,
                    "output": col_name,
                }
                content_hash = compute_content_hash(single_feature)
                version_str = compute_version_string(calc.name(), version_meta, computed_at)
                # start_ts/end_ts from actual DataFrame, not params
                ts_min = single_feature["timestamp"].min()
                ts_max = single_feature["timestamp"].max()
                version = FeatureVersion(
                    asset_id=asset_id,
                    feature_name=col_name,
                    version=version_str,
                    computed_at=computed_at,
                    content_hash=content_hash,
                    calculator_name=calc.name(),
                    calculator_params={
                        "version": calc.version,
                        **dict(calc_params),
                        "output_column": col_name,
                    },
                    row_count=len(single_feature),
                    start_ts=ts_min if isinstance(ts_min, datetime) else start,
                    end_ts=ts_max if isinstance(ts_max, datetime) else end,
                )
                await self._feature_store.save(asset_id, single_feature, version)

        logger.info(
            "feature_pipeline.run_complete",
            asset_id=str(asset_id),
            n_calculators=len(self._calculators),
            n_bars=len(bars),
            computed_at=computed_at.isoformat(),
        )
        return result

    def run_on_frame(self, df: pl.DataFrame, symbol: str) -> pl.DataFrame:
        """Compute features on an already-loaded DataFrame.

        This is the test-friendly entry point for Phase 3.1.

        Args:
            df: Polars DataFrame with bar data (OHLCV + timestamp).
            symbol: Symbol identifier for logging context.

        Returns:
            Augmented DataFrame with all feature columns added.
        """
        t0 = time.monotonic()
        n_bars = len(df)
        result = df

        for calc in self._calculators:
            calc.validate_input(result)
            result = calc.compute(result)
            calc.validate_output(result)

        duration_ms = (time.monotonic() - t0) * 1000
        n_features = sum(len(c.output_columns()) for c in self._calculators)

        logger.info(
            "feature_pipeline.run_on_frame",
            symbol=symbol,
            n_bars=n_bars,
            n_features=n_features,
            n_calculators=len(self._calculators),
            duration_ms=round(duration_ms, 2),
        )
        return result
