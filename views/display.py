"""
Display View
------------
Responsible for ALL terminal output: rich tables, formatted summaries and
progress indicators.  The view never imports from controllers or accesses
yfinance directly — it only receives pre-computed data from the controller.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text
from rich import print as rprint

console = Console()


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _pnl_colour(value: float) -> str:
    if value > 0:
        return "green"
    if value < 0:
        return "red"
    return "white"


def _fmt_pct(value: float, colour: bool = True) -> str:
    sign = "+" if value > 0 else ""
    formatted = f"{sign}{value:.2f}%"
    if colour:
        c = _pnl_colour(value)
        return f"[{c}]{formatted}[/{c}]"
    return formatted


def _fmt_money(value: float, prefix: str = "$") -> str:
    return f"{prefix}{value:,.2f}"


def _fmt_change(value: float) -> str:
    c = _pnl_colour(value)
    sign = "+" if value > 0 else ""
    return f"[{c}]{sign}{value:,.2f}[/{c}]"


# ---------------------------------------------------------------------------
# Portfolio table
# ---------------------------------------------------------------------------

def show_portfolio_table(
    positions: List[dict],
    total_invested: float,
    total_value: float,
    total_pl: float,
    total_pl_pct: float,
) -> None:
    """Render the main holdings table."""
    if not positions:
        console.print(
            Panel("[yellow]Portfolio is empty.[/yellow]  "
                  "Use [bold]add[/bold] to add your first position.",
                  title="Portfolio", border_style="blue")
        )
        return

    table = Table(
        title="Portfolio Holdings",
        box=box.ROUNDED,
        border_style="blue",
        header_style="bold cyan",
        show_footer=True,
        expand=True,
    )

    table.add_column("ID",         style="dim", width=8, footer="")
    table.add_column("Ticker",     style="bold white", footer="[bold]TOTAL[/bold]")
    table.add_column("Name",       style="dim white", max_width=22)
    table.add_column("Sector",     style="cyan", max_width=18)
    table.add_column("Class",      style="magenta", footer="")
    table.add_column("Qty",        justify="right", footer="")
    table.add_column("Buy Price",  justify="right", footer="")
    table.add_column("Cur. Price", justify="right", footer="")
    table.add_column("Cost Basis", justify="right",
                     footer=f"[bold]{_fmt_money(total_invested)}[/bold]")
    table.add_column("Mkt Value",  justify="right",
                     footer=f"[bold]{_fmt_money(total_value)}[/bold]")
    table.add_column("P&L",        justify="right",
                     footer=f"[bold]{_fmt_change(total_pl)}[/bold]")
    table.add_column("P&L %",      justify="right",
                     footer=f"[bold]{_fmt_pct(total_pl_pct)}[/bold]")
    table.add_column("Weight",     justify="right", footer="100.00%")

    for row in positions:
        pl_str = _fmt_change(row["profit_loss"])
        plp_str = _fmt_pct(row["profit_loss_pct"])

        table.add_row(
            row["position_id"],
            row["ticker"],
            row.get("name", row["ticker"])[:22],
            row["sector"],
            row["asset_class"],
            f"{row['quantity']:,.4f}",
            _fmt_money(row["purchase_price"]),
            _fmt_money(row["current_price"]),
            _fmt_money(row["transaction_value"]),
            _fmt_money(row["current_value"]),
            pl_str,
            plp_str,
            f"{row['weight']:.2f}%",
        )

    console.print()
    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Weight tables
# ---------------------------------------------------------------------------

def show_weights_table(rows: List[dict], group_by: str) -> None:
    """Render an aggregated weight breakdown."""
    label_map = {
        "sector":      "Sector",
        "asset_class": "Asset Class",
        "ticker":      "Ticker",
    }
    label = label_map.get(group_by, group_by)

    table = Table(
        title=f"Weights by {label}",
        box=box.ROUNDED,
        border_style="cyan",
        header_style="bold cyan",
        show_footer=True,
        expand=False,
    )

    total_val = sum(r["current_value"] for r in rows)
    total_tv  = sum(r["transaction_value"] for r in rows)
    total_pl  = total_val - total_tv

    table.add_column(label, style="bold white",
                     footer="[bold]TOTAL[/bold]")
    table.add_column("Cost Basis", justify="right",
                     footer=f"[bold]{_fmt_money(total_tv)}[/bold]")
    table.add_column("Mkt Value",  justify="right",
                     footer=f"[bold]{_fmt_money(total_val)}[/bold]")
    table.add_column("P&L",        justify="right",
                     footer=f"[bold]{_fmt_change(total_pl)}[/bold]")
    table.add_column("P&L %",      justify="right", footer="")
    table.add_column("Weight",     justify="right", footer="[bold]100.00%[/bold]")
    table.add_column("Bar",        justify="left",  no_wrap=True)

    for row in rows:
        bar_len = max(1, int(row["weight"] / 2))
        bar = "█" * bar_len
        c = "green" if row["profit_loss"] >= 0 else "red"

        table.add_row(
            str(row.get(group_by, "—")),
            _fmt_money(row["transaction_value"]),
            _fmt_money(row["current_value"]),
            _fmt_change(row["profit_loss"]),
            _fmt_pct(row["profit_loss_pct"]),
            f"{row['weight']:.2f}%",
            f"[{c}]{bar}[/{c}]",
        )

    console.print()
    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Price tables
# ---------------------------------------------------------------------------

def show_price_table(ticker: str, info: dict, history_df) -> None:
    """Display ticker metadata and recent price history."""
    # Metadata panel
    meta_lines = []
    if info.get("name") and info["name"] != ticker:
        meta_lines.append(f"[bold]{info['name']}[/bold]")
    if info.get("market_cap"):
        mc = info["market_cap"]
        mc_str = f"${mc / 1e9:.1f}B" if mc >= 1e9 else f"${mc / 1e6:.1f}M"
        meta_lines.append(f"Market Cap: {mc_str}")
    if info.get("pe_ratio"):
        meta_lines.append(f"P/E Ratio:  {info['pe_ratio']:.1f}×")
    if info.get("52w_high"):
        meta_lines.append(
            f"52W Range:  ${info['52w_low']:.2f} – ${info['52w_high']:.2f}"
        )
    if info.get("dividend_yield"):
        meta_lines.append(f"Div. Yield: {info['dividend_yield']*100:.2f}%")
    if info.get("beta"):
        meta_lines.append(f"Beta:       {info['beta']:.2f}")

    console.print()
    console.print(
        Panel(
            "\n".join(meta_lines) if meta_lines else ticker,
            title=f"[bold cyan]{ticker}[/bold cyan] — Market Data",
            border_style="cyan",
        )
    )

    if history_df is None or history_df.empty:
        console.print("[yellow]No price history available.[/yellow]")
        return

    # Recent-history table (last 20 rows)
    col = ticker if ticker in history_df.columns else history_df.columns[0]
    recent = history_df[col].dropna().tail(20)

    table = Table(
        title=f"Recent Closing Prices — {ticker}",
        box=box.SIMPLE_HEAD,
        border_style="dim",
        header_style="bold",
    )
    table.add_column("Date", style="dim")
    table.add_column("Close", justify="right")
    table.add_column("Chg", justify="right")
    table.add_column("Chg %", justify="right")

    prev = None
    for date_idx, price in recent.items():
        date_str = str(date_idx)[:10]
        if prev is not None:
            chg = price - prev
            chg_pct = chg / prev * 100
            chg_str = _fmt_change(chg)
            chg_pct_str = _fmt_pct(chg_pct)
        else:
            chg_str = "—"
            chg_pct_str = "—"

        table.add_row(date_str, _fmt_money(price), chg_str, chg_pct_str)
        prev = price

    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Risk metrics panel
# ---------------------------------------------------------------------------

def show_risk_metrics(metrics: dict) -> None:
    """Display portfolio risk metrics in a formatted panel."""
    if not metrics:
        console.print("[yellow]Not enough data to compute risk metrics.[/yellow]")
        return

    def fmt_pct(v):
        return f"{v * 100:.2f}%" if v is not None else "N/A"

    lines = [
        f"[bold cyan]Benchmark:[/bold cyan]  {metrics.get('benchmark', 'N/A')}",
        f"[bold cyan]Risk-free rate:[/bold cyan]  {metrics.get('risk_free_rate', 0)*100:.1f}%",
        "",
        f"[bold]Annualised Return:[/bold]   [{'green' if metrics['annualised_return'] >= 0 else 'red'}]{fmt_pct(metrics['annualised_return'])}[/]",
        f"[bold]Annualised Volatility:[/bold] {fmt_pct(metrics['annualised_volatility'])}",
        f"[bold]Sharpe Ratio:[/bold]        {metrics['sharpe_ratio']:.3f}",
        f"[bold]Max Drawdown:[/bold]        [red]{fmt_pct(metrics['max_drawdown'])}[/red]",
        "",
        f"[bold]VaR (1-day, 95%):[/bold]   [red]{fmt_pct(metrics['var_95'])}[/red]",
        f"[bold]CVaR (1-day, 95%):[/bold]  [red]{fmt_pct(metrics['cvar_95'])}[/red]",
        f"[bold]Beta:[/bold]               {metrics['beta']:.3f}" if metrics.get("beta") else "[bold]Beta:[/bold]  N/A",
    ]

    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            title="Risk Metrics (trailing 1 year)",
            border_style="magenta",
        )
    )
    console.print()


# ---------------------------------------------------------------------------
# Simulation summary
# ---------------------------------------------------------------------------

def show_simulation_summary(result) -> None:
    """Display Monte Carlo summary statistics."""
    s = result.scenario_stats
    init = s["initial_value"]

    def mv(v):
        return _fmt_money(v)

    def cagr_str(v):
        c = "green" if v >= 0 else "red"
        return f"[{c}]{v*100:.2f}%[/{c}]"

    lines = [
        f"[bold]Simulation:[/bold]  {result.n_paths:,} paths × {result.n_years} years",
        f"[bold]Initial portfolio value:[/bold]  {mv(init)}",
        "",
        "[bold underline]15-Year Horizon Distribution:[/bold underline]",
        f"  5th  percentile:  {mv(s['p5'])}  (CAGR {cagr_str(s['cagr_p25'])})",
        f"  25th percentile:  {mv(s['p25'])}",
        f"  50th percentile:  {mv(s['p50'])}  (CAGR {cagr_str(s['cagr_median'])})",
        f"  75th percentile:  {mv(s['p75'])}",
        f"  95th percentile:  {mv(s['p95'])}  (CAGR {cagr_str(s['cagr_p75'])})",
        "",
        f"  Mean:             {mv(s['mean'])}",
        f"  Std Dev:          {mv(s['std'])}",
        "",
        "[bold underline]Scenario Probabilities:[/bold underline]",
        f"  Probability of loss:   [red]{s['prob_loss']*100:.1f}%[/red]",
        f"  Probability of 2×:     [green]{s['prob_double']*100:.1f}%[/green]",
        f"  Probability of 3×:     [green]{s['prob_triple']*100:.1f}%[/green]",
    ]

    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            title="Monte Carlo Simulation Results",
            border_style="green",
        )
    )
    console.print()

    # Per-ticker parameters used
    param_table = Table(
        title="Parameters Used (from 5-year history)",
        box=box.SIMPLE_HEAD,
        border_style="dim",
        header_style="bold",
    )
    param_table.add_column("Ticker", style="bold")
    param_table.add_column("Ann. Return", justify="right")
    param_table.add_column("Ann. Volatility", justify="right")
    param_table.add_column("Portfolio Weight", justify="right")

    for ticker, params in result.per_ticker_params.items():
        param_table.add_row(
            ticker,
            _fmt_pct(params["mu"] * 100, colour=True),
            f"{params['sigma'] * 100:.2f}%",
            f"{params['weight'] * 100:.2f}%",
        )

    console.print(param_table)
    console.print()


# ---------------------------------------------------------------------------
# Progress bar factory
# ---------------------------------------------------------------------------

def make_progress() -> Progress:
    """Return a styled Rich Progress bar for long-running tasks."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    )


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------

