"""End-to-end integration test for the Phase 3 feature validation pipeline.

Scenario
--------
10 candidate strategies traverse the complete Phase 3 pipeline:
    IC measurement (3.3)
        -> Multicollinearity analysis (3.9)
        -> DSR / PBO / MHT (3.11)
        -> FeatureSelectionReport (3.12)

Composition:
- 1 strategy ("true_alpha") carrying a genuine predictive signal
  (correlated with forward returns by construction).
- 9 strategies ("noise_00" .. "noise_08") that are pure-noise features
  with no relationship to forward returns.

Expected outcome
----------------
Only the true alpha passes all decision gates; the nine noise strategies
are rejected with explicit reject_reasons. PBO of the final keep set is
strictly below the ADR-0004 threshold of 0.10.

This test validates *composability* across Phase 3 modules. Individual
module correctness is verified by unit tests under tests/unit/features/.
Any gap in the glue between modules surfaces here.

References
----------
- PHASE_3_SPEC.md sub-phases 3.3, 3.9, 3.11, 3.12.
- ADR-0004 Feature Validation Methodology.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from features.hypothesis.dsr import DeflatedSharpeCalculator
from features.hypothesis.mht import holm_bonferroni
from features.hypothesis.pbo import PBOCalculator
from features.hypothesis.report import build_report
from features.ic.measurer import SpearmanICMeasurer
from features.ic.report import ICReport
from features.multicollinearity import MulticollinearityAnalyzer
from features.selection.report_generator import FeatureSelectionReportGenerator

pytestmark = pytest.mark.integration


_CALCULATOR_MAP = {
    "true_alpha": "unknown",
    **{f"noise_{i:02d}": "unknown" for i in range(9)},
}


def _build_synthetic_features(
    rng: np.random.Generator,
    n_obs: int,
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Generate 1 true alpha + 9 noise features plus aligned forward returns.

    The IC layer compares ``feature[t]`` with ``forward_returns[t]`` — the
    caller is expected to have pre-shifted the return series to represent
    the forward horizon. We therefore construct true_alpha so that its
    pointwise correlation with ``forward_returns`` is strong, and the nine
    noise features are independent Gaussian noise.
    """
    forward_returns = rng.standard_normal(n_obs) * 0.01

    features: dict[str, np.ndarray] = {}
    features["true_alpha"] = 0.7 * forward_returns + 0.3 * rng.standard_normal(n_obs) * 0.01
    for i in range(9):
        features[f"noise_{i:02d}"] = rng.standard_normal(n_obs) * 0.01

    return features, forward_returns


def _measure_ic_report(
    features: dict[str, np.ndarray],
    forward_returns: np.ndarray,
    horizon: int,
) -> ICReport:
    measurer = SpearmanICMeasurer(rolling_window=100, bootstrap_n=200)
    results = [
        measurer.measure_rich(
            feature=arr,
            forward_returns=forward_returns,
            feature_name=name,
            horizon_bars=horizon,
        )
        for name, arr in features.items()
    ]
    return ICReport(results)


def _build_is_oos_metrics(
    features: dict[str, np.ndarray],
    forward_returns: np.ndarray,
    *,
    n_folds: int,
) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """Synthesise IS / OOS per-fold metrics for PBO.

    Splits the sample into ``2 * n_folds`` contiguous chunks; odd chunks
    are IS, even chunks are OOS. The per-chunk metric is the Spearman
    rank correlation between the feature and forward-return slices.
    This keeps PBO's IS/OOS structure honest without needing a full CPCV
    backtest infrastructure.
    """
    from scipy.stats import spearmanr

    names = list(features.keys())
    n = forward_returns.size
    chunk = n // (2 * n_folds)

    is_metrics: dict[str, list[float]] = {name: [] for name in names}
    oos_metrics: dict[str, list[float]] = {name: [] for name in names}

    for fold in range(n_folds):
        is_start = 2 * fold * chunk
        is_end = is_start + chunk
        oos_start = is_end
        oos_end = oos_start + chunk

        for name, arr in features.items():
            feat_is = arr[is_start:is_end]
            ret_is = forward_returns[is_start:is_end]
            feat_oos = arr[oos_start:oos_end]
            ret_oos = forward_returns[oos_start:oos_end]

            rho_is, _ = spearmanr(feat_is, ret_is)
            rho_oos, _ = spearmanr(feat_oos, ret_oos)
            is_metrics[name].append(float(rho_is) if np.isfinite(rho_is) else 0.0)
            oos_metrics[name].append(float(rho_oos) if np.isfinite(rho_oos) else 0.0)

    return is_metrics, oos_metrics


