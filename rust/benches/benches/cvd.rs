//! Criterion bench stub for the Phase B Rust port of CVD + divergence.
//!
//! **Python baseline (from `benchmarks/results/baseline_2026-04-21.md`):**
//!   - 1 000 ticks (combined CVD + Kyle):  mean 341 ms, p99 ~432 ms
//!   - 10 000 ticks (combined CVD + Kyle): mean 2.94 s, p99 ~3.82 s
//!   - 50 000 ticks (combined CVD + Kyle): mean 19.6 s, p99 ~21.6 s
//!
//! The combined number shows that CVD+Kyle together are ~3× the cost
//! of OFI at the same input size. Kyle is the dominant contributor
//! (see `kyle_lambda.rs`); CVD alone is cheaper but piggy-backs on
//! the same Rust crate for free once Kyle is ported.
//!
//! **Rust target** (5× speedup on CVD-only contribution):
//!   - 10 000 ticks, CVD only: mean ≤ 200 ms, p99 ≤ 300 ms
//!
//! Implementation notes for the Phase B author:
//! - CVD = running sum of signed volume (BUY +, SELL −). Use `f64`
//!   accumulator; correctness does not require Kahan summation at
//!   the scales we trade.
//! - `cvd_divergence` is a tanh-normalized rank-correlation between
//!   price trend and CVD trend over the last `cvd_window` ticks.
//!   Rank correlation is O(n log n) but n = cvd_window = 20 — use a
//!   fixed-size ring buffer and sort in-place.
//! - When porting, keep CVD + Kyle in the same Rust file
//!   (`apex_microstructure/src/cvd_kyle.rs`) — they share the input
//!   tick stream and it halves the FFI boundary crossings.

use criterion::{criterion_group, criterion_main, Criterion};

fn bench_cvd_10k(c: &mut Criterion) {
    c.bench_function("cvd_divergence_10k_ticks", |b| {
        b.iter(|| {
            todo!("Phase B Rust port — see module docstring for target");
        });
    });
}

criterion_group!(benches, bench_cvd_10k);
criterion_main!(benches);
