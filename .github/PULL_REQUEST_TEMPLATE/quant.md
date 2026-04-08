## Summary
<!-- What alpha feature, signal, or strategy does this PR add or modify? -->

## Linked issue
Closes #

## Methodology Compliance (ADR-0002)

This PR has been evaluated against the Quant Methodology Charter.
Check each box or write "N/A — reason" on the same line.

### Evaluation basis
- [ ] Sharpe computed on daily-resampled equity-curve returns (not per-trade)
- [ ] Sortino and Calmar reported alongside Sharpe
- [ ] Max drawdown (absolute and %) reported
- [ ] Ulcer Index reported
- [ ] Return distribution stats: skewness, excess kurtosis, tail ratio

### Out-of-sample discipline
- [ ] Strict train/test split OR walk-forward with purging+embargo (LdP 2018 Ch. 7)
- [ ] OOS holdout ≥ 30 % of the data
- [ ] No parameter tuned on the OOS period

### Statistical significance
- [ ] 95 % confidence interval on Sharpe via stationary bootstrap (Politis-Romano 1994)
- [ ] Probabilistic Sharpe Ratio reported (Bailey & López de Prado 2012)
- [ ] If N > 1 variants evaluated: Deflated Sharpe OR Haircut Sharpe reported

### Cross-validation (if applicable)
- [ ] Combinatorial Purged CV (LdP 2018 Ch. 12) rather than k-fold
- [ ] PBO (Probability of Backtest Overfitting) reported

### Execution realism
- [ ] Transaction costs applied (spread + commission)
- [ ] Slippage model: Almgren-Chriss or documented equivalent
- [ ] Tested under zero-cost / realistic-cost / stress-cost (2x realistic)
- [ ] Strategy remains profitable under realistic-cost scenario

### Capacity and turnover
- [ ] Annualized turnover reported
- [ ] Alpha decay half-life estimated
- [ ] Capacity estimate (AUM beyond which impact consumes > 25 % of edge)

### Regime decomposition
- [ ] Sharpe, DD, hit rate decomposed by at least one regime axis (vol or trend)
- [ ] Single-regime dependence declared if applicable

### Code discipline
- [ ] All prices and sizes use `Decimal`, never `float`
- [ ] All timestamps use `datetime.now(UTC)`
- [ ] Docstrings cite the academic reference for any non-trivial formula
- [ ] mypy --strict clean, ruff clean
- [ ] `make preflight` green (paste the tail below)

## Academic references cited
<!-- List the ADR-0002 references numbers this PR relies on -->

## Preflight output
```
<paste the last ~20 lines of `make preflight`>
```

## Reviewer notes
<!-- Anything the reviewer should look at in priority -->
