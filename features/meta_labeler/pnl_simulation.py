"""Phase 4.5 - Bet-sized P&L simulation for the Meta-Labeler.

Implements the ADR-0005 D5 G3 input contract: convert per-fold
predicted probabilities into per-label realised returns under a
calibrated long/short bet-sizing rule and an additive transaction
cost model, both per ADR-0002 D7 / ADR-0005 D8.

Bet sizing follows López de Prado (2018) §3.7 ("Betting on
Probabilities"): a probability ``p`` becomes a signed bet
``2*p - 1 ∈ [-1, +1]``. The position is opened at ``t0_i`` close and
closed at ``t1_i`` close - the same `(t0, t1)` schema produced by the
4.1 Triple Barrier labeler - and the gross return is

    r_gross_i = log(C(t1_i) / C(t0_i)) * (2*p_i - 1)

The realistic-cost scenario (ADR-0002 D7, ADR-0005 D8) deducts
``cost_round_trip_bps * |2*p_i - 1| / 1e4`` from the gross return. The
``|2*p_i - 1|`` factor scales cost with conviction so a half-conviction
bet pays half cost - this is the conventional way to embed bet sizing
into a frictional P&L without double-counting.

Per ADR-0005 D8 the realistic round-trip cost is **10 bps**
(5 bps per side). The zero / stress scenarios are **0 bps** and
**30 bps round-trip** respectively (5 bps and 15 bps per side per
ADR-0002 D7); they are computed for the report but only the realistic
scenario feeds the G3 DSR gate.

Anti-leakage guarantees (verified by property tests in
``tests/unit/features/meta_labeler/test_pnl_simulation.py``):

1. The proba feeding label ``i`` is the model's prediction at ``t0_i``,
   built from features available strictly before ``t0_i`` (Phase 4.3
   audit, PR #142). No proba is reused across labels.
2. ``r_i`` depends only on ``(C(t0_i), C(t1_i), p_i)``; permuting close
   prices outside ``{t0_i, t1_i}`` for any label never moves ``r_i``.

References:
    López de Prado, M. (2018). *Advances in Financial Machine
    Learning*, Wiley. §3.7 Betting on Probabilities.
    ADR-0002 (Quant Methodology Charter), Section A item 7.
    ADR-0005 (Meta-Labeling and Fusion Methodology), D5 G3 + D8.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt
import polars as pl

__all__ = [
    "CostScenario",
    "FoldPnL",
    "PnLSimulationResult",
    "simulate_meta_labeler_pnl",
]


# ADR-0002 D7 / ADR-0005 D8: per-side basis-point costs for the three
# canonical scenarios. Round-trip = 2 × per-side.
_PER_SIDE_BPS_ZERO: float = 0.0
_PER_SIDE_BPS_REALISTIC: float = 5.0
_PER_SIDE_BPS_STRESS: float = 15.0


class CostScenario(StrEnum):
    """Three canonical transaction-cost scenarios per ADR-0002 D7.

    Inherits from :class:`enum.StrEnum` (Python 3.11+) so JSON
    serialisation uses the lower-case scenario name verbatim.
    """

    ZERO = "zero"
    REALISTIC = "realistic"
    STRESS = "stress"

    @property
    def per_side_bps(self) -> float:
        """Per-side cost in basis points for this scenario."""
        match self:
            case CostScenario.ZERO:
                return _PER_SIDE_BPS_ZERO
            case CostScenario.REALISTIC:
                return _PER_SIDE_BPS_REALISTIC
            case CostScenario.STRESS:
                return _PER_SIDE_BPS_STRESS
        raise ValueError(f"unknown CostScenario {self!r}")  # pragma: no cover

    @property
    def round_trip_bps(self) -> float:
        """Round-trip (open + close) cost in basis points."""
        return 2.0 * self.per_side_bps


@dataclass(frozen=True)
class FoldPnL:
    """Realised per-label P&L for one CPCV outer fold.

    Attributes:
        fold_index:
            Zero-based index of the outer fold this entry corresponds
            to. Matches the order of ``CombinatoriallyPurgedKFold.split``.
        net_returns:
            Per-label net return after the realistic-cost deduction.
            Shape ``(n_labels_in_fold,)``, dtype ``float64``.
        gross_returns:
            Per-label gross return (no costs). Same shape.
        bets:
            Per-label signed bet ``2*p - 1 ∈ [-1, +1]``. Same shape.
    """

    fold_index: int
    net_returns: npt.NDArray[np.float64]
    gross_returns: npt.NDArray[np.float64]
    bets: npt.NDArray[np.float64]


@dataclass(frozen=True)
class PnLSimulationResult:
    """Frozen container for the complete P&L simulation output.

    Attributes:
        scenario:
            The ``CostScenario`` used to compute ``per_fold[*].net_returns``.
            Stored explicitly so the report can label the DSR/PSR
            scenario and so the report regenerator catches an
            accidental mismatch.
        per_fold:
            One :class:`FoldPnL` per outer CPCV fold. Length equals
            the caller-supplied number of folds.
        all_net_returns:
            Concatenated per-label net returns across folds, in
            outer-fold order. Shape ``(sum_i n_labels_in_fold_i,)``.
            This is the input to the realised Sharpe and the DSR.
    """

    scenario: CostScenario
    per_fold: tuple[FoldPnL, ...]
    all_net_returns: npt.NDArray[np.float64]


def simulate_meta_labeler_pnl(
    bars: pl.DataFrame,
    t0_per_fold: tuple[npt.NDArray[np.datetime64], ...],
    t1_per_fold: tuple[npt.NDArray[np.datetime64], ...],
    proba_per_fold: tuple[npt.NDArray[np.float64], ...],
    *,
    scenario: CostScenario = CostScenario.REALISTIC,
) -> PnLSimulationResult:
    """Compute bet-sized realised P&L per outer CPCV fold.

    For every ``(t0_i, t1_i, p_i)`` triple in each fold:

    1. Look up ``C(t0_i)`` and ``C(t1_i)`` in ``bars``. Both lookups
       are exact-match - Triple Barrier guarantees that ``t0_i`` and
       ``t1_i`` are bar timestamps (Phase 4.1 contract). A missing
       timestamp triggers ``ValueError``.
    2. Compute ``bet_i = 2 * p_i - 1 ∈ [-1, +1]``.
    3. Compute ``r_gross_i = log(C(t1_i) / C(t0_i)) * bet_i``.
    4. Deduct round-trip cost: ``r_net_i = r_gross_i -
       (scenario.round_trip_bps / 1e4) * |bet_i|``.

    Args:
        bars:
            Polars DataFrame with columns ``timestamp`` (sorted,
            unique, Datetime[us, UTC]) and ``close`` (Float64,
            strictly positive). Same convention as
            ``MetaLabelerFeatureBuilder``.
        t0_per_fold:
            Tuple of length ``n_folds``. Element ``i`` is the array of
            ``t0`` timestamps for fold ``i``'s OOS test labels.
        t1_per_fold:
            Same shape - ``t1`` timestamps.
        proba_per_fold:
            Same shape - predicted positive-class probabilities for
            fold ``i``'s OOS test labels.
        scenario:
            Which :class:`CostScenario` to apply. Defaults to
            ``REALISTIC``, the scenario the G3 DSR gate consumes.

    Returns:
        :class:`PnLSimulationResult` with per-fold ``FoldPnL`` and the
        concatenated ``all_net_returns`` array.

    Raises:
        ValueError: on shape mismatches, missing timestamps, non-finite
            inputs, probabilities outside ``[0, 1]``, or if any bar
            close is non-positive.
    """
    _validate_inputs(bars, t0_per_fold, t1_per_fold, proba_per_fold)

    bars_ts = bars["timestamp"].to_numpy().astype("datetime64[us]")
    bars_close = bars["close"].to_numpy().astype(np.float64)

    rt_cost = scenario.round_trip_bps / 1e4

    per_fold: list[FoldPnL] = []
    net_parts: list[npt.NDArray[np.float64]] = []

    for fold_idx, (t0_arr, t1_arr, proba_arr) in enumerate(
        zip(t0_per_fold, t1_per_fold, proba_per_fold, strict=True)
    ):
        n = int(t0_arr.shape[0])
        if n == 0:
            empty = np.empty(0, dtype=np.float64)
            per_fold.append(
                FoldPnL(
                    fold_index=fold_idx,
                    net_returns=empty,
                    gross_returns=empty,
                    bets=empty,
                )
            )
            net_parts.append(empty)
            continue

        t0_us = t0_arr.astype("datetime64[us]")
        t1_us = t1_arr.astype("datetime64[us]")

        # Exact-match lookup via searchsorted(side='left'): the
        # returned index points to a bar with timestamp >= target. We
        # then verify equality and fail loudly otherwise.
        idx0 = np.searchsorted(bars_ts, t0_us, side="left")
        idx1 = np.searchsorted(bars_ts, t1_us, side="left")
        _check_exact_match(bars_ts, t0_us, idx0, label="t0", fold_idx=fold_idx)
        _check_exact_match(bars_ts, t1_us, idx1, label="t1", fold_idx=fold_idx)

        c0 = bars_close[idx0]
        c1 = bars_close[idx1]
        # log(close_t1 / close_t0) is numerically stable for the
        # positive closes we enforced in _validate_inputs.
        log_ret = np.log(c1) - np.log(c0)

        bets = (2.0 * proba_arr.astype(np.float64)) - 1.0
        gross = log_ret * bets
        net = gross - rt_cost * np.abs(bets)

        per_fold.append(
            FoldPnL(
                fold_index=fold_idx,
                net_returns=net.astype(np.float64),
                gross_returns=gross.astype(np.float64),
                bets=bets.astype(np.float64),
            )
        )
        net_parts.append(net.astype(np.float64))

    all_net = np.concatenate(net_parts) if net_parts else np.empty(0, dtype=np.float64)
    return PnLSimulationResult(
        scenario=scenario,
        per_fold=tuple(per_fold),
        all_net_returns=all_net,
    )


# ----------------------------------------------------------------------
# Internal validation helpers
# ----------------------------------------------------------------------


def _validate_inputs(
    bars: pl.DataFrame,
    t0_per_fold: tuple[npt.NDArray[np.datetime64], ...],
    t1_per_fold: tuple[npt.NDArray[np.datetime64], ...],
    proba_per_fold: tuple[npt.NDArray[np.float64], ...],
) -> None:
    if "timestamp" not in bars.columns or "close" not in bars.columns:
        raise ValueError(f"bars must contain columns 'timestamp' and 'close'; got {bars.columns}")
    if bars.height == 0:
        raise ValueError("bars is empty")

    # Phase 4 timestamp contract: bars.timestamp MUST be Datetime[us, UTC].
    # Mirrors features.meta_labeler.feature_builder._validate_utc_column so
    # tz-naive or non-UTC frames fail loud here instead of silently coercing.
    expected_ts_dtype = pl.Datetime("us", "UTC")
    actual_ts_dtype = bars.schema["timestamp"]
    if actual_ts_dtype != expected_ts_dtype:
        raise ValueError(
            f"bars.timestamp must be {expected_ts_dtype} per ADR-0005 / "
            f"Phase 4 contract; got {actual_ts_dtype}"
        )

    ts = bars["timestamp"].to_numpy().astype("datetime64[us]")
    if len(ts) > 1 and not np.all(ts[1:] > ts[:-1]):
        raise ValueError("bars.timestamp must be strictly monotonic increasing")
    closes = bars["close"].to_numpy().astype(np.float64)
    if not np.isfinite(closes).all() or np.any(closes <= 0.0):
        raise ValueError("bars.close must be strictly positive and finite")

    if len(t0_per_fold) != len(t1_per_fold) or len(t0_per_fold) != len(proba_per_fold):
        raise ValueError(
            f"per-fold tuples must have the same length: "
            f"|t0|={len(t0_per_fold)}, |t1|={len(t1_per_fold)}, "
            f"|proba|={len(proba_per_fold)}"
        )

    for fold_idx, (t0, t1, p) in enumerate(
        zip(t0_per_fold, t1_per_fold, proba_per_fold, strict=True)
    ):
        if t0.shape != t1.shape or t0.shape != p.shape:
            raise ValueError(
                f"fold {fold_idx}: t0/t1/proba shapes disagree: "
                f"{t0.shape} vs {t1.shape} vs {p.shape}"
            )
        if t0.size == 0:
            continue
        if not np.all(t1 >= t0):
            raise ValueError(
                f"fold {fold_idx}: every t1_i must be >= t0_i (Triple Barrier guarantee)"
            )
        if not np.isfinite(p).all():
            raise ValueError(f"fold {fold_idx}: proba contains non-finite values")
        if np.any(p < 0.0) or np.any(p > 1.0):
            raise ValueError(
                f"fold {fold_idx}: proba must lie in [0, 1]; got "
                f"min={float(p.min())}, max={float(p.max())}"
            )


def _check_exact_match(
    bars_ts: npt.NDArray[np.datetime64],
    target: npt.NDArray[np.datetime64],
    idx: npt.NDArray[np.intp],
    *,
    label: str,
    fold_idx: int,
) -> None:
    """Verify every searchsorted index lands on an exact-equal bar.

    A miss means the caller passed a label timestamp that doesn't
    correspond to a bar - usually a sign that ``bars`` and ``labels``
    were built from different sources. We fail loudly per spec §3.5.
    """
    if np.any(idx >= bars_ts.size):
        raise ValueError(
            f"fold {fold_idx}: {label}_i exceeds last bar timestamp; "
            "extend bars to cover [min(t0), max(t1)]"
        )
    matched = bars_ts[idx]
    if not np.array_equal(matched, target):
        bad_pos = int(np.argmax(matched != target))
        raise ValueError(
            f"fold {fold_idx}: {label}_i={target[bad_pos]} has no "
            f"exact-matching bar (closest bar timestamp is "
            f"{matched[bad_pos]}); ensure bars and labels share the "
            "same time grid."
        )
