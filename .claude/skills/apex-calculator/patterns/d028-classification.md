# D028 Forecast vs Realization Classification

Every output column MUST be explicitly classified as one of:

## Realization at t
- Uses data INCLUDING timestamp/tick t
- Example: `cvd[t] = cumsum(signed_vol[:t+1])` — includes t
- Safe because: computed from data known at t, no future data
- 5m mode: if aggregates a period (e.g., daily from 5m bars), emit ONLY on period close (D027)

## Forecast-like at t
- Uses ONLY strict past data (excludes timestamp/tick t)
- Example: `kyle_lambda[t] = OLS(delta_p[t-kw:t], ofi[t-kw:t])` — excludes t
- Safe because: no data from t or after used
- 5m mode: safe to broadcast to all bars of the current period

## Rules

1. Each output column MUST be declared in class docstring with type and reason.
2. Look-ahead characterization tests MUST cover both types distinctly (see `patterns/look-ahead-defense.md`).
3. D029 variance gate applies to signal columns regardless of type.

## Examples from merged PRs

- HAR-RV (PR #111): `har_rv_forecast` = forecast-like. `har_rv_residual`, `har_rv_signal` = realization.
- Rough Vol (PR #112 hotfix): all 6 columns = forecast-like (uses `daily_rv[:t]`).
- OFI (PR #113): all 4 columns = realization (uses ticks `[t-w+1, t]` inclusive — realization at tick t).
- CVD+Kyle (PR #114): `cvd`, `cvd_divergence` = realization. `kyle_lambda` + derivatives = forecast-like.
- GEX (PR #116): `gex_raw`, `gex_normalized` = realization. `gex_zscore`, `gex_regime`, `gex_signal` = forecast-like.
