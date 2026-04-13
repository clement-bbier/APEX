"""Feature calculators — concrete alpha features for APEX.

Starting from Phase 3.4, each sub-phase adds a FeatureCalculator
implementation that wraps an existing S07/S02 estimator with
look-ahead-safe refit logic and signal normalization.

Reference:
    PHASE_3_SPEC §2.4-2.8.
"""

from features.calculators.cvd_kyle import CVDKyleCalculator
from features.calculators.har_rv import HARRVCalculator
from features.calculators.ofi import OFICalculator
from features.calculators.rough_vol import RoughVolCalculator

__all__ = [
    "CVDKyleCalculator",
    "HARRVCalculator",
    "OFICalculator",
    "RoughVolCalculator",
]
