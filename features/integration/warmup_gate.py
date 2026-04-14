"""Per-feature warmup tracking.

Each Phase 3 calculator carries a different warmup requirement
(HAR-RV 23 daily bars, Kyle 60 ticks, etc.). The :class:`WarmupGate`
encapsulates the "have I seen enough observations yet?" question so
that :class:`features.integration.s02_adapter.S02FeatureAdapter` does
not have to re-implement counting logic for every feature.

The gate is stateful but trivially small: one counter, one threshold.
It is a helper, not a service -- no I/O, no logging.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WarmupGate:
    """Tracks observations for a single feature and exposes readiness.

    Attributes:
        feature_name: Feature the gate is protecting (for diagnostics).
        required_observations: Number of observations that must be fed
            through :meth:`observe` before :attr:`is_ready` returns
            ``True``.
    """

    feature_name: str
    required_observations: int
    _observed: int = 0

    def __post_init__(self) -> None:
        if self.required_observations < 1:
            raise ValueError(
                f"required_observations must be >= 1, got {self.required_observations}"
            )

    def observe(self) -> None:
        """Record that one more observation has been fed to the calculator."""
        self._observed += 1

    @property
    def observed(self) -> int:
        """Current observation count (read-only view)."""
        return self._observed

    @property
    def is_ready(self) -> bool:
        """True once ``observed >= required_observations``."""
        return self._observed >= self.required_observations
