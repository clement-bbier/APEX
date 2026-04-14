"""Tests for :mod:`features.integration.config`."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from features.integration.config import FeatureActivationConfig


def _write_report(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "feature_selection_report.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _minimal_payload() -> dict[str, object]:
    return {
        "decisions": [
            {"feature_name": "gex_signal", "decision": "keep"},
            {"feature_name": "har_rv_signal", "decision": "keep"},
            {"feature_name": "cvd_signal", "decision": "reject"},
        ],
        "generated_at": "2026-04-14T00:05:46Z",
        "pbo_of_final_set": 0.05,
    }


class TestFromReportJson:
    """Loading the JSON report."""

    def test_parses_keep_and_reject_sets(self, tmp_path: Path) -> None:
        path = _write_report(tmp_path, _minimal_payload())

        cfg = FeatureActivationConfig.from_report_json(path)

        assert cfg.activated_features == frozenset({"gex_signal", "har_rv_signal"})
        assert cfg.rejected_features == frozenset({"cvd_signal"})
        assert cfg.pbo_of_final_set == 0.05
        assert cfg.generated_at == datetime(2026, 4, 14, 0, 5, 46, tzinfo=UTC)

    def test_parses_real_phase_3_12_report(self) -> None:
        path = Path("reports/phase_3_12/feature_selection_report.json")
        if not path.exists():
            pytest.skip("Phase 3.12 report not generated in this workspace")

        cfg = FeatureActivationConfig.from_report_json(path)

        assert "gex_signal" in cfg.activated_features
        assert "har_rv_signal" in cfg.activated_features
        assert "ofi_signal" in cfg.activated_features
        assert cfg.activated_features.isdisjoint(cfg.rejected_features)

    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        path = tmp_path / "does_not_exist.json"

        with pytest.raises(FileNotFoundError):
            FeatureActivationConfig.from_report_json(path)

    def test_malformed_json_raises_value_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")

        with pytest.raises(ValueError, match="not valid JSON"):
            FeatureActivationConfig.from_report_json(path)

    def test_unknown_decision_value_raises(self, tmp_path: Path) -> None:
        payload = _minimal_payload()
        payload["decisions"] = [{"feature_name": "x", "decision": "maybe"}]
        path = _write_report(tmp_path, payload)

        with pytest.raises(ValueError, match="Unknown decision"):
            FeatureActivationConfig.from_report_json(path)

    def test_missing_feature_name_raises(self, tmp_path: Path) -> None:
        payload = _minimal_payload()
        payload["decisions"] = [{"decision": "keep"}]
        path = _write_report(tmp_path, payload)

        with pytest.raises(ValueError, match="feature_name"):
            FeatureActivationConfig.from_report_json(path)

    def test_payload_not_object_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")

        with pytest.raises(ValueError, match="must be a JSON object"):
            FeatureActivationConfig.from_report_json(path)

    def test_decisions_not_list_raises(self, tmp_path: Path) -> None:
        path = _write_report(
            tmp_path, {"decisions": "oops", "generated_at": "2026-04-14T00:00:00Z"}
        )

        with pytest.raises(ValueError, match="must be a list"):
            FeatureActivationConfig.from_report_json(path)

    def test_decision_entry_not_dict_raises(self, tmp_path: Path) -> None:
        payload = _minimal_payload()
        payload["decisions"] = ["not a dict"]
        path = _write_report(tmp_path, payload)

        with pytest.raises(ValueError, match="must be a JSON object"):
            FeatureActivationConfig.from_report_json(path)

    def test_generated_at_missing_raises(self, tmp_path: Path) -> None:
        payload = _minimal_payload()
        del payload["generated_at"]
        path = _write_report(tmp_path, payload)

        with pytest.raises(ValueError, match="generated_at"):
            FeatureActivationConfig.from_report_json(path)

    def test_generated_at_invalid_iso_raises(self, tmp_path: Path) -> None:
        payload = _minimal_payload()
        payload["generated_at"] = "not-a-date"
        path = _write_report(tmp_path, payload)

        with pytest.raises(ValueError, match="Invalid ISO-8601"):
            FeatureActivationConfig.from_report_json(path)

    def test_pbo_null_is_tolerated(self, tmp_path: Path) -> None:
        payload = _minimal_payload()
        payload["pbo_of_final_set"] = None
        path = _write_report(tmp_path, payload)

        cfg = FeatureActivationConfig.from_report_json(path)

        assert cfg.pbo_of_final_set is None

    def test_pbo_non_number_raises(self, tmp_path: Path) -> None:
        payload = _minimal_payload()
        payload["pbo_of_final_set"] = "high"
        path = _write_report(tmp_path, payload)

        with pytest.raises(ValueError, match="pbo_of_final_set"):
            FeatureActivationConfig.from_report_json(path)

    def test_duplicate_feature_name_different_decisions_raises(self, tmp_path: Path) -> None:
        """Duplicate feature_name with conflicting decisions must fail loud."""
        payload = _minimal_payload()
        payload["decisions"] = [
            {"feature_name": "ofi_signal", "decision": "keep"},
            {"feature_name": "ofi_signal", "decision": "reject"},
        ]
        path = _write_report(tmp_path, payload)

        with pytest.raises(ValueError, match="Duplicate feature_name"):
            FeatureActivationConfig.from_report_json(path)

    def test_duplicate_feature_name_same_decision_raises(self, tmp_path: Path) -> None:
        """Even same-decision duplicates fail loud (schema violation)."""
        payload = _minimal_payload()
        payload["decisions"] = [
            {"feature_name": "ofi_signal", "decision": "keep"},
            {"feature_name": "ofi_signal", "decision": "keep"},
        ]
        path = _write_report(tmp_path, payload)

        with pytest.raises(ValueError, match="Duplicate feature_name"):
            FeatureActivationConfig.from_report_json(path)

    def test_naive_timestamp_rejected(self, tmp_path: Path) -> None:
        """UTC-only rule: timezone-naive timestamps must fail loud."""
        payload = _minimal_payload()
        payload["generated_at"] = "2026-04-14T12:00:00"  # no TZ
        path = _write_report(tmp_path, payload)

        with pytest.raises(ValueError, match="timezone-naive"):
            FeatureActivationConfig.from_report_json(path)

    def test_utc_offset_forms_accepted(self, tmp_path: Path) -> None:
        """Both 'Z' and '+00:00' forms accepted; result normalised to UTC."""
        for i, ts in enumerate(("2026-04-14T12:00:00Z", "2026-04-14T12:00:00+00:00")):
            subdir = tmp_path / f"case_{i}"
            subdir.mkdir()
            payload = _minimal_payload()
            payload["generated_at"] = ts
            path = _write_report(subdir, payload)

            cfg = FeatureActivationConfig.from_report_json(path)

            assert cfg.generated_at.tzinfo is not None
            offset = cfg.generated_at.tzinfo.utcoffset(cfg.generated_at)
            assert offset is not None
            assert offset.total_seconds() == 0

    def test_empty_activated_set_is_valid(self, tmp_path: Path) -> None:
        payload = _minimal_payload()
        payload["decisions"] = [{"feature_name": "x", "decision": "reject"}]
        path = _write_report(tmp_path, payload)

        cfg = FeatureActivationConfig.from_report_json(path)

        assert cfg.activated_features == frozenset()
        assert cfg.rejected_features == frozenset({"x"})


class TestFrozenSemantics:
    """Immutability of the config object."""

    def test_is_frozen_dataclass(self, tmp_path: Path) -> None:
        path = _write_report(tmp_path, _minimal_payload())
        cfg = FeatureActivationConfig.from_report_json(path)

        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.activated_features = frozenset()  # type: ignore[misc]

    def test_activated_is_frozenset(self, tmp_path: Path) -> None:
        path = _write_report(tmp_path, _minimal_payload())
        cfg = FeatureActivationConfig.from_report_json(path)

        assert isinstance(cfg.activated_features, frozenset)
        assert isinstance(cfg.rejected_features, frozenset)


class TestIsActivated:
    """Query helper."""

    def test_returns_true_for_kept_feature(self, tmp_path: Path) -> None:
        path = _write_report(tmp_path, _minimal_payload())
        cfg = FeatureActivationConfig.from_report_json(path)

        assert cfg.is_activated("gex_signal") is True

    def test_returns_false_for_rejected_feature(self, tmp_path: Path) -> None:
        path = _write_report(tmp_path, _minimal_payload())
        cfg = FeatureActivationConfig.from_report_json(path)

        assert cfg.is_activated("cvd_signal") is False

    def test_returns_false_for_unknown_feature(self, tmp_path: Path) -> None:
        path = _write_report(tmp_path, _minimal_payload())
        cfg = FeatureActivationConfig.from_report_json(path)

        assert cfg.is_activated("definitely_not_a_feature") is False
