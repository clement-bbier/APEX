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

from features.cv.cpcv import CombinatoriallyPurgedKFold
from features.meta_labeler.feature_builder import FEATURE_NAMES, MetaLabelerFeatureSet
from features.meta_labeler.tuning import NestedCPCVTuner, TuningSearchSpace

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "reports" / "phase_4_4"


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

    payload = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "seed": seed,
        "config_label": cfg["label"],
        "n_samples": int(fs.X.shape[0]),
        "outer_n_folds": cfg["outer"].get_n_splits(),
        "inner_n_folds": cfg["inner"].get_n_splits(),
        "search_space_cardinality": cfg["search_space"].cardinality,
        "wall_clock_seconds": result.wall_clock_seconds,
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
    lines.append(f"- Wall-clock: `{result.wall_clock_seconds:.2f}s`")
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

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(
        f"Stability index: {result.stability_index:.4f}, "
        f"mean best-OOS AUC: {mean_oos:.4f}, "
        f"wall-clock: {result.wall_clock_seconds:.2f}s"
    )


if __name__ == "__main__":
    main()