def print_success(msg: str) -> None:
    console.print(f"[bold green]✓[/bold green]  {msg}")


def print_error(msg: str) -> None:
    console.print(f"[bold red]✗[/bold red]  {msg}")


def print_info(msg: str) -> None:
    console.print(f"[bold blue]ℹ[/bold blue]  {msg}")


def print_warning(msg: str) -> None:
    console.print(f"[bold yellow]⚠[/bold yellow]  {msg}")


def show_welcome() -> None:
    banner = """
[bold cyan]╔══════════════════════════════════════════════╗
║     a.s.r. Investment Portfolio Tracker    ║
║         Powered by yfinance & Monte Carlo    ║
╚══════════════════════════════════════════════╝[/bold cyan]
Run [bold]python main.py --help[/bold] to see all commands.
"""
    console.print(banner)


# ---------------------------------------------------------------------------
# Optimisation summary
# ---------------------------------------------------------------------------

def show_optimization_summary(result) -> None:
    """Display the efficient frontier optimisation results."""

    def fp(v):
        sign = "+" if v >= 0 else ""
        c = "green" if v >= 0 else "red"
        return f"[{c}]{sign}{v*100:.2f}%[/{c}]"

    def fv(v):
        return f"{v*100:.2f}%"

    def fsr(v):
        c = "green" if v >= 1 else "yellow" if v >= 0 else "red"
        return f"[{c}]{v:.3f}x[/{c}]"

    lines = [
        "[bold underline]Current Portfolio:[/bold underline]",
        f"  Annualised Return:    {fp(result.current_return)}",
        f"  Annualised Volatility: {fv(result.current_vol)}",
        f"  Sharpe Ratio:         {fsr(result.current_sharpe)}",
        "",
        "[bold underline]Max-Sharpe Optimal Portfolio:[/bold underline]",
        f"  Annualised Return:    {fp(result.max_sharpe_return)}",
        f"  Annualised Volatility: {fv(result.max_sharpe_vol)}",
        f"  Sharpe Ratio:         {fsr(result.max_sharpe_sharpe)}",
        "",
        "[bold underline]Minimum Variance Portfolio:[/bold underline]",
        f"  Annualised Return:    {fp(result.min_var_return)}",
        f"  Annualised Volatility: {fv(result.min_var_vol)}",
        "",
        f"[bold]Sharpe improvement if rebalanced:[/bold]  "
        + (
            f"[green]+{(result.max_sharpe_sharpe - result.current_sharpe):.3f}x[/green]"
            if result.max_sharpe_sharpe >= result.current_sharpe
            else f"[red]{(result.max_sharpe_sharpe - result.current_sharpe):.3f}x[/red]"
        ),
    ]

    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            title="Efficient Frontier — Optimisation Summary",
            border_style="green",
        )
    )

    # Rebalancing table
    table = Table(
        title="Suggested Rebalancing  (Current  →  Max-Sharpe Optimal)",
        box=box.ROUNDED,
        border_style="yellow",
        header_style="bold cyan",
    )
    table.add_column("Ticker",          style="bold white")
    table.add_column("Current Weight",  justify="right")
    table.add_column("Optimal Weight",  justify="right")
    table.add_column("Delta",           justify="right")
    table.add_column("Action",          justify="left")

    for row in result.rebalancing:
        delta = row["delta"]
        c     = "green" if delta > 0.005 else "red" if delta < -0.005 else "dim"
        sign  = "+" if delta > 0 else ""
        if abs(delta) < 0.005:
            action = "[dim]Hold[/dim]"
        elif delta > 0:
            action = f"[green]Increase ↑[/green]"
        else:
            action = f"[red]Reduce  ↓[/red]"

        table.add_row(
            row["ticker"],
            f"{row['current_weight']*100:.2f}%",
            f"{row['optimal_weight']*100:.2f}%",
            f"[{c}]{sign}{delta*100:.2f}%[/{c}]",
            action,
        )

    console.print()
    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Black-Litterman display
