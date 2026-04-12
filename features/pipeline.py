"""FeaturePipeline — orchestrates feature computation from raw data.

Constructor injection pattern (PHASE_3_SPEC Section 3.4): the pipeline
receives its calculators, labeler, and weighter at construction time.

In Phase 3.1, ``run()`` raises ``NotImplementedError`` (requires
TimescaleDB wiring from Phase 3.2).  ``run_on_frame()`` is functional
for tests.

Reference:
    Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*.
    Wiley, Ch. 3-5.
"""

from __future__ import annotations

import time
from datetime import datetime

import polars as pl
import structlog

from features.base import FeatureCalculator
from features.labels import TripleBarrierLabelerAdapter
from features.weights import SampleWeighter

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class FeaturePipeline:
    """Orchestrates feature computation from raw data to feature matrix.

    Follows the Constructor Injection pattern (Martin, 2008):
    all dependencies are provided at construction, not discovered at
    runtime.

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
    ) -> None:
        self._calculators = calculators
        self._labeler = labeler
        self._weighter = weighter

    @property
    def calculators(self) -> list[FeatureCalculator]:
        """Injected feature calculators."""
        return list(self._calculators)

    async def run(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        bar_size: str = "5m",
    ) -> pl.DataFrame:
        """Fetch data from store and compute full feature matrix.

        .. note::
            This method is a placeholder for Phase 3.2 which wires the
            TimescaleDB data source.  Call :meth:`run_on_frame` for
            testing with synthetic data.

        Raises:
            NotImplementedError: Always — wired in Phase 3.2.
        """
        raise NotImplementedError(
            "FeaturePipeline.run() requires TimescaleDB data source — "
            "wired in Phase 3.2.  Use run_on_frame() for testing."
        )

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
