# Decoded Replication Harness — Methodology and Worked Example

> **Companion research note to [ADR-0011 — Decoded Replication Validation Harness](../adr/ADR-0011-decoded-replication-validation-harness.md).** This document is the longer-form methodology brief that accompanies the ADR. The ADR is the **binding decision record**; this note is the **explanatory and worked-example layer** the CIO, quant researchers, and Claude Code sessions read before implementing any of the three validation tools.
>
> **Scope**: deep methodological walkthrough, worked toy example on HAR-RV variants, paper-to-APEX translation table, illustrative Kalman filter pseudocode, interpretation guide for reading harness output, ADR-0002 reference-list justification, and open questions for future ADRs.
>
> **Out of scope**: production code, real data connectors, vendor onboarding — all deferred to Phase B Gate 3 and Phase C implementation PRs per ADR-0011 §11.
>
> **Date**: 2026-04-21. **Status**: Draft, proposed alongside ADR-0011.

---

## 1. Deep dive on the methodology

### 1.1 What "decoding a strategy" means

In the Ai For Alpha framework (March 2026 paper; Ohana, Benhamou, Saltiel & Guez 2022; Benhamou, Ohana & Guez 2024), a strategy is an opaque return stream `r_target_t` observed over time. The decoder's job is to find a **time-varying tradeable replication** — a portfolio of weights `β̂_t` on a chosen liquid universe of `p` instruments such that the replicating return `x_t^T β̂_t` tracks `r_target_t` closely.

The decoder formalism is a Bayesian dynamic linear model (DLM, West & Harrison 1997, Ch. 2–4):

```
observation:   r_target_t = x_t^T β_t + ε_t,   ε_t ~ N(0, σ²)
state:         β_t = β_{t-1} + η_t,             η_t ~ N(0, W_t)
```

The state equation imposes smoothness on β (a random walk — no trend or mean-reversion — is the most agnostic prior compatible with the data). The observation equation imposes that β be interpretable as dollar-weights on the universe. Together, they produce a sequence of posterior means `β̂_t` that is the forecast-optimal (Kalman) solution under the specified priors.

The chief innovation relative to classical linear factor models (Sharpe 1963, Fama-French 1993, Barra) is **time-variation**. A static linear regression assumes that the exposure of a strategy to each factor is constant through time. Real strategies rotate exposures — a crypto-momentum strategy may be 80% long BTC in 2020 and 40% long ETH / 40% long alt-coins in 2023. The DLM captures this directly by letting β_t drift with the data.

### 1.2 The discount factor

West & Harrison (1997) §4.3 parameterize the state evolution variance `W_t` via a **discount factor** `δ ∈ (0, 1]`: `W_t = (1 − δ)/δ × C_{t-1}`, where `C_{t-1}` is the posterior covariance at the previous step. The interpretation: `δ = 1` collapses the DLM to recursive OLS (no forgetting); `δ = 0.98` yields an effective memory of roughly `1 / (1 − δ) = 50` observations; `δ = 0.90` is a very short memory (~10 obs). The practical range for daily financial data is `δ ∈ [0.95, 0.99]`.

The APEX harness default is `δ = 0.98`. This follows the Ai For Alpha 2026 paper's choice for consistency — in the APEX context, a ~50-day memory roughly matches a monthly rebalancing cycle, which aligns with the decision frequency at which the CIO reviews strategy additions. Per-strategy override is allowed; any override must be declared in the per-strategy Charter and justified against the strategy's genuine rebalancing cadence, not chosen post-hoc to flatter excess metrics.

### 1.3 The long-Enhanced / short-Baseline construction

Ai For Alpha 2026 §2 introduces a structurally important twist: fit **two** decoders on the **same universe** with **two different targets**. The Baseline target is `r_target_t`; the Enhanced target is `r̃_t = r_target_t + c` where `c` is a constant daily increment representing an annualized upward trend of `X%`.

What does this achieve? Consider an intuitive story. If the Baseline replicator tracks the strategy precisely, then injecting a tiny constant trend into the target forces the Enhanced replicator to express that trend *somewhere in the universe*. The decoder's solution — which instruments' weights shift to absorb the injected drift — reveals the replicator's **sensitivity structure**: which assets the decoder "reaches for" when it needs to generate extra return. If the decoder has genuine cross-asset flexibility, the shift will spread across multiple instruments and sleeves; if it has narrow flexibility (because the baseline target has narrow dependencies), the shift will concentrate.

The long-Enhanced / short-Baseline **excess portfolio** `r_excess_t = r_Enhanced_t − r_Baseline_t` materializes this sensitivity as a tradeable return stream. Its Sharpe, its drawdown profile, its correlation to standard market benchmarks, and — critically for multi-strategy use — its correlation to other strategies' excess streams become the diagnostic surface.

### 1.4 Why the excess is more informative than the replicator itself

A Bayesian replicator fit to a strategy's return stream will, by construction, track the strategy. Its own Sharpe, drawdown, and sleeve breakdown reflect the strategy's ex-post behavior — they say nothing new beyond what the strategy's PnL already tells us.

The excess portfolio — the *difference* between Enhanced and Baseline replicators — is not about tracking the strategy. It is about the **incremental degrees of freedom** the universe offers to express an injected trend. A strategy whose Baseline replicator is nearly mechanical (few effective universe DoFs, think: a near-passive BTC-holder) will have an Enhanced replicator that is almost identical to Baseline — the excess collapses. A strategy whose Baseline replicator has genuine cross-asset adaptability (many effective DoFs, think: a cross-sectional basket with shifting tilts) will have an Enhanced replicator that expresses the injected trend through meaningful instrument substitutions — the excess has rich structure.

