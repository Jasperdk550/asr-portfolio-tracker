"""
Simulation Model
----------------
Runs a 100 000-path Monte Carlo simulation over 15 years using correlated
Geometric Brownian Motion (GBM) for each asset in the portfolio.

Key design choices
------------------
- Uses the Cholesky decomposition of the historical correlation matrix to
  model return co-movements realistically.
- Processes simulations in batches of 5 000 to stay within ≈ 300 MB RAM.
- Stores portfolio values at 180 monthly checkpoints (not every daily step)
  for efficient percentile calculation.
- Returns both a full percentile fan (5 / 25 / 50 / 75 / 95) and summary
  statistics at the 15-year horizon.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from models.portfolio import Portfolio


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

N_PATHS: int = 100_000
N_YEARS: int = 15
TRADING_DAYS_PER_YEAR: int = 252
N_STEPS: int = N_YEARS * TRADING_DAYS_PER_YEAR   # 3 780 daily steps
N_CHECKPOINTS: int = N_YEARS * 12                 # 180 monthly checkpoints
BATCH_SIZE: int = 5_000                           # paths per batch (memory)

PERCENTILES = [5, 10, 25, 50, 75, 90, 95]


@dataclass
class SimulationResult:
    """Container for the output of :func:`run_simulation`."""

    initial_value: float
    years: np.ndarray                  # shape (N_CHECKPOINTS,)
    percentile_paths: Dict[int, np.ndarray]  # pct -> shape (N_CHECKPOINTS,)
    final_values: np.ndarray           # shape (N_PATHS,) – all terminal values
    scenario_stats: dict               # summary stats at 15-year horizon
    per_ticker_params: dict            # mu / sigma per ticker (info)
    n_paths: int
    n_years: int


class SimulationModel:
    """
    Orchestrates the Monte Carlo simulation for a :class:`Portfolio`.

    Usage
    -----
    >>> model = SimulationModel(portfolio)
    >>> result = model.run(progress_callback=print)
    """

    def __init__(self, portfolio: Portfolio) -> None:
        self.portfolio = portfolio

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        n_paths: int = N_PATHS,
        n_years: int = N_YEARS,
        historical_period: str = "5y",
        progress_callback=None,
    ) -> SimulationResult:
        """
        Execute the Monte Carlo simulation.

        Parameters
        ----------
        n_paths           : Total number of simulated paths (default 100 000).
        n_years           : Forecast horizon in years (default 15).
        historical_period : yfinance period used to estimate parameters.
        progress_callback : Optional callable(int pct) for progress updates.

        Returns
        -------
        :class:`SimulationResult`
        """
        # Step 1 – gather inputs from the portfolio model
        tickers = self.portfolio.get_tickers()
        if not tickers:
            raise ValueError("Portfolio is empty — nothing to simulate.")

        if progress_callback:
            progress_callback(5, "Fetching historical data…")

        ticker_stats = self.portfolio.per_ticker_stats(period=historical_period)
        prices = self.portfolio.fetch_current_prices(tickers)

        # Filter to tickers we actually have parameters for
        tickers = [t for t in tickers if t in ticker_stats]
        n_assets = len(tickers)

        if n_assets == 0:
            raise ValueError("Could not retrieve historical data for any ticker.")

        # Step 2 – compute portfolio weights (by current market value)
        total_val = sum(
            p.quantity * prices.get(p.ticker, 0.0)
            for p in self.portfolio.get_positions()
            if p.ticker in tickers
        )
        weights = np.array(
            [
                sum(
                    p.quantity * prices.get(p.ticker, 0.0)
                    for p in self.portfolio.get_positions()
                    if p.ticker == t
                )
                / max(total_val, 1e-9)
                for t in tickers
            ]
        )

        # Step 3 – build parameter vectors
        mu = np.array([ticker_stats[t]["mu"] for t in tickers])     # annualised
        sigma = np.array([ticker_stats[t]["sigma"] for t in tickers])

        # Clamp drift to avoid extreme outliers from short history
        mu = np.clip(mu, -0.50, 1.00)

        # Correlation matrix (fall back to identity if < 2 assets)
        corr = self.portfolio.correlation_matrix(period=historical_period)
        if corr is not None and n_assets > 1:
            # .copy() ensures the array is writable (yfinance can return read-only views)
            corr_mat = corr.reindex(index=tickers, columns=tickers).fillna(0).values.copy()
            np.fill_diagonal(corr_mat, 1.0)
        else:
            corr_mat = np.eye(n_assets)

        # Cholesky factor for correlated noise
        try:
            L = np.linalg.cholesky(corr_mat)
        except np.linalg.LinAlgError:
            # Fall back to identity (treat assets as uncorrelated)
            L = np.eye(n_assets)

        if progress_callback:
            progress_callback(15, "Running simulation…")

        # Step 4 – simulation parameters
        n_steps = n_years * TRADING_DAYS_PER_YEAR
        n_checkpoints = n_years * 12
        checkpoint_indices = np.linspace(0, n_steps - 1, n_checkpoints, dtype=int)

        # Daily parameters from annualised — .copy() guards against read-only views
        dt = 1.0 / TRADING_DAYS_PER_YEAR
        mu_dt         = np.asarray((mu - 0.5 * sigma**2) * dt,  dtype=np.float64).copy()
        sigma_sqrt_dt = np.asarray(sigma * np.sqrt(dt),          dtype=np.float64).copy()
        weights       = np.asarray(weights,                       dtype=np.float64).copy()

        # Storage for checkpoint portfolio values across all paths
        # Shape: (n_checkpoints, n_paths) – filled in batches
        checkpoint_values = np.zeros((n_checkpoints, n_paths), dtype=np.float32)

        n_batches = (n_paths + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_idx in range(n_batches):
            start = batch_idx * BATCH_SIZE
            end = min(start + BATCH_SIZE, n_paths)
            b = end - start  # actual batch size

            if progress_callback:
                pct = 15 + int(75 * batch_idx / n_batches)
                progress_callback(pct, f"Batch {batch_idx + 1}/{n_batches}…")

            # Asset log-prices relative to start (start = 0)
            # Shape: (n_assets, b)
            log_prices = np.zeros((n_assets, b), dtype=np.float64)

            cp_step = 0  # checkpoint counter

            for step in range(n_steps):
                # Correlated standard normals: (n_assets, b)
                z = L @ np.random.standard_normal((n_assets, b))
                # GBM update in log-space
                log_prices += mu_dt[:, None] + sigma_sqrt_dt[:, None] * z

                if step == checkpoint_indices[cp_step]:
                    # Portfolio value = sum of weighted price ratios
                    asset_growth = np.exp(log_prices)   # shape (n_assets, b)
                    port_growth = weights @ asset_growth  # shape (b,)
                    checkpoint_values[cp_step, start:end] = (
                        total_val * port_growth
                    ).astype(np.float32)
                    cp_step += 1
                    if cp_step >= n_checkpoints:
                        break

        if progress_callback:
            progress_callback(92, "Computing statistics…")

        # Step 5 – compute percentile paths
        years_axis = np.linspace(1 / 12, n_years, n_checkpoints)
        pct_paths = {
            p: np.percentile(checkpoint_values, p, axis=1)
            for p in PERCENTILES
        }

        # Final distribution (last checkpoint)
        final_values = checkpoint_values[-1, :].astype(np.float64)

        scenario_stats = self._scenario_stats(
            final_values, total_val, n_years
        )

        if progress_callback:
            progress_callback(100, "Done.")

        return SimulationResult(
            initial_value=total_val,
            years=years_axis,
            percentile_paths=pct_paths,
            final_values=final_values,
            scenario_stats=scenario_stats,
            per_ticker_params={
                t: {
                    "mu": float(ticker_stats[t]["mu"]),
                    "sigma": float(ticker_stats[t]["sigma"]),
                    "weight": float(weights[i]),
                }
                for i, t in enumerate(tickers)
            },
            n_paths=n_paths,
            n_years=n_years,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _scenario_stats(
        final_values: np.ndarray,
        initial_value: float,
        n_years: int,
    ) -> dict:
        """Compute summary statistics at the 15-year horizon."""
        sorted_vals = np.sort(final_values)

        def cagr(end_val: float) -> float:
            if initial_value <= 0 or end_val <= 0:
                return 0.0
            return (end_val / initial_value) ** (1.0 / n_years) - 1.0

        p5, p10, p25, p50, p75, p90, p95 = np.percentile(
            final_values, [5, 10, 25, 50, 75, 90, 95]
        )
        prob_loss = float(np.mean(final_values < initial_value))
        prob_double = float(np.mean(final_values >= 2 * initial_value))
        prob_triple = float(np.mean(final_values >= 3 * initial_value))

        return {
            "initial_value": initial_value,
            "mean": float(np.mean(final_values)),
            "median": float(p50),
            "std": float(np.std(final_values)),
            "p5": float(p5),
            "p10": float(p10),
            "p25": float(p25),
            "p50": float(p50),
            "p75": float(p75),
            "p90": float(p90),
            "p95": float(p95),
            "prob_loss": prob_loss,
            "prob_double": prob_double,
            "prob_triple": prob_triple,
            "cagr_median": cagr(p50),
            "cagr_p25": cagr(p25),
            "cagr_p75": cagr(p75),
        }
