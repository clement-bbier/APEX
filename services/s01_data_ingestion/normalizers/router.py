"""Normalizer dispatcher for (connector, data_type) pairs.

Routes incoming raw data to the appropriate :class:`NormalizerStrategy`
registered for the given connector/data_type combination.
"""

from __future__ import annotations

from typing import Any

from core.models.data import Asset
from services.s01_data_ingestion.normalizers.base import NormalizerStrategy


class NormalizerRouter:
    """Dispatches (connector, data_type) to the registered NormalizerStrategy."""

    def __init__(self) -> None:
        self._registry: dict[tuple[str, str], NormalizerStrategy[Any, Any]] = {}

    def register(
        self,
        connector: str,
        data_type: str,
        normalizer: NormalizerStrategy[Any, Any],
    ) -> None:
        """Register a normalizer for a (connector, data_type) pair."""
        self._registry[(connector, data_type)] = normalizer

    def get(self, connector: str, data_type: str) -> NormalizerStrategy[Any, Any]:
        """Return the normalizer for a (connector, data_type) pair.

        Raises:
            KeyError: If no normalizer is registered for the pair.
        """
        key = (connector, data_type)
        if key not in self._registry:
            raise KeyError(f"No normalizer registered for {key}")
        return self._registry[key]

    def normalize(self, connector: str, data_type: str, raw: object, asset: Asset) -> object:
        """Normalize a single raw record via the registered strategy."""
        return self.get(connector, data_type).normalize(raw, asset)

    def normalize_batch(
        self, connector: str, data_type: str, raw_batch: list[object], asset: Asset
    ) -> list[object]:
        """Normalize a batch of raw records via the registered strategy."""
        return self.get(connector, data_type).normalize_batch(raw_batch, asset)
