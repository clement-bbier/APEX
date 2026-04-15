"""Phase 4.7 — IC-weighted fusion engine (library-level MVP).

See ``ic_weighted.py`` for the public API. This package is strictly
additive: it does not modify ``services/s04_fusion_engine/``. Wiring
into the streaming S04 service is Phase 5 work (issue #123).

References:
    ADR-0005 D7 (Fusion Engine: IC-weighted baseline).
    PHASE_4_SPEC §3.7.
"""

from __future__ import annotations

from features.fusion.ic_weighted import ICWeightedFusion, ICWeightedFusionConfig

__all__ = ["ICWeightedFusion", "ICWeightedFusionConfig"]
