"""Tests for features.base — FeatureCalculator ABC."""

from __future__ import annotations

import polars as pl
import pytest

from features.base import FeatureCalculator

# ── Concrete test implementation ───────────────────��──────────────────


class _DummyCalculator(FeatureCalculator):
    """Minimal concrete calculator for testing the ABC."""

    def name(self) -> str:
        return "dummy"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(pl.col("close").alias("dummy_signal"))

    def required_columns(self) -> list[str]:
        return ["close"]

    def output_columns(self) -> list[str]:
        return ["dummy_signal"]


# ── Tests ────────────────────────────��───────────────────────────���────


class TestFeatureCalculatorABC:
    """FeatureCalculator cannot be instantiated directly."""

    def test_abc_cannot_be_instantiated(self) -> None:
        with pytest.raises(TypeError, match="abstract method"):
            FeatureCalculator()  # type: ignore[abstract]

    def test_concrete_subclass_instantiates(self) -> None:
        calc = _DummyCalculator()
        assert calc.name() == "dummy"

    def test_default_version(self) -> None:
        calc = _DummyCalculator()
        assert calc.version == "0.1.0"


class TestValidateInput:
    """FeatureCalculator.validate_input checks required columns."""

    def test_valid_input_passes(self, synthetic_bars: pl.DataFrame) -> None:
        calc = _DummyCalculator()
        calc.validate_input(synthetic_bars)  # should not raise

    def test_missing_column_raises(self) -> None:
        calc = _DummyCalculator()
        df = pl.DataFrame({"not_close": [1.0, 2.0]})
        with pytest.raises(ValueError, match=r"missing required columns.*close"):
            calc.validate_input(df)

    def test_error_lists_all_missing(self) -> None:
        class _Multi(FeatureCalculator):
            def name(self) -> str:
                return "multi"

            def compute(self, df: pl.DataFrame) -> pl.DataFrame:
                return df

            def required_columns(self) -> list[str]:
                return ["a", "b", "c"]

            def output_columns(self) -> list[str]:
                return []

        calc = _Multi()
        df = pl.DataFrame({"a": [1]})
        with pytest.raises(ValueError, match=r"b.*c"):
            calc.validate_input(df)


class TestValidateOutput:
    """FeatureCalculator.validate_output checks output columns and NaN."""

    def test_valid_output_passes(self, synthetic_bars: pl.DataFrame) -> None:
        calc = _DummyCalculator()
        result = calc.compute(synthetic_bars)
        calc.validate_output(result)

    def test_missing_output_column_raises(self) -> None:
        calc = _DummyCalculator()
        df = pl.DataFrame({"close": [1.0], "other": [2.0]})
        with pytest.raises(ValueError, match=r"missing columns.*dummy_signal"):
            calc.validate_output(df)

    def test_null_outside_warmup_raises(self) -> None:
        calc = _DummyCalculator()
        df = pl.DataFrame({"dummy_signal": [None, 1.0, 2.0]})
        with pytest.raises(ValueError, match="null"):
            calc.validate_output(df)

    def test_null_inside_warmup_passes(self) -> None:
        calc = _DummyCalculator()
        df = pl.DataFrame({"dummy_signal": [None, None, 1.0, 2.0]})
        calc.validate_output(df, warm_up_rows=2)  # should not raise

    def test_empty_df_after_warmup_passes(self) -> None:
        calc = _DummyCalculator()
        df = pl.DataFrame({"dummy_signal": [None, None]})
        calc.validate_output(df, warm_up_rows=2)  # should not raise
