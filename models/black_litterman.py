"""
Black-Litterman Model
---------------------
Implements the Black-Litterman (1990, 1992) asset allocation model
exactly as derived in the Baele (Tilburg University) slides.

Theory recap
------------
Markowitz mean-variance optimisation fails in practice because:
  - Optimal weights are extreme and counter-intuitive.
  - Weights are hypersensitive to small changes in expected returns.
  - There is no principled way to embed forward-looking views.

Black-Litterman solution (slide 3):
  1. Start from equilibrium expected returns implied by market-cap weights
     via REVERSE OPTIMISATION: μ_eq = γ Σ w_mkt   (slide 6, 18)
  2. Allow the manager to express K views (absolute or relative).
  3. Bayesian mix: blend equilibrium with views, weighted by their
     respective uncertainty.  The resulting μ_BL is the posterior mean.
  4. Reoptimise using μ_BL → sensible, diversified weights (slide 31).

Key parameters (slides 19-21)
------------------------------
γ  — risk-aversion coefficient. Set so that implied MRP of a reference
     asset equals a target (e.g. S&P500 implies 5.5 % excess return).
     γ = MRP / σ²_M  →  ensures CAPM and reverse-engineered ERs agree.

τ  — uncertainty in the equilibrium (precision of the prior).
     Empirically equal to the R² of predictive regressions → 5-15 %.

Ω  — diagonal covariance matrix of view errors.  Determined via
     Idzorek's method (slide 40):
       α_k = (1 − confidence_k) / confidence_k
       Ω_kk = α_k × [P_k (τΣ) P_k']
     At 100 % confidence Ω → 0, views dominate.
     At   0 % confidence Ω → ∞, equilibrium dominates.

BL formula (slide 27)
---------------------
  Σ̄  = (τΣ)⁻¹ + P' Ω⁻¹ P
  μ_BL = Σ̄⁻¹ [ (τΣ)⁻¹ μ_eq  +  P' Ω⁻¹ Q ]

Optimal weights (slide 6, 9, 31)
----------------------------------
  w_BL = (1/γ) Σ⁻¹ μ_BL          (unconstrained tangency portfolio)
  or constrained version via quadratic programming.

View file format (JSON)
-----------------------
{
  "views": [
    {
      "description": "AAPL will outperform MSFT by 2% (relative)",
      "type": "relative",
      "assets":  ["AAPL", "MSFT"],
      "weights": [1,      -1   ],    # sums to 0 for relative
      "expected_return": 0.02,
      "confidence": 0.65
    },
    {
      "description": "GOOGL will return 8% (absolute)",
      "type": "absolute",
      "assets":  ["GOOGL"],
      "weights": [1],                # sums to 1 for absolute
      "expected_return": 0.08,
      "confidence": 0.50
    }
  ]
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from models.portfolio import Portfolio


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TAU          = 0.05    # prior uncertainty (5 % → conservative)
DEFAULT_GAMMA        = 2.5     # risk aversion (calibrated to MRP ≈ 5.5 %)
DEFAULT_RISK_FREE    = 0.045   # risk-free rate (4.5 %)
TARGET_MRP           = 0.055   # target market risk premium used to set γ


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class View:
    """A single investor view on one or more assets."""
    description:     str
    type:            str        # 'absolute' or 'relative'
    assets:          List[str]
    weights:         List[float]  # sums to 1 (abs) or 0 (rel)
    expected_return: float      # annualised, e.g. 0.08 = 8 %
    confidence:      float      # 0-1, e.g. 0.65 = 65 %

    def validate(self):
        if not 0 < self.confidence <= 1:
            raise ValueError(f"Confidence must be in (0, 1], got {self.confidence}")
        if len(self.assets) != len(self.weights):
            raise ValueError("assets and weights must have the same length")


@dataclass
class BLResult:
    """All outputs of the Black-Litterman computation."""

    tickers:          List[str]

    # Parameters
    gamma:            float
    tau:              float
    risk_free:        float

    # Returns
    mu_eq:            np.ndarray   # equilibrium excess returns (annualised)
    mu_bl:            np.ndarray   # BL posterior expected excess returns
    mu_hist:          np.ndarray   # historical sample means (for comparison)

    # Weights
    w_market:         np.ndarray   # market-cap / current portfolio weights
    w_bl:             np.ndarray   # BL optimal weights (unconstrained)
    w_bl_constrained: np.ndarray   # BL optimal weights (long-only)

    # Matrices
    sigma:            np.ndarray   # annualised covariance matrix
    P:                np.ndarray   # view pick matrix  (K × N)
    Q:                np.ndarray   # view returns      (K,)
    Omega:            np.ndarray   # view uncertainty  (K × K)

    # Views
    views:            List[View]

    # Rebalancing
    rebalancing:      pd.DataFrame

    # Diagnostics
    implied_mrp:      float        # market risk premium implied by γ and w_market


# ---------------------------------------------------------------------------
# Core model
# ---------------------------------------------------------------------------

class BlackLittermanModel:
    """
    Full Black-Litterman model as presented in the Baele (2024) slides.

    Parameters
    ----------
    portfolio         : Portfolio model instance.
    tau               : Uncertainty in equilibrium prior (default 5 %).
    gamma             : Risk aversion coefficient. If None, calibrated
                        automatically so that the portfolio's implied
                        MRP ≈ TARGET_MRP.
    risk_free         : Annual risk-free rate.
    historical_period : yfinance period for covariance estimation.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        tau:              float = DEFAULT_TAU,
        gamma:            Optional[float] = None,
        risk_free:        float = DEFAULT_RISK_FREE,
        historical_period: str  = "3y",
    ) -> None:
        self.portfolio          = portfolio
        self.tau                = tau
        self.gamma              = gamma      # None → auto-calibrate
        self.risk_free          = risk_free
        self.historical_period  = historical_period

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, views: List[View]) -> BLResult:
        """
        Execute the full BL pipeline.

        Parameters
        ----------
        views : List of :class:`View` objects.

        Returns
        -------
        :class:`BLResult`
        """
        for v in views:
            v.validate()

        tickers = self.portfolio.get_tickers()
        if len(tickers) < 2:
            raise ValueError("Need at least 2 assets for BL.")

        # ── Step 1: historical covariance matrix ─────────────────────
        hist = self.portfolio.fetch_history(tickers, period=self.historical_period)
        available = [t for t in tickers if t in hist.columns]
        if len(available) < 2:
            raise ValueError("Not enough historical data.")
        tickers = available

        rets = hist[tickers].pct_change().dropna()
        Sigma = rets.cov().values * 252          # annualised N×N covariance
        mu_hist = rets.mean().values * 252        # annualised sample means

        N = len(tickers)

        # ── Step 2: market-cap weights (proxy = current portfolio MV) ─
        prices = self.portfolio.fetch_current_prices(tickers)
        total_val = sum(
            p.quantity * prices.get(p.ticker, 0.0)
            for p in self.portfolio.get_positions()
            if p.ticker in tickers
        )
        w_mkt = np.array([
            sum(
                p.quantity * prices.get(p.ticker, 0.0)
                for p in self.portfolio.get_positions()
                if p.ticker == t
            ) / max(total_val, 1e-9)
            for t in tickers
        ])
        w_mkt = np.clip(w_mkt, 0, None)
        w_mkt /= w_mkt.sum()

        # ── Step 3: calibrate γ (slide 19) ────────────────────────────
        # γ = MRP / σ²_M   where σ²_M = w' Σ w
        port_var = float(w_mkt @ Sigma @ w_mkt)
        if self.gamma is None:
            gamma = TARGET_MRP / max(port_var, 1e-9)
        else:
            gamma = self.gamma

        # Implied market risk premium (sanity check)
        implied_mrp = gamma * port_var

        # ── Step 4: equilibrium excess returns (slide 6, 18) ─────────
        # μ_eq = γ Σ w_mkt
        mu_eq = gamma * Sigma @ w_mkt

        # ── Step 5: build P, Q, Omega from views (slides 23, 29, 40) ─
        K = len(views)
        if K == 0:
            raise ValueError("At least one view is required.")

        P     = np.zeros((K, N))
        Q     = np.zeros(K)
        Omega = np.zeros((K, K))

        ticker_idx = {t: i for i, t in enumerate(tickers)}

        for k, view in enumerate(views):
            # Build pick vector
            for asset, weight in zip(view.assets, view.weights):
                if asset in ticker_idx:
                    P[k, ticker_idx[asset]] = weight

            Q[k] = view.expected_return

            # Idzorek Omega (slide 40):
            # α = (1 - confidence) / confidence
            # Ω_kk = α × P_k (τΣ) P_k'
            alpha_k = (1.0 - view.confidence) / max(view.confidence, 1e-9)
            Omega[k, k] = alpha_k * float(P[k] @ (self.tau * Sigma) @ P[k])

        # ── Step 6: BL posterior mean (slide 27) ─────────────────────
        # Σ̄⁻¹ = (τΣ)⁻¹ + P' Ω⁻¹ P
        # μ_BL = Σ̄ × [ (τΣ)⁻¹ μ_eq + P' Ω⁻¹ Q ]
        tau_Sigma     = self.tau * Sigma
        tau_Sigma_inv = np.linalg.inv(tau_Sigma + np.eye(N) * 1e-8)
        Omega_inv     = np.diag(1.0 / np.diag(Omega).clip(1e-10))

        Sigma_bar_inv = tau_Sigma_inv + P.T @ Omega_inv @ P
        Sigma_bar     = np.linalg.inv(Sigma_bar_inv + np.eye(N) * 1e-8)

        rhs    = tau_Sigma_inv @ mu_eq + P.T @ Omega_inv @ Q
        mu_bl  = Sigma_bar @ rhs

        # ── Step 7: optimal BL weights (slide 6, 9) ──────────────────
        Sigma_inv = np.linalg.inv(Sigma + np.eye(N) * 1e-8)

        # Unconstrained tangency (slide 9): w* = (1/γ) Σ⁻¹ μ_BL
        w_bl_uncon = (1.0 / gamma) * Sigma_inv @ mu_bl

        # Long-only constrained (practical, insurance context)
        w_bl_con = self._constrained_bl_weights(mu_bl, Sigma, gamma)

        # ── Step 8: rebalancing table ─────────────────────────────────
        rebalancing = pd.DataFrame({
            "ticker":         tickers,
            "w_current":      w_mkt,
            "w_eq_implied":   w_mkt,              # equilibrium = current by construction
            "w_bl_constrained": w_bl_con,
            "delta":          w_bl_con - w_mkt,
            "mu_eq":          mu_eq,
            "mu_bl":          mu_bl,
            "mu_hist":        mu_hist,
        })
        rebalancing["return_revision"] = rebalancing["mu_bl"] - rebalancing["mu_eq"]
        rebalancing = rebalancing.sort_values("delta", key=abs, ascending=False)

        return BLResult(
            tickers          = tickers,
            gamma            = gamma,
            tau              = self.tau,
            risk_free        = self.risk_free,
            mu_eq            = mu_eq,
            mu_bl            = mu_bl,
            mu_hist          = mu_hist,
            w_market         = w_mkt,
            w_bl             = w_bl_uncon,
            w_bl_constrained = w_bl_con,
            sigma            = Sigma,
            P                = P,
            Q                = Q,
            Omega            = Omega,
            views            = views,
            rebalancing      = rebalancing,
            implied_mrp      = implied_mrp,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _constrained_bl_weights(
        mu_bl: np.ndarray,
        Sigma: np.ndarray,
        gamma: float,
    ) -> np.ndarray:
        """
        Long-only constrained optimisation using BL expected returns.
        Maximises:  w' μ_BL − (γ/2) w' Σ w
        subject to: Σ w = 1,  w ≥ 0
        """
        N = len(mu_bl)

        def neg_utility(w):
            return -(w @ mu_bl - (gamma / 2) * w @ Sigma @ w)

        result = minimize(
            neg_utility,
            x0=np.ones(N) / N,
            method="SLSQP",
            bounds=[(0, 1)] * N,
            constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
            options={"ftol": 1e-10, "maxiter": 2000},
        )
        if result.success:
            w = np.clip(result.x, 0, 1)
            return w / w.sum()
        return np.ones(N) / N


# ---------------------------------------------------------------------------
# View file helpers
# ---------------------------------------------------------------------------

def load_views(filepath: str) -> List[View]:
    """Load views from a JSON file."""
    with open(filepath) as f:
        data = json.load(f)
    views = []
    for v in data.get("views", []):
        views.append(View(
            description     = v.get("description", ""),
            type            = v.get("type", "absolute"),
            assets          = v["assets"],
            weights         = v["weights"],
            expected_return = v["expected_return"],
            confidence      = v["confidence"],
        ))
    return views


def save_example_views(tickers: List[str], filepath: str) -> None:
    """
    Write a template views JSON file pre-populated with the user's tickers.
    Two example views: one absolute, one relative (if ≥ 2 tickers).
    """
    views = []

    # Absolute view on first ticker
    views.append({
        "description": f"{tickers[0]} will deliver 8% annual excess return",
        "type": "absolute",
        "assets":  [tickers[0]],
        "weights": [1],
        "expected_return": 0.08,
        "confidence": 0.60,
    })

    # Relative view if we have ≥ 2 tickers
    if len(tickers) >= 2:
        views.append({
            "description": (
                f"{tickers[0]} will outperform {tickers[1]} by 2%"
            ),
            "type": "relative",
            "assets":  [tickers[0], tickers[1]],
            "weights": [1, -1],
            "expected_return": 0.02,
            "confidence": 0.50,
        })

    data = {
        "_readme": (
            "Edit this file to specify your views. "
            "type='absolute' → weights sum to 1. "
            "type='relative' → weights sum to 0. "
            "confidence: 0-1 (1=fully confident, 0=ignore view)."
        ),
        "views": views,
    }
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
