"""Phase 3.12 — Feature Selection Report.

Aggregates IC (Phase 3.3), multicollinearity (Phase 3.9), and hypothesis
testing (Phase 3.11) evidence into final keep/reject decisions per
candidate feature.  No new metrics — consumes existing reports.

Cherry-picking protection: every candidate feature appears in the output,
even rejected ones, with explicit reject reasons.

Reference
---------
- Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio Management*
  (2nd ed.). McGraw-Hill, Ch. 14.
- Harvey, C. R., Liu, Y. & Zhu, H. (2016). "…and the Cross-Section of
  Expected Returns." *Review of Financial Studies*, 29(1), 5-68.
"""

from features.selection.decision import SelectionDecision
from features.selection.report_generator import (
    FeatureSelectionReport,
    FeatureSelectionReportGenerator,
)

__all__ = [
    "FeatureSelectionReport",
    "FeatureSelectionReportGenerator",
    "SelectionDecision",
]