This is the diagnostic that Ai For Alpha 2026 uses to rank hedge-fund families by how much decoding alpha they offer. In APEX's context we flip the question: is a *new* strategy's excess structurally different from *existing* strategies' excesses? If yes — diversifying. If no — redundant.

### 1.5 The trend-shock experiment on feature inputs

The second diagnostic in Ai For Alpha 2026 §3 is operationally distinct. Rather than injecting a trend into the **target** (which tests the replicator), inject a trend into a **feature input** that the strategy consumes (which tests the strategy). The canonical example in the paper: bump EUR/USD daily returns by +10%/year over 2016, re-run a strategy that takes EUR/USD as one of its inputs, and observe that GBP/USD's hedge-ratio absorbs 21.8% of the shift.

The interpretation: a well-calibrated strategy that trades EUR/USD should also, in its hedging logic, *reduce* its GBP/USD exposure when EUR/USD becomes more attractive (or vice versa, depending on the directional logic). A 21.8% substitution rate tells us the strategy has learned a plausible cross-FX relationship. An 80%+ substitution would suggest the strategy is too tightly coupled to EUR/USD specifically; a 0% substitution would suggest the strategy ignores this cross-relationship.

In APEX, the trend-shock test operates as a **feature robustness audit**. For each feature input declared in the per-strategy Charter's "Decoded Replication Baseline" section, we inject a bounded annualized trend and re-run. Three pathologies are gated against (ADR-0011 §7.4 item 5):

- **Dead features** — the bump produces no weight response. The feature is either not connected to the strategy's output, is being suppressed by downstream normalization, or has such low SNR that the strategy has effectively zero gradient on it. Prune the feature.
- **Brittle features** — the bump produces a wildly disproportionate response (single instrument absorbs >80% of the shift, sign flip, or hysteresis lasting months after `bump_end`). The feature has too much leverage in the strategy's decision; a small real-world perturbation in that feature could produce catastrophic mis-sizing. Regularize the feature.
- **Well-calibrated features** — the bump produces a smooth, bounded, sign-consistent, cross-asset substitution response. The feature is well integrated into the strategy's logic; keep it.

None of these outcomes is a Sharpe number. They are **structural properties** of the strategy's input-to-output gradient, surfaced by the harness and read by a human.

### 1.6 Rolling redundancy monitoring

The third use case — `StrategyRedundancyMonitor` — is the simplest mechanically but the most strategically important. Once multiple strategies are live, the harness computes each strategy's excess-return stream (from `EnhancedComparator` runs) on a rolling 60-day window and assembles the pairwise correlation matrix. When any pairwise correlation exceeds 0.85, an alert fires.

Why excess returns and not raw PnL? Because **raw PnL correlation is a lagging, noisy, and scale-dependent signal**. Two strategies can have low realized-PnL correlation by accident (different leverage, different timing of fills, different venue costs) while being structurally redundant — their replicator excess streams would reveal that. Conversely, two strategies can have high realized-PnL correlation in a specific regime (say, a risk-off flight-to-quality period) while being genuinely diversified outside that regime — the excess correlation matrix shows this conditional structure more clearly than raw PnL does.

The 0.85 default is deliberately loose. Tighter thresholds produce more false positives in young books with limited history; looser thresholds miss genuine redundancy. The alert is a review trigger, not an auto-reallocation signal — the allocator ([ADR-0008](../adr/ADR-0008-capital-allocator-topology.md)) does not consume the alert directly; it exists for the CIO's attention.

---

## 2. Worked example on toy data (HAR-RV variants)

This section walks through a realistic example of the `EnhancedComparator` pattern applied to **two variants of the HAR-RV realized-variance signal** that APEX already uses in its realized-variance research. All numbers below are illustrative — the real runs happen in Phase B Gate 3 and Phase C on vendor data per ADR-0011 §11.

### 2.1 The two variants

- **Baseline: `har_rv_baseline`** — Corsi's classical HAR model (Corsi 2009): `RV_t = β_0 + β_d · RV_{t-1}^{(d)} + β_w · RV_{t-1}^{(w)} + β_m · RV_{t-1}^{(m)} + ε_t`, where `RV_{t-1}^{(d)}`, `RV_{t-1}^{(w)}`, `RV_{t-1}^{(m)}` are the daily, weekly-average, and monthly-average lagged realized variances. Three components, no regime conditioning.
- **Enhanced: `har_rv_enhanced`** — same three HAR components plus a regime-conditional term: `RV_t = β_0 + β_d · RV_{t-1}^{(d)} + β_w · RV_{t-1}^{(w)} + β_m · RV_{t-1}^{(m)} + γ(z_t) · RV_{t-1}^{(d)} + ε_t`, where `γ(z_t)` is a gating coefficient that activates in the high-volatility regime (as classified by the S03 RegimeDetector).

The question the harness must answer: *does the regime-conditional term add diversifying information, or is it a scaled version of what the three HAR components already capture?*

### 2.2 Synthetic data setup (illustrative)

Assume two years of daily returns for 25 liquid universe instruments per the cross-asset table in ADR-0011 §6.1, simulated from a block-correlated multivariate normal calibrated to rough historical correlations. The target return streams are generated as follows:

- `r_target_baseline_t` = a signed position in SPY realized-variance forecast × SPY daily return, plus small cross-asset noise.
- `r_target_enhanced_t` = same, with an additional regime-conditional tilt that is non-zero on days the simulated regime detector flags high-vol — roughly 20% of days.

The two strategies are intentionally close cousins. The enhanced version has extra information only on a minority of days, which is exactly the case where inspection of raw PnL correlation would be insufficient — conditional redundancy is precisely the pattern the decoded replication harness is designed to detect.

### 2.3 Decoder fit and excess construction

