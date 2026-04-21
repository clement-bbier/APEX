# ADR-0013 — Capital Allocation Trajectory (Static YAML → Risk Parity → HRP)

> *This ADR specifies the **trajectory of allocation algorithms** the APEX platform will walk as the strategy count grows from 1 to 6+, tied mechanically to the Phase Gates of [`PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md`](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md). It does not replace [ADR-0008 (Capital Allocator Topology)](ADR-0008-capital-allocator-topology.md); it refines its algorithmic content by introducing a pre-allocator Tier 1 (static YAML) and a post-Phase-2 Tier 3 (Hierarchical Risk Parity).*

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-04-20 |
| Decider | Clement Barbier (CIO) |
| Supersedes | None |
| Superseded by | None |
| Related | [ADR-0008](ADR-0008-capital-allocator-topology.md) (allocator topology); [ADR-0007](ADR-0007-strategy-as-microservice.md) (strategy microservice); ADR-0012 (per-strategy sub-books, authored in parallel); [ADR-0014](ADR-0014-timescaledb-schema-v2.md) (`apex_strategy_metrics` as input data source); Charter §5.5, §6 |

---

## 1. Status

Proposed.

This ADR is authored during Phase A (the Pydantic `strategy_id` lift) to settle the algorithmic progression of the allocator **before** any allocator code is written in Phase C. The decision is non-urgent — no live allocation code depends on it — but authoring it now crystallises the interface contract the allocator service must respect across all three tiers.

---

## 2. Context

### 2.1 Why this ADR exists separately from ADR-0008

[ADR-0008](ADR-0008-capital-allocator-topology.md) ratifies the **topology** of the capital allocator: a dedicated microservice at `services/portfolio/strategy_allocator/`, its position in the 7-step VETO chain, its Pydantic contract, and its two-phase algorithmic sketch (Phase 1 Risk Parity, Phase 2 Sharpe overlay). That ADR was authored alongside Document 3 (Roadmap v3) and is necessarily coarse on algorithmic content — it ratifies the *shape*, not the *trajectory*.

This ADR fills in the algorithmic trajectory with three refinements ADR-0008 did not make:

1. **Tier 1 (static YAML)** is introduced as a pre-allocator state for Phase B Gate 2, where the allocator microservice does not yet exist in code. Without Tier 1, there is a chicken-and-egg problem: Strategy #1 needs a capital envelope at Gate 2 (paper) but the allocator service lands in Phase C (after Gate 2). Tier 1 resolves this by parking the weights in a YAML file that each strategy's own config loader reads at startup.
2. **Tier 2 (Risk Parity)** is the first live activation of the ADR-0008 allocator microservice, at Gate 3 (live-micro). It is the exact Phase 1 algorithm specified in ADR-0008 §D2, repeated here for authoritative reference with cross-tier context.
3. **Tier 3 (HRP)** is introduced as the Phase C / post-Phase-C evolution once 5+ strategies exist, *in addition to* the Sharpe overlay (ADR-0008 Phase 2). HRP (Lopez de Prado 2016) is orthogonal to the Sharpe overlay: HRP replaces the base allocation formula; the Sharpe overlay tilts whatever the base produces. The two can stack (HRP base + Sharpe tilt), or ship independently.

### 2.2 Constraints that shape the trajectory

- **Phase B starts with 1–2 strategies**; adaptive allocation has no signal to work with (n=1 means 100% allocation trivially; n=2 with two months of live returns produces a volatility estimate whose 95% CI is ±40% of the point estimate per Lo 2002).
- **Phase C grows to 5+ strategies** as Strategy #2, #3, #4 come online per Roadmap §7.2 — at this scale, cross-strategy correlation matrices become non-trivial and HRP's clustering starts to matter.
- **Static allocation is auditable and deterministic**: a human can reason about "Strategy A has 50%, Strategy B has 30%, cash buffer is 20%" without running code. Adaptive allocation is performance-aware but introduces **instability risk** — a bad volatility estimate or a correlation matrix near-singularity can produce weight oscillations that churn the book for no alpha.
- **The apex_strategy_metrics table** (ADR-0014 §2.1) is the authoritative source of per-strategy returns, vol, and Sharpe. Tier 2 and Tier 3 **depend** on this table being populated with at least 60 days of daily rows per strategy before their allocation decisions are trustworthy.
- **Phase Gates are trigger-based, not calendar-based** (Roadmap §1.2). The trajectory below is phrased in Gate terms, not month terms, so a strategy that takes longer to pass Gate 2 simply delays Tier 2 activation — it does not force a premature cutover.

### 2.3 What this ADR is NOT

- It is **not** a re-litigation of ADR-0008's topology decision. The allocator remains a dedicated microservice.
- It is **not** a commitment to specific live rebalance timestamps. The exact cadence per tier is specified below but may be refined in a follow-up ADR based on live evidence.
- It is **not** a per-strategy tuning document — per-strategy caps and burn-in values belong in `config/strategies/<strategy_id>.yaml` (per-strategy configs) and are discussed only illustratively here.
- It is **not** production code. No Python lands in this ADR or its companion.

