"""Generate the Phase 4.7 IC-weighted Fusion diagnostic report.

End-to-end demo of the fusion contract defined in ADR-0005 D7 and
PHASE_4_SPEC §3.7. Pipeline:

1. Build a synthetic scenario driven by ``APEX_SEED`` (1 thin alpha
   channel + 2 noise signals over ``n=2000`` bars, single symbol
   ``"SYN"``). Forward returns carry a small alpha component so
   ``IC_IR`` is measurable without dominating noise.
2. Compute each signal's ``IC`` / ``IC_IR`` against realised forward
   returns and wrap them in a Phase 3.3-compatible :class:`ICReport`.
3. Build the :class:`ICWeightedFusionConfig` via ``from_ic_report``
   using a :class:`FeatureActivationConfig` that activates all three
   channels (the Phase 3.12 decision is mocked for the demo).
4. Run :meth:`ICWeightedFusion.compute` and collect diagnostics:
   - the frozen weights vector,
   - score distribution percentiles (P05/P25/P50/P75/P95),
   - per-signal Pearson correlations between input and fusion score,
   - Sharpe comparison table (fusion vs each individual signal).
5. Emit ``reports/phase_4_7/fusion_diagnostics.{md,json}``.

Reproducibility follows the 4.3/4.4/4.5/4.6 contract:
    - ``APEX_SEED`` (default 42) seeds numpy.
    - ``APEX_REPORT_NOW`` freezes the ``generated_at`` header.
    - ``APEX_REPORT_WALLCLOCK_MODE`` ∈ {record, zero, omit}.

Usage:

    APEX_SEED=42 \\
      APEX_REPORT_NOW=2026-04-15T00:00:00+00:00 \\
      APEX_REPORT_WALLCLOCK_MODE=omit \\
      python3 scripts/generate_phase_4_7_report.py

The script is a *demo*, not a gate: CI exercises
:class:`ICWeightedFusion` through the unit tests. The generator is
kept alive so reviewers can inspect end-to-end behaviour and so the
artifact stays current as the underlying module evolves.

References:
    PHASE_4_SPEC §3.7.
    ADR-0005 D7.
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

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "reports" / "phase_4_7"

_log = structlog.get_logger(__name__)

_FEATURE_NAMES: tuple[str, str, str] = ("sig_0", "sig_1", "sig_2")
_NOISE_LEVELS: tuple[float, float, float] = (0.4, 0.8, 1.2)
_N_BARS: int = 4000
_SYMBOL: str = "SYN"


# ----------------------------------------------------------------------
# Header helpers — shared contract with the 4.3/4.4/4.5/4.6 reports
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
# Synthetic scenario — 3 noisy observations of one latent alpha
# ----------------------------------------------------------------------


def _synthetic_scenario(
    seed: int,
) -> tuple[dict[str, npt.NDArray[np.float64]], npt.NDArray[np.float64]]:
    """Build ``(signals_by_name, forward_returns)``.

    Textbook IC-weighted fusion scenario (Grinold & Kahn 1999 §4):
    three signals carry independent noisy observations of the same
    latent alpha with different noise levels. Forward returns are
    driven by the same latent alpha, so each signal has positive
    but partial predictive power and IC-weighted fusion strictly
    improves on every individual signal.
    """
    rng = np.random.default_rng(seed)
    alpha = rng.standard_normal(_N_BARS)
    forward_returns = 0.25 * alpha + rng.standard_normal(_N_BARS) * 0.1
    signals_by_name: dict[str, npt.NDArray[np.float64]] = {
        _FEATURE_NAMES[i]: alpha + rng.standard_normal(_N_BARS) * sigma
        for i, sigma in enumerate(_NOISE_LEVELS)
    }
    return signals_by_name, forward_returns


def _measure_ic_ir(
    signal: npt.NDArray[np.float64],
    forward_returns: npt.NDArray[np.float64],
) -> tuple[float, float]:
    """Return ``(ic, ic_ir)`` for a single signal against realised returns.

    IC is the Pearson correlation on this synthetic (pragmatic proxy
    for the Spearman-based production metric). ``IC_IR`` uses the
    bootstrapped per-period standard deviation across 20 folds so the
    proxy has a meaningful denominator even on a single simulated run.
    """
    ic = float(np.corrcoef(signal, forward_returns)[0, 1])
    # Fold the sample into 20 chunks; compute a per-chunk IC and take
    # ``mean/std`` as a cheap ``IC_IR`` proxy.
    chunks = np.array_split(np.column_stack([signal, forward_returns]), 20)
    per_chunk = np.array([float(np.corrcoef(c[:, 0], c[:, 1])[0, 1]) for c in chunks if len(c) > 2])
    std = float(per_chunk.std(ddof=1))
    if std <= 0.0 or not np.isfinite(std):
        ic_ir = 0.0
    else:
        ic_ir = float(per_chunk.mean() / std)
    return ic, ic_ir


def _build_ic_report(
    signals: dict[str, npt.NDArray[np.float64]],
    forward_returns: npt.NDArray[np.float64],
) -> tuple[ICReport, dict[str, tuple[float, float]]]:
    """Materialise the Phase 3.3-compatible :class:`ICReport`."""
    measurements: dict[str, tuple[float, float]] = {}
    results: list[ICResult] = []
    for name in sorted(signals):
        ic, ic_ir = _measure_ic_ir(signals[name], forward_returns)
        measurements[name] = (ic, ic_ir)
        results.append(
            ICResult(
                ic=ic,
                ic_ir=ic_ir,
                p_value=0.01,
                n_samples=_N_BARS,
                ci_low=ic - 0.02,
                ci_high=ic + 0.02,
                feature_name=name,
                horizon_bars=1,
            )
        )
    return ICReport(results), measurements


# ----------------------------------------------------------------------
# Diagnostics
# ----------------------------------------------------------------------


def _score_percentiles(fusion_score: npt.NDArray[np.float64]) -> dict[str, float]:
    values = np.percentile(fusion_score, [5, 25, 50, 75, 95])
    return {
        "p05": float(values[0]),
        "p25": float(values[1]),
        "p50": float(values[2]),
        "p75": float(values[3]),
        "p95": float(values[4]),
    }


def _pearson(a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]) -> float:
    if a.std() == 0.0 or b.std() == 0.0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _sharpe(pnl: npt.NDArray[np.float64]) -> float:
    std = float(pnl.std(ddof=1))
    if std == 0.0:
        return 0.0
    return float(pnl.mean() / std)


def _sharpe_table(
    fusion_score: npt.NDArray[np.float64],
    signals: dict[str, npt.NDArray[np.float64]],
    forward_returns: npt.NDArray[np.float64],
) -> dict[str, float]:
    """Unit-size bet Sharpe: ``returns * sign(signal)``.

    Annualiser-agnostic (mean/std on centred PnL). Keys are the
    signal names plus ``fusion_score``.
    """
    table: dict[str, float] = {
        "fusion_score": _sharpe(forward_returns * np.sign(fusion_score)),
    }
    for name, sig in signals.items():
        table[name] = _sharpe(forward_returns * np.sign(sig))
    return table


# ----------------------------------------------------------------------
# Report emission
# ----------------------------------------------------------------------


def _write_report(
    *,
    config: ICWeightedFusionConfig,
    measurements: dict[str, tuple[float, float]],
    percentiles: dict[str, float],
    correlations: dict[str, float],
    sharpe: dict[str, float],
    best_individual_sharpe: float,
    generated_at: str,
    wallclock: float | None,
    seed: int,
) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    weights_map = dict(zip(config.feature_names, config.weights, strict=True))

    payload: dict[str, Any] = {
        "generated_at": generated_at,
        "seed": seed,
        "n_bars": _N_BARS,
        "symbol": _SYMBOL,
        "config": {
            "feature_names": list(config.feature_names),
            "weights": {name: float(w) for name, w in weights_map.items()},
        },
        "ic_measurements": {
            name: {"ic": float(ic), "ic_ir": float(ic_ir)}
            for name, (ic, ic_ir) in measurements.items()
        },
        "score_distribution": percentiles,
        "per_signal_correlation": correlations,
        "sharpe": sharpe,
        "fusion_beats_best_individual": bool(sharpe["fusion_score"] > best_individual_sharpe),
        "best_individual_sharpe": float(best_individual_sharpe),
    }
    if wallclock is not None:
        payload["wall_clock_seconds"] = wallclock

    json_path = REPORT_DIR / "fusion_diagnostics.json"
    json_path.write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    weights_rows = "\n".join(
        f"| `{name}` | {weights_map[name]:.6f} | {measurements[name][0]:+.4f} | "
        f"{measurements[name][1]:+.4f} |"
        for name in config.feature_names
    )
    sharpe_rows = "\n".join(
        f"| `{name}` | {value:+.4f} |" for name, value in sorted(sharpe.items())
    )
    percentile_rows = "\n".join(
        f"| {label.upper()} | {value:+.4f} |" for label, value in percentiles.items()
    )
    correlation_rows = "\n".join(
        f"| `{name}` | {value:+.4f} |" for name, value in sorted(correlations.items())
    )

    md_lines = [
        "# Phase 4.7 — IC-weighted Fusion Diagnostic",
        "",
        f"**Generated at**: `{generated_at}`",
        "",
        f"- Seed: `{seed}`",
        f"- Bars: `{_N_BARS}`",
        f"- Symbol: `{_SYMBOL}`",
        "",
        "## Frozen config",
        "",
        "| Feature | Weight | IC | IC_IR |",
        "| --- | ---: | ---: | ---: |",
        weights_rows,
        "",
        "## Fusion score distribution",
        "",
        "| Percentile | Value |",
        "| --- | ---: |",
        percentile_rows,
        "",
        "## Per-signal Pearson correlation (vs `fusion_score`)",
        "",
        "| Signal | ρ |",
        "| --- | ---: |",
        correlation_rows,
        "",
        "## Sharpe comparison (unit-size bet, annualiser-agnostic)",
        "",
        "| Series | Sharpe |",
        "| --- | ---: |",
        sharpe_rows,
        "",
        (
            "**Fusion beats best individual**: "
            f"`{payload['fusion_beats_best_individual']}` "
            f"(fusion={sharpe['fusion_score']:+.4f} vs best="
            f"{best_individual_sharpe:+.4f})"
        ),
        "",
    ]
    md_path = REPORT_DIR / "fusion_diagnostics.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


def main() -> None:
    seed = int(os.environ.get("APEX_SEED", "42"))
    os.environ.setdefault("APEX_SEED", str(seed))
    generated_at = _resolve_generated_at()
    start = time.perf_counter()

    signals_map, forward_returns = _synthetic_scenario(seed)

    ic_report, measurements = _build_ic_report(signals_map, forward_returns)
    activation = FeatureActivationConfig(
        activated_features=frozenset(_FEATURE_NAMES),
        rejected_features=frozenset(),
        generated_at=datetime.fromisoformat(generated_at),
        pbo_of_final_set=0.05,
    )
    config = ICWeightedFusionConfig.from_ic_report(ic_report, activation)

    signals_df = pl.DataFrame(
        {
            "timestamp": np.arange(_N_BARS, dtype=np.int64),
            "symbol": [_SYMBOL] * _N_BARS,
            **signals_map,
        }
    )
    fusion_df = ICWeightedFusion(config).compute(signals_df)
    fusion_score = fusion_df["fusion_score"].to_numpy()

    percentiles = _score_percentiles(fusion_score)
    correlations = {name: _pearson(sig, fusion_score) for name, sig in signals_map.items()}
    sharpe = _sharpe_table(fusion_score, signals_map, forward_returns)
    best_individual = max(sharpe[name] for name in _FEATURE_NAMES)

    wallclock = _resolve_wallclock(time.perf_counter() - start)
    _write_report(
        config=config,
        measurements=measurements,
        percentiles=percentiles,
        correlations=correlations,
        sharpe=sharpe,
        best_individual_sharpe=best_individual,
        generated_at=generated_at,
        wallclock=wallclock,
        seed=seed,
    )
    _log.info(
        "phase_4_7_report_written",
        weights={n: float(w) for n, w in zip(config.feature_names, config.weights, strict=True)},
        fusion_sharpe=sharpe["fusion_score"],
        best_individual_sharpe=best_individual,
    )


if __name__ == "__main__":
    main()
