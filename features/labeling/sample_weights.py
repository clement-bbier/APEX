"""Phase 4.2 - Sample weights for Meta-Labeler training.

Canonical Polars-native implementation of the uniqueness x return
attribution sample weights defined in ADR-0005 D2 and Lopez de Prado
(2018) chapter 4 sections 4.4 - 4.5. Consumed by sub-phases 4.3, 4.4,
and 4.5 of the Phase 4 Meta-Labeler training pipeline.

Public API:

- :func:`compute_concurrency` - bar-indexed concurrency count ``c_t``.
- :func:`uniqueness_weights` - ``u_i = mean(1 / c_t for t in [t0_i, t1_i])``.
- :func:`return_attribution_weights` - ``r_i = |sum(ret_t / c_t for t in [t0_i, t1_i])|``.
- :func:`combined_weights` - ``w_i = u_i * r_i`` normalized so ``sum(w) == n_samples``.

Coexistence with :mod:`features.weights`:

    The pre-existing :class:`features.weights.SampleWeighter` (Phase 3.1
    prototype) exposes a *duration-weighted* uniqueness formula on
    ``list[datetime]`` inputs, with ``return_attribution_weights`` still
    ``NotImplementedError``. It remains wired into
    :mod:`features.pipeline` and covered by 21 tests; this Phase 4.2
    module is the canonical bar-indexed implementation and lives as a
    sibling. Migration of the Phase 3 pipeline to the canonical module is
    tracked as technical debt for the Phase 4 closure report (issue #133)
    or Phase 5.

Algorithmic contract:

- Both label bars ``t0`` and ``t1`` are included in the span (closed
  interval). Every ``t0_i`` and ``t1_i`` must exist in ``bars``; orphan
  timestamps raise ``ValueError`` (fail-loud, no silent drop).
- Concurrency ``c_t`` is computed in O(n_samples + n_bars) via a
  delta-plus-cumsum scan over bar indices, never a double Python loop.
- Weights depend only on ``t0``, ``t1``, and bars/log_returns **within**
  the label span ``[t0, t1]``. Shuffling log returns strictly after
  ``max(t1)`` cannot change any weight - this is enforced by a property
  test in :mod:`tests.unit.features.labeling.test_sample_weights_attribution`.
- UTC-only timestamps. Naive or non-UTC datetimes raise ``ValueError``.

Performance contract:

- Target: 10,000 samples x 100,000 bars in <= 30 s on a single CPU core
  (issue #126 DoD section 5). The algorithm is O(n_samples + n_bars)
  which comfortably fits the budget.

References:
    Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*.
    Wiley, Chapter 4 sections 4.4 (Average Uniqueness) and 4.5 (Sample
    Weights by Return Attribution), including Table 4.1.
    ADR-0005 D2 - Sample weights contract.
    PHASE_4_SPEC section 3.2 - module structure and public API.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import numpy.typing as npt
import polars as pl

__all__ = [
    "combined_weights",
    "compute_concurrency",
    "return_attribution_weights",
    "uniqueness_weights",
]

# Tolerance for the normalization invariant ``sum(w) == n_samples``.
_NORMALIZATION_TOL: float = 1e-9


def _ensure_utc_scalar(ts: datetime, field: str) -> None:
    """Fail-loud UTC check for a single datetime scalar."""
    if ts.tzinfo is None:
        raise ValueError(f"{field}={ts!r} is tz-naive; ADR-0005 D2 requires UTC-aware datetimes")
    if ts.utcoffset() != UTC.utcoffset(None):
        raise ValueError(
            f"{field}={ts!r} is not UTC (offset={ts.utcoffset()}); "
            "ADR-0005 D2 requires UTC-aware datetimes"
        )


def _validate_datetime_series(series: pl.Series, name: str) -> None:
    """Reject empty-less checks and enforce Datetime[us, UTC] dtype.

    Empty series are accepted (return path is handled by the callers).
    """
    if series.dtype != pl.Datetime("us", "UTC"):
        # Polars is strict: a pl.Datetime without tz, or with a different
        # tz, has a different dtype. This check fires on both naive and
        # non-UTC inputs.
        raise ValueError(
            f"{name} must be pl.Datetime('us', 'UTC'); got dtype={series.dtype}. "
            "ADR-0005 D2 requires UTC-aware timestamps."
        )
    # Defense in depth: verify first element is UTC-aware. For a fully
    # typed UTC series this is redundant, but it catches the case where a
    # caller hand-builds the series with ``strict=False`` coercion.
    if len(series) > 0:
        head = series.to_list()[0]
        if head is not None:
            _ensure_utc_scalar(head, f"{name}[0]")


def _validate_numeric_series(
    series: pl.Series, name: str, *, expected_length: int | None = None
) -> None:
    """Reject non-finite values and length mismatches on a numeric series."""
    if expected_length is not None and len(series) != expected_length:
        raise ValueError(
            f"{name} length ({len(series)}) does not match expected length ({expected_length})"
        )
    if series.null_count() > 0:
        raise ValueError(f"{name} contains null values; ADR-0005 D2 forbids silent ffill")
    if len(series) == 0:
        return
    arr = series.to_numpy()
    if not np.isfinite(arr).all():
        raise ValueError(
            f"{name} contains non-finite values (NaN/Inf); ADR-0005 D2 forbids silent ffill"
        )


def _locate_span_indices(
    t0: pl.Series,
    t1: pl.Series,
    bars: pl.Series,
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
    """Resolve each sample's ``[t0, t1]`` closed-interval to bar indices.

    Returns ``(i0, i1_plus_one)`` where ``bars[i0] == t0`` and
    ``bars[i1_plus_one - 1] == t1`` for every sample (fail-loud on miss).

    The half-open ``[i0, i1_plus_one)`` convention is what the cumulative
    sum and concurrency delta scan consume downstream.
    """
    if t0.dtype != bars.dtype:
        raise ValueError(f"t0 dtype ({t0.dtype}) does not match bars dtype ({bars.dtype})")
    if t1.dtype != bars.dtype:
        raise ValueError(f"t1 dtype ({t1.dtype}) does not match bars dtype ({bars.dtype})")

    bars_np = bars.to_numpy()
    # Strict monotonicity of bars is required; ``searchsorted`` relies on
    # it and upstream 4.1 output already satisfies it.
    if len(bars_np) > 1 and not np.all(bars_np[1:] > bars_np[:-1]):
        raise ValueError("bars must be strictly monotonic increasing")

    t0_np = t0.to_numpy()
    t1_np = t1.to_numpy()

    if len(t0_np) != len(t1_np):
        raise ValueError(f"t0 ({len(t0_np)}) and t1 ({len(t1_np)}) have different lengths")

    if np.any(t1_np < t0_np):
        bad = int(np.argmax(t1_np < t0_np))
        raise ValueError(f"t1 < t0 at sample index {bad}: t0={t0_np[bad]}, t1={t1_np[bad]}")

    # side='left' finds the insertion index for an exact match; verify
    # equality to detect orphan timestamps.
    i0 = np.searchsorted(bars_np, t0_np, side="left").astype(np.int64)
    i1 = np.searchsorted(bars_np, t1_np, side="left").astype(np.int64)

    if np.any(i0 >= len(bars_np)) or np.any(i1 >= len(bars_np)):
        oob_mask = (i0 >= len(bars_np)) | (i1 >= len(bars_np))
        bad = int(np.argmax(oob_mask))
        raise ValueError(
            f"t0/t1 at sample index {bad} is past the last bar: "
            f"t0={t0_np[bad]}, t1={t1_np[bad]}, last_bar={bars_np[-1]}"
        )

    if not np.array_equal(bars_np[i0], t0_np):
        bad = int(np.argmax(bars_np[i0] != t0_np))
        raise ValueError(
            f"t0={t0_np[bad]} (sample {bad}) is not present in bars; "
            "every event timestamp must exist in the bar series"
        )
    if not np.array_equal(bars_np[i1], t1_np):
        bad = int(np.argmax(bars_np[i1] != t1_np))
        raise ValueError(
            f"t1={t1_np[bad]} (sample {bad}) is not present in bars; "
            "every event timestamp must exist in the bar series"
        )

    # Closed interval [t0, t1] -> half-open [i0, i1 + 1).
    return i0, (i1 + 1).astype(np.int64)


def _empty_float_series() -> pl.Series:
    """Return an empty ``pl.Series`` of dtype ``Float64``."""
    return pl.Series(values=[], dtype=pl.Float64)


def compute_concurrency(
    t0: pl.Series,
    t1: pl.Series,
    bars: pl.Series,
) -> pl.Series:
    """Return ``c_t`` - the number of active labels at each bar ``t``.

    For every bar in ``bars``, counts how many samples satisfy
    ``t0_i <= bar <= t1_i``. Implemented as a delta-plus-cumsum scan in
    O(n_samples + n_bars) time and O(n_bars) memory.

    Args:
        t0: UTC-aware bar timestamps marking the start of each label span.
        t1: UTC-aware bar timestamps marking the end of each label span.
        bars: UTC-aware strictly-monotonic bar timestamps covering the
            union of all label spans.

    Returns:
        ``pl.Series[Int64]`` of length ``len(bars)`` with the concurrency
        count at each bar. Zeroes at bars outside every span are allowed
        and expected; those bars are simply never accessed by downstream
        weight computations.

    Raises:
        ValueError: If timestamps are non-UTC, bars are non-monotonic,
            any ``t0_i`` / ``t1_i`` is absent from ``bars``, or
            ``t1_i < t0_i`` at any sample.

    Reference:
        Lopez de Prado (2018), chapter 4 section 4.4, equation for
        ``c_t = sum_i 1_{t0_i <= t <= t1_i}``.
    """
    _validate_datetime_series(t0, "t0")
    _validate_datetime_series(t1, "t1")
    _validate_datetime_series(bars, "bars")

    n_bars = len(bars)
    if len(t0) == 0:
        return pl.Series(values=np.zeros(n_bars, dtype=np.int64), dtype=pl.Int64)
    if n_bars == 0:
        raise ValueError("bars is empty but t0/t1 are not; cannot compute concurrency")

    i0, i1_plus_one = _locate_span_indices(t0, t1, bars)

    # Delta array: +1 at span start, -1 just after span end. Cumulative
    # sum gives concurrency at each bar.
    delta = np.zeros(n_bars + 1, dtype=np.int64)
    np.add.at(delta, i0, 1)
    np.add.at(delta, i1_plus_one, -1)
    concurrency = np.cumsum(delta[:-1])
    return pl.Series(values=concurrency, dtype=pl.Int64)


def uniqueness_weights(
    t0: pl.Series,
    t1: pl.Series,
    bars: pl.Series,
) -> pl.Series:
    """Compute uniqueness weight ``u_i`` per sample.

    ``u_i = mean(1 / c_t for t in [t0_i, t1_i])``

    where ``c_t`` is the concurrency count at bar ``t``. Lower when the
    span overlaps many other spans (information is shared); higher when
    the span is disjoint (information is unique to this sample).

    Args:
        t0: UTC bar timestamps - span starts.
        t1: UTC bar timestamps - span ends.
        bars: UTC strictly-monotonic bar timestamps covering the label
            range.

    Returns:
        ``pl.Series[Float64]`` of length ``n_samples`` with the per-sample
        uniqueness weight. For disjoint events the value is exactly 1.0.

    Raises:
        ValueError: If inputs fail validation (see
            :func:`compute_concurrency`) or if ``c_t == 0`` at any bar
            inside ``[t0_i, t1_i]`` (should not happen when inputs are
            consistent, but we fail loudly rather than emit NaN).

    Reference:
        Lopez de Prado (2018), chapter 4 section 4.4, equation (4.2):
        ``u_bar_i = (1 / |T_i|) * sum_{t in T_i} (1 / c_t)``.
    """
    _validate_datetime_series(t0, "t0")
    _validate_datetime_series(t1, "t1")
    _validate_datetime_series(bars, "bars")

    n_samples = len(t0)
    if n_samples == 0:
        return _empty_float_series()
    if len(bars) == 0:
        raise ValueError("bars is empty but t0/t1 are not")

    i0, i1_plus_one = _locate_span_indices(t0, t1, bars)

    concurrency = compute_concurrency(t0, t1, bars).to_numpy()

    # Every bar covered by at least one span must have c_t >= 1. Check
    # the slice actually consumed by any sample rather than the whole
    # bars array (some bars may be outside every span and legitimately
    # have c_t == 0; we never access those).
    inv_concurrency = np.zeros(len(concurrency), dtype=np.float64)
    covered_mask = concurrency > 0
    inv_concurrency[covered_mask] = 1.0 / concurrency[covered_mask]

    # Verify fail-loud: every bar inside every sample span must be
    # covered. A single cheap check per sample: min(c_t) over the span.
    # Using the prefix sum trick again: min requires a different
    # structure. Instead we check that `covered_mask[i0:i1+1]` is fully
    # True via a per-sample prefix-cumsum of the covered mask. If the
    # number of covered bars in [i0, i1+1) equals (i1+1 - i0), all bars
    # in the span are covered.
    cumsum_covered = np.concatenate(([0], np.cumsum(covered_mask.astype(np.int64))))
    covered_in_span = cumsum_covered[i1_plus_one] - cumsum_covered[i0]
    span_len = i1_plus_one - i0
    if not np.array_equal(covered_in_span, span_len):
        bad = int(np.argmax(covered_in_span != span_len))
        raise ValueError(
            f"c_t == 0 at a bar inside sample {bad}'s span "
            f"[{t0[bad]}, {t1[bad]}]; this should not happen if inputs "
            "are consistent. ADR-0005 D2 forbids silent zero-weight."
        )

    # Prefix sums of 1/c_t; u_i = (cumsum[i1+1] - cumsum[i0]) / span_len.
    cumsum_inv = np.concatenate(([0.0], np.cumsum(inv_concurrency)))
    weights = (cumsum_inv[i1_plus_one] - cumsum_inv[i0]) / span_len.astype(np.float64)

    return pl.Series(values=weights, dtype=pl.Float64)


def return_attribution_weights(
    t0: pl.Series,
    t1: pl.Series,
    bars: pl.Series,
    log_returns: pl.Series,
) -> pl.Series:
    """Compute return-attribution weight ``r_i`` per sample.

    ``r_i = |sum(ret_t / c_t for t in [t0_i, t1_i])|``

    Attributes the P&L magnitude of the span to the sample, discounted by
    the concurrency at each bar so that overlapping labels do not
    double-count returns.

    Args:
        t0: UTC bar timestamps - span starts.
        t1: UTC bar timestamps - span ends.
        bars: UTC strictly-monotonic bar timestamps.
        log_returns: ``pl.Series[Float64]`` of per-bar log returns,
            aligned with ``bars``. No NaN / Inf allowed.

    Returns:
        ``pl.Series[Float64]`` of length ``n_samples`` with the
        per-sample absolute-value weight. Zero when the span's
        concurrency-adjusted log-return sum is exactly zero.

    Raises:
        ValueError: If inputs fail validation, if ``log_returns`` and
            ``bars`` have different lengths, or if ``c_t == 0`` inside
            any span.

    Reference:
        Lopez de Prado (2018), chapter 4 section 4.5, equation (4.10):
        ``w_i = |sum_{t in T_i} ret_t / c_t|``.
    """
    _validate_datetime_series(t0, "t0")
    _validate_datetime_series(t1, "t1")
    _validate_datetime_series(bars, "bars")
    _validate_numeric_series(log_returns, "log_returns", expected_length=len(bars))

    n_samples = len(t0)
    if n_samples == 0:
        return _empty_float_series()
    if len(bars) == 0:
        raise ValueError("bars is empty but t0/t1 are not")

    i0, i1_plus_one = _locate_span_indices(t0, t1, bars)

    concurrency = compute_concurrency(t0, t1, bars).to_numpy()
    covered_mask = concurrency > 0
    ret = log_returns.to_numpy().astype(np.float64)

    # Same fail-loud check as uniqueness_weights: every bar in every
    # span must be covered.
    cumsum_covered = np.concatenate(([0], np.cumsum(covered_mask.astype(np.int64))))
    covered_in_span = cumsum_covered[i1_plus_one] - cumsum_covered[i0]
    span_len = i1_plus_one - i0
    if not np.array_equal(covered_in_span, span_len):
        bad = int(np.argmax(covered_in_span != span_len))
        raise ValueError(
            f"c_t == 0 at a bar inside sample {bad}'s span "
            f"[{t0[bad]}, {t1[bad]}]; ADR-0005 D2 forbids silent zero-weight."
        )

    # ret_over_c defined only on covered bars; zero elsewhere (we never
    # access the uncovered entries).
    ret_over_c = np.zeros_like(ret)
    ret_over_c[covered_mask] = ret[covered_mask] / concurrency[covered_mask]

    cumsum_rc = np.concatenate(([0.0], np.cumsum(ret_over_c)))
    per_sample_sum = cumsum_rc[i1_plus_one] - cumsum_rc[i0]
    return pl.Series(values=np.abs(per_sample_sum), dtype=pl.Float64)


def combined_weights(
    t0: pl.Series,
    t1: pl.Series,
    bars: pl.Series,
    log_returns: pl.Series,
) -> pl.Series:
    """Compute the final Meta-Labeler training weight ``w_i``.

    ``w_i = u_i * r_i``, then normalized so that
    ``sum(w_i) == n_samples`` (within ``1e-9`` tolerance).

    When every sample's ``r_i`` is zero (pathological zero-return
    scenario), the raw product is all-zero; we return the all-zero
    series unchanged because normalization would divide by zero. The
    caller should treat an all-zero weight vector as a degenerate
    training batch and handle it explicitly upstream.

    Args:
        t0: UTC bar timestamps - span starts.
        t1: UTC bar timestamps - span ends.
        bars: UTC strictly-monotonic bar timestamps.
        log_returns: Per-bar log returns aligned with ``bars``.

    Returns:
        ``pl.Series[Float64]`` of length ``n_samples`` with the final
        normalized training weights. Empty input -> empty output.

    Raises:
        ValueError: If the underlying weight computations fail validation.

    Reference:
        Lopez de Prado (2018), chapter 4 section 4.5, combined weighting.
        ADR-0005 D2 - final training weight contract.
    """
    n_samples = len(t0)
    u = uniqueness_weights(t0, t1, bars)
    r = return_attribution_weights(t0, t1, bars, log_returns)

    if n_samples == 0:
        return _empty_float_series()

    w_raw = u.to_numpy() * r.to_numpy()
    total = float(np.sum(w_raw))
    if total <= 0.0:
        # All-zero or degenerate: return the raw product (all zeros) and
        # let the caller surface the issue. We do NOT silently remap to
        # uniform weights - that would mask a pathological training set.
        return pl.Series(values=w_raw, dtype=pl.Float64)

    w = w_raw * (float(n_samples) / total)

    # Invariant: sum(w) == n_samples within tolerance.
    achieved = float(np.sum(w))
    if abs(achieved - float(n_samples)) > _NORMALIZATION_TOL:
        raise ValueError(
            f"normalization drift: sum(w)={achieved} vs n_samples={n_samples} "
            f"(tolerance={_NORMALIZATION_TOL}); investigate float precision"
        )

    return pl.Series(values=w, dtype=pl.Float64)