---

## 3. Decision — 3-tier progression tied to Phase Gates

The APEX capital allocator walks three tiers of algorithmic sophistication, each tied to a specific Phase Gate in the Roadmap. A tier change requires this ADR to be amended (or a new ADR to supersede the relevant tier). Feature flag: `APEX_ALLOCATION_TIER=static|risk_parity|hrp`.

### 3.1 Tier 1 — Static YAML (Phase B, Gate 2, paper trading, 1–2 strategies)

**When.** Phase B has opened (Roadmap §3); Strategy #1 (LegacyConfluenceStrategy) is the first strategy to reach Gate 2 and enter paper trading with explicit `strategy_id="default"`. Optionally Strategy #2 begins Gate 1/Gate 2 during this window. The dedicated allocator microservice **does not yet exist in code** — it is scheduled for Phase C (Roadmap §4.2).

**How.** A single YAML file at `config/strategies.yaml` declares per-strategy weights as human-authored Decimal values. Each strategy microservice loads this file at startup and reads its own slice (the `capital_usd` field, derived from `weight × portfolio_capital_usd`, is consumed by the strategy's sub-book per ADR-0012). Reloaded on service restart only — no hot reload, no Redis pub/sub on config changes.

**Why.**

- **Deterministic.** The weights at any moment are exactly whatever is checked into `config/strategies.yaml` in the current HEAD commit. Git blame is the audit trail.
- **No math dependencies at runtime.** Tier 1 does not depend on `apex_strategy_metrics` being populated, does not depend on the covariance matrix being non-singular, does not depend on any rolling window of live returns. It ships as soon as a YAML loader exists.
- **Forces discipline before automation.** The operator (CIO) has to consciously think about each weight. This avoids the failure mode where an adaptive allocator silently allocates 80% to a strategy that happened to have low vol for the last 60 days — a failure mode documented in Clarke, de Silva & Thorley (2011) as "vol-minimisation producing concentration in recently-quiet assets."
- **Rationale aligns with institutional practice.** Millennium's new pods start at a fixed capital envelope set by the PM committee; Risk Parity does not apply until the pod has a track record. Tier 1 is the APEX-scale equivalent.

**Exit criteria.** Tier 1 ends when (i) the allocator microservice is deployed in Phase C (Roadmap §4.2), (ii) ≥ 2 strategies have accumulated ≥ 60 days of live paper trading returns in `apex_strategy_metrics`, (iii) a shadow-mode evaluation (see §7) confirms Tier 2 would produce stable weights under the observed volatility regime.

### 3.2 Tier 2 — Risk Parity (Phase C, Gate 3, live-micro, 3–5 strategies)

**When.** Phase C has delivered `services/portfolio/strategy_allocator/` (Roadmap §4.2); Strategy #1 has reached Gate 3 (live-micro) with a 60-day paper history; at least one other strategy exists with ≥ 60 days of history. The `apex_strategy_metrics` table has a non-empty daily time series for each active strategy.

**How.** The allocator microservice computes **inverse-volatility** weights per Maillard, Roncalli & Teiletche (2010, "The Properties of Equally Weighted Risk Contribution Portfolios," *Journal of Portfolio Management* 36(4), 60–70) under a diagonal covariance assumption. Widely published as Bridgewater All Weather's foundational layer (Qian 2005, "Risk Parity Portfolios: Efficient Portfolios Through True Diversification," PanAgora white paper).

**Formula.**

```
σ_i         = stddev( returns_i, rolling 60 days from apex_strategy_metrics )
w_raw_i     = 1 / σ_i
w_norm_i    = w_raw_i / Σ_j w_raw_j
w_clipped_i = clip( w_norm_i, min_weight=0.05, max_weight=0.40 )
w_final_i   = w_clipped_i × (1 - cash_buffer) / Σ_j w_clipped_j
```

where `σ_i` is the 60-day rolling standard deviation of daily returns for strategy `i` consumed from the `apex_strategy_metrics` table (ADR-0014 §2.1, row #9).

**Parameters.**

| Parameter | Value | Justification |
|---|---|---|
| σ window | 60 days rolling | Noise ~1/√60 ≈ 13% on σ estimate; tight enough to adapt within a quarter, loose enough to not churn on one bad week. Matches ADR-0008 §D2. |
| Rebalance cadence | Weekly, **Sunday 23:00 UTC** | Before Asia open Monday; AQR Risk Parity published cadence. Matches ADR-0008 §D2. |
| `min_weight` floor | 5% | Prevents starvation; guarantees drift-monitor (S09) has enough trade flow per strategy for attribution. Matches ADR-0008 §D2 and Charter §6.1.2. |
| `max_weight` ceiling | 40% | Prevents single-strategy dominance. Matches ADR-0008 §D2. |
| `cash_buffer` | 20% (configurable) | Held as idle USD; protects against margin surprise; emergency buffer for hard-CB redemption. |

**Why.**

- **Diagonal inverse-volatility is the canonical simplification** under the Risk Parity family (Maillard, Roncalli & Teiletche 2010 §3.1). It assumes cross-strategy correlations are either zero or roughly uniform — a plausible first approximation when strategies target orthogonal edges per the Charter's §4 boot-strategy selection.
- **Qian (2005)** established Risk Parity as Bridgewater's production sizing rule. It is battle-tested over 20+ years of All Weather performance.
- **Clear upgrade path.** If live evidence at Tier 2 shows cross-strategy correlations are persistently non-zero (e.g., a pairwise correlation matrix with average off-diagonal > 0.3), Tier 3 (HRP) naturally handles correlated clusters — see §3.3.

**Rebalance mechanics.** Detailed in §5 below.

**Exit criteria.** Tier 2 ends when (i) ≥ 5 strategies are active with ≥ 6 months of daily returns each in `apex_strategy_metrics`, (ii) the observed cross-strategy correlation matrix has at least one pair with |ρ| > 0.3 persistently for ≥ 8 weeks, (iii) a shadow-mode evaluation (§7) shows HRP's allocation would differ from Tier 2's by > 5% on at least 2 strategies, justifying the complexity upgrade.

### 3.3 Tier 3 — Hierarchical Risk Parity (Phase C+, 5+ strategies, diversified book)

**When.** Phase C is complete; ≥ 5 strategies are active in live-full; cross-strategy correlations are non-negligible (per Tier 2 exit criteria). Phase D or later.

**How.** The allocator implements **Hierarchical Risk Parity (HRP)** per Lopez de Prado (2016, "Building Diversified Portfolios That Outperform Out of Sample," *Journal of Portfolio Management* 42(4), 59–69). HRP is a multi-step algorithm that combines hierarchical clustering with recursive bisection:

1. **Compute correlation matrix** ρ from strategy daily returns in `apex_strategy_metrics` over a rolling window (60 days matches Tier 2; a longer window, e.g. 120 days, may be used once history allows).
2. **Compute distance matrix** `d_ij = sqrt( 0.5 × (1 - ρ_ij) )` (Lopez de Prado 2016 eq. 5). This converts correlations into a metric distance suitable for hierarchical clustering.
3. **Hierarchical clustering** via Ward linkage on `d`, producing a dendrogram of strategy groupings.
4. **Quasi-diagonalisation** reorders the correlation matrix so that correlated strategies sit adjacent (Lopez de Prado 2016 §2.3). This concentrates large correlations near the diagonal and makes the recursive bisection step meaningful.
5. **Recursive bisection** splits the reordered universe into two halves at each level of the dendrogram, allocating weight to each half inversely proportional to the cluster's inverse-variance portfolio variance. Within each final cluster, the residual weight is distributed by inverse-variance.

**Full algorithm.** Refer to Lopez de Prado (2016) §2 for the complete mathematical specification. This ADR does not reproduce the full pseudocode — the paper is the authoritative reference and is open-access via SSRN. The APEX implementation will follow the paper verbatim in `risk_parity_hrp.py`, with unit tests that reproduce the paper's Table 1 worked example.

**Parameters.**

| Parameter | Value | Justification |
|---|---|---|
| ρ window | 60 days rolling (initially), escalating to 120 days once history allows | Matches Tier 2 σ window. Lopez de Prado 2016 uses 260-day Ledoit-Wolf shrinkage in the paper; APEX's smaller history forces a shorter window initially. |
| Linkage | Ward (default) | Lopez de Prado 2016 §2.2 uses single linkage. Ward is more stable on small samples and is the scipy default; a follow-up ADR can revisit if live evidence favors single linkage. |
| Rebalance cadence | **Monthly**, first trading day UTC | HRP is more expensive computationally than Risk Parity and less susceptible to high-frequency noise; monthly cadence matches institutional HRP deployments (Lopez de Prado 2020 textbook). |
| `min_weight` / `max_weight` / `cash_buffer` | Unchanged from Tier 2 (5% / 40% / 20%) | Caps apply **after** the HRP allocation, with overflow redistribution. |

**Why.**

- **Lopez de Prado (2016)** demonstrates in out-of-sample Monte Carlo that HRP outperforms Markowitz MVO and inverse-variance (i.e., Tier 2 Risk Parity) on both Sharpe and max drawdown for portfolios of 10+ assets with non-trivial correlation structure. The paper is the highest-cited allocation paper of the last decade.
- **Handles correlated strategies gracefully.** If Strategies #3, #4, #5 are all variants of crypto momentum (high pairwise correlation), Tier 2 over-allocates to the cluster because each strategy "looks" diversified in isolation. HRP identifies the cluster and allocates within-cluster first, avoiding concentration.
- **Matrix singularity robustness.** HRP does **not** invert the covariance matrix (unlike Markowitz). It works on distances. This makes it robust to near-singular correlation matrices that would destabilise a Markowitz solver.

**Rebalance mechanics.** Identical to Tier 2 (§5) but monthly instead of weekly.

**Exit criteria.** Tier 3 is the terminal tier contemplated in this ADR. Further evolution (Black-Litterman, regime-conditional HRP, Kelly meta-allocation) is out of scope and parked for a future ADR (see §10).

### 3.4 Sharpe overlay (orthogonal to the tier progression)

ADR-0008 §D3 specifies a **Phase 2 Sharpe overlay** that tilts the base allocation by ±20% based on rolling 6-month Sharpe spread. This overlay is **orthogonal** to the tier progression:

- It can sit on top of Tier 2 (Risk Parity + Sharpe tilt) — this is exactly ADR-0008's Phase 2 vision.
- It can sit on top of Tier 3 (HRP + Sharpe tilt) — a natural extension once HRP is stable.
- It cannot sit on top of Tier 1 (static YAML) — Tier 1 is deliberately manual; performance tilts at Tier 1 defeat the purpose.

Activation of the Sharpe overlay is governed by ADR-0008 §D3 (6 months of live data on 3+ strategies + bootstrap CI stability). This ADR does not re-specify the overlay; it simply notes that Tier 2 and Tier 3 are compatible substrates for it.

---

## 4. Mathematical specifications

### 4.1 Tier 1 — trivial

```
w_i = static_weight_i  (read from config/strategies.yaml)
Σ_i w_i + cash_buffer ≤ 1.0  (enforced by schema validator at load time)
```

No runtime computation. The YAML file is the specification.

### 4.2 Tier 2 — Risk Parity (inverse volatility, diagonal covariance)

Given daily return series `r_i[t]` for strategy `i` over the last 60 trading days:

```
μ_i         = mean(r_i[t-59:t])
σ_i         = sqrt( Σ_t (r_i[t] - μ_i)² / 59 )   # sample stdev, T-1 denominator
w_raw_i     = 1 / max(σ_i, σ_floor)               # σ_floor = 1e-6 guards /0
w_norm_i    = w_raw_i / Σ_j w_raw_j
w_clipped_i = clip( w_norm_i, min_weight, max_weight )
w_final_i   = w_clipped_i × (1 - cash_buffer) / Σ_j w_clipped_j
```

**Notes.**

- Annualisation is **not required** for the formula — `1/σ_daily` and `1/σ_annual` produce identical normalised weights because the annualisation constant (`sqrt(252)`) cancels in the ratio. `apex_strategy_metrics.sigma_annualized` is persisted for observability; the allocator can use either column.
- The clip-then-renormalise step is standard in Risk Parity implementations (AQR 2012 white paper §4). Without renormalisation after clipping, `Σ w_final < 1 - cash_buffer`, leaving unallocated capital.
- If a strategy's σ is unobservable (e.g., < 20 days of history), the strategy is **excluded** from the current rebalance and its share redistributes pro-rata. See §9.

**Worked example.** Three strategies, σ = (10%, 15%, 20%), cash_buffer = 20%:

```
w_raw     = (10.00, 6.67, 5.00)
w_norm    = (0.461, 0.308, 0.231)
w_clipped = (0.400, 0.308, 0.231)   # clipped at 40%
Σ w_clip  = 0.939
w_final   = (0.341, 0.262, 0.197)   # sums to 0.80 = 1 - cash_buffer
```

(Checked in the companion research doc §1 with the full 2-year simulation.)

### 4.3 Tier 3 — Hierarchical Risk Parity

The HRP algorithm is specified exhaustively in Lopez de Prado (2016) §2 with full pseudocode. Summary:

```
# Step 1: correlation and distance matrices
ρ    = corr(R)                                     # R = returns matrix, shape (T, N)
D    = sqrt(0.5 × (1 - ρ))                         # distance matrix, eq. 5

# Step 2: hierarchical clustering
link = scipy.cluster.hierarchy.linkage(D, method='ward')

# Step 3: quasi-diagonal order
order = get_quasi_diag(link)                       # recursive leaf extraction
D'    = D[order, :][:, order]

# Step 4: recursive bisection
w = recursive_bisection(cov=cov(R)[order][:,order], indices=order)
#   at each split point k:
#     left  = indices[:k]
#     right = indices[k:]
#     V_L   = inverse_variance_portfolio_variance(cov[left, left])
#     V_R   = inverse_variance_portfolio_variance(cov[right, right])
#     α     = 1 - V_L / (V_L + V_R)
#     w[left]  *= α
#     w[right] *= (1 - α)

# Step 5: clip + renormalise (same as Tier 2)
w = clip(w, min_weight, max_weight)
w = w × (1 - cash_buffer) / sum(w)
```

Lopez de Prado's companion code is published at Quantresearch.org (referenced from his SSRN papers). The APEX implementation will port it to asyncio and wrap it in the `BaseAllocator` interface, not reinvent it.

---

## 5. Rebalance mechanics

### 5.1 Tier 1 — no rebalance at runtime

Changes to Tier 1 weights require a commit to `config/strategies.yaml` and a service restart for every strategy whose weight changed. This is deliberate — Tier 1 is manual by design.

### 5.2 Tier 2 / Tier 3 — rebalance job

At the configured cadence (Tier 2: weekly Sunday 23:00 UTC; Tier 3: monthly first trading day), the allocator service:

1. Reads returns from `apex_strategy_metrics` for all active strategies.
2. Computes target weights per §4.2 (Tier 2) or §4.3 (Tier 3).
3. Applies the Sharpe overlay if ADR-0008 §D3 conditions hold.
4. Computes the **delta** between target and currently deployed capital per `portfolio:allocation:{strategy_id}` (Redis).
5. For each strategy where `|delta_i| > trigger_threshold_pct × portfolio_capital`:
   - Writes the new target to `portfolio:allocation:{strategy_id}`.
   - Publishes `portfolio.allocation.updated` on ZMQ.
   - The per-strategy sub-book (ADR-0012) subsequently emits `OrderCandidate` messages to bring positions to the new target.
6. For each strategy where `|delta_i| ≤ trigger_threshold_pct × portfolio_capital`, the rebalance is **skipped** for that strategy — Redis and ZMQ state is unchanged. This avoids trading noise.
7. Persists the full `AllocatorResult` (ADR-0008 §D8) to TimescaleDB `apex_allocation_history` (a new table introduced in a follow-up ADR; see §8).

### 5.3 Transition cost estimation

Before emitting rebalance orders, the allocator estimates the transition cost:

```
transition_cost_i = (half_spread_usd × |delta_notional_i|) + market_impact_i
market_impact_i   = k × |delta_notional_i|^1.5 / ADV_symbol   (Almgren-Chriss 2000)
```

where `k` is a per-asset constant calibrated from S06 execution telemetry. If the summed transition cost exceeds **20% of the expected incremental Sharpe contribution** from the rebalance, the rebalance is deferred to the next cycle with a Telemetry alert. This prevents the allocator from trading its own slippage.

### 5.4 Minimum delta threshold

`trigger_threshold_pct = 0.5%` of portfolio value per strategy. Below this threshold, the rebalance is skipped for that strategy — the weight in Redis stays at the previous value, and no orders are emitted. Rationale: small deltas are indistinguishable from σ estimation noise; acting on them churns the book for no expected alpha.

---

## 6. Configuration schema

### 6.1 Tier 1 YAML schema (authoritative)

```yaml
# config/strategies.yaml — Tier 1 static allocation
allocation_tier: static          # static | risk_parity | hrp
cash_buffer: 0.20                # 20% held as USD, not allocated
portfolio_capital_usd: 250000.00 # total capital under APEX management (reference only)

strategies:
  - id: legacy_confluence
    enabled: true
    weight: 0.50
    min_weight: 0.30             # lower bound when Tier >= 2 activates
    max_weight: 0.60             # upper bound when Tier >= 2 activates
    burn_in_days: 0              # established strategy; no burn-in
    capital_usd: 125000.00       # weight x portfolio_capital_usd (computed)

  - id: har_rv_momentum
    enabled: true
    weight: 0.30
    min_weight: 0.10
    max_weight: 0.40
    burn_in_days: 30             # new strategy; 30 days observation before adaptive

rebalance:
  policy: static                 # static | weekly | monthly
  weekly_day: sun
  weekly_time_utc: "23:00"       # aligned to ADR-0008 §D2
  monthly_day: 1
  trigger_threshold_pct: 0.5     # min weight change (%) before rebalance actually trades

blacklist:
  # strategies that failed a gate (CPCV PBO > 50%, PSR < 0.5, etc.) — weight forced to 0
  - id: experimental_mean_rev
    reason: "CPCV PBO = 62% on 2026-Q1 walk-forward; benched pending re-derivation"
    benched_since: "2026-04-01"
```

**Schema validation rules** (enforced by Pydantic loader at Tier 1 service startup):

- `sum(strategies[enabled].weight) + cash_buffer ≤ 1.0` (strict).
- `0 ≤ strategies[*].weight ≤ 1.0` per entry.
- `0 ≤ strategies[*].min_weight ≤ strategies[*].weight ≤ strategies[*].max_weight ≤ 1.0`.
- `cash_buffer ≥ 0.0`.
- `rebalance.trigger_threshold_pct > 0.0`.
- Every `strategies[*].id` is unique; blacklisted ids cannot also appear in the `strategies` list.

### 6.2 Tier 2 / Tier 3 additional fields

Tier 2 and Tier 3 use the same schema plus:

```yaml
allocation_tier: risk_parity    # or hrp

# Tier 2 / Tier 3 compute weights at runtime; the `weight` field above
# becomes the **seed** weight for the first rebalance and the **fallback**
# if the compute job fails.

compute:
  sigma_window_days: 60
  correlation_window_days: 60   # Tier 3 only
  linkage: ward                 # Tier 3 only: ward | single | complete
  sigma_floor: 0.000001         # numerical guard
  shadow_mode: false            # if true, compute + log + do NOT act
```

---

## 7. Migration path between tiers

Each tier change requires:

1. **ADR amendment** (or new ADR) formally authorising the transition.
2. **Feature flag** flipped in `config/strategies.yaml` (`allocation_tier: <new_tier>`).
3. **Shadow mode** enabled for **4 weeks** before the cutover (`compute.shadow_mode: true`). During shadow mode:
   - The new tier's compute job runs on its cadence and writes its would-be weights to `portfolio:allocation:shadow:{strategy_id}` (a separate Redis namespace).
   - The allocator publishes `portfolio.allocation.shadow` on ZMQ for observability.
   - The Telemetry stack records per-strategy deltas between current-tier and shadow-tier weights.
   - **No orders** are emitted from the shadow computation. The current tier continues to drive live allocation.
4. **Cutover criteria** (CIO-ratified):
   - Shadow-mode weights are stable (no single-strategy weight change > 10% week-over-week during the 4-week window).
   - No missing-data or numerical failures in the shadow compute job for 4 consecutive cycles.
   - The shadow tier's ex-ante Sharpe estimate (on a 30-day backtest replay) is ≥ the current tier's.
5. **Cutover execution**: flip `shadow_mode: false` + `allocation_tier: <new_tier>`, restart allocator service. The next scheduled rebalance acts on the new tier.
6. **Deprecation** of the previous tier: the old compute path is removed only after the new tier has run cleanly for **8 more weeks** post-cutover. Until then, the previous tier's code stays in the repo as a rollback target (guarded by the feature flag).

This shadow-then-cutover protocol is adapted from standard canary-deployment practice in production software, applied with the Sharpe-CI stability checks from ADR-0008 §D3.

---

## 8. Observability

Every rebalance emits the following telemetry:

- **Current weights per strategy_id**, persisted to TimescaleDB `apex_allocation_history` (schema: `rebalance_ts_utc TIMESTAMPTZ, strategy_id TEXT, tier TEXT, weight_target NUMERIC(20,8), weight_effective NUMERIC(20,8), sigma_60d NUMERIC(20,8), overlay_tilt NUMERIC(20,8) NULL, algorithm_metadata JSONB, PRIMARY KEY (rebalance_ts_utc, strategy_id)`). This table is additive to ADR-0014's 11 tables and will be introduced in a follow-up ADR that amends the schema.
- **Input data for the tier**: σ per strategy (Tier 2), correlation matrix and dendrogram structure (Tier 3), in `algorithm_metadata` JSONB.
- **Deltas from previous weights** — absolute and pct-of-portfolio per strategy.
- **Transition cost estimate** — total USD across the rebalance.
- **Rebalance duration** — wall-clock time from compute start to Redis write end.
- **Dashboard**: a new "Allocation" tab in `services/command_center/` showing:
  - Current weights per strategy (bar chart).
  - Weight history (time series per strategy, stacked).
  - Blacklist status with benched-since dates.
  - Shadow-mode delta panel during tier transitions.
  - Rebalance log (last 20 rebalances with status, delta, cost).

---

## 9. Failure modes

| Failure | Tier | Response |
|---|---|---|
| Strategy volatility spike (σ × 2 in 1 week) | Tier 2 | Risk Parity auto-reduces the strategy's weight via `1/σ`; the 40% ceiling on **other** strategies prevents runaway reallocation into a newly low-vol outlier. Emit `telemetry.allocator.vol_spike` for audit. |
| New strategy added (enabled=true, burn_in_days=30) | All | Strategy allocated at `min_weight` (5% by default) for the `burn_in_days` window. During burn-in, the strategy is **excluded** from the adaptive compute — its allocation is pinned at the floor until the timer elapses. Prevents a new strategy with no history from dominating via spuriously low σ. |
| Strategy blacklisted (CPCV PBO > 50%, PSR < 0.5, 3 consecutive DD breaches) | All | `weight = 0`; the strategy's share is redistributed pro-rata to active strategies. The blacklist entry persists in `config/strategies.yaml`. Reactivation requires a fresh Gate 2 PR (Playbook §9). |
| Correlation matrix singular (Tier 3) | Tier 3 | Fallback to Tier 2 Risk Parity for that rebalance cycle; emit `telemetry.allocator.hrp_fallback`. If singular for ≥ 3 consecutive cycles, raise a CIO alert. |
| Missing data in `apex_strategy_metrics` for active strategy | All | If < 20 days of history, strategy is excluded from the rebalance (as if disabled). If 20–60 days, strategy is included at `min_weight`. Alert raised via Telemetry `apex.metrics.missing_for_allocation`. |
| Allocator compute job fails (exception, timeout) | Tier 2 / 3 | Weights in Redis remain at previous values — **fail-static**, not fail-closed, consistent with ADR-0008 §3.3. The Risk Manager's 7-step chain continues to read the last-written allocation. A CIO pager alert fires. |
| Hard circuit breaker trips globally | All | Allocator publishes `portfolio.allocation.suspended` on ZMQ and skips the rebalance. See ADR-0008 §D6. |

---

## 10. References

### 10.1 Academic

- Qian, E. (2005). "Risk Parity Portfolios: Efficient Portfolios Through True Diversification." *PanAgora Asset Management white paper.* [Foundational Risk Parity publication.]
- Maillard, S., Roncalli, T., & Teiletche, J. (2010). "The Properties of Equally Weighted Risk Contribution Portfolios." *Journal of Portfolio Management* 36(4), 60–70. [Formal ERC specification; diagonal-covariance simplification.]
- Lopez de Prado, M. (2016). "Building Diversified Portfolios That Outperform Out of Sample." *Journal of Portfolio Management* 42(4), 59–69. [Hierarchical Risk Parity original paper; out-of-sample superiority demonstrated via Monte Carlo.]
- Lopez de Prado, M. (2020). *Machine Learning for Asset Managers.* Cambridge University Press. [Chapter 4 expands HRP with NCO (Nested Clustered Optimisation) extensions; parked for future tier.]
- Kelly, J. L. (1956). "A New Interpretation of Information Rate." *Bell System Technical Journal* 35(4), 917–926. [Referenced for future Tier 4 Kelly meta-allocation; see §10.2 below — parked.]
- Lo, A. W. (2002). "The Statistics of Sharpe Ratios." *Financial Analysts Journal* 58(4), 36–52. [Sharpe estimation uncertainty; motivates the 4-week shadow window.]
- Michaud, R. O. (1989). "The Markowitz Optimization Enigma." *Financial Analysts Journal* 45(1), 31–42. [Estimation-error critique motivating rejection of MVO — see companion research doc §3.]
- Almgren, R., & Chriss, N. (2000). "Optimal Execution of Portfolio Transactions." *Journal of Risk* 3, 5–39. [Transition-cost model used in §5.3.]
- Clarke, R., de Silva, H., & Thorley, S. (2011). "Minimum-Variance Portfolio Composition." *Journal of Portfolio Management* 37(2), 31–45. [Concentration failure mode of unconstrained vol-minimisation; motivates floor + ceiling.]
- MacLean, L. C., Thorp, E. O., & Ziemba, W. T. (eds.) (2011). *The Kelly Capital Growth Investment Criterion: Theory and Practice.* World Scientific. [Survey motivating Kelly meta-allocation being parked as Tier 4.]
- Black, F., & Litterman, R. (1992). "Global Portfolio Optimization." *Financial Analysts Journal* 48(5), 28–43. [Operator-view extension contemplated as future ADR.]

### 10.2 Parked for future ADRs

- **Kelly meta-allocation** (Kelly 1956; MacLean, Thorp & Ziemba 2011) — an aggressive, leverage-maximising allocation that sizes each strategy by its expected growth rate. Noted as a future Tier 4 candidate; rejected for Tier 3 on the grounds that Kelly is extraordinarily sensitive to input noise (Kelly fraction > 1 is routinely produced by noisy Sharpe estimates, inducing ruinous leverage).
- **Regime-conditional allocation** — different weights per S03 RegimeDetector regime (risk-on vs risk-off). Plausible Phase 6+ extension.
- **Black-Litterman overlay** (Black & Litterman 1992) — allows operator views to be incorporated as prior beliefs. Useful once APEX has 10+ strategies and the operator develops conviction views.

### 10.3 Internal

- [ADR-0007 — Strategy as Microservice](ADR-0007-strategy-as-microservice.md)
- [ADR-0008 — Capital Allocator Topology](ADR-0008-capital-allocator-topology.md)
- ADR-0012 — Multi-Strategy Order Netting *(sub-books receive the capital allocated here; authored in parallel on `docs/adr-0012-multi-strat-netting`)*
- [ADR-0014 — TimescaleDB Schema v2](ADR-0014-timescaledb-schema-v2.md) *(`apex_strategy_metrics` is the input data source)*
- [Charter §5.5 — per-strategy identity](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md)
- [Charter §6 — Capital Allocation Framework](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md)
- [Phase 5 v3 Roadmap](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md)
- [Companion research: docs/research/CAPITAL_ALLOCATION_TRAJECTORY.md](../research/CAPITAL_ALLOCATION_TRAJECTORY.md)
- [Sample config: config/strategies.example.yaml](../../config/strategies.example.yaml)

---

## 11. Consequences

### 11.1 Positive

- **Complexity grows only when justified.** Tier 1 ships with Gate 2; Tier 2 is deferred until live data exists; Tier 3 is deferred until cross-strategy correlations become material. No premature optimisation.
- **Gate 2 unblocked on day 1.** Tier 1 is trivial — a YAML loader. Strategy #1 can reach Gate 2 paper without waiting for the allocator service to exist. Roadmap §3 Phase B can ship.
- **Blacklist mechanism makes the gates operational.** CPCV PBO > 50% and PSR < 0.5 are already Charter requirements (Charter §7.2 Gate 2 criteria); the `blacklist:` section of the YAML is the mechanism that makes them bite — a strategy that fails a gate has weight forced to 0 until a CIO-ratified reactivation commit.
- **Shadow-mode cutover is paranoid by design.** 4 weeks of shadow + 8 weeks post-cutover rollback-readiness protects against algorithmic surprise. The cost is latency on tier upgrades; the benefit is that a bad upgrade cannot silently destroy the book.
- **Aligns with published institutional practice.** Qian 2005 → Maillard/Roncalli/Teiletche 2010 → Lopez de Prado 2016 is the canonical trajectory of multi-strat capital allocation at quant firms over the last 20 years.

### 11.2 Negative

- **Tier 2 and Tier 3 hinge on the quality of `apex_strategy_metrics`.** If S09 FeedbackLoop's persistence is incorrect (e.g., daily returns are computed wrong, or the aggregation job silently drops rows during a DB failover), the allocator silently produces wrong weights. Mitigated by CI invariants on `apex_strategy_metrics` and a daily reconciliation job (to be specified in a follow-up ADR).
- **Four tables of dependency** — `apex_strategy_metrics`, `apex_allocation_history`, `apex_risk_limits`, `portfolio:allocation:{strategy_id}` (Redis) — must all be in sync. Schema drift between ADR-0014's tables and the follow-up `apex_allocation_history` table is a real risk.
- **Tier transitions are expensive in shadow time.** 12 weeks total (4 shadow + 8 post-cutover stability) per transition. Two transitions (Tier 1→2 and Tier 2→3) = 24 weeks of operational overhead. This is the price of stability.
- **ADR-0008 alignment required** — any future drift between this ADR and ADR-0008 must be reconciled by amendment. The binding-precedence rule says ADR-0008 prevails on topology; this ADR prevails on algorithmic trajectory. Any genuine conflict is an escalation to the CIO.

### 11.3 Mitigations

- The CI gate on `apex_strategy_metrics` freshness (daily row count ≥ expected, no gaps > 48h) is a proposed addition to the allocator's startup checks. To be specified alongside the `apex_allocation_history` table in the follow-up ADR.
- The rollback path from any tier transition is a single `config/strategies.yaml` edit (`allocation_tier:` flag) + service restart. The previous tier's compute code remains in the repo for 8 weeks post-cutover specifically to enable this.

---

## 12. Implementation plan (mapped to Phase Gates)

| Phase | Tier | Deliverables | Estimate |
|---|---|---|---|
| Phase B (weeks 6–14) | Tier 1 | (i) YAML schema + Pydantic loader in `core/config/strategies.py`. (ii) Per-strategy `capital_usd` field consumed by each strategy's sub-book (ADR-0012). (iii) `make-strategy-yaml-validate` CI gate. (iv) Strategy #1 Gate 2 PR includes a valid `config/strategies.yaml`. | ~1 sprint |
| Phase C (weeks 14–22) | Tier 2 | (i) `services/portfolio/strategy_allocator/` microservice scaffolding (per ADR-0008 §5.1). (ii) `risk_parity.py` per §4.2 of this ADR. (iii) Weekly Sunday 23:00 UTC rebalance scheduler (asyncio). (iv) `apex_allocation_history` TimescaleDB table (follow-up ADR). (v) 4-week shadow-mode evaluation before cutover. (vi) Tier 2 cutover on Strategy #1 Gate 3 entry + 2nd active strategy. | ~2 sprints |
| Phase C+ / Phase D (weeks 22+) | Tier 3 | (i) `risk_parity_hrp.py` implementing Lopez de Prado 2016 §2 verbatim, with property tests reproducing Table 1. (ii) Correlation matrix compute job (daily). (iii) Monthly rebalance scheduler. (iv) "Allocation" dashboard tab upgraded to show HRP dendrogram + clusters. (v) 4-week shadow + 8-week post-cutover stability window. (vi) Cutover contingent on Tier 2 exit criteria (§3.2). | ~3–4 sprints |

### 12.1 Acceptance tests per tier

- **Tier 1**: given `config/strategies.yaml` with three strategies summing to 80% + 20% cash buffer, the loader returns a validated object; an invalid file (sum > 1.0, duplicate ids, missing fields) raises `ValidationError` with a descriptive message.
- **Tier 2**: given σ = (10%, 15%, 20%) and cash_buffer = 0.20, the allocator returns w = (0.341, 0.262, 0.197) ± 1e-6 (worked example §4.2). Property test: for any valid σ vector, `Σ w + cash_buffer ≤ 1.0` and `min_weight ≤ w_i ≤ max_weight` for every i.
- **Tier 3**: the Lopez de Prado 2016 Table 1 example (10 simulated assets) is reproduced by `risk_parity_hrp.py` within Decimal tolerance 1e-6. Property test: for any correlation matrix with spectral decomposition eigenvalues ≥ 0, HRP returns a valid weight vector (no NaNs, sum ≤ 1 - cash_buffer, per-strategy caps respected).

---

**END OF ADR-0013.**
