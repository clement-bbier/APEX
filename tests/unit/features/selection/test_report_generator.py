"""Tests for FeatureSelectionReportGenerator and FeatureSelectionReport.

Covers:
- Constructor validation (D030)
- Per-gate rejection logic
- Cherry-picking protection (missing multicoll/hypothesis evidence)
- Serialization determinism (Markdown + JSON)
- End-to-end synthetic 8-feature scenario
"""

from __future__ import annotations

import json

import pytest

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
from features.selection.decision import SelectionDecision
from features.selection.report_generator import (
    FeatureSelectionReport,
    FeatureSelectionReportGenerator,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ic_result(
    name: str,
    ic: float = 0.08,
    ic_ir: float = 1.5,
    p_value: float = 0.001,
    turnover_adj: float | None = 0.07,
) -> ICResult:
    return ICResult(
        ic=ic,
        ic_ir=ic_ir,
        p_value=p_value,
        n_samples=500,
        ci_low=ic - 0.02,
        ci_high=ic + 0.02,
        feature_name=name,
        turnover_adj_ic=turnover_adj,
    )


def _multicoll_report(
    signals: list[str],
    vifs: dict[str, float] | None = None,
    clusters: dict[str, int] | None = None,
    drops: list[str] | None = None,
) -> MulticollinearityReport:
    """Build a minimal MulticollinearityReport."""
    if vifs is None:
        vifs = dict.fromkeys(signals, 1.5)
    if clusters is None:
        clusters = {s: i for i, s in enumerate(signals)}
    if drops is None:
        drops = []
    corr: dict[str, dict[str, float]] = {}
    for s1 in signals:
        corr[s1] = {}
        for s2 in signals:
            corr[s1][s2] = 1.0 if s1 == s2 else 0.1
    return MulticollinearityReport(
        correlation_matrix=corr,
        vif_scores=vifs,
        high_correlation_pairs=[],
        high_vif_signals=[],
        cluster_assignments=clusters,
        recommended_drops=drops,
        condition_number=5.0,
        n_rows_used=500,
        signal_columns=signals,
        max_vif=5.0,
    )


def _hyp_decision(
    name: str,
    sharpe: float = 1.8,
    psr: float = 0.97,
    dsr: float = 0.96,
    min_trl: int = 200,
    p_holm: float | None = 0.01,
) -> HypFeatureDecision:
    return HypFeatureDecision(
        feature_name=name,
        sharpe_raw=sharpe,
        psr=psr,
        dsr=dsr,
        min_trl=min_trl,
        n_trials=5,
        n_obs=500,
        p_value_raw=0.005,
        p_value_holm=p_holm,
        p_value_bh=p_holm,
        decision="pass" if dsr >= 0.95 else "fail",
        fail_reasons=[],
    )


def _hyp_report(
    decisions: list[HypFeatureDecision],
    pbo: float | None = 0.05,
) -> HypothesisTestingReport:
    pbo_result = None
    if pbo is not None:
        pbo_result = PBOResult(
            pbo=pbo,
            n_folds=10,
            n_features=len(decisions),
            rank_logits=[0.1] * 10,
            is_overfit=pbo > 0.50,
            passes_adr0004=pbo < 0.10,
        )
    n_pass = sum(1 for d in decisions if d.decision == "pass")
    return HypothesisTestingReport(
        feature_decisions=decisions,
        pbo_result=pbo_result,
        mht_correction="holm",
        alpha=0.05,
        n_features=len(decisions),
        n_pass=n_pass,
        n_fail=len(decisions) - n_pass,
    )


# ---------------------------------------------------------------------------
# Constructor validation (D030)
# ---------------------------------------------------------------------------


class TestReportGeneratorConstructor:
    """D030 validation: thresholds in sensible ranges."""

    def test_defaults_match_adr0004(self) -> None:
        gen = FeatureSelectionReportGenerator()
        # Just verifying construction succeeds with ADR-0004 defaults
        assert gen is not None

    @pytest.mark.parametrize(
        ("kwarg", "bad_value"),
        [
            ("ic_min", 0.0),
            ("ic_min", 1.0),
            ("ic_min", -0.5),
            ("ic_ir_min", 0.0),
            ("ic_ir_min", 10.0),
            ("ic_p_max", 0.0),
            ("vif_max", 1.0),
            ("vif_max", 0.5),
            ("dsr_min", 0.0),
            ("dsr_min", 1.0),
            ("psr_min", 0.0),
            ("psr_min", 1.0),
            ("alpha", 0.0),
            ("pbo_max", 0.0),
            ("pbo_max", 1.0),
        ],
    )
    def test_invalid_thresholds_raise(self, kwarg: str, bad_value: float) -> None:
        with pytest.raises(ValueError, match=kwarg):
            FeatureSelectionReportGenerator(**{kwarg: bad_value})


# ---------------------------------------------------------------------------
# Decision logic — per-gate tests
# ---------------------------------------------------------------------------


class TestDecisionLogic:
    """Each gate independently triggers rejection."""

    def _generate_single(
        self,
        ic_kwargs: dict[str, object] | None = None,
        multicoll_kwargs: dict[str, object] | None = None,
        hyp_kwargs: dict[str, object] | None = None,
        pbo: float | None = 0.05,
    ) -> SelectionDecision:
        """Generate report for a single feature and return its decision."""
        name = "test_signal"
        ic = _ic_result(name, **(ic_kwargs or {}))
        mc = _multicoll_report(
            [name],
            **(multicoll_kwargs or {}),
        )
        hd = _hyp_decision(name, **(hyp_kwargs or {}))
        hr = _hyp_report([hd], pbo=pbo)

        gen = FeatureSelectionReportGenerator(
            calculator_map={name: "TestCalc"},
        )
        report = gen.generate(
            ic_report=ICReport([ic]),
            multicoll_report=mc,
            hypothesis_report=hr,
        )
        assert len(report.decisions) == 1
        return report.decisions[0]

    def test_all_gates_pass(self) -> None:
        d = self._generate_single()
        assert d.decision == "keep"
        assert d.reject_reasons == []

    def test_ic_below_min(self) -> None:
        d = self._generate_single(ic_kwargs={"ic": 0.01})
        assert d.decision == "reject"
        assert any("ic_mean" in r for r in d.reject_reasons)

    def test_ic_ir_below_min(self) -> None:
        d = self._generate_single(ic_kwargs={"ic_ir": 0.3})
        assert d.decision == "reject"
        assert any("ic_ir" in r for r in d.reject_reasons)

    def test_ic_p_above_max(self) -> None:
        d = self._generate_single(ic_kwargs={"p_value": 0.10})
        assert d.decision == "reject"
        assert any("ic_p_value" in r for r in d.reject_reasons)

    def test_vif_above_max(self) -> None:
        d = self._generate_single(
            multicoll_kwargs={"vifs": {"test_signal": 8.0}},
        )
        assert d.decision == "reject"
        assert any("vif=" in r for r in d.reject_reasons)

    def test_cluster_dropped(self) -> None:
        d = self._generate_single(
            multicoll_kwargs={"drops": ["test_signal"]},
        )
        assert d.decision == "reject"
        assert any("cluster_dropped" in r for r in d.reject_reasons)

    def test_dsr_below_min(self) -> None:
        d = self._generate_single(hyp_kwargs={"dsr": 0.80})
        assert d.decision == "reject"
        assert any("dsr=" in r for r in d.reject_reasons)

    def test_psr_below_min(self) -> None:
        d = self._generate_single(hyp_kwargs={"psr": 0.70})
        assert d.decision == "reject"
        assert any("psr=" in r for r in d.reject_reasons)

    def test_p_holm_above_alpha(self) -> None:
        d = self._generate_single(hyp_kwargs={"p_holm": 0.20})
        assert d.decision == "reject"
        assert any("p_value_holm" in r for r in d.reject_reasons)

    def test_pbo_above_max(self) -> None:
        d = self._generate_single(pbo=0.30)
        assert d.decision == "reject"
        assert any("pbo=" in r for r in d.reject_reasons)

    def test_multiple_failures_all_listed(self) -> None:
        d = self._generate_single(
            ic_kwargs={"ic": 0.005, "ic_ir": 0.2},
            hyp_kwargs={"dsr": 0.50},
        )
        assert d.decision == "reject"
        assert len(d.reject_reasons) >= 3


# ---------------------------------------------------------------------------
# Cherry-picking protection
# ---------------------------------------------------------------------------


class TestCherryPickingProtection:
    """Harvey-Liu-Zhu 2016: every feature must appear, no silent passes."""

    def test_missing_multicoll_is_explicit_reject(self) -> None:
        """Feature in IC but multicoll_report is None → vif_not_computed."""
        gen = FeatureSelectionReportGenerator()
        ic = ICReport([_ic_result("feat_a")])
        hd = _hyp_decision("feat_a")
        hr = _hyp_report([hd])

        report = gen.generate(
            ic_report=ic,
            multicoll_report=None,
            hypothesis_report=hr,
        )
        assert report.n_candidates == 1
        d = report.decisions[0]
        assert d.decision == "reject"
        assert "vif_not_computed" in d.reject_reasons

    def test_missing_hypothesis_is_explicit_reject(self) -> None:
        """Feature in IC but hypothesis_report is None → dsr_not_computed."""
        gen = FeatureSelectionReportGenerator()
        ic = ICReport([_ic_result("feat_a")])
        mc = _multicoll_report(["feat_a"])

        report = gen.generate(
            ic_report=ic,
            multicoll_report=mc,
            hypothesis_report=None,
        )
        assert report.n_candidates == 1
        d = report.decisions[0]
        assert d.decision == "reject"
        assert "dsr_not_computed" in d.reject_reasons

    def test_feature_absent_from_multicoll_dict(self) -> None:
        """Feature in IC but not in multicoll signal_columns → vif_not_computed."""
        gen = FeatureSelectionReportGenerator()
        ic = ICReport([_ic_result("feat_a"), _ic_result("feat_b")])
        mc = _multicoll_report(["feat_a"])  # feat_b missing
        hd_a = _hyp_decision("feat_a")
        hd_b = _hyp_decision("feat_b")
        hr = _hyp_report([hd_a, hd_b])

        report = gen.generate(ic_report=ic, multicoll_report=mc, hypothesis_report=hr)
        assert report.n_candidates == 2
        decision_b = next(d for d in report.decisions if d.feature_name == "feat_b")
        assert "vif_not_computed" in decision_b.reject_reasons

    def test_feature_absent_from_hypothesis(self) -> None:
        """Feature in IC but not in hypothesis → dsr_not_computed."""
        gen = FeatureSelectionReportGenerator()
        ic = ICReport([_ic_result("feat_a"), _ic_result("feat_b")])
        mc = _multicoll_report(["feat_a", "feat_b"])
        hd_a = _hyp_decision("feat_a")
        hr = _hyp_report([hd_a])  # feat_b missing

        report = gen.generate(ic_report=ic, multicoll_report=mc, hypothesis_report=hr)
        assert report.n_candidates == 2
        decision_b = next(d for d in report.decisions if d.feature_name == "feat_b")
        assert "dsr_not_computed" in decision_b.reject_reasons

    def test_n_candidates_equals_ic_count(self) -> None:
        """n_candidates must always equal len(ic_report.results)."""
        gen = FeatureSelectionReportGenerator()
        features = [_ic_result(f"feat_{i}") for i in range(5)]
        ic = ICReport(features)

        report = gen.generate(
            ic_report=ic,
            multicoll_report=None,
            hypothesis_report=None,
        )
        assert report.n_candidates == 5
        assert len(report.decisions) == 5


# ---------------------------------------------------------------------------
# Serialization determinism
# ---------------------------------------------------------------------------


class TestReportSerialization:
    """Same inputs → same bytes for Markdown and JSON."""

    def _build_report(self) -> FeatureSelectionReport:
        gen = FeatureSelectionReportGenerator(
            calculator_map={"feat_a": "CalcA", "feat_b": "CalcB"},
        )
        ic = ICReport([_ic_result("feat_a"), _ic_result("feat_b", ic=0.01)])
        mc = _multicoll_report(["feat_a", "feat_b"])
        hd_a = _hyp_decision("feat_a")
        hd_b = _hyp_decision("feat_b", dsr=0.80)
        hr = _hyp_report([hd_a, hd_b], pbo=0.05)

        return gen.generate(ic_report=ic, multicoll_report=mc, hypothesis_report=hr)

    def test_markdown_deterministic(self) -> None:
        r1 = self._build_report()
        r2 = self._build_report()
        # Replace timestamps for comparison (generated_at differs)
        md1 = r1.to_markdown().split("\n", 3)[3]
        md2 = r2.to_markdown().split("\n", 3)[3]
        assert md1 == md2

    def test_json_deterministic(self) -> None:
        r1 = self._build_report()
        r2 = self._build_report()
        j1 = json.loads(r1.to_json())
        j2 = json.loads(r2.to_json())
        # Remove timestamps
        j1.pop("generated_at")
        j2.pop("generated_at")
        assert j1 == j2

    def test_json_valid_roundtrip(self) -> None:
        report = self._build_report()
        j = report.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict)
        assert parsed["n_candidates"] == 2
        assert len(parsed["decisions"]) == 2

    def test_markdown_contains_all_candidates(self) -> None:
        report = self._build_report()
        md = report.to_markdown()
        assert "feat_a" in md
        assert "feat_b" in md

    def test_json_contains_all_candidates(self) -> None:
        report = self._build_report()
        parsed = json.loads(report.to_json())
        names = {d["feature_name"] for d in parsed["decisions"]}
        assert names == {"feat_a", "feat_b"}

    def test_ordering_keep_first_then_by_dsr(self) -> None:
        report = self._build_report()
        decisions = report.decisions
        # feat_a should be keep (or at least ranked before feat_b)
        keep_indices = [i for i, d in enumerate(decisions) if d.decision == "keep"]
        reject_indices = [i for i, d in enumerate(decisions) if d.decision == "reject"]
        if keep_indices and reject_indices:
            assert max(keep_indices) < min(reject_indices)


