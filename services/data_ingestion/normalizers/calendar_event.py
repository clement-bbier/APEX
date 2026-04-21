"""Calendar / economic event normalizer stub.

Implemented in Phase 2.8.
"""

from __future__ import annotations

from typing import Any

from core.models.data import Asset, EconomicEvent
from services.data_ingestion.normalizers.base import NormalizerStrategy


class CalendarEventNormalizer(NormalizerStrategy[dict[str, Any], EconomicEvent]):
    """Normalizes calendar event data. Implemented in Phase 2.8."""

    def normalize(self, raw: dict[str, Any], asset: Asset) -> EconomicEvent:
        """Not yet implemented."""
        raise NotImplementedError("CalendarEventNormalizer: implemented in Phase 2.8")
