"""Generate the Phase 4.6 Meta-Labeler persistence report.

End-to-end demo of the save-load-predict round-trip contract defined
in ADR-0005 D6 and PHASE_4_SPEC §3.6. Pipeline:

1. Build the same synthetic ``(features, y, weights)`` tuple as
   Phases 4.3 - 4.5 (``_BAR_DRIFT_PER_SIGMA`` + ``ofi_signal``).
2. Fit a single ``RandomForestClassifier`` with the 4.3 default
   hyperparameters.
3. Hash the training dataset via
   :func:`~features.meta_labeler.persistence.compute_dataset_hash`.
4. Assemble a :class:`~features.meta_labeler.model_card.ModelCardV1`
   dict sourced from the 4.5 report's gates (read from
   ``reports/phase_4_5/validation_report.json`` when present, or
   synthesised when not).
5. Serialise via :func:`save_model` into
   ``models/meta_labeler/`` (gitignored).
6. Re-load via :func:`load_model` and verify the bit-exact
   round-trip on 1000 fixed rows.
7. Emit ``reports/phase_4_6/persistence_report.{md,json}`` with the
   verdict and the card snapshot.

Reproducibility follows the 4.4 / 4.5 contract:
    - ``APEX_SEED`` (default 42) seeds numpy + sklearn.
    - ``APEX_REPORT_NOW`` freezes the ``generated_at`` header.
    - ``APEX_REPORT_WALLCLOCK_MODE`` ∈ {record, zero, omit}.

Usage:

    APEX_SEED=42 \\
      APEX_REPORT_NOW=2026-04-15T00:00:00+00:00 \\
      APEX_REPORT_WALLCLOCK_MODE=omit \\
      python3 scripts/generate_phase_4_6_report.py

The script is a *demo*, not a gate: CI exercises ``save_model`` /
``load_model`` via the unit tests. The script exists so reviewers can
see an end-to-end artifact and so the generator stays alive as the
underlying modules evolve.

References:
    PHASE_4_SPEC §3.6.
    ADR-0005 D6.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import structlog
from sklearn.ensemble import RandomForestClassifier

from features.meta_labeler.feature_builder import FEATURE_NAMES
from features.meta_labeler.model_card import ModelCardV1
from features.meta_labeler.persistence import (
    compute_dataset_hash,
    get_head_commit_sha,
    is_working_tree_clean,
    load_model,
    save_model,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "reports" / "phase_4_6"
MODELS_DIR = REPO_ROOT / "models" / "meta_labeler"
PHASE_4_5_JSON = REPO_ROOT / "reports" / "phase_4_5" / "validation_report.json"

_log = structlog.get_logger(__name__)


# ----------------------------------------------------------------------
# Header helpers (shared contract with the 4.3/4.4/4.5 reports)
# ----------------------------------------------------------------------


def _resolve_generated_at() -> str:
    override = os.environ.get("APEX_REPORT_NOW")
    if override is not None:
        try:
            parsed = datetime.fromisoformat(override)
        except ValueError as exc:
            raise ValueError(f"APEX_REPORT_NOW={override!r} is not ISO 8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("APEX_REPORT_NOW must include a timezone offset (e.g. '...+00:00')")
        return parsed.isoformat()
    return datetime.now(tz=UTC).isoformat()


def _resolve_wallclock(measured: float) -> float | None:
    mode = os.environ.get("APEX_REPORT_WALLCLOCK_MODE", "record").lower()
    if mode == "record":
        return float(measured)
    if mode == "zero":
        return 0.0
    if mode == "omit":
        return None
    raise ValueError(f"APEX_REPORT_WALLCLOCK_MODE={mode!r} not in {{'record', 'zero', 'omit'}}")


def _resolve_training_date_utc() -> str:
    """Training date is frozen to the report's ``generated_at`` for
    byte-deterministic output. Converts any ``+00:00`` offset to ``Z``
    to satisfy the model-card schema's Z-suffix rule.
    """
    iso = _resolve_generated_at()
    if iso.endswith("+00:00"):
        iso = iso[:-6] + "Z"
    elif not iso.endswith("Z"):
        raise ValueError(f"APEX_REPORT_NOW must resolve to a UTC timestamp; got {iso!r}")
    return iso


# ----------------------------------------------------------------------
# Synthetic data (same generator as 4.3/4.4/4.5 without the P&L path)
# ----------------------------------------------------------------------


def _synthetic_training_set(
    n: int, seed: int
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.int_]]:
    rng = np.random.default_rng(seed)
    n_feat = len(FEATURE_NAMES)
    x_mat: npt.NDArray[np.float64] = rng.standard_normal((n, n_feat)).astype(np.float64)
    # Alpha concentrated in column 2 (ofi_signal) to mimic 4.3/4.4 fixtures.
    logits = 0.35 * x_mat[:, 2] + 0.1 * rng.standard_normal(n)
    y = (logits > 0).astype(np.int_)
    return x_mat, y


# ----------------------------------------------------------------------
# Model card assembly
# ----------------------------------------------------------------------


def _load_phase_4_5_gates() -> tuple[dict[str, float], dict[str, bool], float]:
    """Pull gates from the 4.5 report if present; else synthesise defaults.

    Returns ``(gates_measured, gates_passed, baseline_auc_logreg)``.
    """
    gates_measured: dict[str, float] = {}
    gates_passed: dict[str, bool] = {}
    if not PHASE_4_5_JSON.exists():
        _log.info("phase_4_5_report_missing", path=str(PHASE_4_5_JSON))
        gates_measured = {
            "G1_mean_auc": 0.58,
            "G2_min_auc": 0.53,
            "G3_dsr": 0.97,
            "G4_pbo": 0.07,
            "G5_brier": 0.22,
            "G6_minority_freq": 0.18,
            "G7_auc_over_logreg": 0.04,
        }
        gates_passed = dict.fromkeys(("G1", "G2", "G3", "G4", "G5", "G6", "G7"), True)
        gates_passed["aggregate"] = True
        return gates_measured, gates_passed, 0.54

    data = json.loads(PHASE_4_5_JSON.read_text(encoding="utf-8"))
    for g in data.get("gates", []):
        name = g["name"]
        gates_measured[name] = float(g["measured"])
        gates_passed[name] = bool(g["passed"])
    gates_passed["aggregate"] = bool(data.get("all_passed", all(gates_passed.values())))
    baseline = float(data.get("baseline_auc_logreg", 0.54))
    return gates_measured, gates_passed, baseline


def _build_card(
    *,
    hyperparameters: dict[str, Any],
    dataset_hash: str,
    commit_sha: str,
    training_date_utc: str,
) -> ModelCardV1:
    gates_measured, gates_passed, baseline = _load_phase_4_5_gates()
    card: ModelCardV1 = {
        "schema_version": 1,
        "model_type": "RandomForestClassifier",
        "hyperparameters": hyperparameters,
        "training_date_utc": training_date_utc,
        "training_commit_sha": commit_sha,
        "training_dataset_hash": dataset_hash,
        "cpcv_splits_used": [],
        "features_used": list(FEATURE_NAMES),
        "sample_weight_scheme": "uniform",
        "gates_measured": gates_measured,
        "gates_passed": gates_passed,
        "baseline_auc_logreg": baseline,
        "notes": (
            "Phase 4.6 persistence demo run. Synthetic alpha concentrated in "
            "ofi_signal; gates sourced from reports/phase_4_5/validation_report.json "
            "when available, else synthesised defaults."
        ),
    }
    return card


# ----------------------------------------------------------------------
# Report emission
# ----------------------------------------------------------------------


def _write_report(
    *,
    card: ModelCardV1,
    model_path: Path,
    card_path: Path,
    generated_at: str,
    wallclock: float | None,
    round_trip_passed: bool,
) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "generated_at": generated_at,
        "round_trip_bit_exact": round_trip_passed,
        "model_path": str(model_path.relative_to(REPO_ROOT)),
        "card_path": str(card_path.relative_to(REPO_ROOT)),
        "card": card,
    }
    if wallclock is not None:
        payload["wall_clock_seconds"] = wallclock

    json_path = REPORT_DIR / "persistence_report.json"
    json_path.write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    md_lines = [
        "# Phase 4.6 — Persistence Round-Trip Report",
        "",
        f"**Generated at**: `{generated_at}`",
        "",
        f"**Round-trip bit-exact**: `{round_trip_passed}`",
        "",
        f"- Model: `{payload['model_path']}`",
        f"- Card:  `{payload['card_path']}`",
        f"- Training commit SHA: `{card['training_commit_sha']}`",
        f"- Training dataset hash: `{card['training_dataset_hash']}`",
        "",
        "## Card snapshot",
        "",
        "```json",
        json.dumps(card, sort_keys=True, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    md_path = REPORT_DIR / "persistence_report.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


def main() -> None:
    seed = int(os.environ.get("APEX_SEED", "42"))
    os.environ.setdefault("APEX_SEED", str(seed))
    generated_at = _resolve_generated_at()
    start = time.perf_counter()

    if not is_working_tree_clean():
        raise SystemExit(
            "git working tree is dirty; Phase 4.6 report requires a clean "
            "tree to guarantee reproducible training provenance (ADR-0005 D6)."
        )
    commit_sha = get_head_commit_sha()

    x_mat, y = _synthetic_training_set(n=600, seed=seed)
    hyperparameters: dict[str, Any] = {
        "n_estimators": 200,
        "max_depth": 10,
        "min_samples_leaf": 5,
        "random_state": seed,
        "n_jobs": 1,
    }
    rf = RandomForestClassifier(**hyperparameters)
    rf.fit(x_mat, y)

    dataset_hash = compute_dataset_hash(list(FEATURE_NAMES), x_mat, y)
    card = _build_card(
        hyperparameters=hyperparameters,
        dataset_hash=dataset_hash,
        commit_sha=commit_sha,
        training_date_utc=_resolve_training_date_utc(),
    )

    model_path, card_path = save_model(rf, card, MODELS_DIR)
    loaded, _ = load_model(model_path, card_path)

    # Bit-exact check on 1000 fixed rows.
    rng = np.random.default_rng(seed)
    x_fixture: npt.NDArray[np.float64] = rng.standard_normal((1000, len(FEATURE_NAMES)))
    round_trip_passed = bool(
        np.array_equal(rf.predict_proba(x_fixture), loaded.predict_proba(x_fixture))
    )

    wallclock = _resolve_wallclock(time.perf_counter() - start)
    _write_report(
        card=card,
        model_path=model_path,
        card_path=card_path,
        generated_at=generated_at,
        wallclock=wallclock,
        round_trip_passed=round_trip_passed,
    )
    _log.info(
        "phase_4_6_report_written",
        round_trip_passed=round_trip_passed,
        model_path=str(model_path),
    )
    if not round_trip_passed:
        raise SystemExit("Phase 4.6 round-trip FAILED — non-bit-exact predictions detected.")


if __name__ == "__main__":
    main()