Fit `StrategyDecoder` twice, both with `δ = 0.98`, both on the same 25-instrument universe, one with target `r_target_baseline_t`, one with `r̃_t = r_target_enhanced_t + 10%/252`. The outputs are two time series of 25-dimensional weight vectors `β̂^{Baseline}_t` and `β̂^{Enhanced}_t` over 504 trading days.

The replicating returns:
- `r^{Baseline}_t = x_t^T β̂^{Baseline}_t`
- `r^{Enhanced}_t = x_t^T β̂^{Enhanced}_t`

The excess return: `r_excess_t = r^{Enhanced}_t − r^{Baseline}_t`.

### 2.4 Illustrative metrics table

Below are the shape of numbers a well-calibrated "enhanced does add alpha" run would produce on this toy setup. These are **illustrative** — exact values depend on the simulation seed and the specific γ(z_t) calibration.

| Metric | Value (illustrative) |
|---|---|
| `cumulative_return` | +4.2% over 504 days |
| `annual_return` | +2.1% |
| `volatility` | 3.4% annualized |
| `sharpe` | 0.62 |
| `max_drawdown` | -1.8% |
| `return_to_drawdown` | 1.17 |
| `correlation_to_market` (SPY TR) | +0.08 |
| `correlation_to_baseline` (r_baseline_t) | +0.41 |

The reading:

- `sharpe = 0.62` > 0.3 → passes ADR-0011 §7.4 item 1.
- `correlation_to_market = 0.08` is low absolute value → weakly sensitive to broad equity beta, a good sign if the book already has equity exposure elsewhere.
- `correlation_to_baseline = 0.41` → moderately correlated. Not a scaled version of the baseline (that would be ~0.95+), but not orthogonal either. The enhancement rides adjacent information to the baseline on most days and diverges only in specific regimes, consistent with the design.

### 2.5 Attribution by sleeve

The sleeve attribution aggregates `|β̂^{Enhanced}_t − β̂^{Baseline}_t|` by sleeve over all 504 days, then normalizes to sum to 100%:

| Sleeve | Share of weight shift (illustrative) |
|---|---|
| Equities | 42% |
| Bonds | 18% |
| Credit | 6% |
| FX | 21% |
| Commodities | 13% |

No single sleeve exceeds 70% → passes ADR-0011 §7.4 item 3. The shift is reasonably spread, with equities dominant (expected — the underlying strategy trades equity realized variance) but meaningful contributions from FX (volatility carry substitution) and bonds (flight-to-quality substitution during high-vol regimes).

### 2.6 Redundancy against the (hypothetical) live book

Suppose Strategy #1 (Crypto Momentum) is already live and has its own excess stream. We compute the rolling 60-day correlation between `r_excess^{har_rv_enhanced}` and `r_excess^{crypto_momentum}`:

- Full-sample correlation: +0.12
- Max rolling 60-day correlation: +0.28
- Min rolling 60-day correlation: −0.15

All windows stay below 0.85 → passes ADR-0011 §7.4 item 4. No redundancy alert would fire.

### 2.7 Trend-shock on realized variance input

For `TrendShockInjector` with `bump_bps_annual = +1000` (+10%/year) on `RV_t^{(d)}` of SPY over a 3-month window, re-run both variants and compare `β̂^{shocked}` vs `β̂^{unshocked}` for the enhanced variant.

Illustrative substitution pattern during the bump window:
- QQQ absorbs ~24% of the shift (strong SPY-QQQ correlation, expected).
- VGK absorbs ~11% (cross-sectional equity-beta substitution).
- IEF absorbs ~9% (flight-to-quality tilt during the induced vol shock).
- Remaining 56% spread across 22 other instruments with single shares < 8%.

Reading: no single instrument >80%, sign-consistent direction, moderate substitution into bonds — passes ADR-0011 §7.4 item 5.

### 2.8 A failure-case variant — illustrating what rejection looks like

To calibrate intuition on what a **failing** gate looks like, consider a hypothetical alternative enhancement: `har_rv_enhanced_v2`, which adds a constant +3% annualized carry to the baseline output without adding any cross-asset or regime-conditional structure. This is the archetypal "trivial enhancement" the gate is designed to reject.

Illustrative output on the same 2-year window:

| Metric | Value (illustrative) |
|---|---|
| `cumulative_return` | +6.0% over 504 days (matches the injected carry, nothing more) |
| `sharpe` | 2.40 (!) |
| `correlation_to_market` | +0.02 |
| `correlation_to_baseline` | +0.96 |

At first glance the Sharpe is exceptional. But `correlation_to_baseline = 0.96` is the giveaway — the enhanced return stream is essentially `r_baseline + constant`, which correlates with itself. The gate reads this correctly:

- Item 1 (Sharpe > 0.3): passes mechanically, but the number is suspicious.
- Item 2 (|correlation_to_market| below book average): passes, but for a spurious reason — constant carry has zero market beta by construction.
- Item 3 (no sleeve > 70%): *fails*. Because the enhancement's only effect is a scalar add, the decoder has no incremental structural information; it allocates the carry to whichever single instrument has the highest local Sharpe over the window (often SPY, sometimes GLD). In the illustrative run, 82% of the weight shift lands on SPY — single-sleeve concentration, reject.
- Item 4 (pairwise correlation < 0.85 vs live strategies): **fails**. Constant-carry enhancements correlate highly with any other constant-carry enhancement (trivially) and also highly with any enhancement that happens to land on the same dominant instrument. If Strategy #1 Crypto Momentum's excess happens to also concentrate in equity beta in the evaluation window, the correlation may exceed 0.85.
- Item 5 (trend-shock robustness): passes vacuously — the constant carry does not consume any feature input, so trend-shocking any input produces the same weight response as the baseline. The gate does not penalize this directly, but item 3's failure is sufficient.

