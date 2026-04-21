"""Interactive Brokers bar normalizer stub.

Implemented in Phase 2.6.
"""

from __future__ import annotations

from typing import Any

from core.models.data import Asset, Bar
from services.data_ingestion.normalizers.base import NormalizerStrategy


class IBKRBarNormalizer(NormalizerStrategy[dict[str, Any], Bar]):
    """Normalizes IBKR bar data. Implemented in Phase 2.6."""

    def normalize(self, raw: dict[str, Any], asset: Asset) -> Bar:
        """Not yet implemented."""
        raise NotImplementedError("IBKRBarNormalizer: implemented in Phase 2.6")
