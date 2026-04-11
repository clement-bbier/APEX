# Phase 3 — Feature Validation Harness: Complete Specification

**Version**: 1.0
**Date**: 2026-04-11
**Author**: Claude Opus 4.6 (orchestrated by Clement Barbier)
**Status**: APPROVED — Gate for Phase 3.1 execution
**Issue**: #61
**Supersedes**: PROJECT_ROADMAP.md Section 5 Phase 3 (indicative sub-phases)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Sub-Phase Specifications (3.1 -- 3.13)](#2-sub-phase-specifications)
3. [Architecture](#3-architecture)
4. [SOLID Principles and Design Patterns](#4-solid-principles-and-design-patterns)
5. [Anti-Patterns in Signal Validation](#5-anti-patterns-in-signal-validation)
6. [Persistent Claude Memory System](#6-persistent-claude-memory-system)
7. [Managed Agents for Phase 3](#7-managed-agents-for-phase-3)
8. [Tier-1 Tooling Evaluation](#8-tier-1-tooling-evaluation)
9. [Execution Roadmap](#9-execution-roadmap)
10. [Decision Matrix: Cleared for Phase 3.1](#10-decision-matrix-cleared-for-phase-31)
11. [Bibliography](#11-bibliography)

---

## 1. Executive Summary

### Why Phase 3 exists

Lopez de Prado (2018, Ch. 1) establishes that **80% of quantitative strategies validated
naively fail out-of-sample**. The primary causes are backtest overfitting (Bailey et al.,
2014), selection bias under multiple testing (Harvey, Liu & Zhu, 2016), and failure to
measure genuine predictive power before deployment.

APEX currently has six candidate alpha features scaffolded in S02 (Signal Engine) and
S07 (Quant Analytics): HAR-RV, Rough Volatility, OFI, CVD, Kyle lambda, and GEX. None
of these have been scientifically validated on real data. Phase 3 builds the **Feature
Validation Harness** -- an offline pipeline that measures the Information Coefficient (IC),
stability, multicollinearity, and statistical significance of every feature before it is
allowed to influence live trading decisions.

### What Phase 3 produces

- A **Feature Engineering Pipeline** that computes features from Phase 2 historical data.
- A **Feature Store** for versioned, reproducible feature sets.
- **IC measurement** (Spearman rank IC, IC_IR, turnover-adjusted IC) per feature.
- **Individual validation** of each of the 6 alpha features against academic benchmarks.
- **Multicollinearity analysis** and orthogonalization (VIF, PCA, clustering).
- **CPCV with purging** (Combinatorial Purged Cross-Validation) for robust OOS testing.
- **Multiple hypothesis testing** (DSR, PBO) to avoid selection bias.
- A **final feature selection report** with keep/reject decisions.
- **Integration scaffolding** for wiring validated features into S02 Signal Engine.

### What Phase 3 does NOT produce

- No live trading changes. S02 is not modified beyond adding feature stubs.
- No backtesting engine (that is Phase 5).
- No regime detection logic (that is Phase 4).
- No execution logic changes.

### Scope and duration

- **13 sub-phases** (3.1 through 3.13), sequenced with explicit dependencies.
- **Estimated duration**: 3-4 weeks for a single developer with Claude Code assistance.
- **Test coverage target**: 85% minimum per sub-phase (CI-enforced).

### Gate prerequisites (all met)

| Prerequisite | Status | Reference |
|---|---|---|
| Phase 2 merged (all data sources) | DONE | PR #37--#62 |
| Whole-codebase audit CLEARED | YES (0 P0) | #55, `docs/audits/AUDIT_2026_04_11_WHOLE_CODEBASE.md` |
| Meta-governance audit CLEARED | YES (3 P0 docs) | #59, `docs/audits/META_AUDIT_2026_04_11_GOVERNANCE.md` |
| ADR-0002 Quant Methodology Charter | ACCEPTED | `docs/adr/0002-quant-methodology-charter.md` |
| 1,283 tests passing | YES | 1,228 unit + 55 integration |
| mypy strict zero errors | YES | 319 files |

---

## 2. Sub-Phase Specifications

---

### 2.1 Phase 3.1 -- Feature Engineering Pipeline Foundation

#### A.1 Identifier

| Field | Value |
|---|---|
| Number | 3.1 |
| Title | Feature Engineering Pipeline Foundation |
| Objective | Build the core pipeline that transforms raw market data (bars, ticks) from Phase 2 into feature vectors suitable for IC measurement |

#### A.2 Justification

The Fundamental Law of Active Management (Grinold & Kahn, 1999) states that portfolio
performance is proportional to the Information Coefficient (IC) multiplied by the square
root of the number of independent bets. Before measuring IC, we need a repeatable pipeline
that computes features from raw data without look-ahead bias.

Lopez de Prado (2018, Ch. 3-5) emphasizes that feature engineering for financial time
series requires special handling: fractional differentiation to preserve memory while
achieving stationarity, proper labeling (triple-barrier method), and sample weighting
to account for overlapping returns.

#### A.3 Dependencies

| Dependency | Type | Source |
|---|---|---|
| None | First sub-phase | -- |
| Phase 2 historical data | Data | TimescaleDB bars table (ADR-0003) |
| S07 `RealizedVolEstimator` | Code (read-only) | `services/s07_quant_analytics/realized_vol.py` |
| S07 `AdvancedMicrostructure` | Code (read-only) | `services/s07_quant_analytics/microstructure_adv.py` |
| S07 `RoughVolAnalyzer` | Code (read-only) | `services/s07_quant_analytics/rough_vol.py` |
| `core/models/data.py` | Models | `Bar`, `Asset`, `DbTick` |
| `core/math/` | Math utils | Fractional differentiation, labeling |

#### A.4 Technical deliverables

**Files to create:**

| Path | Purpose |
|---|---|
| `features/__init__.py` | Package init |
| `features/pipeline.py` | `FeaturePipeline` class -- orchestrates feature computation |
| `features/base.py` | `FeatureCalculator` ABC -- interface all feature calculators implement |
| `features/labels.py` | `TripleBarrierLabeler` -- label generation (Lopez de Prado Ch. 3) |
| `features/weights.py` | `SampleWeighter` -- uniqueness-weighted samples (Lopez de Prado Ch. 4) |
| `features/fracdiff.py` | Wrapper around `core/math/fractional_diff.py` for pipeline use |
| `tests/unit/test_feature_pipeline.py` | Pipeline unit tests |
| `tests/unit/test_labels.py` | Label unit tests |
| `tests/unit/test_weights.py` | Sample weight unit tests |

**Key signatures:**

```python
from abc import ABC, abstractmethod
from decimal import Decimal
import polars as pl

class FeatureCalculator(ABC):
    """Base class for all feature calculators.

    Every feature calculator takes a polars DataFrame of bars/ticks and returns
    a polars DataFrame with computed feature columns.

    Reference: Grinold & Kahn (1999) Active Portfolio Management, Ch. 14.
    """

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def compute(self, df: pl.DataFrame) -> pl.DataFrame: ...

    @abstractmethod
    def required_columns(self) -> list[str]: ...

    @abstractmethod
    def output_columns(self) -> list[str]: ...


class FeaturePipeline:
    """Orchestrates feature computation from raw data to feature matrix.

    Reference: Lopez de Prado (2018) Ch. 3-5.
    """

    def __init__(
        self,
        calculators: list[FeatureCalculator],
        labeler: TripleBarrierLabeler,
        weighter: SampleWeighter,
    ) -> None: ...

    async def run(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        bar_size: str = "5m",
    ) -> pl.DataFrame: ...
```

**Tests minimum**: 25 unit tests, 85% coverage on `features/`.

**Documentation**: Docstrings with references on every public method.

#### A.5 Success metrics

| Metric | Target |
|---|---|
| Pipeline processes 1 year of 5m bars for 1 symbol | < 30 seconds |
| Output DataFrame has no NaN in feature columns (after warm-up) | 0 NaN |
| Triple-barrier labels produce balanced-ish classes | 30-70% positive |
| Sample weights sum to effective N (uniqueness > 0.5) | Verified |
| Unit test coverage | >= 85% |

#### A.6 Risks

| Risk | Mitigation |
|---|---|
| Look-ahead bias in label computation | Triple-barrier uses only past data; embargo period added |
| Insufficient historical data for warm-up | Require minimum 500 bars before first label |
| Fractional diff parameters hard to tune | Use ADF test to find minimum d for stationarity (Lopez de Prado Ch. 5) |

#### A.7 References

1. Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*, Ch. 3-5. Wiley.
2. Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio Management* (2nd ed.), Ch. 14. McGraw-Hill.
3. Hosking, J. R. M. (1981). "Fractional differencing". *Biometrika*, 68(1), 165-176.
4. Politis, D. N. & Romano, J. P. (1994). "The Stationary Bootstrap". *JASA*, 89(428), 1303-1313.
5. Cont, R. (2001). "Empirical properties of asset returns: stylized facts and statistical issues". *Quantitative Finance*, 1(2), 223-236.

#### A.8 Effort estimate

| Field | Value |
|---|---|
| Duration | 2-3 days |
| Complexity | M |
| Uncertainty | Low (well-documented approach) |

---

### 2.2 Phase 3.2 -- Feature Store Architecture

#### A.1 Identifier

| Field | Value |
|---|---|
| Number | 3.2 |
| Title | Feature Store Architecture |
| Objective | Implement a versioned, reproducible feature storage layer that prevents look-ahead bias and enables time-travel queries |

#### A.2 Justification

A Feature Store is critical for reproducible quantitative research (Sculley et al., 2015).
Without it, feature computation is ad-hoc, non-reproducible, and prone to subtle data
leakage. The store must support point-in-time queries: "what features were available at
time T?" -- because any feature computed from data after T would introduce look-ahead bias.

Feast (Tecton open-source) and custom solutions are the two viable paths. Given APEX is
a single-operator system, a lightweight custom solution built on TimescaleDB + Polars
is preferred over a heavy Feast deployment.

#### A.3 Dependencies

| Dependency | Type | Source |
|---|---|---|
| Phase 3.1 | Pipeline | `features/pipeline.py` |
| TimescaleDB | Infrastructure | Phase 2 (ADR-0003) |
| Redis | Cache | Existing infrastructure |

#### A.4 Technical deliverables

**Files to create:**

| Path | Purpose |
|---|---|
| `features/store.py` | `FeatureStore` -- Repository pattern for feature persistence |
| `features/registry.py` | `FeatureRegistry` -- Metadata catalog of available features |
| `features/versioning.py` | `FeatureVersion` -- Immutable version tracking |
| `tests/unit/test_feature_store.py` | Store unit tests |

**Key signatures:**

```python
class FeatureStore:
    """Repository for versioned feature data.

    Implements the Repository Pattern (Fowler, 2002) for feature persistence.
    Point-in-time queries prevent look-ahead bias.

    Reference: Sculley et al. (2015) "Hidden Technical Debt in ML Systems", NIPS.
    """

    async def save(
        self,
        symbol: str,
        features: pl.DataFrame,
        version: str,
        computed_at: datetime,
    ) -> None: ...

    async def load(
        self,
        symbol: str,
        feature_names: list[str],
        start: datetime,
        end: datetime,
        as_of: datetime | None = None,  # point-in-time query
    ) -> pl.DataFrame: ...

    async def list_versions(self, symbol: str) -> list[FeatureVersion]: ...
```

**Tests minimum**: 15 unit tests (using FakeRedis + mock DB), 85% coverage.

#### A.5 Success metrics

| Metric | Target |
|---|---|
| Point-in-time query returns only features computed before as_of | Verified |
| Feature version is immutable (re-computation creates new version) | Verified |
| Load 1 year of features for 1 symbol | < 5 seconds |
| Registry lists all available features with metadata | Verified |

#### A.6 Risks

| Risk | Mitigation |
|---|---|
| Schema evolution as features change | Version features; never mutate existing versions |
| Storage bloat from multiple versions | Retention policy: keep last 5 versions per symbol |
| Feast adds operational complexity | Use custom lightweight solution instead |

#### A.7 References

1. Sculley, D. et al. (2015). "Hidden Technical Debt in Machine Learning Systems". *NeurIPS*, 2503-2511.
2. Fowler, M. (2002). *Patterns of Enterprise Application Architecture*, Ch. 10. Addison-Wesley.
3. Kleppmann, M. (2017). *Designing Data-Intensive Applications*, Ch. 11. O'Reilly.

#### A.8 Effort estimate

| Field | Value |
|---|---|
| Duration | 2 days |
| Complexity | M |
| Uncertainty | Low |

---

### 2.3 Phase 3.3 -- Information Coefficient Measurement

#### A.1 Identifier

| Field | Value |
|---|---|
| Number | 3.3 |
| Title | Information Coefficient Measurement |
| Objective | Build the IC measurement framework that quantifies the predictive power of every feature |

#### A.2 Justification

The Information Coefficient (IC) is the Spearman rank correlation between a feature's
predicted signal and the subsequent realized return. It is the single most important
metric for evaluating alpha features (Grinold & Kahn, 1999, Ch. 6).

The Fundamental Law of Active Management: IR = IC * sqrt(BR), where IR is the
Information Ratio, IC is the Information Coefficient, and BR is the breadth (number of
independent forecasts). A feature with |IC| < 0.02 is typically noise.

IC alone is insufficient. We also need:
- **IC_IR** (IC Information Ratio): mean(IC) / std(IC) -- measures IC stability.
- **Turnover-adjusted IC**: penalizes features whose IC is high but require excessive
  rebalancing (Grinold & Kahn, 1999, Ch. 16).
- **IC decay**: how fast the feature's IC degrades over the forecast horizon.

#### A.3 Dependencies

| Dependency | Type | Source |
|---|---|---|
| Phase 3.1 | Pipeline | Feature vectors |
| Phase 3.2 | Store | Versioned features for reproducibility |

#### A.4 Technical deliverables

**Files to create:**

| Path | Purpose |
|---|---|
| `features/ic.py` | `ICMeasurer` -- IC computation engine |
| `features/ic_report.py` | `ICReport` -- Structured report generation |
| `tests/unit/test_ic.py` | IC measurement unit tests |
| `tests/unit/test_ic_report.py` | Report format tests |

**Key signatures:**

```python
@dataclass(frozen=True)
class ICResult:
    """Result of IC measurement for a single feature.

    Reference: Grinold & Kahn (1999), Ch. 6.
    """
    feature_name: str
    ic_mean: float           # Mean Spearman rank IC
    ic_std: float            # IC standard deviation
    ic_ir: float             # IC / std(IC) -- stability measure
    ic_t_stat: float         # t-statistic for IC != 0
    ic_hit_rate: float       # % of periods with correct sign
    turnover_adj_ic: float   # IC penalized by feature turnover
    ic_decay: list[float]    # IC at horizons [1, 5, 10, 20] bars
    n_observations: int
    is_significant: bool     # t-stat > 1.96


class ICMeasurer:
    """Measures the Information Coefficient of features.

    Uses Spearman rank correlation between feature values at time t
    and forward returns at time t+h.

    Reference: Grinold & Kahn (1999) Ch. 6, 16.
    """

    def measure(
        self,
        features: pl.DataFrame,
        forward_returns: pl.Series,
        horizon_bars: int = 1,
    ) -> ICResult: ...

    def measure_all(
        self,
        feature_matrix: pl.DataFrame,
        forward_returns: pl.Series,
        horizons: list[int] = [1, 5, 10, 20],
    ) -> list[ICResult]: ...

    def rolling_ic(
        self,
        features: pl.DataFrame,
        forward_returns: pl.Series,
        window: int = 252,
    ) -> pl.DataFrame: ...
```

**Tests minimum**: 20 unit tests including Hypothesis property tests for IC bounds [-1, +1].

#### A.5 Success metrics

| Metric | Target |
|---|---|
| IC computation for 1 feature on 3 years of data | < 10 seconds |
| IC values are in [-1, +1] | Always (property test with 1000 examples) |
| IC_IR matches manual computation on synthetic data | Exact match |
| Rolling IC produces time series of correct length | window-adjusted |
| IC report is machine-readable (JSON + Markdown) | Both formats |

#### A.6 Risks

| Risk | Mitigation |
|---|---|
| Low IC does not mean no alpha (non-linear signals) | Document limitation; consider mutual information in Phase 11 |
| IC inflated by autocorrelated returns | Use purged/embargoed returns (linked to Phase 3.10) |
| Turnover adjustment penalizes high-frequency features | Allow configurable turnover cost assumption |

#### A.7 References

1. Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio Management* (2nd ed.), Ch. 6, 14, 16. McGraw-Hill.
2. Qian, E., Hua, R. & Sorensen, E. (2007). *Quantitative Equity Portfolio Management*. Chapman & Hall/CRC.
3. Gu, S., Kelly, B. & Xiu, D. (2020). "Empirical Asset Pricing via Machine Learning". *Review of Financial Studies*, 33(5), 2223-2273. DOI: 10.1093/rfs/hhaa009.
4. Israel, R., Kelly, B. T. & Moskowitz, T. J. (2020). "Can Machines 'Learn' Finance?". *Journal of Investment Management*, 18(2), 23-36.
5. Kakushadze, Z. (2016). "101 Formulaic Alphas". *Wilmott*, 2016(84), 72-81.

#### A.8 Effort estimate

| Field | Value |
|---|---|
| Duration | 2-3 days |
| Complexity | M |
| Uncertainty | Low |

---

### 2.4 Phase 3.4 -- HAR-RV Validation

#### A.1 Identifier

| Field | Value |
|---|---|
| Number | 3.4 |
| Title | HAR-RV Validation |
| Objective | Validate the Heterogeneous Autoregressive Realized Volatility model as a predictive feature for APEX |

#### A.2 Justification

The HAR-RV model (Corsi, 2009) decomposes realized volatility into daily, weekly, and
monthly components, capturing the heterogeneous behavior of market participants at
different time horizons. It is the most widely used realized volatility forecasting
model in empirical finance.

S07 already implements `har_rv_forecast()` in `realized_vol.py`, which returns
`HARForecast` with `beta_daily`, `beta_weekly`, `beta_monthly`, and `r_squared`. Phase 3.4
validates whether this forecast has genuine predictive IC on APEX's target assets.

The HAR-RV model:
```
RV_{t+1} = beta_0 + beta_D * RV_t^{(d)} + beta_W * RV_t^{(w)} + beta_M * RV_t^{(m)} + epsilon
```

Where RV^{(d)}, RV^{(w)}, RV^{(m)} are daily, weekly (5-day average), and monthly
(22-day average) realized volatilities, respectively.

#### A.3 Dependencies

| Dependency | Type | Source |
|---|---|---|
| Phase 3.1 | Pipeline | Feature pipeline |
| Phase 3.2 | Store | Feature store |
| Phase 3.3 | IC | IC measurement framework |
| S07 `RealizedVolEstimator` | Existing code | `har_rv_forecast()`, `realized_variance()`, `bipower_variation()` |
| Phase 2 historical data | Data | 5m and 1d bars for BTC, ETH, SPY, QQQ |

#### A.4 Technical deliverables

**Files to create:**

| Path | Purpose |
|---|---|
| `features/calculators/har_rv.py` | `HARRVCalculator(FeatureCalculator)` |
| `features/validation/har_rv_report.py` | HAR-RV specific validation report |
| `tests/unit/test_har_rv_calculator.py` | Unit tests with known-result verification |

**Key signatures:**

```python
class HARRVCalculator(FeatureCalculator):
    """HAR-RV feature calculator.

    Computes HAR-RV forecast residuals and regime signals from realized
    volatility data. The forecast error (RV_actual - RV_forecast) is
    used as a predictive feature: negative residuals indicate unexpectedly
    low volatility (potential breakout), positive residuals indicate
    unexpectedly high volatility (potential mean-reversion opportunity).

    Reference: Corsi, F. (2009). "A Simple Approximate Long-Memory Model
    of Realized Volatility". Journal of Financial Econometrics, 7(2), 174-196.
    """

    def name(self) -> str:
        return "har_rv"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        """Adds columns: har_rv_forecast, har_rv_residual, har_rv_signal."""
        ...
```

**Tests minimum**: 15 unit tests.

- Verify HAR-RV forecast against manually computed values from Corsi (2009) Table 2.
- Hypothesis property tests: forecast is always non-negative (realized variance >= 0).
- Verify signal output is in [-1, +1].

#### A.5 Success metrics

| Metric | Target |
|---|---|
| IC of har_rv_signal on 3-year crypto data | Report (accept if \|IC\| > 0.02, IC_IR > 0.5) |
| IC of har_rv_signal on 3-year equity data | Report (accept if \|IC\| > 0.02, IC_IR > 0.5) |
| HAR-RV R-squared on BTC 5m data | Report (literature benchmark: 0.3-0.6 for daily) |
| IC stability across rolling windows | IC_IR > 0.5 |
| Computation latency per symbol | < 5 seconds for 3 years |

#### A.6 Risks

| Risk | Mitigation |
|---|---|
| HAR-RV designed for daily data, not 5m | Test on both 5m and daily; report IC for each |
| Jump component distorts RV | Use bipower variation (Barndorff-Nielsen & Shephard, 2004) as robustness check |
| Crypto vol structure differs from equities | Run validation separately per asset class; allow different conclusions |

#### A.7 References

1. Corsi, F. (2009). "A Simple Approximate Long-Memory Model of Realized Volatility". *Journal of Financial Econometrics*, 7(2), 174-196. DOI: 10.1093/jjfinec/nbp001.
2. Andersen, T. G., Bollerslev, T., Diebold, F. X. & Labys, P. (2003). "Modeling and Forecasting Realized Volatility". *Econometrica*, 71(2), 579-625.
3. Barndorff-Nielsen, O. E. & Shephard, N. (2004). "Power and Bipower Variation with Stochastic Volatility and Jumps". *Journal of Financial Econometrics*, 2(1), 1-37.
4. Patton, A. J. & Sheppard, K. (2015). "Good Volatility, Bad Volatility: Signed Jumps and the Persistence of Volatility". *Review of Economics and Statistics*, 97(3), 683-697.
5. Bollerslev, T., Patton, A. J. & Quaedvlieg, R. (2016). "Exploiting the Errors: A Simple Approach for Improved Volatility Forecasting". *Journal of Econometrics*, 192(1), 1-18.

#### A.8 Effort estimate

| Field | Value |
|---|---|
| Duration | 2 days |
| Complexity | M |
| Uncertainty | Medium (IC outcome unknown) |

---

### 2.5 Phase 3.5 -- Rough Volatility Validation

#### A.1 Identifier

| Field | Value |
|---|---|
| Number | 3.5 |
| Title | Rough Volatility Validation |
| Objective | Validate the Rough Volatility framework as a predictive feature for APEX |

#### A.2 Justification

Gatheral, Jaisson & Rosenbaum (2018) demonstrated that log-volatility behaves like a
fractional Brownian motion with Hurst exponent H ~ 0.1, far below the 0.5 of classical
models. This "roughness" has profound implications for trading: rough volatility regimes
exhibit different mean-reversion characteristics than classical regimes.

S07 already implements `estimate_hurst_from_vol()` in `rough_vol.py`, which returns a
`RoughVolSignal` with `hurst_exponent`, `is_rough`, `scalping_edge_score`, `vol_regime`,
and `size_adjustment`. S07 also provides `variance_ratio_test()` from Lo & MacKinlay (1988).

Phase 3.5 validates whether these rough volatility features have genuine predictive power.

#### A.3 Dependencies

| Dependency | Type | Source |
|---|---|---|
| Phase 3.1 | Pipeline | Feature pipeline |
| Phase 3.3 | IC | IC measurement |
| S07 `RoughVolAnalyzer` | Existing code | `estimate_hurst_from_vol()`, `variance_ratio_test()` |
| Phase 2 historical data | Data | 5m bars for BTC, ETH, SPY, QQQ |

#### A.4 Technical deliverables

**Files to create:**

| Path | Purpose |
|---|---|
| `features/calculators/rough_vol.py` | `RoughVolCalculator(FeatureCalculator)` |
| `features/validation/rough_vol_report.py` | Rough vol validation report |
| `tests/unit/test_rough_vol_calculator.py` | Unit tests |

**Key signatures:**

```python
class RoughVolCalculator(FeatureCalculator):
    """Rough volatility feature calculator.

    Computes Hurst exponent of log-volatility via the methodology of
    Gatheral, Jaisson & Rosenbaum (2018). When H < 0.3, the vol process
    is 'rough' and scalping opportunities arise from faster-than-expected
    mean-reversion in volatility.

    Also computes the Lo-MacKinlay (1988) variance ratio as a complementary
    feature for momentum vs. mean-reversion detection.

    Reference: Gatheral, J., Jaisson, T. & Rosenbaum, M. (2018).
    "Volatility is rough". Quantitative Finance, 18(6), 933-949.
    """

    def name(self) -> str:
        return "rough_vol"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        """Adds: rough_hurst, rough_is_rough, rough_scalping_score,
        rough_size_adj, variance_ratio, vr_signal."""
        ...
```

**Tests minimum**: 12 unit tests.

#### A.5 Success metrics

| Metric | Target |
|---|---|
| Hurst exponent on BTC 5m vol | Report (literature: H ~ 0.1 for liquid assets) |
| IC of rough_scalping_score | Report (accept if \|IC\| > 0.02) |
| IC of variance_ratio signal | Report (accept if \|IC\| > 0.02) |
| Variance ratio = 1.0 on random walk synthetic data | Verified (property test) |

#### A.6 Risks

| Risk | Mitigation |
|---|---|
| Hurst estimation unstable with short windows | Require minimum 100 realized vol observations |
| Rough vol theory mainly validated on SPX options | Test on BTC and ETH separately; be honest if crypto results differ |
| Variance ratio test has low power in small samples | Use at least 500 observations |

#### A.7 References

1. Gatheral, J., Jaisson, T. & Rosenbaum, M. (2018). "Volatility is rough". *Quantitative Finance*, 18(6), 933-949. DOI: 10.1080/14697688.2017.1393551.
2. Bayer, C., Friz, P. & Gatheral, J. (2016). "Pricing under rough volatility". *Quantitative Finance*, 16(6), 887-904. DOI: 10.1080/14697688.2015.1099717.
3. Lo, A. W. & MacKinlay, A. C. (1988). "Stock Market Prices Do Not Follow Random Walks: Evidence from a Simple Specification Test". *Review of Financial Studies*, 1(1), 41-66.
4. Fukasawa, M. (2011). "Asymptotic analysis for stochastic volatility: Martingale expansion". *Finance and Stochastics*, 15(4), 635-654.
5. El Euch, O. & Rosenbaum, M. (2019). "The characteristic function of rough Heston models". *Mathematical Finance*, 29(1), 3-38.

#### A.8 Effort estimate

| Field | Value |
|---|---|
| Duration | 2 days |
| Complexity | M |
| Uncertainty | Medium (rough vol is newer, less empirical validation) |

---

### 2.6 Phase 3.6 -- Order Flow Imbalance Validation

#### A.1 Identifier

| Field | Value |
|---|---|
| Number | 3.6 |
| Title | Order Flow Imbalance Validation |
| Objective | Validate OFI (Cont, Kukanov & Stoikov, 2014) as a predictive feature |

#### A.2 Justification

Order Flow Imbalance (OFI) is the most direct measure of buying/selling pressure in
the limit order book. Cont, Kukanov & Stoikov (2014) showed that OFI explains 60-70%
of short-term price changes (R-squared ~ 0.6 at 10-second horizons).

S02 already computes `ofi()` in `microstructure.py` as the normalized sum of bid-ask
volume imbalances. Phase 3.6 validates whether this OFI computation, when measured
over APEX's target horizons (1-bar to 20-bar forward returns), has genuine predictive IC.

OFI formula:
```
OFI_t = sum(delta_bid_vol - delta_ask_vol) / total_volume
```

Where `delta_bid_vol = max(0, bid_vol_t - bid_vol_{t-1})` captures new bid volume.

#### A.3 Dependencies

| Dependency | Type | Source |
|---|---|---|
| Phase 3.1 | Pipeline | Feature pipeline |
| Phase 3.3 | IC | IC measurement |
| S02 `MicrostructureAnalyzer` | Existing code | `ofi()` method |
| Phase 2 tick data | Data | `DbTick` from TimescaleDB |

#### A.4 Technical deliverables

**Files to create:**

| Path | Purpose |
|---|---|
| `features/calculators/ofi.py` | `OFICalculator(FeatureCalculator)` |
| `features/validation/ofi_report.py` | OFI validation report |
| `tests/unit/test_ofi_calculator.py` | Unit tests |

**Key signatures:**

```python
class OFICalculator(FeatureCalculator):
    """Order Flow Imbalance feature calculator.

    Computes OFI at multiple aggregation windows (10, 50, 100 ticks)
    to capture microstructure at different granularities.

    Reference: Cont, R., Kukanov, A. & Stoikov, S. (2014). "The Price
    Impact of Order Book Events". Journal of Financial Economics, 104(2), 293-320.
    """

    def name(self) -> str:
        return "ofi"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        """Adds: ofi_10, ofi_50, ofi_100 (multi-window OFI)."""
        ...
```

**Tests minimum**: 15 unit tests.

#### A.5 Success metrics

| Metric | Target |
|---|---|
| IC of ofi_10 on 1-bar forward return (BTC) | Report (literature: high IC at short horizons) |
| IC of ofi_100 on 5-bar forward return (BTC) | Report |
| IC decay curve shows expected pattern (high short, low long) | Verified |
| OFI on SPY vs BTC: report structural differences | Documented |
| OFI in [-1, +1] on all test data | Always (property test) |

#### A.6 Risks

| Risk | Mitigation |
|---|---|
| OFI requires L2 order book data (not always available) | Fall back to trade-based OFI (buy vs sell volume) for equities |
| OFI IC may be high at 10s but negligible at 5m | Test multiple horizons; if only ultra-short, document limitation |
| Binance trade data has UNKNOWN side classification | Lee-Ready classification already in S02 VPIN; reuse |

#### A.7 References

1. Cont, R., Kukanov, A. & Stoikov, S. (2014). "The Price Impact of Order Book Events". *Journal of Financial Economics*, 104(2), 293-320. DOI: 10.1016/j.jfineco.2012.01.001.
2. Cont, R. (2011). "Statistical Modeling of High-Frequency Financial Data". *IEEE Signal Processing Magazine*, 28(5), 16-25.
3. Cartea, A., Jaimungal, S. & Penalva, J. (2015). *Algorithmic and High-Frequency Trading*, Ch. 9. Cambridge University Press.
4. Bouchaud, J.-P., Bonart, J., Donier, J. & Gould, M. (2018). *Trades, Quotes and Prices*, Ch. 7. Cambridge University Press.
5. Hasbrouck, J. (2007). *Empirical Market Microstructure*, Ch. 4-5. Oxford University Press.

#### A.8 Effort estimate

| Field | Value |
|---|---|
| Duration | 2 days |
| Complexity | M |
| Uncertainty | Low (OFI is well-studied) |

---

### 2.7 Phase 3.7 -- CVD + Kyle Lambda Validation

#### A.1 Identifier

| Field | Value |
|---|---|
| Number | 3.7 |
| Title | CVD + Kyle Lambda Validation |
| Objective | Validate Cumulative Volume Delta and Kyle's lambda as predictive features |

#### A.2 Justification

**Kyle's Lambda** (Kyle, 1985) measures the price impact of order flow. Higher lambda
indicates lower liquidity and higher information asymmetry. Lambda is the coefficient
in the regression: `delta_P = lambda * OFI + epsilon`.

**Cumulative Volume Delta (CVD)** measures the cumulative difference between buyer-initiated
and seller-initiated volume. Divergence between CVD and price is a strong reversal signal:
price rising while CVD falls indicates distribution (smart money selling into the rally).

S02 already computes `cvd()` and `kyle_lambda()` in `microstructure.py`. S07 has a
separate `AdvancedMicrostructure` class. Phase 3.7 validates whether these features,
individually and in combination, have predictive power.

#### A.3 Dependencies

| Dependency | Type | Source |
|---|---|---|
| Phase 3.1 | Pipeline | Feature pipeline |
| Phase 3.3 | IC | IC measurement |
| Phase 3.6 | OFI | OFI results (for lambda regression) |
| S02 `MicrostructureAnalyzer` | Existing code | `cvd()`, `kyle_lambda()` |

#### A.4 Technical deliverables

**Files to create:**

| Path | Purpose |
|---|---|
| `features/calculators/cvd_kyle.py` | `CVDKyleCalculator(FeatureCalculator)` |
| `features/validation/cvd_kyle_report.py` | CVD + Kyle validation report |
| `tests/unit/test_cvd_kyle_calculator.py` | Unit tests |

**Key signatures:**

```python
class CVDKyleCalculator(FeatureCalculator):
    """CVD and Kyle's lambda feature calculator.

    Computes:
    - CVD (cumulative volume delta) as a directional pressure indicator
    - CVD-price divergence as a reversal signal
    - Kyle's lambda as a liquidity/information asymmetry indicator

    Reference: Kyle, A. S. (1985). "Continuous Auctions and Insider Trading".
    Econometrica, 53(6), 1315-1335.
    """

    def name(self) -> str:
        return "cvd_kyle"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        """Adds: cvd, cvd_price_divergence, kyle_lambda, kyle_lambda_zscore."""
        ...
```

**Tests minimum**: 15 unit tests.

#### A.5 Success metrics

| Metric | Target |
|---|---|
| IC of cvd_price_divergence on 5-bar forward returns | Report |
| IC of kyle_lambda_zscore on forward returns | Report |
| Kyle lambda is positive on all test data | Always (property test: lambda >= 0) |
| CVD-price divergence detects known reversal events in test data | >= 60% hit rate |

#### A.6 Risks

| Risk | Mitigation |
|---|---|
| Kyle's model assumes single informed trader | Use as liquidity proxy, not literal information measure |
| CVD requires reliable buy/sell classification | Validate Lee-Ready classification accuracy first |
| Lambda unstable in low-volume periods | Require minimum 50 trades in regression window |

#### A.7 References

1. Kyle, A. S. (1985). "Continuous Auctions and Insider Trading". *Econometrica*, 53(6), 1315-1335.
2. Hasbrouck, J. (2007). *Empirical Market Microstructure*, Ch. 8. Oxford University Press.
3. O'Hara, M. (1995). *Market Microstructure Theory*, Ch. 3. Blackwell.
4. Easley, D. & O'Hara, M. (1987). "Price, Trade Size, and Information in Securities Markets". *Journal of Financial Economics*, 19(1), 69-90.
5. Lee, C. M. C. & Ready, M. J. (1991). "Inferring Trade Direction from Intraday Data". *Journal of Finance*, 46(2), 733-746.

#### A.8 Effort estimate

| Field | Value |
|---|---|
| Duration | 2 days |
| Complexity | M |
| Uncertainty | Medium |

---

### 2.8 Phase 3.8 -- GEX Validation

#### A.1 Identifier

| Field | Value |
|---|---|
| Number | 3.8 |
| Title | GEX Validation |
| Objective | Validate Gamma Exposure (GEX) as a predictive feature for price pinning and volatility |

#### A.2 Justification

When options market makers are long gamma (positive GEX), they buy dips and sell rallies
to delta-hedge, creating a stabilizing effect that pins prices near high-GEX strikes.
When market makers are short gamma (negative GEX), their hedging amplifies moves, creating
explosive volatility.

Barbon & Buraschi (2020) formalized this relationship, showing that dealer gamma exposure
predicts future return variance and creates predictable "pinning" effects around
large open interest strikes.

S02 already implements `update_gex()` and `gex_magnet_levels()` in `crowd_behavior.py`.
Phase 3.8 validates whether GEX-derived features have predictive IC.

GEX formula:
```
GEX_i = Gamma_i * OI_i * 100 * contract_multiplier
Net_GEX = sum(GEX_calls) - sum(GEX_puts)
```

#### A.3 Dependencies

| Dependency | Type | Source |
|---|---|---|
| Phase 3.1 | Pipeline | Feature pipeline |
| Phase 3.3 | IC | IC measurement |
| S02 `CrowdBehaviorAnalyzer` | Existing code | `update_gex()`, `gex_magnet_levels()` |
| Phase 2 options data | Data | Options OI + gamma (source TBD) |

#### A.4 Technical deliverables

**Files to create:**

| Path | Purpose |
|---|---|
| `features/calculators/gex.py` | `GEXCalculator(FeatureCalculator)` |
| `features/validation/gex_report.py` | GEX validation report |
| `tests/unit/test_gex_calculator.py` | Unit tests |

**Key signatures:**

```python
class GEXCalculator(FeatureCalculator):
    """Gamma Exposure feature calculator.

    Computes dealer GEX and derived features:
    - net_gex: total dealer gamma exposure
    - gex_regime: positive (stabilizing) vs. negative (amplifying)
    - distance_to_gex_magnet: distance from price to nearest high-GEX strike
    - gex_flip_proximity: how close price is to the GEX flip level

    Reference: Barbon, A. & Buraschi, A. (2020). "Gamma Fragility".
    Working paper, University of St. Gallen.
    """

    def name(self) -> str:
        return "gex"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        """Adds: net_gex, gex_regime, distance_to_magnet, gex_flip_proximity."""
        ...
```

**Tests minimum**: 12 unit tests.

#### A.5 Success metrics

| Metric | Target |
|---|---|
| IC of gex_regime on next-day return variance | Report |
| IC of distance_to_magnet on next-day return | Report |
| GEX pinning effect: returns lower near high-GEX strikes | Verified on SPY |
| GEX flip level predicts vol regime changes | >= 55% accuracy |

**Important caveat**: GEX is primarily meaningful for SPY/QQQ/indices with liquid options
markets. Crypto does not have a comparable options ecosystem. GEX features may only
apply to equities.

#### A.6 Risks

| Risk | Mitigation |
|---|---|
| Options data is expensive/hard to get | Use CBOE DataShop or free alternatives (OptionStrat API); document data limitations |
| GEX only relevant for US equities with deep options markets | Document scope limitation; do NOT force GEX on crypto |
| Dealer positioning is not directly observable | GEX is a proxy; results are probabilistic, not deterministic |

#### A.7 References

1. Barbon, A. & Buraschi, A. (2020). "Gamma Fragility". Working paper, University of St. Gallen.
2. Bollen, N. P. B. & Whaley, R. E. (2004). "Does Net Buying Pressure Affect the Shape of Implied Volatility Functions?". *Journal of Finance*, 59(2), 711-753.
3. Ni, S. X., Pearson, N. D. & Poteshman, A. M. (2005). "Stock Price Clustering on Option Expiration Dates". *Journal of Financial Economics*, 78(1), 49-87.
4. Avellaneda, M. & Lipkin, M. D. (2003). "A market-induced mechanism for stock pinning". *Quantitative Finance*, 3(6), 417-425.
5. Choi, J. & Mueller, P. (2012). "Nominal Bond-Stock Correlations: The Role of Macroeconomic Uncertainty". Working paper, LSE.

#### A.8 Effort estimate

| Field | Value |
|---|---|
| Duration | 3 days |
| Complexity | L |
| Uncertainty | High (data availability, limited to equities) |

---

### 2.9 Phase 3.9 -- Multicollinearity and Orthogonalization

#### A.1 Identifier

| Field | Value |
|---|---|
| Number | 3.9 |
| Title | Multicollinearity and Orthogonalization |
| Objective | Detect and resolve multicollinearity among validated features to avoid redundant signals |

#### A.2 Justification

Multicollinearity inflates coefficient variance and produces unstable models. In a
signal-based portfolio, highly correlated features provide no additional information
but increase overfitting risk (Belsley, Kuh & Welsch, 1980).

If OFI and CVD are 90% correlated, keeping both doubles the weight of order flow
without doubling the information. Lopez de Prado (2020, Ch. 6) recommends hierarchical
clustering of features followed by orthogonalization.

#### A.3 Dependencies

| Dependency | Type | Source |
|---|---|---|
| Phases 3.4-3.8 | Validated features | All individual feature IC results |
| Phase 3.3 | IC | IC measurement framework |

#### A.4 Technical deliverables

**Files to create:**

| Path | Purpose |
|---|---|
| `features/multicollinearity.py` | `MulticollinearityAnalyzer` |
| `features/orthogonalizer.py` | `FeatureOrthogonalizer` |
| `tests/unit/test_multicollinearity.py` | Unit tests |
| `tests/unit/test_orthogonalizer.py` | Unit tests |

**Key signatures:**

```python
@dataclass(frozen=True)
class MulticollinearityReport:
    """Report on feature multicollinearity.

    Reference: Belsley, D. A., Kuh, E. & Welsch, R. E. (1980).
    Regression Diagnostics. Wiley.
    """
    correlation_matrix: dict[str, dict[str, float]]
    vif_scores: dict[str, float]       # Variance Inflation Factor
    high_correlation_pairs: list[tuple[str, str, float]]  # |corr| > 0.7
    cluster_assignments: dict[str, int]  # Feature -> cluster ID
    recommended_drops: list[str]        # Features to drop (lowest IC in cluster)


class MulticollinearityAnalyzer:
    """Detects multicollinearity among features.

    Uses VIF (Variance Inflation Factor), Spearman correlation matrix,
    and hierarchical clustering to identify redundant features.

    VIF > 5 indicates problematic multicollinearity.
    VIF > 10 indicates severe multicollinearity.

    Reference: Belsley, Kuh & Welsch (1980), Lopez de Prado (2020) Ch. 6.
    """

    def analyze(
        self,
        feature_matrix: pl.DataFrame,
        ic_results: list[ICResult],
        max_correlation: float = 0.70,
        max_vif: float = 5.0,
    ) -> MulticollinearityReport: ...


class FeatureOrthogonalizer:
    """Orthogonalizes correlated features via PCA or residualization.

    When two features are highly correlated, either:
    1. Drop the one with lower IC (recommended)
    2. Residualize: regress Y on X, keep residual (preserves unique info)
    3. PCA: replace correlated set with principal components

    Reference: Lopez de Prado, M. (2020). Machine Learning for Asset Managers,
    Ch. 6. Cambridge University Press.
    """

    def orthogonalize(
        self,
        feature_matrix: pl.DataFrame,
        report: MulticollinearityReport,
        method: str = "drop_lowest_ic",  # or "residualize" or "pca"
    ) -> pl.DataFrame: ...
```

**Tests minimum**: 15 unit tests.

#### A.5 Success metrics

| Metric | Target |
|---|---|
| No pair of retained features with \|correlation\| > 0.70 | Verified |
| VIF of all retained features < 5.0 | Verified |
| Orthogonalized matrix has lower condition number | Verified |
| Dropped features are documented with IC comparison | Report |

#### A.6 Risks

| Risk | Mitigation |
|---|---|
| PCA components lose interpretability | Prefer drop-lowest-IC over PCA; PCA only as fallback |
| Residualization creates look-ahead if not time-indexed | Use rolling window regression for residualization |
| May drop features that are conditionally useful | Document regime-conditional correlation before dropping |

#### A.7 References

1. Belsley, D. A., Kuh, E. & Welsch, R. E. (1980). *Regression Diagnostics: Identifying Influential Data and Sources of Collinearity*. Wiley.
2. Lopez de Prado, M. (2020). *Machine Learning for Asset Managers*, Ch. 6. Cambridge University Press.
3. Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*, Ch. 8. Wiley.
4. Friedman, J. H. (2001). "Greedy Function Approximation: A Gradient Boosting Machine". *Annals of Statistics*, 29(5), 1189-1232.
5. Tibshirani, R. (1996). "Regression Shrinkage and Selection via the Lasso". *JRSSB*, 58(1), 267-288.

#### A.8 Effort estimate

| Field | Value |
|---|---|
| Duration | 2 days |
| Complexity | M |
| Uncertainty | Low |

---

### 2.10 Phase 3.10 -- CPCV with Purging

#### A.1 Identifier

| Field | Value |
|---|---|
| Number | 3.10 |
| Title | CPCV with Purging |
| Objective | Implement Combinatorial Purged Cross-Validation for robust out-of-sample feature validation |

#### A.2 Justification

Standard k-fold cross-validation is invalid for time series data because it ignores
temporal ordering and creates data leakage through autocorrelation. Bailey & Lopez de
Prado (2017) introduced Combinatorial Purged Cross-Validation (CPCV) which:

1. **Purges**: removes training samples whose labels overlap with test samples.
2. **Embargoes**: adds a gap after each test fold to prevent information leakage.
3. **Combinatorial**: tests all C(N,k) path combinations, not just k folds.

CPCV is the gold standard for evaluating financial features and strategies. ADR-0002
mandates it for all quant PRs.

#### A.3 Dependencies

| Dependency | Type | Source |
|---|---|---|
| Phase 3.1 | Pipeline | Feature pipeline with labels |
| Phase 3.3 | IC | IC measurement |
| Phase 3.9 | Orthogonalized features | Clean feature set |
| ADR-0002 | Methodology | Mandatory CPCV compliance |

#### A.4 Technical deliverables

**Files to create:**

| Path | Purpose |
|---|---|
| `features/cv/cpcv.py` | `CPCVSplitter` -- CPCV fold generator |
| `features/cv/purger.py` | `PurgeEmbargo` -- purging and embargo logic |
| `features/cv/validator.py` | `CrossValidator` -- runs IC measurement across CPCV folds |
| `tests/unit/test_cpcv.py` | Unit tests |
| `tests/unit/test_purger.py` | Purger unit tests |

**Key signatures:**

```python
class PurgeEmbargo:
    """Purging and embargo for time series cross-validation.

    Purging: removes training observations whose labels overlap in time
    with any test observation.

    Embargo: adds a temporal gap after the test fold boundary to prevent
    information leakage through autocorrelation.

    Reference: Lopez de Prado (2018), Ch. 7.
    """

    def __init__(
        self,
        embargo_pct: float = 0.01,  # 1% of total samples
    ) -> None: ...

    def purge(
        self,
        train_indices: np.ndarray,
        test_indices: np.ndarray,
        label_end_times: np.ndarray,
    ) -> np.ndarray: ...


class CPCVSplitter:
    """Combinatorial Purged Cross-Validation splitter.

    Generates all C(N, k) combinations of N groups taken k at a time
    as test folds, with purging and embargo on the remaining groups.

    Reference: Lopez de Prado (2018), Ch. 12.
    Bailey, D. H., Borwein, J. M., Lopez de Prado, M. & Zhu, Q. J. (2017).
    "The Probability of Backtest Overfitting".
    Journal of Computational Finance, 20(4).
    """

    def __init__(
        self,
        n_groups: int = 6,
        n_test_groups: int = 2,
        purge_embargo: PurgeEmbargo | None = None,
    ) -> None: ...

    def split(
        self,
        timestamps: np.ndarray,
        label_end_times: np.ndarray,
    ) -> Iterator[tuple[np.ndarray, np.ndarray]]: ...

    def n_splits(self) -> int:
        """Returns C(n_groups, n_test_groups)."""
        ...


class CrossValidator:
    """Runs IC measurement across CPCV folds.

    For each fold, measures the IC of every feature on the test set.
    Aggregates OOS IC across all folds to produce robust estimates.

    Reference: Lopez de Prado (2018), Ch. 7, 12.
    """

    def __init__(
        self,
        splitter: CPCVSplitter,
        ic_measurer: ICMeasurer,
    ) -> None: ...

    def validate(
        self,
        feature_matrix: pl.DataFrame,
        forward_returns: pl.Series,
        timestamps: np.ndarray,
        label_end_times: np.ndarray,
    ) -> dict[str, ICResult]: ...
```

**Tests minimum**: 20 unit tests.

#### A.5 Success metrics

| Metric | Target |
|---|---|
| CPCV generates correct number of folds: C(6,2) = 15 | Verified |
| Purged training set has no temporal overlap with test | Verified |
| Embargo gap is correctly applied | Verified |
| OOS IC across CPCV folds is consistent (low variance) | IC_IR > 0.5 |
| CPCV IC < in-sample IC (expected for honest validation) | Verified |

#### A.6 Risks

| Risk | Mitigation |
|---|---|
| CPCV is computationally expensive (C(N,k) can be large) | Use N=6, k=2 (15 folds) as default; only increase if needed |
| Purging removes too many training samples | Monitor purged fraction; if > 30%, increase dataset or reduce label horizon |
| Embargo too large reduces effective training size | Start with 1% embargo; adjust based on autocorrelation analysis |

#### A.7 References

1. Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*, Ch. 7, 12. Wiley.
2. Bailey, D. H., Borwein, J. M., Lopez de Prado, M. & Zhu, Q. J. (2017). "The Probability of Backtest Overfitting". *Journal of Computational Finance*, 20(4), 39-69.
3. Bailey, D. H. & Lopez de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality". *Journal of Portfolio Management*, 40(5), 94-107.
4. Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies* (2nd ed.). Wiley.
5. Arlot, S. & Celisse, A. (2010). "A survey of cross-validation procedures for model selection". *Statistics Surveys*, 4, 40-79.

#### A.8 Effort estimate

| Field | Value |
|---|---|
| Duration | 3 days |
| Complexity | L |
| Uncertainty | Low (well-specified algorithm) |

---

### 2.11 Phase 3.11 -- Multiple Hypothesis Testing

#### A.1 Identifier

| Field | Value |
|---|---|
| Number | 3.11 |
| Title | Multiple Hypothesis Testing (DSR, PBO) |
| Objective | Apply multiple-testing corrections to prevent selection bias across the feature set |

#### A.2 Justification

When testing N features, the probability of finding at least one "significant" result
by chance increases rapidly. Harvey, Liu & Zhu (2016) showed that the standard t-stat
threshold of 1.96 is insufficient when hundreds of strategies have been tested; they
propose a threshold of ~3.0 for new factors.

Two mandatory corrections (per ADR-0002):

1. **Deflated Sharpe Ratio (DSR)** (Bailey & Lopez de Prado, 2014): corrects the Sharpe
   Ratio for the number of trials, non-normality (skewness, kurtosis), and estimation
   error. PSR > 0.95 means the true Sharpe is positive with 95% confidence.

2. **Probability of Backtest Overfitting (PBO)** (Bailey et al., 2014): measures the
   probability that the best-performing strategy in-sample will underperform the median
   OOS. PBO < 0.50 means overfitting is unlikely.

#### A.3 Dependencies

| Dependency | Type | Source |
|---|---|---|
| Phase 3.10 | CPCV | Cross-validated IC results |
| Phase 3.9 | Orthogonalized features | Multicollinearity-clean feature set |
| Existing `backtesting/metrics.py` | Code | `probabilistic_sharpe_ratio()`, `deflated_sharpe_ratio()` |

#### A.4 Technical deliverables

**Files to create:**

| Path | Purpose |
|---|---|
| `features/hypothesis/dsr.py` | `DeflatedSharpeCalculator` |
| `features/hypothesis/pbo.py` | `PBOCalculator` -- Probability of Backtest Overfitting |
| `features/hypothesis/report.py` | Multiple hypothesis testing report |
| `tests/unit/test_dsr.py` | DSR unit tests |
| `tests/unit/test_pbo.py` | PBO unit tests |

**Key signatures:**

```python
@dataclass(frozen=True)
class DSRResult:
    """Deflated Sharpe Ratio result.

    Reference: Bailey, D. H. & Lopez de Prado, M. (2014).
    "The Deflated Sharpe Ratio". JPM, 40(5), 94-107.
    """
    feature_name: str
    sharpe_ratio: float
    psr: float              # Probabilistic Sharpe Ratio
    dsr: float              # Deflated Sharpe Ratio
    n_trials: int           # Number of features/strategies tested
    skewness: float
    kurtosis: float
    is_significant: bool    # DSR > 0.95


@dataclass(frozen=True)
class PBOResult:
    """Probability of Backtest Overfitting result.

    Reference: Bailey et al. (2014). "The Probability of Backtest Overfitting".
    Journal of Computational Finance.
    """
    pbo: float              # Probability of overfitting [0, 1]
    rank_logits: list[float]
    is_overfit: bool        # pbo > 0.50


class DeflatedSharpeCalculator:
    """Computes DSR for a set of features/strategies.

    Accounts for:
    - Number of trials (features tested)
    - Non-normality of returns (skewness, excess kurtosis)
    - Sample size

    Reference: Bailey & Lopez de Prado (2014).
    """

    def compute(
        self,
        feature_sharpes: dict[str, float],
        returns_data: dict[str, pl.Series],
        benchmark_sharpe: float = 0.0,
    ) -> list[DSRResult]: ...


class PBOCalculator:
    """Computes Probability of Backtest Overfitting via CPCV.

    For each CPCV combination:
    1. Rank strategies by IS performance
    2. Record OOS rank of the IS-best strategy
    3. PBO = fraction of combinations where IS-best underperforms OOS median

    Reference: Bailey et al. (2014).
    """

    def compute(
        self,
        cpcv_results: dict[str, list[float]],  # feature -> list of OOS ICs per fold
    ) -> PBOResult: ...
```

**Tests minimum**: 18 unit tests.

#### A.5 Success metrics

| Metric | Target |
|---|---|
| DSR < PSR for all features (deflation reduces significance) | Verified |
| DSR correctly penalizes more when N_trials is larger | Verified on synthetic |
| PBO < 0.50 for the retained feature set | Target |
| PBO > 0.50 triggers WARNING in report | Verified |
| Existing `full_report()` PSR/DSR match new implementation | Cross-validated |

#### A.6 Risks

| Risk | Mitigation |
|---|---|
| DSR may reject all features if N_trials is too high | Report DSR for individual and grouped features; use grouped if individual all fail |
| PBO requires many CPCV paths for stable estimate | Use at least 15 paths (C(6,2)) |
| Non-normality corrections may be extreme for crypto | Cap kurtosis correction at reasonable bound; document |

#### A.7 References

1. Bailey, D. H. & Lopez de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality". *Journal of Portfolio Management*, 40(5), 94-107.
2. Bailey, D. H., Borwein, J. M., Lopez de Prado, M. & Zhu, Q. J. (2014). "The Probability of Backtest Overfitting". *Journal of Computational Finance*.
3. Harvey, C. R., Liu, Y. & Zhu, H. (2016). "...and the Cross-Section of Expected Returns". *Review of Financial Studies*, 29(1), 5-68. DOI: 10.1093/rfs/hhv059.
4. Harvey, C. R. & Liu, Y. (2015). "Backtesting". *Journal of Portfolio Management*, 42(1), 13-28.
5. White, H. (2000). "A Reality Check for Data Snooping". *Econometrica*, 68(5), 1097-1126.

#### A.8 Effort estimate

| Field | Value |
|---|---|
| Duration | 2-3 days |
| Complexity | L |
| Uncertainty | Low |

---

### 2.12 Phase 3.12 -- Feature Selection Report

#### A.1 Identifier

| Field | Value |
|---|---|
| Number | 3.12 |
| Title | Feature Selection Report |
| Objective | Produce the final keep/reject report for all candidate features with full academic justification |

#### A.3 Dependencies

| Dependency | Type | Source |
|---|---|---|
| Phases 3.4-3.8 | Individual feature ICs | Per-feature validation results |
| Phase 3.9 | Multicollinearity | Orthogonalization results |
| Phase 3.10 | CPCV | Cross-validated OOS results |
| Phase 3.11 | DSR/PBO | Multiple testing corrections |

#### A.2 Justification

This sub-phase produces no new code -- it aggregates all prior results into a single,
authoritative document that decides which features enter Phase 4 (Regime Detector)
and Phase 5 (Backtesting). The report format follows institutional practice: every
keep/reject decision is backed by measured IC, IC_IR, DSR, PBO, and multicollinearity
analysis.

Grinold & Kahn (1999, Ch. 14) provide the framework: a feature is worth keeping if its
marginal IC contribution to the portfolio exceeds its marginal cost (turnover, complexity).

#### A.4 Technical deliverables

**Files to create:**

| Path | Purpose |
|---|---|
| `features/selection/report_generator.py` | `FeatureSelectionReportGenerator` |
| `features/selection/decision.py` | `FeatureDecision` -- keep/reject with rationale |
| `tests/unit/test_report_generator.py` | Unit tests |

**Report output:** `docs/reports/PHASE_3_FEATURE_SELECTION.md`

**Report structure:**

```markdown
# Phase 3 Feature Selection Report
## Date: YYYY-MM-DD
## Executive Summary
- N features evaluated, M retained, K rejected

## Per-Feature Results
### Feature: HAR-RV
| Metric | Value | Threshold | Decision |
|---|---|---|---|
| IC (1-bar, BTC) | X.XXX | > 0.02 | PASS/FAIL |
| IC (1-bar, SPY) | X.XXX | > 0.02 | PASS/FAIL |
| IC_IR | X.XX | > 0.50 | PASS/FAIL |
| DSR | X.XX | > 0.95 | PASS/FAIL |
| VIF | X.XX | < 5.0 | PASS/FAIL |
| **Decision** | KEEP / REJECT | | Rationale: ... |

[... repeat for each feature ...]

## Multicollinearity Matrix
## PBO Results
## Final Approved Feature List
## Recommendations for Phase 4
```

**Tests minimum**: 10 unit tests.

#### A.5 Success metrics

| Metric | Target |
|---|---|
| Every candidate feature has a keep/reject decision | 100% |
| Every decision cites measured IC, IC_IR, DSR | 100% |
| Report is machine-parseable (structured Markdown + JSON) | Both formats |
| Report matches all IC thresholds documented in Phase 3.3 | Consistent |
| PBO of final feature set < 0.50 | Target |

#### A.6 Risks

| Risk | Mitigation |
|---|---|
| All features rejected (IC too low) | Document honestly; this means Phase 4 needs different features |
| Report cherry-picks favorable metrics | Require ALL metrics in report; no omissions |
| Overconfident conclusions from limited data | Include confidence intervals on all metrics |

#### A.7 References

1. Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio Management* (2nd ed.), Ch. 14. McGraw-Hill.
2. Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*, Ch. 8. Wiley.
3. Harvey, C. R., Liu, Y. & Zhu, H. (2016). "...and the Cross-Section of Expected Returns". *Review of Financial Studies*, 29(1), 5-68.
4. Arnott, R. D., Harvey, C. R., Kalesnik, V. & Linnainmaa, J. T. (2019). "Reports of Value's Death May Be Greatly Exaggerated". *Financial Analysts Journal*, 75(4), 36-52.
5. Gu, S., Kelly, B. & Xiu, D. (2020). "Empirical Asset Pricing via Machine Learning". *Review of Financial Studies*, 33(5), 2223-2273.

#### A.8 Effort estimate

| Field | Value |
|---|---|
| Duration | 1-2 days |
| Complexity | S |
| Uncertainty | Low |

---

### 2.13 Phase 3.13 -- Integration with S02 Signal Engine

#### A.1 Identifier

| Field | Value |
|---|---|
| Number | 3.13 |
| Title | Integration with S02 Signal Engine |
| Objective | Wire validated features into S02's signal computation pipeline as new `SignalComponent` sources |

#### A.2 Justification

The validated features from Phase 3.12 need an integration path into the live signal
pipeline. This sub-phase creates the scaffolding -- abstract interfaces, configuration,
and test stubs -- WITHOUT modifying S02's live behavior. The actual activation of new
signals is deferred to Phase 4 (after regime detection is in place).

This follows the Open/Closed Principle (Martin, 2008): S02 is extended via new
`FeatureCalculator` implementations, not modified internally.

#### A.3 Dependencies

| Dependency | Type | Source |
|---|---|---|
| Phase 3.12 | Feature selection | Approved feature list |
| S02 `SignalScorer` | Existing code | Component weight system |
| S02 `service.py` | Existing code | `_process_tick()` pipeline |

#### A.4 Technical deliverables

**Files to create:**

| Path | Purpose |
|---|---|
| `features/integration/s02_adapter.py` | `S02FeatureAdapter` -- adapts offline features for real-time use |
| `features/integration/config.py` | Feature activation configuration |
| `tests/unit/test_s02_adapter.py` | Adapter unit tests |

**Key approach:**

The adapter translates each validated `FeatureCalculator` into a function that can be
called from S02's `_process_tick()` on each tick, producing a `SignalComponent` compatible
with `SignalScorer.compute()`.

```python
class S02FeatureAdapter:
    """Adapts offline FeatureCalculators for real-time S02 use.

    Each validated feature becomes a new SignalComponent that participates
    in the SignalScorer weighted confluence computation.

    The adapter maintains a rolling buffer of recent ticks/bars sufficient
    for the feature's warm-up period, and computes the feature value
    on each tick.

    Reference: Martin, R. C. (2008). Clean Code, Ch. 10 (Classes).
    """

    def __init__(
        self,
        calculator: FeatureCalculator,
        warmup_bars: int,
        weight: float,
    ) -> None: ...

    def update(self, tick: NormalizedTick) -> SignalComponent | None:
        """Returns SignalComponent if warmup is complete, None otherwise."""
        ...
```

**Important**: This sub-phase does NOT modify S02's `_process_tick()`. It creates the
adapter pattern that Phase 4 will use to inject new features.

**Tests minimum**: 12 unit tests.

#### A.5 Success metrics

| Metric | Target |
|---|---|
| Adapter produces valid `SignalComponent` objects | Verified |
| Adapter returns None during warmup period | Verified |
| Adapter output is consistent with offline computation (< 1% drift) | Verified |
| No modification to S02 production code | Zero diff in services/s02_signal_engine/ |

#### A.6 Risks

| Risk | Mitigation |
|---|---|
| Real-time feature values may differ from offline (tick vs bar) | Use identical aggregation logic; test for consistency |
| Feature warmup may cause gaps at start of session | Return None during warmup; S02 already handles missing components |
| Adding too many features slows _process_tick | Profile; target < 1ms per feature per tick |

#### A.7 References

1. Martin, R. C. (2008). *Clean Code: A Handbook of Agile Software Craftsmanship*, Ch. 10. Prentice Hall.
2. Martin, R. C. (2017). *Clean Architecture: A Craftsman's Guide to Software Structure and Design*, Ch. 22. Prentice Hall.
3. Gamma, E., Helm, R., Johnson, R. & Vlissides, J. (1994). *Design Patterns: Elements of Reusable Object-Oriented Software*. Addison-Wesley.
4. Fowler, M. (2018). *Refactoring: Improving the Design of Existing Code* (2nd ed.), Ch. 8. Addison-Wesley.
5. Evans, E. (2003). *Domain-Driven Design: Tackling Complexity in the Heart of Software*, Ch. 4. Addison-Wesley.

#### A.8 Effort estimate

| Field | Value |
|---|---|
| Duration | 2 days |
| Complexity | M |
| Uncertainty | Low |

---

## 3. Architecture

### 3.1 Feature Validation Harness -- System Diagram

```
                      ┌────────────────────────────────┐
                      │     Phase 2 Historical Data     │
                      │   (TimescaleDB: bars, ticks)    │
                      └───────────────┬────────────────┘
                                      │
                                      ▼
                      ┌────────────────────────────────┐
                      │      FeaturePipeline (3.1)      │
                      │  ┌──────────┐ ┌──────────────┐ │
                      │  │LabelsGen │ │SampleWeighter│ │
                      │  └──────────┘ └──────────────┘ │
                      └───────────────┬────────────────┘
                                      │ feature vectors
                                      ▼
                      ┌────────────────────────────────┐
                      │     FeatureStore (3.2)          │
                      │  Versioned, point-in-time       │
                      │  Repository Pattern              │
                      └───────────────┬────────────────┘
                                      │
                   ┌──────────────────┼──────────────────┐
                   │                  │                   │
                   ▼                  ▼                   ▼
          ┌────────────┐    ┌────────────┐     ┌────────────┐
          │ HAR-RV     │    │ OFI        │     │ GEX        │
          │ Calc (3.4) │    │ Calc (3.6) │     │ Calc (3.8) │
          └──────┬─────┘    └──────┬─────┘     └──────┬─────┘
                 │                 │                   │
          ┌──────┴─────┐    ┌─────┴──────┐     ┌─────┴──────┐
          │ Rough Vol  │    │ CVD+Kyle   │     │            │
          │ Calc (3.5) │    │ Calc (3.7) │     │            │
          └──────┬─────┘    └──────┬─────┘     └────────────┘
                 │                 │
                 └────────┬────────┘
                          │ all IC results
                          ▼
          ┌───────────────────────────────┐
          │   ICMeasurer (3.3)            │
          │   Spearman IC, IC_IR, decay   │
          └───────────────┬───────────────┘
                          │
                          ▼
          ┌───────────────────────────────┐
          │   MulticollinearityAnalyzer   │
          │   + Orthogonalizer (3.9)      │
          └───────────────┬───────────────┘
                          │ clean features
                          ▼
          ┌───────────────────────────────┐
          │   CPCVSplitter +              │
          │   CrossValidator (3.10)       │
          └───────────────┬───────────────┘
                          │ OOS IC per fold
                          ▼
          ┌───────────────────────────────┐
          │   DSR + PBO Calculators       │
          │   (3.11)                      │
          └───────────────┬───────────────┘
                          │
                          ▼
          ┌───────────────────────────────┐
          │   Feature Selection Report    │
          │   (3.12) — keep/reject        │
          └───────────────┬───────────────┘
                          │ approved features
                          ▼
          ┌───────────────────────────────┐
          │   S02 Feature Adapter (3.13)  │
          │   SignalComponent interface    │
          └───────────────────────────────┘
```

### 3.2 Abstract Base Classes

| ABC | Module | Purpose | Key Methods |
|---|---|---|---|
| `FeatureCalculator` | `features/base.py` | Interface for all feature calculators | `name()`, `compute()`, `required_columns()`, `output_columns()` |
| `FeatureStore` | `features/store.py` | Repository for versioned features | `save()`, `load()`, `list_versions()` |
| `ICMetric` | `features/ic.py` | Interface for IC-like metrics | `measure()`, `measure_all()` |
| `BacktestSplitter` | `features/cv/cpcv.py` | Interface for CV fold generators | `split()`, `n_splits()` |
| `FeatureValidator` | `features/cv/validator.py` | Runs validation across CV folds | `validate()` |

### 3.3 Strategy Patterns Applied

1. **FeatureCalculator as Strategy** -- Each feature (HAR-RV, Rough Vol, OFI, CVD, GEX)
   implements the same `FeatureCalculator` interface. `FeaturePipeline` composes them
   without knowing which specific features are active.

2. **Repository Pattern for FeatureStore** -- Features are persisted and queried through
   a uniform interface, abstracting the underlying storage (TimescaleDB + Redis cache).

3. **Adapter Pattern for S02 Integration** -- `S02FeatureAdapter` adapts offline
   `FeatureCalculator` implementations for real-time tick-by-tick use in S02.

### 3.4 Dependency Injection

```python
# Example: wiring in features/config.py

def build_pipeline(config: Config) -> FeaturePipeline:
    """Factory function that assembles the feature pipeline.

    All dependencies are injected — no concrete imports in FeaturePipeline.
    """
    calculators = [
        HARRVCalculator(window=config.har_rv_window),
        RoughVolCalculator(n_lags=config.rough_vol_lags),
        OFICalculator(windows=config.ofi_windows),
        CVDKyleCalculator(regression_window=config.kyle_window),
        GEXCalculator(),  # only for equities
    ]

    labeler = TripleBarrierLabeler(
        take_profit=config.tp_pct,
        stop_loss=config.sl_pct,
        max_holding=config.max_holding_bars,
    )

    weighter = SampleWeighter(method="uniqueness")

    return FeaturePipeline(
        calculators=calculators,
        labeler=labeler,
        weighter=weighter,
    )
```

### 3.5 Integration with Existing Services

| Service | Integration Type | Details |
|---|---|---|
| S01 (Data Ingestion) | Read-only | Historical data from TimescaleDB |
| S07 (Quant Analytics) | Read-only | Reuse pure functions (`har_rv_forecast`, `estimate_hurst_from_vol`, etc.) |
| S02 (Signal Engine) | Adapter (3.13) | `S02FeatureAdapter` creates `SignalComponent` objects |
| S09 (Feedback Loop) | Future | Feature IC drift monitoring (Phase 9+) |

---

## 4. SOLID Principles and Design Patterns

### 4.1 SOLID Application per Sub-Phase

| Sub-Phase | S (SRP) | O (OCP) | L (LSP) | I (ISP) | D (DIP) |
|---|---|---|---|---|---|
| 3.1 Pipeline | `FeaturePipeline` orchestrates only | New calculators added without modifying pipeline | All calculators honor `FeatureCalculator` contract | Minimal interface: 4 methods | Pipeline depends on ABC, not implementations |
| 3.2 Store | Store handles persistence only | New storage backends via interface | Any store implementation works | `save()` and `load()` are independent | `FeaturePipeline` receives store via constructor |
| 3.3 IC | IC measurement is one concern | New metrics (mutual info) via new class | `ICResult` contract honored by all | `ICMeasurer` only measures IC | No dependency on specific features |
| 3.4-3.8 Calculators | Each calculates one feature family | New features = new class | All produce `pl.DataFrame` with documented columns | Only `FeatureCalculator` methods | Depend on ABC |
| 3.9 Multicol | Analysis is one concern | New methods (LASSO) via new class | - | - | Depends on `ICResult` interface |
| 3.10 CPCV | Splitting is one concern | New CV strategies possible | `CPCVSplitter` compatible with any validator | `split()` only | Validator receives splitter via constructor |
| 3.11 DSR/PBO | Statistical testing is one concern | New corrections via new class | - | - | Uses `ICResult` interface |
| 3.12 Report | Report generation only | New report formats possible | - | - | Depends on result interfaces |
| 3.13 Adapter | Adapts offline to online | New adapters for new features | Produces valid `SignalComponent` | One method: `update()` | S02 depends on `SignalComponent`, not adapter |

### 4.2 Design Patterns with References

| Pattern | Where Used | Justification | Reference |
|---|---|---|---|
| **Strategy** | `FeatureCalculator` implementations | Each feature algorithm is interchangeable | [refactoring.guru/strategy](https://refactoring.guru/design-patterns/strategy); GoF (1994) Ch. 5 |
| **Repository** | `FeatureStore` | Decouples domain logic from persistence | [refactoring.guru/repository](https://refactoring.guru/design-patterns/repository); Fowler (2002) Ch. 10 |
| **Factory Method** | `build_pipeline()` | Centralizes creation of feature pipeline | [refactoring.guru/factory-method](https://refactoring.guru/design-patterns/factory-method); GoF (1994) Ch. 3 |
| **Adapter** | `S02FeatureAdapter` | Adapts offline calculators to real-time interface | [refactoring.guru/adapter](https://refactoring.guru/design-patterns/adapter); GoF (1994) Ch. 4 |
| **Template Method** | `FeatureCalculator.compute()` | Base class defines skeleton; subclasses implement steps | [refactoring.guru/template-method](https://refactoring.guru/design-patterns/template-method); GoF (1994) Ch. 5 |
| **Iterator** | `CPCVSplitter.split()` | Yields train/test splits lazily | [refactoring.guru/iterator](https://refactoring.guru/design-patterns/iterator); GoF (1994) Ch. 5 |
| **Composite** | `FeaturePipeline` composing calculators | Treats single and multiple calculators uniformly | [refactoring.guru/composite](https://refactoring.guru/design-patterns/composite); GoF (1994) Ch. 4 |
| **Builder** | `FeatureSelectionReportGenerator` | Step-by-step report construction | [refactoring.guru/builder](https://refactoring.guru/design-patterns/builder); GoF (1994) Ch. 3 |
| **Observer** | Feature IC drift → S09 notification | S09 observes feature quality changes | [refactoring.guru/observer](https://refactoring.guru/design-patterns/observer); GoF (1994) Ch. 5 |
| **Chain of Responsibility** | Validation pipeline (IC → multicol → CPCV → DSR) | Each stage can reject a feature | [refactoring.guru/chain-of-responsibility](https://refactoring.guru/design-patterns/chain-of-responsibility); GoF (1994) Ch. 5 |

### 4.3 Clean Code Practices

| Practice | Reference | Application |
|---|---|---|
| One level of abstraction per function | Martin (2008) Ch. 3 | `FeaturePipeline.run()` delegates to sub-methods |
| Meaningful names | Martin (2008) Ch. 2 | `ic_mean`, not `val1`; `har_rv_residual`, not `res` |
| Small classes, small functions | Martin (2008) Ch. 10 | Each calculator is < 100 LOC |
| No side effects | Martin (2008) Ch. 3 | All calculators are pure: DataFrame in, DataFrame out |
| Error handling as first-class citizen | Martin (2008) Ch. 7 | Return `None` or empty DataFrame on insufficient data |
| Don't Repeat Yourself (DRY) | Hunt & Thomas (2019) Ch. 2 | IC measurement centralized in `ICMeasurer` |
| Bounded contexts | Evans (2003) Ch. 14 | `features/` is a separate bounded context from `services/` |

### 4.4 Clean Architecture Layers

Following Martin (2017) Ch. 22:

```
┌─────────────────────────────────────────────────────┐
│                    Entities Layer                     │
│  FeatureCalculator ABC, ICResult, ICMetric,          │
│  PurgeEmbargo, FeatureVersion                        │
│  (pure domain logic, no external dependencies)       │
├─────────────────────────────────────────────────────┤
│                   Use Cases Layer                     │
│  FeaturePipeline, CrossValidator, DSR/PBO,           │
│  MulticollinearityAnalyzer, ReportGenerator          │
│  (application-specific business rules)               │
├─────────────────────────────────────────────────────┤
│              Interface Adapters Layer                 │
│  S02FeatureAdapter, FeatureStore (TimescaleDB impl), │
│  CLI commands for running validation                 │
│  (converts data between layers)                      │
├─────────────────────────────────────────────────────┤
│          Frameworks & Drivers Layer                   │
│  Polars, NumPy, AsyncPG, Redis, TimescaleDB          │
│  (external tools and infrastructure)                 │
└─────────────────────────────────────────────────────┘
```

---

## 5. Anti-Patterns in Signal Validation

Each anti-pattern is a trap that can invalidate months of validation work. Phase 3
must be designed to make these errors structurally impossible.

### 5.1 Look-Ahead Bias

**Definition**: Using information that would not have been available at prediction time.

**Example**: Computing a moving average using data from both before and after the
prediction timestamp, or using tomorrow's close to label today's sample.

**How Phase 3 prevents it**:
- `FeatureStore.load()` enforces point-in-time queries via the `as_of` parameter.
- `TripleBarrierLabeler` uses only past prices for barrier computation.
- `FeatureCalculator.compute()` receives data sorted chronologically and cannot access
  future rows (enforced by Polars column-oriented processing).

**Reference**: Lopez de Prado (2018), Ch. 7; Harvey & Liu (2015).

### 5.2 Survivorship Bias

**Definition**: Only analyzing assets that exist today, ignoring those that were delisted,
acquired, or went bankrupt.

**Example**: Testing a momentum strategy on current S&P 500 constituents. The ones that
are in the index today are the ones that did well -- the ones that failed were removed.

**How Phase 3 prevents it**:
- Phase 2 `Asset` model includes `delisting_date` field. Feature validation includes
  all assets that were active during the test period, not just current ones.
- Report documents the asset universe explicitly.

**Reference**: Brown, S. J., Goetzmann, W. N., Ibbotson, R. G. & Ross, S. A. (1992).
"Survivorship Bias in Performance Studies". *Review of Financial Studies*, 5(4), 553-580.

### 5.3 Snooping Bias (Data Mining Bias)

**Definition**: Testing many hypotheses on the same dataset and reporting only the
best result.

**Example**: Testing 100 parameter combinations of an RSI strategy, then reporting
only the Sharpe of the best one without adjusting for multiple testing.

**How Phase 3 prevents it**:
- Phase 3.11 mandates DSR correction for all features tested.
- Phase 3.12 report documents ALL features tested, not just the best.
- ADR-0002 requires reporting the number of trials alongside any Sharpe claim.

**Reference**: Harvey, Liu & Zhu (2016); White (2000); Hansen (2005).

### 5.4 Overfitting

**Definition**: A model that learns the noise in the training data rather than the
underlying signal, producing excellent in-sample performance but poor OOS.

**Example**: A neural network that achieves 95% accuracy on training data but 50% on
new data.

**How Phase 3 prevents it**:
- CPCV (Phase 3.10) with purging ensures strict train/test separation.
- PBO (Phase 3.11) directly measures the probability of overfitting.
- Simple models preferred (linear IC measurement, not deep learning).
- Feature count is kept small (6 candidates, expect 3-4 survivors).

**Reference**: Lopez de Prado (2018), Ch. 11; Bailey et al. (2014).

### 5.5 Backtest Overfitting (The Cardinal Sin)

**Definition**: Selecting the best strategy among many backtested variants without
correcting for the selection process itself.

**Example**: Testing 1,000 parameter combinations, finding one with Sharpe 2.5,
and declaring it validated. With 1,000 trials, Sharpe 2.5 can arise by chance.

**How Phase 3 prevents it**:
- PBO computation (Phase 3.11) is MANDATORY (ADR-0002).
- PBO < 0.50 required to retain a feature.
- DSR deflates the Sharpe by the number of trials.
- The feature selection report (Phase 3.12) documents the total number of features
  and parameter combinations tested.

**Reference**: Bailey, Borwein, Lopez de Prado & Zhu (2014); Bailey & Lopez de Prado
(2014); Harvey & Liu (2015).

### 5.6 In-Sample vs Out-of-Sample Confusion

**Definition**: Failing to maintain a strict separation between the data used to develop
a strategy and the data used to evaluate it.

**Example**: Tuning a feature's parameters on 2020-2023 data, then "validating" on
a subset of 2020-2023 that was excluded from parameter tuning but was visible during
development.

**How Phase 3 prevents it**:
- CPCV with purging (Phase 3.10) ensures strict temporal separation.
- Embargo period prevents information leakage from autocorrelation.
- Walk-forward analysis uses expanding windows, never backward-looking.
- No parameter tuning on the combined dataset; parameters are set per-fold.

**Reference**: Lopez de Prado (2018), Ch. 7, 12; Pardo (2008).

### 5.7 Single Backtest Fallacy

**Definition**: Making decisions based on a single train/test split rather than
evaluating across multiple configurations.

**Example**: Splitting data 70/30 once and declaring the feature validated on the
30% OOS set.

**How Phase 3 prevents it**:
- CPCV generates C(N,k) combinatorial splits (default: C(6,2) = 15 paths).
- IC is averaged across ALL paths, not cherry-picked from the best path.
- IC_IR (IC / std(IC) across paths) measures path-to-path stability.

**Reference**: Lopez de Prado (2018), Ch. 12; Bailey et al. (2017).

### 5.8 Cherry-Picking

**Definition**: Selectively reporting favorable results while omitting unfavorable ones.

**Example**: Reporting that a feature works on BTC but not mentioning it fails on
ETH, SPY, and QQQ.

**How Phase 3 prevents it**:
- Feature selection report (Phase 3.12) documents results for ALL assets tested.
- Report template is enforced: every feature must show IC for every asset.
- If a feature works only on one asset, it is flagged as "asset-specific" with
  reduced confidence.

**Reference**: Harvey, Liu & Zhu (2016); Arnott et al. (2019).

### 5.9 Data Leakage in Cross-Fold Validation

**Definition**: Information from the test fold leaking into the training fold through
overlapping time windows or shared samples.

**Example**: In standard k-fold CV on time series, fold 3's training set includes
data from both before and after fold 3's test period. This means the model trains
on "future" data relative to some test samples.

**How Phase 3 prevents it**:
- CPCV with purging (Phase 3.10) removes all training samples whose labels overlap
  with any test sample.
- Embargo adds a gap between train and test to break autocorrelation.
- `PurgeEmbargo.purge()` is unit-tested with synthetic overlap scenarios.

**Reference**: Lopez de Prado (2018), Ch. 7; Bailey & Lopez de Prado (2017).

---

## 6. Persistent Claude Memory System

Phase 3 will span multiple Claude Code sessions over 3-4 weeks. Without a persistence
mechanism, each session starts from zero context. This section specifies a file-based
memory system in the repository.

### 6.1 Directory Structure

```
docs/claude_memory/
├── SESSIONS.md          # Chronological log of Claude Code sessions
├── DECISIONS.md         # Architectural decisions (mini-ADRs)
├── CONTEXT.md           # Current project state snapshot
├── PHASE_3_NOTES.md     # Phase 3-specific notes and findings
└── templates/
    ├── SESSION_TEMPLATE.md
    └── DECISION_TEMPLATE.md
```

### 6.2 Integration Rules

**Rule 1 -- Pre-Session Context Loading**:
Every Claude Code session that touches Phase 3 code MUST begin with:
```
Step 1bis: Read docs/claude_memory/CONTEXT.md AND docs/claude_memory/PHASE_3_NOTES.md
```

**Rule 2 -- Post-Session Logging**:
Every Claude Code session MUST end with:
```
Final step: Append a session entry to docs/claude_memory/SESSIONS.md
```

**Rule 3 -- Decision Recording**:
Any architectural decision made during a session MUST be recorded in
`docs/claude_memory/DECISIONS.md` using the decision template.

### 6.3 File Specifications

See `docs/claude_memory/` for initial files created alongside this document.

---

## 7. Managed Agents for Phase 3

### Budget context

The user has a budget of $0-20/month for managed agents. All proposals must be
honest about costs and justified by concrete value.

### 7.1 Agent: `apex-paper-watcher` (P0 -- Deploy Now)

| Field | Value |
|---|---|
| Name | `apex-paper-watcher` |
| Trigger | Weekly, Monday 8:00 UTC |
| Model | Claude Sonnet 4.6 |
| Cost | ~$2-4/month |
| Priority | P0 |

**Description**: Scans arXiv q-fin.ST, q-fin.TR, and SSRN Financial Economics for new
papers relevant to APEX Phase 3 features (HAR-RV, rough vol, OFI, microstructure, GEX).
Produces a brief in `docs/veille/YYYY-MM-DD-phase3-brief.md`.

**Inputs**: arXiv/SSRN search queries for Phase 3 keywords.
**Outputs**: Markdown brief with 3-5 relevant papers, each rated by APEX relevance.

**Activation roadmap**: Deploy during Phase 3.1. Value: catches new methodological
improvements before feature validation is complete.

### 7.2 Agent: `apex-codebase-analyzer` (P0 -- Deploy Now)

| Field | Value |
|---|---|
| Name | `apex-codebase-analyzer` |
| Trigger | Weekly, Sunday 20:00 UTC |
| Model | Claude Haiku 4.5 |
| Cost | ~$1-3/month |
| Priority | P0 |

**Description**: Runs incremental audit on the `features/` package added during Phase 3.
Checks: test coverage, mypy compliance, docstring presence, SOLID violations, forbidden
patterns (float, print, threading). Reports findings to `docs/audits/incremental/`.

**Inputs**: Git diff since last run.
**Outputs**: Incremental audit report.

**Activation roadmap**: Deploy after Phase 3.1 merges (code exists to audit).

### 7.3 Agent: `apex-feature-tester` (P1 -- Phase 3.3+)

| Field | Value |
|---|---|
| Name | `apex-feature-tester` |
| Trigger | On-demand (when new data arrives or feature changes) |
| Model | Claude Sonnet 4.6 |
| Cost | ~$3-5/run (~$10-15/month if triggered biweekly) |
| Priority | P1 (may exceed budget; defer if necessary) |

**Description**: Runs the IC measurement pipeline on a specific feature against the
latest data. Produces IC report and compares to previous baseline. Alerts if IC
degrades > 20%.

**Inputs**: Feature name, symbol, date range.
**Outputs**: IC report JSON + Markdown.

**Activation roadmap**: Deploy after Phase 3.3 (IC framework ready). **WARNING**: at
~$10-15/month, this may push total agent budget to $15-22/month, near the upper bound.
Consider running manually instead.

### 7.4 Agent: `apex-academic-coherence-checker` (P1 -- Phase 3.4+)

| Field | Value |
|---|---|
| Name | `apex-academic-coherence-checker` |
| Trigger | On each PR to `features/` |
| Model | Claude Haiku 4.5 |
| Cost | ~$1-2/month |
| Priority | P1 |

**Description**: Verifies that every `FeatureCalculator` class docstring cites the
originating academic paper, that the mathematical formula matches the paper, and that
the implementation is consistent with the cited reference.

**Inputs**: PR diff in `features/`.
**Outputs**: PR comment with coherence check results.

**Activation roadmap**: Deploy after Phase 3.4 (first feature calculator exists).

### Budget Summary

| Agent | Monthly Cost | Priority |
|---|---|---|
| apex-paper-watcher | $2-4 | P0 |
| apex-codebase-analyzer | $1-3 | P0 |
| apex-feature-tester | $10-15 | P1 (may exceed budget) |
| apex-academic-coherence-checker | $1-2 | P1 |
| **Total P0** | **$3-7** | |
| **Total P0+P1** | **$14-24** | Near budget ceiling |

**Recommendation**: Deploy P0 agents immediately ($3-7/month). Evaluate P1 agents
after Phase 3.3 based on actual budget headroom.

---

## 8. Tier-1 Tooling Evaluation

### 8.1 vectorbt PRO ($400/year)

| Field | Assessment |
|---|---|
| What it does | Vectorized backtesting framework with portfolio simulation |
| Relevance to Phase 3 | LOW -- Phase 3 validates features, not strategies. vectorbt is more relevant for Phase 5 |
| ROI | Negative for Phase 3; potentially positive for Phase 5 |
| Alternative | Custom IC pipeline with Polars + NumPy (free, already in stack) |
| **Recommendation** | **DEFER to Phase 5 evaluation. Do NOT purchase for Phase 3.** |

### 8.2 Hypothesis Property Tests (Free)

| Field | Assessment |
|---|---|
| What it does | Property-based testing for mathematical functions |
| Relevance to Phase 3 | HIGH -- every IC computation, VIF, DSR must satisfy mathematical invariants |
| ROI | High. Catches edge cases that example-based tests miss |
| Integration | Already in `pyproject.toml` as dev dependency; extend to `features/` |
| **Recommendation** | **USE extensively. Mandate for all math in features/.** |

Key Hypothesis strategies for Phase 3:
- IC always in [-1, +1]: `@given(st.lists(st.floats(-100, 100), min_size=30))`
- VIF always >= 1.0
- Kyle lambda always >= 0
- DSR <= PSR (deflation can only reduce)
- PBO in [0, 1]
- CPCV fold count = C(n_groups, n_test_groups)

### 8.3 Jupyter Notebooks (Free)

| Field | Assessment |
|---|---|
| What it does | Interactive exploration and visualization |
| Relevance to Phase 3 | MEDIUM -- useful for exploratory analysis before formalizing in tests |
| ROI | Moderate. Risk: notebooks become the "real" validation instead of automated tests |
| Integration | Create `notebooks/phase3/` directory with templates |
| **Recommendation** | **USE for exploration only. All validation logic MUST be in tested Python.** |

Usage guidelines:
- Notebooks are for visual exploration and presenting results.
- NO validation logic lives solely in notebooks.
- Every insight from a notebook must be codified in a `test_*.py` file.
- Notebooks are NOT version-controlled for CI (too large, too variable).

### 8.4 DVC (Free)

| Field | Assessment |
|---|---|
| What it does | Data Version Control -- version large data files alongside git |
| Relevance to Phase 3 | LOW -- Phase 3 data lives in TimescaleDB, not flat files |
| ROI | Low for current architecture. Useful if we switch to flat-file features |
| Alternative | Feature Store versioning (Phase 3.2) handles version tracking |
| **Recommendation** | **SKIP for Phase 3. Re-evaluate if flat-file features become common.** |

---

## 9. Execution Roadmap

### 9.1 Dependency Graph

```
Week 1:
  3.1 (Pipeline Foundation) ──────────────────────────┐
                                                       │
Week 1-2:                                             │
  3.2 (Feature Store) ─────── depends on 3.1 ────────┤
  3.3 (IC Measurement) ────── depends on 3.1, 3.2 ───┤
                                                       │
Week 2 (parallelizable):                              │
  3.4 (HAR-RV) ──────────── depends on 3.1, 3.3 ─────┤
  3.5 (Rough Vol) ────────── depends on 3.1, 3.3 ─────┤  ← can run in parallel
  3.6 (OFI) ─────────────── depends on 3.1, 3.3 ─────┤
  3.7 (CVD + Kyle) ──────── depends on 3.1, 3.3, 3.6 ─┤
  3.8 (GEX) ─────────────── depends on 3.1, 3.3 ─────┤
                                                       │
Week 3:                                               │
  3.9 (Multicollinearity) ── depends on 3.4-3.8 ─────┤
  3.10 (CPCV) ──────────── depends on 3.1, 3.3, 3.9 ──┤
  3.11 (DSR/PBO) ─────────── depends on 3.10 ─────────┤
                                                       │
Week 3-4:                                             │
  3.12 (Feature Report) ──── depends on 3.4-3.11 ────┤
  3.13 (S02 Integration) ─── depends on 3.12 ─────────┘
```

### 9.2 Week-by-Week Plan

| Week | Sub-Phases | Key Milestone |
|---|---|---|
| Week 1 | 3.1, 3.2, 3.3 | IC framework operational; first feature IC measured |
| Week 2 | 3.4, 3.5, 3.6, 3.7, 3.8 | All 6 features individually validated |
| Week 3 | 3.9, 3.10, 3.11 | Multicollinearity clean; CPCV + DSR/PBO computed |
| Week 4 | 3.12, 3.13 | Final report; S02 adapter ready for Phase 4 |

### 9.3 Parallelization Opportunities

Sub-phases 3.4 through 3.8 (individual feature validation) are **fully parallelizable**
because each feature calculator is independent. In practice, with a single developer,
2-3 features can be validated per day.

### 9.4 Milestones

| Milestone | Definition | Expected Date |
|---|---|---|
| M1: Pipeline Operational | 3.1 + 3.2 + 3.3 merged; first IC computed | End of Week 1 |
| M2: All Features Validated | 3.4-3.8 merged; individual IC results available | End of Week 2 |
| M3: Statistical Rigor Complete | 3.9-3.11 merged; CPCV + DSR + PBO computed | End of Week 3 |
| M4: Phase 3 Complete | 3.12 + 3.13 merged; feature selection report published | End of Week 4 |

### 9.5 Risk Management

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| All features have IC < 0.02 | Medium | High | Document honestly; Phase 4 re-scopes features |
| GEX data unavailable (paid APIs) | High | Medium | Validate GEX with synthetic data; defer live validation |
| CPCV too slow on large datasets | Low | Medium | Reduce n_groups; subsample; parallelize folds |
| Session context lost between Claude Code sessions | Medium | Medium | Claude memory system (Section 6) |
| Scope creep: building backtesting during Phase 3 | Medium | High | Phase 3 measures IC, NOT strategy performance |

---

## 10. Decision Matrix: Cleared for Phase 3.1

| Criterion | Status | Reference |
|---|---|---|
| Audit whole-codebase Cleared | YES (0 P0) | #55 |
| Audit meta-governance Cleared | YES (3 P0 docs, non-blocking) | #59 |
| Phase 3 design specification complete | YES (this document) | #61 |
| Academic references Tier-1 validated | YES (50+ references) | Section 11 |
| Architecture validated | YES (Section 3) | ABCs, patterns, DI |
| SOLID patterns identified | YES (Section 4) | 10 patterns with refactoring.guru |
| Anti-patterns documented | YES (Section 5) | 9 anti-patterns |
| Persistent Claude memory in place | YES (Section 6) | `docs/claude_memory/` |
| Managed agents prioritized | YES (Section 7) | 2 P0, 2 P1 |
| Tier-1 tools evaluated | YES (Section 8) | 4 tools assessed |
| Roadmap Phase 3 sequenced | YES (Section 9) | 4-week plan |
| Risk management documented | YES (Section 9.5) | 5 risks identified |

**DECISION: CLEARED FOR PHASE 3.1 EXECUTION.**

---

## 11. Bibliography

### Financial Econometrics and Volatility Modeling

1. Andersen, T. G., Bollerslev, T., Diebold, F. X. & Labys, P. (2003). "Modeling and Forecasting Realized Volatility". *Econometrica*, 71(2), 579-625.
2. Barndorff-Nielsen, O. E. & Shephard, N. (2004). "Power and Bipower Variation with Stochastic Volatility and Jumps". *Journal of Financial Econometrics*, 2(1), 1-37.
3. Bollerslev, T. (1986). "Generalized Autoregressive Conditional Heteroskedasticity". *Journal of Econometrics*, 31(3), 307-327.
4. Bollerslev, T., Patton, A. J. & Quaedvlieg, R. (2016). "Exploiting the Errors: A Simple Approach for Improved Volatility Forecasting". *Journal of Econometrics*, 192(1), 1-18.
5. Corsi, F. (2009). "A Simple Approximate Long-Memory Model of Realized Volatility". *Journal of Financial Econometrics*, 7(2), 174-196. DOI: 10.1093/jjfinec/nbp001.
6. Engle, R. F. (1982). "Autoregressive Conditional Heteroscedasticity with Estimates of the Variance of United Kingdom Inflation". *Econometrica*, 50(4), 987-1007.
7. Patton, A. J. & Sheppard, K. (2015). "Good Volatility, Bad Volatility: Signed Jumps and the Persistence of Volatility". *Review of Economics and Statistics*, 97(3), 683-697.

### Rough Volatility

8. Bayer, C., Friz, P. & Gatheral, J. (2016). "Pricing under rough volatility". *Quantitative Finance*, 16(6), 887-904. DOI: 10.1080/14697688.2015.1099717.
9. El Euch, O. & Rosenbaum, M. (2019). "The characteristic function of rough Heston models". *Mathematical Finance*, 29(1), 3-38.
10. Fukasawa, M. (2011). "Asymptotic analysis for stochastic volatility: Martingale expansion". *Finance and Stochastics*, 15(4), 635-654.
11. Gatheral, J., Jaisson, T. & Rosenbaum, M. (2018). "Volatility is rough". *Quantitative Finance*, 18(6), 933-949. DOI: 10.1080/14697688.2017.1393551.

### Market Microstructure and Order Flow

12. Bouchaud, J.-P., Bonart, J., Donier, J. & Gould, M. (2018). *Trades, Quotes and Prices: Financial Markets Under the Microscope*. Cambridge University Press.
13. Cartea, A., Jaimungal, S. & Penalva, J. (2015). *Algorithmic and High-Frequency Trading*. Cambridge University Press.
14. Cont, R. (2001). "Empirical properties of asset returns: stylized facts and statistical issues". *Quantitative Finance*, 1(2), 223-236.
15. Cont, R. (2011). "Statistical Modeling of High-Frequency Financial Data". *IEEE Signal Processing Magazine*, 28(5), 16-25.
16. Cont, R., Kukanov, A. & Stoikov, S. (2014). "The Price Impact of Order Book Events". *Journal of Financial Economics*, 104(2), 293-320. DOI: 10.1016/j.jfineco.2012.01.001.
17. Easley, D. & O'Hara, M. (1987). "Price, Trade Size, and Information in Securities Markets". *Journal of Financial Economics*, 19(1), 69-90.
18. Hasbrouck, J. (2007). *Empirical Market Microstructure*. Oxford University Press.
19. Kyle, A. S. (1985). "Continuous Auctions and Insider Trading". *Econometrica*, 53(6), 1315-1335.
20. Lee, C. M. C. & Ready, M. J. (1991). "Inferring Trade Direction from Intraday Data". *Journal of Finance*, 46(2), 733-746.
21. O'Hara, M. (1995). *Market Microstructure Theory*. Blackwell.

### Options and Gamma Exposure

22. Avellaneda, M. & Lipkin, M. D. (2003). "A market-induced mechanism for stock pinning". *Quantitative Finance*, 3(6), 417-425.
23. Barbon, A. & Buraschi, A. (2020). "Gamma Fragility". Working paper, University of St. Gallen.
24. Bollen, N. P. B. & Whaley, R. E. (2004). "Does Net Buying Pressure Affect the Shape of Implied Volatility Functions?". *Journal of Finance*, 59(2), 711-753.
25. Ni, S. X., Pearson, N. D. & Poteshman, A. M. (2005). "Stock Price Clustering on Option Expiration Dates". *Journal of Financial Economics*, 78(1), 49-87.

### Statistical Testing, Backtesting, and Overfitting

26. Arlot, S. & Celisse, A. (2010). "A survey of cross-validation procedures for model selection". *Statistics Surveys*, 4, 40-79.
27. Bailey, D. H. & Lopez de Prado, M. (2012). "The Sharpe Ratio Efficient Frontier". *Journal of Risk*, 15(2), 3-44.
28. Bailey, D. H. & Lopez de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality". *Journal of Portfolio Management*, 40(5), 94-107.
29. Bailey, D. H., Borwein, J. M., Lopez de Prado, M. & Zhu, Q. J. (2014). "The Probability of Backtest Overfitting". *Journal of Computational Finance*.
30. Bailey, D. H., Borwein, J. M., Lopez de Prado, M. & Zhu, Q. J. (2017). "The Probability of Backtest Overfitting". *Journal of Computational Finance*, 20(4), 39-69.
31. Hansen, P. R. (2005). "A Test for Superior Predictive Ability". *Journal of Business & Economic Statistics*, 23(4), 365-380.
32. Harvey, C. R. & Liu, Y. (2015). "Backtesting". *Journal of Portfolio Management*, 42(1), 13-28.
33. Harvey, C. R., Liu, Y. & Zhu, H. (2016). "...and the Cross-Section of Expected Returns". *Review of Financial Studies*, 29(1), 5-68. DOI: 10.1093/rfs/hhv059.
34. Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies* (2nd ed.). Wiley.
35. White, H. (2000). "A Reality Check for Data Snooping". *Econometrica*, 68(5), 1097-1126.

### Portfolio Management and Factor Models

36. Almgren, R. & Chriss, N. (2001). "Optimal execution of portfolio transactions". *Journal of Risk*, 3(2), 5-40.
37. Arnott, R. D., Harvey, C. R., Kalesnik, V. & Linnainmaa, J. T. (2019). "Reports of Value's Death May Be Greatly Exaggerated". *Financial Analysts Journal*, 75(4), 36-52.
38. Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio Management* (2nd ed.). McGraw-Hill.
39. Gu, S., Kelly, B. & Xiu, D. (2020). "Empirical Asset Pricing via Machine Learning". *Review of Financial Studies*, 33(5), 2223-2273. DOI: 10.1093/rfs/hhaa009.
40. Israel, R., Kelly, B. T. & Moskowitz, T. J. (2020). "Can Machines 'Learn' Finance?". *Journal of Investment Management*, 18(2), 23-36.
41. Kakushadze, Z. (2016). "101 Formulaic Alphas". *Wilmott*, 2016(84), 72-81.
42. Kelly, J. L. (1956). "A New Interpretation of Information Rate". *Bell System Technical Journal*, 35(4), 917-926.
43. Lo, A. W. & MacKinlay, A. C. (1988). "Stock Market Prices Do Not Follow Random Walks: Evidence from a Simple Specification Test". *Review of Financial Studies*, 1(1), 41-66.
44. Politis, D. N. & Romano, J. P. (1994). "The Stationary Bootstrap". *JASA*, 89(428), 1303-1313.
45. Qian, E., Hua, R. & Sorensen, E. (2007). *Quantitative Equity Portfolio Management*. Chapman & Hall/CRC.

### Statistics and Machine Learning

46. Belsley, D. A., Kuh, E. & Welsch, R. E. (1980). *Regression Diagnostics: Identifying Influential Data and Sources of Collinearity*. Wiley.
47. Friedman, J. H. (2001). "Greedy Function Approximation: A Gradient Boosting Machine". *Annals of Statistics*, 29(5), 1189-1232.
48. Hosking, J. R. M. (1981). "Fractional differencing". *Biometrika*, 68(1), 165-176.
49. Tibshirani, R. (1996). "Regression Shrinkage and Selection via the Lasso". *JRSSB*, 58(1), 267-288.

### Survivorship and Bias

50. Brown, S. J., Goetzmann, W. N., Ibbotson, R. G. & Ross, S. A. (1992). "Survivorship Bias in Performance Studies". *Review of Financial Studies*, 5(4), 553-580.

### Machine Learning Systems

51. Sculley, D. et al. (2015). "Hidden Technical Debt in Machine Learning Systems". *NeurIPS*, 2503-2511.

### Software Engineering

52. Evans, E. (2003). *Domain-Driven Design: Tackling Complexity in the Heart of Software*. Addison-Wesley.
53. Fowler, M. (2002). *Patterns of Enterprise Application Architecture*. Addison-Wesley.
54. Fowler, M. (2018). *Refactoring: Improving the Design of Existing Code* (2nd ed.). Addison-Wesley.
55. Gamma, E., Helm, R., Johnson, R. & Vlissides, J. (1994). *Design Patterns: Elements of Reusable Object-Oriented Software*. Addison-Wesley.
56. Hunt, A. & Thomas, D. (2019). *The Pragmatic Programmer* (20th Anniversary ed.). Addison-Wesley.
57. Kleppmann, M. (2017). *Designing Data-Intensive Applications*. O'Reilly.
58. Martin, R. C. (2008). *Clean Code: A Handbook of Agile Software Craftsmanship*. Prentice Hall.
59. Martin, R. C. (2017). *Clean Architecture: A Craftsman's Guide to Software Structure and Design*. Prentice Hall.

### Data Infrastructure

60. Cochrane, J. H. (2005). *Asset Pricing* (Revised Edition). Princeton University Press.

---

*Document produced by Claude Opus 4.6, orchestrated by Clement Barbier, 2026-04-11.*
*Reference: Issue #61. Gate decision: CLEARED for Phase 3.1.*
