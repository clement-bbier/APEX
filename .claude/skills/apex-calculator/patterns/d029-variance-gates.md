# D029 Signal Variance Gate Pattern

Every signal-type output column MUST have a test verifying it varies across inputs. Prevents silent constant columns that produce IC=0.

## Test template

```python
def test_<signal_col>_varies_across_inputs(self) -> None:
    """D029: <col> must vary across different inputs (not silently constant)."""
    means = []
    for seed in range(100):
        df = _make_<domain>_data(seed=seed)
        out = calc.compute(df)
        col_vals = out["<signal_col>"].drop_nulls().to_numpy()
        if len(col_vals) > 0:
            means.append(col_vals.mean())
    assert len(means) >= 50, "Not enough non-empty outputs"
    assert float(np.std(means)) > 0.01, (
        f"<signal_col> std across {len(means)} inputs = {np.std(means):.5f}, "
        f"indicates constant column (silent IC=0 bug)."
    )
```

## When to apply

Apply to every column that is a SIGNAL (normalized in [-1, +1] or regime flag). Do NOT apply to raw aggregates (unnecessary — they vary by construction).

Example applicability:
- HAR-RV: `har_rv_signal` yes | `har_rv_residual` optional | `har_rv_forecast` not necessary
- OFI: `ofi_signal` yes | `ofi_10/50/100` not necessary
- CVD+Kyle: `cvd_divergence` yes | `liquidity_signal` yes | `combined_signal` yes
- GEX: `gex_signal` yes | `gex_raw` yes (could degenerate on edge data) | `gex_regime` not necessary (discrete)