class TestPhase3EndToEndPipeline:
    """Validates Phase 3 modules compose correctly end-to-end."""

    def test_synthetic_alpha_survives_full_pipeline(self) -> None:
        """1 true alpha + 9 noise -> only true_alpha in KEEP, PBO < 0.10.

        Exercises IC measurement -> Multicollinearity -> DSR/PBO/MHT ->
        FeatureSelectionReport. Any composition gap between Phase 3
        modules surfaces here; individual-module correctness is covered
        by the unit suite.
        """
        rng = np.random.default_rng(seed=42)
        n_obs = 2000
        horizon = 5
        n_folds = 10

        # 1. Synthetic data --------------------------------------------
        features, forward_returns = _build_synthetic_features(rng, n_obs)
        true_alpha_name = "true_alpha"

        # 2. IC measurement (Phase 3.3) --------------------------------
        ic_report = _measure_ic_report(features, forward_returns, horizon)
        ic_by_name = {r.feature_name: r for r in ic_report.results}
        assert set(ic_by_name) == set(features)

        # Sanity check: true alpha IC dominates the noise band.
        true_ic = abs(ic_by_name[true_alpha_name].ic)
        noise_ics = [abs(ic_by_name[f"noise_{i:02d}"].ic) for i in range(9)]
        assert true_ic > max(noise_ics), (
            f"true_alpha IC ({true_ic:.4f}) should exceed noise IC (max {max(noise_ics):.4f})"
        )

        # 3. Multicollinearity (Phase 3.9) -----------------------------
        feature_df = pl.DataFrame(dict(features.items()))
        multicoll_report = MulticollinearityAnalyzer(
            max_correlation=0.70,
            max_vif=5.0,
        ).analyze(feature_matrix=feature_df, ic_results=ic_report.results)

        # 4. DSR (Phase 3.11) ------------------------------------------
        # Strategy return = sign(feature[t]) * forward_returns[t] — a simple
        # long/short rule. The true alpha's signs align with forward returns;
        # noise features produce a zero-mean PnL.
        strategy_returns = {name: np.sign(arr) * forward_returns for name, arr in features.items()}
        returns_data = {
            name: pl.Series(name, ret.tolist()) for name, ret in strategy_returns.items()
        }
        dsr_results = DeflatedSharpeCalculator().compute_from_returns(returns_data)

        # 5. PBO (Phase 3.11) ------------------------------------------
        is_metrics, oos_metrics = _build_is_oos_metrics(features, forward_returns, n_folds=n_folds)
        pbo_result = PBOCalculator().compute(is_metrics, oos_metrics)

        # 6. MHT (Phase 3.11) ------------------------------------------
        raw_p = {r.feature_name: 1.0 - r.dsr for r in dsr_results}
        ordered_names = list(raw_p.keys())
        _, p_adj = holm_bonferroni([raw_p[name] for name in ordered_names], alpha=0.05)
        p_holm = dict(zip(ordered_names, (float(p) for p in p_adj), strict=True))

        # 7. Hypothesis-testing aggregation (Phase 3.11) --------------
        hypothesis_report = build_report(
            dsr_results=dsr_results,
            pbo_result=pbo_result,
            p_values_raw=raw_p,
            p_values_holm=p_holm,
            alpha=0.05,
            mht_correction="holm",
        )

        # 8. Selection decision (Phase 3.12) ---------------------------
        selection_report = FeatureSelectionReportGenerator(calculator_map=_CALCULATOR_MAP).generate(
            ic_report=ic_report,
            multicoll_report=multicoll_report,
            hypothesis_report=hypothesis_report,
        )

        # 9. Assertions ------------------------------------------------
        kept = [d for d in selection_report.decisions if d.decision == "keep"]
        rejected = [d for d in selection_report.decisions if d.decision == "reject"]

        # Exactly the true alpha passes all gates.
        assert selection_report.n_candidates == 10
        assert len(kept) == 1, (
            f"Expected 1 keep (the true alpha), got {len(kept)}: {[d.feature_name for d in kept]}"
        )
        assert kept[0].feature_name == true_alpha_name

        # All nine noise strategies carry explicit reject reasons.
        assert len(rejected) == 9
        noise_rejected_names = {d.feature_name for d in rejected}
        assert noise_rejected_names == {f"noise_{i:02d}" for i in range(9)}
        for d in rejected:
            assert d.reject_reasons, (
                f"{d.feature_name} was rejected but carries no reject_reasons — "
                "silent reject is forbidden (ADR-0004 §6)."
            )

        # ADR-0004 PBO gate.
        assert selection_report.pbo_of_final_set is not None
        assert selection_report.pbo_of_final_set < 0.10, (
            f"PBO={selection_report.pbo_of_final_set:.4f} violates ADR-0004 "
            "strict threshold of 0.10"
        )

        # Determinism: report serializes consistently to JSON + Markdown.
        json_blob = selection_report.to_json()
        md_blob = selection_report.to_markdown()
        assert json_blob
        assert md_blob
        assert true_alpha_name in json_blob
        assert "keep" in json_blob