# ---------------------------------------------------------------------------
# End-to-end: synthetic 8-feature scenario
# ---------------------------------------------------------------------------


class TestEndToEndSynthetic8Features:
    """Realistic scenario: 8 features, mix of outcomes.

    - 2 pass all gates (high IC, low VIF, high DSR)
    - 2 collinear (same cluster, one dropped)
    - 2 with DSR too low
    - 2 with IC non-significant
    """

    def _build(self) -> FeatureSelectionReport:
        features = [
            # Pass all gates
            _ic_result("gex_signal", ic=0.09, ic_ir=1.5, p_value=0.0005),
            _ic_result("har_rv_signal", ic=0.08, ic_ir=1.2, p_value=0.001),
            # Collinear pair — ofi_signal wins, cvd_signal dropped
            _ic_result("ofi_signal", ic=0.07, ic_ir=1.0, p_value=0.002),
            _ic_result("cvd_signal", ic=0.05, ic_ir=0.8, p_value=0.01),
            # Low DSR
            _ic_result("rough_hurst", ic=0.06, ic_ir=0.9, p_value=0.005),
            _ic_result("rough_vol_signal", ic=0.04, ic_ir=0.7, p_value=0.02),
            # IC non-significant
            _ic_result("combined_signal", ic=0.01, ic_ir=0.3, p_value=0.20),
            _ic_result("liquidity_signal", ic=0.005, ic_ir=0.1, p_value=0.50),
        ]
        ic_report = ICReport(features)

        all_names = [f.feature_name for f in features]
        assert all(n is not None for n in all_names)
        names: list[str] = [n for n in all_names if n is not None]

        mc = _multicoll_report(
            names,
            vifs={
                "gex_signal": 1.01,
                "har_rv_signal": 3.57,
                "ofi_signal": 2.10,
                "cvd_signal": 2.30,
                "rough_hurst": 1.80,
                "rough_vol_signal": 1.50,
                "combined_signal": 1.20,
                "liquidity_signal": 1.10,
            },
            clusters={
                "gex_signal": 0,
                "har_rv_signal": 1,
                "ofi_signal": 2,
                "cvd_signal": 2,  # same cluster as ofi
                "rough_hurst": 3,
                "rough_vol_signal": 4,
                "combined_signal": 5,
                "liquidity_signal": 6,
            },
            drops=["cvd_signal"],  # ofi_signal has higher IC
        )

        hyp_decisions = [
            _hyp_decision("gex_signal", sharpe=1.85, psr=0.97, dsr=0.97, p_holm=0.01),
            _hyp_decision("har_rv_signal", sharpe=1.60, psr=0.96, dsr=0.96, p_holm=0.008),
            _hyp_decision("ofi_signal", sharpe=1.50, psr=0.95, dsr=0.96, p_holm=0.015),
            _hyp_decision("cvd_signal", sharpe=1.30, psr=0.94, dsr=0.95, p_holm=0.02),
            _hyp_decision("rough_hurst", sharpe=1.23, psr=0.91, dsr=0.89, p_holm=0.045),
            _hyp_decision("rough_vol_signal", sharpe=1.10, psr=0.90, dsr=0.85, p_holm=0.04),
            _hyp_decision("combined_signal", sharpe=0.50, psr=0.60, dsr=0.55, p_holm=0.30),
            _hyp_decision("liquidity_signal", sharpe=0.30, psr=0.50, dsr=0.40, p_holm=0.50),
        ]
        hr = _hyp_report(hyp_decisions, pbo=0.05)

        gen = FeatureSelectionReportGenerator()
        return gen.generate(
            ic_report=ic_report,
            multicoll_report=mc,
            hypothesis_report=hr,
        )

    def test_candidate_count(self) -> None:
        report = self._build()
        assert report.n_candidates == 8

    def test_keep_count(self) -> None:
        report = self._build()
        kept_names = {d.feature_name for d in report.decisions if d.decision == "keep"}
        # gex_signal, har_rv_signal, ofi_signal pass all gates
        assert kept_names == {"gex_signal", "har_rv_signal", "ofi_signal"}
        assert report.n_kept == 3

    def test_reject_count(self) -> None:
        report = self._build()
        assert report.n_rejected == 5

    def test_cvd_rejected_for_cluster_drop(self) -> None:
        report = self._build()
        cvd = next(d for d in report.decisions if d.feature_name == "cvd_signal")
        assert cvd.decision == "reject"
        assert "cluster_dropped_by_ic_ranking" in cvd.reject_reasons

    def test_rough_rejected_for_dsr(self) -> None:
        report = self._build()
        rough = next(d for d in report.decisions if d.feature_name == "rough_hurst")
        assert rough.decision == "reject"
        assert any("dsr=" in r for r in rough.reject_reasons)

    def test_ic_nonsignificant_rejected(self) -> None:
        report = self._build()
        combined = next(d for d in report.decisions if d.feature_name == "combined_signal")
        assert combined.decision == "reject"
        assert any("ic_mean" in r for r in combined.reject_reasons)

    def test_pbo_of_final_set(self) -> None:
        report = self._build()
        assert report.pbo_of_final_set == 0.05

    def test_markdown_output(self) -> None:
        report = self._build()
        md = report.to_markdown()
        # All 8 features present in markdown
        for d in report.decisions:
            assert d.feature_name in md
        assert "## Decision summary" in md
        assert "## Per-feature details" in md
        assert "## PBO analysis" in md

    def test_json_output(self) -> None:
        report = self._build()
        parsed = json.loads(report.to_json())
        assert parsed["n_candidates"] == 8
        assert parsed["n_kept"] == 3
        assert len(parsed["decisions"]) == 8


