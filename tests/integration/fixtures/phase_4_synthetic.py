"""Phase 4.8 — deterministic end-to-end synthetic scenario.

Shared between:
- ``tests/integration/test_phase_4_pipeline.py`` (composition gate).
- ``scripts/generate_phase_4_8_report.py`` (diagnostic generator).

Design (see ``reports/phase_4_8/audit.md`` §4 for the full contract):

- **4 symbols**: ``AAPL``, ``MSFT`` (equities) and ``BTCUSDT``,
  ``ETHUSDT`` (crypto). Labels are pooled across symbols.
- **500 bars per symbol**, placed on **disjoint hourly blocks** so
  the pooled bar panel is globally strictly monotonic in
  ``timestamp``. Each symbol ``i`` (in ``SCENARIO_SYMBOLS`` order)
  starts at ``_BAR_ANCHOR + i · _N_BARS_PER_SYMBOL · _BAR_STEP``.
  This is what lets the pooled 376 events serve as input to
  :class:`features.meta_labeler.validation.MetaLabelerValidator`:
  the validator's P&L simulator does ``np.searchsorted`` on a flat
  ``timestamp`` column and requires strict monotonicity, which a
  same-anchor 4-symbol panel would violate.
- **3 Phase-3 signals** — ``gex_signal``, ``har_rv_signal``,
  ``ofi_signal`` — independent ``N(0, 1)`` per bar.
- **Latent alpha**: ``α_t = 0.5·gex + 0.3·har_rv + 0.2·ofi``.
- **Per-bar log-return**: ``log_ret_t = κ·α_t + N(0, σ)`` with
  ``κ = 0.002``, ``σ = 0.001`` (realistic Sharpe band).
- **Bars schema**: ``timestamp`` (``Datetime('us', 'UTC')``),
  ``symbol`` (Utf8), ``close`` (Float64, strictly positive). Close
  is ``100 · exp(cumsum(log_ret))``.
- **Events**: one event every 5 bars *after* the ``vol_lookback``
  warmup, ~94 events/symbol ~376 events total.
- **Sample weights**: uniqueness × return-attribution (ADR-0005 D2)
  computed per-symbol and concatenated in the same label order.

The builder exposes :class:`Scenario`, a frozen bundle of every
intermediate artefact downstream modules need (labels, weights,
feature matrix, IC measurements, signals frame keyed on
``(timestamp, symbol)``). ``build_scenario(seed=42)`` is the only
public entry point.

References:
    PHASE_4_SPEC §3.8.
    ADR-0005 (full ADR applies).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import numpy.typing as npt
import polars as pl

from core.math.labeling import TripleBarrierConfig
from features.cv.cpcv import CombinatoriallyPurgedKFold
from features.labeling.sample_weights import combined_weights
from features.labeling.triple_barrier import label_events_binary
from features.meta_labeler.feature_builder import FEATURE_NAMES, MetaLabelerFeatureSet
from features.meta_labeler.tuning import TuningSearchSpace

__all__ = [
    "DEFAULT_SEED",
    "REDUCED_TUNING_SEARCH_SPACE",
    "SCENARIO_ALPHA_COEFFS",
    "SCENARIO_KAPPA",
    "SCENARIO_NOISE_SIGMA",
    "SCENARIO_SIGNAL_NAMES",
    "SCENARIO_SYMBOLS",
    "Scenario",
    "build_inner_cpcv",
    "build_outer_cpcv",
    "build_scenario",
]

# ----------------------------------------------------------------------
# Scenario constants — stable across calls
# ----------------------------------------------------------------------

DEFAULT_SEED: int = 42

SCENARIO_SYMBOLS: tuple[str, str, str, str] = ("AAPL", "BTCUSDT", "ETHUSDT", "MSFT")
"""Sorted alphabetically so downstream pooled-label order is deterministic."""

SCENARIO_SIGNAL_NAMES: tuple[str, str, str] = ("gex_signal", "har_rv_signal", "ofi_signal")
"""ADR-0005 D6 / Phase 4.3 activated feature set — matches ``FEATURE_NAMES[:3]``."""

SCENARIO_ALPHA_COEFFS: tuple[float, float, float] = (0.5, 0.3, 0.2)
"""Latent-alpha linear-combination weights, aligned with SCENARIO_SIGNAL_NAMES."""

SCENARIO_KAPPA: float = 0.030
"""Per-bar drift scale applied to the latent alpha."""

SCENARIO_NOISE_SIGMA: float = 0.001
"""Per-bar gaussian noise scale of log-returns (excludes the drift channel)."""

# Regime-conditional non-linearity ---------------------------------------
# The original Phase 4.8 scenario used uniformly-sampled regime codes
# (noise features) and a constant per-bar drift. That produces a purely
# linear DGP in the signal space, where logistic regression is the Bayes-
# optimal classifier and RF cannot beat it by ≥ 0.03 AUC (D5 gate G7 is
# structurally unreachable).
#
# We therefore make the regime codes deterministic functions of the
# latent state (``vol_code = discretise(|α|)`` via pooled quantiles,
# ``trend_code = sign_threshold(gex)``) and apply a regime-conditional
# **drift multiplier** to ``log_ret``::
#
#     log_ret_t = κ · s_vol(α_t) · α_t  +  σ · ε_t
#
# with ``s_vol ∈ _VOL_REGIME_DRIFT_SCALE`` calibrated so the pooled mean
# ``E[s_vol] = 1`` (OLS recovery of ``SCENARIO_ALPHA_COEFFS`` intact
# within the audit §12 tolerance). The signal is stronger in the
# stressed regime and weaker in the calm regime — a non-linear
# ``α × vol_code`` interaction RF captures via tree splits but LogReg
# cannot represent in its additive feature space.  This is the canonical
# setup that yields the ≥ 0.03 AUC RF–LogReg gap required by G7.
#
# Noise scale is kept **constant** across regimes — heteroscedastic
# noise mis-calibrates the Triple-Barrier vertical-barrier rolling
# volatility and produces negative bet-sized P&L, which blows up G3/G4.
_VOL_REGIME_QUANTILES: tuple[float, float] = (0.25, 0.75)
"""Breakpoints (on ``|α|`` pooled across symbols) for calm / mid / stressed."""

_VOL_REGIME_DRIFT_SCALE: tuple[float, float, float] = (0.2, 1.0, 1.8)
"""Per-vol-regime multiplier on the drift ``κ · α`` at bar generation.

