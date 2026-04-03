//! APEX Monte Carlo engine — PyO3 0.28 / numpy 0.28 extension.
//!
//! Exposes three functions to Python:
//! - `run_mc_batch`: Simulate N price paths via bootstrap resampling.
//! - `compute_var`:  Historical Value-at-Risk at confidence level α.
//! - `compute_cvar`: Conditional VaR (Expected Shortfall) at α.

use numpy::{IntoPyArray, PyArray2, PyReadonlyArray1};
use pyo3::prelude::*;
use rand::prelude::*;
use rand::rngs::SmallRng;
use rand_distr::Uniform;
use rayon::prelude::*;

// ── Internal simulation ───────────────────────────────────────────────────────

/// Bootstrap-resample `n_simulations` paths of length equal to `returns`.
///
/// Each path is a cumulative product `Π(1 + r_i) - 1`.
fn simulate_paths(returns: &[f64], n_simulations: usize, seed: u64) -> Vec<Vec<f64>> {
    let n = returns.len();
    (0..n_simulations)
        .into_par_iter()
        .map(|i| {
            let mut rng = SmallRng::seed_from_u64(seed.wrapping_add(i as u64));
            let dist = Uniform::new(0, n);
            let mut path = Vec::with_capacity(n);
            let mut cum = 1.0_f64;
            for _ in 0..n {
                let idx = rng.sample(dist);
                cum *= 1.0 + returns[idx];
                path.push(cum - 1.0);
            }
            path
        })
        .collect()
}

// ── Python-exported functions ─────────────────────────────────────────────────

/// Run a Monte Carlo batch, returning a 2-D array of shape (n_simulations, n_steps).
///
/// Each row is one simulated equity curve expressed as cumulative return.
/// Bootstrap resampling from `returns` is used (historical simulation).
///
/// Args:
///     returns:       1-D float64 array of historical period returns.
///     n_simulations: Number of paths to generate.
///     seed:          Random seed (use different seeds per worker for independence).
///
/// Returns:
///     2-D float64 array of shape ``(n_simulations, len(returns))``.
#[pyfunction]
fn run_mc_batch<'py>(
    py: Python<'py>,
    returns: PyReadonlyArray1<'py, f64>,
    n_simulations: usize,
    seed: u64,
) -> Bound<'py, PyArray2<f64>> {
    let arr = returns.as_slice().expect("returns must be contiguous");
    let paths = simulate_paths(arr, n_simulations, seed);
    let n_steps = arr.len();
    let flat: Vec<f64> = paths.into_iter().flatten().collect();
    // Build ndarray and convert to numpy
    let shape = [n_simulations, n_steps];
    let nd = ndarray::Array2::from_shape_vec(shape, flat)
        .expect("shape mismatch in run_mc_batch");
    nd.into_pyarray(py)
}

/// Compute historical Value-at-Risk (VaR) at the given confidence level.
///
/// Formula: VaR_α = -quantile(returns, 1 - α)
///
/// Args:
///     returns:    1-D float64 array of historical returns.
///     confidence: Confidence level, e.g. 0.95 for 95% VaR.
///
/// Returns:
///     VaR as a positive number representing the loss threshold.
#[pyfunction]
fn compute_var(returns: PyReadonlyArray1<'_, f64>, confidence: f64) -> f64 {
    let mut v: Vec<f64> = returns.as_slice().expect("contiguous").to_vec();
    v.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let idx = ((1.0 - confidence) * v.len() as f64) as usize;
    -v[idx.min(v.len().saturating_sub(1))]
}

/// Compute Conditional VaR (Expected Shortfall / CVaR) at the given confidence level.
///
/// Formula: CVaR_α = -E[R | R < -VaR_α]
///
/// Args:
///     returns:    1-D float64 array of historical returns.
///     confidence: Confidence level, e.g. 0.95.
///
/// Returns:
///     CVaR as a positive number.
#[pyfunction]
fn compute_cvar(returns: PyReadonlyArray1<'_, f64>, confidence: f64) -> f64 {
    let var = {
        let mut v: Vec<f64> = returns.as_slice().expect("contiguous").to_vec();
        v.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let idx = ((1.0 - confidence) * v.len() as f64) as usize;
        -v[idx.min(v.len().saturating_sub(1))]
    };
    let tail: Vec<f64> = returns
        .as_slice()
        .expect("contiguous")
        .iter()
        .filter(|&&r| r < -var)
        .copied()
        .collect();
    if tail.is_empty() {
        return var;
    }
    -tail.iter().sum::<f64>() / tail.len() as f64
}

// ── Module definition ─────────────────────────────────────────────────────────

#[pymodule]
fn apex_mc(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_mc_batch, m)?)?;
    m.add_function(wrap_pyfunction!(compute_var, m)?)?;
    m.add_function(wrap_pyfunction!(compute_cvar, m)?)?;
    Ok(())
}

// ── Unit tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn simulate_paths_shape() {
        let returns = vec![0.01, -0.02, 0.03, -0.01, 0.02];
        let paths = simulate_paths(&returns, 100, 42);
        assert_eq!(paths.len(), 100);
        assert_eq!(paths[0].len(), 5);
    }

    #[test]
    fn var_positive() {
        let returns = vec![-0.10, -0.05, 0.02, 0.03, -0.08, 0.01, -0.03];
        // VaR should be a positive loss threshold
        let mut v = returns.clone();
        v.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let idx = ((1.0 - 0.95) * v.len() as f64) as usize;
        let var_val = -v[idx.min(v.len() - 1)];
        assert!(var_val >= 0.0);
    }
}
