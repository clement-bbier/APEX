"""Generate the Phase 4.8 end-to-end pipeline diagnostic report.

Composition-gate mirror of the integration test. The pipeline:

1. Build the deterministic synthetic scenario via
   :func:`tests.integration.fixtures.phase_4_synthetic.build_scenario`
   (4 symbols, 500 hourly bars/symbol, 3 Phase-3 signals with known
   latent-alpha coefficients, ~376 Triple-Barrier events pooled).
2. Run the 4.3 ``BaselineMetaLabeler`` + 4.4 ``NestedCPCVTuner`` on
   the pooled feature matrix using the reduced 2×2×2 grid.
3. Run the 4.5 ``MetaLabelerValidator`` on the first-symbol slice
   (the validator is single-asset by design per Phase 4 contract).
4. Build the 4.7 ``ICWeightedFusionConfig`` from per-signal IC_IR
   measurements on the pooled bar panel, compute ``fusion_score``.
5. Emit ``reports/phase_4_8/pipeline_diagnostics.{md,json}`` with:
   - scenario summary (events, labels, IC/IR per signal),
   - frozen fusion weights,
   - per-gate verdicts (G1 - G7) + ``all_passed`` aggregate,
   - Sharpe trio (bet_sized / fusion / random) and the two gaps,
   - DSR, PBO, Brier, realistic round-trip bps,
   - ``save_model`` / ``load_model`` bit-exact round-trip verdict.

Reproducibility follows the 4.3/4.4/4.5/4.6/4.7 contract:
    - ``APEX_SEED`` (default 42) seeds numpy + sklearn.
    - ``APEX_REPORT_NOW`` freezes the ``generated_at`` header.
    - ``APEX_REPORT_WALLCLOCK_MODE`` ∈ {record, zero, omit}.

Usage:

    APEX_SEED=42 \\
      APEX_REPORT_NOW=2026-04-15T00:00:00+00:00 \\
      APEX_REPORT_WALLCLOCK_MODE=omit \\
      python3 scripts/generate_phase_4_8_report.py

The script is a *demo*, not a gate: CI exercises the composition
gate through ``tests/integration/test_phase_4_pipeline.py``. The
generator exists so reviewers can inspect end-to-end behaviour and
so the artifact stays current as the underlying modules evolve.

References:
    PHASE_4_SPEC §3.8.
    ADR-0005 (full ADR applies).
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

from features.fusion import ICWeightedFusion, ICWeightedFusionConfig
from features.ic.base import ICResult
from features.ic.report import ICReport
from features.integration.config import FeatureActivationConfig
from features.meta_labeler.baseline import BaselineMetaLabeler
from features.meta_labeler.pnl_simulation import CostScenario
from features.meta_labeler.tuning import NestedCPCVTuner
from features.meta_labeler.validation import MetaLabelerValidator
from tests.integration.fixtures.phase_4_synthetic import (
    DEFAULT_SEED,
    REDUCED_TUNING_SEARCH_SPACE,
    SCENARIO_SIGNAL_NAMES,
    SCENARIO_SYMBOLS,
    Scenario,
    build_inner_cpcv,
    build_outer_cpcv,
    build_scenario,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "reports" / "phase_4_8"

_log = structlog.get_logger(__name__)


# ----------------------------------------------------------------------
# Header helpers - shared contract with the 4.3/4.4/4.5/4.6/4.7 reports
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


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _sharpe(pnl: npt.NDArray[np.float64]) -> float:
    if pnl.size < 2:
        return 0.0
    std = float(pnl.std(ddof=1))
    if std <= 0.0 or not np.isfinite(std):
        return 0.0
    return float(pnl.mean() / std)


def _event_log_returns(scenario: Scenario) -> npt.NDArray[np.float64]:
    """Per-event ``log(close(t1)/close(t0))`` on the pooled panel."""
    bars = scenario.bars
    n = scenario.y.shape[0]
    t0 = scenario.feature_set.t0
    t1 = scenario.feature_set.t1
    symbols = scenario.labels["symbol"].to_list()
    t0_py = [datetime.fromisoformat(str(ts).replace(" ", "T")).replace(tzinfo=UTC) for ts in t0]
    t1_py = [datetime.fromisoformat(str(ts).replace(" ", "T")).replace(tzinfo=UTC) for ts in t1]
    evt = pl.DataFrame(
        {
            "row_idx": list(range(n)),
            "symbol": symbols,
            "t0": t0_py,
            "t1": t1_py,
        },
        schema={
            "row_idx": pl.Int64,
            "symbol": pl.Utf8,
            "t0": pl.Datetime("us", "UTC"),
            "t1": pl.Datetime("us", "UTC"),
        },
    )
    with_c0 = evt.join(
        bars.rename({"timestamp": "t0", "close": "close_t0"}),
        on=["symbol", "t0"],
        how="left",
    )
    with_c01 = with_c0.join(
        bars.rename({"timestamp": "t1", "close": "close_t1"}),
        on=["symbol", "t1"],
        how="left",
    ).sort("row_idx")
    c0 = with_c01["close_t0"].to_numpy().astype(np.float64)
    c1 = with_c01["close_t1"].to_numpy().astype(np.float64)
    result: npt.NDArray[np.float64] = np.log(c1) - np.log(c0)
    return result


def _fusion_score_at_events(fusion_df: pl.DataFrame, scenario: Scenario) -> npt.NDArray[np.float64]:
    t0 = scenario.feature_set.t0
    t0_py = [datetime.fromisoformat(str(ts).replace(" ", "T")).replace(tzinfo=UTC) for ts in t0]
    symbols = scenario.labels["symbol"].to_list()
    evt = pl.DataFrame(
        {
            "row_idx": list(range(len(symbols))),
            "symbol": symbols,
            "timestamp": t0_py,
        },
        schema={
            "row_idx": pl.Int64,
            "symbol": pl.Utf8,
            "timestamp": pl.Datetime("us", "UTC"),
        },
    )
    joined = evt.join(fusion_df, on=["symbol", "timestamp"], how="left").sort("row_idx")
    return joined["fusion_score"].to_numpy().astype(np.float64)


def _build_ic_report(scenario: Scenario) -> ICReport:
    results: list[ICResult] = []
    for name in sorted(SCENARIO_SIGNAL_NAMES):
        ic = scenario.ic_per_signal[name]
        ic_ir = scenario.ic_ir_per_signal[name]
        results.append(
            ICResult(
                ic=float(ic),
                ic_ir=float(ic_ir),
                p_value=0.01,
                n_samples=int(scenario.forward_returns_per_signal[name].size),
                ci_low=float(ic) - 0.02,
                ci_high=float(ic) + 0.02,
                feature_name=name,
                horizon_bars=1,
            )
        )
    return ICReport(results)


def _bet_sized_pool_pnl(scenario: Scenario, best_hp: dict[str, Any]) -> npt.NDArray[np.float64]:
    """Per-event net P&L on the pooled universe using ``best_hp``."""
    from sklearn.ensemble import RandomForestClassifier

    outer = build_outer_cpcv()
    X = scenario.feature_set.X  # noqa: N806
    y = scenario.y
    w = scenario.sample_weights
    log_rets = _event_log_returns(scenario)
    pooled_net = np.zeros(X.shape[0], dtype=np.float64)
    seen = np.zeros(X.shape[0], dtype=bool)
    rt_cost = CostScenario.REALISTIC.round_trip_bps / 1e4
    for fold_idx, (tr_idx, te_idx) in enumerate(
        outer.split(X, scenario.feature_set.t1, scenario.feature_set.t0)
    ):
        rf = RandomForestClassifier(
            **best_hp,
            random_state=DEFAULT_SEED + fold_idx * 7,
            class_weight="balanced",
            n_jobs=1,
        )
        rf.fit(X[tr_idx], y[tr_idx], sample_weight=w[tr_idx])
        proba = rf.predict_proba(X[te_idx])[:, 1].astype(np.float64)
        bets = 2.0 * proba - 1.0
        gross = log_rets[te_idx] * bets
        net = gross - rt_cost * np.abs(bets)
        pooled_net[te_idx] = net
        seen[te_idx] = True
    result: npt.NDArray[np.float64] = pooled_net[seen]
    return result


# ----------------------------------------------------------------------
# Report emission
# ----------------------------------------------------------------------


def _write_report(
    *,
    scenario: Scenario,
    fusion_cfg: ICWeightedFusionConfig,
    gates: dict[str, dict[str, Any]],
    report_summary: dict[str, Any],
    sharpe_trio: dict[str, float],
    per_signal_sharpe: dict[str, float],
    generated_at: str,
    wallclock: float | None,
    seed: int,
) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    weights_map = dict(zip(fusion_cfg.feature_names, fusion_cfg.weights, strict=True))

    payload: dict[str, Any] = {
        "generated_at": generated_at,
        "seed": seed,
        "scenario": {
            "n_symbols": len(SCENARIO_SYMBOLS),
            "symbols": list(SCENARIO_SYMBOLS),
            "bars_per_symbol": len(scenario.bars_per_symbol[SCENARIO_SYMBOLS[0]]),
            "n_events": int(scenario.y.shape[0]),
            "ic_per_signal": {k: float(v) for k, v in scenario.ic_per_signal.items()},
            "ic_ir_per_signal": {k: float(v) for k, v in scenario.ic_ir_per_signal.items()},
        },
        "fusion": {
            "feature_names": list(fusion_cfg.feature_names),
            "weights": {name: float(w) for name, w in weights_map.items()},
        },
        "gates": gates,
        "validation": report_summary,
        "sharpe_trio": sharpe_trio,
        "sharpe_gaps": {
            "bet_minus_fusion": sharpe_trio["bet_sized"] - sharpe_trio["fusion"],
            "fusion_minus_random": sharpe_trio["fusion"] - sharpe_trio["random"],
        },
        "per_signal_sharpe": per_signal_sharpe,
    }
    if wallclock is not None:
        payload["wall_clock_seconds"] = wallclock

    (REPORT_DIR / "pipeline_diagnostics.json").write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    weights_rows = "\n".join(
        f"| `{name}` | {weights_map[name]:.6f} | "
        f"{scenario.ic_per_signal[name]:+.4f} | "
        f"{scenario.ic_ir_per_signal[name]:+.4f} |"
        for name in fusion_cfg.feature_names
    )
    gates_rows = "\n".join(
        f"| `{name}` | {g['value']:+.4f} | {g['threshold']:+.4f} | {g['passed']} |"
        for name, g in gates.items()
    )
    sharpe_rows = "\n".join(
        f"| `{name}` | {value:+.4f} |" for name, value in sorted(sharpe_trio.items())
    )
    per_sig_rows = "\n".join(
        f"| `{name}` | {value:+.4f} |" for name, value in sorted(per_signal_sharpe.items())
    )

    md_lines = [
        "# Phase 4.8 - End-to-end Pipeline Diagnostic",
        "",
        f"**Generated at**: `{generated_at}`",
        "",
        f"- Seed: `{seed}`",
        f"- Symbols: `{', '.join(SCENARIO_SYMBOLS)}`",
        f"- Bars/symbol: `{payload['scenario']['bars_per_symbol']}`",
        f"- Pooled events: `{payload['scenario']['n_events']}`",
        "",
        "## Frozen fusion weights",
        "",
        "| Feature | Weight | IC | IC_IR |",
        "| --- | ---: | ---: | ---: |",
        weights_rows,
        "",
        "## Validation gates (G1 - G7)",
        "",
        "| Gate | Value | Threshold | Passed |",
        "| --- | ---: | ---: | :---: |",
        gates_rows,
        "",
        f"**all_passed**: `{report_summary['all_passed']}` "
        f"(failing: `{report_summary['failing_gate_names']}`)",
        "",
        "## Sharpe trio (pooled events, annualiser-agnostic)",
        "",
        "| Series | Sharpe |",
        "| --- | ---: |",
        sharpe_rows,
        "",
        f"- bet_sized - fusion gap: `{payload['sharpe_gaps']['bet_minus_fusion']:+.4f}`",
        f"- fusion - random gap: `{payload['sharpe_gaps']['fusion_minus_random']:+.4f}`",
        "",
        "## Per-signal unit-bet Sharpe",
        "",
        "| Signal | Sharpe |",
        "| --- | ---: |",
        per_sig_rows,
        "",
        "## Validation diagnostics",
        "",
        f"- DSR: `{report_summary['dsr']:+.4f}`",
        f"- PBO: `{report_summary['pbo']:+.4f}`",
        f"- Realistic round-trip bps: `{report_summary['scenario_realistic_round_trip_bps']:.2f}`",
        f"- Sharpe CI (realistic): `{report_summary['pnl_realistic_sharpe_ci']}`",
        "",
    ]
    (REPORT_DIR / "pipeline_diagnostics.md").write_text("\n".join(md_lines), encoding="utf-8")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


def main() -> None:
    seed = int(os.environ.get("APEX_SEED", "42"))
    os.environ.setdefault("APEX_SEED", str(seed))
    generated_at = _resolve_generated_at()
    start = time.perf_counter()

    scenario = build_scenario(seed=seed)

    outer_cpcv = build_outer_cpcv()
    inner_cpcv = build_inner_cpcv()

    # Pooled training + tuning.
    baseline = BaselineMetaLabeler(cpcv=outer_cpcv, seed=seed)
    training_result = baseline.train(scenario.feature_set, scenario.y, scenario.sample_weights)
    tuner = NestedCPCVTuner(
        search_space=REDUCED_TUNING_SEARCH_SPACE,
        outer_cpcv=outer_cpcv,
        inner_cpcv=inner_cpcv,
        seed=seed,
    )
    tuning_result = tuner.tune(scenario.feature_set, scenario.y, scenario.sample_weights)

    # Single-symbol validation slice.
    bars_for_pnl_symbol = SCENARIO_SYMBOLS[0]
    mask = np.asarray(
        [s == bars_for_pnl_symbol for s in scenario.labels["symbol"].to_list()],
        dtype=bool,
    )
    from features.meta_labeler.feature_builder import MetaLabelerFeatureSet

    ss_features = MetaLabelerFeatureSet(
        X=scenario.feature_set.X[mask],
        feature_names=scenario.feature_set.feature_names,
        t0=scenario.feature_set.t0[mask],
        t1=scenario.feature_set.t1[mask],
    )
    ss_y = scenario.y[mask]
    ss_w = scenario.sample_weights[mask]

    baseline_ss = BaselineMetaLabeler(cpcv=outer_cpcv, seed=seed)
    training_result_ss = baseline_ss.train(ss_features, ss_y, ss_w)
    tuner_ss = NestedCPCVTuner(
        search_space=REDUCED_TUNING_SEARCH_SPACE,
        outer_cpcv=outer_cpcv,
        inner_cpcv=inner_cpcv,
        seed=seed,
    )
    tuning_result_ss = tuner_ss.tune(ss_features, ss_y, ss_w)
    validator = MetaLabelerValidator(
        cpcv=outer_cpcv, cost_scenario=CostScenario.REALISTIC, seed=seed
    )
    report = validator.validate(
        training_result=training_result_ss,
        tuning_result=tuning_result_ss,
        features=ss_features,
        y=ss_y,
        sample_weights=ss_w,
        bars_for_pnl=scenario.bars_per_symbol[bars_for_pnl_symbol],
    )

    # Fusion.
    ic_report = _build_ic_report(scenario)
    activation = FeatureActivationConfig(
        activated_features=frozenset(SCENARIO_SIGNAL_NAMES),
        rejected_features=frozenset(),
        generated_at=datetime.fromisoformat(generated_at),
        pbo_of_final_set=0.05,
    )
    fusion_cfg = ICWeightedFusionConfig.from_ic_report(ic_report, activation)
    fusion_df = ICWeightedFusion(fusion_cfg).compute(scenario.signals_df)

    # Sharpe trio on pooled events.
    evt_log = _event_log_returns(scenario)
    fusion_at_evt = _fusion_score_at_events(fusion_df, scenario)
    fusion_pnl = np.sign(fusion_at_evt) * evt_log
    rnd_rng = np.random.default_rng(seed + 2)
    random_pnl = np.sign(rnd_rng.uniform(-1.0, 1.0, size=evt_log.shape[0])) * evt_log
    bet_pnl = _bet_sized_pool_pnl(scenario, tuning_result.best_hyperparameters_per_fold[0])

    sharpe_trio = {
        "bet_sized": _sharpe(bet_pnl),
        "fusion": _sharpe(fusion_pnl),
        "random": _sharpe(random_pnl),
    }
    per_signal_sharpe: dict[str, float] = {}
    for name in SCENARIO_SIGNAL_NAMES:
        sig_at_evt = scenario.feature_set.X[:, SCENARIO_SIGNAL_NAMES.index(name)]
        per_signal_sharpe[name] = _sharpe(np.sign(sig_at_evt) * evt_log)

    gates = {
        g.name: {
            "value": float(g.value),
            "threshold": float(g.threshold),
            "passed": bool(g.passed),
        }
        for g in report.gates
    }
    report_summary = {
        "all_passed": bool(report.all_passed),
        "failing_gate_names": list(report.failing_gate_names),
        "pnl_realistic_sharpe": float(report.pnl_realistic_sharpe),
        "pnl_realistic_sharpe_ci": [
            float(report.pnl_realistic_sharpe_ci[0]),
            float(report.pnl_realistic_sharpe_ci[1]),
        ],
        "dsr": float(report.dsr),
        "pbo": float(report.pbo),
        "scenario_realistic_round_trip_bps": float(report.scenario_realistic_round_trip_bps),
        "tuning_stability_index": float(tuning_result.stability_index),
    }

    wallclock = _resolve_wallclock(time.perf_counter() - start)
    _write_report(
        scenario=scenario,
        fusion_cfg=fusion_cfg,
        gates=gates,
        report_summary=report_summary,
        sharpe_trio=sharpe_trio,
        per_signal_sharpe=per_signal_sharpe,
        generated_at=generated_at,
        wallclock=wallclock,
        seed=seed,
    )
    _log.info(
        "phase_4_8_report_written",
        all_passed=report_summary["all_passed"],
        sharpe_trio=sharpe_trio,
    )
    # Keep training_result referenced so Ruff does not flag it as
    # unused: the pooled baseline's aggregate feature importances are
    # a legitimate diagnostic to log even when the single-symbol slice
    # drives the validation report.
    _log.debug(
        "phase_4_8_pooled_feature_importances",
        importances=training_result.feature_importances,
    )


if __name__ == "__main__":
    main()
