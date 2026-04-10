"""FRED macroeconomic data normalizer stub.

Implemented in Phase 2.7.
"""

from __future__ import annotations

from typing import Any

from core.models.data import Asset, MacroPoint
from services.s01_data_ingestion.normalizers.base import NormalizerStrategy


class FREDMacroNormalizer(NormalizerStrategy[dict[str, Any], MacroPoint]):
    """Normalizes FRED macro data. Implemented in Phase 2.7."""

    def normalize(self, raw: dict[str, Any], asset: Asset) -> MacroPoint:
        """Not yet implemented."""
        raise NotImplementedError("FREDMacroNormalizer: implemented in Phase 2.7")
