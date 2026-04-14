"""Phase 3.13 -- Integration of validated features with S02 Signal Engine.

Scaffolding only: the :class:`S02FeatureAdapter` is implemented and
tested end-to-end but NOT yet wired into ``services/s02_signal_engine/``.
Wiring is deferred to a later phase (Phase 5 or an explicit decision
point) so that S02's live pipeline remains untouched while Phase 4
(Fusion + Meta-Labeler) is built on top of Phase 3 outputs.

Design references:
    - Gamma, Helm, Johnson, Vlissides (1994). *Design Patterns*.
      Addison-Wesley -- Adapter.
    - Martin, R. C. (2008). *Clean Code*, Ch. 10 -- Classes / SRP.
    - Fowler, M. (2018). *Refactoring* (2nd ed.), Ch. 8. Addison-Wesley.
"""

from features.integration.config import FeatureActivationConfig
from features.integration.s02_adapter import S02FeatureAdapter
from features.integration.warmup_gate import WarmupGate

__all__ = [
    "FeatureActivationConfig",
    "S02FeatureAdapter",
    "WarmupGate",
]
