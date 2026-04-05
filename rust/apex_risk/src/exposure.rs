//! Portfolio Exposure Aggregation — Rayon-parallelized.
//!
//! compute_exposure(sizes: np.ndarray, prices: np.ndarray) -> f64
//!     Returns Σ(sizes[i] × prices[i]) — total notional.
//!     Performance: O(n) with Rayon parallel reduction.
//!
//! compute_correlation_matrix(returns: np.ndarray[n_assets, n_periods]) -> np.ndarray[n_assets, n_assets]
//!     Pearson correlation matrix. O(n_assets^2 × n_periods).
//!
//! Reference:
//!     Pearson, K. (1895). Notes on regression and inheritance.
//!     Proceedings of the Royal Society of London, 58, 240-242.

use pyo3::prelude::*;
use numpy::{IntoPyArray, PyArray2, PyReadonlyArray1, PyReadonlyArray2};
use rayon::prelude::*;
use ndarray::Array2;

#[pyfunction]
pub fn compute_exposure(
    sizes: PyReadonlyArray1<f64>,
    prices: PyReadonlyArray1<f64>,
) -> f64 {
    let s = sizes.as_slice().expect("sizes C-contiguous");
    let p = prices.as_slice().expect("prices C-contiguous");
    assert_eq!(s.len(), p.len(), "sizes and prices must be same length");     
    s.par_iter().zip(p.par_iter()).map(|(si, pi)| si * pi).sum()
}

#[pyfunction]
pub fn compute_correlation_matrix<'py>(
    py: Python<'py>,
    returns: PyReadonlyArray2<'py, f64>,
) -> Bound<'py, PyArray2<f64>> {
    let arr = returns.as_array();
    let (n_assets, n_periods) = arr.dim();
    let means: Vec<f64> = (0..n_assets)
        .map(|i| arr.row(i).iter().sum::<f64>() / n_periods as f64)
        .collect();
    let mut corr = vec![0.0f64; n_assets * n_assets];
    for i in 0..n_assets {
        for j in 0..n_assets {
            if i == j { corr[i * n_assets + j] = 1.0; continue; }
            let ri = arr.row(i);
            let rj = arr.row(j);
            let cov: f64 = ri.iter().zip(rj.iter())
                .map(|(a, b)| (a - means[i]) * (b - means[j]))
                .sum::<f64>() / n_periods as f64;
            let var_i: f64 = ri.iter().map(|a| (a - means[i]).powi(2)).sum::<f64>() / n_periods as f64;
            let var_j: f64 = rj.iter().map(|a| (a - means[j]).powi(2)).sum::<f64>() / n_periods as f64;
            
            let c = if var_i > 0.0 && var_j > 0.0 {
                cov / (var_i.sqrt() * var_j.sqrt())
            } else {
                0.0
            };
            corr[i * n_assets + j] = c;
        }
    }
    
    let corr_arr = Array2::from_shape_vec((n_assets, n_assets), corr).unwrap();
    corr_arr.into_pyarray(py)
}
