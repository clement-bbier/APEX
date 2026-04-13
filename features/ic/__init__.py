"""IC Measurement sub-package — Information Coefficient framework.

Phase 3.3 provides:
- :class:`ICMetric` ABC and :class:`ICResult` dataclass (from 3.1)
- :class:`SpearmanICMeasurer` concrete implementation
- :class:`ICReport` structured report (JSON + Markdown)
- :func:`compute_forward_returns` target-return helper
- Pure statistical functions in :mod:`features.ic.stats`
"""

from features.ic.base import ICMetric, ICResult
from features.ic.forward_returns import compute_forward_returns
from features.ic.measurer import SpearmanICMeasurer
from features.ic.report import ICReport

__all__ = [
    "ICMetric",
    "ICReport",
    "ICResult",
    "SpearmanICMeasurer",
    "compute_forward_returns",
]