Reject. The author is sent back to rethink what the enhancement is actually supposed to accomplish.

This failure case is valuable not because it represents a realistic proposal (no APEX engineer would actually submit a constant-carry enhancement) but because it demonstrates that the gate has **multiple independent failure modes** that are hard to satisfy simultaneously without a genuine cross-asset / cross-regime edge. A trivial enhancement may clear one gate accidentally but cannot clear all five.

### 2.9 A second worked example — cross-strategy redundancy

Suppose Strategy #2 Trend Following has been live for 60 days with the `EnhancedComparator` producing its excess stream regularly. Now Strategy #3 (say, a VIX-term-structure strategy) is entering Gate 2 review. We run `EnhancedComparator` on Strategy #3 and, critically, also compute the rolling 60-day correlation between Strategy #3's excess and Strategy #2's excess.

Illustrative rolling correlation trajectory across the evaluation history (daily windows):

| Window end | corr(S3_excess, S2_excess) |
|---|---|
| 2025-01-15 | +0.21 |
| 2025-04-30 | +0.34 |
| 2025-07-10 | +0.62 |
| 2025-10-05 | +0.81 |
| 2026-01-20 | +0.88 ← **alert** |
| 2026-03-18 | +0.77 |

One window exceeds the 0.85 threshold. Is this structural redundancy or an artifact of a specific market regime?

A reviewer would:

1. Check what was happening around 2026-01-20. If a volatility event — a VIX spike — coincided with a trend-following risk-off move, the excess streams of both strategies would track the same cross-asset flight-to-quality. This is **conditional** redundancy.
2. Check the rest of the history. A single window above 0.85 in an otherwise sub-0.5 history is consistent with conditional redundancy and is not fatal.
3. Check whether the allocator ([ADR-0008](../adr/ADR-0008-capital-allocator-topology.md)) has a regime-aware de-weighting rule that would reduce one of the two strategies' allocation during VIX spikes. If yes, the redundancy is managed; if no, Strategy #3's per-strategy Charter must propose one.

Outcome: **conditional pass** with a required Charter addendum. This is the kind of decision the harness surfaces to the CIO — it does not auto-reject, but it does require a human reading.

---

## 3. Translation table — Ai For Alpha concepts to APEX equivalents

| Ai For Alpha 2026 concept | APEX equivalent | Notes |
|---|---|---|
| Opaque hedge-fund strategy to decode | A strategy we own, decoded internally as QA | We own the code; decoding is a diagnostic, not an information-extraction exercise |
| Hedge Fund family baseline | Current production variant of our strategy's signal | The baseline is always explicit, declared in per-strategy Charter §7.1 |
| Hedge Fund family enhanced | Proposed variant of the same strategy with a new feature / parameter change | The "enhancement" is what the PR author is proposing to ship |
| Long Enhanced / Short Baseline excess | `EnhancedComparator.excess_portfolio()` output | Same construction, same math; cosmetic rename reflects the QA framing |
| Liquid universe (Ai For Alpha 25-instrument cross-asset) | ADR-0011 §6.1 default universe (same instruments, APEX venues) | We preserve the paper's universe by default for comparability; per-strategy supersets allowed with declaration |
| Trend-shock EUR/USD +10% over 2016 | `TrendShockInjector` on any declared feature input, bounded window | We apply the bump to *feature inputs*, not strategy outputs; scope is broader than the paper's FX-only examples |
| 15% correlation to S&P 500 (Ai For Alpha result) | Not a target for APEX | Those numbers are paper findings on paper data; our gate is *relative* to our own book (ADR-0011 §7.4 item 2) |
| 0.91 Sharpe of Hedge Funds family excess | Not a target for APEX | Same reason; our gate is > 0.3 with CPCV purging (ADR-0011 §7.4 item 1) |
| 21.8% GBP/USD substitution ratio | Substitution pattern in ADR-0011 §7.4 item 5 | Detected by the harness; interpreted by the reviewer; not pinned to a specific number |
| Deep decoding of the strategy (Ohana et al. 2022) | Linear DLM decoder as v1; deep extensions deferred to post-Phase-D ADR | We start linear per ADR-0011 §11 "Post-Phase D extensions"; non-linear is out of scope for v1 |
| Preference-conditioned portfolios (Benhamou et al. 2024) | Not directly in APEX | Relevant reference for the methodology lineage; no current APEX use case |

---

## 4. Python pseudocode for the Kalman filter (illustrative only)

The following is a **sketch** intended to communicate the shape of the forward-filter implementation, not a runnable module. Real implementation will live in `validation/decoding/kalman.py` per ADR-0011 §11 Phase B Gate 3, likely delegated to a Rust crate (`apex_risk` or similar) for performance. Type annotations omitted below for compactness — the production implementation must include them per [CLAUDE.md §5 type safety](../../CLAUDE.md).

```python
def forward_filter(y, X, delta=0.98, sigma_eps_sq=None):
    """
    West & Harrison 1997 Ch. 4 sketch — forward Kalman filter for
    the DLM:
        y_t = X_t^T β_t + ε_t,  ε_t ~ N(0, σ²)
        β_t = β_{t-1} + η_t,     η_t ~ N(0, W_t)
    with discount-factor parameterization W_t = (1-δ)/δ C_{t-1}.

    Args:
      y: shape (T,)   — target returns
      X: shape (T, p) — universe returns
      delta: discount factor in (0, 1]
      sigma_eps_sq: observation variance; if None, estimated adaptively

    Returns:
      beta: shape (T, p) — posterior mean β̂_t
    """
    T, p = X.shape
    beta = np.zeros((T, p))
    C = np.eye(p)  # initial prior covariance — diffuse
    sigma_sq = sigma_eps_sq if sigma_eps_sq is not None else 1.0

    for t in range(T):
        # 1. Evolve state prior: mean unchanged, covariance inflated by 1/δ
        a = beta[t - 1] if t > 0 else np.zeros(p)
        R = C / delta

        # 2. Form one-step forecast and its variance
        f = X[t] @ a
        Q = X[t] @ R @ X[t] + sigma_sq

        # 3. Observe and update
        e = y[t] - f                # forecast error
        A = R @ X[t] / Q            # Kalman gain, shape (p,)
        beta[t] = a + A * e
        C = R - np.outer(A, X[t] @ R)

        # 4. Optional adaptive σ² update (Bayesian conjugate)
        # — see West & Harrison 1997 §4.5 for the full update rule

    return beta
```