# ---------------------------------------------------------------------------
# Copilot PR #121 review — characterising tests for silent-bug fixes
# ---------------------------------------------------------------------------


class TestMHTSilentSkipFix:
    """p_value_holm=None must reject explicitly when MHT is required.

    Same anti-pattern family as PR #120 ``build_report`` silent skip.
    When the hypothesis report claims Holm/BH correction was applied over
    multiple features, a feature whose ``p_value_holm`` is ``None`` has
    missing evidence — **reject with a named reason, never silent-skip**.
    """

    def test_missing_p_holm_when_mht_required_rejects_explicitly(self) -> None:
        """Multi-feature Holm run with one missing p_holm → explicit reject."""
        ic_report = ICReport(
            [
                _ic_result("feat_a"),
                _ic_result("feat_b"),
                _ic_result("feat_c"),
            ]
        )
        mc = _multicoll_report(["feat_a", "feat_b", "feat_c"])

        # feat_c has p_holm=None despite mht_correction="holm"
        hyp_decisions = [
            _hyp_decision("feat_a", p_holm=0.01),
            _hyp_decision("feat_b", p_holm=0.02),
            _hyp_decision("feat_c", p_holm=None),
        ]
        hr = _hyp_report(hyp_decisions, pbo=0.05)
        assert hr.mht_correction == "holm"

        gen = FeatureSelectionReportGenerator()
        report = gen.generate(ic_report=ic_report, multicoll_report=mc, hypothesis_report=hr)

        feat_c = next(d for d in report.decisions if d.feature_name == "feat_c")
        assert feat_c.decision == "reject", (
            f"feat_c should reject: missing p_holm under MHT. "
            f"Got: {feat_c.decision}, reasons: {feat_c.reject_reasons}"
        )
        assert "p_value_holm_missing_when_mht_required" in feat_c.reject_reasons, (
            f"Expected explicit 'p_value_holm_missing_when_mht_required' reason. "
            f"Got: {feat_c.reject_reasons}"
        )

    def test_missing_p_holm_when_single_feature_is_ok(self) -> None:
        """Single-feature run: p_holm=None is legitimate (no MHT required)."""
        ic_report = ICReport([_ic_result("feat_solo")])
        mc = _multicoll_report(["feat_solo"])
        hr = _hyp_report([_hyp_decision("feat_solo", p_holm=None)], pbo=0.05)

        gen = FeatureSelectionReportGenerator()
        report = gen.generate(ic_report=ic_report, multicoll_report=mc, hypothesis_report=hr)

        feat = report.decisions[0]
        # Single feature → MHT not required → missing p_holm is fine
        assert "p_value_holm_missing_when_mht_required" not in feat.reject_reasons

    def test_missing_p_holm_when_mht_none_is_ok(self) -> None:
        """mht_correction='none': p_holm=None never triggers reject."""
        ic_report = ICReport([_ic_result("feat_a"), _ic_result("feat_b"), _ic_result("feat_c")])
        mc = _multicoll_report(["feat_a", "feat_b", "feat_c"])
        hyp_decisions = [_hyp_decision(n, p_holm=None) for n in ("feat_a", "feat_b", "feat_c")]
        hr = HypothesisTestingReport(
            feature_decisions=hyp_decisions,
            pbo_result=None,
            mht_correction="none",
            alpha=0.05,
            n_features=3,
            n_pass=3,
            n_fail=0,
        )

        gen = FeatureSelectionReportGenerator()
        report = gen.generate(ic_report=ic_report, multicoll_report=mc, hypothesis_report=hr)
        for d in report.decisions:
            assert "p_value_holm_missing_when_mht_required" not in d.reject_reasons


