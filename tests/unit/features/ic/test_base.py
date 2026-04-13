"""Tests for features.ic.base — ICMetric ABC and ICResult dataclass."""

from __future__ import annotations

import pytest

from features.ic.base import ICMetric, ICResult


class TestICResult:
    """ICResult is a frozen dataclass."""

    def test_frozen(self) -> None:
        r = ICResult(
            ic=0.05,
            ic_ir=0.6,
            p_value=0.01,
            n_samples=1000,
            ci_low=0.03,
            ci_high=0.07,
        )
        with pytest.raises(AttributeError):
            r.ic = 0.99  # type: ignore[misc]

    def test_fields_accessible(self) -> None:
        r = ICResult(
            ic=0.05,
            ic_ir=0.6,
            p_value=0.01,
            n_samples=1000,
            ci_low=0.03,
            ci_high=0.07,
        )
        assert r.ic == 0.05
        assert r.ic_ir == 0.6
        assert r.p_value == 0.01
        assert r.n_samples == 1000
        assert r.ci_low == 0.03
        assert r.ci_high == 0.07

    def test_equality(self) -> None:
        a = ICResult(ic=0.05, ic_ir=0.6, p_value=0.01, n_samples=100, ci_low=0.0, ci_high=0.1)
        b = ICResult(ic=0.05, ic_ir=0.6, p_value=0.01, n_samples=100, ci_low=0.0, ci_high=0.1)
        assert a == b


class TestICMetricABC:
    """ICMetric cannot be instantiated."""

    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError, match="abstract method"):
            ICMetric()  # type: ignore[abstract]
