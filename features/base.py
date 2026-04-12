"""FeatureCalculator ABC — interface for all feature calculators.

Every feature calculator takes a Polars DataFrame of bars/ticks and
returns a Polars DataFrame with computed feature columns appended.

Spec reference: ``docs/phases/PHASE_3_SPEC.md`` Section 2.1 A.4.
Academic reference:
    Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio Management*
    (2nd ed.). McGraw-Hill, Ch. 14 — "Forecasting".
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import polars as pl


class FeatureCalculator(ABC):
    """Base class for all APEX feature calculators.

    Sub-classes implement concrete alpha features (HAR-RV, Rough Vol,
    OFI, CVD, Kyle lambda, GEX) starting from Phase 3.4.

    The ``validate_input`` / ``validate_output`` methods are concrete
    and enforce structural correctness at the pipeline boundary.

    Reference:
        Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio
        Management* (2nd ed.), Ch. 14. McGraw-Hill.
    """

    # ------------------------------------------------------------------
    # Abstract interface — every calculator must implement these
    # ------------------------------------------------------------------

    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this feature (e.g. ``'har_rv'``)."""

    @abstractmethod
    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        """Compute feature columns and return an augmented DataFrame.

        The returned DataFrame MUST contain all original columns plus
        the columns declared by :meth:`output_columns`.

        Args:
            df: Input DataFrame with at least the columns declared
                by :meth:`required_columns`.

        Returns:
            A **new** DataFrame (immutability) with feature columns added.
        """

    @abstractmethod
    def required_columns(self) -> list[str]:
        """Column names that must be present in the input DataFrame."""

    @abstractmethod
    def output_columns(self) -> list[str]:
        """Column names that this calculator adds to the DataFrame."""

    # ------------------------------------------------------------------
    # Version tracking — useful for FeatureStore (Phase 3.2)
    # ------------------------------------------------------------------

    @property
    def version(self) -> str:
        """Semantic version of this calculator's implementation.

        Used by FeatureStore (Phase 3.2) for reproducibility tracking.
        Override in concrete sub-classes when the formula changes.
        """
        return "0.1.0"

    # ------------------------------------------------------------------
    # Concrete validation helpers
    # ------------------------------------------------------------------

    def validate_input(self, df: pl.DataFrame) -> None:
        """Verify that *df* contains all required columns.

        Raises:
            ValueError: With a message listing the missing columns.
        """
        required = set(self.required_columns())
        present = set(df.columns)
        missing = required - present
        if missing:
            raise ValueError(
                f"FeatureCalculator '{self.name()}' is missing required columns: {sorted(missing)}"
            )

    def validate_output(self, df: pl.DataFrame, warm_up_rows: int = 0) -> None:
        """Verify that *df* contains all output columns without NaN.

        Args:
            df: The DataFrame returned by :meth:`compute`.
            warm_up_rows: Number of leading rows allowed to contain nulls
                (warm-up period for rolling calculations).

        Raises:
            ValueError: If output columns are missing or contain NaN
                outside the warm-up window.
        """
        expected = set(self.output_columns())
        present = set(df.columns)
        missing = expected - present
        if missing:
            raise ValueError(
                f"FeatureCalculator '{self.name()}' output is missing columns: {sorted(missing)}"
            )

        check_df = df.slice(warm_up_rows) if warm_up_rows > 0 else df
        if len(check_df) == 0:
            return

        for col in self.output_columns():
            null_count = check_df[col].null_count()
            if null_count > 0:
                raise ValueError(
                    f"FeatureCalculator '{self.name()}' output column "
                    f"'{col}' has {null_count} null(s) outside warm-up "
                    f"window (warm_up_rows={warm_up_rows})."
                )
            # Polars null_count does not detect float NaN values.
            if check_df[col].dtype in (pl.Float32, pl.Float64):
                nan_count = check_df[col].is_nan().sum()
                if nan_count > 0:
                    raise ValueError(
                        f"FeatureCalculator '{self.name()}' output column "
                        f"'{col}' contains {nan_count} NaN values outside "
                        f"warm-up window (warm_up_rows={warm_up_rows})."
                    )
