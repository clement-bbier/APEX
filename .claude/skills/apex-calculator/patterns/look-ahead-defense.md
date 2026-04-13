# D024 Look-Ahead Defense Pattern

## Expanding window (for regressions refitted from scratch)

Use when: estimator refits on each timestep's full past history (HAR-RV, Rough Vol).

```python
for t in range(self._warm_up_periods, n):
    # Fit on [0, t-1] STRICT past
    past_window = series[:t]  # NOTE: [:t] is exclusive, so excludes index t
    forecast_t = estimator.fit_and_forecast(past_window)
    result[t] = forecast_t
```

## Fixed-length rolling window (for stable-length regressions)

Use when: estimator needs a consistent lookback (Kyle lambda, GEX z-score).

```python
for t in range(kw, n):
    # Window [t-kw, t-1] exclusive of current tick t
    window = series[t - kw : t]  # kw elements, strict past
    estimate_t = compute_on_window(window)
    result[t] = estimate_t
```

## CRITICAL: never include current index t in the fit data for forecast-like columns

Wrong:
```python
past_window = series[:t+1]  # ← includes t, look-ahead!
```

Right:
```python
past_window = series[:t]  # ← excludes t, strict past
```

## Characterization tests (mandatory)

```python
def test_forecast_at_t_uses_only_data_before_t(self) -> None:
    """Two DataFrames identical on [0, N], divergent after → identical output on [0, N]."""
    df_a = _make_data(seed=1)
    df_b = df_a.clone()
    # Modify df_b starting at index N+1
    df_b = df_b.with_columns(...)  # divergent future
    out_a = calc.compute(df_a)
    out_b = calc.compute(df_b)
    # Outputs at rows [warm_up, N] must be bitwise identical
    for col in ["<forecast_col_1>", "<forecast_col_2>"]:
        np.testing.assert_array_equal(
            out_a[col].to_numpy()[warm_up:N+1],
            out_b[col].to_numpy()[warm_up:N+1],
        )
```
