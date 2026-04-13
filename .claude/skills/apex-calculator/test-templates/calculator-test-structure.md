# Calculator Test Structure Template

Minimum 20 tests, target 25-31. Organize in test classes by category.

## Categories and counts

```python
"""Unit tests for <Name>Calculator (Phase 3.X).

<N> tests covering ABC conformity, correctness, look-ahead defense,
D028 compliance, D029 variance gates, D030 constructor validation,
edge cases, integration, and report formatting.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from features.calculators.<name> import <Name>Calculator
from features.validation.<name>_report import <Name>ValidationReport
from features.ic.base import ICResult

# Hypothesis max_examples gated by CI env (pattern PR #111 hotfix)
HYPOTHESIS_EXAMPLES = 50 if os.environ.get("CI") else 300


class TestABCConformity:
    """3 tests: name, required_columns, output_columns."""


class TestConstructorValidation:
    """N tests, one per D030 validated invariant."""


class TestInputValidation:
    """2+ tests: invalid values, missing column."""


class TestCorrectness:
    """7+ tests: shape, warm-up NaN, Hypothesis bounds, determinism, version."""


class TestSignConvention:
    """If applicable (e.g., GEX): characterize dealer adjustments."""


class TestMagnitudeSanity:
    """1 test: realistic synthetic input produces output in plausible range."""


class TestLookAheadDefense:
    """2 tests: strict past independence, characterization."""


class TestD028Compliance:
    """1 test: docstring declares classification keywords for each column."""


class TestVarianceGates:
    """One test per signal output column (D029)."""


class TestEdgeCases:
    """3 tests: insufficient data, missing column, unsorted timestamps."""


class TestIntegration:
    """2 tests: ValidationPipeline with ICStage, IC > 0.1 on predictive synthetic.
    If calculator is snapshot-granularity (like GEX), aggregate to snapshot level
    before measuring IC (D034).
    """


class TestReport:
    """2 tests: summary schema stable on empty, None significance → 'n/a'."""
```

## Helper patterns

Define private `_make_<data_type>()` helpers at module level to build synthetic inputs.
Follow existing calculators for the expected structure. Seed with default for determinism.