# ---------------------------------------------------------------------------

def show_bl_summary(result) -> None:
    """Display the Black-Litterman results in structured panels."""

    def fp(v):
        """Format annualised return as coloured percent."""
        if v is None or (isinstance(v, float) and (v != v)):
            return "N/A"
        pct = v * 100
        sign = "+" if pct > 0 else ""
        txt = f"{sign}{pct:.2f}%"
        c = "green" if pct > 0 else "red"
        return f"[{c}]{txt}[/{c}]"

    console.print()
    console.print(
        Panel(
            "\n".join([
                f"[bold cyan]Model:[/bold cyan]           Black-Litterman (Baele / Goldman Sachs, 1992)",
                f"[bold cyan]Risk aversion γ:[/bold cyan]  {result.gamma:.3f}",
                f"[bold cyan]Prior weight τ:[/bold cyan]   {result.tau*100:.1f}%  (uncertainty around equilibrium)",
                f"[bold cyan]Risk-free rate:[/bold cyan]   {result.risk_free*100:.1f}%",
                f"[bold cyan]Implied MRP:[/bold cyan]      {result.implied_mrp*100:.2f}%  (γ × w'Σw)",
                f"[bold cyan]Views loaded:[/bold cyan]     {len(result.views)}",
            ]),
            title="Black-Litterman Configuration",
            border_style="cyan",
        )
    )

    # ── Views table ──────────────────────────────────────────────────
    vt = Table(title="Investor Views  (P matrix, Q vector, Idzorek Ω)",
               box=box.ROUNDED, border_style="yellow", header_style="bold cyan",
               expand=False)
    vt.add_column("#",           style="dim",        width=3)
    vt.add_column("Type",        style="bold white",  width=9)
    vt.add_column("Description", style="white",       max_width=38)
    vt.add_column("Q (view)",    justify="right",     width=10)
    vt.add_column("Confidence",  justify="right",     width=11)
    vt.add_column("Ω_kk",        justify="right",     width=10)

    for k, view in enumerate(result.views):
        omega_kk = result.Omega[k, k]
        c = "green" if view.expected_return >= 0 else "red"
        sign = "+" if view.expected_return >= 0 else ""
        vt.add_row(
            str(k + 1),
            f"[cyan]{view.type}[/cyan]",
            view.description[:38],
            f"[{c}]{sign}{view.expected_return*100:.2f}%[/{c}]",
            f"{view.confidence*100:.0f}%",
            f"{omega_kk:.5f}",
        )
    console.print()
    console.print(vt)

    # ── Return comparison table ───────────────────────────────────────
    rt = Table(
        title="Expected Excess Returns: Equilibrium vs BL Posterior",
        box=box.ROUNDED, border_style="blue", header_style="bold cyan", expand=False
    )
    rt.add_column("Ticker",     style="bold white")
    rt.add_column("Historical", justify="right")
    rt.add_column("Equilibrium μ_eq", justify="right")
    rt.add_column("BL Posterior μ_BL", justify="right")
    rt.add_column("Revision Δ", justify="right")
    rt.add_column("Driver",     style="dim")

    tickers = result.tickers
    for i, t in enumerate(tickers):
        hist_r  = result.mu_hist[i]
        eq_r    = result.mu_eq[i]
        bl_r    = result.mu_bl[i]
        delta   = bl_r - eq_r

        # Which views affect this ticker?
        view_tags = []
        for k, view in enumerate(result.views):
            if t in view.assets:
                direction = "↑" if result.P[k, i] > 0 else "↓"
                view_tags.append(f"V{k+1}{direction}")
        driver = ", ".join(view_tags) if view_tags else "correlation spill"

        rt.add_row(
            t,
            fp(hist_r),
            fp(eq_r),
            fp(bl_r),
            fp(delta),
            driver,
        )
    console.print()
    console.print(rt)

    # ── Weight rebalancing table ──────────────────────────────────────
    wt = Table(
        title="Optimal Weights: Current (Equilibrium) → BL Optimal",
        box=box.ROUNDED, border_style="green", header_style="bold cyan", expand=False
    )
    wt.add_column("Ticker",       style="bold white")
    wt.add_column("Current",      justify="right")
    wt.add_column("BL Optimal",   justify="right")
    wt.add_column("Delta",        justify="right")
    wt.add_column("Action",       justify="left")

    rb = result.rebalancing
    for _, row in rb.iterrows():
        delta = row["delta"]
        c = "green" if delta > 0.005 else "red" if delta < -0.005 else "dim"
        sign = "+" if delta > 0 else ""
        if abs(delta) < 0.005:
            action = "[dim]Hold[/dim]"
        elif delta > 0:
            action = "[green]Increase ↑[/green]"
        else:
            action = "[red]Reduce  ↓[/red]"

        wt.add_row(
            row["ticker"],
            f"{row['w_current']*100:.2f}%",
            f"{row['w_bl_constrained']*100:.2f}%",
            f"[{c}]{sign}{delta*100:.2f}%[/{c}]",
            action,
        )
    console.print()
    console.print(wt)
    console.print()