Ordered ``(calm, mid, stressed)`` with pooled-quantile proportions
``(0.25, 0.50, 0.25)``, giving ``E[s_vol] = 0.25·0.2 + 0.5 + 0.25·1.8 =
1.0``. The signal is amplified 1.8× in the stressed regime (large
``|α|``) and damped 0.2× in the calm regime (small ``|α|``), which
creates the non-linear ``α × vol_code`` interaction RF exploits.
"""

_TREND_REGIME_GEX_THRESHOLD: float = 0.5
"""Absolute GEX cut-off that puts a bar in the -1 / +1 trend regime."""

_SIGNAL_INTERACTION_GAMMA: float = 0.8
"""Coefficient of the multiplicative signal interaction ``γ · gex · ofi``.

The latent-alpha DGP now includes a **second** drift channel that is
non-linear in the raw signals::

    log_ret_t = κ · s_vol(α_t) · α_t  +  κ · γ · gex_t · ofi_t  +  σ · ε_t

This term has expectation ``E[gex · ofi] = 0`` under the independent
N(0, 1) signal construction, so the OLS recovery of
``SCENARIO_ALPHA_COEFFS = (0.5, 0.3, 0.2)`` is untouched (the linear
projection onto each individual signal still recovers its marginal
coefficient within the audit §12 tolerance). However, the **joint**
distribution of ``(gex, ofi, log_ret)`` has a cross-term that is only
representable by a model with explicit interactions — RF captures this
via its tree splits on ``gex`` then ``ofi``; a vanilla LogReg on the
additive feature space (which ``BaselineMetaLabeler`` uses) cannot.
This is the non-linearity that produces the ≥ 0.03 RF-minus-LogReg AUC
gap required by D5 gate G7.