The full production implementation must additionally provide:

- Retrospective (backward) smoothing per West & Harrison 1997 §4.4.
- Posterior covariance `C_t` as a second output for confidence intervals on β̂_t.
- Handling of missing observations (skip the update step; only evolve the prior).
- Adaptive σ² estimation via the conjugate inverse-gamma update.
- Numerical stability: Cholesky-factored covariance updates, clipping of singular Q.

### 4.1 Backward (retrospective) smoothing — sketch

Forward filtering produces `β̂_t` conditioned on information up to time t. For offline analysis (which the harness always is), we also want the full-sample posterior `β̂_{t|T}` conditioned on all observations 1..T — this is the **smoother**. West & Harrison 1997 §4.4 gives the backward recursion; a sketch:

```python
def backward_smoother(beta_filt, C_filt, delta=0.98):
    """
    Given forward-filter output (beta_filt, C_filt), compute
    smoothed estimates beta_smooth[t] = E[β_t | y_{1:T}].
    """
    T, p = beta_filt.shape
    beta_smooth = beta_filt.copy()
    C_smooth = C_filt.copy()
    for t in range(T - 2, -1, -1):
        # Backward gain
        R_next = C_filt[t] / delta
        B = C_filt[t] @ np.linalg.inv(R_next)
        # Smooth
        beta_smooth[t] = beta_filt[t] + B @ (beta_smooth[t + 1] - beta_filt[t])
        C_smooth[t] = C_filt[t] + B @ (C_smooth[t + 1] - R_next) @ B.T
    return beta_smooth, C_smooth
```

For the harness's primary use case — computing the excess portfolio — both filtered and smoothed estimates are valid, but they answer different questions. The filtered excess is what the replicator **would have produced in real time** had it been running live; the smoothed excess is what the replicator **retrospectively says is the best reconstruction** given all observations. The onboarding gate uses the **smoothed** excess because offline evaluation has the full sample available; the post-Gate-4 weekly cron uses the **filtered** excess because it is simulating what would be knowable at each point in time.

### 4.2 Adaptive observation variance

A fixed σ² is suboptimal in practice — real strategy returns have time-varying noise. West & Harrison 1997 §4.5 introduce a conjugate inverse-gamma update that tracks σ² over time. Sketch:

```python
def update_sigma_sq(n_prev, s_prev, e, Q, delta_sigma=0.96):
    """
    Adaptive σ² update via inverse-gamma conjugate prior.
    delta_sigma discounts the variance prior like delta discounts
    the state prior; common choice is 0.96 for daily returns.
    """
    n_new = delta_sigma * n_prev + 1
    s_new = delta_sigma * s_prev + (e ** 2) / Q
    sigma_sq = s_new / n_new
    return sigma_sq, n_new, s_new
```

The harness's production implementation integrates `update_sigma_sq` inside the forward filter loop, updating `sigma_sq` on each step.

### 4.3 Numerical stability considerations

For a universe of `p = 25` instruments over `T = 2520` daily bars, the `O(T · p³)` forward filter is well within numerical reason. However, practical pitfalls:

- **Near-singular Q**: when `x_t` has near-zero variance at time t (e.g., a holiday with stale prices), `Q = x_t^T R x_t + σ²` may be dominated by σ² and produce a near-zero Kalman gain. This is correct behavior but can produce under-updates if σ² is mis-estimated. The production implementation should log a warning when `x_t^T R x_t / Q < 0.01`.
- **Covariance symmetry drift**: the update `C = R − A x_t^T R` is mathematically symmetric but numerically can develop small asymmetries over many steps. Re-symmetrize: `C = (C + C.T) / 2` every 100 steps.
- **Positive-definiteness**: use Joseph form `C = (I − A x_t^T) R (I − A x_t^T).T + σ² A A.T` for guaranteed positive definiteness, at the cost of a constant factor in runtime.
- **Prior sensitivity**: the initial `C_0 = I` (diffuse prior) produces over-confident early estimates. The production implementation sets `C_0 = κ · I` with `κ = 10^4` (very diffuse) and discards the first `p` observations from analysis.

None of these are novel — they are standard Kalman implementation hygiene and are well-documented in West & Harrison 1997 §4.6 and in the broader DLM / control-theory literature. The harness's design PR must demonstrate on synthetic data that the implementation clears these hygiene gates before it is used on real APEX strategy data.

---

## 4bis. Calibration methodology for the §7.4 thresholds

The gate thresholds in ADR-0011 §7.4 — `excess_sharpe > 0.3`, single-sleeve < 70%, pairwise-excess-correlation < 0.85, ±30% Gate-3 drift tolerance — are **initial defaults**. They must be calibrated against empirical runs as APEX accumulates data. This section lays out the calibration protocol.

### 4bis.1 Bootstrap CI on excess metrics

