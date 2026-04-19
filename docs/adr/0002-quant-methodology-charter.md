# ADR-0002 — Quant Methodology Charter

> *Note (2026-04-18): This ADR continues to govern its respective subsystem. See [APEX Multi-Strat Charter](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md) §12.4 for the inventory of existing and anticipated ADRs in the multi-strat context.*

Status: Accepted
Date: 2026-04-08
Decider: clement-bbier
Supersedes: none
Superseded-by: none

## Context

Ninety-five percent of published quantitative trading strategies fail to
replicate out-of-sample (Harvey, Liu & Zhu, 2016). The main causes are
backtest overfitting, selection bias under multiple testing, ignoring
transaction costs, and evaluating on unrealistic data. A repository that
generates alpha at institutional quality must therefore enforce a
methodology charter — not a suggestion, a hard requirement — on every
feature, signal, and strategy it accepts.

The APEX repo already contains scaffolding for several advanced metrics
(PSR, DSR, CPCV, fractional differentiation, meta-labeling, VPIN, rough
volatility) but none of these are currently wired into `full_report()`
or enforced on PR review. This ADR fixes that.

## Decision

Every Quant PR that adds, modifies, or claims performance improvement
for an alpha feature, signal, or strategy MUST include the following in
its evaluation. PRs that fail to demonstrate any of the mandatory items
below will be rejected at review, regardless of the headline Sharpe.

### Mandatory evaluation checklist

1. **Returns basis**: Sharpe, Sortino, Calmar computed on the
   daily-resampled equity-curve returns, never on per-trade returns.
   (SRE-001d empirically demonstrated why per-trade returns break for
   HFT-magnitude strategies.)

2. **Out-of-sample validation**: strict train/test split with an
   embargoed gap, OR walk-forward analysis with purging and embargo as
   specified by López de Prado (2018, Ch. 7). No evaluation on the full
   dataset without holdout.

3. **Statistical significance of the Sharpe**:
   - 95 % confidence interval via stationary bootstrap
     (Politis & Romano, 1994)
   - Probabilistic Sharpe Ratio (Bailey & López de Prado, 2012) with
     the non-normality correction (skewness, kurtosis)

4. **Multiple-testing correction**: when more than one variant of a
   strategy is evaluated, report the Deflated Sharpe Ratio
   (Bailey & López de Prado, 2014) OR the Haircut Sharpe
   (Harvey & Liu, 2015). Variants include parameter sweeps, feature
   additions, lookback-window tuning, and regime filters.

5. **Cross-validation discipline**: use Combinatorial Purged
   Cross-Validation (CPCV; López de Prado, 2018, Ch. 12) rather than
   k-fold, and report the Probability of Backtest Overfitting
   (PBO; Bailey, Borwein, López de Prado, Zhu, 2014).

6. **Drawdown and tail metrics**:
   - Maximum drawdown (absolute and relative)
   - Calmar ratio (annualized return / max DD)
   - Ulcer Index (Martin & McCann, 1989) for drawdown duration
   - Return distribution: skewness, excess kurtosis, tail ratio
     (95th/5th percentile absolute ratio)

7. **Transaction-cost sensitivity**: evaluate the strategy under at
   least three cost scenarios: zero cost, realistic cost (spread +
   commission + impact model), and stress cost (2x realistic). Report
   the Sharpe degradation curve. The strategy must remain profitable
   under the realistic scenario to be accepted.

8. **Execution realism**: slippage is modeled with an Almgren-Chriss
   style temporary + permanent impact model (Almgren & Chriss, 2001)
   or a documented equivalent. Fills are not assumed instantaneous at
   mid-price.

9. **Turnover and capacity**:
   - Annualized turnover ratio
   - Alpha decay half-life estimate
   - Capacity estimate: at what AUM does market impact consume more
     than 25 % of the gross edge (Perold, 1988)

10. **Regime conditionality**: Sharpe, DD, and hit rate decomposed by
    market regime (at minimum: low-vol / high-vol, trending / ranging).
    A strategy whose edge lives in a single regime must declare it.

### Mandatory references

These are the books and papers that the APEX quant methodology builds on.
All Quant PRs must cite the relevant reference for any metric or method
they invoke, in the docstring and in the PR body.