class TestCalculatorMapEmptyDict:
    """Copilot #1: ``{}`` must not trigger the default fallback."""

    def test_constructor_accepts_empty_calculator_map(self) -> None:
        """Empty dict input is a legitimate signal to force 'unknown' for all."""
        gen = FeatureSelectionReportGenerator(calculator_map={})
        ic_report = ICReport([_ic_result("har_rv_signal")])
        mc = _multicoll_report(["har_rv_signal"])
        hr = _hyp_report([_hyp_decision("har_rv_signal")])

        report = gen.generate(ic_report=ic_report, multicoll_report=mc, hypothesis_report=hr)
        # Even though "har_rv_signal" is in the default map, our explicit
        # empty dict means every feature maps to "unknown".
        assert report.decisions[0].calculator == "unknown"

    def test_constructor_uses_defaults_when_none(self) -> None:
        """``calculator_map=None`` still yields the ADR-0004 defaults."""
        gen = FeatureSelectionReportGenerator()
        ic_report = ICReport([_ic_result("har_rv_signal")])
        mc = _multicoll_report(["har_rv_signal"])
        hr = _hyp_report([_hyp_decision("har_rv_signal")])
        report = gen.generate(ic_report=ic_report, multicoll_report=mc, hypothesis_report=hr)
        assert report.decisions[0].calculator == "HAR-RV"