Per [ADR-0002](../adr/0002-quant-methodology-charter.md) item 3, all Sharpe claims must carry a 95% CI via stationary bootstrap (Politis & Romano 1994). The excess Sharpe is no exception. The harness's `ExcessMetrics.sharpe` must be reported with a 95% CI in the Gate 2 PR body:

```
excess_sharpe = 0.62  [CI_95: 0.18, 1.07]
```

The threshold check in §7.4 item 1 operates on the **lower bound** of the CI, not on the point estimate. A strategy whose point estimate is 0.62 but whose lower bound is 0.18 is marginal; a strategy whose lower bound is > 0.3 passes decisively.

### 4bis.2 Multi-strategy DSR correction

When multiple variants of a strategy are evaluated against the same baseline (e.g., enhanced-v1, enhanced-v2, enhanced-v3 all proposed as improvements over the same baseline), the DSR correction (Bailey & López de Prado 2014) applies. The harness must report `DSR_excess` alongside `excess_sharpe` and the gate operates on the DSR-corrected value. Per ADR-0002 item 4, this is already the convention for standard backtests; the excess evaluation inherits it unchanged.

### 4bis.3 Initial calibration of thresholds

The 0.3, 0.70, 0.85, and ±30% numbers in ADR-0011 §7.4 are initial values taken from:

- **0.3 excess Sharpe**: half of the Ai For Alpha 2026 paper's Hedge Fund family excess Sharpe of 0.91; chosen as a half-confident bar given APEX's smaller universe and less-diversified book than a full hedge-fund family aggregate.
- **70% single-sleeve cap**: pragmatic — most cross-asset strategies in the academic literature concentrate 40-60% in their "home" sleeve; 70% allows some concentration without permitting single-sleeve riding.
- **0.85 pairwise excess correlation**: roughly the correlation level at which two strategies' excess streams can be treated as substitutes for capital-allocation purposes under a risk-parity allocator ([ADR-0008](../adr/ADR-0008-capital-allocator-topology.md) §3).
- **±30% Gate-3 drift tolerance**: loose enough to allow genuine out-of-sample evolution without re-triggering the gate, tight enough to catch regime-specific paper-trading performance that does not match backtest.

These numbers are **provisional**. After Phase B Gate 3 and the first two live strategies pass through, the CIO and Claude Code agents will have empirical data on what thresholds actually distinguish good from bad strategies on APEX data. A calibration ADR (candidate ADR-00XX, post-Phase-D) will revisit these numbers with at-that-point empirical backing.

### 4bis.4 Threshold drift over time

As the book grows from one strategy to six, the redundancy threshold (item 4) becomes harder to satisfy — there are more pairwise correlations to keep below 0.85. This is intentional: the gate **should** tighten as the book matures, because the marginal diversification benefit of the Nth strategy shrinks. If the threshold becomes binding (i.e., many candidate strategies are rejected purely on redundancy), the CIO has two responses:

1. **Accept the bottleneck**: the book is already well-diversified; further diversification requires materially novel strategies, which is the intended design.
2. **Reduce the allocator concentration**: if the allocator's risk-parity constraints are forcing similar-looking strategies, the fix is at the allocator level, not at the onboarding gate.

A tightening gate is a feature, not a bug. Neither response involves loosening the threshold to make more strategies pass.

---

## 5. Interpretation guide — how a reviewer reads the harness output

The harness produces four artifacts per strategy per run: the `ExcessMetrics` bundle, the sleeve attribution dict, the rolling redundancy matrix, and (when `TrendShockInjector` is used) the substitution / elasticity / hysteresis summary. A reviewer's job is to triangulate these four artifacts against the per-strategy Charter's claimed edge.

### 5.1 Reading `ExcessMetrics`

| Observation | Reading |
|---|---|
| `sharpe > 0.5` AND `correlation_to_baseline < 0.7` | **Strong signal** — enhanced variant adds real, diversifying alpha on top of baseline. Favor merging. |
| `sharpe > 0.5` AND `correlation_to_baseline > 0.9` | **Scaled replica** — enhanced variant produces a higher Sharpe, but its returns are strongly co-moving with baseline. The "enhancement" is likely just a leverage or normalization change, not new information. Reject — or request a revised enhancement that targets a different sleeve of variance. |
| `sharpe < 0.3` AND `correlation_to_baseline < 0.3` | **Uncorrelated but unprofitable** — enhanced variant produces a genuinely different return stream, but that stream does not have alpha. Reject — the variant is introducing noise, not signal. |
| `sharpe ≈ 0` (in either direction) AND `correlation_to_baseline ≈ 1` | **No-op** — the enhancement does nothing. The harness is behaving correctly; the author should reconsider whether the enhancement is real or a bug in the feature pipeline. |
| `|correlation_to_market| > existing book's average` | **Introduces market beta** — the enhancement's profile is more equity-beta-like than what the book already holds. Reject under ADR-0011 §7.4 item 2 unless an explicit capital-allocation case is made for adding market beta. |

### 5.2 Reading the sleeve attribution

| Observation | Reading |
|---|---|
| Single sleeve > 70% | **Concentration** — the enhancement rides one sleeve's dynamics. Reject under ADR-0011 §7.4 item 3. |
| No sleeve > 40%, shift spread over ≥3 sleeves | **Diversified** — the enhancement pulls from multiple asset classes, suggesting genuine cross-sleeve sensitivity. Favor. |
| Large shift into sleeves the strategy does not trade | **Replicator artifact** — expected and benign. The decoder may hedge realized variance via the bond sleeve even if the strategy itself only trades equity vol; what matters is whether the *excess* is explainable, not whether it maps 1-to-1 to what the strategy actually holds. |

### 5.3 Reading the rolling redundancy matrix

