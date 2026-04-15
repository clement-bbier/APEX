"""Phase 4.7 — unit tests for the IC-weighted fusion engine.

Mirrors PHASE_4_SPEC §3.7 (test list + DoD Sharpe assertion) and the
audit at ``reports/phase_4_7/audit.md`` §8.
"""

from __future__ import annotations

import math
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from features.fusion import ICWeightedFusion, ICWeightedFusionConfig
from features.ic.base import ICResult
from features.ic.report import ICReport
from features.integration.config import FeatureActivationConfig

REPO_ROOT = Path(__file__).resolve().parents[4]


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _ic_result(name: str, ic_ir: float, *, ic: float = 0.05) -> ICResult:
    """Minimal ICResult carrying only the fields 4.7 actually reads."""
    return ICResult(
        ic=ic,
        ic_ir=ic_ir,
        p_value=0.01,
        n_samples=500,
        ci_low=ic - 0.01,
        ci_high=ic + 0.01,
        feature_name=name,
        horizon_bars=5,
    )


def _activation(names: list[str]) -> FeatureActivationConfig:
    return FeatureActivationConfig(
        activated_features=frozenset(names),
        rejected_features=frozenset(),
        generated_at=datetime(2026, 4, 15, tzinfo=UTC),
        pbo_of_final_set=0.05,
    )


def _signals(n: int, *, seed: int, feature_names: list[str]) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    data: dict[str, object] = {
        "timestamp": np.arange(n, dtype=np.int64),
        "symbol": ["TEST"] * n,
    }
    for name in feature_names:
        data[name] = rng.standard_normal(n).astype(np.float64)
    return pl.DataFrame(data)


# ----------------------------------------------------------------------
# 1 — weights live on the simplex
# ----------------------------------------------------------------------


def test_weights_sum_to_one() -> None:
    report = ICReport(
        [
            _ic_result("alpha", 1.5),
            _ic_result("beta", 0.5),
            _ic_result("gamma", 0.25),
        ]
    )
    cfg = ICWeightedFusionConfig.from_ic_report(report, _activation(["alpha", "beta", "gamma"]))
    assert math.isclose(math.fsum(cfg.weights), 1.0, abs_tol=1e-12)


def test_weights_proportional_to_abs_ic_ir() -> None:
    report = ICReport(
        [
            _ic_result("a", 2.0),
            _ic_result("b", 1.0),
        ]
    )
    cfg = ICWeightedFusionConfig.from_ic_report(report, _activation(["a", "b"]))
    # a gets 2/3, b gets 1/3.
    mapping = dict(zip(cfg.feature_names, cfg.weights, strict=True))
    assert math.isclose(mapping["a"], 2 / 3, abs_tol=1e-12)
    assert math.isclose(mapping["b"], 1 / 3, abs_tol=1e-12)


def test_weights_use_absolute_value_on_negative_ic_ir() -> None:
    # Negative IC_IR still contributes via its magnitude.
    report = ICReport(
        [
            _ic_result("pos", 1.0),
            _ic_result("neg", -1.0),
        ]
    )
    cfg = ICWeightedFusionConfig.from_ic_report(report, _activation(["pos", "neg"]))
    mapping = dict(zip(cfg.feature_names, cfg.weights, strict=True))
    assert math.isclose(mapping["pos"], 0.5, abs_tol=1e-12)
    assert math.isclose(mapping["neg"], 0.5, abs_tol=1e-12)


# ----------------------------------------------------------------------
# 2 — linear-combination sanity
# ----------------------------------------------------------------------


def test_single_feature_equals_that_feature() -> None:
    report = ICReport([_ic_result("only", 1.25)])
    cfg = ICWeightedFusionConfig.from_ic_report(report, _activation(["only"]))
    signals = _signals(20, seed=42, feature_names=["only"])
    out = ICWeightedFusion(cfg).compute(signals)
    expected = signals["only"].to_numpy()
    np.testing.assert_array_almost_equal(out["fusion_score"].to_numpy(), expected)


