"""Regime detection via ML methods (Phase 2 stubs) for APEX Trading System."""

from __future__ import annotations


class RegimeML:
    """ML-based regime detection. Phase 2 implementations - stubs only."""

    def fit_hmm(self, returns: list[float], n_states: int = 4) -> dict:
        """Fit a Hidden Markov Model to return series.

        TODO Phase 2: Implement 4-state HMM on returns using hmmlearn or
        custom Baum-Welch algorithm.

        Args:
            returns: List of return values.
            n_states: Number of hidden states.

        Returns:
            Stub dict indicating the method is not yet implemented.
        """
        # TODO Phase 2: HMM 4-state on returns
        return {"n_states": n_states, "status": "not_implemented"}

    def detect_breakpoints(self, series: list[float]) -> list[int]:
        """Detect structural breakpoints using PELT algorithm.

        TODO Phase 2: Implement PELT (Pruned Exact Linear Time) breakpoint
        detection using ruptures library or custom implementation.

        Args:
            series: Time series of values.

        Returns:
            Empty list (stub). Phase 2 returns list of breakpoint indices.
        """
        # TODO Phase 2: PELT breakpoint detection
        return []

    def cointegration_test(
        self, series_a: list[float], series_b: list[float]
    ) -> dict:
        """Run the Engle-Granger cointegration test on two series.

        TODO Phase 2: Implement Engle-Granger two-step cointegration test
        using statsmodels.tsa.stattools.coint.

        Args:
            series_a: First time series.
            series_b: Second time series.

        Returns:
            Stub dict indicating the method is not yet implemented.
        """
        # TODO Phase 2: Engle-Granger test
        return {"cointegrated": False, "status": "not_implemented"}