| Observation | Reading |
|---|---|
| All pairwise 60-day correlations consistently < 0.5 | **Well-diversified book** — the new strategy adds value across the evaluation history. Pass. |
| One pair briefly exceeds 0.85 in a specific regime | **Conditional redundancy** — the two strategies behave similarly under a specific regime. Not an automatic reject, but the per-strategy Charter must acknowledge the regime and explain how capital allocation handles it (e.g., allocator de-weights one when the regime hits). |
| One pair sustains > 0.85 across most windows | **Structural redundancy** — fatal. The new strategy replicates an existing one too closely to earn independent capital. Reject. |

### 5.4 Reading the trend-shock response

| Observation | Reading |
|---|---|
| Bump produces no weight response at all | **Dead feature** — the input is not effectively wired into the strategy's decision function. Either it has no predictive power or it is being suppressed downstream. Audit the feature pipeline. |
| Bump produces a response concentrated on one instrument (>80% of shift) | **Brittleness** — the feature has too much leverage on one substitute. A real-world perturbation could cause mis-sizing. Regularize the feature or widen the substitution space. |
| Bump produces smooth cross-asset substitution (no single instrument > 40%) | **Well-calibrated** — the feature is integrated into a broader decision logic with realistic hedging substitution. Keep. |
| Weight response persists for > 1 month after `bump_end` | **Hysteresis** — the feature or the strategy has slow-decay memory beyond what is plausible for a liquid-market system. Audit for stale-state bugs. |

### 5.5 What the harness does **not** tell you

- **Causality**. A non-trivial β̂_t does not imply the strategy causally trades those instruments.
- **Profitability in isolation**. The excess portfolio is a diagnostic; its Sharpe is a gate, not a forecast for the enhanced strategy's live-trading Sharpe.
- **Out-of-sample generalization**. The harness is historical. Its output says nothing about how the enhancement will behave in a regime not yet seen.
- **Transaction costs**. The replicating portfolios are not real portfolios; their returns do not include costs. ADR-0002 §1–10 continues to govern cost-sensitivity evaluation.
- **Capacity**. The decoder ignores strategy-capacity constraints. ADR-0002 item 9 governs capacity separately.

These limits matter: the harness is one gate in the onboarding pipeline, not a substitute for ADR-0002's ten-item evaluation.

---

## 6. Integration with the ADR-0002 canonical reference list

ADR-0011 §9 proposes adding the following five references to the ADR-0002 "Mandatory references" table. The rationale for each:

1. **Ai For Alpha Team (March 2026)** — primary source for the long-Enhanced / short-Baseline diagnostic and the trend-shock experiment. Every implementation of the three harness tools traces back to this note.

2. **Benhamou, Ohana & Guez (2024)** — SSRN working paper 4780034 on preference-conditioned portfolio construction via the same decoding framework. Relevant for the methodology lineage and for future extensions of the harness.

3. **Ohana, Benhamou, Saltiel & Guez (2022)** — Paris-Dauphine WP 4128693; foundational academic reference for the decoding framework as applied to strategies. Future non-linear decoder extensions (ADR-0011 §11 Post-Phase-D) build on the deep extensions in this paper.

4. **West & Harrison (1997)** — canonical textbook reference for dynamic linear models, discount factors, forward filtering, and retrospective smoothing. Any implementation of `StrategyDecoder` must cite this reference in its docstring per [ADR-0002](../adr/0002-quant-methodology-charter.md) convention.

5. **Kim & Nelson (1999)** — canonical textbook reference for regime-switching state-space models. The Phase B–D harness does not yet use regime switching, but the future ADR that addresses structural breaks (flagged in ADR-0011 §8 item 6) will be grounded in this reference.

A follow-up PR against ADR-0002 will append these five rows to the "Mandatory references" table with brief "Used for" descriptions, without altering the existing ten-item mandatory evaluation checklist.

---

## 7. Open questions for future ADRs

These are questions the authors could not resolve within the scope of ADR-0011 and that require either more empirical evidence or an explicit CIO decision.

### 7.1 Should the decoder universe be global or per-strategy-scoped?

ADR-0011 §6.1 takes a pragmatic compromise: a **default universe** applies to every strategy for cross-strategy comparability, but **per-strategy supersets** are allowed for sleeve-attribution analysis. The unresolved question: is this the right split, or should the universe be genuinely per-strategy (simpler per-strategy analytics, but cross-strategy redundancy checks become apples-to-oranges)?

The current compromise is workable for Phase B–D with two to three live strategies. By the time the book has five or six strategies, we will have enough empirical evidence (several rounds of onboarding gate runs) to decide whether the compromise holds or whether one of the two pure options is strictly better.

### 7.2 How to handle strategies that trade instruments NOT in the liquid universe?

A strategy that trades illiquid OTC instruments (bilateral swaps, illiquid options, niche crypto pairs) cannot be decoded against a universe that excludes those instruments. Two options:

- (a) Restrict the strategy to not trade outside the universe.
- (b) Extend the universe to include proxies for the illiquid instruments.

