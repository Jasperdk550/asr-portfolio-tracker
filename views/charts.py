"""
Charts View
-----------
All matplotlib / seaborn visualisations.  Every function receives
pre-computed data from the controller and produces a figure — it
never fetches data itself.
"""

from __future__ import annotations

import warnings
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")   # non-interactive backend (safe for CLI)

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

try:
    import seaborn as sns
    HAS_SEABORN = True
except ImportError:
    HAS_SEABORN = False

# ------------------------------------------------------------------
# Global style
# ------------------------------------------------------------------
ASR_BLUE   = "#003082"
ASR_GREEN  = "#00A651"
ASR_ORANGE = "#F26522"
ASR_GREY   = "#808080"
PALETTE    = [ASR_BLUE, ASR_GREEN, ASR_ORANGE, "#9B59B6", "#E74C3C",
              "#2ECC71", "#F39C12", "#1ABC9C", "#D35400", "#8E44AD"]


def _apply_style(ax: plt.Axes) -> None:
    ax.set_facecolor("#0d1117")
    ax.figure.patch.set_facecolor("#0d1117")
    ax.tick_params(colors="#cccccc")
    ax.xaxis.label.set_color("#cccccc")
    ax.yaxis.label.set_color("#cccccc")
    ax.title.set_color("white")
    for spine in ax.spines.values():
        spine.set_edgecolor("#333333")
    ax.grid(color="#1f2937", linestyle="--", linewidth=0.5, alpha=0.7)


def _money_fmt(x, _):
    """Y-axis formatter showing values as $k or $M."""
    if abs(x) >= 1e6:
        return f"${x/1e6:.1f}M"
    if abs(x) >= 1e3:
        return f"${x/1e3:.0f}k"
    return f"${x:.0f}"


# ------------------------------------------------------------------
# 1 – Price history
# ------------------------------------------------------------------

def plot_price_history(
    history_df: pd.DataFrame,
    tickers: List[str],
    period: str = "1y",
    save_path: Optional[str] = None,
) -> str:
    """
    Multi-line chart of closing prices, normalised to 100 when
    more than one ticker is shown (makes comparison easy).
    """
    if history_df is None or history_df.empty:
        print("No data to plot.")
        return ""

    fig, axes = plt.subplots(
        2 if len(tickers) == 1 else 1,
        1,
        figsize=(14, 8 if len(tickers) == 1 else 5),
        facecolor="#0d1117",
    )
    if not isinstance(axes, np.ndarray):
        axes = [axes]

    ax = axes[0]
    _apply_style(ax)

    # Normalise to 100 for multi-ticker comparison
    normalise = len(tickers) > 1
    for i, ticker in enumerate(tickers):
        if ticker not in history_df.columns:
            continue
        series = history_df[ticker].dropna()
        if normalise:
            series = series / series.iloc[0] * 100
        colour = PALETTE[i % len(PALETTE)]
        ax.plot(series.index, series.values, color=colour,
                linewidth=1.8, label=ticker)
        # Shaded area under curve for single ticker
        if not normalise:
            ax.fill_between(series.index, series.values,
                            alpha=0.1, color=colour)

    ylabel = "Indexed Price (start=100)" if normalise else "Price (USD)"
    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_title(
        f"{'  vs  '.join(tickers)} — Closing Price ({period})",
        fontsize=13, fontweight="bold", color="white",
    )
    ax.legend(facecolor="#1f2937", labelcolor="white", fontsize=9)
    if not normalise:
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(_money_fmt))

    # For single ticker — add volume or rolling return subplot
    if len(tickers) == 1 and len(axes) > 1:
        ax2 = axes[1]
        _apply_style(ax2)
        ticker = tickers[0]
        if ticker in history_df.columns:
            rets = history_df[ticker].pct_change().dropna() * 100
            colours_bar = [ASR_GREEN if r >= 0 else "#E74C3C" for r in rets]
            ax2.bar(rets.index, rets.values, color=colours_bar, width=1.2)
            ax2.axhline(0, color=ASR_GREY, linewidth=0.7)
            ax2.set_ylabel("Daily Return (%)", fontsize=9)
            ax2.set_title("Daily Returns", fontsize=10, color="white")

    plt.tight_layout()
    path = _save_or_show(fig, save_path, "price_history")
    return path


