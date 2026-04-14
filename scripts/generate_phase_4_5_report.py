"""Generate the Phase 4.5 Meta-Labeler statistical-validation report.

Wires the seven ADR-0005 D5 deployment gates (G1-G7) on a synthetic
dataset whose alpha is concentrated in ``ofi_signal`` (same generator
as the Phase 4.3 / 4.4 reports), then emits Markdown + JSON under
``reports/phase_4_5/``.

Pipeline (executed in order):

1. Build the synthetic ``(features, y, sample_weights, bars)`` tuple.
   The bar series is constructed so that the per-bar log-return has
   a small drift proportional to ``ofi_signal``; this gives the
   tuned RF a real edge to exploit and produces non-degenerate G3
   DSR statistics.
2. Run :class:`BaselineMetaLabeler` to produce per-fold AUCs / Brier
   needed by gates G1, G2, G5, G7.
3. Run :class:`NestedCPCVTuner` to populate the trial ledger for G4
   PBO.
4. Run :class:`MetaLabelerValidator` under the realistic cost
   scenario (5 bps per side per ADR-0005 D8) to produce the
   :class:`MetaLabelerValidationReport`.
5. Persist ``validation_report.{md,json}``.

Usage:

    # Fast / CI report (default)
    APEX_SEED=42 python3 scripts/generate_phase_4_5_report.py

    # Full production run (slow)
    APEX_SEED=42 APEX_FULL_VALIDATION=1 \\
        python3 scripts/generate_phase_4_5_report.py

    # Byte-for-byte reproducible artefact (for audit diffs)
    APEX_SEED=42 APEX_REPORT_NOW=2026-04-14T00:00:00+00:00 \\
        APEX_REPORT_WALLCLOCK_MODE=omit \\
        python3 scripts/generate_phase_4_5_report.py

Reproducibility:
    Mirrors the Phase 4.4 contract introduced in PR #141: two
    intrinsically time-dependent fields (``generated_at`` and
    ``wall_clock_seconds``) can be frozen via
    ``APEX_REPORT_NOW`` and ``APEX_REPORT_WALLCLOCK_MODE``. The
    bootstrap CI on the realised Sharpe is seeded by ``APEX_SEED``
    so runs are deterministic given the seed.

References:
    PHASE_4_SPEC §3.5 - outputs and DoD.
    ADR-0005 D5 - gates G1-G7.
    ADR-0005 D8 / ADR-0002 §A.7 - three-scenario cost model.
    Bailey, D. H., & López de Prado, M. (2014). "The Deflated Sharpe
    Ratio." *Journal of Portfolio Management*, 40(5), 94-107.
    Bailey, D. H., Borwein, J. M., López de Prado, M., & Zhu, Q. J.
    (2017). "The probability of backtest overfitting." *Journal of
    Computational Finance*, 20(4).
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
import polars as pl
import structlog

from features.cv.cpcv import CombinatoriallyPurgedKFold
from features.meta_labeler.baseline import BaselineMetaLabeler
from features.meta_labeler.feature_builder import FEATURE_NAMES, MetaLabelerFeatureSet
from features.meta_labeler.pnl_simulation import CostScenario
from features.meta_labeler.tuning import NestedCPCVTuner, TuningSearchSpace
from features.meta_labeler.validation import (
    GateResult,
    MetaLabelerValidationReport,
    MetaLabelerValidator,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "reports" / "phase_4_5"

_log = structlog.get_logger(__name__)

# Drift coefficient mapping ``ofi_signal`` → per-bar log-return.
# Calibrated so the per-label realised Sharpe lands in the (0.5, 3.0)
# band on the small CI dataset - large enough to fire G3 yet not so
# large the synthetic regime distorts the gate semantics.
_BAR_DRIFT_PER_SIGMA: float = 0.001
_BAR_NOISE_SIGMA: float = 0.0015


def _resolve_generated_at() -> str:
    """Return the ``generated_at`` header.

    Honours ``APEX_REPORT_NOW`` so audit diffs can freeze the
    timestamp. Unparseable values fail loud rather than silently
    falling back to ``datetime.now``.
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