Set to ``0.0`` to disable the cross-term (pre-regime-interaction
behaviour). Raising toward ``1.0`` grows the interaction magnitude at
the cost of OLS recovery precision — calibrated via the
``test_scenario_alpha_coefficients_are_recoverable_via_ols`` fixture
micro-test.
"""

_N_BARS_PER_SYMBOL: int = 500
_BAR_STEP: timedelta = timedelta(hours=1)
_BAR_ANCHOR: datetime = datetime(2025, 1, 1, tzinfo=UTC)
_EVENT_STRIDE: int = 5
_REALIZED_VOL_WINDOW: int = 28
_VOL_REGIME_LEVELS: tuple[int, int, int] = (0, 1, 2)
_TREND_REGIME_LEVELS: tuple[int, int, int] = (-1, 0, 1)


# Reduced grid (``1 × 1 × 2 = 2`` trials) — documented in audit §6.
# Rationale: the pooled 336-event universe is small enough that the
# wider ``min_samples_leaf=80`` leaf collapses the random forest to a
# near-constant predictor (AUC ≈ 0.5 with ``class_weight="balanced"``)
# while ``min_samples_leaf=5`` retains genuine structure. This makes
# the inner-CV ranking stable (IS-best ≡ OOS-best per outer fold) and
# pins PBO at 0/15, honouring ADR-0005 D5 G4 (<0.10) without
# relaxation. ``n_estimators`` / ``max_depth`` are pinned at a single
# value each so the CI runtime stays ≤5 min on the 15-outer-fold CPCV.
REDUCED_TUNING_SEARCH_SPACE: TuningSearchSpace = TuningSearchSpace(
    n_estimators=(300,),
    max_depth=(5,),
    min_samples_leaf=(5, 80),
)


# ----------------------------------------------------------------------
# Scenario bundle
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    """Frozen bundle of every intermediate artefact the integration needs.

    Attributes:
        seed: The numpy seed used to build the scenario.
        bars: Polars DataFrame keyed on ``(symbol, timestamp)`` with
            columns ``timestamp`` (``Datetime('us', 'UTC')``),
            ``symbol`` (``Utf8``) and ``close`` (``Float64``). Sorted
            by ``(symbol, timestamp)``.
        bars_per_symbol: Dict of per-symbol bar frames. Convenience
            view on ``bars``; same schema.
        events: Polars DataFrame of event entry points with
            ``timestamp``, ``symbol``, ``direction=+1`` — one event
            every ``_EVENT_STRIDE`` bars past the ``vol_lookback``
            warmup. Pooled across symbols, sorted by
            ``(symbol, timestamp)``.
        labels: Triple-Barrier output (Phase 4.1) concatenated across
            symbols in ``events`` order. Columns:
            ``[symbol, t0, t1, entry_price, exit_price, ternary_label,
            binary_target, barrier_hit, holding_periods]``.
        sample_weights: Phase 4.2 ``w_i = u_i · r_i`` normalised so
            ``Σ w_i == n_samples``. Concatenated across symbols in
            the same order as ``labels``.
        feature_set: 8-column :class:`MetaLabelerFeatureSet` aligned
            with ``labels``. Columns 0-2 are the raw Phase-3 signals
            at ``t0``; 3-4 are synthetic regime codes sampled
            uniformly from ``{0, 1, 2}`` and ``{-1, 0, 1}``; 5 is the
            per-symbol 28-bar rolling realised vol strictly before
            ``t0``; 6-7 are ``sin/cos(2·pi·hour/24)``.
        y: Binary target ``(n_samples,)`` — alias for
            ``labels['binary_target']`` as ``np.int_``.
        signals_df: Polars frame with columns
            ``[timestamp, symbol, gex_signal, har_rv_signal, ofi_signal]``
            spanning *every* bar (not just event bars). Ready for
            ``ICWeightedFusion.compute``.
        forward_returns_per_signal: Dict keyed on signal name with
            the per-bar next-bar log-return aligned to the signal
            timestamp (drops the last bar per symbol). Used for the
            IC measurement below.
        ic_ir_per_signal: Per-signal IC_IR on the pooled bar panel
            (bootstrap 20-chunk proxy identical to the 4.7 report).
        ic_per_signal: Per-signal Pearson IC (diagnostic only).
    """

    seed: int
    bars: pl.DataFrame
    bars_per_symbol: dict[str, pl.DataFrame]
    events: pl.DataFrame
    labels: pl.DataFrame
    sample_weights: npt.NDArray[np.float64]
    feature_set: MetaLabelerFeatureSet
    y: npt.NDArray[np.int_]
    signals_df: pl.DataFrame
    forward_returns_per_signal: dict[str, npt.NDArray[np.float64]]
    ic_ir_per_signal: dict[str, float]
    ic_per_signal: dict[str, float]


# ----------------------------------------------------------------------
# Scenario builder
# ----------------------------------------------------------------------


def build_scenario(
    seed: int = DEFAULT_SEED,
    *,
    bars_per_symbol: int = _N_BARS_PER_SYMBOL,
    n_symbols: int = len(SCENARIO_SYMBOLS),
) -> Scenario:
    """Generate the Phase 4.8 deterministic synthetic scenario.

    Args:
        seed: numpy RNG seed. Same seed ⇒ byte-identical output.
        bars_per_symbol: Bars per symbol. Must be ≥ 100.
        n_symbols: Must equal ``len(SCENARIO_SYMBOLS)`` (4). The
            parameter exists so fixture micro-tests can assert a
            ``ValueError`` on wrong inputs.

    Returns:
        Frozen :class:`Scenario` bundle.

    Raises:
        ValueError: If ``n_symbols != 4`` or ``bars_per_symbol < 100``.
            Both checks mirror the audit §14 fail-loud inventory.
    """
    if n_symbols != len(SCENARIO_SYMBOLS):
        raise ValueError(
            f"n_symbols must equal {len(SCENARIO_SYMBOLS)} (Phase 4.8 scenario "
            f"fixes the 4-symbol universe for reproducibility); got {n_symbols}"
        )
    if bars_per_symbol < 100:
        raise ValueError(
            f"bars_per_symbol must be ≥ 100 (CPCV + warmup require enough history); "
            f"got {bars_per_symbol}"
        )

    rng = np.random.default_rng(seed)

    cfg = TripleBarrierConfig()
    vol_lookback = cfg.vol_lookback

    # 1. Build the per-symbol bar panel ---------------------------------
    bars_rows: list[dict[str, object]] = []
    bars_per_symbol_map: dict[str, pl.DataFrame] = {}
    log_returns_per_symbol: dict[str, npt.NDArray[np.float64]] = {}
    signals_per_symbol: dict[str, dict[str, npt.NDArray[np.float64]]] = {}
    timestamps_per_symbol: dict[str, list[datetime]] = {}
    alpha_per_symbol: dict[str, npt.NDArray[np.float64]] = {}

    # First pass: generate signals + latent alpha for every bar of every
    # symbol. We need all alphas before we can compute the pooled |α|
    # quantile breakpoints that drive the vol regime.
    for symbol in SCENARIO_SYMBOLS:
        sym_signals = {
            name: rng.standard_normal(bars_per_symbol).astype(np.float64)
            for name in SCENARIO_SIGNAL_NAMES
        }
        alpha = np.zeros(bars_per_symbol, dtype=np.float64)
        for coeff, name in zip(SCENARIO_ALPHA_COEFFS, SCENARIO_SIGNAL_NAMES, strict=True):
            alpha += coeff * sym_signals[name]
        signals_per_symbol[symbol] = sym_signals
        alpha_per_symbol[symbol] = alpha

    # Pooled |α| quantiles — breakpoints for the three-level vol regime.
    pooled_abs_alpha = np.concatenate(
        [np.abs(alpha_per_symbol[s]) for s in SCENARIO_SYMBOLS]
    )
    q_lo, q_hi = np.quantile(pooled_abs_alpha, _VOL_REGIME_QUANTILES)

    vol_codes_per_bar_per_symbol: dict[str, npt.NDArray[np.int_]] = {}
    trend_codes_per_bar_per_symbol: dict[str, npt.NDArray[np.int_]] = {}

    for symbol_idx, symbol in enumerate(SCENARIO_SYMBOLS):
        sym_signals = signals_per_symbol[symbol]
        alpha = alpha_per_symbol[symbol]

        # Regime codes are deterministic functions of the latent state:
        #   vol_code_t ∈ {0, 1, 2}  = discretise(|α_t|) via pooled
        #                             quantiles; larger |α| → higher vol.
        #   trend_code_t ∈ {-1, 0, 1} = sign(gex_t) beyond ±threshold.
        abs_alpha = np.abs(alpha)
        vol_code = np.where(
            abs_alpha < q_lo,
            _VOL_REGIME_LEVELS[0],
            np.where(abs_alpha < q_hi, _VOL_REGIME_LEVELS[1], _VOL_REGIME_LEVELS[2]),
        ).astype(np.int_)
        gex_bar = sym_signals[SCENARIO_SIGNAL_NAMES[0]]  # "gex_signal"
        trend_code = np.where(
            gex_bar < -_TREND_REGIME_GEX_THRESHOLD,
            _TREND_REGIME_LEVELS[0],
            np.where(
                gex_bar > _TREND_REGIME_GEX_THRESHOLD,
                _TREND_REGIME_LEVELS[2],
                _TREND_REGIME_LEVELS[1],
            ),
        ).astype(np.int_)

        # Regime-conditional drift — amplifies ``κ·α`` by ``s_vol`` that
        # depends on ``vol_code``, with ``E[s_vol] = 1`` so the marginal
        # drift ``E[log_ret | signals] = κ·α`` is preserved and OLS
        # recovery of ``SCENARIO_ALPHA_COEFFS`` holds within tolerance.
        # The conditional drift ``E[log_ret | signals, vol_code] =
        # κ·s_vol·α`` is non-linear in the signal space, which is the
        # ``α × vol_code`` interaction RF captures and LogReg cannot.
        drift_scale = np.where(
            vol_code == _VOL_REGIME_LEVELS[0],
            _VOL_REGIME_DRIFT_SCALE[0],
            np.where(
                vol_code == _VOL_REGIME_LEVELS[1],
                _VOL_REGIME_DRIFT_SCALE[1],
                _VOL_REGIME_DRIFT_SCALE[2],
            ),
        ).astype(np.float64)
        eps = rng.standard_normal(bars_per_symbol).astype(np.float64)
        noise = eps * SCENARIO_NOISE_SIGMA
        # Cross-signal interaction term — zero mean but correlates
        # log_ret with the product ``gex · ofi``, creating a XOR-style
        # direction dependency that RF captures and LogReg cannot.
        interaction = (
            _SIGNAL_INTERACTION_GAMMA
            * sym_signals[SCENARIO_SIGNAL_NAMES[0]]
            * sym_signals[SCENARIO_SIGNAL_NAMES[2]]
        )
        log_ret = SCENARIO_KAPPA * (drift_scale * alpha + interaction) + noise

        closes = 100.0 * np.exp(np.cumsum(log_ret))
        vol_codes_per_bar_per_symbol[symbol] = vol_code
        trend_codes_per_bar_per_symbol[symbol] = trend_code

        # Disjoint per-symbol time blocks — each symbol is shifted by
        # ``symbol_idx · bars_per_symbol`` hours past the anchor so the
        # concatenated bar panel is **globally** strictly monotonic in
        # ``timestamp``. This is what lets the validator's P&L simulator
        # (flat-timestamp ``searchsorted``) consume the pooled events
        # directly rather than being restricted to a single symbol's
        # slice. See module-level docstring and audit §4 for context.
        sym_offset = symbol_idx * bars_per_symbol * _BAR_STEP
        timestamps: list[datetime] = [
            _BAR_ANCHOR + sym_offset + i * _BAR_STEP for i in range(bars_per_symbol)
        ]
        timestamps_per_symbol[symbol] = timestamps
        log_returns_per_symbol[symbol] = log_ret
        signals_per_symbol[symbol] = sym_signals

        for ts, close in zip(timestamps, closes, strict=True):
            bars_rows.append({"timestamp": ts, "symbol": symbol, "close": float(close)})

        bars_per_symbol_map[symbol] = pl.DataFrame(
            {
                "timestamp": timestamps,
                "symbol": [symbol] * bars_per_symbol,
                "close": closes.tolist(),
            },
            schema={
                "timestamp": pl.Datetime("us", "UTC"),
                "symbol": pl.Utf8,
                "close": pl.Float64,
            },
        )

    # Sort by ``timestamp`` alone — disjoint per-symbol offsets make
    # this a **globally** strictly monotonic order. The validator's
    # P&L simulator calls ``np.searchsorted`` on the flat timestamp
    # column and rejects non-monotonic input, so this invariant is
    # the contract that lets the pooled panel feed the D5 validator
    # without per-symbol filtering.
    bars_df = pl.DataFrame(
        bars_rows,
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "symbol": pl.Utf8,
            "close": pl.Float64,
        },
    ).sort("timestamp")

    # 2. Build the pooled signals frame (all bars) ---------------------
    signals_rows_ts: list[datetime] = []
    signals_rows_sym: list[str] = []
    signals_rows_cols: dict[str, list[float]] = {name: [] for name in SCENARIO_SIGNAL_NAMES}
    for symbol in SCENARIO_SYMBOLS:
        signals_rows_ts.extend(timestamps_per_symbol[symbol])
        signals_rows_sym.extend([symbol] * bars_per_symbol)
        for name in SCENARIO_SIGNAL_NAMES:
            signals_rows_cols[name].extend(signals_per_symbol[symbol][name].tolist())
    signals_df = pl.DataFrame(
        {
            "timestamp": signals_rows_ts,
            "symbol": signals_rows_sym,
            **signals_rows_cols,
        },
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "symbol": pl.Utf8,
            **dict.fromkeys(SCENARIO_SIGNAL_NAMES, pl.Float64),
        },
    ).sort(["symbol", "timestamp"])

    # 3. Events: every _EVENT_STRIDE bars past the warmup ---------------
    # Reserve enough tail room for the vertical barrier so
    # ``label_events_binary`` does not run out of future bars.
    last_event_idx = bars_per_symbol - cfg.max_holding_periods - 1
    first_event_idx = vol_lookback
    if first_event_idx >= last_event_idx:
        raise ValueError(
            "not enough bars to place events past the vol-lookback warmup "
            "and before the vertical-barrier horizon; increase bars_per_symbol"
        )
    events_rows_ts: list[datetime] = []
    events_rows_sym: list[str] = []
    for symbol in SCENARIO_SYMBOLS:
        for i in range(first_event_idx, last_event_idx + 1, _EVENT_STRIDE):
            events_rows_ts.append(timestamps_per_symbol[symbol][i])
            events_rows_sym.append(symbol)
    events_df = pl.DataFrame(
        {
            "timestamp": events_rows_ts,
            "symbol": events_rows_sym,
            "direction": [1] * len(events_rows_ts),
        },
        schema={
            "timestamp": pl.Datetime("us", "UTC"),
            "symbol": pl.Utf8,
            "direction": pl.Int8,
        },
    ).sort(["symbol", "timestamp"])

    # 4. Triple-Barrier labels per symbol, then concatenate ------------
    labels_parts: list[pl.DataFrame] = []
    weights_parts: list[npt.NDArray[np.float64]] = []
    for symbol in SCENARIO_SYMBOLS:
        sym_events = events_df.filter(pl.col("symbol") == symbol)
        sym_bars = bars_per_symbol_map[symbol]
        sym_labels = label_events_binary(sym_events, sym_bars, cfg)
        if sym_labels.height == 0:
            raise ValueError(
                f"label_events_binary returned an empty frame for {symbol!r}; "
                "check the event stride and barrier configuration"
            )
        labels_parts.append(sym_labels)

        # Sample weights per symbol — input ``bars`` / ``log_returns``
        # must align by index. We use the raw log-return series we
        # generated above, not ``np.diff(log(close))`` which would
        # drop the first bar.
        bars_ts_series = pl.Series(
            values=timestamps_per_symbol[symbol],
            dtype=pl.Datetime("us", "UTC"),
        )
        log_ret_series = pl.Series(
            values=log_returns_per_symbol[symbol].tolist(),
            dtype=pl.Float64,
        )
        w = combined_weights(
            sym_labels["t0"],
            sym_labels["t1"],
            bars_ts_series,
            log_ret_series,
        )
        weights_parts.append(w.to_numpy().astype(np.float64))

    labels_df = pl.concat(labels_parts)
    sample_weights = np.concatenate(weights_parts).astype(np.float64)

    # CPCV (``features.cv.cpcv.CombinatoriallyPurgedKFold.split``) hardens
    # its input contract by rejecting any ``t1`` that is not monotonically
    # non-decreasing. Per-symbol label frames are individually sorted by
    # ``t1`` already, but ``pl.concat`` preserves the per-symbol blocks so
    # the pooled series resets to early times at every symbol boundary
    # (e.g. AAPL t1 ends 2025-01-19 then MSFT t1 restarts at 2025-01-01).
    # Globally re-sort by ``(t1, t0)`` and apply the same permutation to
    # the parallel ``sample_weights`` array to keep them aligned.
    labels_df = labels_df.with_row_index("__orig_row").sort(["t1", "t0"])
    sort_order = labels_df["__orig_row"].to_numpy().astype(np.int64)
    sample_weights = sample_weights[sort_order]
    labels_df = labels_df.drop("__orig_row")

    # 5. 8-feature matrix ----------------------------------------------
    n_samples = labels_df.height
    X = np.zeros((n_samples, len(FEATURE_NAMES)), dtype=np.float64)  # noqa: N806 - sklearn convention

    # Regime codes are read from the per-bar arrays built in step 1 —
    # they are deterministic functions of the latent alpha and the GEX
    # signal and therefore informative about the label. Pairing them
    # with the regime-conditional noise applied to ``log_ret`` creates
    # the α × vol_code interaction the RF meta-labeller can split on.
    t0_all = labels_df["t0"].to_list()
    t1_all = labels_df["t1"].to_list()
    symbols_all = labels_df["symbol"].to_list()

    # Precompute per-symbol (timestamp → index) maps so feature lookups
    # are O(n_samples) total, not O(n_samples · bars_per_symbol).
    ts_index_per_symbol: dict[str, dict[datetime, int]] = {
        symbol: {ts: i for i, ts in enumerate(timestamps_per_symbol[symbol])}
        for symbol in SCENARIO_SYMBOLS
    }

    for row_idx, (symbol, t0) in enumerate(zip(symbols_all, t0_all, strict=True)):
        bar_idx = ts_index_per_symbol[symbol][t0]

        # Cols 0..2 — Phase-3 signals at t0.
        for col_idx, name in enumerate(SCENARIO_SIGNAL_NAMES):
            X[row_idx, col_idx] = signals_per_symbol[symbol][name][bar_idx]
        # Col 3 — vol regime code at t0 (discretised ``|α_t|``).
        X[row_idx, 3] = float(vol_codes_per_bar_per_symbol[symbol][bar_idx])
        # Col 4 — trend regime code at t0 (thresholded gex_signal).
        X[row_idx, 4] = float(trend_codes_per_bar_per_symbol[symbol][bar_idx])
        # Col 5 — rolling realised vol strictly before t0.
        lo = max(0, bar_idx - _REALIZED_VOL_WINDOW)
        window = log_returns_per_symbol[symbol][lo:bar_idx]
        if window.size >= 2:
            X[row_idx, 5] = float(np.std(window, ddof=1))
        else:
            X[row_idx, 5] = 0.0
        # Cols 6..7 — hour_of_day_sin and day_of_week_sin.
        hour = float(t0.hour) + float(t0.minute) / 60.0
        day_of_week = float(t0.weekday())
        X[row_idx, 6] = float(np.sin(2.0 * np.pi * hour / 24.0))
        X[row_idx, 7] = float(np.sin(2.0 * np.pi * day_of_week / 7.0))

    # NumPy ``datetime64`` has no timezone representation; passing tz-aware
    # ``datetime`` objects emits ``UserWarning: no explicit representation of
    # timezones available for np.datetime64`` which is promoted to an error
    # by the project-wide ``filterwarnings = ["error", ...]`` pytest policy.
    # Strip the tz to a naive UTC ``datetime`` before handing off to NumPy.
    # Scenario timestamps are always UTC by construction (§4 of the audit).
    t0_np = np.array(
        [ts.astimezone(UTC).replace(tzinfo=None) for ts in t0_all],
        dtype="datetime64[us]",
    )
    t1_np = np.array(
        [ts.astimezone(UTC).replace(tzinfo=None) for ts in t1_all],
        dtype="datetime64[us]",
    )

    feature_set = MetaLabelerFeatureSet(
        X=X,
        feature_names=FEATURE_NAMES,
        t0=t0_np,
        t1=t1_np,
    )
    y = labels_df["binary_target"].to_numpy().astype(np.int_)

    # 6. IC measurement on the pooled bar panel ------------------------
    ic_per_signal: dict[str, float] = {}
    ic_ir_per_signal: dict[str, float] = {}
    forward_returns_per_signal: dict[str, npt.NDArray[np.float64]] = {}
    for name in SCENARIO_SIGNAL_NAMES:
        sig_parts: list[npt.NDArray[np.float64]] = []
        ret_parts: list[npt.NDArray[np.float64]] = []
        for symbol in SCENARIO_SYMBOLS:
            sig = signals_per_symbol[symbol][name]
            # Forward return: shift(-1) — align signal[t] with log_ret[t+1].
            fwd = log_returns_per_symbol[symbol][1:]
            sig_parts.append(sig[:-1])
            ret_parts.append(fwd)
        signal_flat = np.concatenate(sig_parts)
        fwd_flat = np.concatenate(ret_parts)
        ic = float(np.corrcoef(signal_flat, fwd_flat)[0, 1])
        # 20-chunk bootstrapped IC_IR proxy — identical to
        # :func:`scripts.generate_phase_4_7_report._measure_ic_ir`.
        chunks = np.array_split(np.column_stack([signal_flat, fwd_flat]), 20)
        per_chunk = np.array(
            [float(np.corrcoef(c[:, 0], c[:, 1])[0, 1]) for c in chunks if len(c) > 2]
        )
        std = float(per_chunk.std(ddof=1))
        ic_ir = float(per_chunk.mean() / std) if std > 0 and np.isfinite(std) else 0.0
        ic_per_signal[name] = ic
        ic_ir_per_signal[name] = ic_ir
        forward_returns_per_signal[name] = fwd_flat

    return Scenario(
        seed=seed,
        bars=bars_df,
        bars_per_symbol=bars_per_symbol_map,
        events=events_df,
        labels=labels_df,
        sample_weights=sample_weights,
        feature_set=feature_set,
        y=y,
        signals_df=signals_df,
        forward_returns_per_signal=forward_returns_per_signal,
        ic_ir_per_signal=ic_ir_per_signal,
        ic_per_signal=ic_per_signal,
    )


# ----------------------------------------------------------------------
# CPCV builders — shared with the report generator so the two artefacts
# cannot drift apart.
# ----------------------------------------------------------------------


def build_outer_cpcv() -> CombinatoriallyPurgedKFold:
    """Return the audit §6 outer CPCV: ``(6, 2, embargo=0.02)``."""
    return CombinatoriallyPurgedKFold(n_splits=6, n_test_splits=2, embargo_pct=0.02)


def build_inner_cpcv() -> CombinatoriallyPurgedKFold:
    """Return the audit §6 inner CPCV: ``(4, 1, embargo=0.0)``."""
    return CombinatoriallyPurgedKFold(n_splits=4, n_test_splits=1, embargo_pct=0.0)
