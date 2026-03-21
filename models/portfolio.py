"""
Portfolio Model
---------------
Stores all asset positions and owns every calculation performed on the
portfolio: current values, weights, P&L, risk metrics and price history.
Data is persisted to a JSON file so the portfolio survives between sessions.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

from models.asset import Asset

# Default path for portfolio persistence
DEFAULT_DATA_FILE = Path(__file__).parent.parent / "data" / "portfolio.json"


class Portfolio:
    """
    Core model that manages a collection of :class:`Asset` positions.

    Responsibilities
    ----------------
    - Add / remove positions.
    - Persist and restore state to/from JSON.
    - Fetch real-time and historical prices via yfinance.
    - Compute weights, P&L, risk metrics and benchmark comparison.
    """

    def __init__(self, data_file: Path = DEFAULT_DATA_FILE) -> None:
        self.data_file = Path(data_file)
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self._positions: List[Asset] = []
        self._price_cache: Dict[str, float] = {}   # ticker -> latest price
        self._load()

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def add_position(self, asset: Asset) -> None:
        """Add a new purchase lot to the portfolio."""
        self._positions.append(asset)
        self._save()

    def remove_position(self, position_id: str) -> Optional[Asset]:
        """
        Remove a position by its ID.
        Returns the removed Asset, or None if not found.
        """
        for i, pos in enumerate(self._positions):
            if pos.position_id == position_id:
                removed = self._positions.pop(i)
                self._save()
                return removed
        return None

    def get_positions(self) -> List[Asset]:
        """Return all positions (read-only copy)."""
        return list(self._positions)

    def get_tickers(self) -> List[str]:
        """Unique list of tickers currently held."""
        return list({p.ticker for p in self._positions})

    def is_empty(self) -> bool:
        return len(self._positions) == 0

    # ------------------------------------------------------------------
    # Price data
    # ------------------------------------------------------------------

    def fetch_current_prices(self, tickers: Optional[List[str]] = None) -> Dict[str, float]:
        """
        Fetch the latest close price for each ticker via yfinance.
        Results are cached for the lifetime of this object.
        """
        tickers = tickers or self.get_tickers()
        if not tickers:
            return {}

        for ticker in tickers:
            try:
                info = yf.Ticker(ticker)
                hist = info.history(period="2d")
                if not hist.empty:
                    self._price_cache[ticker] = float(hist["Close"].iloc[-1])
                else:
                    self._price_cache[ticker] = 0.0
            except Exception:
                self._price_cache[ticker] = 0.0

        return dict(self._price_cache)

    def get_cached_price(self, ticker: str) -> float:
        """Return cached price or 0 if not yet fetched."""
        return self._price_cache.get(ticker, 0.0)

    def fetch_history(
        self,
        tickers: List[str],
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch OHLCV history for one or more tickers.

        Parameters
        ----------
        tickers  : List of ticker symbols.
        period   : yfinance period string (e.g. '1y', '5y', 'max').
        interval : yfinance interval string (e.g. '1d', '1wk').

        Returns
        -------
        DataFrame with Date index and Close prices in columns named by ticker.
        """
        if not tickers:
            return pd.DataFrame()

        dfs: Dict[str, pd.Series] = {}
        for ticker in tickers:
            try:
                raw = yf.Ticker(ticker).history(period=period, interval=interval)
                if not raw.empty:
                    dfs[ticker] = raw["Close"]
            except Exception:
                pass

        if not dfs:
            return pd.DataFrame()

        df = pd.DataFrame(dfs)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df

    def get_asset_info(self, ticker: str) -> dict:
        """Return metadata (name, currency, sector) from yfinance."""
        try:
            info = yf.Ticker(ticker).info
            return {
                "name": info.get("longName", ticker),
                "currency": info.get("currency", "USD"),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "market_cap": info.get("marketCap", None),
                "pe_ratio": info.get("trailingPE", None),
                "52w_high": info.get("fiftyTwoWeekHigh", None),
                "52w_low": info.get("fiftyTwoWeekLow", None),
                "dividend_yield": info.get("dividendYield", None),
                "beta": info.get("beta", None),
            }
        except Exception:
            return {"name": ticker, "currency": "USD"}

    # ------------------------------------------------------------------
    # Portfolio-level calculations
    # ------------------------------------------------------------------

    def total_invested(self) -> float:
        """Sum of all transaction values (cost basis)."""
        return sum(p.transaction_value for p in self._positions)

    def total_current_value(self) -> float:
        """Sum of current market values across all positions."""
        return sum(
            p.current_value(self._price_cache.get(p.ticker, 0.0))
            for p in self._positions
        )

    def total_profit_loss(self) -> float:
        """Absolute portfolio P&L."""
        return self.total_current_value() - self.total_invested()

    def total_profit_loss_pct(self) -> float:
        """Relative portfolio P&L as a percentage."""
        invested = self.total_invested()
        if invested == 0:
            return 0.0
        return (self.total_profit_loss() / invested) * 100

    # ------------------------------------------------------------------
    # Weight calculations
    # ------------------------------------------------------------------

    def position_weights(self) -> List[dict]:
        """
        Per-position breakdown with current value and weight in portfolio.

        Returns a list of dicts, one per position, sorted by weight descending.
        """
        total = self.total_current_value()
        rows = []
        for p in self._positions:
            cur_price = self._price_cache.get(p.ticker, 0.0)
            cur_val = p.current_value(cur_price)
            rows.append(
                {
                    "position_id": p.position_id,
                    "ticker": p.ticker,
                    "name": p.name or p.ticker,
                    "sector": p.sector,
                    "asset_class": p.asset_class,
                    "quantity": p.quantity,
                    "purchase_price": p.purchase_price,
                    "current_price": cur_price,
                    "transaction_value": p.transaction_value,
                    "current_value": cur_val,
                    "profit_loss": p.profit_loss(cur_price),
                    "profit_loss_pct": p.profit_loss_pct(cur_price),
                    "weight": (cur_val / total * 100) if total > 0 else 0.0,
                    "purchase_date": p.purchase_date,
                    "currency": p.currency,
                }
            )
        return sorted(rows, key=lambda x: x["weight"], reverse=True)

    def weights_by_group(self, group_by: str = "sector") -> List[dict]:
        """
        Aggregate weights by 'sector', 'asset_class', or 'ticker'.

        Parameters
        ----------
        group_by : One of 'sector', 'asset_class', 'ticker'.

        Returns
        -------
        List of dicts with group label, total value, weight, P&L.
        """
        totals: Dict[str, dict] = defaultdict(
            lambda: {"current_value": 0.0, "transaction_value": 0.0}
        )

        for p in self._positions:
            key = getattr(p, group_by, "Unknown")
            cur_price = self._price_cache.get(p.ticker, 0.0)
            totals[key]["current_value"] += p.current_value(cur_price)
            totals[key]["transaction_value"] += p.transaction_value

        total_val = sum(v["current_value"] for v in totals.values())

        rows = []
        for label, vals in totals.items():
            cv = vals["current_value"]
            tv = vals["transaction_value"]
            pl = cv - tv
            rows.append(
                {
                    group_by: label,
                    "current_value": cv,
                    "transaction_value": tv,
                    "profit_loss": pl,
                    "profit_loss_pct": (pl / tv * 100) if tv > 0 else 0.0,
                    "weight": (cv / total_val * 100) if total_val > 0 else 0.0,
                }
            )
        return sorted(rows, key=lambda x: x["weight"], reverse=True)

    # ------------------------------------------------------------------
    # Risk metrics
    # ------------------------------------------------------------------

    def compute_risk_metrics(
        self,
        benchmark_ticker: str = "^GSPC",
        period: str = "1y",
    ) -> dict:
        """
        Compute portfolio-level risk metrics using historical data.

        Metrics
        -------
        annualised_return    : Geometric mean annual return.
        annualised_volatility: Annualised standard deviation of daily returns.
        sharpe_ratio         : (return - rf) / vol  (rf assumed 4.5 %).
        max_drawdown         : Worst peak-to-trough decline.
        var_95               : Historical 1-day VaR at 95 % confidence.
        cvar_95              : Conditional VaR (Expected Shortfall) at 95 %.
        beta                 : Sensitivity to benchmark (S&P 500 by default).
        """
        tickers = self.get_tickers()
        if not tickers:
            return {}

        # Fetch history for all portfolio tickers + benchmark
        all_tickers = tickers + [benchmark_ticker]
        hist_close = self.fetch_history(all_tickers, period=period)
        if hist_close.empty:
            return {}

        # Portfolio weights by current value
        prices = self.fetch_current_prices(tickers)
        total_val = sum(
            p.quantity * prices.get(p.ticker, 0.0) for p in self._positions
        )
        weights: Dict[str, float] = defaultdict(float)
        for p in self._positions:
            if total_val > 0:
                weights[p.ticker] += (
                    p.quantity * prices.get(p.ticker, 0.0) / total_val
                )

        # Daily log returns for portfolio tickers that have data
        port_tickers_in_hist = [t for t in tickers if t in hist_close.columns]
        if not port_tickers_in_hist:
            return {}

        port_daily_rets = pd.Series(0.0, index=hist_close.index)
        for ticker in port_tickers_in_hist:
            w = weights.get(ticker, 0.0)
            rets = hist_close[ticker].pct_change().fillna(0)
            port_daily_rets += w * rets

        port_daily_rets = port_daily_rets.iloc[1:]  # drop first NaN row

        # Annualised metrics
        ann_return = (1 + port_daily_rets.mean()) ** 252 - 1
        ann_vol = port_daily_rets.std() * np.sqrt(252)
        rf = 0.045  # risk-free rate assumption
        sharpe = (ann_return - rf) / ann_vol if ann_vol > 0 else 0.0

        # Max drawdown
        cum = (1 + port_daily_rets).cumprod()
        rolling_max = cum.cummax()
        drawdown = (cum - rolling_max) / rolling_max
        max_dd = drawdown.min()

        # VaR / CVaR
        var_95 = float(np.percentile(port_daily_rets, 5))
        cvar_95 = float(port_daily_rets[port_daily_rets <= var_95].mean())

        # Beta relative to benchmark
        beta = None
        if benchmark_ticker in hist_close.columns:
            bench_rets = hist_close[benchmark_ticker].pct_change().dropna()
            aligned = pd.concat(
                [port_daily_rets, bench_rets], axis=1, join="inner"
            ).dropna()
            if len(aligned) > 20:
                cov = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])
                beta = cov[0, 1] / cov[1, 1]

        return {
            "annualised_return": ann_return,
            "annualised_volatility": ann_vol,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "var_95": var_95,
            "cvar_95": cvar_95,
            "beta": beta,
            "risk_free_rate": rf,
            "benchmark": benchmark_ticker,
        }

    def portfolio_daily_returns(self, period: str = "1y") -> pd.Series:
        """
        Compute the weighted daily return series for the portfolio.
        Used by the simulation model.
        """
        tickers = self.get_tickers()
        if not tickers:
            return pd.Series(dtype=float)

        hist_close = self.fetch_history(tickers, period=period)
        prices = self._price_cache or self.fetch_current_prices(tickers)

        total_val = sum(
            p.quantity * prices.get(p.ticker, 0.0) for p in self._positions
        )
        weights: Dict[str, float] = defaultdict(float)
        for p in self._positions:
            if total_val > 0:
                weights[p.ticker] += (
                    p.quantity * prices.get(p.ticker, 0.0) / total_val
                )

        port_rets = pd.Series(0.0, index=hist_close.index)
        for ticker in tickers:
            if ticker in hist_close.columns:
                rets = hist_close[ticker].pct_change().fillna(0)
                port_rets += weights.get(ticker, 0.0) * rets

        return port_rets.iloc[1:]

    def per_ticker_stats(self, period: str = "1y") -> Dict[str, dict]:
        """
        Per-ticker annualised return and volatility — used by simulation.
        Returns dict: ticker -> {mu, sigma, last_price}
        """
        tickers = self.get_tickers()
        if not tickers:
            return {}

        hist = self.fetch_history(tickers, period=period)
        prices = self.fetch_current_prices(tickers)
        stats = {}

        for ticker in tickers:
            if ticker not in hist.columns:
                continue
            rets = hist[ticker].pct_change().dropna()
            mu = rets.mean() * 252        # annualised drift
            sigma = rets.std() * np.sqrt(252)  # annualised vol
            stats[ticker] = {
                "mu": mu,
                "sigma": sigma,
                "last_price": prices.get(ticker, 0.0),
            }

        return stats

    def correlation_matrix(self, period: str = "2y") -> Optional[pd.DataFrame]:
        """Return pairwise correlation matrix of daily returns."""
        tickers = self.get_tickers()
        if len(tickers) < 2:
            return None
        hist = self.fetch_history(tickers, period=period)
        if hist.empty:
            return None
        return hist.pct_change().dropna().corr()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Serialise portfolio to JSON."""
        data = {
            "positions": [p.to_dict() for p in self._positions],
            "last_updated": datetime.utcnow().isoformat(),
        }
        with open(self.data_file, "w") as f:
            json.dump(data, f, indent=2)

    def _load(self) -> None:
        """Restore portfolio from JSON (silently ignores missing file)."""
        if not self.data_file.exists():
            return
        try:
            with open(self.data_file) as f:
                data = json.load(f)
            self._positions = [Asset.from_dict(p) for p in data.get("positions", [])]
        except (json.JSONDecodeError, KeyError, TypeError):
            self._positions = []

    def export_to_csv(self, filepath: str) -> str:
        """Export position-level detail to CSV and return the path."""
        rows = self.position_weights()
        df = pd.DataFrame(rows)
        df.to_csv(filepath, index=False)
        return filepath
