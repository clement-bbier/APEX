//! Criterion bench stub for the Phase B Rust port of Kyle's lambda.
//!
//! **Python baseline (from `benchmarks/results/baseline_2026-04-21.md`):**
//!   - 20 000 ticks, kyle_window=50: mean 7.86 s, p99 ~10.2 s
//!   - 20 000 ticks, kyle_window=100: mean 7.84 s, p99 ~9.1 s
//!
//! **Rust target** (10× speedup, per baseline recommendation #1):
//!   - 20 000 ticks, kyle_window=50: mean ≤ 800 ms, p99 ≤ 1.0 s
//!   - 20 000 ticks, kyle_window=100: mean ≤ 800 ms, p99 ≤ 1.0 s
//!
//! Implementation notes for the Phase B author:
//! - The hot kernel is a rolling OLS on `(price_delta, signed_volume)`
//!   over a fixed window. Use `ndarray` slice views; avoid copying.
//! - `kyle_lambda_zscore` piggy-backs on a second rolling window over
//!   the lambda history — keep that in a `VecDeque<f64>` with O(1)
//!   `push_back` / `pop_front`.
//! - Parallelism: rayon `par_iter` across symbols is cheaper than
//!   across ticks (tick-path is already sequential under a single
//!   order book).

use criterion::{criterion_group, criterion_main, Criterion};

fn bench_kyle_lambda_20k_w50(c: &mut Criterion) {
    c.bench_function("kyle_lambda_20k_ticks_window50", |b| {
        b.iter(|| {
            // Phase B: call apex_microstructure::kyle_lambda(...)
            // on a 20 000-tick window with window=50.
            todo!("Phase B Rust port — see module docstring for target");
        });
    });
}

fn bench_kyle_lambda_20k_w100(c: &mut Criterion) {
    c.bench_function("kyle_lambda_20k_ticks_window100", |b| {
        b.iter(|| {
            todo!("Phase B Rust port — see module docstring for target");
        });
    });
}

criterion_group!(benches, bench_kyle_lambda_20k_w50, bench_kyle_lambda_20k_w100);
criterion_main!(benches);