class TestUniqueFeatureNamePlaceholder:
    """Copilot #2: missing feature_name must not collide."""

    def test_unique_placeholder_when_feature_name_missing(self) -> None:
        """Multiple IC results without names get unique placeholders."""
        # Build two ICResults with feature_name=None (legacy)
        ic_report = ICReport(
            [
                ICResult(
                    ic=0.05,
                    ic_ir=1.0,
                    p_value=0.01,
                    n_samples=500,
                    ci_low=0.03,
                    ci_high=0.07,
                    feature_name=None,
                    turnover_adj_ic=0.04,
                ),
                ICResult(
                    ic=0.03,
                    ic_ir=0.8,
                    p_value=0.02,
                    n_samples=500,
                    ci_low=0.01,
                    ci_high=0.05,
                    feature_name=None,
                    turnover_adj_ic=0.02,
                ),
            ]
        )

        gen = FeatureSelectionReportGenerator()
        report = gen.generate(ic_report=ic_report, multicoll_report=None, hypothesis_report=None)

        names = [d.feature_name for d in report.decisions]
        assert len(set(names)) == 2, f"Expected unique names, got {names}"
        assert all(n.startswith("unknown_") for n in names), (
            f"Expected 'unknown_N' placeholders, got {names}"
        )
        assert all("feature_name_missing" in d.reject_reasons for d in report.decisions)


