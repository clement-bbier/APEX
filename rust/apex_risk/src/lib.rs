//! APEX Risk Engine — PyO3 0.28 / numpy 0.28 / ndarray 0.16 extension.
//!
//! Exposes portfolio-level risk calculations:
//! - `compute_exposure`: Sum of absolute notional values.
//! - `compute_correlation_matrix`: Pearson pairwise correlation.
//! - `max_drawdown`: Maximum peak-to-trough drawdown of an equity curve.

use ndarray::Array2;
use numpy::{IntoPyArray, PyArray2, PyReadonlyArray1, PyReadonlyArray2};
use pyo3::prelude::*;

// ── Python-exported functions ─────────────────────────────────────────────────

/// Compute total portfolio exposure as the sum of absolute notional values.
///
/// Args:
///     notionals: 1-D float64 array of position notional values (may be negative for shorts).
///
/// Returns:
///     Sum of |notional_i| — total gross exposure.
#[pyfunction]
fn compute_exposure(notionals: PyReadonlyArray1<'_, f64>) -> f64 {
    notionals
        .as_slice()
        .expect("contiguous")
        .iter()
        .map(|x| x.abs())
        .sum()
}

/// Compute the pairwise Pearson correlation matrix for a returns matrix.
///
/// Args:
///     returns: 2-D float64 array of shape (n_assets, n_periods).
///
/// Returns:
///     Symmetric 2-D float64 correlation matrix of shape (n_assets, n_assets).
#[pyfunction]
fn compute_correlation_matrix<'py>(
    py: Python<'py>,
    returns: PyReadonlyArray2<'py, f64>,
) -> Bound<'py, PyArray2<f64>> {
    let arr = returns.as_array();
    let n_assets = arr.nrows();
    let mut corr = Array2::<f64>::eye(n_assets);

    // Pre-compute means and stds
    let means: Vec<f64> = (0..n_assets)
        .map(|i| arr.row(i).mean().unwrap_or(0.0))
        .collect();
    let stds: Vec<f64> = (0..n_assets)
        .map(|i| {
            let row = arr.row(i);
            let m = means[i];
            let var = row.iter().map(|x| (x - m).powi(2)).sum::<f64>() / row.len() as f64;
            var.sqrt()
        })
        .collect();

    for i in 0..n_assets {
        for j in (i + 1)..n_assets {
            let row_i = arr.row(i);
            let row_j = arr.row(j);
            let n = row_i.len() as f64;
            let cov = row_i
                .iter()
                .zip(row_j.iter())
                .map(|(a, b)| (a - means[i]) * (b - means[j]))
                .sum::<f64>()
                / n;
            let c = if stds[i] > 0.0 && stds[j] > 0.0 {
                cov / (stds[i] * stds[j])
            } else {
                0.0
            };
            corr[[i, j]] = c;
            corr[[j, i]] = c;
        }
    }

    corr.into_pyarray(py)
}

/// Compute the maximum peak-to-trough drawdown of an equity curve.
///
/// Formula: max_DD = max_t { (peak_t - equity_t) / peak_t }
///
/// Args:
///     equity_curve: 1-D float64 array of portfolio equity values over time.
///
/// Returns:
///     Maximum drawdown as a fraction in [0, 1].
#[pyfunction]
fn max_drawdown(equity_curve: PyReadonlyArray1<'_, f64>) -> f64 {
    let values = equity_curve.as_slice().expect("contiguous");
    if values.is_empty() {
        return 0.0;
    }
    let mut peak = values[0];
    let mut max_dd = 0.0_f64;
    for &v in values {
        if v > peak {
            peak = v;
        }
        if peak > 0.0 {
            let dd = (peak - v) / peak;
            if dd > max_dd {
                max_dd = dd;
            }
        }
    }
    max_dd
}

// ── Module definition ─────────────────────────────────────────────────────────

#[pymodule]
fn apex_risk(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_exposure, m)?)?;
    m.add_function(wrap_pyfunction!(compute_correlation_matrix, m)?)?;
    m.add_function(wrap_pyfunction!(max_drawdown, m)?)?;
    Ok(())
}

// ── Unit tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    #[test]
    fn max_drawdown_simple() {
        let curve = vec![100.0, 110.0, 90.0, 105.0];
        // Peak=110, trough=90: DD = 20/110 ≈ 0.182
        let mut peak = curve[0];
        let mut max_dd = 0.0_f64;
        for &v in &curve {
            if v > peak {
                peak = v;
            }
            if peak > 0.0 {
                let dd = (peak - v) / peak;
                if dd > max_dd {
                    max_dd = dd;
                }
            }
        }
        assert!((max_dd - 0.1818).abs() < 0.001);
    }

    #[test]
    fn exposure_sum() {
        let notionals: Vec<f64> = vec![10_000.0, -5_000.0, 8_000.0];
        let exp: f64 = notionals.iter().map(|x| x.abs()).sum();
        assert_eq!(exp, 23_000.0);
    }
}
