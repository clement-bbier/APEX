"""Generate Phase 3.12 Feature Selection Report from hardcoded synthetic data.

All metric values are hardcoded for exact reproducibility — no RNG is used.
Rerunning the script produces byte-identical Markdown and JSON artefacts
(modulo the UTC generation timestamp in the header).

Produces:
- reports/phase_3_12/feature_selection_report.md
- reports/phase_3_12/feature_selection_report.json

Run:
    python scripts/generate_phase_3_12_report.py
"""

from __future__ import annotations

from pathlib import Path

from features.hypothesis.pbo import PBOResult
from features.hypothesis.report import (
    FeatureDecision as HypFeatureDecision,
)
from features.hypothesis.report import (
    HypothesisTestingReport,
)
from features.ic.base import ICResult
from features.ic.report import ICReport
from features.multicollinearity import MulticollinearityReport
from features.selection.report_generator import FeatureSelectionReportGenerator


def _ic(
    name: str,
    ic: float,
    ic_ir: float,
    p_value: float,
    adj: float | None = None,
) -> ICResult:
    return ICResult(
        ic=ic,
        ic_ir=ic_ir,
        p_value=p_value,
        n_samples=500,
        ci_low=ic - 0.02,
        ci_high=ic + 0.02,
        feature_name=name,
        turnover_adj_ic=adj if adj is not None else ic * 0.9,
    )


def _hyp(
    name: str,
    sharpe: float,
    psr: float,
    dsr: float,
    min_trl: int,
    p_holm: float,
) -> HypFeatureDecision:
    return HypFeatureDecision(
        feature_name=name,
        sharpe_raw=sharpe,
        psr=psr,
        dsr=dsr,
        min_trl=min_trl,
        n_trials=8,
        n_obs=500,
        p_value_raw=p_holm * 0.5,
        p_value_holm=p_holm,
        p_value_bh=p_holm * 0.8,
        decision="pass" if dsr >= 0.95 else "fail",
        fail_reasons=[],
    )


def main() -> None:
    """Build and write reports."""
    # 8 candidate features from 5 calculators
    ic_report = ICReport(
        [
            _ic("gex_signal", ic=0.09, ic_ir=1.50, p_value=0.0005),
            _ic("har_rv_signal", ic=0.08, ic_ir=1.20, p_value=0.0010),
            _ic("ofi_signal", ic=0.07, ic_ir=1.00, p_value=0.0020),
            _ic("cvd_signal", ic=0.05, ic_ir=0.80, p_value=0.0100),
            _ic("rough_hurst", ic=0.06, ic_ir=0.90, p_value=0.0050),
            _ic("rough_vol_signal", ic=0.04, ic_ir=0.70, p_value=0.0200),
            _ic("combined_signal", ic=0.01, ic_ir=0.30, p_value=0.2000),
            _ic("liquidity_signal", ic=0.005, ic_ir=0.10, p_value=0.5000),
        ]
    )

    all_names = [
        "gex_signal",
        "har_rv_signal",
        "ofi_signal",
        "cvd_signal",
        "rough_hurst",
        "rough_vol_signal",
        "combined_signal",
        "liquidity_signal",
    ]

    corr: dict[str, dict[str, float]] = {}
    for s1 in all_names:
        corr[s1] = {}
        for s2 in all_names:
            if s1 == s2:
                corr[s1][s2] = 1.0
            elif {s1, s2} == {"ofi_signal", "cvd_signal"}:
                corr[s1][s2] = 0.78
            elif {s1, s2} == {"rough_hurst", "rough_vol_signal"}:
                corr[s1][s2] = 0.65
            else:
                corr[s1][s2] = 0.10

    multicoll_report = MulticollinearityReport(
        correlation_matrix=corr,
        vif_scores={
            "gex_signal": 1.01,
            "har_rv_signal": 3.57,
            "ofi_signal": 2.10,
            "cvd_signal": 2.30,
            "rough_hurst": 1.80,
            "rough_vol_signal": 1.50,
            "combined_signal": 1.20,
            "liquidity_signal": 1.10,
        },
        high_correlation_pairs=[("ofi_signal", "cvd_signal", 0.78)],
        high_vif_signals=[],
        cluster_assignments={
            "gex_signal": 0,
            "har_rv_signal": 1,
            "ofi_signal": 2,
            "cvd_signal": 2,
            "rough_hurst": 3,
            "rough_vol_signal": 4,
            "combined_signal": 5,
            "liquidity_signal": 6,
        },
        recommended_drops=["cvd_signal"],
        condition_number=12.3,
        n_rows_used=500,
        signal_columns=all_names,
        max_vif=5.0,
    )

    hypothesis_report = HypothesisTestingReport(
        feature_decisions=[
            _hyp("gex_signal", 1.85, 0.97, 0.97, 200, 0.010),
            _hyp("har_rv_signal", 1.60, 0.96, 0.96, 220, 0.008),
            _hyp("ofi_signal", 1.50, 0.95, 0.96, 230, 0.015),
            _hyp("cvd_signal", 1.30, 0.94, 0.95, 250, 0.020),
            _hyp("rough_hurst", 1.23, 0.91, 0.89, 380, 0.045),
            _hyp("rough_vol_signal", 1.10, 0.90, 0.85, 400, 0.040),
            _hyp("combined_signal", 0.50, 0.60, 0.55, 600, 0.300),
            _hyp("liquidity_signal", 0.30, 0.50, 0.40, 800, 0.500),
        ],
        pbo_result=PBOResult(
            pbo=0.05,
            n_folds=10,
            n_features=8,
            rank_logits=[0.12, 0.08, 0.15, 0.05, 0.09, 0.11, 0.07, 0.13, 0.10, 0.06],
            is_overfit=False,
            passes_adr0004=True,
        ),
        mht_correction="holm",
        alpha=0.05,
        n_features=8,
        n_pass=4,
        n_fail=4,
    )

    gen = FeatureSelectionReportGenerator()
    report = gen.generate(
        ic_report=ic_report,
        multicoll_report=multicoll_report,
        hypothesis_report=hypothesis_report,
    )

    out_dir = Path("reports/phase_3_12")
    out_dir.mkdir(parents=True, exist_ok=True)

    md_path = out_dir / "feature_selection_report.md"
    md_path.write_text(report.to_markdown(), encoding="utf-8")

    json_path = out_dir / "feature_selection_report.json"
    json_path.write_text(report.to_json(), encoding="utf-8")

    print(f"Markdown: {md_path}")
    print(f"JSON:     {json_path}")
    print(f"Kept:     {report.n_kept}/{report.n_candidates}")
    print(f"PBO:      {report.pbo_of_final_set}")


if __name__ == "__main__":
    main()