def test_two_features_equal_weight_when_ic_ir_equal() -> None:
    report = ICReport([_ic_result("a", 0.8), _ic_result("b", 0.8)])
    cfg = ICWeightedFusionConfig.from_ic_report(report, _activation(["a", "b"]))
    signals = _signals(50, seed=1, feature_names=["a", "b"])
    out = ICWeightedFusion(cfg).compute(signals)
    expected = 0.5 * signals["a"].to_numpy() + 0.5 * signals["b"].to_numpy()
    np.testing.assert_array_almost_equal(out["fusion_score"].to_numpy(), expected)


def test_fusion_score_linear_combination() -> None:
    cfg = ICWeightedFusionConfig(
        feature_names=("a", "b", "c"),
        weights=(0.5, 0.3, 0.2),
    )
    signals = _signals(100, seed=7, feature_names=["a", "b", "c"])
    out = ICWeightedFusion(cfg).compute(signals)
    expected = (
        0.5 * signals["a"].to_numpy()
        + 0.3 * signals["b"].to_numpy()
        + 0.2 * signals["c"].to_numpy()
    )
    np.testing.assert_array_almost_equal(out["fusion_score"].to_numpy(), expected)


# ----------------------------------------------------------------------
# 3 — ic_report / activation mismatch handling
# ----------------------------------------------------------------------


def test_ic_report_extra_features_silently_dropped() -> None:
    # `stale` is in the report but was rejected by Phase 3.12; must
    # not propagate into weights.
    report = ICReport(
        [
            _ic_result("kept_a", 1.0),
            _ic_result("kept_b", 1.0),
            _ic_result("stale", 10.0),
        ]
    )
    cfg = ICWeightedFusionConfig.from_ic_report(report, _activation(["kept_a", "kept_b"]))
    assert cfg.feature_names == ("kept_a", "kept_b")
    assert all(math.isclose(w, 0.5, abs_tol=1e-12) for w in cfg.weights)


def test_activated_feature_missing_from_ic_report_raises() -> None:
    report = ICReport([_ic_result("a", 1.0)])
    with pytest.raises(ValueError, match="missing activated features"):
        ICWeightedFusionConfig.from_ic_report(report, _activation(["a", "b"]))


def test_duplicate_feature_in_ic_report_raises() -> None:
    report = ICReport(
        [
            _ic_result("a", 1.0),
            _ic_result("a", 2.0),  # same feature, different horizon
            _ic_result("b", 1.0),
        ]
    )
    with pytest.raises(ValueError, match="duplicate entries"):
        ICWeightedFusionConfig.from_ic_report(report, _activation(["a", "b"]))


def test_all_zero_ic_ir_raises() -> None:
    report = ICReport([_ic_result("a", 0.0), _ic_result("b", 0.0)])
    with pytest.raises(ValueError, match=r"Σ .*IC_IR.*zero"):
        ICWeightedFusionConfig.from_ic_report(report, _activation(["a", "b"]))


def test_empty_activation_raises() -> None:
    report = ICReport([_ic_result("a", 1.0)])
    empty = FeatureActivationConfig(
        activated_features=frozenset(),
        rejected_features=frozenset({"a"}),
        generated_at=datetime(2026, 4, 15, tzinfo=UTC),
        pbo_of_final_set=None,
    )
    with pytest.raises(ValueError, match="no activated features"):
        ICWeightedFusionConfig.from_ic_report(report, empty)


# ----------------------------------------------------------------------
# 4 — determinism
# ----------------------------------------------------------------------


def test_feature_names_sorted_alphabetically_for_determinism() -> None:
    # Insertion order: z, a, m → output order must be a, m, z.
    report = ICReport([_ic_result("z", 1.0), _ic_result("a", 2.0), _ic_result("m", 3.0)])
    cfg = ICWeightedFusionConfig.from_ic_report(report, _activation(["a", "m", "z"]))
    assert cfg.feature_names == ("a", "m", "z")


def test_compute_deterministic_reproducible() -> None:
    cfg = ICWeightedFusionConfig(feature_names=("a", "b"), weights=(0.6, 0.4))
    signals = _signals(40, seed=99, feature_names=["a", "b"])
    out1 = ICWeightedFusion(cfg).compute(signals)
    out2 = ICWeightedFusion(cfg).compute(signals)
    assert out1.equals(out2)


# ----------------------------------------------------------------------
# 5 — compute input validation
# ----------------------------------------------------------------------