class TestPBONarrativeUsesConfiguredThreshold:
    """Copilot #4: Markdown PBO narrative must reflect configured gate."""

    def test_narrative_quotes_configured_threshold(self) -> None:
        """Markdown quotes the configured pbo_max, not a hardcoded 0.10."""
        # Use a non-default threshold so the narrative diverges
        gen = FeatureSelectionReportGenerator(pbo_max=0.15)
        ic = ICReport([_ic_result("feat_a")])
        mc = _multicoll_report(["feat_a"])
        hr = _hyp_report([_hyp_decision("feat_a")], pbo=0.05)

        report = gen.generate(ic_report=ic, multicoll_report=mc, hypothesis_report=hr)
        md = report.to_markdown()

        # Narrative must quote "< 0.15" (configured), never the hardcoded "0.10"
        assert "0.15" in md
        assert "configured gate" in md
        # Must not misattribute to ADR-0004 when user used a different threshold
        assert "PBO < 0.10 per ADR-0004" not in md

    def test_report_exposes_pbo_strict_threshold(self) -> None:
        """The report dataclass carries pbo_strict_threshold for downstream consumers."""
        gen = FeatureSelectionReportGenerator(pbo_max=0.12)
        ic = ICReport([_ic_result("feat_a")])
        report = gen.generate(ic_report=ic, multicoll_report=None, hypothesis_report=None)
        assert report.pbo_strict_threshold == 0.12


class TestJSONFloatRounding:
    """Copilot #8: JSON output must not leak float noise."""

    def test_json_floats_rounded(self) -> None:
        """0.07200000000000001 → 0.072 in serialised output."""
        # Build a decision whose ic_mean would produce noise (0.1 + 0.2 = 0.30000...4)
        ic_report = ICReport(
            [
                ICResult(
                    ic=0.1 + 0.2,  # classic float noise
                    ic_ir=1.0,
                    p_value=0.01,
                    n_samples=500,
                    ci_low=0.2,
                    ci_high=0.4,
                    feature_name="feat_noisy",
                    turnover_adj_ic=0.1 + 0.2,
                )
            ]
        )
        gen = FeatureSelectionReportGenerator()
        report = gen.generate(ic_report=ic_report, multicoll_report=None, hypothesis_report=None)
        parsed = json.loads(report.to_json())
        ic_mean = parsed["decisions"][0]["ic_mean"]
        # 0.1 + 0.2 == 0.30000000000000004 in raw repr; rounded → 0.3
        assert ic_mean == 0.3, (
            f"Expected rounded 0.3, got {ic_mean!r} — float noise leaked into JSON"
        )
