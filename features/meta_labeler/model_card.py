"""Phase 4.6 - Model Card schema (v1) + validator.

Per ADR-0005 D6 and PHASE_4_SPEC §3.6, every serialised Meta-Labeler
artifact ships a JSON model card alongside its ``.joblib`` binary.
The card documents the exact training provenance (commit SHA,
dataset hash, CPCV splits, hyperparameters) plus the seven-gate
verdict from Phase 4.5 validation so a downstream auditor can
reconstruct the training run without reading the pickle.

Schema v1 is defined here as a :class:`typing.TypedDict`. Validation
is performed by :func:`validate_model_card` which raises
``ValueError`` on any violation - no silent-pass is allowed per
ADR-0005 D6.

References:
    ADR-0005 (Meta-Labeling and Fusion Methodology), D6.
    PHASE_4_SPEC §3.6.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Final, Literal, TypedDict

__all__ = [
    "ALLOWED_MODEL_TYPES",
    "ModelCardV1",
    "validate_model_card",
]


# ADR-0005 D6: schema v1 freezes the model_type set at two sklearn
# estimators. Any other estimator requires a schema bump (v2) and an
# ADR amendment, which is why the validator explicitly rejects v != 1.
ALLOWED_MODEL_TYPES: Final[frozenset[str]] = frozenset(
    {"RandomForestClassifier", "LogisticRegression"}
)

_REQUIRED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "model_type",
        "hyperparameters",
        "training_date_utc",
        "training_commit_sha",
        "training_dataset_hash",
        "cpcv_splits_used",
        "features_used",
        "sample_weight_scheme",
        "gates_measured",
        "gates_passed",
        "baseline_auc_logreg",
        "notes",
    }
)

# 40-char lowercase hex - ``git rev-parse HEAD`` never emits uppercase
# on a clean install, so we reject uppercase to keep the on-disk
# representation canonical.
_COMMIT_SHA_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_DATASET_HASH_PATTERN: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")


class ModelCardV1(TypedDict):
    """Frozen schema for a serialised Meta-Labeler artifact.

    All fields are required. The validator rejects any card that
    omits one or carries an extra. See
    :func:`validate_model_card` for the per-field contract.
    """

    schema_version: Literal[1]
    model_type: str
    hyperparameters: dict[str, Any]
    training_date_utc: str
    training_commit_sha: str
    training_dataset_hash: str
    cpcv_splits_used: list[list[list[int]]]
    features_used: list[str]
    sample_weight_scheme: str
    gates_measured: dict[str, float]
    gates_passed: dict[str, bool]
    baseline_auc_logreg: float
    notes: str


def validate_model_card(card: dict[str, Any]) -> ModelCardV1:
    """Validate a model-card dict against schema v1.

    Per ADR-0005 D6: any violation raises ``ValueError`` with a
    message naming the failing field. No silent-pass.

    Args:
        card: Candidate card dict. Typically parsed from JSON at
            load time, or constructed in-memory at save time.

    Returns:
        The same dict, narrowed to :class:`ModelCardV1`. Returning
        the narrowed value lets type-checkers treat the output as
        schema-compliant without a ``cast``.

    Raises:
        ValueError: on any schema violation.
    """
    if not isinstance(card, dict):
        raise ValueError(f"card must be a dict, got {type(card).__name__}")

    _check_key_set(card)

    # 1. schema_version - explicit v1 lock. Even "2" (str) or 2 (int)
    # must fail, because future v2 readers will have their own
    # validator and accepting v2 here would silently degrade.
    schema_version = card["schema_version"]
    if schema_version != 1:
        raise ValueError(
            f"schema_version must be 1 (ModelCardV1 only supports v1); "
            f"got {schema_version!r}. A v2 card requires a new validator."
        )

    # 2. model_type
    model_type = card["model_type"]
    if not isinstance(model_type, str):
        raise ValueError(f"model_type must be str, got {type(model_type).__name__}")
    if model_type not in ALLOWED_MODEL_TYPES:
        raise ValueError(
            f"model_type must be one of {sorted(ALLOWED_MODEL_TYPES)}; got {model_type!r}"
        )

    # 3. hyperparameters
    hp = card["hyperparameters"]
    if not isinstance(hp, dict):
        raise ValueError(f"hyperparameters must be dict, got {type(hp).__name__}")
    _check_json_serialisable(hp, field="hyperparameters")

    # 4. training_date_utc - ISO-8601 with Z suffix
    training_date_utc = card["training_date_utc"]
    if not isinstance(training_date_utc, str):
        raise ValueError(f"training_date_utc must be str, got {type(training_date_utc).__name__}")
    if not training_date_utc.endswith("Z"):
        raise ValueError(
            f"training_date_utc must end with 'Z' per ADR-0005 D6; got {training_date_utc!r}"
        )
    # datetime.fromisoformat accepts "+00:00" in 3.11+ but not "Z" until
    # 3.11. Strip the Z and let fromisoformat parse the rest; on failure,
    # re-raise with a clear message.
    try:
        datetime.fromisoformat(training_date_utc[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(
            f"training_date_utc is not a valid ISO-8601 UTC timestamp: "
            f"{training_date_utc!r} ({exc})"
        ) from exc

    # 5. training_commit_sha - 40 lowercase hex
    commit_sha = card["training_commit_sha"]
    if not isinstance(commit_sha, str):
        raise ValueError(f"training_commit_sha must be str, got {type(commit_sha).__name__}")
    if not _COMMIT_SHA_PATTERN.fullmatch(commit_sha):
        raise ValueError(
            f"training_commit_sha must be exactly 40 lowercase hex chars; "
            f"got {commit_sha!r} (length={len(commit_sha)})"
        )

    # 6. training_dataset_hash - "sha256:" + 64 lowercase hex
    dataset_hash = card["training_dataset_hash"]
    if not isinstance(dataset_hash, str):
        raise ValueError(f"training_dataset_hash must be str, got {type(dataset_hash).__name__}")
    if not _DATASET_HASH_PATTERN.fullmatch(dataset_hash):
        raise ValueError(
            f"training_dataset_hash must match 'sha256:' + 64 lowercase hex; got {dataset_hash!r}"
        )

    # 7. cpcv_splits_used - JSON-serialisable, list of list of list of int
    cpcv = card["cpcv_splits_used"]
    if not isinstance(cpcv, list):
        raise ValueError(f"cpcv_splits_used must be list, got {type(cpcv).__name__}")
    _check_json_serialisable(cpcv, field="cpcv_splits_used")

    # 8. features_used - non-empty, unique, all strings
    features = card["features_used"]
    if not isinstance(features, list) or not features:
        raise ValueError(f"features_used must be a non-empty list; got {features!r}")
    if not all(isinstance(f, str) for f in features):
        raise ValueError("features_used must contain only strings")
    if len(set(features)) != len(features):
        raise ValueError(f"features_used must not contain duplicates; got {features!r}")

    # 9. sample_weight_scheme
    sws = card["sample_weight_scheme"]
    if not isinstance(sws, str):
        raise ValueError(f"sample_weight_scheme must be str, got {type(sws).__name__}")

    # 10. gates_measured - dict[str, float]
    gm = card["gates_measured"]
    if not isinstance(gm, dict):
        raise ValueError(f"gates_measured must be dict, got {type(gm).__name__}")
    for k, v in gm.items():
        if not isinstance(k, str):
            raise ValueError(f"gates_measured keys must be str; got {type(k).__name__}")
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError(f"gates_measured[{k!r}] must be numeric; got {type(v).__name__}")

    # 11. gates_passed - dict[str, bool], must contain "aggregate",
    # and the aggregate bool must equal AND of the per-gate bools.
    gp = card["gates_passed"]
    if not isinstance(gp, dict):
        raise ValueError(f"gates_passed must be dict, got {type(gp).__name__}")
    for k, v in gp.items():
        if not isinstance(k, str):
            raise ValueError(f"gates_passed keys must be str; got {type(k).__name__}")
        if not isinstance(v, bool):
            raise ValueError(f"gates_passed[{k!r}] must be bool; got {type(v).__name__}")
    if "aggregate" not in gp:
        raise ValueError("gates_passed must contain the key 'aggregate'")
    per_gate = [v for k, v in gp.items() if k != "aggregate"]
    expected_aggregate = all(per_gate) if per_gate else False
    if gp["aggregate"] is not expected_aggregate:
        raise ValueError(
            f"gates_passed['aggregate'] must equal the AND of all per-gate "
            f"entries; got {gp['aggregate']} but expected {expected_aggregate}"
        )

    # 12. baseline_auc_logreg - [0, 1]
    bal = card["baseline_auc_logreg"]
    if isinstance(bal, bool) or not isinstance(bal, (int, float)):
        raise ValueError(f"baseline_auc_logreg must be numeric; got {type(bal).__name__}")
    if not (0.0 <= float(bal) <= 1.0):
        raise ValueError(f"baseline_auc_logreg must lie in [0, 1]; got {bal}")

    # 13. notes
    notes = card["notes"]
    if not isinstance(notes, str):
        raise ValueError(f"notes must be str, got {type(notes).__name__}")

    # Final guarantee: the whole card round-trips through json.dumps
    # without loss. This catches exotic values (sets, numpy scalars, ...)
    # that might have slipped past individual checks.
    _check_json_serialisable(card, field="<card>")

    return card  # type: ignore[return-value]


def _check_key_set(card: dict[str, Any]) -> None:
    """Reject cards with missing or extra keys."""
    actual = set(card.keys())
    missing = _REQUIRED_KEYS - actual
    extras = actual - _REQUIRED_KEYS
    if missing or extras:
        parts = []
        if missing:
            parts.append(f"missing={sorted(missing)}")
        if extras:
            parts.append(f"extras={sorted(extras)}")
        raise ValueError(f"model card key-set mismatch: {'; '.join(parts)}")


def _check_json_serialisable(value: object, *, field: str) -> None:
    """Ensure ``value`` is round-trippable through ``json.dumps``.

    Catches numpy scalars, sets, tuples-of-tuples-of-..., datetimes,
    and any other exotic types before they reach disk.
    """
    try:
        json.dumps(value, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not JSON-serialisable: {exc}") from exc