def test_compute_missing_column_raises() -> None:
    cfg = ICWeightedFusionConfig(feature_names=("a", "b"), weights=(0.5, 0.5))
    bad = _signals(10, seed=0, feature_names=["a"])  # missing 'b'
    with pytest.raises(ValueError, match="missing required columns"):
        ICWeightedFusion(cfg).compute(bad)


def test_compute_missing_timestamp_raises() -> None:
    cfg = ICWeightedFusionConfig(feature_names=("a",), weights=(1.0,))
    bad = pl.DataFrame({"symbol": ["X"] * 5, "a": [0.1, 0.2, 0.3, 0.4, 0.5]})
    with pytest.raises(ValueError, match="missing required columns"):
        ICWeightedFusion(cfg).compute(bad)


def test_compute_null_value_raises() -> None:
    cfg = ICWeightedFusionConfig(feature_names=("a",), weights=(1.0,))
    df = pl.DataFrame(
        {
            "timestamp": [1, 2, 3],
            "symbol": ["X", "X", "X"],
            "a": [0.1, None, 0.3],
        }
    )
    with pytest.raises(ValueError, match="null value"):
        ICWeightedFusion(cfg).compute(df)


def test_compute_nan_value_raises() -> None:
    cfg = ICWeightedFusionConfig(feature_names=("a",), weights=(1.0,))
    df = pl.DataFrame(
        {
            "timestamp": [1, 2, 3],
            "symbol": ["X", "X", "X"],
            "a": [0.1, float("nan"), 0.3],
        }
    )
    with pytest.raises(ValueError, match="NaN value"):
        ICWeightedFusion(cfg).compute(df)


def test_compute_int64_feature_column_is_accepted() -> None:
    cfg = ICWeightedFusionConfig(feature_names=("a",), weights=(1.0,))
    df = pl.DataFrame(
        {
            "timestamp": [1, 2, 3],
            "symbol": ["X", "X", "X"],
            "a": pl.Series("a", [1, 2, 3], dtype=pl.Int64),
        }
    )

    result = ICWeightedFusion(cfg).compute(df)

    assert result.height == df.height


def test_compute_empty_dataframe_raises() -> None:
    cfg = ICWeightedFusionConfig(feature_names=("a",), weights=(1.0,))
    empty = pl.DataFrame(
        {
            "timestamp": pl.Series("timestamp", [], dtype=pl.Int64),
            "symbol": pl.Series("symbol", [], dtype=pl.Utf8),
            "a": pl.Series("a", [], dtype=pl.Float64),
        }
    )
    with pytest.raises(ValueError, match="empty"):
        ICWeightedFusion(cfg).compute(empty)


# ----------------------------------------------------------------------
# 6 — output contract
# ----------------------------------------------------------------------


def test_timestamp_preserved() -> None:
    cfg = ICWeightedFusionConfig(feature_names=("a",), weights=(1.0,))
    ts = [1000, 2000, 3000]
    df = pl.DataFrame({"timestamp": ts, "symbol": ["X", "X", "X"], "a": [0.1, 0.2, 0.3]})
    out = ICWeightedFusion(cfg).compute(df)
    assert out["timestamp"].to_list() == ts


def test_symbol_preserved() -> None:
    cfg = ICWeightedFusionConfig(feature_names=("a",), weights=(1.0,))
    df = pl.DataFrame(
        {
            "timestamp": [1, 2, 3],
            "symbol": ["AAPL", "BTC", "ETH"],
            "a": [0.1, 0.2, 0.3],
        }
    )
    out = ICWeightedFusion(cfg).compute(df)
    assert out["symbol"].to_list() == ["AAPL", "BTC", "ETH"]


def test_output_schema_matches_contract() -> None:
    cfg = ICWeightedFusionConfig(feature_names=("a",), weights=(1.0,))
    signals = _signals(10, seed=0, feature_names=["a"])
    out = ICWeightedFusion(cfg).compute(signals)
    assert out.columns == ["timestamp", "symbol", "fusion_score"]
    assert out["fusion_score"].dtype == pl.Float64


