"""Tests for :mod:`features.integration.warmup_gate`."""

from __future__ import annotations

import pytest

from features.integration.warmup_gate import WarmupGate


class TestConstructor:
    def test_rejects_non_positive_required_observations(self) -> None:
        with pytest.raises(ValueError, match="required_observations"):
            WarmupGate(feature_name="f", required_observations=0)

    def test_accepts_minimum_one(self) -> None:
        gate = WarmupGate(feature_name="f", required_observations=1)
        assert gate.observed == 0
        assert gate.is_ready is False


class TestStateTransitions:
    def test_not_ready_before_observations(self) -> None:
        gate = WarmupGate(feature_name="f", required_observations=3)
        assert gate.is_ready is False

    def test_not_ready_while_below_threshold(self) -> None:
        gate = WarmupGate(feature_name="f", required_observations=3)
        gate.observe()
        gate.observe()
        assert gate.is_ready is False
        assert gate.observed == 2

    def test_ready_at_exactly_required(self) -> None:
        gate = WarmupGate(feature_name="f", required_observations=3)
        for _ in range(3):
            gate.observe()
        assert gate.is_ready is True

    def test_stays_ready_after_threshold(self) -> None:
        gate = WarmupGate(feature_name="f", required_observations=2)
        for _ in range(10):
            gate.observe()
        assert gate.is_ready is True
        assert gate.observed == 10
