"""FeatureSelectionReportGenerator — Phase 3.12 aggregate report.

Combines IC (Phase 3.3), multicollinearity (Phase 3.9), and hypothesis
testing (Phase 3.11) evidence into final keep/reject decisions per
candidate feature.

Cherry-picking protection (Harvey-Liu-Zhu 2016): **every** candidate
feature present in ``ic_report.results`` gets a :class:`SelectionDecision`,
even if absent from multicollinearity or hypothesis reports.  Missing
evidence is an explicit reject reason, never a silent pass.

Decision gates (configurable, defaults from ADR-0004):
- ``|IC| >= ic_min`` (0.02)
- ``IC_IR >= ic_ir_min`` (0.50)
- ``ic_p_value <= ic_p_max`` (0.05, raw — MHT applied separately)
- ``VIF <= vif_max`` (5.0)
- ``is_cluster_keeper == True`` (if cluster member)
- ``DSR >= dsr_min`` (0.95)
- ``PSR >= psr_min`` (0.90)
- ``p_value_holm <= alpha`` (0.05) if multi-feature run
- ``PBO of final set <= pbo_max`` (0.10)

Reference
---------
- Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio Management*
  (2nd ed.). McGraw-Hill, Ch. 14.
- Harvey, C. R., Liu, Y. & Zhu, H. (2016). "…and the Cross-Section of
  Expected Returns." *Review of Financial Studies*, 29(1), 5-68.
- Bailey, D. H. & López de Prado, M. (2014). "The Deflated Sharpe
  Ratio." *JPM*, 40(5), 94-107.
- Bailey, D. H., Borwein, J. M., López de Prado, M. & Zhu, Q. J.
  (2014). "Probability of Backtest Overfitting." *JCF*.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from features.hypothesis.report import (
    FeatureDecision as HypothesisFeatureDecision,
)
from features.hypothesis.report import (
    HypothesisTestingReport,
)
from features.ic.report import ICReport
from features.multicollinearity import MulticollinearityReport
from features.selection.decision import SelectionDecision

# Map feature names to calculator names.  Extensible via constructor.
_DEFAULT_CALCULATOR_MAP: dict[str, str] = {
    "har_rv_signal": "HAR-RV",
    "rough_hurst": "Rough Vol",
    "rough_vol_signal": "Rough Vol",
    "ofi_signal": "OFI",
    "cvd_signal": "CVD+Kyle",
    "combined_signal": "CVD+Kyle",
    "liquidity_signal": "CVD+Kyle",
    "gex_signal": "GEX",
}


class FeatureSelectionReportGenerator:
    """Aggregates IC / multicollinearity / hypothesis testing evidence
    into final keep/reject decisions with full audit trail.

    Enforces: all candidate features appear in output, even rejected ones
    (no cherry-picking per Harvey-Liu-Zhu 2016).

    Reference: Grinold & Kahn (1999), Harvey-Liu-Zhu (2016).
    """

    def __init__(
        self,
        *,
        ic_min: float = 0.02,
        ic_ir_min: float = 0.50,
        ic_p_max: float = 0.05,
        vif_max: float = 5.0,
        dsr_min: float = 0.95,
        psr_min: float = 0.90,
        alpha: float = 0.05,
        pbo_max: float = 0.10,
        calculator_map: dict[str, str] | None = None,
    ) -> None:
        # D030-style validation: thresholds in sensible ranges
        if not 0.0 < ic_min < 1.0:
            raise ValueError(f"ic_min must be in (0, 1), got {ic_min}")
        if not 0.0 < ic_ir_min < 10.0:
            raise ValueError(f"ic_ir_min must be in (0, 10), got {ic_ir_min}")
        if not 0.0 < ic_p_max <= 1.0:
            raise ValueError(f"ic_p_max must be in (0, 1], got {ic_p_max}")
        if vif_max <= 1.0:
            raise ValueError(f"vif_max must be > 1.0, got {vif_max}")
        if not 0.0 < dsr_min < 1.0:
            raise ValueError(f"dsr_min must be in (0, 1), got {dsr_min}")
        if not 0.0 < psr_min < 1.0:
            raise ValueError(f"psr_min must be in (0, 1), got {psr_min}")
        if not 0.0 < alpha <= 1.0:
            raise ValueError(f"alpha must be in (0, 1], got {alpha}")
        if not 0.0 < pbo_max < 1.0:
            raise ValueError(f"pbo_max must be in (0, 1), got {pbo_max}")

        self._ic_min = ic_min
        self._ic_ir_min = ic_ir_min
        self._ic_p_max = ic_p_max
        self._vif_max = vif_max
        self._dsr_min = dsr_min
        self._psr_min = psr_min
        self._alpha = alpha
        self._pbo_max = pbo_max
        # Explicit None check — ``{}`` is a legitimate input (force every
        # feature to "unknown" calculator) and must not trigger the default.
        # Defensive copy prevents external mutation from affecting the generator.
        if calculator_map is None:
            self._calculator_map = dict(_DEFAULT_CALCULATOR_MAP)
        else:
            self._calculator_map = dict(calculator_map)

    def generate(
        self,
        *,
        ic_report: ICReport,
        multicoll_report: MulticollinearityReport | None = None,
        hypothesis_report: HypothesisTestingReport | None = None,
    ) -> FeatureSelectionReport:
        """Combine three Phase 3 reports into final keep/reject verdicts.

        Every feature present in ``ic_report.results`` gets a
        :class:`SelectionDecision`, even if absent from multicoll or
        hypothesis reports (those gates are explicit reject reasons,
        not silent passes).

        Parameters
        ----------
        ic_report:
            Phase 3.3 IC measurement results.
        multicoll_report:
            Phase 3.9 multicollinearity analysis.  ``None`` if not run.
        hypothesis_report:
            Phase 3.11 DSR/PBO/MHT results.  ``None`` if not run.
        """
        # Build lookup dicts for multicoll and hypothesis
        vif_map: dict[str, float] = {}
        cluster_map: dict[str, int] = {}
        drops_set: set[str] = set()
        if multicoll_report is not None:
            vif_map = dict(multicoll_report.vif_scores)
            cluster_map = dict(multicoll_report.cluster_assignments)
            drops_set = set(multicoll_report.recommended_drops)

        hyp_map: dict[str, HypothesisFeatureDecision] = {}
        if hypothesis_report is not None:
            for fd in hypothesis_report.feature_decisions:
                hyp_map[fd.feature_name] = fd

        # MHT requirement: if the hypothesis report claims Holm/BH correction
        # was applied across multiple features, then every feature MUST carry
        # a non-None ``p_value_holm``.  A missing p_holm in that configuration
        # is a data gap — reject explicitly, never silent-skip the gate.
        # Same anti-pattern family as PR #120 build_report silent skip.
        mht_required = (
            hypothesis_report is not None
            and hypothesis_report.mht_correction != "none"
            and len(hyp_map) > 1
        )

        pbo_value: float | None = None
        if hypothesis_report is not None and hypothesis_report.pbo_result is not None:
            pbo_value = hypothesis_report.pbo_result.pbo

        decisions: list[SelectionDecision] = []

        for ic_index, ic_result in enumerate(ic_report.results):
            raw_name = ic_result.feature_name
            has_feature_name = bool(raw_name)
            feature_name: str = raw_name if raw_name else f"unknown_{ic_index}"
            calculator = self._calculator_map.get(feature_name, "unknown")

            reject_reasons: list[str] = []
            if not has_feature_name:
                reject_reasons.append("feature_name_missing")

            # ── IC gates ─────────────────────────────────────────────
            if abs(ic_result.ic) < self._ic_min:
                reject_reasons.append(f"ic_mean={ic_result.ic:.4f} < {self._ic_min}")
            if ic_result.ic_ir < self._ic_ir_min:
                reject_reasons.append(f"ic_ir={ic_result.ic_ir:.3f} < {self._ic_ir_min}")
            if ic_result.p_value > self._ic_p_max:
                reject_reasons.append(f"ic_p_value={ic_result.p_value:.4f} > {self._ic_p_max}")

            # ── Multicollinearity gates ──────────────────────────────
            vif: float | None = None
            cluster_id: int | None = None
            is_cluster_keeper: bool | None = None

            if multicoll_report is None:
                reject_reasons.append("vif_not_computed")
            elif feature_name not in vif_map:
                reject_reasons.append("vif_not_computed")
            else:
                vif = vif_map[feature_name]
                cluster_id = cluster_map.get(feature_name)
                is_in_drops = feature_name in drops_set
                is_cluster_keeper = not is_in_drops

                if vif > self._vif_max:
                    reject_reasons.append(f"vif={vif:.2f} > {self._vif_max}")
                if is_in_drops:
                    reject_reasons.append("cluster_dropped_by_ic_ranking")

            # ── Hypothesis testing gates ─────────────────────────────
            sharpe: float | None = None
            psr: float | None = None
            dsr: float | None = None
            min_trl: int | None = None
            p_holm: float | None = None

            if hypothesis_report is None:
                reject_reasons.append("dsr_not_computed")
            elif feature_name not in hyp_map:
                reject_reasons.append("dsr_not_computed")
            else:
                fd_hyp = hyp_map[feature_name]
                sharpe = fd_hyp.sharpe_raw
                psr = fd_hyp.psr
                dsr = fd_hyp.dsr
                min_trl = fd_hyp.min_trl
                p_holm = fd_hyp.p_value_holm

                if dsr < self._dsr_min:
                    reject_reasons.append(f"dsr={dsr:.3f} < {self._dsr_min}")
                if psr < self._psr_min:
                    reject_reasons.append(f"psr={psr:.3f} < {self._psr_min}")

                # Holm-adjusted p-value gate:
                # - If MHT was declared but p_holm is None → explicit reject
                #   (missing evidence is not a free pass).
                # - If MHT not required (single-feature or correction="none"),
                #   None legitimately skips the gate.
                if p_holm is None:
                    if mht_required:
                        reject_reasons.append("p_value_holm_missing_when_mht_required")
                elif p_holm > self._alpha:
                    reject_reasons.append(f"p_value_holm={p_holm:.4f} > {self._alpha}")

            # ── PBO gate (aggregate, applies to all) ─────────────────
            if pbo_value is not None and pbo_value > self._pbo_max:
                reject_reasons.append(f"pbo={pbo_value:.3f} > {self._pbo_max}")

            decision_val: Literal["keep", "reject"] = "keep" if not reject_reasons else "reject"

            decisions.append(
                SelectionDecision(
                    feature_name=feature_name,
                    calculator=calculator,
                    decision=decision_val,
                    ic_mean=ic_result.ic,
                    ic_ir=ic_result.ic_ir,
                    ic_turnover_adj=ic_result.turnover_adj_ic,
                    ic_p_value=ic_result.p_value,
                    vif=vif,
                    cluster_id=cluster_id,
                    is_cluster_keeper=is_cluster_keeper,
                    sharpe_ratio=sharpe,
                    psr=psr,
                    dsr=dsr,
                    min_trl=min_trl,
                    p_value_holm=p_holm,
                    pbo_of_final_set=pbo_value,
                    reject_reasons=reject_reasons,
                )
            )

        # Sort: keep first, then by DSR descending (None treated as -inf)
        decisions.sort(
            key=lambda d: (
                0 if d.decision == "keep" else 1,
                -(d.dsr if d.dsr is not None else float("-inf")),
            )
        )

        n_kept = sum(1 for d in decisions if d.decision == "keep")

        return FeatureSelectionReport(
            decisions=decisions,
            pbo_of_final_set=pbo_value,
            n_candidates=len(decisions),
            n_kept=n_kept,
            n_rejected=len(decisions) - n_kept,
            generated_at=datetime.now(UTC),
            pbo_strict_threshold=self._pbo_max,
        )


def _round_floats(obj: object, ndigits: int = 6) -> object:
    """Recursively round floats in nested dict/list structures.

    Normalises float noise (``0.07200000000000001`` → ``0.072``) so that
    committed JSON artefacts produce clean diffs and the byte-level
    determinism guarantee survives arithmetic jitter.
    """
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, dict):
        return {k: _round_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(x, ndigits) for x in obj]
    return obj


@dataclass(frozen=True)
class FeatureSelectionReport:
    """Final Phase 3 feature selection report.

    Machine-parseable (JSON) and human-readable (Markdown).

    Reference: Harvey, Liu & Zhu (2016). Review of Financial Studies.
    """

    decisions: list[SelectionDecision]
    pbo_of_final_set: float | None
    n_candidates: int
    n_kept: int
    n_rejected: int
    generated_at: datetime
    pbo_strict_threshold: float

    def to_markdown(self) -> str:
        """Render the report as deterministic Markdown.

        Ordering: keep first, then by DSR descending.
        Same inputs → same bytes.
        """
        lines: list[str] = []
        ts = self.generated_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        lines.append("# Phase 3 Feature Selection Report")
        lines.append("")
        lines.append(f"Generated: {ts}")
        lines.append(f"Candidates: {self.n_candidates}")
        lines.append(f"Kept: {self.n_kept}")
        lines.append(f"Rejected: {self.n_rejected}")
        pbo_str = f"{self.pbo_of_final_set:.4f}" if self.pbo_of_final_set is not None else "N/A"
        lines.append(f"PBO of final set: {pbo_str}")
        lines.append("")

        # Decision summary table
        lines.append("## Decision summary")
        lines.append("")
        lines.append("| Feature | Calculator | Decision | DSR | VIF | IC_IR | p_holm | Reasons |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for d in self.decisions:
            dec_str = f"**{d.decision}**" if d.decision == "keep" else d.decision
            dsr_str = f"{d.dsr:.3f}" if d.dsr is not None else "N/A"
            vif_str = f"{d.vif:.2f}" if d.vif is not None else "N/A"
            ir_str = f"{d.ic_ir:.3f}"
            p_str = f"{d.p_value_holm:.4f}" if d.p_value_holm is not None else "N/A"
            reasons = "; ".join(d.reject_reasons) if d.reject_reasons else "—"
            lines.append(
                f"| {d.feature_name} | {d.calculator} | {dec_str} "
                f"| {dsr_str} | {vif_str} | {ir_str} | {p_str} | {reasons} |"
            )
        lines.append("")

        # Per-feature details
        lines.append("## Per-feature details")
        lines.append("")
        for d in self.decisions:
            label = d.decision.upper()
            lines.append(f"### {d.feature_name} ({label})")
            lines.append("")
            lines.append(f"- **Calculator**: {d.calculator}")

            adj_str = f"{d.ic_turnover_adj:.4f}" if d.ic_turnover_adj is not None else "N/A"
            lines.append(
                f"- **IC (mean / IR / p-value)**: "
                f"{d.ic_mean:.4f} / {d.ic_ir:.3f} / {d.ic_p_value:.4f}"
            )
            lines.append(f"- **Turnover-adjusted IC**: {adj_str}")

            if d.vif is not None:
                cluster_info = (
                    f"cluster {d.cluster_id}" if d.cluster_id is not None else "singleton"
                )
                lines.append(f"- **VIF**: {d.vif:.2f} ({cluster_info})")
            else:
                lines.append("- **VIF**: not computed")

            if d.sharpe_ratio is not None:
                dsr_str = f"{d.dsr:.3f}" if d.dsr is not None else "N/A"
                psr_str = f"{d.psr:.3f}" if d.psr is not None else "N/A"
                trl_str = str(d.min_trl) if d.min_trl is not None else "N/A"
                lines.append(
                    f"- **Sharpe / PSR / DSR / Min-TRL**: "
                    f"{d.sharpe_ratio:.3f} / {psr_str} / {dsr_str} / {trl_str}"
                )
            else:
                lines.append("- **Sharpe / PSR / DSR / Min-TRL**: not computed")

            if d.p_value_holm is not None:
                lines.append(f"- **p-value (Holm-adjusted)**: {d.p_value_holm:.4f}")
            else:
                lines.append("- **p-value (Holm-adjusted)**: N/A")

            if d.decision == "keep":
                lines.append("- **All gates passed.**")
            else:
                lines.append("- **Reject reasons**:")
                for reason in d.reject_reasons:
                    lines.append(f"  - {reason}")
            lines.append("")

        # PBO analysis
        lines.append("## PBO analysis")
        lines.append("")
        if self.pbo_of_final_set is not None:
            strict = self.pbo_strict_threshold
            lines.append(f"Final set of {self.n_kept} features, PBO = {self.pbo_of_final_set:.4f}.")
            if self.pbo_of_final_set < strict:
                lines.append(
                    f"Strong evidence of genuine edge (PBO < {strict:.2f} configured gate)."
                )
            elif self.pbo_of_final_set < 0.50:
                lines.append(
                    "Moderate evidence; PBO passes secondary threshold (< 0.50) "
                    f"but fails strict configured gate (< {strict:.2f})."
                )
            else:
                lines.append(
                    "WARNING: PBO >= 0.50 indicates likely overfitting. "
                    "Feature set requires re-evaluation."
                )
        else:
            lines.append("PBO not computed (requires separate CPCV run on final feature set).")
        lines.append("")

        # References
        lines.append("## References")
        lines.append("")
        lines.append("- Grinold & Kahn (1999) Ch. 14 — IC-based alpha model construction")
        lines.append(
            "- Harvey, Liu & Zhu (2016) — Multiple testing in cross-sectional return predictors"
        )
        lines.append("- Bailey & López de Prado (2014) — DSR")
        lines.append("- Bailey et al. (2014) — PBO")
        lines.append("- ADR-0004 Feature Validation Methodology")
        lines.append("")

        return "\n".join(lines)

    def to_json(self) -> str:
        """Serialize to deterministic JSON string.

        Same inputs → same bytes.  Keys sorted, indent=2.  Floats are
        rounded to 6 decimals so committed artefacts are free of the
        arithmetic noise (``0.0720000000000001``) that Python's native
        repr would otherwise leak into diffs.
        """
        data: dict[str, Any] = {
            "generated_at": self.generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "n_candidates": self.n_candidates,
            "n_kept": self.n_kept,
            "n_rejected": self.n_rejected,
            "pbo_of_final_set": self.pbo_of_final_set,
            "pbo_strict_threshold": self.pbo_strict_threshold,
            "decisions": [d.to_dict() for d in self.decisions],
        }
        return json.dumps(_round_floats(data, ndigits=6), indent=2, sort_keys=True)