def test_extra_input_columns_are_tolerated() -> None:
    cfg = ICWeightedFusionConfig(feature_names=("a",), weights=(1.0,))
    df = pl.DataFrame(
        {
            "timestamp": [1, 2],
            "symbol": ["X", "X"],
            "a": [0.1, 0.2],
            "ignored": ["foo", "bar"],
        }
    )
    out = ICWeightedFusion(cfg).compute(df)
    assert out.columns == ["timestamp", "symbol", "fusion_score"]


# ----------------------------------------------------------------------
# 7 — direct-construction validation
# ----------------------------------------------------------------------


def test_config_rejects_negative_weight() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ICWeightedFusionConfig(feature_names=("a", "b"), weights=(1.2, -0.2))


def test_config_rejects_weights_not_summing_to_one() -> None:
    with pytest.raises(ValueError, match=r"sum to 1\.0"):
        ICWeightedFusionConfig(feature_names=("a", "b"), weights=(0.3, 0.3))


def test_config_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        ICWeightedFusionConfig(feature_names=("a", "b"), weights=(1.0,))


def test_config_rejects_empty_feature_names() -> None:
    with pytest.raises(ValueError, match="at least one"):
        ICWeightedFusionConfig(feature_names=(), weights=())


def test_config_rejects_duplicate_feature_names() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        ICWeightedFusionConfig(feature_names=("a", "a"), weights=(0.5, 0.5))


def test_config_rejects_non_finite_weight() -> None:
    with pytest.raises(ValueError, match="finite"):
        ICWeightedFusionConfig(feature_names=("a",), weights=(float("nan"),))


# ----------------------------------------------------------------------
# 8 — anti-leakage property test
# ----------------------------------------------------------------------


