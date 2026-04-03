"""Economic surprise index for APEX Trading System."""

from __future__ import annotations
from typing import Any


class SurpriseIndex:
    """Computes economic data surprise scores and regime adjustments."""

    def compute_surprise(
        self,
        actual: float,
        consensus: float,
        historical_std: float,
    ) -> float:
        """Compute a standardised economic surprise score.

        surprise = (actual - consensus) / historical_std

        Args:
            actual: Reported economic data value.
            consensus: Consensus (expected) estimate.
            historical_std: Historical standard deviation of the data series.

        Returns:
            Standardised surprise score. Returns 0.0 if historical_std is zero.
        """
        if historical_std == 0.0:
            return 0.0
        return (actual - consensus) / historical_std

    def regime_adjustment(self, surprise_score: float) -> float:
        """Return a regime multiplier based on the magnitude of the surprise.

        Args:
            surprise_score: Standardised surprise score from compute_surprise().

        Returns:
            Multiplier: 0.5 if |score| > 2, 0.75 if |score| > 1, else 1.0.
        """
        abs_score = abs(surprise_score)
        if abs_score > 2.0:
            return 0.5
        if abs_score > 1.0:
            return 0.75
        return 1.0

    async def get_latest_economic_data(self) -> dict[str, Any]:
        """Retrieve the latest economic release data.

        Returns:
            Empty dict[str, Any] (stub). TODO Phase 2: integrate FRED releases API.
        """
        # TODO Phase 2: Integrate FRED releases API for live economic data
        return {}