# ------------------------------------------------------------------
# 2 – Pie / donut charts
# ------------------------------------------------------------------

def plot_allocation(
    weights_by_sector: List[dict],
    weights_by_class: List[dict],
    save_path: Optional[str] = None,
) -> str:
    """Side-by-side donut charts for sector and asset-class allocation."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6),
                                    facecolor="#0d1117")

    def _donut(ax, rows, group_key, title):
        labels = [r[group_key] for r in rows]
        sizes  = [r["weight"] for r in rows]
        colours = PALETTE[: len(rows)]
        wedges, texts, autotexts = ax.pie(
            sizes, labels=None, colors=colours,
            autopct="%1.1f%%", startangle=90,
            wedgeprops=dict(width=0.55, edgecolor="#0d1117"),
            pctdistance=0.82,
        )
        for at in autotexts:
            at.set_color("white")
            at.set_fontsize(8)
        ax.set_facecolor("#0d1117")
        ax.set_title(title, color="white", fontsize=12, fontweight="bold")
        ax.legend(
            wedges, labels,
            loc="lower center",
            facecolor="#1f2937",
            labelcolor="white",
            fontsize=8,
            ncol=2,
            bbox_to_anchor=(0.5, -0.15),
        )

    _donut(ax1, weights_by_sector, "sector", "By Sector")
    _donut(ax2, weights_by_class, "asset_class", "By Asset Class")

    fig.suptitle("Portfolio Allocation", color="white",
                 fontsize=15, fontweight="bold", y=1.01)
    plt.tight_layout()
    path = _save_or_show(fig, save_path, "allocation")
    return path


# ------------------------------------------------------------------
# 3 – Portfolio value waterfall / bar
# ------------------------------------------------------------------

def plot_portfolio_bar(
    positions: List[dict],
    save_path: Optional[str] = None,
) -> str:
    """Horizontal bar chart of position market values."""
    if not positions:
        return ""

    tickers = [f"{p['ticker']}\n({p['position_id']})" for p in positions]
    values  = [p["current_value"] for p in positions]
    colours = [ASR_GREEN if p["profit_loss"] >= 0 else "#E74C3C"
               for p in positions]

    fig, ax = plt.subplots(figsize=(12, max(4, len(positions) * 0.55)),
                           facecolor="#0d1117")
    _apply_style(ax)

    bars = ax.barh(tickers, values, color=colours, edgecolor="#0d1117")
    ax.set_xlabel("Market Value (USD)", fontsize=10)
    ax.set_title("Holdings — Market Value", fontsize=13,
                 fontweight="bold", color="white")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(_money_fmt))

    for bar, row in zip(bars, positions):
        pnl_pct = row["profit_loss_pct"]
        label_colour = ASR_GREEN if pnl_pct >= 0 else "#E74C3C"
        sign = "+" if pnl_pct >= 0 else ""
        ax.text(
            bar.get_width() * 1.01, bar.get_y() + bar.get_height() / 2,
            f"{sign}{pnl_pct:.1f}%",
            va="center", ha="left", color=label_colour, fontsize=8,
        )

    plt.tight_layout()
    path = _save_or_show(fig, save_path, "portfolio_bar")
    return path


# ------------------------------------------------------------------
# 4 – Monte Carlo fan chart
# ------------------------------------------------------------------

def plot_simulation(
    result,
    save_path: Optional[str] = None,
) -> str:
    """
    Fan chart showing the 5/25/50/75/95th percentile paths of the
    Monte Carlo simulation, plus the terminal value histogram.
    """
    years       = result.years
    pct_paths   = result.percentile_paths
    init        = result.initial_value
    final_vals  = result.final_values
    stats       = result.scenario_stats

    fig = plt.figure(figsize=(16, 10), facecolor="#0d1117")
    gs  = fig.add_gridspec(2, 2, hspace=0.38, wspace=0.3)
    ax_fan  = fig.add_subplot(gs[:, 0])   # fan chart (left, full height)
    ax_hist = fig.add_subplot(gs[0, 1])   # terminal histogram (top right)
    ax_cdf  = fig.add_subplot(gs[1, 1])   # CDF (bottom right)

    # ── Fan chart ──────────────────────────────────────────────────
    _apply_style(ax_fan)
    x = np.concatenate([[0], years])

    def _path(pct):
        return np.concatenate([[init], pct_paths[pct]])

    ax_fan.fill_between(x, _path(5),  _path(95),
                        alpha=0.15, color=ASR_BLUE,  label="5–95th pct")
    ax_fan.fill_between(x, _path(10), _path(90),
                        alpha=0.20, color=ASR_BLUE,  label="10–90th pct")
    ax_fan.fill_between(x, _path(25), _path(75),
                        alpha=0.30, color=ASR_GREEN, label="25–75th pct")

    ax_fan.plot(x, _path(50), color="white",    linewidth=2.2, label="Median")
    ax_fan.plot(x, _path(5),  color="#E74C3C",  linewidth=0.9, linestyle="--",
                label="5th / 95th pct", alpha=0.8)
    ax_fan.plot(x, _path(95), color="#E74C3C",  linewidth=0.9, linestyle="--",
                alpha=0.8)

    ax_fan.axhline(init, color=ASR_GREY, linewidth=1.2, linestyle=":",
                   label=f"Initial value ({_money_fmt(init, None)})")

    ax_fan.set_xlabel("Years", fontsize=10)
    ax_fan.set_ylabel("Portfolio Value", fontsize=10)
    ax_fan.set_title(
        f"Monte Carlo Fan Chart\n{result.n_paths:,} paths × {result.n_years} years",
        fontsize=12, fontweight="bold", color="white",
    )
    ax_fan.yaxis.set_major_formatter(mticker.FuncFormatter(_money_fmt))
    ax_fan.legend(facecolor="#1f2937", labelcolor="white", fontsize=8,
                  loc="upper left")

    # Annotate median at horizon
    med_end = float(pct_paths[50][-1])
    ax_fan.annotate(
        f"Median\n{_money_fmt(med_end, None)}",
        xy=(years[-1], med_end),
        xytext=(-70, 20),
        textcoords="offset points",
        color="white",
        fontsize=8,
        arrowprops=dict(arrowstyle="->", color="white", lw=0.8),
    )

    # ── Terminal histogram ──────────────────────────────────────────
    _apply_style(ax_hist)
    sample = final_vals[::max(1, len(final_vals) // 5000)]  # downsample
    n, bins, patches = ax_hist.hist(sample, bins=60, color=ASR_BLUE,
                                    edgecolor="#0d1117", alpha=0.85)

    # Colour bars below initial value red
    for patch, left in zip(patches, bins[:-1]):
        if left < init:
            patch.set_facecolor("#E74C3C")

    ax_hist.axvline(init,           color="white",   linestyle=":",
                    linewidth=1.2, label="Initial value")
    ax_hist.axvline(stats["p50"],   color=ASR_GREEN, linestyle="--",
                    linewidth=1.2, label="Median")
    ax_hist.axvline(stats["p5"],    color="#E74C3C", linestyle="--",
                    linewidth=1.0, label="5th pct")

    ax_hist.set_xlabel("Terminal Value", fontsize=9)
    ax_hist.set_ylabel("Frequency", fontsize=9)
    ax_hist.set_title("Terminal Value Distribution\n(Year 15)", fontsize=10,
                       fontweight="bold", color="white")
    ax_hist.xaxis.set_major_formatter(mticker.FuncFormatter(_money_fmt))
    ax_hist.legend(facecolor="#1f2937", labelcolor="white", fontsize=7)

    # ── CDF ────────────────────────────────────────────────────────
    _apply_style(ax_cdf)
    sorted_vals = np.sort(final_vals)
    cdf = np.arange(1, len(sorted_vals) + 1) / len(sorted_vals)
    ax_cdf.plot(sorted_vals, cdf * 100, color=ASR_GREEN, linewidth=1.5)

    # Reference lines
    prob_loss = stats["prob_loss"] * 100
    ax_cdf.axvline(init, color="white", linestyle=":", linewidth=1.0)
    ax_cdf.axhline(prob_loss, color="#E74C3C", linestyle="--",
                   linewidth=0.9, alpha=0.8)
    ax_cdf.text(sorted_vals[-1] * 0.02, prob_loss + 2,
                f"P(loss)={prob_loss:.1f}%", color="#E74C3C", fontsize=7)

    ax_cdf.set_xlabel("Terminal Value", fontsize=9)
    ax_cdf.set_ylabel("Cumulative Probability (%)", fontsize=9)
    ax_cdf.set_title("Cumulative Distribution\n(Year 15)", fontsize=10,
                      fontweight="bold", color="white")
    ax_cdf.xaxis.set_major_formatter(mticker.FuncFormatter(_money_fmt))
    ax_cdf.set_ylim(0, 100)

    fig.suptitle(
        "Portfolio Monte Carlo Simulation — Risk & Uncertainty Analysis",
        color="white", fontsize=14, fontweight="bold", y=1.005,
    )

    path = _save_or_show(fig, save_path, "simulation")
    return path


# ------------------------------------------------------------------
# 5 – Correlation matrix heatmap
# ------------------------------------------------------------------

def plot_correlation_matrix(
    corr: pd.DataFrame,
    save_path: Optional[str] = None,
) -> str:
    """Heatmap of pairwise return correlations."""
    if corr is None or corr.empty:
        print("No correlation data.")
        return ""

    fig, ax = plt.subplots(figsize=(max(6, len(corr) + 2),
                                    max(5, len(corr) + 1)),
                            facecolor="#0d1117")
    _apply_style(ax)

    cmap = plt.cm.RdYlGn
    im = ax.imshow(corr.values, cmap=cmap, vmin=-1, vmax=1, aspect="auto")

    ax.set_xticks(range(len(corr.columns)))
    ax.set_yticks(range(len(corr.index)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right", color="#cccccc")
    ax.set_yticklabels(corr.index, color="#cccccc")

    for i in range(len(corr)):
        for j in range(len(corr.columns)):
            val = corr.values[i, j]
            text_colour = "black" if abs(val) < 0.5 else "white"
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    fontsize=9, color=text_colour, fontweight="bold")

    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    ax.set_title("Return Correlation Matrix", fontsize=13,
                  fontweight="bold", color="white", pad=12)
    plt.tight_layout()
    path = _save_or_show(fig, save_path, "correlation")
    return path


# ------------------------------------------------------------------
# 6 – Performance vs benchmark
# ------------------------------------------------------------------

def plot_performance_vs_benchmark(
    portfolio_rets: pd.Series,
    benchmark_rets: pd.Series,
    benchmark_label: str = "S&P 500",
    save_path: Optional[str] = None,
) -> str:
    """Cumulative return comparison between portfolio and benchmark."""
    fig, ax = plt.subplots(figsize=(13, 6), facecolor="#0d1117")
    _apply_style(ax)

    def cum_ret(s):
        return (1 + s).cumprod() * 100

    port_cum  = cum_ret(portfolio_rets)
    bench_cum = cum_ret(benchmark_rets.reindex(portfolio_rets.index).fillna(0))

    ax.plot(port_cum.index, port_cum.values, color=ASR_BLUE,
            linewidth=2.0, label="Portfolio")
    ax.plot(bench_cum.index, bench_cum.values, color=ASR_ORANGE,
            linewidth=1.6, linestyle="--", label=benchmark_label)
    ax.axhline(100, color=ASR_GREY, linewidth=0.8, linestyle=":")

    ax.fill_between(port_cum.index,
                    port_cum.values, bench_cum.values,
                    where=port_cum.values >= bench_cum.values,
                    alpha=0.15, color=ASR_GREEN, label="Outperformance")
    ax.fill_between(port_cum.index,
                    port_cum.values, bench_cum.values,
                    where=port_cum.values < bench_cum.values,
                    alpha=0.15, color="#E74C3C", label="Underperformance")

    ax.set_ylabel("Cumulative Return (start=100)", fontsize=10)
    ax.set_title(f"Portfolio vs {benchmark_label}", fontsize=13,
                  fontweight="bold", color="white")
    ax.legend(facecolor="#1f2937", labelcolor="white", fontsize=9)
    plt.tight_layout()
    path = _save_or_show(fig, save_path, "benchmark")
    return path


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------

def _save_or_show(fig: plt.Figure, save_path: Optional[str],
                  default_name: str) -> str:
    """Save figure to file and return path."""
    from datetime import datetime
    import os

    if save_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = f"charts/{default_name}_{ts}.png"

    os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else ".",
                exist_ok=True)
    fig.savefig(save_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    return save_path


# ------------------------------------------------------------------
# 7 – Efficient Frontier
# ------------------------------------------------------------------

def plot_efficient_frontier(
    result,
    save_path: Optional[str] = None,
) -> str:
    """
    Two-panel chart:
      Left  — the Efficient Frontier scatter coloured by Sharpe ratio,
               with current, max-Sharpe and min-variance portfolios marked.
      Right — bar chart comparing current vs optimal (max-Sharpe) weights.
    """
    fig = plt.figure(figsize=(16, 7), facecolor="#0d1117")
    gs  = fig.add_gridspec(1, 2, wspace=0.35)
    ax_f = fig.add_subplot(gs[0])
    ax_b = fig.add_subplot(gs[1])

    _apply_style(ax_f)

    vols    = result.frontier_vols    * 100
    rets    = result.frontier_returns * 100
    sharpes = result.frontier_sharpes

    sc = ax_f.scatter(
        vols, rets,
        c=sharpes, cmap="RdYlGn",
        s=6, alpha=0.85, zorder=2,
        vmin=max(sharpes.min(), -0.5),
        vmax=min(sharpes.max(),  3.0),
    )
    cbar = plt.colorbar(sc, ax=ax_f, fraction=0.04, pad=0.02)
    cbar.set_label("Sharpe Ratio", color="#cccccc", fontsize=8)
    cbar.ax.yaxis.set_tick_params(color="#cccccc")
    plt.setp(plt.getp(cbar.ax.axes, "yticklabels"), color="#cccccc")

    rf    = result.risk_free_rate * 100
    msr_v = result.max_sharpe_vol    * 100
    msr_r = result.max_sharpe_return * 100
    cml_x = np.linspace(0, msr_v * 1.6, 100)
    slope = (msr_r - rf) / msr_v if msr_v > 0 else 0
    ax_f.plot(cml_x, rf + slope * cml_x, color="#aaaaaa", linewidth=1.0,
              linestyle="--", label="Capital Market Line", zorder=1)

    ax_f.scatter(result.min_var_vol * 100, result.min_var_return * 100,
                 marker="D", s=130, color="#F39C12", zorder=5,
                 label="Min Variance", edgecolors="white", linewidths=0.8)
    ax_f.scatter(msr_v, msr_r,
                 marker="*", s=280, color=ASR_GREEN, zorder=5,
                 label=f"Max Sharpe  ({result.max_sharpe_sharpe:.2f}x)",
                 edgecolors="white", linewidths=0.8)
    ax_f.scatter(result.current_vol * 100, result.current_return * 100,
                 marker="o", s=160, color="#E74C3C", zorder=5,
                 label=f"Current  ({result.current_sharpe:.2f}x)",
                 edgecolors="white", linewidths=0.8)

    ax_f.annotate("", xy=(msr_v, msr_r),
                  xytext=(result.current_vol*100, result.current_return*100),
                  arrowprops=dict(arrowstyle="->", color="white", lw=1.2,
                                  connectionstyle="arc3,rad=0.25"), zorder=6)
    ax_f.scatter(0, rf, marker="x", s=80, color="#aaaaaa", zorder=4,
                 label=f"Risk-free ({result.risk_free_rate*100:.1f}%)")

    ax_f.set_xlabel("Annualised Volatility (%)", fontsize=10)
    ax_f.set_ylabel("Annualised Return (%)",     fontsize=10)
    ax_f.set_title("Efficient Frontier\n(Markowitz Mean-Variance Optimisation)",
                   fontsize=12, fontweight="bold", color="white")
    ax_f.legend(facecolor="#1f2937", labelcolor="white", fontsize=8, loc="upper left")

    delta_sr = result.max_sharpe_sharpe - result.current_sharpe
    sign = "+" if delta_sr >= 0 else ""
    ax_f.text(0.97, 0.05, f"Sharpe improvement:\n{sign}{delta_sr:.2f}x",
              transform=ax_f.transAxes, ha="right", va="bottom",
              color=ASR_GREEN if delta_sr >= 0 else "#E74C3C",
              fontsize=9, fontweight="bold",
              bbox=dict(boxstyle="round,pad=0.4", facecolor="#1f2937",
                        edgecolor="#333333", alpha=0.9))

    _apply_style(ax_b)
    tickers = result.tickers
    x       = np.arange(len(tickers))
    width   = 0.38
    cur_w   = result.current_weights    * 100
    opt_w   = result.max_sharpe_weights * 100

    ax_b.bar(x - width/2, cur_w, width, label="Current",
             color="#E74C3C", alpha=0.85, edgecolor="#0d1117")
    ax_b.bar(x + width/2, opt_w, width, label="Max-Sharpe Optimal",
             color=ASR_GREEN, alpha=0.85, edgecolor="#0d1117")

    for i, (cw, ow) in enumerate(zip(cur_w, opt_w)):
        delta = ow - cw
        c = ASR_GREEN if delta >= 0 else "#E74C3C"
        sign2 = "+" if delta >= 0 else ""
        ax_b.text(x[i], max(cw, ow) + 0.8, f"{sign2}{delta:.1f}%",
                  ha="center", va="bottom", fontsize=7, color=c, fontweight="bold")

    ax_b.set_xticks(x)
    ax_b.set_xticklabels(tickers, rotation=30, ha="right",
                          color="#cccccc", fontsize=9)
    ax_b.set_ylabel("Weight (%)", fontsize=10)
    ax_b.set_title("Current vs Optimal Weights\n(delta = suggested rebalancing)",
                   fontsize=12, fontweight="bold", color="white")
    ax_b.legend(facecolor="#1f2937", labelcolor="white", fontsize=9)
    ax_b.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))

    fig.suptitle("Portfolio Optimisation  -  Efficient Frontier Analysis",
                 color="white", fontsize=14, fontweight="bold", y=1.02)

    return _save_or_show(fig, save_path, "efficient_frontier")


# ------------------------------------------------------------------
# 8 – Black-Litterman chart
# ------------------------------------------------------------------

def plot_black_litterman(
    result,
    save_path: Optional[str] = None,
) -> str:
    """
    Four-panel Black-Litterman summary chart:
      Top-left  — Return comparison bar chart (hist / eq / BL per ticker)
      Top-right — Return revision heatmap (view propagation via Σ)
      Bot-left  — Weight shift: current vs BL optimal
      Bot-right — Correlation heatmap of the portfolio
    """
    fig = plt.figure(figsize=(18, 11), facecolor="#0d1117")
    gs  = fig.add_gridspec(2, 2, hspace=0.42, wspace=0.32)
    ax_ret  = fig.add_subplot(gs[0, 0])
    ax_heat = fig.add_subplot(gs[0, 1])
    ax_wgt  = fig.add_subplot(gs[1, 0])
    ax_corr = fig.add_subplot(gs[1, 1])

    tickers = result.tickers
    n       = len(tickers)
    x       = np.arange(n)
    w       = 0.26

    # ── Top-left: return comparison bars ───────────────────────────
    _apply_style(ax_ret)
    ax_ret.bar(x - w,   result.mu_hist * 100,  w, label="Historical",   color="#555555",  alpha=0.9)
    ax_ret.bar(x,       result.mu_eq   * 100,  w, label="Equilibrium",  color=ASR_BLUE,   alpha=0.9)
    ax_ret.bar(x + w,   result.mu_bl   * 100,  w, label="BL Posterior", color=ASR_GREEN,  alpha=0.9)
    ax_ret.axhline(0, color="#666666", linewidth=0.7)
    ax_ret.set_xticks(x)
    ax_ret.set_xticklabels(tickers, rotation=30, ha="right", color="#cccccc", fontsize=9)
    ax_ret.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.1f}%"))
    ax_ret.set_title("Expected Excess Returns\n(Historical | Equilibrium | BL Posterior)",
                     fontsize=11, fontweight="bold", color="white")
    ax_ret.legend(facecolor="#1f2937", labelcolor="white", fontsize=8)

    # ── Top-right: return revision as annotated heatmap ─────────────
    _apply_style(ax_heat)
    revision = (result.mu_bl - result.mu_eq) * 100  # %
    im = ax_heat.imshow(
        revision.reshape(1, n),
        cmap="RdYlGn", vmin=-max(abs(revision).max(), 0.01),
        vmax=max(abs(revision).max(), 0.01), aspect="auto"
    )
    ax_heat.set_xticks(range(n))
    ax_heat.set_xticklabels(tickers, rotation=30, ha="right", color="#cccccc", fontsize=9)
    ax_heat.set_yticks([])
    for i, r in enumerate(revision):
        sign = "+" if r >= 0 else ""
        ax_heat.text(i, 0, f"{sign}{r:.2f}%",
                     ha="center", va="center", fontsize=9,
                     fontweight="bold",
                     color="black" if abs(r) < 0.5 * abs(revision).max() else "white")
    plt.colorbar(im, ax=ax_heat, fraction=0.046, pad=0.02).set_label(
        "Δ Return (%)", color="#cccccc", fontsize=8
    )
    ax_heat.set_title("Return Revision (μ_BL − μ_eq)\nView propagation via Σ",
                      fontsize=11, fontweight="bold", color="white")

    # ── Bot-left: weight comparison ─────────────────────────────────
    _apply_style(ax_wgt)
    w_cur = result.w_market         * 100
    w_bl  = result.w_bl_constrained * 100
    ax_wgt.bar(x - w/2, w_cur, w, label="Current",    color="#E74C3C", alpha=0.85, edgecolor="#0d1117")
    ax_wgt.bar(x + w/2, w_bl,  w, label="BL Optimal", color=ASR_GREEN, alpha=0.85, edgecolor="#0d1117")

    for i, (c, b) in enumerate(zip(w_cur, w_bl)):
        delta = b - c
        c_col = ASR_GREEN if delta >= 0 else "#E74C3C"
        sign  = "+" if delta >= 0 else ""
        ax_wgt.text(x[i], max(c, b) + 0.5,
                    f"{sign}{delta:.1f}%",
                    ha="center", va="bottom", fontsize=7,
                    color=c_col, fontweight="bold")

    ax_wgt.set_xticks(x)
    ax_wgt.set_xticklabels(tickers, rotation=30, ha="right", color="#cccccc", fontsize=9)
    ax_wgt.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax_wgt.set_title("Current vs BL Optimal Weights\n(long-only constrained)",
                     fontsize=11, fontweight="bold", color="white")
    ax_wgt.legend(facecolor="#1f2937", labelcolor="white", fontsize=8)

    # ── Bot-right: P matrix heatmap (which assets each view touches) ─
    _apply_style(ax_corr)
    P = result.P
    K = P.shape[0]
    if K > 0:
        im2 = ax_corr.imshow(P, cmap="RdYlGn", vmin=-1, vmax=1, aspect="auto")
        ax_corr.set_xticks(range(n))
        ax_corr.set_xticklabels(tickers, rotation=30, ha="right", color="#cccccc", fontsize=9)
        ax_corr.set_yticks(range(K))
        view_labels = [f"V{k+1}: {result.views[k].description[:18]}…"
                       if len(result.views[k].description) > 18
                       else f"V{k+1}: {result.views[k].description}"
                       for k in range(K)]
        ax_corr.set_yticklabels(view_labels, color="#cccccc", fontsize=8)
        for ki in range(K):
            for ni in range(n):
                val = P[ki, ni]
                if val != 0:
                    ax_corr.text(ni, ki, f"{val:+.0f}",
                                 ha="center", va="center",
                                 fontsize=9, fontweight="bold",
                                 color="black" if abs(val) < 0.8 else "white")
        plt.colorbar(im2, ax=ax_corr, fraction=0.046, pad=0.02)
        ax_corr.set_title("View Selection Matrix P\n(+1 = long, −1 = short)",
                          fontsize=11, fontweight="bold", color="white")
    else:
        ax_corr.text(0.5, 0.5, "No views defined", ha="center", va="center",
                     color="white", fontsize=12, transform=ax_corr.transAxes)

    fig.suptitle(
        "Black-Litterman Model  —  Equilibrium × Views = Posterior",
        color="white", fontsize=14, fontweight="bold", y=1.005,
    )
    return _save_or_show(fig, save_path, "black_litterman")