def test_weights_frozen_permuting_future_signals_does_not_change_past_score() -> None:
    """Regression guard for ADR-0005 D7: weights are frozen at
    construction; mutating future rows after construction must not
    alter any already-computed past fusion score.
    """
    rng = np.random.default_rng(123)
    n = 100
    signals = pl.DataFrame(
        {
            "timestamp": np.arange(n, dtype=np.int64),
            "symbol": ["X"] * n,
            "a": rng.standard_normal(n).astype(np.float64),
            "b": rng.standard_normal(n).astype(np.float64),
        }
    )
    report = ICReport([_ic_result("a", 1.0), _ic_result("b", 2.0)])
    cfg = ICWeightedFusionConfig.from_ic_report(report, _activation(["a", "b"]))
    engine = ICWeightedFusion(cfg)

    past = signals.head(n // 2)
    baseline = engine.compute(past)

    # Perturb future rows in a second frame; past half stays byte-
    # identical.
    future_mutated = signals.with_columns(
        pl.when(pl.col("timestamp") >= n // 2)
        .then(pl.col("a") + 1000.0)
        .otherwise(pl.col("a"))
        .alias("a"),
        pl.when(pl.col("timestamp") >= n // 2)
        .then(pl.col("b") - 1000.0)
        .otherwise(pl.col("b"))
        .alias("b"),
    )
    after = engine.compute(future_mutated.head(n // 2))
    assert baseline.equals(after)


# ----------------------------------------------------------------------
# 9 — DoD Sharpe assertion on a controlled synthetic
# ----------------------------------------------------------------------


def _sharpe(series: np.ndarray) -> float:
    std = series.std(ddof=1)
    if std == 0.0:
        return 0.0
    return float(series.mean() / std)


def test_fusion_sharpe_exceeds_best_individual_on_synthetic() -> None:
    """DoD from PHASE_4_SPEC §3.7 — textbook IC-weighted fusion scenario.

    Three signals carry independent noisy observations of the same
    latent alpha. Each signal, on its own, tracks the alpha with a
    different noise level; the IC-weighted fusion combines them so
    that the independent observation noise averages out while the
    common alpha reinforces.

    Statistical subtlety: ADR-0005 D7 uses the simple IC-weighted
    formula ``w_i ∝ |IC_IR_i|``, which is NOT the Markowitz-optimal
    mixing weight ``w_i ∝ IC_IR_i / σ²_ε_i``. When noise levels are
    disparate, the lowest-noise signal can already be near-optimal
    on its own, so on a specific finite-sample draw fusion may
    occasionally trail the best individual by O(1/√n). The DoD
    therefore holds *in expectation* (under LLN) rather than per
    draw. We evaluate this with two robust checks over a
    deterministic seed panel:

      1. Mean Sharpe uplift ``E[fusion − best_individual]`` must be
         strictly positive — fusion dominates on expectation.
      2. Fusion must beat the best individual on a strict majority
         of panel seeds — defends against cherry-picking a single
         favourable draw.

    Both checks must pass; either failing is a DoD regression.
    """
    n = 4000
    # Deterministic panel — broad enough that any single unlucky
    # draw cannot flip both the mean and the majority simultaneously.
    seeds = (7, 11, 17, 23, 29, 42, 73, 101, 313, 2026)
    noise_levels = (0.4, 0.8, 1.2)
    min_mean_uplift = 1e-3  # ``≈ 0.1%`` Sharpe advantage on average.
    min_majority = 0.6  # fusion must win on ``≥ 60%`` of seeds.

    per_seed: list[tuple[int, float, float]] = []  # (seed, fusion, best)
    for seed in seeds:
        rng = np.random.default_rng(seed)
        alpha = rng.standard_normal(n)
        returns = 0.25 * alpha + rng.standard_normal(n) * 0.1
        signals_by_name = {
            f"sig_{i}": alpha + rng.standard_normal(n) * sigma
            for i, sigma in enumerate(noise_levels)
        }

        def _ic_ir(sig: np.ndarray, ret: np.ndarray = returns) -> float:
            c = float(np.corrcoef(sig, ret)[0, 1])
            return c / max(1e-6, 1.0 - c * c)

        report = ICReport([_ic_result(name, _ic_ir(sig)) for name, sig in signals_by_name.items()])
        cfg = ICWeightedFusionConfig.from_ic_report(report, _activation(list(signals_by_name)))
        frame_data: dict[str, object] = {
            "timestamp": np.arange(n, dtype=np.int64),
            "symbol": ["SYN"] * n,
        }
        frame_data.update(signals_by_name)
        fusion = ICWeightedFusion(cfg).compute(pl.DataFrame(frame_data))["fusion_score"].to_numpy()

        individual = {
            name: _sharpe(returns * np.sign(sig)) for name, sig in signals_by_name.items()
        }
        s_fusion = _sharpe(returns * np.sign(fusion))
        best_individual = max(individual.values())
        per_seed.append((seed, s_fusion, best_individual))

    deltas = [fusion - best for _, fusion, best in per_seed]
    mean_uplift = float(np.mean(deltas))
    wins = sum(1 for d in deltas if d > 0.0)
    win_rate = wins / len(per_seed)

    assert mean_uplift > min_mean_uplift, (
        f"DoD regression: mean Sharpe uplift {mean_uplift:+.4f} ≤ {min_mean_uplift:+.4f}; "
        f"per-seed (seed, fusion, best): {per_seed}"
    )
    assert win_rate >= min_majority, (
        f"DoD regression: fusion beat best individual on {wins}/{len(per_seed)} seeds "
        f"(win rate {win_rate:.2f} < {min_majority:.2f}); per-seed: {per_seed}"
    )


# ----------------------------------------------------------------------
# 10 — scope guard: services/s04_fusion_engine/ must be untouched by 4.7
# ----------------------------------------------------------------------


def test_services_s04_fusion_engine_untouched_by_phase_4_7_branch() -> None:
    """Scope guard per PHASE_4_SPEC §3.7 DoD #6.

    Verifies that the current 4.7 branch has not modified any file
    under ``services/s04_fusion_engine/``. Implemented via ``git
    diff --name-only main...HEAD``. Skipped when the test is run
    outside a git checkout or when the ``main`` branch cannot be
    located (e.g. in a shallow sandbox clone).
    """
    git_dir = REPO_ROOT / ".git"
    if not git_dir.exists():
        pytest.skip("not a git checkout")
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "main...HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("git unavailable or main branch not resolvable")
    changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    offenders = [p for p in changed if p.startswith("services/s04_fusion_engine/")]
    assert not offenders, (
        f"Phase 4.7 must not modify services/s04_fusion_engine/; offending files: {offenders}"
    )
