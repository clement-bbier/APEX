//! Criterion bench stub for the Phase B Rust port of multi-window OFI.
//!
//! **Python baseline (from `benchmarks/results/baseline_2026-04-21.md`):**
//!   - 10 000 ticks, trade-mode: mean 987 ms, p99 ~1.25 s
//!   - 10 000 ticks, book-mode:  mean 1 191 ms, p99 ~1.36 s
//!   - 100 000 ticks, trade-mode: mean 11.5 s, p99 ~12.1 s
//!   - 100 000 ticks, book-mode:  mean 11.2 s, p99 ~12.2 s
//!
//! **Rust target** (8× speedup, per baseline recommendation #2):
//!   - 10 000 ticks:  mean ≤ 150 ms, p99 ≤ 200 ms
//!   - 100 000 ticks: mean ≤ 1.5 s, p99 ≤ 1.8 s
//!
//! Implementation notes for the Phase B author:
//! - Three windows (10 / 50 / 100) in a single pass over the tick
//!   stream. Maintain three running sums in `VecDeque<f64>` rings.
//! - Book-mode (Δbid_size − Δask_size) is preferred when available;
//!   fall back to signed-volume trade-mode only when the input frame
//!   lacks `bid_size` / `ask_size` columns.
//! - Output is tanh-normalized — keep the tanh call on the final
//!   weighted combination, not per-window (one syscall saved per
//!   tick).

use criterion::{criterion_group, criterion_main, Criterion};

fn bench_ofi_10k_trade(c: &mut Criterion) {
    c.bench_function("ofi_10k_ticks_trade_mode", |b| {
        b.iter(|| {
            todo!("Phase B Rust port — see module docstring for target");
        });
    });
}

fn bench_ofi_10k_book(c: &mut Criterion) {
    c.bench_function("ofi_10k_ticks_book_mode", |b| {
        b.iter(|| {
            todo!("Phase B Rust port — see module docstring for target");
        });
    });
}

fn bench_ofi_100k_trade(c: &mut Criterion) {
    c.bench_function("ofi_100k_ticks_trade_mode", |b| {
        b.iter(|| {
            todo!("Phase B Rust port — see module docstring for target");
        });
    });
}

criterion_group!(benches, bench_ofi_10k_trade, bench_ofi_10k_book, bench_ofi_100k_trade);
criterion_main!(benches);
