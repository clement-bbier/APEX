"""Benchmark skeleton for services.risk_manager.chain_orchestrator.

Module: services/risk_manager/chain_orchestrator.py
Hot path role: risk_check (aggregate VETO chain per order candidate)
Current mean latency: TBD (skipped in baseline_2026-04-21.md -- see Notes)
Rust port feasibility: low (chain is async, Redis-bound, not CPU-bound)
Estimated Rust speedup: negligible (< 1.2x -- I/O dominates)
Recommendation: do not port -- latency budget is Redis round-trips + asyncio;
                optimize Redis locality and pipelining instead.

Notes:
    The risk chain requires injected collaborators (FailClosedGuard,
    CBEventGuard, CircuitBreaker, MetaLabelGate, RiskDecisionBuilder) plus
    an async context_load_fn. Constructing a faithful in-process harness
    touches services/ internals which this PR explicitly excludes (see
    HARD STOPS). The 2026-04-21 baseline therefore records latency from
    the existing S05 integration tests (`tests/integration/s05/...`)
    rather than reproducing the full orchestrator mock stack here.

    Enabling this bench in Phase B:
        1. Import RiskChainOrchestrator and its collaborators.
        2. Provide MockFailClosed, MockCBGuard, etc. returning PASS
           results synchronously.
        3. Provide a MockContextLoader(async) that returns a canned
           context dict in ~10 us.
        4. Instantiate OrderCandidate with representative fields.
        5. benchmark(asyncio.run, orchestrator.process(candidate)).

    Until then, this file stays importable (no hard skip) but has no
    parametrized benches -- only a sentinel test that records the skip.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Requires in-process S05 mock stack; deferred to Phase B.")
def test_bench_risk_chain_process_placeholder() -> None:
    """Placeholder -- see module docstring for Phase B activation steps."""
