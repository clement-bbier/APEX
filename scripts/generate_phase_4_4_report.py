"""Generate the Phase 4.4 nested-CPCV tuning diagnostic report.

Runs :class:`features.meta_labeler.tuning.NestedCPCVTuner` on a
synthetic dataset with calibrated alpha in ``ofi_signal`` (same
generator as the Phase 4.3 report) and emits Markdown + JSON under
``reports/phase_4_4/``. Two configurations are available:

- **CI / fast** (default): smaller grid + smaller CPCV so the whole
  tune completes in under ~60 s on a single core. Keeps the full run
  deterministic and cheap enough to execute on every PR check.
- **Production** (gated behind ``APEX_FULL_TUNING=1``): the spec
  configuration - 3 x 3 x 2 = 18 trials, Outer C(6, 2) = 15 folds,
  Inner C(4, 1) = 4 folds, n=1200. Approximately 1,350 RF fits.

Usage:

    # Fast / CI report
    APEX_SEED=42 python3 scripts/generate_phase_4_4_report.py

    # Full production run (slow)
    APEX_SEED=42 APEX_FULL_TUNING=1 python3 scripts/generate_phase_4_4_report.py

    # Byte-for-byte reproducible artefact (for audit diffs)
    APEX_SEED=42 APEX_REPORT_NOW=2026-04-14T00:00:00+00:00 \\
        APEX_REPORT_WALLCLOCK_MODE=omit \\
        python3 scripts/generate_phase_4_4_report.py

Reproducibility:
    The two intrinsically time-dependent fields in the report are
    ``generated_at`` (timestamp of the run) and ``wall_clock_seconds``
    (how long ``tune()`` took). By default we record both so operators
    can spot performance regressions across CI runs. Two environment
    variables let downstream audit diffs be byte-for-byte stable:

    - ``APEX_REPORT_NOW``: ISO 8601 timestamp used in place of
      ``datetime.now(UTC)`` for the ``generated_at`` field. Use this
      in audit scripts that diff two report runs for unchanged trial
      ledgers. Invalid / unparseable values fail loud.
    - ``APEX_REPORT_WALLCLOCK_MODE``: ``"record"`` (default, keeps
      ``wall_clock_seconds``), ``"omit"`` (drops the key entirely), or
      ``"zero"`` (forces ``0.0``). Use ``omit`` in audit diffs.

Report contents:

- Header: seed, dataset size, outer/inner CPCV geometry, search space,
  wall-clock, stability index.
- Per-outer-fold winner table: hparams + OOS AUC.
- Top-5 trials across all outer folds by OOS AUC.
- Full trial ledger persisted in ``tuning_trials.json`` for Phase 4.5
  PBO / DSR consumption.

References:
    PHASE_4_SPEC section 3.4 - Nested Hyperparameter Tuning.
    ADR-0005 D4 - Nested CPCV methodology rationale.
    Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*,
    section 7.4 (purged / nested CV).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import structlog

from features.cv.cpcv import CombinatoriallyPurgedKFold
from features.meta_labeler.feature_builder import FEATURE_NAMES, MetaLabelerFeatureSet
from features.meta_labeler.tuning import NestedCPCVTuner, TuningSearchSpace

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "reports" / "phase_4_4"

_log = structlog.get_logger(__name__)


def _resolve_generated_at() -> str:
    """Return the ``generated_at`` header.

    Honors ``APEX_REPORT_NOW`` so audit diffs can freeze the timestamp.
    Unparseable values fail loud rather than silently falling back.
    """
    override = os.environ.get("APEX_REPORT_NOW")
    if override is not None:
        try:
            parsed = datetime.fromisoformat(override)
        except ValueError as exc:
            raise ValueError(
                f"APEX_REPORT_NOW={override!r} is not ISO 8601; refusing to generate report"
            ) from exc
        if parsed.tzinfo is None:
            raise ValueError("APEX_REPORT_NOW must include a timezone offset (e.g. '...+00:00')")
        return parsed.isoformat()
    return datetime.now(tz=UTC).isoformat()


def _resolve_wallclock(measured: float) -> float | None:
    """Return the wall-clock value to record, or ``None`` to omit it."""
    mode = os.environ.get("APEX_REPORT_WALLCLOCK_MODE", "record").lower()
    if mode == "record":
        return float(measured)
    if mode == "zero":
        return 0.0
    if mode == "omit":
        return None
    raise ValueError(f"APEX_REPORT_WALLCLOCK_MODE={mode!r} not in {{'record', 'zero', 'omit'}}")


def _synthetic_dataset(
    n: int, seed: int
) -> tuple[
    MetaLabelerFeatureSet,
    npt.NDArray[np.int_],
    npt.NDArray[np.float64],
]:
    """Same generator as the Phase 4.3 report: alpha in ``ofi_signal``."""
    rng = np.random.default_rng(seed)
    x = rng.normal(0.0, 1.0, size=(n, len(FEATURE_NAMES))).astype(np.float64)
    x[:, 3] = rng.integers(0, 4, size=n).astype(np.float64)
    x[:, 4] = rng.integers(-1, 2, size=n).astype(np.float64)
    x[:, 5] = np.abs(rng.normal(0.01, 0.002, size=n))
    logit = 1.5 * x[:, 2]
    probs = 1.0 / (1.0 + np.exp(-logit))
    y = (rng.uniform(0, 1, size=n) < probs).astype(np.int_)
    t0 = np.array(
        [np.datetime64("2025-01-01") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[us]",
    )
    t1: npt.NDArray[np.datetime64] = (t0 + np.timedelta64(5, "h")).astype("datetime64[us]")
    fs = MetaLabelerFeatureSet(X=x, feature_names=FEATURE_NAMES, t0=t0, t1=t1)
    w = np.ones(n, dtype=np.float64)
    return fs, y, w


def _config(full: bool) -> dict[str, Any]:
    if full:
        return {
            "n": 1200,
            "search_space": TuningSearchSpace(
                n_estimators=(100, 300, 500),
                max_depth=(5, 10, None),
                min_samples_leaf=(5, 20),
            ),
            "outer": CombinatoriallyPurgedKFold(n_splits=6, n_test_splits=2, embargo_pct=0.02),
            "inner": CombinatoriallyPurgedKFold(n_splits=4, n_test_splits=1, embargo_pct=0.0),
            "label": "full (APEX_FULL_TUNING=1)",
        }
    return {
        "n": 400,
        "search_space": TuningSearchSpace(
            n_estimators=(30, 60),
            max_depth=(3, 5),
            min_samples_leaf=(5, 10),
        ),
        "outer": CombinatoriallyPurgedKFold(n_splits=4, n_test_splits=2, embargo_pct=0.0),
        "inner": CombinatoriallyPurgedKFold(n_splits=3, n_test_splits=1, embargo_pct=0.0),
        "label": "fast (CI default)",
    }


def _format_hparams(hp: dict[str, Any]) -> str:
    parts = [
        f"n_estimators={hp['n_estimators']}",
        f"max_depth={hp['max_depth']}",
        f"min_samples_leaf={hp['min_samples_leaf']}",
    ]
    return ", ".join(parts)


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    seed = int(os.environ.get("APEX_SEED", "42"))
    full = os.environ.get("APEX_FULL_TUNING", "0") == "1"
    cfg = _config(full)

    fs, y, w = _synthetic_dataset(n=int(cfg["n"]), seed=seed)
    tuner = NestedCPCVTuner(
        search_space=cfg["search_space"],
        outer_cpcv=cfg["outer"],
        inner_cpcv=cfg["inner"],
        seed=seed,
    )
    result = tuner.tune(fs, y, w)

    best_oos = list(result.best_oos_auc_per_fold)
    mean_oos = float(np.mean(best_oos))
    std_oos = float(np.std(best_oos, ddof=0))

    # Top 5 trials globally by OOS AUC for a quick eyeball of whether
    # the inner-selected winners also score well OOS. Phase 4.5 will do
    # the statistical version (PBO).
    ranked = sorted(result.all_trials, key=lambda t: -t[2])[:5]

    wallclock = _resolve_wallclock(result.wall_clock_seconds)
    payload: dict[str, Any] = {
        "generated_at": _resolve_generated_at(),
        "seed": seed,
        "config_label": cfg["label"],
        "n_samples": int(fs.X.shape[0]),
        "outer_n_folds": cfg["outer"].get_n_splits(),
        "inner_n_folds": cfg["inner"].get_n_splits(),
        "search_space_cardinality": cfg["search_space"].cardinality,
        "stability_index": result.stability_index,
        "best_hyperparameters_per_fold": [dict(h) for h in result.best_hyperparameters_per_fold],
        "best_oos_auc_per_fold": best_oos,
        "mean_best_oos_auc": mean_oos,
        "std_best_oos_auc": std_oos,
        "all_trials": [
            {
                "hparams": dict(hp),
                "mean_inner_cv_auc": float(inner_auc),
                "oos_auc": float(oos_auc),
            }
            for (hp, inner_auc, oos_auc) in result.all_trials
        ],
    }
    if wallclock is not None:
        payload["wall_clock_seconds"] = wallclock

    json_path = REPORT_DIR / "tuning_trials.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")

    lines: list[str] = []
    lines.append("# Phase 4.4 - Nested CPCV tuning report")
    lines.append("")
    lines.append(f"- Generated at: `{payload['generated_at']}`")
    lines.append(f"- Seed: `{seed}`")
    lines.append(f"- Config: **{cfg['label']}**")
    lines.append(f"- Samples: `{payload['n_samples']}`")
    lines.append(
        f"- Outer CPCV folds: `{payload['outer_n_folds']}` / "
        f"Inner CPCV folds: `{payload['inner_n_folds']}`"
    )
    lines.append(f"- Search-space cardinality: `{payload['search_space_cardinality']}` trials")
    lines.append(f"- Total trials in ledger: `{len(result.all_trials)}`")
    if wallclock is not None:
        lines.append(f"- Wall-clock: `{wallclock:.2f}s`")
    else:
        lines.append("- Wall-clock: *(omitted for reproducible audit diff)*")
    lines.append(
        f"- Stability index: `{result.stability_index:.4f}` "
        "(fraction of outer folds whose best hparams equal the mode)"
    )
    lines.append("")
    lines.append("## Outer-fold winners")
    lines.append("")
    lines.append("| Fold | n_estimators | max_depth | min_samples_leaf | OOS AUC |")
    lines.append("|---|---|---|---|---|")
    for i, (hp, auc) in enumerate(zip(result.best_hyperparameters_per_fold, best_oos, strict=True)):
        lines.append(
            f"| {i + 1} | {hp['n_estimators']} | {hp['max_depth']} "
            f"| {hp['min_samples_leaf']} | {auc:.4f} |"
        )
    lines.append("")
    lines.append("## Aggregate OOS performance")
    lines.append("")
    lines.append(f"- Mean best-OOS AUC: `{mean_oos:.4f}` (std `{std_oos:.4f}`)")
    lines.append("- Selection criterion: inner-CV-mean weighted AUC (honest nested CV).")
    lines.append("")
    lines.append("## Top-5 trials globally by OOS AUC")
    lines.append("")
    lines.append("| Rank | Hparams | mean_inner_cv_auc | OOS AUC |")
    lines.append("|---|---|---|---|")
    for r, (hp, inner_auc, oos_auc) in enumerate(ranked, start=1):
        lines.append(f"| {r} | `{_format_hparams(hp)}` | {inner_auc:.4f} | {oos_auc:.4f} |")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Inputs are synthetic with calibrated alpha in `ofi_signal`; "
        "real Phase 3 signal history will be substituted in Phase 4.5."
    )
    lines.append(
        "- Full trial ledger is persisted in `tuning_trials.json` for "
        "Phase 4.5 PBO / DSR computation (Bailey et al. 2014)."
    )
    lines.append(
        "- The CI default runs a narrower grid (8 trials x 6 outer x 3 "
        "inner = 144 fits + 48 refits) to keep the report under a minute."
    )
    lines.append(
        "- Set `APEX_FULL_TUNING=1` to run the PHASE_4_SPEC section 3.4 "
        "spec grid (18 x 15 x 4 = 1,080 inner fits + 270 outer refits)."
    )

    md_path = REPORT_DIR / "tuning_report.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    _log.info("phase_4_4.report_written", json_path=str(json_path), md_path=str(md_path))
    _log.info(
        "phase_4_4.tuning_summary",
        stability_index=result.stability_index,
        mean_best_oos_auc=mean_oos,
        wall_clock_seconds=result.wall_clock_seconds,
        wallclock_recorded=wallclock,
    )


if __name__ == "__main__":
    main()