def _synthetic_features_and_labels(
    n: int, seed: int
) -> tuple[
    MetaLabelerFeatureSet,
    npt.NDArray[np.int_],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    """Produce the same ``(X, y, weights)`` triple as Phase 4.3 / 4.4.

    Returns the feature set, the binary target, the uniform sample
    weights, and the raw ``ofi_signal`` column (column 2 of ``X``)
    which the bar-builder consumes to inject alpha.
    """
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
    t1: npt.NDArray[np.datetime64] = (t0 + np.timedelta64(5, "h")).astype("datetime64[us]")
    fs = MetaLabelerFeatureSet(X=x, feature_names=FEATURE_NAMES, t0=t0, t1=t1)
    w = np.ones(n, dtype=np.float64)
    return fs, y, w, x[:, 2].astype(np.float64)


def _synthetic_bars(
    features: MetaLabelerFeatureSet,
    ofi_signal: npt.NDArray[np.float64],
    seed: int,
) -> pl.DataFrame:
    """Build a Polars bars frame covering ``[min(t0), max(t1)]``.

    The price series is a geometric random walk:

        log_ret[bar k] ~ Normal(drift_k, _BAR_NOISE_SIGMA)
        drift_k = _BAR_DRIFT_PER_SIGMA * ofi_signal_at_bar(k)

    where ``ofi_signal_at_bar(k)`` is the signal at the label whose
    ``t0_i`` equals bar ``k`` (or zero if no label opens at that
    bar - i.e. the post-``max(t0)`` tail bars). This injects a
    real, deterministic edge that the tuned RF can exploit for the
    G3 DSR gate, without tampering with feature values.

    The resulting frame has columns ``timestamp`` (Datetime[us, UTC],
    strictly monotonic) and ``close`` (Float64, strictly positive).
    """
    t0 = features.t0
    t1 = features.t1
    start = np.min(t0)
    end = np.max(t1)
    # One bar per hour over [start, end] inclusive.
    span_hours = int((end - start).astype("timedelta64[h]").astype(np.int64)) + 1
    timestamps = np.array(
        [start + np.timedelta64(i, "h") for i in range(span_hours)],
        dtype="datetime64[us]",
    )

    # Map each bar timestamp to the ofi_signal of the label whose
    # ``t0_i`` matches it. Bars that have no matching label get drift 0.
    drift = np.zeros(span_hours, dtype=np.float64)
    # ``np.searchsorted(timestamps, t0)`` gives an exact index since
    # both grids are hourly and aligned.
    idx = np.searchsorted(timestamps, t0, side="left")
    drift[idx] = _BAR_DRIFT_PER_SIGMA * ofi_signal

    rng = np.random.default_rng(seed + 1)
    noise = rng.normal(0.0, _BAR_NOISE_SIGMA, size=span_hours)
    log_returns = drift + noise
    log_returns[0] = 0.0  # first bar has no return
    log_prices = np.cumsum(log_returns)
    close = 100.0 * np.exp(log_prices)

    return pl.DataFrame(
        {
            "timestamp": pl.Series("timestamp", timestamps, dtype=pl.Datetime("us", "UTC")),
            "close": pl.Series("close", close.astype(np.float64), dtype=pl.Float64),
        }
    )


def _config(full: bool) -> dict[str, Any]:
    """Two configurations: fast (CI default) vs full (production)."""
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
            "label": "full (APEX_FULL_VALIDATION=1)",
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


def _gate_row(g: GateResult) -> str:
    verdict = "✅ pass" if g.passed else "❌ fail"
    return f"| `{g.name}` | {g.value:.4f} | {g.threshold:.4f} | {verdict} |"


def _gate_to_json(g: GateResult) -> dict[str, Any]:
    return {
        "name": g.name,
        "value": float(g.value),
        "threshold": float(g.threshold),
        "passed": bool(g.passed),
    }


def _mitigation_for(name: str) -> str:
    """Per-gate mitigation hint surfaced when a gate fails.

    PHASE_4_SPEC §3.5 Outputs requires the report to suggest a
    remediation path. Hints are intentionally short - the operator
    runs the corresponding deeper diagnostic.
    """
    return {
        "G1_mean_auc": (
            "Inspect feature drift in 4.3 reliability bins; consider widening the "
            "training window or revising the Phase 3 alpha sources."
        ),
        "G2_min_auc": (
            "Identify the worst outer fold and audit its calendar slice - likely "
            "a regime transition. Increase CPCV embargo or partition by regime."
        ),
        "G3_dsr": (
            "Realised Sharpe is not statistically distinguishable from zero under "
            "deflation. Re-tune with stronger regularisation, or revisit the cost "
            "assumption (ADR-0005 D8) before deployment."
        ),
        "G4_pbo": (
            "PBO ≥ 10 % indicates the inner-CV winner systematically underperforms "
            "out of sample. Reduce the search-space cardinality or widen inner-CV "
            "(see López de Prado 2018 §11)."
        ),
        "G5_brier": (
            "Calibration is poor. Add Platt or isotonic post-fit calibration "
            "(sklearn ``CalibratedClassifierCV``) or revisit class-weight balancing."
        ),
        "G6_minority_freq": (
            "Minority class is too rare for stable training. Extend the labelling "
            "horizon or rebalance the Triple Barrier vertical / horizontal limits."
        ),
        "G7_rf_minus_logreg": (
            "Tree ensemble does not beat the linear baseline by ≥ 3 AUC pts. "
            "Drop RF in favour of LogReg for this regime, or revisit feature "
            "engineering - non-linearity may not be present."
        ),
    }.get(name, "Investigate the failing diagnostic in the per-gate documentation.")


def _emit_markdown(
    payload: dict[str, Any],
    report: MetaLabelerValidationReport,
    cfg: dict[str, Any],
    seed: int,
    wallclock: float | None,
) -> str:
    lines: list[str] = []
    lines.append("# Phase 4.5 - Meta-Labeler statistical validation")
    lines.append("")
    lines.append(f"- Generated at: `{payload['generated_at']}`")
    lines.append(f"- Seed: `{seed}`")
    lines.append(f"- Config: **{cfg['label']}**")
    lines.append(f"- Samples: `{payload['n_samples']}`")
    lines.append(
        f"- Outer CPCV folds: `{payload['outer_n_folds']}` / "
        f"Inner CPCV folds: `{payload['inner_n_folds']}`"
    )
    lines.append(
        f"- Cost scenario (G3 input): **realistic** "
        f"(round-trip = `{report.scenario_realistic_round_trip_bps:.1f}` bps "
        "per ADR-0005 D8)"
    )
    if wallclock is not None:
        lines.append(f"- Wall-clock: `{wallclock:.2f}s` (4.3 + 4.4 + 4.5 combined)")
    else:
        lines.append("- Wall-clock: *(omitted for reproducible audit diff)*")
    verdict = "✅ **ALL PASS**" if report.all_passed else "❌ **FAIL**"
    lines.append(f"- Aggregate verdict: {verdict}")
    if report.failing_gate_names:
        lines.append("- Failing gates: " + ", ".join(f"`{n}`" for n in report.failing_gate_names))
    lines.append("")
    lines.append("## ADR-0005 D5 deployment gates")
    lines.append("")
    lines.append("| Gate | Value | Threshold | Verdict |")
    lines.append("|---|---|---|---|")
    for g in report.gates:
        lines.append(_gate_row(g))
    lines.append("")
    lines.append("## Aggregate scalars (PHASE_4_SPEC §3.5 outputs)")
    lines.append("")
    lo, hi = report.pnl_realistic_sharpe_ci
    lines.append(
        f"- `pnl_realistic_sharpe`: **{report.pnl_realistic_sharpe:.4f}** "
        f"(95 % stationary-bootstrap CI = [{lo:.4f}, {hi:.4f}])"
    )
    lines.append(f"- `dsr`: **{report.dsr:.4f}** (threshold 0.95)")
    lines.append(f"- `pbo`: **{report.pbo:.4f}** (threshold < 0.10)")
    lines.append("")
    if not report.all_passed:
        lines.append("## Mitigation paths for failing gates")
        lines.append("")
        for name in report.failing_gate_names:
            lines.append(f"- `{name}`: {_mitigation_for(name)}")
        lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Inputs are synthetic with calibrated alpha in `ofi_signal`; the bar "
        "series carries an aligned drift so the tuned RF has a real edge to "
        "exploit. Real Phase 3 signal history will be substituted in Phase 4.7."
    )
    lines.append(
        "- Bootstrap CI on the realised Sharpe uses Politis & Romano (1994) "
        "stationary bootstrap with block length `max(1, round(n^(1/3)))` and "
        "1000 resamples seeded from `APEX_SEED`."
    )
    lines.append(
        "- DSR is computed as a single-strategy DSR (n_trials = 1); "
        "multi-strategy correction across the Fusion Engine is Phase 4.7+."
    )
    lines.append(
        "- Failure on this synthetic scenario (`APEX_SEED=42`) under realistic "
        "costs blocks merge per PHASE_4_SPEC §3.5 DoD #4."
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    seed = int(os.environ.get("APEX_SEED", "42"))
    full = os.environ.get("APEX_FULL_VALIDATION", "0") == "1"
    cfg = _config(full)
    n = int(cfg["n"])

    fs, y, w, ofi_signal = _synthetic_features_and_labels(n=n, seed=seed)
    bars = _synthetic_bars(fs, ofi_signal, seed=seed)

    t_start = time.perf_counter()

    # Phase 4.3 - baseline training (provides G1, G2, G5, G7 inputs).
    baseline = BaselineMetaLabeler(cpcv=cfg["outer"], seed=seed)
    training_result = baseline.train(fs, y, w)

    # Phase 4.4 - nested tuning (provides the trial ledger for G4).
    tuner = NestedCPCVTuner(
        search_space=cfg["search_space"],
        outer_cpcv=cfg["outer"],
        inner_cpcv=cfg["inner"],
        seed=seed,
    )
    tuning_result = tuner.tune(fs, y, w)

    # Phase 4.5 - wire G1-G7.
    validator = MetaLabelerValidator(
        cpcv=cfg["outer"],
        cost_scenario=CostScenario.REALISTIC,
        seed=seed,
    )
    report = validator.validate(
        training_result=training_result,
        tuning_result=tuning_result,
        features=fs,
        y=y,
        sample_weights=w,
        bars_for_pnl=bars,
    )

    measured = time.perf_counter() - t_start
    wallclock = _resolve_wallclock(measured)

    payload: dict[str, Any] = {
        "generated_at": _resolve_generated_at(),
        "seed": seed,
        "config_label": cfg["label"],
        "n_samples": int(fs.X.shape[0]),
        "outer_n_folds": cfg["outer"].get_n_splits(),
        "inner_n_folds": cfg["inner"].get_n_splits(),
        "cost_scenario": "realistic",
        "scenario_round_trip_bps": float(report.scenario_realistic_round_trip_bps),
        "all_passed": bool(report.all_passed),
        "failing_gate_names": list(report.failing_gate_names),
        "gates": [_gate_to_json(g) for g in report.gates],
        "aggregate": {
            "pnl_realistic_sharpe": float(report.pnl_realistic_sharpe),
            "pnl_realistic_sharpe_ci": [
                float(report.pnl_realistic_sharpe_ci[0]),
                float(report.pnl_realistic_sharpe_ci[1]),
            ],
            "dsr": float(report.dsr),
            "pbo": float(report.pbo),
        },
    }
    if wallclock is not None:
        payload["wall_clock_seconds"] = wallclock

    json_path = REPORT_DIR / "validation_report.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")

    md_path = REPORT_DIR / "validation_report.md"
    md_path.write_text(_emit_markdown(payload, report, cfg, seed, wallclock), encoding="utf-8")

    _log.info(
        "phase_4_5.report_written",
        json_path=str(json_path),
        md_path=str(md_path),
    )
    _log.info(
        "phase_4_5.validation_summary",
        all_passed=report.all_passed,
        failing=list(report.failing_gate_names),
        pnl_realistic_sharpe=report.pnl_realistic_sharpe,
        dsr=report.dsr,
        pbo=report.pbo,
        wall_clock_seconds=measured,
        wallclock_recorded=wallclock,
    )


if __name__ == "__main__":
    main()
