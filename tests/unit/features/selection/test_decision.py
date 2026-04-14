"""Tests for SelectionDecision frozen dataclass."""

from __future__ import annotations

import json

import pytest

from features.selection.decision import SelectionDecision


def _make_keep_decision(**overrides: object) -> SelectionDecision:
    """Build a keep decision with sensible defaults."""
    defaults: dict[str, object] = {
        "feature_name": "har_rv_signal",
        "calculator": "HAR-RV",
        "decision": "keep",
        "ic_mean": 0.08,
        "ic_ir": 1.5,
        "ic_turnover_adj": 0.07,
        "ic_p_value": 0.001,
        "vif": 1.5,
        "cluster_id": 1,
        "is_cluster_keeper": True,
        "sharpe_ratio": 1.8,
        "psr": 0.97,
        "dsr": 0.96,
        "min_trl": 200,
        "p_value_holm": 0.01,
        "pbo_of_final_set": 0.05,
        "reject_reasons": [],
    }
    defaults.update(overrides)
    return SelectionDecision(**defaults)


class TestSelectionDecisionFrozen:
    """SelectionDecision must be immutable."""

    def test_frozen(self) -> None:
        d = _make_keep_decision()
        with pytest.raises(AttributeError):
            d.decision = "reject"  # type: ignore[misc]

    def test_frozen_reject_reasons(self) -> None:
        d = _make_keep_decision()
        with pytest.raises(AttributeError):
            d.reject_reasons = ["foo"]  # type: ignore[misc]


class TestSelectionDecisionToDict:
    """to_dict() must produce JSON-serializable output."""

    def test_json_serializable(self) -> None:
        d = _make_keep_decision()
        result = d.to_dict()
        # Must not raise
        serialized = json.dumps(result)
        roundtrip = json.loads(serialized)
        assert roundtrip["feature_name"] == "har_rv_signal"
        assert roundtrip["decision"] == "keep"

    def test_all_fields_present(self) -> None:
        d = _make_keep_decision()
        result = d.to_dict()
        expected_keys = {
            "feature_name",
            "calculator",
            "decision",
            "ic_mean",
            "ic_ir",
            "ic_turnover_adj",
            "ic_p_value",
            "vif",
            "cluster_id",
            "is_cluster_keeper",
            "sharpe_ratio",
            "psr",
            "dsr",
            "min_trl",
            "p_value_holm",
            "pbo_of_final_set",
            "reject_reasons",
        }
        assert set(result.keys()) == expected_keys

    def test_none_values_serialize(self) -> None:
        d = _make_keep_decision(
            vif=None,
            cluster_id=None,
            is_cluster_keeper=None,
            ic_turnover_adj=None,
        )
        result = d.to_dict()
        serialized = json.dumps(result)
        roundtrip = json.loads(serialized)
        assert roundtrip["vif"] is None
        assert roundtrip["ic_turnover_adj"] is None

    def test_reject_reasons_copy(self) -> None:
        reasons = ["dsr=0.80 < 0.95"]
        d = SelectionDecision(
            feature_name="x",
            calculator="X",
            decision="reject",
            ic_mean=0.01,
            ic_ir=0.3,
            ic_turnover_adj=None,
            ic_p_value=0.5,
            vif=None,
            cluster_id=None,
            is_cluster_keeper=None,
            sharpe_ratio=None,
            psr=None,
            dsr=None,
            min_trl=None,
            p_value_holm=None,
            pbo_of_final_set=None,
            reject_reasons=reasons,
        )
        result = d.to_dict()
        # Mutating the output must not affect the dataclass
        result["reject_reasons"].append("extra")
        assert len(d.reject_reasons) == 1
