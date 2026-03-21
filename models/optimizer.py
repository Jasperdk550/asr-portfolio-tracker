"""
Optimizer Model
---------------
Implements Markowitz Mean-Variance Portfolio Optimisation.

Given the assets currently held, this module computes:
  - The full Efficient Frontier (set of portfolios offering the highest
    expected return for each level of risk).
  - The Maximum Sharpe Ratio portfolio  (best risk-adjusted return).
  - The Minimum Variance portfolio      (lowest achievable risk).
  - A comparison of the current portfolio against these optima.
  - A rebalancing recommendation.

Why this matters for a.s.r.
----------------------------
As an insurance company, a.s.r. must manage assets against long-duration
liabilities.  Simply maximising return is never the goal — the goal is
maximising return *per unit of risk taken*.  The Efficient Frontier makes
this trade-off explicit and quantifiable, turning "should we rebalance?"
from a gut-feel question into a mathematically grounded one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize, Bounds, LinearConstraint

from models.portfolio import Portfolio


RISK_FREE_RATE = 0.045   # 4.5 % — consistent with metrics module
N_FRONTIER_POINTS = 500  # resolution of the frontier curve


@dataclass
class OptimizationResult:
    """Container for all outputs of the mean-variance optimisation."""

    tickers: List[str]

    # Frontier
    frontier_vols: np.ndarray       # annualised volatility for each point
    frontier_returns: np.ndarray    # annualised return for each point
    frontier_sharpes: np.ndarray    # Sharpe ratio for each point

    # Special portfolios
    max_sharpe_weights: np.ndarray
    max_sharpe_return: float
    max_sharpe_vol: float
    max_sharpe_sharpe: float

    min_var_weights: np.ndarray
    min_var_return: float
    min_var_vol: float

    # Current portfolio
    current_weights: np.ndarray
    current_return: float
    current_vol: float
    current_sharpe: float

    # Input parameters
    mean_returns: np.ndarray        # annualised per ticker
    cov_matrix: np.ndarray          # annualised covariance
    risk_free_rate: float

    # Rebalancing
    rebalancing: List[dict]         # per-ticker current vs suggested weights


class PortfolioOptimizer:
    """
    Computes the Markowitz Efficient Frontier for the current portfolio.

    Parameters
    ----------
    portfolio    : The Portfolio model instance.
    period       : Historical period used to estimate mu and Sigma.
    risk_free    : Annual risk-free rate used in Sharpe calculation.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        period: str = "3y",
        risk_free: float = RISK_FREE_RATE,
    ) -> None:
        self.portfolio = portfolio
        self.period = period
        self.rf = risk_free

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> OptimizationResult:
        """
        Execute the full optimisation pipeline.

        Returns
        -------
        OptimizationResult
        """
        tickers = self.portfolio.get_tickers()
        if len(tickers) < 2:
            raise ValueError(
                "Need at least 2 assets to compute an Efficient Frontier."
            )

        # ── Step 1: parameter estimation ──────────────────────────────
        hist = self.portfolio.fetch_history(tickers, period=self.period)
        available = [t for t in tickers if t in hist.columns]
        if len(available) < 2:
            raise ValueError("Not enough historical data to optimise.")

        tickers = available
        daily_returns = hist[tickers].pct_change().dropna()

        # Annualised mean returns and covariance
        mean_returns = daily_returns.mean().values * 252
        cov_matrix   = daily_returns.cov().values  * 252

        n = len(tickers)

        # ── Step 2: current portfolio weights ─────────────────────────
        prices = self.portfolio.fetch_current_prices(tickers)
        total_val = sum(
            p.quantity * prices.get(p.ticker, 0.0)
            for p in self.portfolio.get_positions()
            if p.ticker in tickers
        )
        current_weights = np.zeros(n)
        for i, ticker in enumerate(tickers):
            w = sum(
                p.quantity * prices.get(p.ticker, 0.0)
                for p in self.portfolio.get_positions()
                if p.ticker == ticker
            ) / max(total_val, 1e-9)
            current_weights[i] = w

        # Normalise (rounding safety)
        current_weights /= current_weights.sum()

        # ── Step 3: optimise special portfolios ───────────────────────
        max_sr_w  = self._max_sharpe(mean_returns, cov_matrix, n)
        min_var_w = self._min_variance(mean_returns, cov_matrix, n)

        # ── Step 4: trace the efficient frontier ──────────────────────
        target_returns = np.linspace(
            mean_returns.min() * 0.8,
            mean_returns.max() * 1.1,
            N_FRONTIER_POINTS,
        )
        f_vols, f_rets, f_sharpes = [], [], []

        for target in target_returns:
            w = self._min_variance_for_return(mean_returns, cov_matrix, n, target)
            if w is None:
                continue
            vol    = _portfolio_vol(w, cov_matrix)
            ret    = _portfolio_return(w, mean_returns)
            sharpe = (ret - self.rf) / vol if vol > 0 else 0.0
            f_vols.append(vol)
            f_rets.append(ret)
            f_sharpes.append(sharpe)

        # ── Step 5: assemble result ────────────────────────────────────
        def stats(w):
            r   = _portfolio_return(w, mean_returns)
            v   = _portfolio_vol(w, cov_matrix)
            sr  = (r - self.rf) / v if v > 0 else 0.0
            return r, v, sr

        cur_r, cur_v, cur_sr  = stats(current_weights)
        msr_r, msr_v, msr_sr  = stats(max_sr_w)
        mvr_r, mvr_v, _       = stats(min_var_w)

        # Rebalancing table
        rebalancing = [
            {
                "ticker": t,
                "current_weight": float(current_weights[i]),
                "optimal_weight": float(max_sr_w[i]),
                "delta": float(max_sr_w[i] - current_weights[i]),
            }
            for i, t in enumerate(tickers)
        ]
        rebalancing.sort(key=lambda x: abs(x["delta"]), reverse=True)

        return OptimizationResult(
            tickers=tickers,
            frontier_vols=np.array(f_vols),
            frontier_returns=np.array(f_rets),
            frontier_sharpes=np.array(f_sharpes),
            max_sharpe_weights=max_sr_w,
            max_sharpe_return=msr_r,
            max_sharpe_vol=msr_v,
            max_sharpe_sharpe=msr_sr,
            min_var_weights=min_var_w,
            min_var_return=mvr_r,
            min_var_vol=mvr_v,
            current_weights=current_weights,
            current_return=cur_r,
            current_vol=cur_v,
            current_sharpe=cur_sr,
            mean_returns=mean_returns,
            cov_matrix=cov_matrix,
            risk_free_rate=self.rf,
            rebalancing=rebalancing,
        )

    # ------------------------------------------------------------------
    # Optimisation routines
    # ------------------------------------------------------------------

    def _max_sharpe(
        self, mean_returns: np.ndarray, cov: np.ndarray, n: int
    ) -> np.ndarray:
        """Find weights that maximise the Sharpe ratio."""
        def neg_sharpe(w):
            r = _portfolio_return(w, mean_returns)
            v = _portfolio_vol(w, cov)
            return -(r - self.rf) / (v + 1e-9)

        return _solve(neg_sharpe, n)

    def _min_variance(
        self, mean_returns: np.ndarray, cov: np.ndarray, n: int
    ) -> np.ndarray:
        """Find weights that minimise portfolio variance."""
        def variance(w):
            return _portfolio_vol(w, cov) ** 2

        return _solve(variance, n)

    def _min_variance_for_return(
        self,
        mean_returns: np.ndarray,
        cov: np.ndarray,
        n: int,
        target_return: float,
    ) -> Optional[np.ndarray]:
        """
        Find minimum-variance weights that achieve exactly `target_return`.
        Returns None if the target is infeasible.
        """
        def variance(w):
            return _portfolio_vol(w, cov) ** 2

        constraints = [
            {"type": "eq", "fun": lambda w: w.sum() - 1.0},
            {"type": "eq", "fun": lambda w: _portfolio_return(w, mean_returns) - target_return},
        ]
        result = minimize(
            variance,
            x0=np.ones(n) / n,
            method="SLSQP",
            bounds=Bounds(0.0, 1.0),
            constraints=constraints,
            options={"ftol": 1e-9, "maxiter": 1000},
        )
        if result.success:
            return result.x
        return None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _portfolio_return(w: np.ndarray, mu: np.ndarray) -> float:
    return float(w @ mu)


def _portfolio_vol(w: np.ndarray, cov: np.ndarray) -> float:
    return float(np.sqrt(w @ cov @ w))


def _solve(objective, n: int) -> np.ndarray:
    """Generic constrained optimisation: weights sum to 1, all >= 0."""
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    best_result = None
    best_val = np.inf

    # Multi-start with 5 random initialisations for robustness
    for _ in range(5):
        x0 = np.random.dirichlet(np.ones(n))
        res = minimize(
            objective,
            x0=x0,
            method="SLSQP",
            bounds=Bounds(0.0, 1.0),
            constraints=constraints,
            options={"ftol": 1e-10, "maxiter": 2000},
        )
        if res.success and res.fun < best_val:
            best_val = res.fun
            best_result = res.x

    if best_result is None:
        return np.ones(n) / n   # fallback to equal weight

    # Clean up near-zero weights
    best_result = np.clip(best_result, 0, 1)
    best_result /= best_result.sum()
    return best_result
