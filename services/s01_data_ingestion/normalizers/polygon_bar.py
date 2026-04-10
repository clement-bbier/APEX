"""Polygon.io bar normalizer stub.

Implemented in Phase 2.5.
"""

from __future__ import annotations

from typing import Any

from core.models.data import Asset, Bar
from services.s01_data_ingestion.normalizers.base import NormalizerStrategy


class PolygonBarNormalizer(NormalizerStrategy[dict[str, Any], Bar]):
    """Normalizes Polygon.io bar data. Implemented in Phase 2.5."""

    def normalize(self, raw: dict[str, Any], asset: Asset) -> Bar:
        """Not yet implemented."""
        raise NotImplementedError("PolygonBarNormalizer: implemented in Phase 2.5")
