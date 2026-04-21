"""Abstract base for all APEX normalizer strategies.

Implements the Strategy pattern (Gamma et al. 1994) for asset-agnostic
data normalization.  Each concrete normalizer transforms a raw record
type ``T_Raw`` into a typed output ``T_Out``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models.data import Asset


class NormalizerStrategy[T_Raw, T_Out](ABC):
    """Base strategy for normalizing raw market data into typed output."""

    @abstractmethod
    def normalize(self, raw: T_Raw, asset: Asset) -> T_Out:
        """Transform a single raw record into normalized format."""
        ...

    def normalize_batch(self, raw_batch: list[T_Raw], asset: Asset) -> list[T_Out]:
        """Transform a batch. Override for performance-critical paths."""
        return [self.normalize(r, asset) for r in raw_batch]
