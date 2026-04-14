"""Generate the Phase 4.3 baseline Meta-Labeler diagnostic report.

Runs the full training loop on a synthetic dataset with calibrated alpha
(controlled by ``APEX_SEED``) and emits a Markdown + JSON report under
``reports/phase_4_3/``. The inputs are **purely synthetic** to avoid
network dependencies in CI; Phase 4.5 will re-run the pipeline on real
Phase 3 signal history as part of the DSR audit.

Usage:
    APEX_SEED=42 python3 scripts/generate_phase_4_3_report.py

Report contents:
    - Per-fold RF / LogReg AUC table and RF Brier.
    - Feature importances (sorted).
    - 10-bin reliability diagram (aggregate OOS).
    - Smoke gate pass/fail (mean RF AUC >= 0.55).

References:
    PHASE_4_SPEC section 3.3 DoD #4 - diagnostic report artefact.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt

from features.cv.cpcv import CombinatoriallyPurgedKFold
from features.meta_labeler.baseline import BaselineMetaLabeler
from features.meta_labeler.feature_builder import FEATURE_NAMES, MetaLabelerFeatureSet

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "reports" / "phase_4_3"


def _synthetic_dataset(
    n: int, seed: int
) -> tuple[
    MetaLabelerFeatureSet,
    npt.NDArray[np.int_],
    npt.NDArray[np.float64],
]:
    rng = np.random.default_rng(seed)
    x = rng.normal(0.0, 1.0, size=(n, len(FEATURE_NAMES))).astype(np.float64)
    x[:, 3] = rng.integers(0, 4, size=n).astype(np.float64)
    x[:, 4] = rng.integers(-1, 2, size=n).astype(np.float64)
    x[:, 5] = np.abs(rng.normal(0.01, 0.002, size=n))
    logit = 1.5 * x[:, 2]  # alpha concentrated in ofi_signal
    probs = 1.0 / (1.0 + np.exp(-logit))
    y = (rng.uniform(0, 1, size=n) < probs).astype(np.int_)
    t0 = np.array(
        [np.datetime64("2025-01-01") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[us]",
    )
    # ``datetime64 + timedelta64 -> datetime64`` at runtime, but the numpy
    # type stubs return ``timedelta64`` for the binary op. Cast explicitly
    # to keep mypy --strict happy.
    t1: npt.NDArray[np.datetime64] = (t0 + np.timedelta64(5, "h")).astype("datetime64[us]")
    fs = MetaLabelerFeatureSet(X=x, feature_names=FEATURE_NAMES, t0=t0, t1=t1)
    w = np.ones(n, dtype=np.float64)
    return fs, y, w


def main() -> None:
    # Create the report directory on *invocation*, not at module import
    # time — keeps ``import scripts.generate_phase_4_3_report`` side-effect
    # free for tooling / test discovery.
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    seed = int(os.environ.get("APEX_SEED", "42"))
    fs, y, w = _synthetic_dataset(n=1200, seed=seed)
    cpcv = CombinatoriallyPurgedKFold(n_splits=6, n_test_splits=2, embargo_pct=0.02)
    trainer = BaselineMetaLabeler(cpcv, seed=seed)
    result = trainer.train(fs, y, w)

    mean_rf = float(np.mean(result.rf_auc_per_fold))
    mean_lr = float(np.mean(result.logreg_auc_per_fold))
    std_rf = float(np.std(result.rf_auc_per_fold, ddof=0))
    mean_brier = float(np.mean(result.rf_brier_per_fold))

    gate_pass = mean_rf >= 0.55

    payload = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "seed": seed,
        "n_samples": int(fs.X.shape[0]),
        "n_folds": cpcv.get_n_splits(),
        "rf_auc_per_fold": list(result.rf_auc_per_fold),
        "logreg_auc_per_fold": list(result.logreg_auc_per_fold),
        "rf_brier_per_fold": list(result.rf_brier_per_fold),
        "mean_rf_auc": mean_rf,
        "mean_logreg_auc": mean_lr,
        "std_rf_auc": std_rf,
        "mean_rf_brier": mean_brier,
        "feature_importances": dict(
            sorted(result.feature_importances.items(), key=lambda kv: -kv[1])
        ),
        "calibration_bins": list(result.rf_calibration_bins),
        "smoke_gate_rf_auc_min": 0.55,
        "smoke_gate_pass": gate_pass,
    }

    json_path = REPORT_DIR / "baseline_report.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")

    lines: list[str] = []
    lines.append("# Phase 4.3 - Baseline Meta-Labeler diagnostic report")
    lines.append("")
    lines.append(f"- Generated at: `{payload['generated_at']}`")
    lines.append(f"- Seed: `{seed}`")
    lines.append(f"- Samples: `{payload['n_samples']}`")
    lines.append(f"- CPCV folds: `{payload['n_folds']}`")
    lines.append(f"- Smoke gate (RF mean OOS AUC >= 0.55): **{'PASS' if gate_pass else 'FAIL'}**")
    lines.append("")
    lines.append("## Mean metrics")
    lines.append("")
    lines.append(f"- RF mean OOS AUC: `{mean_rf:.4f}` (std `{std_rf:.4f}`)")
    lines.append(f"- LogReg mean OOS AUC: `{mean_lr:.4f}`")
    lines.append(f"- RF mean OOS Brier: `{mean_brier:.4f}`")
    lines.append(f"- RF - LogReg gap: `{mean_rf - mean_lr:+.4f}` (Phase 4.5 gate: >= +0.03)")
    lines.append("")
    lines.append("## Per-fold OOS metrics")
    lines.append("")
    lines.append("| Fold | RF AUC | LogReg AUC | RF Brier |")
    lines.append("|---|---|---|---|")
    for i, (rf_auc, lr_auc, brier) in enumerate(
        zip(
            result.rf_auc_per_fold,
            result.logreg_auc_per_fold,
            result.rf_brier_per_fold,
            strict=True,
        )
    ):
        lines.append(f"| {i + 1} | {rf_auc:.4f} | {lr_auc:.4f} | {brier:.4f} |")
    lines.append("")
    lines.append("## Feature importances (RF, final fit)")
    lines.append("")
    lines.append("| Feature | Importance |")
    lines.append("|---|---|")
    for name, imp in sorted(result.feature_importances.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{name}` | {imp:.4f} |")
    lines.append("")
    lines.append("## Calibration bins (aggregate OOS, 10-bin uniform)")
    lines.append("")
    lines.append("| Bin | Mean predicted | Observed positive rate |")
    lines.append("|---|---|---|")
    for i, (mp, fp) in enumerate(result.rf_calibration_bins):
        lines.append(f"| {i + 1} | {mp:.4f} | {fp:.4f} |")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Inputs are synthetic with calibrated alpha in `ofi_signal`; real "
        "Phase 3 signal history will be substituted in Phase 4.5."
    )
    lines.append("- DSR / PBO gates are **not** evaluated here (deferred to Phase 4.5).")

    md_path = REPORT_DIR / "baseline_report.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"Smoke gate: {'PASS' if gate_pass else 'FAIL'} (mean RF AUC={mean_rf:.4f})")


if __name__ == "__main__":
    main()