# ---------------------------------------------------------------------------
# Excel import display
# ---------------------------------------------------------------------------

def show_import_preview(result) -> None:
    """Show a full validation report before importing."""

    # ── File summary panel ────────────────────────────────────────────
    status_colour = "green" if not result.has_errors else "yellow"
    status_txt    = "Ready to import" if not result.has_errors else "Import with warnings"
    if result.n_valid == 0:
        status_colour = "red"
        status_txt    = "✗ No valid rows found"

    summary_lines = [
        f"[bold]File:[/bold]        {result.filepath}",
        f"[bold]Sheet:[/bold]       {result.sheet_name}",
        f"[bold]Total rows:[/bold]  {result.total_rows}",
        f"[bold cyan]Valid rows:[/bold cyan]  [{status_colour}]{result.n_valid}[/{status_colour}]",
        f"[bold red]Error rows:[/bold red] {result.n_errors}",
    ]
    console.print()
    console.print(
        Panel("\n".join(summary_lines),
              title=f"[{status_colour}]{status_txt}[/{status_colour}]  —  Import Preview",
              border_style=status_colour)
    )

    # ── Column mapping ────────────────────────────────────────────────
    cm_table = Table(title="Column Mapping  (your headers → tracker fields)",
                     box=box.SIMPLE_HEAD, border_style="dim",
                     header_style="bold", expand=False)
    cm_table.add_column("Your Column",    style="white")
    cm_table.add_column("Mapped To",      style="cyan")
    cm_table.add_column("Required",       justify="center")

    required_fields = {"ticker", "quantity", "purchase_price"}
    for canonical, actual in sorted(result.column_mapping.items()):
        req = "★" if canonical in required_fields else ""
        cm_table.add_row(actual, canonical, f"[yellow]{req}[/yellow]")

    # Show unmapped required fields
    for req in required_fields:
        if req not in result.column_mapping:
            cm_table.add_row("[red]NOT FOUND[/red]", req, "[red]★ MISSING[/red]")

    console.print()
    console.print(cm_table)

    # ── Valid rows preview ────────────────────────────────────────────
    if result.valid_rows:
        prev_table = Table(
            title=f"Positions to Import  ({result.n_valid} rows)",
            box=box.ROUNDED, border_style="green",
            header_style="bold cyan", expand=True
        )
        prev_table.add_column("Row",    style="dim",  width=4)
        prev_table.add_column("Ticker", style="bold white", width=8)
        prev_table.add_column("Name",   style="dim",  max_width=22)
        prev_table.add_column("Sector", style="cyan", max_width=16)
        prev_table.add_column("Class",  width=10)
        prev_table.add_column("Qty",    justify="right", width=10)
        prev_table.add_column("Price",  justify="right", width=10)
        prev_table.add_column("Date",   width=12)
        prev_table.add_column("CCY",    width=5)
        prev_table.add_column("Txn Value", justify="right", width=12)

        for r in result.valid_rows:
            txn = r.quantity * r.purchase_price
            prev_table.add_row(
                str(r.source_row),
                r.ticker,
                r.name[:22] if r.name else "—",
                r.sector[:16],
                r.asset_class,
                f"{r.quantity:,.4f}",
                f"${r.purchase_price:,.2f}",
                r.purchase_date,
                r.currency,
                f"${txn:,.2f}",
            )

        console.print()
        console.print(prev_table)

    # ── Errors ────────────────────────────────────────────────────────
    if result.errors:
        err_table = Table(
            title=f"[red]Validation Errors  ({result.n_errors})[/red]",
            box=box.ROUNDED, border_style="red",
            header_style="bold red", expand=False
        )
        err_table.add_column("Row",    style="dim",  width=4)
        err_table.add_column("Column", style="bold", width=16)
        err_table.add_column("Value",  style="dim",  width=20)
        err_table.add_column("Reason", style="white")

        for e in result.errors:
            err_table.add_row(
                str(e.row) if e.row else "—",
                e.column,
                e.value[:20] if e.value else "—",
                e.reason,
            )
        console.print()
        console.print(err_table)

    # ── Warnings ──────────────────────────────────────────────────────
    if result.warnings:
        console.print()
        for w in result.warnings:
            print_warning(w)

    console.print()


def show_import_success(n_imported: int, skipped: int = 0) -> None:
    """Confirmation message after successful import."""
    console.print(
        Panel(
            f"[bold green]{n_imported} position(s) imported successfully.[/bold green]\n"
            + (f"[dim]{skipped} row(s) skipped due to errors.[/dim]" if skipped else ""),
            title="✓  Import Complete",
            border_style="green",
        )
    )
    console.print()
