//! apex_risk Portfolio Risk Computation (PyO3 bindings).
//!
//! Exposed to Python:
//!     from apex_risk import compute_exposure, compute_correlation_matrix
//!
//! Performance: Rayon parallelized. < 1ms for 100-asset portfolio.

use pyo3::prelude::*;
mod exposure;

#[pymodule]
fn apex_risk(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(exposure::compute_exposure, m)?)?;
    m.add_function(wrap_pyfunction!(exposure::compute_correlation_matrix, m)?)?;
    Ok(())
}
