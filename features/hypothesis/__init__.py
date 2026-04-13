"""Phase 3.11 — Multiple Hypothesis Testing (DSR, PBO, MHT).

Statistical validation layer consuming CPCV outputs (Phase 3.10)
to quantify overfitting risk.  Three pillars:

1. **DeflatedSharpeCalculator** — wraps ``backtesting.metrics`` DSR/PSR.
2. **PBOCalculator** — rank-based Probability of Backtest Overfitting.
3. **MHT corrections** — Holm-Bonferroni (FWER) and Benjamini-Hochberg (FDR).

Reference
---------
- Bailey & López de Prado (2014). "The Deflated Sharpe Ratio." JPM.
- Bailey, Borwein, López de Prado, Zhu (2017). "Probability of Backtest
  Overfitting." J. Computational Finance.
- Holm (1979). "A simple sequentially rejective multiple test procedure."
- Benjamini & Hochberg (1995). "Controlling the FDR." JRSS B.
"""