Option (a) is too restrictive for a multi-strat platform. Option (b) risks the proxy-basis risk problem (the proxy may drift from the actual instrument's returns in stress periods). The default compromise in ADR-0011 §6.1 — per-strategy universe extensions — addresses this partially but does not solve the proxy-basis-risk problem. A future ADR may need to specify acceptable proxy-selection rules.

### 7.3 How often should the onboarding gate be re-run after initial promotion?

ADR-0011 §7.5 specifies weekly cron re-validation. This is a reasonable default but is not load-tested. If weekly proves too noisy (alert fatigue), we may relax to bi-weekly. If weekly proves too lagged (a redundancy develops mid-week and trades are placed before the next run), we may accelerate to daily. The Phase D operational experience with two live strategies will inform this calibration.

### 7.4 Should `RedundancyAlert` ever feed back into the capital allocator automatically?

ADR-0011 §7.5 keeps the alert as a **review trigger only** — the allocator does not consume it. Long-term, one could imagine a rule where sustained `RedundancyAlert` at correlation > 0.90 triggers an automatic allocator-weight tilt away from the more redundant strategy. This would be a material change to the capital allocation framework ([ADR-0008](../adr/ADR-0008-capital-allocator-topology.md)) and is out of scope for v1; a future ADR may revisit it after multi-strategy live experience is accumulated.

### 7.5 How should the harness interact with the meta-labeling fusion layer?

[ADR-0005](../adr/ADR-0005-meta-labeling-fusion-methodology.md) governs how signals are combined within a strategy via meta-labeling. If a strategy's signal pipeline includes a meta-label gate, should the decoded replication harness treat the *pre-meta-label* return stream or the *post-meta-label* return stream as the target?

The current working assumption is that the **post-meta-label** return stream is the strategy's actual output and is the correct target — the meta-label is part of the strategy's definition, not separate from it. But this has not been empirically validated against a meta-labeled signal in the harness. Phase B Gate 3 (HAR-RV enhanced variant) does not use meta-labeling; Phase C (Strategy #1 Crypto Momentum) does. Whichever pattern proves workable on the first meta-labeled application will set the convention.

### 7.6 Does the discount factor need to adapt during regime shifts?

A fixed `δ = 0.98` assumes homogeneous non-stationarity across the sample. In practice, regime shifts (e.g., the March 2020 COVID shock) produce bursts of volatility during which a smaller δ (more aggressive forgetting) might track the strategy better. Ai For Alpha 2026 §2 uses a fixed δ; Kim & Nelson (1999) Ch. 5 develop regime-switching DLMs where the state equation's hyperparameters depend on a latent regime variable.

The Phase B–D harness takes a fixed δ for simplicity. If empirical runs show systematic tracking failures during regime shifts, a future ADR will introduce a regime-switching δ or delegate to a full Kim-Nelson state-space model.

### 7.7 What to do when two strategies are decoded on non-overlapping universes?

ADR-0011 §7.4 item 4 requires pairwise correlation < 0.85 across all existing strategies' excess streams. If Strategy A's universe is global cross-asset and Strategy B's universe is crypto-only, their excess streams live in different instrument spaces. Correlation still makes sense pointwise in time (both are scalar return streams), but the **interpretation** of the correlation is less clear — the two excesses are not directly substitutable.

The default interpretation in Phase B–D: compute pairwise excess correlation regardless of universe, treat alerts as review triggers, and let the CIO read the correlation in context. A future ADR may tighten this if empirical confusion accumulates.

---

## 8. Summary

The decoded replication harness is a **three-tool QA infrastructure** inspired by the Ai For Alpha March 2026 paper and grounded in the Bayesian state-space literature (West & Harrison 1997, Kim & Nelson 1999) and its modern extensions to portfolio decoding (Ohana et al. 2022, Benhamou et al. 2024). APEX adapts the diagnostic pattern — long-Enhanced vs short-Baseline excess portfolios, trend-shock robustness tests, rolling excess-correlation monitoring — from its original use on external opaque strategies to an **internal QA use** at strategy onboarding gates and periodic live re-validation.

The harness is **additive to ADR-0002's ten-item mandatory evaluation checklist**, not a replacement. It closes the gap ADR-0002 leaves open: the multi-strategy question of whether a new strategy's contribution is structurally novel against an existing book. It runs offline, does not affect the live tick-to-order path, and produces human-read output summarized in the Decoded Replication telemetry tab.

Implementation is staged across Phase B Gate 3 (`EnhancedComparator`), Phase C (`TrendShockInjector` and `StrategyRedundancyMonitor`), and Phase D (full onboarding-gate integration and weekly live re-validation). Post-Phase-D extensions — regime-switching decoders, non-linear decoders, per-instrument attribution — are flagged but not scoped.

Full binding authority is in [ADR-0011](../adr/ADR-0011-decoded-replication-validation-harness.md). This note is the explanatory layer that the ADR references and that engineers and the CIO read before each implementation PR.

---

## 9. References

The following are the references cited in this note. Full bibliographic citations are also listed in [ADR-0011 §9](../adr/ADR-0011-decoded-replication-validation-harness.md).

- Ai For Alpha Team (March 2026). *"Strategy Spotlight: Decoding Alpha in Practice"*. Ai For Alpha white paper series.
- Benhamou, E., Ohana, J. & Guez, B. (2024). *"Generative AI: Crafting Portfolios Tailored to Investor Preferences"*. SSRN working paper 4780034.
- Ohana, J., Benhamou, E., Saltiel, D. & Guez, B. (2022). *"Deep Decoding of Strategies"*. Université Paris-Dauphine Research Paper 4128693 (SSRN).
- West, M. & Harrison, J. (1997). *Bayesian Forecasting and Dynamic Models* (2nd ed.). Springer-Verlag.
- Kim, C.-J. & Nelson, C. R. (1999). *State-Space Models with Regime Switching*. MIT Press.
- Corsi, F. (2009). *"A Simple Approximate Long-Memory Model of Realized Volatility"*. Journal of Financial Econometrics 7(2), 174–196. — basis of the HAR-RV signal used in the Phase B Gate 3 worked example (§2).
- Sharpe, W. F. (1963). *"A Simplified Model for Portfolio Analysis"*. Management Science 9(2), 277–293. — classical single-factor model, context for §1.1 discussion of time-varying exposures.
- Fama, E. F. & French, K. R. (1993). *"Common Risk Factors in the Returns on Stocks and Bonds"*. Journal of Financial Economics 33(1), 3–56. — classical three-factor model, same context.
