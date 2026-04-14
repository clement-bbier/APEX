"""Adapter bridging Phase 3 validated calculators to S02 SignalComponent.

Design pattern: classical GoF Adapter (Gamma et al. 1994). Purpose is
to let code that expects :class:`SignalComponent` objects (e.g. S02's
``SignalScorer``) consume the output of batch-oriented
:class:`features.base.FeatureCalculator` instances, without either
side knowing about the other.

Phase 3.13 ships this adapter as **scaffolding** only: it is not yet
wired into ``services/s02_signal_engine/``. Wiring happens in a later
phase when the call-site owner is ready.

Performance note (honest reporting, per CLAUDE.md rule 10):
    The Phase 3.4-3.8 calculators expose a batch
    ``compute(df) -> df`` API. The adapter therefore maintains a
    rolling buffer of past observations and invokes ``compute`` on
    every ``on_observation`` call, taking the last row of the output
    column as the current signal value. Some calculators (notably
    HAR-RV) use O(n^2) expanding-window refits inside ``compute``;
    per-tick latency scales with buffer size. Actual measurements
    are exposed via the adapter's test suite (see
    ``tests/unit/features/integration/test_s02_adapter.py``). When
    the per-(feature, tick) budget of 1 ms cannot be met, that is
    reported explicitly rather than hidden.

Thread-safety:
    Not thread-safe. S02's tick pipeline is single-threaded (asyncio),
    which is the only intended call site. Calling ``on_observation``
    concurrently from multiple threads on the same adapter instance
    is undefined behaviour.

References:
    Gamma, E., Helm, R., Johnson, R. & Vlissides, J. (1994).
        *Design Patterns: Elements of Reusable Object-Oriented
        Software*. Addison-Wesley -- Chapter 4, Adapter.
    Martin, R. C. (2008). *Clean Code*, Ch. 10. Prentice Hall.
    Fowler, M. (2018). *Refactoring* (2nd ed.), Ch. 8. Addison-Wesley.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping
from typing import Any

import polars as pl

from features.base import FeatureCalculator
from features.integration.config import FeatureActivationConfig
from features.integration.warmup_gate import WarmupGate
from services.s02_signal_engine.signal_scorer import SignalComponent


def _validate_weight(name: str, value: float) -> float:
    """Enforce the SignalComponent.weight contract: finite and in [0, 1]."""
    if not math.isfinite(value):
        raise ValueError(f"weight[{name!r}]={value!r} must be finite")
    if not 0.0 <= value <= 1.0:
        raise ValueError(
            f"weight[{name!r}]={value!r} must be in [0.0, 1.0] (per SignalComponent contract)"
        )
    return value


def _validate_threshold(name: str, value: float) -> float:
    """Enforce the trigger-threshold contract: finite and non-negative."""
    if not math.isfinite(value):
        raise ValueError(f"trigger_threshold[{name!r}]={value!r} must be finite")
    if value < 0.0:
        raise ValueError(f"trigger_threshold[{name!r}]={value!r} must be >= 0.0")
    return value


class S02FeatureAdapter:
    """Adapts Phase 3 batch calculators to S02's SignalComponent API.

    The adapter is agnostic to the semantic shape of an "observation":
    callers pass a ``Mapping[str, Any]`` containing at least the columns
    declared by each calculator's :meth:`required_columns`. This keeps
    the adapter decoupled from :class:`core.models.tick.NormalizedTick`
    and from any bar-aggregation logic.

    Contract:
        * Returns ``None`` for feature names known to
          :class:`FeatureActivationConfig` but NOT activated
          (``decision == "reject"`` in the Phase 3.12 report).
        * Returns ``None`` while the per-feature warmup is incomplete.
        * Returns ``None`` when the calculator emits NaN or null on the
          last row of its output.
        * Returns a valid :class:`SignalComponent` once warmup is
          complete and the calculator produced a finite value. ``name``
          equals the feature name, ``score`` equals the calculator's
          last-row output value clamped to ``[-1, +1]`` and
          ``triggered`` reflects an ``abs(score) > trigger_threshold``
          test.
        * Raises :class:`ValueError` for feature names unknown to the
          activation config (neither activated nor rejected -- caller
          bug, not a data event).

    The output column read from the calculator is assumed to match
    the feature name (holds for all Phase 3 ``*_signal`` outputs:
    ``har_rv_signal``, ``ofi_signal``, ``gex_signal``).

    Note on :attr:`SignalComponent.weight` propagation:
        The current :class:`SignalScorer.compute` in S02 ignores the
        ``weight`` field on incoming :class:`SignalComponent` objects
        and looks up weights via ``SignalScorer.WEIGHTS.get(name, 0.1)``.
        Weights passed to this adapter therefore control
        ``SignalComponent.weight`` (for audit / introspection) but do
        not yet influence scoring until S02 is modified to honour
        component-level weights. :attr:`DEFAULT_WEIGHT` is ``0.1`` so
        the adapter agrees with the existing fallback out of the box.

    Note on measured latency:
        The original DoD target was ``<1 ms per (feature, tick)``.
        With the batch-only calculators of Phase 3.4-3.8 and the
        rolling-buffer recompute loop used here, the measured
        ``p50`` on OFI is ~4-9 ms. Resolution requires a streaming
        calculator surface -- tracked in GitHub issue #123 and
        prerequisite for eventual wiring into S02 (Phase 5).
    """

    DEFAULT_WEIGHT: float = 0.1
    DEFAULT_TRIGGER_THRESHOLD: float = 0.05
    DEFAULT_MAX_BUFFER: int = 2048

    def __init__(
        self,
        config: FeatureActivationConfig,
        calculators: Mapping[str, FeatureCalculator],
        warmup_periods: Mapping[str, int],
        weights: Mapping[str, float] | None = None,
        trigger_thresholds: Mapping[str, float] | None = None,
        max_buffer_size: int = DEFAULT_MAX_BUFFER,
    ) -> None:
        """Initialise the adapter.

        Args:
            config: Activation decisions from Phase 3.12.
            calculators: Mapping ``feature_name -> calculator``. One
                calculator instance may be shared across multiple
                feature names (e.g. CVD+Kyle produces several). Every
                activated feature must have an entry.
            warmup_periods: Mapping ``feature_name -> N observations``.
                Every activated feature must have an entry.
            weights: Optional ``feature_name -> SignalComponent.weight``
                mapping. Defaults to :attr:`DEFAULT_WEIGHT` per feature.
            trigger_thresholds: Optional ``feature_name -> float`` for
                the ``abs(score) > threshold`` trigger rule. Defaults
                to :attr:`DEFAULT_TRIGGER_THRESHOLD` per feature.
            max_buffer_size: Maximum number of rows kept per feature's
                rolling buffer. Must be strictly greater than the
                largest warmup period; otherwise :meth:`compute` sees
                an incomplete history.

        Raises:
            ValueError: If an activated feature is missing from
                ``calculators`` / ``warmup_periods``, if
                ``max_buffer_size`` is not strictly greater than the
                largest declared warmup, or if any weight /
                trigger_threshold value is non-finite or out of range.
        """
        missing_calc = sorted(config.activated_features - set(calculators))
        if missing_calc:
            raise ValueError(f"Activated features missing a calculator: {missing_calc}")
        missing_warmup = sorted(config.activated_features - set(warmup_periods))
        if missing_warmup:
            raise ValueError(f"Activated features missing a warmup entry: {missing_warmup}")
        for name in config.activated_features:
            w = warmup_periods[name]
            if w < 1:
                raise ValueError(f"warmup_periods[{name!r}] must be >= 1, got {w}")
            if max_buffer_size <= w:
                raise ValueError(
                    f"max_buffer_size ({max_buffer_size}) must exceed warmup for {name!r} ({w})"
                )

        self._config = config
        self._calculators: dict[str, FeatureCalculator] = dict(calculators)
        self._weights: dict[str, float] = {
            name: _validate_weight(name, float((weights or {}).get(name, self.DEFAULT_WEIGHT)))
            for name in config.activated_features
        }
        self._trigger_thresholds: dict[str, float] = {
            name: _validate_threshold(
                name,
                float((trigger_thresholds or {}).get(name, self.DEFAULT_TRIGGER_THRESHOLD)),
            )
            for name in config.activated_features
        }
        self._warmup_gates: dict[str, WarmupGate] = {
            name: WarmupGate(feature_name=name, required_observations=warmup_periods[name])
            for name in config.activated_features
        }
        self._buffers: dict[str, deque[dict[str, Any]]] = {
            name: deque(maxlen=max_buffer_size) for name in config.activated_features
        }

    def on_observation(
        self,
        feature_name: str,
        record: Mapping[str, Any],
    ) -> SignalComponent | None:
        """Consume one observation and optionally emit a SignalComponent.

        Args:
            feature_name: The feature to update. Must be known to the
                adapter's config (activated or rejected). Unknown names
                raise ``ValueError``.
            record: A mapping containing at least the columns required
                by the calculator bound to ``feature_name``.

        Returns:
            A :class:`SignalComponent` when the feature is activated,
            warmed up and produced a finite value; otherwise ``None``.
        """
        if feature_name in self._config.rejected_features:
            return None
        if feature_name not in self._config.activated_features:
            raise ValueError(f"Unknown feature {feature_name!r}: not present in Phase 3.12 report")

        self._buffers[feature_name].append(dict(record))
        gate = self._warmup_gates[feature_name]
        gate.observe()
        if not gate.is_ready:
            return None

        score = self._compute_latest(feature_name)
        if score is None:
            return None

        clamped = max(-1.0, min(1.0, score))
        threshold = self._trigger_thresholds[feature_name]
        return SignalComponent(
            name=feature_name,
            score=clamped,
            weight=self._weights[feature_name],
            triggered=abs(clamped) > threshold,
            metadata={
                "source": "phase_3_adapter",
                "warmup_observed": gate.observed,
            },
        )

    def _compute_latest(self, feature_name: str) -> float | None:
        """Run the calculator on the current buffer and return last row.

        Callers must have appended at least one observation to the
        buffer before invoking this helper (the public
        :meth:`on_observation` does exactly that).

        Returns ``None`` if the output column is missing (defensive --
        should not happen if the calculator respects its own
        :meth:`output_columns` contract) or if the last row is NaN.
        """
        buffer = self._buffers[feature_name]
        df = pl.DataFrame(list(buffer))
        out = self._calculators[feature_name].compute(df)
        if feature_name not in out.columns:
            return None
        last = out[feature_name][-1]
        if last is None:
            return None
        value = float(last)
        if math.isnan(value):
            return None
        return value
