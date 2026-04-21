"""Economic Surprise Index.

Tracks actual vs consensus for key macro releases:
  - NFP (Non-Farm Payrolls) — first Friday of month, 08:30 ET
  - CPI (Consumer Price Index) — mid-month, 08:30 ET
  - GDP — quarterly
  - ISM PMI — monthly

Surprise = (Actual - Consensus) / |Consensus|

Positive surprise (actual > consensus) → risk-on boost
Negative surprise → risk-off, reduce macro_mult
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class EconRelease:
    """One economic data release with consensus vs actual."""

    name: str
    released_at: datetime
    consensus: float
    actual: float
    surprise_pct: float  # (actual - consensus) / abs(consensus)
    impact: str  # "high" | "medium" | "low"


class SurpriseIndexEngine:
    """Computes economic surprise contribution to macro_mult.

    A positive surprise (better than expected) → mult > 1.0
    A negative surprise → mult < 1.0
    The effect decays over 24 hours.
    """

    def compute_surprise(self, consensus: float, actual: float) -> float:
        """Surprise as fraction: 0.1 = 10% beat, -0.1 = 10% miss.

        Args:
            consensus: Expected value from economists.
            actual: Released actual value.

        Returns:
            Normalized surprise in [-∞, +∞] (typically ≈ [-1.0, +1.0]).
        """
        if consensus == 0:
            return 0.0
        return (actual - consensus) / abs(consensus)

    def compute_mult_adjustment(
        self,
        surprise_pct: float,
        impact: str,
        hours_since_release: float,
    ) -> float:
        """Compute macro_mult adjustment from one release.

        Args:
            surprise_pct: Normalized surprise [-1.0, +1.0]
            impact: "high" | "medium" | "low"
            hours_since_release: How long ago the release happened

        Returns:
            Multiplier adjustment [0.5, 1.5] — applied additively to macro_mult
        """
        # Decay: full effect for 2h, linear decay to 0 over 24h
        if hours_since_release >= 24:
            return 1.0  # no effect after 24h

        decay = max(0.0, 1.0 - (hours_since_release - 2.0) / 22.0)
        decay = min(1.0, decay)

        # Impact weight
        weight = {"high": 0.3, "medium": 0.15, "low": 0.05}.get(impact, 0.1)

        # Adjustment: surprise_pct = +0.10 (10% beat) → +0.03 mult for high impact
        adjustment = surprise_pct * weight * decay

        return 1.0 + adjustment  # 1.0 = neutral, 1.3 = very positive surprise

    async def get_latest_economic_data(self) -> dict[str, Any]:
        """Retrieve the latest economic release data.

        Returns:
            Empty dict (Phase 3 will integrate FRED releases API).
        """
        # Phase 3: Integrate FRED releases API for live economic data
        return {}

    def build_release(
        self,
        name: str,
        consensus: float,
        actual: float,
        impact: str,
        released_at: datetime | None = None,
    ) -> EconRelease:
        """Construct an EconRelease with computed surprise_pct.

        Args:
            name: Release name (e.g. "NFP", "CPI").
            consensus: Expected value.
            actual: Reported value.
            impact: "high" | "medium" | "low".
            released_at: Release timestamp (defaults to now UTC).

        Returns:
            Fully populated EconRelease.
        """
        if released_at is None:
            released_at = datetime.now(UTC)
        return EconRelease(
            name=name,
            released_at=released_at,
            consensus=consensus,
            actual=actual,
            surprise_pct=self.compute_surprise(consensus, actual),
            impact=impact,
        )