| # | Reference | Used for |
|---|---|---|
| 1 | López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. | Meta-labeling, triple-barrier, fractional diff, CPCV, PSR/DSR/PBO, MDA feature importance. The canonical reference. |
| 2 | Bailey, D. H., & López de Prado, M. (2012). "The Sharpe Ratio Efficient Frontier". *Journal of Risk*, 15(2), 3-44. | Probabilistic Sharpe Ratio |
| 3 | Bailey, D. H., & López de Prado, M. (2014). "The Deflated Sharpe Ratio". *Journal of Portfolio Management*, 40(5), 94-107. | Deflated Sharpe under multiple testing and non-normality |
| 4 | Bailey, D. H., Borwein, J. M., López de Prado, M., & Zhu, Q. J. (2014). "The Probability of Backtest Overfitting". *Journal of Computational Finance*. | PBO metric |
| 5 | Harvey, C. R., & Liu, Y. (2015). "Backtesting". *Journal of Portfolio Management*, 42(1), 13-28. | Haircut Sharpe for multiple testing |
| 6 | Harvey, C. R., Liu, Y., & Zhu, H. (2016). "…and the Cross-Section of Expected Returns". *Review of Financial Studies*, 29(1), 5-68. | Multiple-testing discipline in quant research |
| 7 | White, H. (2000). "A Reality Check for Data Snooping". *Econometrica*, 68(5), 1097-1126. | Reality Check test for superior predictive ability |
| 8 | Hansen, P. R. (2005). "A Test for Superior Predictive Ability". *Journal of Business & Economic Statistics*, 23(4), 365-380. | SPA test, stricter than Reality Check |
| 9 | Politis, D. N., & Romano, J. P. (1994). "The Stationary Bootstrap". *JASA*, 89(428), 1303-1313. | Bootstrap CI on Sharpe and other statistics |
| 10 | Almgren, R., & Chriss, N. (2001). "Optimal execution of portfolio transactions". *Journal of Risk*, 3(2), 5-40. | Market impact and slippage modeling |
| 11 | Hasbrouck, J. (2007). *Empirical Market Microstructure*. Oxford University Press. | Kyle's λ, PIN, VPIN, order flow toxicity |
| 12 | Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies* (2nd ed.). Wiley. | Walk-forward analysis, robustness testing |
| 13 | Grinold, R. C., & Kahn, R. N. (1999). *Active Portfolio Management* (2nd ed.). McGraw-Hill. | Fundamental law of active management, information ratio |
| 14 | Martin, P. G., & McCann, B. B. (1989). *The Investor's Guide to Fidelity Funds*. Wiley. | Ulcer Index |
| 15 | Kelly, J. L. (1956). "A New Interpretation of Information Rate". *Bell System Technical Journal*, 35(4), 917-926. | Position sizing |

### Anti-patterns (automatic rejection at review)

Any Quant PR exhibiting any of the following is rejected on sight and
must be reworked:

- Sharpe computed on per-trade returns (see SRE-001d autopsy)
- No out-of-sample validation, or OOS split smaller than 30 % of data
- Reporting Sharpe without a confidence interval when claiming edge
- Claiming edge from N > 1 variants without DSR or Haircut correction
- Backtest on the full dataset with no holdout
- Zero-cost backtest presented as the primary result
- "Optimized" parameters selected by peeking at OOS performance
- `np.float64` or `float` used for prices or sizes (use `Decimal`)
- `datetime.utcnow()` instead of `datetime.now(UTC)`
- Features that leak future information into the training set

## Consequences

1. Every Quant PR template now includes a "Methodology Compliance"
   section with a checklist derived from this ADR. Reviewers reject
   PRs where any mandatory box is unchecked without justification.

2. The `.github/agents/apex-quant.agent.md` system prompt now
   references this ADR as binding.

3. An existing-scaffolding audit issue will be opened separately to
   inventory which components of the repo (PSR, DSR, CPCV, fractional
   diff, meta-labeling, VPIN, rough vol) are already implemented,
   which are wired into `full_report()`, and which need completion.

4. Future issues labeled `alpha` must cite the exact subset of this
   ADR they satisfy, and may extend the ADR (via ADR-0003, ADR-0004,
   etc.) rather than sidestep it.

## Alternatives considered and rejected

- **Ad-hoc evaluation per PR**: rejected. Leads to cherry-picking
  metrics that flatter each individual strategy.
- **Sharpe-only evaluation**: rejected. Sharpe alone is gameable and
  insensitive to tail risk, autocorrelation of returns, and capacity.
- **In-sample-only evaluation**: rejected. Guarantees overfitting
  (Bailey et al., 2014).
- **Copying a popular Python library's defaults**: rejected. Most
  libraries (backtrader, zipline, quantstats) do not enforce multiple
  testing correction and compute Sharpe on per-period returns without
  PSR/DSR adjustment.

## References for this ADR itself

See the "Mandatory references" table above. All of these are cited
throughout the charter.
