"""Regime detection via ML methods for APEX Trading System.

Implements three quantitative regime-detection algorithms using only numpy/scipy:

1. fit_hmm      -- 4-state Gaussian HMM via Baum-Welch EM algorithm.
2. detect_breakpoints -- Structural breakpoint detection via PELT
                       (Pruned Exact Linear Time) with L2 cost.
3. cointegration_test -- Engle-Granger two-step cointegration test
                        using OLS residuals and ADF statistic.

References:
  - Baum et al. (1970). "A Maximization Technique Occurring in the Statistical
    Analysis of Probabilistic Functions of Markov Chains." Ann. Math. Stat.
  - Killick et al. (2012). "Optimal Detection of Changepoints with a Linear
    Computational Cost." JASA.
  - Engle & Granger (1987). "Co-integration and Error Correction:
    Representation, Estimation, and Testing." Econometrica.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


class RegimeML:
    """ML-based regime detection using numpy/scipy primitives.

    All methods are stateless and accept raw Python lists for compatibility
    with the upstream data pipeline (no pandas dependency required).
    """

    # ── HMM ───────────────────────────────────────────────────────────────────

    def fit_hmm(
        self,
        returns: list[float],
        n_states: int = 4,
        n_iter: int = 100,
        tol: float = 1e-4,
        seed: int = 42,
    ) -> dict[str, Any]:
        """Fit a Gaussian Hidden Markov Model to a return series.

        Uses Baum-Welch (EM) algorithm with Gaussian emissions.

        Emission model: P(obs | state=k) = N(mu_k, sigma_k^2)

        Algorithm:
          E-step: Forward-backward to compute gamma_t(k) = P(S_t=k | obs).
          M-step: Update mu_k = sum(gamma_t(k) * obs_t) / sum(gamma_t(k)).
                  Update sigma_k^2 = sum(gamma_t(k) * (obs_t - mu_k)^2) / sum(gamma_t(k)).
                  Update trans[i,j] = sum_t(xi_t(i,j)) / sum_t(gamma_t(i)).
                  Update pi_k = gamma_0(k).

        Args:
            returns: Time series of returns (e.g. log-returns).
            n_states: Number of hidden states (default 4: low/normal/high/crisis).
            n_iter: Maximum EM iterations.
            tol: Log-likelihood convergence tolerance.
            seed: Random seed for reproducibility.

        Returns:
            dict with keys:
              - n_states (int): Number of fitted states.
              - means (list[float]): Emission mean per state.
              - stds (list[float]): Emission std per state.
              - transition_matrix (list[list[float]]): n_states x n_states matrix.
              - initial_probs (list[float]): Initial state probabilities.
              - viterbi_path (list[int]): Most-likely state sequence.
              - log_likelihood (float): Final log-likelihood.
              - n_iter (int): Iterations until convergence.
              - converged (bool): Whether EM converged within n_iter.
              - status (str): 'fitted' on success, 'insufficient_data' if too short.
        """
        obs = np.asarray(returns, dtype=float)
        seq_len = len(obs)

        if seq_len < n_states:
            return {
                "n_states": n_states,
                "status": "insufficient_data",
                "means": [],
                "stds": [],
                "transition_matrix": [],
                "initial_probs": [],
                "viterbi_path": [],
                "log_likelihood": float("-inf"),
                "n_iter": 0,
                "converged": False,
            }

        rng = np.random.default_rng(seed)

        # Initialise parameters
        sorted_idx = np.argsort(obs)
        chunk = max(1, seq_len // n_states)
        mu = np.array(
            [obs[sorted_idx[min(i * chunk, seq_len - 1)]] for i in range(n_states)],
            dtype=float,
        )
        sigma = np.full(n_states, float(np.std(obs)) + 1e-8)
        trans_mat = rng.dirichlet(np.ones(n_states), size=n_states)
        pi = rng.dirichlet(np.ones(n_states))

        prev_ll = float("-inf")
        ll = float("-inf")  # initialised before loop to avoid unbound reference
        n_converged = n_iter

        for iteration in range(n_iter):
            # ── E-step: Forward-Backward ──────────────────────────────────────
            # Emission log-probabilities log_b[t, k]
            log_b = np.column_stack(
                [
                    -0.5 * ((obs - mu[k]) / sigma[k]) ** 2
                    - np.log(sigma[k])
                    - 0.5 * math.log(2 * math.pi)
                    for k in range(n_states)
                ]
            )  # shape (seq_len, n_states)

            # Forward pass (log-space)
            log_alpha = np.full((seq_len, n_states), float("-inf"))
            log_alpha[0] = np.log(pi + 1e-300) + log_b[0]
            for t in range(1, seq_len):
                for j in range(n_states):
                    log_alpha[t, j] = (
                        np.logaddexp.reduce(log_alpha[t - 1] + np.log(trans_mat[:, j] + 1e-300))
                        + log_b[t, j]
                    )

            ll = float(np.logaddexp.reduce(log_alpha[-1]))

            # Backward pass (log-space)
            log_beta = np.zeros((seq_len, n_states))
            for t in range(seq_len - 2, -1, -1):
                for i in range(n_states):
                    log_beta[t, i] = np.logaddexp.reduce(
                        np.log(trans_mat[i] + 1e-300) + log_b[t + 1] + log_beta[t + 1]
                    )

            # gamma: P(S_t = k | obs)
            log_gamma = log_alpha + log_beta
            log_gamma -= np.logaddexp.reduce(log_gamma, axis=1, keepdims=True)
            gamma = np.exp(log_gamma)  # (seq_len, n_states)

            # xi: P(S_t=i, S_{t+1}=j | obs)
            xi = np.zeros((seq_len - 1, n_states, n_states))
            for t in range(seq_len - 1):
                for i in range(n_states):
                    for j in range(n_states):
                        xi[t, i, j] = (
                            log_alpha[t, i]
                            + np.log(trans_mat[i, j] + 1e-300)
                            + log_b[t + 1, j]
                            + log_beta[t + 1, j]
                        )
                xi[t] = np.exp(xi[t] - np.logaddexp.reduce(xi[t].ravel()))

            # ── M-step ───────────────────────────────────────────────────────
            gamma_sum = gamma.sum(axis=0) + 1e-300
            pi = gamma[0] / gamma[0].sum()
            mu = (gamma * obs[:, None]).sum(axis=0) / gamma_sum
            sigma = (
                np.sqrt((gamma * (obs[:, None] - mu[None, :]) ** 2).sum(axis=0) / gamma_sum) + 1e-8
            )

            xi_sum = xi.sum(axis=0) + 1e-300
            trans_mat = xi_sum / xi_sum.sum(axis=1, keepdims=True)

            # Convergence check
            if abs(ll - prev_ll) < tol:
                n_converged = iteration + 1
                break
            prev_ll = ll
        else:
            n_converged = n_iter

        viterbi_path = self._viterbi(obs, pi, trans_mat, mu, sigma)

        return {
            "n_states": n_states,
            "status": "fitted",
            "means": mu.tolist(),
            "stds": sigma.tolist(),
            "transition_matrix": trans_mat.tolist(),
            "initial_probs": pi.tolist(),
            "viterbi_path": viterbi_path,
            "log_likelihood": float(ll),
            "n_iter": n_converged,
            "converged": n_converged < n_iter,
        }

    @staticmethod
    def _viterbi(
        obs: np.ndarray[Any, np.dtype[np.float64]],
        pi: np.ndarray[Any, np.dtype[np.float64]],
        trans_mat: np.ndarray[Any, np.dtype[np.float64]],
        mu: np.ndarray[Any, np.dtype[np.float64]],
        sigma: np.ndarray[Any, np.dtype[np.float64]],
    ) -> list[int]:
        """Viterbi algorithm for most-likely state sequence.

        Args:
            obs: Observation sequence (n_t,).
            pi: Initial state probabilities (n_k,).
            trans_mat: Transition matrix (n_k, n_k).
            mu: Emission means (n_k,).
            sigma: Emission stds (n_k,).

        Returns:
            List of state indices, length n_t.
        """
        n_t = len(obs)
        n_k = len(pi)

        log_delta = np.full((n_t, n_k), float("-inf"))
        psi = np.zeros((n_t, n_k), dtype=int)

        log_b = np.column_stack(
            [
                -0.5 * ((obs - mu[k]) / sigma[k]) ** 2
                - np.log(sigma[k])
                - 0.5 * math.log(2 * math.pi)
                for k in range(n_k)
            ]
        )

        log_delta[0] = np.log(pi + 1e-300) + log_b[0]

        for t in range(1, n_t):
            for j in range(n_k):
                trans = log_delta[t - 1] + np.log(trans_mat[:, j] + 1e-300)
                psi[t, j] = int(np.argmax(trans))
                log_delta[t, j] = trans[psi[t, j]] + log_b[t, j]

        path = [int(np.argmax(log_delta[-1]))]
        for t in range(n_t - 1, 0, -1):
            path.append(int(psi[t, path[-1]]))
        path.reverse()
        return path

    # ── PELT ──────────────────────────────────────────────────────────────────

    def detect_breakpoints(
        self,
        series: list[float],
        penalty: float | None = None,
        min_size: int = 5,
    ) -> list[int]:
        """Detect structural breakpoints using PELT with L2 (least-squares) cost.

        PELT (Killick et al., 2012) finds the optimal changepoint set that
        minimises total within-segment L2 cost plus a linear penalty:

            C* = argmin_{tau} sum_k cost(y_{tau_k+1:tau_{k+1}}) + beta * |tau|

        where cost(y_{s:t}) = sum_{i=s}^{t} (y_i - mean(y_{s:t}))^2

        L2 cost admits an O(1) update via cumulative sums.

        Args:
            series: Univariate time series.
            penalty: BIC-like penalty per changepoint.
                     Defaults to log(n) * variance (BIC approximation).
            min_size: Minimum segment length between breakpoints.

        Returns:
            Sorted list of breakpoint indices (exclusive end of each segment).
            E.g. [10, 25] means segments [0:10], [10:25], [25:end].
            Returns empty list if no breakpoints detected.
        """
        arr = np.asarray(series, dtype=float)
        seq_len = len(arr)

        if seq_len < 2 * min_size:
            return []

        # L2 cost via prefix sums: cost(s, t) = sum(y[s:t]^2) - (sum(y[s:t])^2)/(t-s)
        prefix_sum = np.concatenate([[0.0], np.cumsum(arr)])
        prefix_sum2 = np.concatenate([[0.0], np.cumsum(arr**2)])

        def l2_cost(s: int, t: int) -> float:
            """L2 (variance) cost for segment arr[s:t]."""
            n = t - s
            if n <= 0:
                return 0.0
            s_val = prefix_sum[t] - prefix_sum[s]
            s2_val = prefix_sum2[t] - prefix_sum2[s]
            return float(s2_val - (s_val**2) / n)

        var = float(np.var(arr)) if np.var(arr) > 0 else 1.0
        if penalty is None:
            penalty = math.log(seq_len) * var

        # PELT dynamic programming
        # opt_cost[t] = min cost to partition arr[0:t]
        opt_cost = np.full(seq_len + 1, float("inf"))
        opt_cost[0] = -penalty
        last_cp: list[int] = [-1] * (seq_len + 1)
        admissible: list[int] = [0]

        for t in range(min_size, seq_len + 1):
            new_admissible: list[int] = []
            best_f = float("inf")
            best_prev = 0

            for s in admissible:
                seg_len = t - s
                if seg_len < min_size:
                    new_admissible.append(s)
                    continue
                cost_val = opt_cost[s] + l2_cost(s, t) + penalty
                if cost_val < best_f:
                    best_f = cost_val
                    best_prev = s
                # PELT pruning: if opt_cost[s] + cost(s,t) <= opt_cost[t],
                # s remains a candidate for future t' > t
                if opt_cost[s] + l2_cost(s, t) <= opt_cost[t]:
                    new_admissible.append(s)

            opt_cost[t] = best_f
            last_cp[t] = best_prev
            new_admissible.append(t)
            admissible = new_admissible

        # Backtrack to recover changepoints
        cps: list[int] = []
        t = seq_len
        while True:
            prev = last_cp[t]
            if prev == 0:
                break
            cps.append(prev)
            t = prev

        cps.sort()
        return cps

    # ── Engle-Granger cointegration ───────────────────────────────────────────

    def cointegration_test(
        self,
        series_a: list[float],
        series_b: list[float],
        significance: float = 0.05,
    ) -> dict[str, Any]:
        """Run the Engle-Granger two-step cointegration test.

        Step 1: OLS regression of series_a on series_b to get residuals.
        Step 2: ADF test on residuals (no constant, no trend).

        ADF critical values (MacKinnon 1994, n=infinity):
          10%: -3.12,  5%: -3.41,  1%: -3.96

        Reference:
          Engle, R. F. & Granger, C. W. J. (1987). "Co-integration and Error
          Correction: Representation, Estimation, and Testing." Econometrica,
          55(2), 251-276.

        Args:
            series_a: First time series (dependent in OLS).
            series_b: Second time series (regressor in OLS).
            significance: Significance level (default 0.05 = 5% critical value).

        Returns:
            dict with keys:
              - cointegrated (bool): True if ADF rejects unit-root in residuals.
              - adf_statistic (float): ADF test statistic.
              - critical_value (float): Critical value at requested significance.
              - significance (float): Requested significance level.
              - hedge_ratio (float): OLS coefficient of series_b (beta).
              - intercept (float): OLS intercept (alpha).
              - n_obs (int): Number of observations used.
              - status (str): 'tested' on success, 'insufficient_data' otherwise.
        """
        arr_a = np.asarray(series_a, dtype=float)
        arr_b = np.asarray(series_b, dtype=float)
        n_obs = min(len(arr_a), len(arr_b))

        if n_obs < 10:
            return {
                "cointegrated": False,
                "adf_statistic": float("nan"),
                "critical_value": float("nan"),
                "significance": significance,
                "hedge_ratio": float("nan"),
                "intercept": float("nan"),
                "n_obs": n_obs,
                "status": "insufficient_data",
            }

        arr_a = arr_a[:n_obs]
        arr_b = arr_b[:n_obs]

        # Step 1: OLS regression arr_a = alpha + beta * arr_b
        b_with_const = np.column_stack([np.ones(n_obs), arr_b])
        try:
            coeffs, _, _, _ = np.linalg.lstsq(b_with_const, arr_a, rcond=None)
        except np.linalg.LinAlgError:
            return {
                "cointegrated": False,
                "adf_statistic": float("nan"),
                "critical_value": float("nan"),
                "significance": significance,
                "hedge_ratio": float("nan"),
                "intercept": float("nan"),
                "n_obs": n_obs,
                "status": "singular_matrix",
            }
        intercept, hedge_ratio = float(coeffs[0]), float(coeffs[1])
        residuals = arr_a - (intercept + hedge_ratio * arr_b)

        # Step 2: ADF test on residuals (lag=1, no constant, no trend)
        # Test: delta_r_t = rho * r_{t-1} + epsilon_t
        delta_r = np.diff(residuals)
        r_lag = residuals[:-1]

        if len(delta_r) < 3:
            return {
                "cointegrated": False,
                "adf_statistic": float("nan"),
                "critical_value": float("nan"),
                "significance": significance,
                "hedge_ratio": hedge_ratio,
                "intercept": intercept,
                "n_obs": n_obs,
                "status": "insufficient_data",
            }

        # OLS for delta_r ~ rho * r_lag (no intercept)
        rho = float(np.dot(r_lag, delta_r) / (np.dot(r_lag, r_lag) + 1e-300))
        epsilon = delta_r - rho * r_lag
        sigma_sq = float(np.sum(epsilon**2) / (len(epsilon) - 1) + 1e-300)
        se_rho = math.sqrt(sigma_sq / (np.dot(r_lag, r_lag) + 1e-300))
        adf_stat = rho / (se_rho + 1e-300)

        # MacKinnon (1994) asymptotic critical values for no-constant ADF
        cv_map: dict[float, float] = {0.10: -3.12, 0.05: -3.41, 0.01: -3.96}
        crit_val = cv_map.get(significance, -3.41)

        return {
            "cointegrated": adf_stat < crit_val,
            "adf_statistic": adf_stat,
            "critical_value": crit_val,
            "significance": significance,
            "hedge_ratio": hedge_ratio,
            "intercept": intercept,
            "n_obs": n_obs,
            "status": "tested",
        }
