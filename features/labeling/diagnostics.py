"""Phase 4.1 label diagnostics - distributions and sanity checks.

Produces the stats required by the Phase 4.1 DoD report:

- Class balance (binary 0 vs 1, ternary -1 / 0 / +1).
- Barrier-hit distribution (upper / lower / vertical).
- Holding-period distribution (min, p25, median, p75, max).
- Per-class mean return sanity check (label=1 should have mean return
  strictly positive; label=0 should have mean return <= 0).

Consumed by ``reports/phase_4_1/labels_diagnostics.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class LabelDiagnostics:
    """Snapshot of a labeled batch used for the Phase 4.1 report."""

    n_events: int
    binary_pct_one: float
    binary_pct_zero: float
    ternary_pct_up: float
    ternary_pct_flat: float
    ternary_pct_down: float
    barrier_pct_upper: float
    barrier_pct_lower: float
    barrier_pct_vertical: float
    holding_min: int
    holding_p25: float
    holding_median: float
    holding_p75: float
    holding_max: int
    mean_return_label_one: float
    mean_return_label_zero: float
    sanity_label_one_positive: bool
    sanity_label_zero_nonpositive: bool


def _pct(numer: int, denom: int) -> float:
    if denom == 0:
        return 0.0
    return numer / denom


def compute_label_diagnostics(labels: pl.DataFrame) -> LabelDiagnostics:
    """Compute summary statistics from a :func:`label_events_binary` output.

    Args:
        labels: Polars DataFrame with the schema produced by
            :func:`features.labeling.triple_barrier.label_events_binary`
            (columns ``ternary_label``, ``binary_target``,
            ``barrier_hit``, ``holding_periods``, ``entry_price``,
            ``exit_price``).

    Returns:
        :class:`LabelDiagnostics` immutable snapshot.

    Raises:
        ValueError: If ``labels`` is empty or missing required columns.
    """
    required = {
        "ternary_label",
        "binary_target",
        "barrier_hit",
        "holding_periods",
        "entry_price",
        "exit_price",
    }
    missing = required - set(labels.columns)
    if missing:
        raise ValueError(f"labels DataFrame missing columns: {sorted(missing)}")
    if len(labels) == 0:
        raise ValueError(
            "compute_label_diagnostics received an empty DataFrame; "
            "diagnostics on zero events are meaningless (ADR-0005 D1 fail-loud)"
        )

    n = len(labels)

    ternary = labels["ternary_label"].to_list()
    binary = labels["binary_target"].to_list()
    barriers = labels["barrier_hit"].to_list()

    n_up = sum(1 for v in ternary if v == 1)
    n_flat = sum(1 for v in ternary if v == 0)
    n_down = sum(1 for v in ternary if v == -1)

    n_bin_one = sum(1 for v in binary if v == 1)
    n_bin_zero = sum(1 for v in binary if v == 0)

    n_upper = sum(1 for v in barriers if v == "upper")
    n_lower = sum(1 for v in barriers if v == "lower")
    n_vert = sum(1 for v in barriers if v == "vertical")

    holding_values = [int(v) for v in labels["holding_periods"].to_list()]
    holding_min = min(holding_values)
    holding_max = max(holding_values)
    sorted_hold = sorted(holding_values)

    def _quantile(q: float) -> float:
        if not sorted_hold:
            return 0.0
        idx = max(0, min(len(sorted_hold) - 1, int(q * (len(sorted_hold) - 1))))
        return float(sorted_hold[idx])

    holding_p25 = _quantile(0.25)
    holding_median = _quantile(0.5)
    holding_p75 = _quantile(0.75)

    entry_prices = [float(v) for v in labels["entry_price"].to_list()]
    exit_prices = [float(v) for v in labels["exit_price"].to_list()]
    per_event_returns = [
        (exit_p - entry_p) / entry_p
        for entry_p, exit_p in zip(entry_prices, exit_prices, strict=True)
    ]

    returns_label_one = [r for r, y in zip(per_event_returns, binary, strict=True) if y == 1]
    returns_label_zero = [r for r, y in zip(per_event_returns, binary, strict=True) if y == 0]

    mean_one = sum(returns_label_one) / len(returns_label_one) if returns_label_one else 0.0
    mean_zero = sum(returns_label_zero) / len(returns_label_zero) if returns_label_zero else 0.0

    return LabelDiagnostics(
        n_events=n,
        binary_pct_one=_pct(n_bin_one, n),
        binary_pct_zero=_pct(n_bin_zero, n),
        ternary_pct_up=_pct(n_up, n),
        ternary_pct_flat=_pct(n_flat, n),
        ternary_pct_down=_pct(n_down, n),
        barrier_pct_upper=_pct(n_upper, n),
        barrier_pct_lower=_pct(n_lower, n),
        barrier_pct_vertical=_pct(n_vert, n),
        holding_min=holding_min,
        holding_p25=holding_p25,
        holding_median=holding_median,
        holding_p75=holding_p75,
        holding_max=holding_max,
        mean_return_label_one=mean_one,
        mean_return_label_zero=mean_zero,
        sanity_label_one_positive=mean_one > 0,
        sanity_label_zero_nonpositive=mean_zero <= 0,
    )
