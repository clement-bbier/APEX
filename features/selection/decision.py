"""SelectionDecision — final keep/reject verdict for a single feature.

Aggregates evidence from Phase 3.3 (IC), 3.9 (multicollinearity),
and 3.11 (DSR/PBO/MHT) into a single publishable verdict per feature.

Named ``SelectionDecision`` (not ``FeatureDecision``) to avoid
collision with :class:`features.hypothesis.report.FeatureDecision`
which captures the hypothesis-testing layer only.

Reference
---------
Harvey, C. R., Liu, Y. & Zhu, H. (2016). "…and the Cross-Section
of Expected Returns." *Review of Financial Studies*, 29(1), 5-68.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class SelectionDecision:
    """Final keep/reject decision for a single candidate feature.

    Aggregates evidence from Phase 3.3 (IC), 3.9 (multicollinearity),
    and 3.11 (DSR/PBO/MHT) into a single publishable verdict.

    Reference: Harvey, Liu & Zhu (2016). Review of Financial Studies.
    """

    feature_name: str
    calculator: str

    decision: Literal["keep", "reject"]

    # Evidence — IC layer (Phase 3.3)
    ic_mean: float
    ic_ir: float
    ic_turnover_adj: float | None
    ic_p_value: float

    # Evidence — Multicollinearity layer (Phase 3.9)
    vif: float | None
    cluster_id: int | None
    is_cluster_keeper: bool | None

    # Evidence — Hypothesis Testing layer (Phase 3.11)
    sharpe_ratio: float | None
    psr: float | None
    dsr: float | None
    min_trl: int | None
    p_value_holm: float | None

    # Evidence — PBO (final feature set, aggregate)
    pbo_of_final_set: float | None

    # Reasoning
    reject_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict.

        All values are JSON-native types (no numpy, no datetime).
        """
        return {
            "feature_name": self.feature_name,
            "calculator": self.calculator,
            "decision": self.decision,
            "ic_mean": self.ic_mean,
            "ic_ir": self.ic_ir,
            "ic_turnover_adj": self.ic_turnover_adj,
            "ic_p_value": self.ic_p_value,
            "vif": self.vif,
            "cluster_id": self.cluster_id,
            "is_cluster_keeper": self.is_cluster_keeper,
            "sharpe_ratio": self.sharpe_ratio,
            "psr": self.psr,
            "dsr": self.dsr,
            "min_trl": self.min_trl,
            "p_value_holm": self.p_value_holm,
            "pbo_of_final_set": self.pbo_of_final_set,
            "reject_reasons": list(self.reject_reasons),
        }
