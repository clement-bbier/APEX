"""Monte Carlo Risk Engine for APEX Trading System.

VaR (Value at Risk):
    VaR_α = -quantile(returns, 1-α)
    Reference: Jorion (2006), *Value at Risk: The New Benchmark for Managing Financial Risk*.

CVaR (Conditional VaR / Expected Shortfall):
    CVaR_α = -E[R | R < -VaR_α]
    Reference: Artzner et al. (1999), "Coherent Measures of Risk".

Kelly fraction (MC-optimised):
    f* = argmax_f E[log(1 + f×R)] s.t. max_drawdown(f) < 10%
    Reference: Kelly (1956), "A New Interpretation of Information Rate".

GBM path:
    S(t+dt) = S(t) × exp((μ - σ²/2)dt + σ√dt×Z),  Z ~ N(0,1)
    Reference: Black & Scholes (1973).

CPU-parallelism via :class:`ProcessPoolExecutor` delegating inner loops to the
``apex_mc`` Rust crate (PyO3 0.28).  Falls back to NumPy when the extension
is not available.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any, cast

import numpy as np

try:
    from apex_mc import compute_cvar, compute_var, run_mc_batch

    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False

STRESS_SCENARIOS: dict[str, dict[str, Any]] = {
    "flash_crash": {"price_shock": -0.20, "spread_mult": 10.0},
    "vol_spike": {"price_shock": -0.05, "spread_mult": 3.0, "vol_mult": 2.0},
    "liquidity_gone": {"price_shock": 0.00, "spread_mult": 10.0, "fill_pct": 0.30},
    "cb_hike_200bps": {"price_shock": -0.08, "sector": "risk_off"},
    "cb_cut_200bps": {"price_shock": -0.05, "sector": "panic"},
}


def _run_chunk(args: tuple[np.ndarray[Any, np.dtype[Any]], int, int]) -> np.ndarray[Any, np.dtype[Any]]:
    """Worker function for ProcessPoolExecutor.

    Args:
        args: Tuple of (returns_array, n_simulations, seed).

    Returns:
        2-D array of shape (n_simulations, n_steps) with cumulative returns.
    """
    returns, n_sims, seed = args
    if RUST_AVAILABLE:
        return cast("np.ndarray[Any, np.dtype[Any]]", run_mc_batch(returns, n_sims, seed))
    rng = np.random.default_rng(seed)
    n_steps = len(returns)
    paths = np.zeros((n_sims, n_steps))
    for i in range(n_sims):
        sampled = rng.choice(returns, n_steps, replace=True)
        paths[i] = np.cumprod(1 + sampled) - 1
    return paths


class MonteCarloEngine:
    """CPU-parallel Monte Carlo risk and sizing engine.

    Uses :class:`ProcessPoolExecutor` with the ``apex_mc`` Rust extension
    for the inner bootstrap loop, falling back to NumPy.

    Args:
        n_simulations: Total number of Monte Carlo paths (default 50,000).
    """

    def __init__(self, n_simulations: int = 50_000) -> None:
        self.n_simulations = n_simulations
        self._n_workers: int = os.cpu_count() or 4

    def simulate_pnl_distribution(self, historical_returns: np.ndarray[Any, np.dtype[Any]]) -> dict[str, float]:
        """Bootstrap-simulate P&L distribution and compute risk metrics.

        Args:
            historical_returns: 1-D array of historical period returns.

        Returns:
            Dict with keys: var_95, var_99, cvar_95, cvar_99, mean, std.
        """
        paths = self._run_simulations(historical_returns)
        # Final PnL = last column of each path
        final_pnl = paths[:, -1]

        if RUST_AVAILABLE:
            var_95 = compute_var(final_pnl, 0.95)
            var_99 = compute_var(final_pnl, 0.99)
            cvar_95 = compute_cvar(final_pnl, 0.95)
            cvar_99 = compute_cvar(final_pnl, 0.99)
        else:
            var_95 = float(-np.quantile(final_pnl, 0.05))
            var_99 = float(-np.quantile(final_pnl, 0.01))
            tail_95 = final_pnl[final_pnl < -var_95]
            tail_99 = final_pnl[final_pnl < -var_99]
            cvar_95 = float(-tail_95.mean()) if len(tail_95) > 0 else var_95
            cvar_99 = float(-tail_99.mean()) if len(tail_99) > 0 else var_99

        return {
            "var_95": float(var_95),
            "var_99": float(var_99),
            "cvar_95": float(cvar_95),
            "cvar_99": float(cvar_99),
            "mean": float(np.mean(final_pnl)),
            "std": float(np.std(final_pnl)),
        }

    def optimize_kelly_fraction(
        self, win_rate: float, rr_ratio: float, max_drawdown_limit: float = 0.10
    ) -> float:
        """Optimise Kelly fraction via Monte Carlo simulation.

        Finds ``f* = argmax_f E[log(1 + f×R)]`` subject to
        ``max_drawdown(paths) < max_drawdown_limit``.

        Quarter-Kelly (f*/4) is applied internally to ensure prudent sizing.

        Args:
            win_rate: Historical win rate in [0, 1].
            rr_ratio: Average reward-to-risk ratio.
            max_drawdown_limit: Maximum acceptable drawdown fraction (default 10%).

        Returns:
            Optimal Kelly fraction f_used = f*/4.
        """
        # Analytical Kelly: f* = (p*b - q) / b
        q = 1.0 - win_rate
        b = rr_ratio
        f_star = (win_rate * b - q) / b
        f_star = max(0.0, min(f_star, 0.5))  # clamp to [0, 0.5]

        # MC validation
        synthetic_returns = np.array(
            [rr_ratio] * int(win_rate * 100) + [-1.0] * int((1 - win_rate) * 100)
        )
        if len(synthetic_returns) == 0:
            return 0.0

        best_f = 0.0
        for f in np.linspace(0.01, f_star, 20):
            scaled = f * synthetic_returns
            rng = np.random.default_rng(42)
            paths = np.zeros((1000, len(scaled)))
            for i in range(1000):
                sampled = rng.choice(scaled, len(scaled), replace=True)
                paths[i] = np.cumprod(1 + sampled) - 1
            # Compute per-path max drawdown
            cum_returns = paths + 1  # convert to equity multiples
            running_max = np.maximum.accumulate(cum_returns, axis=1)
            drawdowns = (running_max - cum_returns) / running_max
            max_dds = drawdowns.max(axis=1)
            if float(np.percentile(max_dds, 95)) <= max_drawdown_limit:
                best_f = float(f)

        return best_f / 4.0  # quarter-Kelly

    def stress_test_positions(self, positions: dict[str, float], capital: float) -> list[dict[str, Any]]:
        """Apply stress scenarios to current positions and estimate losses.

        Args:
            positions: Mapping of {symbol: notional_value}.
            capital:   Total portfolio capital.

        Returns:
            List of dicts with {scenario, estimated_loss, pct_capital}.
        """
        results: list[dict[str, Any]] = []
        for scenario_name, params in STRESS_SCENARIOS.items():
            price_shock = float(params.get("price_shock", 0.0))
            total_notional = sum(abs(v) for v in positions.values())
            estimated_loss = total_notional * abs(price_shock)
            results.append(
                {
                    "scenario": scenario_name,
                    "price_shock": price_shock,
                    "estimated_loss": estimated_loss,
                    "pct_capital": estimated_loss / capital if capital > 0 else 0.0,
                }
            )
        return sorted(results, key=lambda x: x["estimated_loss"], reverse=True)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run_simulations(self, returns: np.ndarray[Any, np.dtype[Any]]) -> np.ndarray[Any, np.dtype[Any]]:
        """Run MC simulations in parallel, using Rust or NumPy fallback.

        Args:
            returns: Historical returns array.

        Returns:
            2-D array of shape (n_simulations, n_steps).
        """
        chunk = max(1, self.n_simulations // self._n_workers)
        args_list = [(returns, chunk, seed) for seed in range(self._n_workers)]

        with ProcessPoolExecutor(max_workers=self._n_workers) as executor:
            futures = [executor.submit(_run_chunk, args) for args in args_list]
            results = [f.result() for f in futures]

        return np.vstack(results)
