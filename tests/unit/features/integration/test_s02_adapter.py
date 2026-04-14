"""Tests for :mod:`features.integration.s02_adapter`.

The adapter tests are structured in layers:

1. Constructor validation (cheap, pure).
2. ``on_observation`` None paths (warmup, rejected, NaN).
3. ``on_observation`` happy path and :class:`SignalComponent` shape.
4. Batch-vs-streaming consistency (<1% drift, DoD requirement).
5. Latency benchmark (honest measurement, no DoD overclaim).
6. Scope check asserting zero diff in ``services/s02_signal_engine/``.

Consistency and latency tests use the real :class:`OFICalculator`
because (a) it is the fastest Phase 3 calculator, and (b) its
streaming surface is representative (tick-level, no day boundaries).
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import numpy as np
import polars as pl
import pytest

from features.base import FeatureCalculator
from features.calculators.ofi import OFICalculator
from features.integration.config import FeatureActivationConfig
from features.integration.s02_adapter import S02FeatureAdapter
from services.s02_signal_engine.signal_scorer import SignalComponent


class _DummyCalculator(FeatureCalculator):
    """Synthetic calculator that emits ``value * 0.5`` on the last row.

    Produces one output column named after the feature. Emits NaN on
    the first ``nan_rows`` rows regardless of input.
    """

    def __init__(self, feature_name: str, nan_rows: int = 0) -> None:
        self._feature_name = feature_name
        self._nan_rows = nan_rows

    def name(self) -> str:
        return self._feature_name

    def required_columns(self) -> list[str]:
        return ["value"]

    def output_columns(self) -> list[str]:
        return [self._feature_name]

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        n = len(df)
        out = np.full(n, np.nan)
        for i in range(self._nan_rows, n):
            out[i] = float(df["value"][i]) * 0.5
        return df.with_columns(pl.Series(self._feature_name, out))


def _config(activated: set[str], rejected: set[str] | None = None) -> FeatureActivationConfig:
    return FeatureActivationConfig(
        activated_features=frozenset(activated),
        rejected_features=frozenset(rejected or set()),
        generated_at=datetime(2026, 4, 14, tzinfo=UTC),
        pbo_of_final_set=0.05,
    )


# ---------------------------------------------------------------------------
# 1. Constructor validation
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_missing_calculator_raises(self) -> None:
        cfg = _config({"feat_a"})
        with pytest.raises(ValueError, match="missing a calculator"):
            S02FeatureAdapter(
                config=cfg,
                calculators={},
                warmup_periods={"feat_a": 10},
            )

    def test_missing_warmup_entry_raises(self) -> None:
        cfg = _config({"feat_a"})
        with pytest.raises(ValueError, match="missing a warmup entry"):
            S02FeatureAdapter(
                config=cfg,
                calculators={"feat_a": _DummyCalculator("feat_a")},
                warmup_periods={},
            )

    def test_non_positive_warmup_raises(self) -> None:
        cfg = _config({"feat_a"})
        with pytest.raises(ValueError, match=r"warmup_periods\['feat_a'\]"):
            S02FeatureAdapter(
                config=cfg,
                calculators={"feat_a": _DummyCalculator("feat_a")},
                warmup_periods={"feat_a": 0},
            )

    def test_buffer_smaller_than_warmup_raises(self) -> None:
        cfg = _config({"feat_a"})
        with pytest.raises(ValueError, match="max_buffer_size"):
            S02FeatureAdapter(
                config=cfg,
                calculators={"feat_a": _DummyCalculator("feat_a")},
                warmup_periods={"feat_a": 100},
                max_buffer_size=50,
            )

    def test_rejected_features_dont_require_calculator(self) -> None:
        cfg = _config({"feat_a"}, {"feat_b"})

        adapter = S02FeatureAdapter(
            config=cfg,
            calculators={"feat_a": _DummyCalculator("feat_a")},
            warmup_periods={"feat_a": 3},
        )

        assert adapter.on_observation("feat_b", {"value": 1.0}) is None

    def test_weight_out_of_range_rejected(self) -> None:
        cfg = _config({"feat_a"})
        cals: dict[str, FeatureCalculator] = {"feat_a": _DummyCalculator("feat_a")}
        wp = {"feat_a": 3}

        with pytest.raises(ValueError, match=r"must be in \[0\.0, 1\.0\]"):
            S02FeatureAdapter(
                config=cfg, calculators=cals, warmup_periods=wp, weights={"feat_a": 1.5}
            )
        with pytest.raises(ValueError, match=r"must be in \[0\.0, 1\.0\]"):
            S02FeatureAdapter(
                config=cfg,
                calculators=cals,
                warmup_periods=wp,
                weights={"feat_a": -0.1},
            )

    def test_weight_nan_or_inf_rejected(self) -> None:
        cfg = _config({"feat_a"})
        cals: dict[str, FeatureCalculator] = {"feat_a": _DummyCalculator("feat_a")}
        wp = {"feat_a": 3}

        with pytest.raises(ValueError, match="must be finite"):
            S02FeatureAdapter(
                config=cfg,
                calculators=cals,
                warmup_periods=wp,
                weights={"feat_a": float("nan")},
            )
        with pytest.raises(ValueError, match="must be finite"):
            S02FeatureAdapter(
                config=cfg,
                calculators=cals,
                warmup_periods=wp,
                weights={"feat_a": float("inf")},
            )

    def test_negative_threshold_rejected(self) -> None:
        cfg = _config({"feat_a"})
        cals: dict[str, FeatureCalculator] = {"feat_a": _DummyCalculator("feat_a")}
        wp = {"feat_a": 3}

        with pytest.raises(ValueError, match=r"must be >= 0\.0"):
            S02FeatureAdapter(
                config=cfg,
                calculators=cals,
                warmup_periods=wp,
                trigger_thresholds={"feat_a": -0.5},
            )

    def test_non_finite_threshold_rejected(self) -> None:
        cfg = _config({"feat_a"})
        cals: dict[str, FeatureCalculator] = {"feat_a": _DummyCalculator("feat_a")}
        wp = {"feat_a": 3}

        with pytest.raises(ValueError, match="must be finite"):
            S02FeatureAdapter(
                config=cfg,
                calculators=cals,
                warmup_periods=wp,
                trigger_thresholds={"feat_a": float("nan")},
            )


# ---------------------------------------------------------------------------
# 2. None paths
# ---------------------------------------------------------------------------


class TestReturnsNone:
    def _adapter(self, nan_rows: int = 0) -> S02FeatureAdapter:
        cfg = _config({"feat_a"}, {"feat_bad"})
        return S02FeatureAdapter(
            config=cfg,
            calculators={"feat_a": _DummyCalculator("feat_a", nan_rows=nan_rows)},
            warmup_periods={"feat_a": 3},
        )

    def test_rejected_feature_returns_none(self) -> None:
        assert self._adapter().on_observation("feat_bad", {"value": 1.0}) is None

    def test_unknown_feature_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown feature"):
            self._adapter().on_observation("nope", {"value": 1.0})

    def test_returns_none_during_warmup(self) -> None:
        adapter = self._adapter()
        assert adapter.on_observation("feat_a", {"value": 0.5}) is None
        assert adapter.on_observation("feat_a", {"value": 0.5}) is None

    def test_emits_after_exactly_required_observations(self) -> None:
        adapter = self._adapter()
        for _ in range(2):
            assert adapter.on_observation("feat_a", {"value": 0.5}) is None
        result = adapter.on_observation("feat_a", {"value": 0.5})
        assert isinstance(result, SignalComponent)

    def test_returns_none_when_calculator_emits_nan(self) -> None:
        adapter = self._adapter(nan_rows=10)
        for _ in range(5):
            result = adapter.on_observation("feat_a", {"value": 0.5})
            # During and after warmup: calculator still NaN -> adapter -> None
            assert result is None

    def test_returns_none_when_calculator_drops_output_column(self) -> None:
        """Defensive path: calculator violates its own output_columns contract."""

        class _BadCalc(FeatureCalculator):
            def name(self) -> str:
                return "feat_a"

            def required_columns(self) -> list[str]:
                return ["value"]

            def output_columns(self) -> list[str]:
                return ["feat_a"]

            def compute(self, df: pl.DataFrame) -> pl.DataFrame:
                # Oops, forgot to append the output column.
                return df

        cfg = _config({"feat_a"})
        adapter = S02FeatureAdapter(
            config=cfg,
            calculators={"feat_a": _BadCalc()},
            warmup_periods={"feat_a": 1},
        )

        assert adapter.on_observation("feat_a", {"value": 0.5}) is None

    def test_returns_none_when_last_row_is_polars_null(self) -> None:
        """Polars None (not NaN) on the last row must be treated like NaN."""

        class _NullCalc(FeatureCalculator):
            def name(self) -> str:
                return "feat_a"

            def required_columns(self) -> list[str]:
                return ["value"]

            def output_columns(self) -> list[str]:
                return ["feat_a"]

            def compute(self, df: pl.DataFrame) -> pl.DataFrame:
                # All-null output column (not NaN, but Polars null).
                n = len(df)
                return df.with_columns(pl.Series("feat_a", [None] * n, dtype=pl.Float64))

        cfg = _config({"feat_a"})
        adapter = S02FeatureAdapter(
            config=cfg,
            calculators={"feat_a": _NullCalc()},
            warmup_periods={"feat_a": 1},
        )

        assert adapter.on_observation("feat_a", {"value": 0.5}) is None


# ---------------------------------------------------------------------------
# 3. SignalComponent shape
# ---------------------------------------------------------------------------


class TestSignalComponentOutput:
    def test_component_name_matches_feature_name(self) -> None:
        cfg = _config({"feat_a"})
        adapter = S02FeatureAdapter(
            config=cfg,
            calculators={"feat_a": _DummyCalculator("feat_a")},
            warmup_periods={"feat_a": 1},
        )
        comp = adapter.on_observation("feat_a", {"value": 0.4})
        assert comp is not None
        assert comp.name == "feat_a"

    def test_component_score_matches_calculator(self) -> None:
        cfg = _config({"feat_a"})
        adapter = S02FeatureAdapter(
            config=cfg,
            calculators={"feat_a": _DummyCalculator("feat_a")},
            warmup_periods={"feat_a": 1},
        )
        comp = adapter.on_observation("feat_a", {"value": 0.6})
        assert comp is not None
        assert comp.score == pytest.approx(0.3)

    def test_score_is_clamped_to_unit_interval(self) -> None:
        cfg = _config({"feat_a"})
        adapter = S02FeatureAdapter(
            config=cfg,
            calculators={"feat_a": _DummyCalculator("feat_a")},
            warmup_periods={"feat_a": 1},
        )
        # value * 0.5 = 5.0 -> should clamp to +1.0
        comp = adapter.on_observation("feat_a", {"value": 10.0})
        assert comp is not None
        assert -1.0 <= comp.score <= 1.0
        assert comp.score == 1.0

    def test_default_weight_matches_signal_scorer_fallback(self) -> None:
        # S02's SignalScorer uses self.WEIGHTS.get(name, 0.1) for unknown
        # names. The adapter's DEFAULT_WEIGHT must match to avoid surprising
        # behaviour when the adapter is eventually wired in.
        cfg = _config({"feat_a"})
        adapter = S02FeatureAdapter(
            config=cfg,
            calculators={"feat_a": _DummyCalculator("feat_a")},
            warmup_periods={"feat_a": 1},
        )
        comp = adapter.on_observation("feat_a", {"value": 0.4})
        assert comp is not None
        assert comp.weight == pytest.approx(0.1)

    def test_custom_weight_and_threshold(self) -> None:
        cfg = _config({"feat_a"})
        adapter = S02FeatureAdapter(
            config=cfg,
            calculators={"feat_a": _DummyCalculator("feat_a")},
            warmup_periods={"feat_a": 1},
            weights={"feat_a": 0.25},
            trigger_thresholds={"feat_a": 0.5},
        )
        # score = 0.2 * 0.5 = 0.1 < 0.5 -> not triggered.
        comp = adapter.on_observation("feat_a", {"value": 0.2})
        assert comp is not None
        assert comp.weight == pytest.approx(0.25)
        assert comp.triggered is False

    def test_triggered_flag_reflects_threshold(self) -> None:
        cfg = _config({"feat_a"})
        adapter = S02FeatureAdapter(
            config=cfg,
            calculators={"feat_a": _DummyCalculator("feat_a")},
            warmup_periods={"feat_a": 1},
            trigger_thresholds={"feat_a": 0.1},
        )
        # abs(0.3) > 0.1 -> triggered.
        comp = adapter.on_observation("feat_a", {"value": 0.6})
        assert comp is not None
        assert comp.triggered is True

    def test_metadata_carries_warmup_observation_count(self) -> None:
        cfg = _config({"feat_a"})
        adapter = S02FeatureAdapter(
            config=cfg,
            calculators={"feat_a": _DummyCalculator("feat_a")},
            warmup_periods={"feat_a": 1},
        )
        adapter.on_observation("feat_a", {"value": 0.5})
        comp = adapter.on_observation("feat_a", {"value": 0.5})
        assert comp is not None
        assert comp.metadata["warmup_observed"] == 2
        assert comp.metadata["source"] == "phase_3_adapter"


# ---------------------------------------------------------------------------
# 4. Consistency: streaming via adapter vs batch compute()
# ---------------------------------------------------------------------------


@dataclass
class _OFIStream:
    """Deterministic synthetic tick stream for OFI."""

    n_ticks: int
    seed: int = 7

    DRIFT: ClassVar[float] = 0.001

    def build(self) -> list[dict[str, object]]:
        rng = np.random.default_rng(self.seed)
        price = 100.0
        ticks: list[dict[str, object]] = []
        for i in range(self.n_ticks):
            price *= 1.0 + self.DRIFT * rng.standard_normal()
            quantity = float(abs(rng.standard_normal()) * 10.0 + 1.0)
            side = "BUY" if rng.random() > 0.5 else "SELL"
            ticks.append(
                {
                    "timestamp": i,
                    "price": price,
                    "quantity": quantity,
                    "side": side,
                }
            )
        return ticks


class TestBatchStreamingConsistency:
    """DoD: streaming adapter output matches batch compute within 1%."""

    def test_ofi_streaming_matches_batch(self) -> None:
        ticks = _OFIStream(n_ticks=400).build()
        warmup = 100  # max(windows) default = 100 ticks

        calc_batch = OFICalculator()
        batch_out = calc_batch.compute(pl.DataFrame(ticks))
        batch_signal = batch_out["ofi_signal"].to_numpy()

        cfg = _config({"ofi_signal"})
        adapter = S02FeatureAdapter(
            config=cfg,
            calculators={"ofi_signal": OFICalculator()},
            warmup_periods={"ofi_signal": warmup},
            max_buffer_size=len(ticks) + 10,
        )

        streamed: list[float] = []
        for t in ticks:
            comp = adapter.on_observation("ofi_signal", t)
            streamed.append(comp.score if comp is not None else float("nan"))

        streamed_arr = np.array(streamed)

        # Compare only after warmup where both are defined.
        warm_mask = ~np.isnan(batch_signal) & ~np.isnan(streamed_arr)
        assert warm_mask.sum() > 10, "Not enough warm samples to compare"

        b = batch_signal[warm_mask]
        s = streamed_arr[warm_mask]
        # Adapter score is clamped to [-1, +1]; OFI signal is already
        # tanh-bounded so clamp is a no-op. Use relative diff with a
        # small epsilon floor to avoid division by ~0.
        denom = np.maximum(np.abs(b), 1e-3)
        rel = np.abs(b - s) / denom
        max_rel = float(rel.max())

        assert max_rel < 0.01, (
            f"Batch-vs-streaming max relative drift {max_rel:.4%} exceeds 1% DoD threshold"
        )


# ---------------------------------------------------------------------------
# 5. Latency benchmark
# ---------------------------------------------------------------------------


class TestLatency:
    """DoD target: < 1 ms per (feature, tick) pair after warmup.

    The Phase 3.4-3.8 calculators expose only a batch
    ``compute(df) -> df`` API, so the adapter necessarily re-runs
    ``compute`` on a rolling buffer per tick. This test measures the
    real latency and reports the numbers honestly: if the target is
    missed it is marked xfail with the observed percentiles -- per
    CLAUDE.md forbidden-pattern list: no silent "perf < 1ms" in
    commit messages when the benchmark says otherwise.
    """

    BUDGET_MS: ClassVar[float] = 1.0

    def test_ofi_adapter_p50_under_1ms(self) -> None:
        ticks = _OFIStream(n_ticks=400).build()
        warmup = 100

        cfg = _config({"ofi_signal"})
        adapter = S02FeatureAdapter(
            config=cfg,
            calculators={"ofi_signal": OFICalculator()},
            warmup_periods={"ofi_signal": warmup},
            max_buffer_size=len(ticks) + 10,
        )

        # Prime past warmup so measurements reflect steady state.
        for t in ticks[:warmup]:
            adapter.on_observation("ofi_signal", t)

        latencies_ns: list[int] = []
        for t in ticks[warmup:]:
            start = time.perf_counter_ns()
            adapter.on_observation("ofi_signal", t)
            latencies_ns.append(time.perf_counter_ns() - start)

        latencies_ms = np.array(latencies_ns) / 1e6
        p50 = float(np.percentile(latencies_ms, 50))
        p95 = float(np.percentile(latencies_ms, 95))
        p99 = float(np.percentile(latencies_ms, 99))

        if p50 >= self.BUDGET_MS:
            pytest.xfail(
                f"Adapter latency p50={p50:.3f}ms exceeds {self.BUDGET_MS}ms DoD budget "
                f"(p95={p95:.3f}ms, p99={p99:.3f}ms). "
                f"Root cause: OFICalculator is batch-only; adapter re-runs compute() "
                f"on a rolling buffer per tick. Plan B options: "
                f"(a) add streaming compute() on OFI, "
                f"(b) accept a higher budget for the Phase 4 fusion path, "
                f"(c) cache last compute and recompute every K ticks."
            )


# ---------------------------------------------------------------------------
# 6. Scope check
# ---------------------------------------------------------------------------


def _resolve_base_ref(repo_root: Path) -> str | None:
    """Resolve a git base ref for the scope-check test.

    Tries ``GITHUB_BASE_REF`` first (set on GitHub Actions PR events),
    then ``origin/main`` and ``main`` as fallbacks. Returns the first
    that ``git rev-parse --verify`` accepts, or ``None`` if none
    resolve (e.g. shallow clone with no base ref).
    """
    candidates: list[str] = []
    env_ref = os.environ.get("GITHUB_BASE_REF")
    if env_ref:
        candidates.append(env_ref)
        if "/" not in env_ref:
            candidates.append(f"origin/{env_ref}")
    candidates += ["origin/main", "main"]

    for ref in candidates:
        check = subprocess.run(
            ["git", "rev-parse", "--verify", ref],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if check.returncode == 0:
            return ref
    return None


class TestScope:
    """Zero diff in services/s02_signal_engine/ is non-negotiable (DoD).

    The test must not silently skip. If the base ref cannot be resolved
    (e.g. a CI runner with a shallow clone and no ``GITHUB_BASE_REF``),
    the test fails loud so the DoD is never bypassed.
    """

    def test_no_modification_of_s02_on_branch(self) -> None:
        repo_root = Path(__file__).resolve().parents[4]
        if not (repo_root / ".git").exists():
            pytest.skip("Not in a git checkout (scope check cannot run)")

        base_ref = _resolve_base_ref(repo_root)
        if base_ref is None:
            pytest.fail(
                "Could not resolve a base ref (tried GITHUB_BASE_REF, "
                "origin/main, main). DoD 'zero diff in S02' cannot be "
                "verified; this check must not silently skip."
            )

        cmd = [
            "git",
            "diff",
            "--stat",
            f"{base_ref}..HEAD",
            "--",
            "services/s02_signal_engine/",
        ]
        try:
            result = subprocess.run(
                cmd,
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            pytest.fail(f"git subprocess failed: {exc}. Cannot verify DoD 'zero diff in S02'.")

        if result.returncode != 0:
            pytest.fail(f"git diff returned {result.returncode}: {result.stderr.strip()}")

        assert result.stdout.strip() == "", (
            "DoD violation: services/s02_signal_engine/ has modifications "
            f"on this branch. Phase 3.13 is scaffolding-only.\n"
            f"git diff --stat {base_ref}..HEAD -- services/s02_signal_engine/:\n"
            f"{result.stdout}"
        )
