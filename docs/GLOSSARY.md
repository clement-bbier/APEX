# APEX Glossary

Centralized definitions for all specialized terms, acronyms, and concepts used in the
APEX trading system. Organized by domain. For each term, a brief definition (2-4 lines)
and academic reference when applicable.

**Companion to**: `CLAUDE.md`, `MANIFEST.md`, `docs/adr/0002-quant-methodology-charter.md`

---

## Table of Contents

1. [Architecture and Infrastructure](#1-architecture-and-infrastructure)
2. [Statistical Validation (Quant)](#2-statistical-validation-quant)
3. [Market Microstructure](#3-market-microstructure)
4. [Volatility Modeling](#4-volatility-modeling)
5. [Machine Learning for Finance](#5-machine-learning-for-finance)
6. [Risk Management](#6-risk-management)
7. [Execution and Portfolio](#7-execution-and-portfolio)
8. [Macro and Central Banks](#8-macro-and-central-banks)

---

## 1. Architecture and Infrastructure

### S01 -- S10 (Services)

APEX is built as 10 microservices communicating via ZMQ PUB/SUB and Redis:

| ID | Name | Role |
|---|---|---|
| **S01** | Data Ingestion | Real-time and historical data ingestion from all sources (Alpaca, Binance, Yahoo, FRED, ECB, BoJ, EDGAR, SimFin) |
| **S02** | Signal Engine | Computes trading signals from normalized ticks using weighted confluence of indicators |
| **S03** | Regime Detector | Identifies market regimes (trending/ranging, vol state, risk-on/risk-off) via HMM |
| **S04** | Fusion Engine | Combines signals with regime context, applies Kelly sizing and meta-labeling |
| **S05** | Risk Manager | Non-bypassable veto layer: circuit breaker, position rules, exposure monitor |
| **S06** | Execution Engine | Order lifecycle management, multi-broker routing (Alpaca, Binance), fill tracking |
| **S07** | Quant Analytics | Pure statistical functions: Hurst, GARCH, Hawkes, Monte Carlo, HAR-RV, rough vol |
| **S08** | Macro Intelligence | Central bank calendars, geopolitical events, trading session management |
| **S09** | Feedback Loop | Signal quality tracking, Kelly win-rate/RR stats, drift detection |
| **S10** | Monitor Dashboard | Read-only Streamlit web dashboard for system monitoring |

### ZMQ Broker (XSUB/XPUB)

ZeroMQ Extended Subscriber/Publisher socket pair acting as a centralized message broker.
All services CONNECT to the broker (never BIND). Defined in `core/zmq_broker.py`.
Topology decision documented in ADR-0001.

### Redis State

In-memory key-value store used for inter-service state sharing, heartbeats, circuit
breaker persistence, and caching. Services read/write state via `core.state.StateStore`.

### TimescaleDB

PostgreSQL extension for time-series data. Stores all historical bars, ticks, macro
series, and calendar events in a universal schema with hypertables and compression.
Schema defined in ADR-0003.

### Rust Extensions (PyO3)

Two Rust crates exposed to Python via PyO3/maturin for CPU-bound hot paths:
- **apex_mc** -- Monte Carlo simulation engine
- **apex_risk** -- Risk chain computations (target p99 < 5ms)

### BaseService

Abstract base class (`core.base_service.BaseService`) that all 10 services inherit from.
Provides ZMQ subscription, heartbeat loop, graceful shutdown, and structured logging.

### Immutable Data Pipeline

The chain `Tick -> NormalizedTick -> Signal -> OrderCandidate -> ApprovedOrder ->
ExecutedOrder -> TradeRecord`. Each stage produces a new frozen Pydantic v2 object.
No mutations allowed.

---

## 2. Statistical Validation (Quant)

### PSR -- Probabilistic Sharpe Ratio

Probability that the true Sharpe ratio exceeds a benchmark, accounting for skewness and
kurtosis of returns. Corrects the naive assumption that returns are Gaussian.
**Ref**: Bailey, D.H. & Lopez de Prado, M. (2012). "The Sharpe Ratio Efficient Frontier".
*Journal of Risk*, 15(2), 3-44.

### DSR -- Deflated Sharpe Ratio

Adjusts the observed Sharpe ratio for the number of trials (strategies tested). If you
test 100 strategies and pick the best, DSR deflates that Sharpe to account for selection
bias. Essential for multiple hypothesis correction.
**Ref**: Bailey, D.H. & Lopez de Prado, M. (2014). "The Deflated Sharpe Ratio".
*Journal of Portfolio Management*, 40(5), 94-107.

### PBO -- Probability of Backtest Overfitting

Probability that the best in-sample strategy underperforms the median out-of-sample.
Computed via CPCV. A PBO > 0.5 means overfitting is more likely than not.
**Ref**: Bailey, D.H., Borwein, J.M., Lopez de Prado, M. & Zhu, Q.J. (2014).
"The Probability of Backtest Overfitting". *Journal of Computational Finance*.

### CPCV -- Combinatorial Purged Cross-Validation

Cross-validation method that generates all C(N,k) train/test combinations with purging
(removing contaminated samples near the boundary) and embargo (gap after test set).
APEX uses C(6,2) = 15 folds. Mandatory per ADR-0002.
**Ref**: Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*, Ch. 12. Wiley.

### IC -- Information Coefficient

Spearman rank correlation between predicted and realized returns. Measures a feature's
directional predictive power. APEX acceptance threshold: |IC| > 0.02.
**Ref**: Grinold, R.C. & Kahn, R.N. (1999). *Active Portfolio Management* (2nd ed.).
McGraw-Hill.

### IC_IR -- Information Coefficient Information Ratio

IC divided by the standard deviation of IC over time: `IC_IR = mean(IC) / std(IC)`.
Measures stability of predictive power. APEX threshold: IC_IR > 0.5.
**Ref**: Grinold & Kahn (1999).

### MinTRL -- Minimum Track Record Length

Minimum number of observations required for a Sharpe ratio to be statistically
distinguishable from zero at a given confidence level. Prevents premature conclusions
from short track records.
**Ref**: Bailey, D.H. & Lopez de Prado, M. (2012).

### Sharpe Ratio

Risk-adjusted return: `SR = (R_p - R_f) / sigma_p`. The most common performance metric,
but misleading without PSR/DSR correction. Named after William Sharpe (Nobel 1990).
**Ref**: Sharpe, W.F. (1966). "Mutual Fund Performance". *Journal of Business*, 39(1).

### Sortino Ratio

Like Sharpe but uses downside deviation instead of total volatility. Penalizes only
negative returns, not upside volatility.
**Ref**: Sortino, F.A. & van der Meer, R. (1991). "Downside Risk".
*Journal of Portfolio Management*, 17(4).

### Calmar Ratio

Annualized return divided by maximum drawdown. Measures return per unit of worst-case
loss. Useful for strategies where drawdown management is critical.

### Ulcer Index

Square root of the mean squared drawdown over a period. Captures both depth and duration
of drawdowns. More nuanced than max drawdown alone.
**Ref**: Martin, P. & McCann, B. (1989). *The Investor's Guide to Fidelity Funds*. Wiley.

### Sharpe Efficient Frontier

Curve of maximum achievable Sharpe ratio for a given number of independent trials.
Used to benchmark whether a strategy search has extracted available alpha efficiently.
**Ref**: Bailey & Lopez de Prado (2012).

---

## 3. Market Microstructure

### OFI -- Order Flow Imbalance

Net difference between buy-initiated and sell-initiated order flow at the best bid/ask.
Measures short-term directional pressure on price. Computed from trade-by-trade data.
**Ref**: Cont, R., Kukanov, A. & Stoikov, S. (2014). "The Price Impact of Order Book
Events". *Journal of Financial Econometrics*, 12(1), 47-88.

### CVD -- Cumulative Volume Delta

Running sum of (buy volume - sell volume) over time. Tracks whether aggressive buying
or selling dominates. Divergence between CVD and price suggests hidden absorption.

### Kyle Lambda

Measures market depth (price impact per unit of order flow). High lambda = illiquid
market where trades move price significantly. Estimated from regression of price change
on signed order flow.
**Ref**: Kyle, A.S. (1985). "Continuous Auctions and Insider Trading".
*Econometrica*, 53(6), 1315-1335.

### VPIN -- Volume-synchronized Probability of Informed Trading

Estimates the probability of informed trading using volume-bucketed bars (not time bars).
Spikes in VPIN precede flash crashes and periods of high toxicity.
**Ref**: Easley, D., Lopez de Prado, M. & O'Hara, M. (2012). "Flow Toxicity and
Liquidity in a High-Frequency World". *Review of Financial Studies*, 25(5), 1457-1493.

### Bid-Ask Spread

Difference between the best ask and best bid price. Proxy for transaction cost and
liquidity. Wider spreads indicate less liquid markets.

### Mid-Price

Average of the best bid and best ask: `mid = (bid + ask) / 2`. Reference price for
most microstructure calculations.

### Tick Data

Trade-by-trade records at the finest granularity: timestamp, price, volume, aggressor
side. The raw input for S01 data ingestion and S02 signal computation.

### Order Book Imbalance

Ratio of volume at best bid vs. best ask: `OBI = (V_bid - V_ask) / (V_bid + V_ask)`.
Positive OBI suggests buying pressure. Related to but distinct from OFI.

### Toxicity

Measure of adverse selection risk for market makers. High toxicity means informed
traders dominate the order flow. Captured by VPIN and Kyle lambda.

---

## 4. Volatility Modeling

### HAR-RV -- Heterogeneous Autoregressive Realized Volatility

Forecasts realized volatility using a cascade of lagged components: daily RV, weekly RV,
and monthly RV. Captures the heterogeneous behavior of market participants operating on
different time horizons. S07 implements `har_rv_forecast()`.
**Ref**: Corsi, F. (2009). "A Simple Approximate Long-Memory Model of Realized
Volatility". *Journal of Financial Econometrics*, 7(2), 174-196.

### Rough Volatility

Volatility process with Hurst exponent H ~ 0.1 (much rougher than Brownian motion
where H = 0.5). Implies volatility paths are highly irregular and mean-reverting at
short horizons. S07 implements `estimate_hurst_from_vol()`.
**Ref**: Gatheral, J., Jaisson, T. & Rosenbaum, M. (2018). "Volatility is Rough".
*Quantitative Finance*, 18(6), 933-949.

### GARCH -- Generalized Autoregressive Conditional Heteroskedasticity

Model where today's variance depends on yesterday's variance and yesterday's squared
return. Captures volatility clustering. S07 implements GARCH(1,1) fitting.
**Ref**: Bollerslev, T. (1986). "Generalized Autoregressive Conditional
Heteroskedasticity". *Journal of Econometrics*, 31(3), 307-327.

### Realized Volatility (RV)

Sum of squared intraday returns over a period. The standard non-parametric estimator
of integrated variance. Basis for HAR-RV and bipower variation.

### Bipower Variation

Estimator of integrated variance robust to jumps. Uses products of adjacent absolute
returns instead of squared returns. Separates continuous volatility from jump variation.
**Ref**: Barndorff-Nielsen, O.E. & Shephard, N. (2004). "Power and Bipower Variation".
*Econometrica*, 72(1), 1-37.

### TSRV -- Two-Scale Realized Volatility

Estimator that corrects for market microstructure noise in high-frequency data by
combining RV computed at two different sampling frequencies. Allows using very
high-frequency data without noise bias.
**Ref**: Zhang, L., Mykland, P.A. & Ait-Sahalia, Y. (2005). "A Tale of Two Time
Scales". *JASA*, 100(472), 1394-1411.

---

## 5. Machine Learning for Finance

### Meta-Labeling

Two-stage approach: (1) a primary model predicts direction (buy/sell), (2) a secondary
model predicts whether to act on that signal (probability of success). The secondary
model filters out low-confidence entries.
**Ref**: Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*, Ch. 3. Wiley.

### Triple-Barrier Method

Labeling method where each trade has three exits: take-profit (upper barrier),
stop-loss (lower barrier), and time expiry (vertical barrier). The label is determined
by whichever barrier is hit first. Replaces naive fixed-horizon returns.
**Ref**: Lopez de Prado (2018), Ch. 3.

### Fractional Differentiation

Applies a fractional order of differencing (0 < d < 1) to a time series to achieve
stationarity while preserving as much memory as possible. Standard differencing (d=1)
destroys too much signal.
**Ref**: Lopez de Prado (2018), Ch. 5.

### Feature Importance (MDA / MDI / SFI)

Methods for measuring which features drive model predictions:
- **MDA** (Mean Decrease Accuracy): permutation importance
- **MDI** (Mean Decrease Impurity): tree-based impurity importance
- **SFI** (Single Feature Importance): importance measured one feature at a time
**Ref**: Lopez de Prado (2018), Ch. 8.

### GEX -- Gamma Exposure

Net gamma exposure of options market makers. When GEX is positive, dealers hedge by
selling into rallies and buying dips (volatility suppression). When negative, they
amplify moves (volatility expansion).
**Ref**: Barbon, A. & Buraschi, A. (2020). "Gamma Fragility".

---

## 6. Risk Management

### Circuit Breaker

State machine in S05 with states CLOSED (trading active), OPEN (trading halted), and
HALF_OPEN (cautious re-entry). Triggers: daily DD > 3%, rapid loss in 30min, VIX
spike > 20% in 1h, data feed silence > 60s, price gap > 5%.
Persisted in Redis. Cannot be bypassed.

### Kelly Fraction (Kelly Criterion)

Optimal fraction of capital to bet: `f* = (bp - q) / b` where b = odds, p = win
probability, q = 1-p. Maximizes long-run geometric growth. APEX uses Bayesian
shrinkage to avoid overestimation from small samples.
**Ref**: Kelly, J.L. (1956). "A New Interpretation of Information Rate".
*Bell System Technical Journal*, 35(4), 917-926.

### VaR -- Value at Risk

Maximum loss at a given confidence level over a given horizon. e.g., "1-day 99% VaR
= $10K" means 99% probability of losing less than $10K in one day.
**Ref**: Jorion, P. (2007). *Value at Risk* (3rd ed.). McGraw-Hill.

### CVaR / Expected Shortfall (ES)

Expected loss given that VaR is breached. Answers "if we're in the worst 1%, how bad
is it on average?" More coherent risk measure than VaR (subadditive).
**Ref**: Artzner, P., Delbaen, F., Eber, J.-M. & Heath, D. (1999). "Coherent Measures
of Risk". *Mathematical Finance*, 9(3), 203-228.

### Drawdown (DD)

Decline from a peak to a trough in portfolio value. Maximum drawdown (max DD) is the
worst peak-to-trough loss. APEX CI gate: max DD <= 8% on 30-day fixture.

### Bayesian Shrinkage

Technique to shrink an estimate (e.g., Kelly fraction) toward a conservative prior.
Prevents over-aggressive sizing from noisy estimates based on limited data.
APEX shrinks Kelly toward half-Kelly as default.

---

## 7. Execution and Portfolio

### Almgren-Chriss Model

Optimal execution framework that balances temporary market impact (urgency cost) against
permanent market impact (information leakage). Minimizes total execution cost for a
given risk aversion.
**Ref**: Almgren, R. & Chriss, N. (2001). "Optimal Execution of Portfolio Transactions".
*Journal of Risk*, 3(2), 5-40.

### TWAP -- Time-Weighted Average Price

Execution algorithm that splits a large order into equal-sized child orders at regular
time intervals. Simple baseline for execution quality measurement.

### VWAP -- Volume-Weighted Average Price

Execution benchmark: `VWAP = sum(price_i * volume_i) / sum(volume_i)`. Executing at
better than VWAP indicates good execution quality.

### Slippage

Difference between expected execution price and actual fill price. Includes spread
crossing cost, market impact, and latency cost. Measured in basis points (bps).

### Market Impact

Price change caused by the act of trading. Temporary impact (reverts after trade) and
permanent impact (information incorporated into price). Modeled by Almgren-Chriss.

### Black-Litterman (B-L)

Portfolio allocation model that combines market equilibrium with investor views.
Starts from CAPM equilibrium weights, then tilts based on signal-derived views
with specified confidence levels.
**Ref**: Black, F. & Litterman, R. (1992). "Global Portfolio Optimization".
*Financial Analysts Journal*, 48(5), 28-43.

### Risk Parity

Allocation where each asset contributes equally to total portfolio risk. Unlike
equal-weight, risk parity accounts for volatility and correlation differences.
**Ref**: Maillard, S., Roncalli, T. & Teiletche, J. (2010). "The Properties of
Equally Weighted Risk Contribution Portfolios". *Journal of Portfolio Management*.

---

## 8. Macro and Central Banks

### FOMC -- Federal Open Market Committee

The Fed's monetary policy body. Meets ~8 times/year. Rate decisions are among the
highest-impact events for all markets. S08 tracks meeting dates and publishes
`macro.catalyst.fomc` events.

### ECB -- European Central Bank

Sets monetary policy for the eurozone. Governing Council meets every 6 weeks.
Key decisions: deposit facility rate, asset purchase programs. S01 ingests ECB
Statistical Data Warehouse data.

### BoJ -- Bank of Japan

Sets monetary policy for Japan. Known for yield curve control (YCC) and
unconventional policy. S01 ingests BoJ policy rate, monetary base, and Tankan survey.

### FRED -- Federal Reserve Economic Data

Public API from the St. Louis Fed. APEX ingests: GDP, CPI, NFP, unemployment,
Fed Funds rate, yield curve, credit spreads, consumer sentiment, ISM PMI, housing starts.

### Yield Curve

Plot of Treasury yields across maturities (2Y, 5Y, 10Y, 30Y). Inversion (short > long)
historically precedes recessions. APEX tracks 10Y-2Y and 10Y-3M spreads from FRED.

### DXY -- US Dollar Index

Trade-weighted index of the USD against six major currencies (EUR, JPY, GBP, CAD, SEK,
CHF). Rising DXY generally pressures risk assets and commodities.

### VIX -- CBOE Volatility Index

Implied volatility of S&P 500 options over the next 30 days. Often called the "fear
gauge". VIX > 30 typically indicates high stress. S05 circuit breaker monitors VIX
spikes (> 20% in 1h as trigger).

---

## Revision History

| Date | Change |
|---|---|
| 2026-04-11 | Initial creation (Sprint 1, closes #78). 46 terms across 8 categories. |
