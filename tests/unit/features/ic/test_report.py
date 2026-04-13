"""Tests for features.ic.report — ICReport JSON and Markdown output."""

from __future__ import annotations

import json

from features.ic.base import ICResult
from features.ic.report import ICReport


def _make_result(
    feature_name: str = "test_feat",
    ic: float = 0.05,
    ic_ir: float = 0.6,
    is_keep: bool = True,
) -> ICResult:
    """Helper to create a populated ICResult."""
    return ICResult(
        ic=ic,
        ic_ir=ic_ir,
        p_value=0.01,
        n_samples=200,
        ci_low=ic - 0.02,
        ci_high=ic + 0.02,
        feature_name=feature_name,
        ic_std=0.08,
        ic_t_stat=3.5 if is_keep else 0.5,
        ic_hit_rate=0.65,
        turnover_adj_ic=ic - 0.001,
        ic_decay=(ic, ic * 0.8, ic * 0.5, ic * 0.2),
        is_significant=is_keep,
        horizon_bars=1,
        newey_west_lags=0,
    )


class TestICReport:
    """ICReport generates valid JSON and Markdown."""

    def test_to_json_parseable(self) -> None:
        results = [_make_result("a"), _make_result("b")]
        report = ICReport(results)
        parsed = json.loads(report.to_json())
        assert len(parsed) == 2
        assert parsed[0]["feature_name"] == "a"
        assert "decision" in parsed[0]

    def test_to_markdown_columns(self) -> None:
        results = [_make_result("feat_x")]
        report = ICReport(results)
        md = report.to_markdown()
        for col in ("Feature", "Horizon", "IC", "IC_IR", "t-stat", "p-value", "Decision"):
            assert col in md

    def test_decision_respects_thresholds(self) -> None:
        """KEEP when |IC|>=0.02 AND IC_IR>=0.50; REJECT otherwise."""
        keep = _make_result(ic=0.05, ic_ir=0.60, is_keep=True)
        reject = _make_result(ic=0.01, ic_ir=0.30, is_keep=False)
        report = ICReport([keep, reject])
        parsed = json.loads(report.to_json())
        assert parsed[0]["decision"] == "KEEP"
        assert parsed[1]["decision"] == "REJECT"

    def test_empty_results(self) -> None:
        report = ICReport([])
        assert "No IC results" in report.to_markdown()
        parsed = json.loads(report.to_json())
        assert parsed == []

    def test_summary_table(self) -> None:
        results = [_make_result("a"), _make_result("b", ic=0.01, ic_ir=0.3)]
        report = ICReport(results)
        df = report.summary_table()
        assert len(df) == 2
        assert set(df.columns) >= {"feature", "ic", "ic_ir", "decision"}
