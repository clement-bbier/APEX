"""Unit tests for :mod:`features.meta_labeler.model_card`.

Coverage target: ≥ 94 % on ``model_card.py``.

The suite covers every branch of :func:`validate_model_card`:
- happy path (returns a valid v1 card unchanged)
- every required-key-missing / extra-key case
- type and value contracts for each field
- the cross-field invariant on ``gates_passed['aggregate']``
- explicit rejection of ``schema_version == 2``
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from features.meta_labeler.model_card import (
    ALLOWED_MODEL_TYPES,
    validate_model_card,
)

# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _valid_card() -> dict[str, Any]:
    """Return a freshly-constructed valid v1 card dict.

    Tests mutate a copy of this baseline to exercise individual
    validation branches without cross-contaminating other tests.
    """
    return {
        "schema_version": 1,
        "model_type": "RandomForestClassifier",
        "hyperparameters": {
            "n_estimators": 200,
            "max_depth": 10,
            "min_samples_leaf": 5,
            "random_state": 42,
        },
        "training_date_utc": "2026-05-01T14:30:00Z",
        "training_commit_sha": "4cbbdfca9f2e1d7a6e3b0c8f9a2d1e4b5c6a7f8d",
        "training_dataset_hash": (
            "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "cpcv_splits_used": [[[0, 1, 2], [3, 4]]],
        "features_used": [
            "gex_signal",
            "har_rv_signal",
            "ofi_signal",
            "regime_vol_code",
            "regime_trend_code",
            "realized_vol_28d",
            "hour_of_day_sin",
            "day_of_week_sin",
        ],
        "sample_weight_scheme": "uniqueness_x_return_attribution",
        "gates_measured": {
            "G1_mean_auc": 0.581,
            "G2_min_auc": 0.534,
            "G3_dsr": 0.972,
            "G4_pbo": 0.073,
            "G5_brier": 0.223,
            "G6_minority_freq": 0.18,
            "G7_auc_over_logreg": 0.041,
        },
        "gates_passed": {
            "G1": True,
            "G2": True,
            "G3": True,
            "G4": True,
            "G5": True,
            "G6": True,
            "G7": True,
            "aggregate": True,
        },
        "baseline_auc_logreg": 0.54,
        "notes": "example",
    }


# ----------------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------------


def test_validate_returns_valid_card_unchanged() -> None:
    card = _valid_card()
    out = validate_model_card(card)
    assert out is card  # validator narrows-in-place, no copy


def test_validate_accepts_logistic_regression_model_type() -> None:
    card = _valid_card()
    card["model_type"] = "LogisticRegression"
    card["gates_passed"] = {"G1": True, "aggregate": True}
    validate_model_card(card)  # does not raise


def test_allowed_model_types_contract() -> None:
    # Schema v1 locks the set - guard against accidental expansion.
    assert ALLOWED_MODEL_TYPES == {"RandomForestClassifier", "LogisticRegression"}


# ----------------------------------------------------------------------
# Schema version
# ----------------------------------------------------------------------


def test_card_schema_version_1_rejects_2() -> None:
    card = _valid_card()
    card["schema_version"] = 2
    with pytest.raises(ValueError, match=r"schema_version must be 1"):
        validate_model_card(card)


def test_schema_version_rejects_string_one() -> None:
    card = _valid_card()
    card["schema_version"] = "1"
    with pytest.raises(ValueError, match=r"schema_version must be 1"):
        validate_model_card(card)


# ----------------------------------------------------------------------
# Key-set integrity
# ----------------------------------------------------------------------


def test_card_required_fields_all_present() -> None:
    card = _valid_card()
    del card["notes"]
    with pytest.raises(ValueError, match=r"missing=\['notes'\]"):
        validate_model_card(card)


def test_extra_keys_are_rejected() -> None:
    card = _valid_card()
    card["extra_field"] = "not allowed"
    with pytest.raises(ValueError, match=r"extras=\['extra_field'\]"):
        validate_model_card(card)


def test_non_dict_card_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"card must be a dict"):
        validate_model_card("not a dict")  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# model_type
# ----------------------------------------------------------------------


def test_model_type_must_be_str() -> None:
    card = _valid_card()
    card["model_type"] = 42
    with pytest.raises(ValueError, match=r"model_type must be str"):
        validate_model_card(card)


def test_model_type_rejects_unknown_estimator() -> None:
    card = _valid_card()
    card["model_type"] = "XGBClassifier"
    with pytest.raises(ValueError, match=r"model_type must be one of"):
        validate_model_card(card)


# ----------------------------------------------------------------------
# hyperparameters
# ----------------------------------------------------------------------


def test_hyperparameters_must_be_dict() -> None:
    card = _valid_card()
    card["hyperparameters"] = [("n_estimators", 200)]
    with pytest.raises(ValueError, match=r"hyperparameters must be dict"):
        validate_model_card(card)


def test_hyperparameters_must_be_json_serialisable() -> None:
    card = _valid_card()
    card["hyperparameters"] = {"some_set": {1, 2, 3}}
    with pytest.raises(ValueError, match=r"hyperparameters is not JSON-serialisable"):
        validate_model_card(card)


# ----------------------------------------------------------------------
# training_date_utc — ISO-8601 with Z suffix
# ----------------------------------------------------------------------


def test_card_iso8601_z_suffix_enforced() -> None:
    card = _valid_card()
    card["training_date_utc"] = "2026-05-01T14:30:00+00:00"
    with pytest.raises(ValueError, match=r"must end with 'Z'"):
        validate_model_card(card)


def test_training_date_must_be_valid_iso() -> None:
    card = _valid_card()
    card["training_date_utc"] = "not-a-dateZ"
    with pytest.raises(ValueError, match=r"not a valid ISO-8601"):
        validate_model_card(card)


def test_training_date_must_be_string() -> None:
    card = _valid_card()
    card["training_date_utc"] = 20260501
    with pytest.raises(ValueError, match=r"training_date_utc must be str"):
        validate_model_card(card)


# ----------------------------------------------------------------------
# training_commit_sha
# ----------------------------------------------------------------------


def test_card_commit_sha_40_chars_required() -> None:
    card = _valid_card()
    card["training_commit_sha"] = "4cbbdfc"  # too short
    with pytest.raises(ValueError, match=r"exactly 40 lowercase hex chars"):
        validate_model_card(card)


def test_commit_sha_rejects_uppercase() -> None:
    card = _valid_card()
    card["training_commit_sha"] = "A" * 40
    with pytest.raises(ValueError, match=r"exactly 40 lowercase hex chars"):
        validate_model_card(card)


def test_commit_sha_must_be_string() -> None:
    card = _valid_card()
    card["training_commit_sha"] = 42
    with pytest.raises(ValueError, match=r"training_commit_sha must be str"):
        validate_model_card(card)


# ----------------------------------------------------------------------
# training_dataset_hash
# ----------------------------------------------------------------------


def test_dataset_hash_must_have_sha256_prefix() -> None:
    card = _valid_card()
    card["training_dataset_hash"] = "0" * 64  # no "sha256:"
    with pytest.raises(ValueError, match=r"must match 'sha256:'"):
        validate_model_card(card)


def test_dataset_hash_must_be_string() -> None:
    card = _valid_card()
    card["training_dataset_hash"] = None
    with pytest.raises(ValueError, match=r"training_dataset_hash must be str"):
        validate_model_card(card)


# ----------------------------------------------------------------------
# features_used
# ----------------------------------------------------------------------


def test_card_feature_names_preserved_order() -> None:
    card = _valid_card()
    original = list(card["features_used"])
    out = validate_model_card(card)
    # Validator must not reorder - downstream hash protocol is
    # order-sensitive so a silent reorder would invalidate the hash.
    assert out["features_used"] == original


def test_features_used_rejects_empty_list() -> None:
    card = _valid_card()
    card["features_used"] = []
    with pytest.raises(ValueError, match=r"features_used must be a non-empty list"):
        validate_model_card(card)


def test_features_used_rejects_duplicates() -> None:
    card = _valid_card()
    card["features_used"] = ["a", "b", "a"]
    with pytest.raises(ValueError, match=r"must not contain duplicates"):
        validate_model_card(card)


def test_features_used_must_be_strings() -> None:
    card = _valid_card()
    card["features_used"] = ["a", 1, "b"]
    with pytest.raises(ValueError, match=r"features_used must contain only strings"):
        validate_model_card(card)


# ----------------------------------------------------------------------
# sample_weight_scheme
# ----------------------------------------------------------------------


def test_sample_weight_scheme_must_be_string() -> None:
    card = _valid_card()
    card["sample_weight_scheme"] = None
    with pytest.raises(ValueError, match=r"sample_weight_scheme must be str"):
        validate_model_card(card)


# ----------------------------------------------------------------------
# gates_measured
# ----------------------------------------------------------------------


def test_gates_measured_must_be_dict() -> None:
    card = _valid_card()
    card["gates_measured"] = [("G1", 0.5)]
    with pytest.raises(ValueError, match=r"gates_measured must be dict"):
        validate_model_card(card)


def test_gates_measured_values_must_be_numeric() -> None:
    card = _valid_card()
    card["gates_measured"]["G1_mean_auc"] = "0.5"
    with pytest.raises(ValueError, match=r"gates_measured\[.*\] must be numeric"):
        validate_model_card(card)


def test_gates_measured_rejects_bool_values() -> None:
    # bool is a subclass of int - explicit guard prevents a True leaking in.
    card = _valid_card()
    card["gates_measured"]["G1_mean_auc"] = True
    with pytest.raises(ValueError, match=r"gates_measured\[.*\] must be numeric"):
        validate_model_card(card)


# ----------------------------------------------------------------------
# gates_passed
# ----------------------------------------------------------------------


def test_card_gates_passed_all_true_when_aggregate_true() -> None:
    card = _valid_card()
    card["gates_passed"]["G1"] = False  # aggregate still True - inconsistent
    with pytest.raises(ValueError, match=r"aggregate.*must equal the AND"):
        validate_model_card(card)


def test_gates_passed_allows_aggregate_false_when_a_gate_fails() -> None:
    card = _valid_card()
    card["gates_passed"]["G1"] = False
    card["gates_passed"]["aggregate"] = False
    validate_model_card(card)  # does not raise


def test_gates_passed_requires_aggregate_key() -> None:
    card = _valid_card()
    del card["gates_passed"]["aggregate"]
    with pytest.raises(ValueError, match=r"must contain the key 'aggregate'"):
        validate_model_card(card)


def test_gates_passed_values_must_be_bool() -> None:
    card = _valid_card()
    card["gates_passed"]["G1"] = 1  # int, not bool
    with pytest.raises(ValueError, match=r"gates_passed\[.*\] must be bool"):
        validate_model_card(card)


def test_gates_passed_must_be_dict() -> None:
    card = _valid_card()
    card["gates_passed"] = [("aggregate", True)]
    with pytest.raises(ValueError, match=r"gates_passed must be dict"):
        validate_model_card(card)


def test_gates_passed_aggregate_only_defaults_false() -> None:
    # When only "aggregate" is present (no per-gate bools),
    # expected_aggregate is False per the validator.
    card = _valid_card()
    card["gates_passed"] = {"aggregate": False}
    validate_model_card(card)  # does not raise


# ----------------------------------------------------------------------
# baseline_auc_logreg
# ----------------------------------------------------------------------


def test_baseline_auc_logreg_rejects_out_of_range() -> None:
    card = _valid_card()
    card["baseline_auc_logreg"] = 1.5
    with pytest.raises(ValueError, match=r"baseline_auc_logreg must lie in"):
        validate_model_card(card)


def test_baseline_auc_logreg_rejects_bool() -> None:
    card = _valid_card()
    card["baseline_auc_logreg"] = True
    with pytest.raises(ValueError, match=r"baseline_auc_logreg must be numeric"):
        validate_model_card(card)


def test_baseline_auc_logreg_accepts_int() -> None:
    card = _valid_card()
    card["baseline_auc_logreg"] = 1
    validate_model_card(card)  # does not raise (int is numeric, within [0,1])


# ----------------------------------------------------------------------
# notes
# ----------------------------------------------------------------------


def test_notes_must_be_string() -> None:
    card = _valid_card()
    card["notes"] = None
    with pytest.raises(ValueError, match=r"notes must be str"):
        validate_model_card(card)


# ----------------------------------------------------------------------
# cpcv_splits_used
# ----------------------------------------------------------------------


def test_cpcv_splits_used_must_be_list() -> None:
    card = _valid_card()
    card["cpcv_splits_used"] = "not a list"
    with pytest.raises(ValueError, match=r"cpcv_splits_used must be list"):
        validate_model_card(card)


# ----------------------------------------------------------------------
# Whole-card JSON round-trip
# ----------------------------------------------------------------------


def test_validated_card_round_trips_through_json() -> None:
    card = _valid_card()
    validated = validate_model_card(card)
    serialised = json.dumps(validated, sort_keys=True)
    parsed = json.loads(serialised)
    # Validating the round-tripped copy must still succeed.
    validate_model_card(parsed)


def test_example_model_card_on_disk_is_valid() -> None:
    # The reference example under docs/examples/ MUST remain schema-valid
    # so consumers copy-pasting it get a working template.
    from pathlib import Path

    example_path = (
        Path(__file__).resolve().parents[4] / "docs" / "examples" / "model_card_v1_example.json"
    )
    card = json.loads(example_path.read_text(encoding="utf-8"))
    validate_model_card(card)


def test_validate_does_not_mutate_deep_copy() -> None:
    # Validator narrows-in-place; the caller's dict should be
    # structurally unchanged (values, types, key order on Python 3.7+).
    card = _valid_card()
    snapshot = copy.deepcopy(card)
    validate_model_card(card)
    assert card == snapshot
