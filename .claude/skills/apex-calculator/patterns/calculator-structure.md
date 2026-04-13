# Calculator File Structure Pattern

## Imports order

```python
from __future__ import annotations

from typing import ClassVar, Literal
from decimal import Decimal  # if financial values
from datetime import datetime, UTC

import numpy as np
import numpy.typing as npt
import polars as pl
import structlog

from features.base import FeatureCalculator

logger = structlog.get_logger(__name__)
```

## Class skeleton

```python
class <Name>Calculator(FeatureCalculator):
    """<Title> calculator (<Author> <Year>).

    <2-3 sentence description>.

    Output columns:
        <col_1>: <description> (<realization | forecast-like> at t).
        ...

    D028 classification:
        <list realization columns>: realization at t (<reason>).
        <list forecast-like columns>: forecast-like at t (<reason>).

    [D027 intraday contract (if applicable, bar_frequency="5m"):]
        <emission rules per column>

    Look-ahead defense:
        <D024 expanding or fixed-length rolling window rule>

    [Fallback for equities without L2 (if applicable):]
        <Lee-Ready or alternative rule>

    Reference:
        <Author>, <Year>. "<Title>". <Journal/Venue>, <volume>(<issue>), <pages>.
        [additional refs]
    """

    _REQUIRED_COLUMNS: ClassVar[list[str]] = [...]

    def __init__(self, <params with defaults>) -> None:
        # D030 validation — raise ValueError with explicit message
        if <invariant_violated>:
            raise ValueError(f"<param> must <constraint>, got {<param>}")
        # ... store all params as self._<param>

    @property
    def version(self) -> str:
        return "1.0.0"  # SemVer

    def name(self) -> str:
        return "<name>"

    def required_columns(self) -> list[str]:
        return list(self._REQUIRED_COLUMNS)

    def output_columns(self) -> list[str]:
        # Generate dynamically if params affect naming (D030)
        return [...]

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        self.validate_input(df)

        # Monotonic timestamp invariant (pattern from PR #111 hotfix)
        is_sorted = df.select(pl.col("timestamp").is_sorted(descending=False)).item()
        if not isinstance(is_sorted, bool) or not is_sorted:
            raise ValueError(
                "<Name>Calculator.compute() requires ascending-sorted 'timestamp'."
            )

        # ... computation steps
```
