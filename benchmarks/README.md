# APEX Benchmarks

Performance benchmarks used to establish a Python baseline for the
hot-path feature calculators and sizing / risk logic. Drives Rust-port
prioritization for Phase B.

**This directory is outside `tests/`** — normal CI runs (`make
test-unit`, `make test-int`) do **not** execute these benchmarks. Run
them explicitly when you want to:

1. Establish a new baseline before optimizing or porting a module.
2. Regression-test a PR that claims to move the needle on latency.
3. Validate that a Rust port actually delivers the estimated speedup.

## Layout

```
benchmarks/
├── README.md                  — this file
├── pyproject_additions.toml   — dependency additions to paste into pyproject.toml
├── python/
│   ├── conftest.py            — pytest-benchmark config + shared fixtures
│   ├── bench_har_rv.py        — HAR-RV realized-vol cascade
│   ├── bench_ofi.py           — Order Flow Imbalance, rolling windows
│   ├── bench_cvd.py           — Cumulative Volume Delta + divergence
│   ├── bench_kyle_lambda.py   — Kyle's lambda rolling regression
│   ├── bench_kelly_sizer.py   — Kelly fraction + position sizing
│   └── bench_risk_chain.py    — Risk-chain E2E (Phase B deferred)
└── results/
    └── baseline_2026-04-21.md — first committed baseline + recommendations
```

## How to run

Install the dev-only benchmark deps (already satisfied if you installed
the `dev` dependency group — see `pyproject_additions.toml`):

```bash
pip install pytest-benchmark
```

Then, for a single module:

```bash
# Default output: pretty table to stdout
pytest benchmarks/python/bench_ofi.py --benchmark-only

# Emit a machine-readable JSON snapshot for regression tracking
pytest benchmarks/python/bench_ofi.py \
    --benchmark-only \
    --benchmark-json=/tmp/ofi.json

# Quick smoke (fewer rounds, useful when iterating locally)
pytest benchmarks/python/bench_ofi.py \
    --benchmark-only \
    --benchmark-warmup=off \
    --benchmark-min-rounds=3
```

Run everything (takes 20–30 minutes on a dev box — most time is in
HAR-RV which is O(n²)):

```bash
pytest benchmarks/python/ --benchmark-only
```

## How to interpret the baseline

Each `bench_*.py` file's docstring records:

```
Module: <path to the Python module being benched>
Hot path role: <signal_gen | risk_check | sizing | ...>
Current mean latency: <N unit> (p99: <M unit>)
Rust port feasibility: <high | medium | low>
Estimated Rust speedup: <Nx>
Recommendation: <port | don't port | decide after next cycle>
```

The `results/baseline_YYYY-MM-DD.md` file aggregates these into a
single ranked table plus a short prose recommendation on which
modules to port next.

## Recommendation framework

A module is a **high-priority Rust candidate** when all three hold:

1. It runs on the tick hot path (not EOD / daily / once-at-startup).
2. Its Python mean latency is > 1 ms per call at production input
   sizes, i.e. it is measurably chewing latency budget.
3. Its inner loop is pure numeric work that maps cleanly to `ndarray`
   (no Python branching, no object dispatch, no external async I/O).

A module is a **low-priority / don't-port** candidate when any of:

- It's already sub-microsecond (Kelly sizer).
- It's I/O-bound (risk chain — Redis round-trips dominate).
- It's a batch EOD feature with natural amortization (HAR-RV).
- It's not actually in the hot path (any reporting / dashboard code).

When in doubt: run the benchmark before porting. Rust is load-bearing
complexity; don't introduce it on speculation.

## Regression tracking

When you add a new Python feature calculator that touches the tick
path, drop a `bench_<name>.py` here and commit a new dated
`results/baseline_YYYY-MM-DD.md`. Subsequent PRs that move latency
should include a diff vs the latest baseline in the PR description
(Python pytest-benchmark emits `compare` output when passed
`--benchmark-compare=<path>`).

## Rust side

Rust benches use [criterion.rs](https://crates.io/crates/criterion)
and live in `rust/benches/` (one file per crate / candidate). They are
currently **scaffolding stubs** — each records a `todo!()` harness
plus the target speedup from the Python baseline, ready for the
actual Rust implementation in Phase B.

Run them with:

```bash
cd rust
cargo bench --workspace
```

(Will no-op until a bench body is filled in.)
