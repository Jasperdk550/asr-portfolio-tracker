"""
Portfolio Controller
--------------------
Implements the Click CLI and acts as the glue between the Model layer
(Portfolio, SimulationModel) and the View layer (display, charts).

The controller:
- parses CLI arguments
- calls model methods to retrieve / mutate data
- passes results to view functions for rendering
- handles errors gracefully without exposing stack traces to the user
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

import click

from models.asset import Asset, VALID_ASSET_CLASSES
from models.portfolio import Portfolio
from models.simulation import SimulationModel, N_PATHS, N_YEARS
from models.optimizer import PortfolioOptimizer
from models.black_litterman import BlackLittermanModel, load_views, save_example_views, View
from models.excel_importer import parse_excel, create_template, ImportResult
from views import display, charts


# ---------------------------------------------------------------------------
# Shared portfolio instance (created once at CLI startup)
# ---------------------------------------------------------------------------

def _get_portfolio(ctx: click.Context) -> Portfolio:
    """Retrieve the Portfolio instance from Click context."""
    return ctx.obj["portfolio"]


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------

@click.group()
@click.option(
    "--data-file",
    default="data/portfolio.json",
    show_default=True,
    help="Path to the JSON file that stores portfolio data.",
)
@click.pass_context
def cli(ctx: click.Context, data_file: str) -> None:
    """
    \b
    ╔══════════════════════════════════════════════╗
    ║     a.s.r. Investment Portfolio Tracker    ║
    ╚══════════════════════════════════════════════╝

    Manage your investment portfolio from the command line.
    All data is persisted automatically between sessions.
    """
    ctx.ensure_object(dict)
    ctx.obj["portfolio"] = Portfolio(data_file=Path(data_file))


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

@cli.command("add")
@click.argument("ticker")
@click.option("--sector",         "-s", required=True,  help="Business sector (e.g. Technology).")
@click.option("--asset-class",    "-c", required=True,
              type=click.Choice(VALID_ASSET_CLASSES, case_sensitive=False),
              help="Asset class.")
@click.option("--quantity",       "-q", required=True,  type=float, help="Number of units purchased.")
@click.option("--purchase-price", "-p", required=True,  type=float, help="Price per unit at purchase.")
@click.option("--date",           "-d", default=str(date.today()),
              show_default=True, help="Purchase date (YYYY-MM-DD).")
@click.option("--currency",            default="USD",   show_default=True,
              help="Currency the asset trades in.")
@click.pass_context
def add_position(
    ctx, ticker, sector, asset_class, quantity, purchase_price, date, currency
):
    """Add a new purchase lot to the portfolio.

    \b
    Examples
    --------
      python main.py add AAPL -s Technology -c Equity -q 10 -p 178.50
      python main.py add BTC-USD -s Crypto -c Crypto -q 0.5 -p 42000 --date 2024-01-10
    """
    portfolio: Portfolio = _get_portfolio(ctx)

    ticker = ticker.upper()
    display.print_info(f"Fetching metadata for [bold]{ticker}[/bold]…")

    try:
        info = portfolio.get_asset_info(ticker)
        name = info.get("name", ticker)
        detected_currency = info.get("currency", currency)
    except Exception:
        name = ticker
        detected_currency = currency

    asset = Asset(
        ticker=ticker,
        sector=sector,
        asset_class=asset_class,
        quantity=quantity,
        purchase_price=purchase_price,
        purchase_date=date,
        name=name,
        currency=detected_currency,
    )

    portfolio.add_position(asset)
    display.print_success(
        f"Added [bold]{ticker}[/bold] — {quantity:,.4f} units at "
        f"${purchase_price:,.2f}  "
        f"(position ID: [cyan]{asset.position_id}[/cyan])"
    )


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------

@cli.command("remove")
@click.argument("position_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def remove_position(ctx, position_id: str, yes: bool):
    """Remove a position by its 8-character ID (shown in the portfolio table).

    \b
    Example
    -------
      python main.py remove a1b2c3d4
    """
    portfolio: Portfolio = _get_portfolio(ctx)

    # Find position first so we can show a description
    match = next(
        (p for p in portfolio.get_positions() if p.position_id == position_id), None
    )
    if match is None:
        display.print_error(
            f"Position [bold]{position_id}[/bold] not found. "
            "Run [bold]show[/bold] to see valid IDs."
        )
        sys.exit(1)

    if not yes:
        click.confirm(
            f"Remove {match.quantity:,.4f}× {match.ticker} "
            f"(bought at ${match.purchase_price:,.2f} on {match.purchase_date})?",
            abort=True,
        )

    portfolio.remove_position(position_id)
    display.print_success(f"Position [bold]{position_id}[/bold] removed.")


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

@cli.command("show")
@click.option("--refresh", "-r", is_flag=True, help="Force refresh of live prices.")
@click.pass_context
def show_portfolio(ctx, refresh: bool):
    """Display all holdings with live prices and P&L.

    \b
    Example
    -------
      python main.py show
      python main.py show --refresh
    """
    portfolio: Portfolio = _get_portfolio(ctx)

    if portfolio.is_empty():
        display.print_warning(
            "Portfolio is empty. Use [bold]add[/bold] to add positions."
        )
        return

    display.print_info("Fetching live prices…")
    try:
        portfolio.fetch_current_prices()
    except Exception as exc:
        display.print_warning(f"Could not fetch prices: {exc}")

    positions = portfolio.position_weights()
    display.show_portfolio_table(
        positions=positions,
        total_invested=portfolio.total_invested(),
        total_value=portfolio.total_current_value(),
        total_pl=portfolio.total_profit_loss(),
        total_pl_pct=portfolio.total_profit_loss_pct(),
    )


# ---------------------------------------------------------------------------
# prices
# ---------------------------------------------------------------------------

@cli.command("prices")
@click.argument("tickers", nargs=-1, required=True)
@click.option(
    "--period", "-p",
    default="1y",
    show_default=True,
    type=click.Choice(["1d","5d","1mo","3mo","6mo","1y","2y","5y","10y","max"],
                      case_sensitive=False),
    help="Historical period to display.",
)
@click.option("--graph",  "-g", is_flag=True, help="Open an interactive price chart.")
@click.option("--save",   "-s", default=None, help="Save chart to this file path.")
@click.option("--interval",     default="1d",
              type=click.Choice(["1d","1wk","1mo"], case_sensitive=False),
              help="Data granularity.", show_default=True)
@click.pass_context
def show_prices(ctx, tickers, period, graph, save, interval):
    """Show current and historical prices for one or more tickers.

    \b
    Examples
    --------
      python main.py prices AAPL
      python main.py prices AAPL MSFT GOOGL --period 2y --graph
      python main.py prices AAPL --period 5y --save charts/aapl.png
    """
    portfolio: Portfolio = _get_portfolio(ctx)
    tickers = [t.upper() for t in tickers]

    display.print_info(f"Fetching data for: [bold]{', '.join(tickers)}[/bold]…")

    # Live price + metadata for each ticker
    for ticker in tickers:
        try:
            info = portfolio.get_asset_info(ticker)
            hist = portfolio.fetch_history([ticker], period=period,
                                           interval=interval)
            display.show_price_table(ticker, info, hist)
        except Exception as exc:
            display.print_error(f"Failed to fetch {ticker}: {exc}")

    if graph or save:
        hist_all = portfolio.fetch_history(list(tickers), period=period,
                                            interval=interval)
        save_path = save or _default_chart_path("prices")
        chart_path = charts.plot_price_history(
            hist_all, list(tickers), period=period, save_path=save_path
        )
        if chart_path:
            display.print_success(f"Chart saved to [bold]{chart_path}[/bold]")
            _open_file(chart_path)


# ---------------------------------------------------------------------------
# weights
# ---------------------------------------------------------------------------

@cli.command("weights")
@click.option(
    "--by", "-b",
    default="ticker",
    type=click.Choice(["ticker", "sector", "asset_class"], case_sensitive=False),
    show_default=True,
    help="Dimension to group by.",
)
@click.option("--graph",  "-g", is_flag=True, help="Show allocation donut chart.")
@click.option("--save",   "-s", default=None, help="Save chart to this file path.")
@click.pass_context
def show_weights(ctx, by, graph, save):
    """Show portfolio weights broken down by ticker, sector, or asset class.

    \b
    Examples
    --------
      python main.py weights
      python main.py weights --by sector
      python main.py weights --by asset_class --graph
    """
    portfolio: Portfolio = _get_portfolio(ctx)

    if portfolio.is_empty():
        display.print_warning("Portfolio is empty.")
        return

    display.print_info("Fetching live prices…")
    try:
        portfolio.fetch_current_prices()
    except Exception:
        pass

    rows = portfolio.weights_by_group(group_by=by)
    display.show_weights_table(rows, group_by=by)

    if graph or save:
        sector_rows = portfolio.weights_by_group("sector")
        class_rows  = portfolio.weights_by_group("asset_class")
        save_path   = save or _default_chart_path("allocation")
        chart_path  = charts.plot_allocation(sector_rows, class_rows,
                                              save_path=save_path)
        display.print_success(f"Chart saved to [bold]{chart_path}[/bold]")
        _open_file(chart_path)


# ---------------------------------------------------------------------------
# simulate
# ---------------------------------------------------------------------------

@cli.command("simulate")
@click.option("--paths",     default=N_PATHS, show_default=True,
              help="Number of simulated paths (default 100 000).")
@click.option("--years",     default=N_YEARS,  show_default=True,
              help="Forecast horizon in years.")
@click.option("--period",    default="5y",    show_default=True,
              type=click.Choice(["1y","2y","3y","5y","10y","max"],
                                case_sensitive=False),
              help="Historical period used to calibrate parameters.")
@click.option("--save",      default=None,    help="Save chart to this file path.")
@click.option("--no-graph",  is_flag=True,    help="Skip chart generation.")
@click.pass_context
def simulate(ctx, paths, years, period, save, no_graph):
    """Run a Monte Carlo simulation over the portfolio.

    Uses Geometric Brownian Motion with correlated asset returns,
    calibrated to historical data.  Generates a fan chart showing the
    5 / 25 / 50 / 75 / 95th percentile portfolio value paths.

    \b
    Examples
    --------
      python main.py simulate
      python main.py simulate --paths 50000 --years 10
      python main.py simulate --save charts/sim.png
    """
    portfolio: Portfolio = _get_portfolio(ctx)

    if portfolio.is_empty():
        display.print_warning("Portfolio is empty — nothing to simulate.")
        return

    display.print_info("Fetching current prices…")
    try:
        portfolio.fetch_current_prices()
    except Exception:
        pass

    sim_model = SimulationModel(portfolio)

    progress = display.make_progress()
    task = None

    def callback(pct: int, msg: str = ""):
        nonlocal task
        if task is None:
            task = progress.add_task(msg, total=100)
        progress.update(task, completed=pct, description=msg)

    display.print_info(
        f"Running [bold]{paths:,}[/bold] paths × [bold]{years}[/bold] years…"
    )
    with progress:
        try:
            result = sim_model.run(
                n_paths=paths,
                n_years=years,
                historical_period=period,
                progress_callback=callback,
            )
        except ValueError as exc:
            display.print_error(str(exc))
            return
        except Exception as exc:
            display.print_error(f"Simulation failed: {exc}")
            if os.environ.get("DEBUG"):
                traceback.print_exc()
            return

    display.show_simulation_summary(result)

    if not no_graph:
        save_path = save or _default_chart_path("simulation")
        chart_path = charts.plot_simulation(result, save_path=save_path)
        display.print_success(f"Chart saved to [bold]{chart_path}[/bold]")
        _open_file(chart_path)


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

@cli.command("metrics")
@click.option("--benchmark", default="^GSPC", show_default=True,
              help="Benchmark ticker (default: S&P 500).")
@click.option("--period",    default="1y",    show_default=True,
              type=click.Choice(["6mo","1y","2y","3y","5y"], case_sensitive=False),
              help="Look-back period for metric calculation.")
@click.option("--graph",     "-g", is_flag=True, help="Plot vs benchmark.")
@click.option("--save",      default=None, help="Save chart to this file path.")
@click.option("--corr",      is_flag=True, help="Also show correlation matrix heatmap.")
@click.pass_context
def show_metrics(ctx, benchmark, period, graph, save, corr):
    """Compute and display risk metrics for the portfolio.

    \b
    Metrics include: annualised return, volatility, Sharpe ratio,
    maximum drawdown, VaR, CVaR, and beta relative to the benchmark.

    Examples
    --------
      python main.py metrics
      python main.py metrics --benchmark ^FTSE --period 2y
      python main.py metrics --graph --corr
    """
    portfolio: Portfolio = _get_portfolio(ctx)

    if portfolio.is_empty():
        display.print_warning("Portfolio is empty.")
        return

    display.print_info("Computing risk metrics…")
    try:
        metrics = portfolio.compute_risk_metrics(
            benchmark_ticker=benchmark, period=period
        )
    except Exception as exc:
        display.print_error(f"Failed to compute metrics: {exc}")
        return

    display.show_risk_metrics(metrics)

    if graph or save:
        try:
            tickers = portfolio.get_tickers()
            port_rets = portfolio.portfolio_daily_returns(period=period)
            bench_hist = portfolio.fetch_history([benchmark], period=period)
            if not bench_hist.empty and benchmark in bench_hist.columns:
                bench_rets = bench_hist[benchmark].pct_change().dropna()
                save_path  = save or _default_chart_path("benchmark")
                chart_path = charts.plot_performance_vs_benchmark(
                    port_rets, bench_rets,
                    benchmark_label=benchmark,
                    save_path=save_path,
                )
                display.print_success(
                    f"Benchmark chart saved to [bold]{chart_path}[/bold]"
                )
                _open_file(chart_path)
        except Exception as exc:
            display.print_warning(f"Could not generate benchmark chart: {exc}")

    if corr:
        try:
            corr_matrix = portfolio.correlation_matrix(period=period)
            if corr_matrix is not None:
                corr_path = charts.plot_correlation_matrix(
                    corr_matrix,
                    save_path=_default_chart_path("correlation"),
                )
                display.print_success(
                    f"Correlation chart saved to [bold]{corr_path}[/bold]"
                )
                _open_file(corr_path)
            else:
                display.print_warning(
                    "Need at least 2 assets to compute correlations."
                )
        except Exception as exc:
            display.print_warning(f"Could not generate correlation chart: {exc}")


# ---------------------------------------------------------------------------
# optimize
# ---------------------------------------------------------------------------

@cli.command("optimize")
@click.option("--period", default="3y", show_default=True,
              type=click.Choice(["1y","2y","3y","5y"], case_sensitive=False),
              help="Historical period for parameter estimation.")
@click.option("--save",   default=None, help="Save chart to this file path.")
@click.option("--no-graph", is_flag=True, help="Skip chart generation.")
@click.pass_context
def optimize_portfolio(ctx, period, save, no_graph):
    """Compute the Efficient Frontier and find the optimal portfolio weights.

    Uses Markowitz Mean-Variance Optimisation to identify:

    
    - The Maximum Sharpe Ratio portfolio (best risk-adjusted return).
    - The Minimum Variance portfolio (lowest possible risk).
    - A rebalancing table showing how to shift from current to optimal.

    The chart plots the full frontier coloured by Sharpe ratio, marks
    your current portfolio, and draws the Capital Market Line.

    
    Examples
    --------
      python main.py optimize
      python main.py optimize --period 5y --save charts/frontier.png
    """
    portfolio: Portfolio = _get_portfolio(ctx)

    if portfolio.is_empty():
        display.print_warning("Portfolio is empty.")
        return

    tickers = portfolio.get_tickers()
    if len(tickers) < 2:
        display.print_warning(
            "Need at least 2 different assets to compute the Efficient Frontier."
        )
        return

    display.print_info("Fetching prices and historical data…")
    try:
        portfolio.fetch_current_prices()
    except Exception:
        pass

    display.print_info(
        f"Running optimisation over [bold]{len(tickers)}[/bold] assets "        f"([bold]{period}[/bold] history)…"
    )

    optimizer = PortfolioOptimizer(portfolio, period=period)
    try:
        result = optimizer.run()
    except ValueError as exc:
        display.print_error(str(exc))
        return
    except Exception as exc:
        display.print_error(f"Optimisation failed: {exc}")
        if os.environ.get("DEBUG"):
            traceback.print_exc()
        return

    display.show_optimization_summary(result)

    if not no_graph:
        save_path  = save or _default_chart_path("efficient_frontier")
        chart_path = charts.plot_efficient_frontier(result, save_path=save_path)
        display.print_success(f"Chart saved to [bold]{chart_path}[/bold]")
        _open_file(chart_path)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

@cli.command("export")
@click.option("--format", "fmt",
              type=click.Choice(["csv", "charts-all"], case_sensitive=False),
              default="csv", show_default=True,
              help="Export format.")
@click.option("--output", "-o", default=None,
              help="Output file path (CSV) or directory (charts-all).")
@click.pass_context
def export_data(ctx, fmt, output):
    """Export portfolio data to CSV or generate all charts at once.

    \b
    Examples
    --------
      python main.py export
      python main.py export --format csv --output my_portfolio.csv
      python main.py export --format charts-all --output charts/
    """
    portfolio: Portfolio = _get_portfolio(ctx)

    if portfolio.is_empty():
        display.print_warning("Portfolio is empty — nothing to export.")
        return

    display.print_info("Fetching live prices…")
    try:
        portfolio.fetch_current_prices()
    except Exception:
        pass

    if fmt == "csv":
        filepath = output or f"portfolio_export_{_ts()}.csv"
        portfolio.export_to_csv(filepath)
        display.print_success(f"Portfolio exported to [bold]{filepath}[/bold]")

    elif fmt == "charts-all":
        out_dir = output or f"charts_{_ts()}"
        os.makedirs(out_dir, exist_ok=True)

        # Price history for all holdings
        tickers = portfolio.get_tickers()
        if tickers:
            hist = portfolio.fetch_history(tickers, period="1y")
            p = charts.plot_price_history(
                hist, tickers,
                save_path=os.path.join(out_dir, "price_history.png")
            )
            display.print_success(f"Price history chart → {p}")

        # Allocation donuts
        s_rows = portfolio.weights_by_group("sector")
        c_rows = portfolio.weights_by_group("asset_class")
        p = charts.plot_allocation(
            s_rows, c_rows,
            save_path=os.path.join(out_dir, "allocation.png")
        )
        display.print_success(f"Allocation chart → {p}")

        # Holdings bar
        pos = portfolio.position_weights()
        p = charts.plot_portfolio_bar(
            pos, save_path=os.path.join(out_dir, "holdings_bar.png")
        )
        display.print_success(f"Holdings bar chart → {p}")

        # Correlation matrix
        corr = portfolio.correlation_matrix()
        if corr is not None:
            p = charts.plot_correlation_matrix(
                corr, save_path=os.path.join(out_dir, "correlation.png")
            )
            display.print_success(f"Correlation chart → {p}")

        display.print_success(f"All charts saved to [bold]{out_dir}/[/bold]")


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# import-excel  —  import portfolio from Excel / CSV
# ---------------------------------------------------------------------------

@cli.command("import-excel")
@click.option("--file",   "-f", default=None,
              help="Path to .xlsx, .xls or .csv file to import.")
@click.option("--sheet",  "-s", default=None,
              help="Sheet name to read (default: first sheet).")
@click.option("--create-template", is_flag=True, default=False,
              help="Generate a ready-to-fill Excel template and exit.")
@click.option("--template-path", default="portfolio_template.xlsx",
              show_default=True,
              help="Output path for the generated template.")
@click.option("--yes", "-y", is_flag=True, default=False,
              help="Skip the confirmation prompt and import immediately.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Validate and preview only — do not write to portfolio.")
@click.option("--data-file", default="data/portfolio.json",
              show_default=True, help="Portfolio data file.")
@click.pass_context
def import_excel(ctx, file, sheet, create_template, template_path,
                 yes, dry_run, data_file):
    '''Import an existing portfolio from an Excel (.xlsx) or CSV file.

    
    QUICK START
      1. Generate a template:
           python main.py import-excel --create-template
      2. Fill in your positions and save the file.
      3. Import:
           python main.py import-excel --file portfolio_template.xlsx

    
    FLEXIBLE COLUMN NAMES
      Your spreadsheet does not need to match exactly — the importer
      auto-recognises many common header variants:
        Ticker / Symbol / Stock / ISIN
        Quantity / Qty / Shares / Units / Holdings
        Purchase Price / Avg Price / Cost / Entry Price
        Sector / Industry / Category
        Asset Class / Type / Class
        Purchase Date / Buy Date / Trade Date
        Currency / CCY

    
    EXAMPLES
      python main.py import-excel --file my_portfolio.xlsx
      python main.py import-excel --file portfolio.xlsx --sheet Holdings
      python main.py import-excel --file data.xlsx --dry-run
      python main.py import-excel --file data.csv --yes
    '''
    # Generate template and exit
    if create_template:
        path = create_template_file(template_path)
        display.print_success(
            f"Template created: [bold]{path}[/bold]  "
            f"Fill in your positions and run:  "
            f"[cyan]python main.py import-excel --file {path}[/cyan]"
        )
        return

    if file is None:
        display.print_error(
            "No file specified. "
            "Use [bold]--file PATH[/bold] or generate a template with "
            "[bold]--create-template[/bold]."
        )
        return

    if not os.path.exists(file):
        display.print_error(f"File not found: [bold]{file}[/bold]")
        return

    display.print_info(f"Reading [bold]{file}[/bold]...")
    result = parse_excel(file, sheet_name=sheet)
    display.show_import_preview(result)

    if result.n_valid == 0:
        display.print_error("No valid rows to import. Fix the errors above and try again.")
        return

    if dry_run:
        display.print_info("Dry-run complete. No data was written.")
        return

    # Confirmation
    if not yes:
        click.confirm(
            f"Import {result.n_valid} position(s) into the portfolio?",
            abort=True
        )

    portfolio: Portfolio = _get_portfolio(ctx)

    # Fetch names from yfinance for rows where name is blank
    display.print_info("Fetching metadata for new tickers...")
    unique_tickers = list({r.ticker for r in result.valid_rows})
    name_cache: dict = {}
    for ticker in unique_tickers:
        try:
            info = portfolio.get_asset_info(ticker)
            name_cache[ticker] = info.get("name", ticker)
        except Exception:
            name_cache[ticker] = ticker

    # Add positions
    n_imported = 0
    for row in result.valid_rows:
        asset = Asset(
            ticker         = row.ticker,
            sector         = row.sector,
            asset_class    = row.asset_class,
            quantity       = row.quantity,
            purchase_price = row.purchase_price,
            purchase_date  = row.purchase_date,
            name           = row.name or name_cache.get(row.ticker, row.ticker),
            currency       = row.currency,
        )
        portfolio.add_position(asset)
        n_imported += 1

    display.show_import_success(n_imported, skipped=result.n_errors)


# Alias to avoid shadowing the imported function name
create_template_file = create_template

# ---------------------------------------------------------------------------
# bl  —  Black-Litterman model
# ---------------------------------------------------------------------------

@cli.command("bl")
@click.option("--views-file", "-v", default=None,
              help="Path to JSON file containing investor views.")
@click.option("--init-views", is_flag=True, default=False,
              help="Generate a template views file and exit.")
@click.option("--tau",   default=0.05, show_default=True,
              type=float, help="Prior uncertainty τ (5-15%% recommended).")
@click.option("--gamma", default=None, type=float,
              help="Risk-aversion γ. Default: auto-calibrate from portfolio.")
@click.option("--period", default="3y", show_default=True,
              type=click.Choice(["1y","2y","3y","5y"], case_sensitive=False),
              help="Historical period for covariance estimation.")
@click.option("--save", default=None, help="Save chart to this file path.")
@click.option("--no-graph", is_flag=True, help="Skip chart generation.")
@click.option("--data-file", default="data/portfolio.json",
              show_default=True, help="Portfolio data file.")
@click.pass_context
def black_litterman(ctx, views_file, init_views, tau, gamma, period, save,
                    no_graph, data_file):
    '''Run the Black-Litterman model (Black & Litterman, 1992).

    
    The BL model solves the core failure of Markowitz: extreme, unstable
    weights.  It starts from equilibrium returns implied by your current
    portfolio weights (μ_eq = γΣw), then blends in your views via Bayes:

        μ_BL = [(τΣ)⁻¹ + P' Ω⁻¹ P]⁻¹ × [(τΣ)⁻¹ μ_eq + P' Ω⁻¹ Q]

    View uncertainty Ω is calibrated via Idzorek' s method so you only
    need to supply an intuitive 0-100% confidence level per view.

    
    Steps:
      1. Generate a template views file:   bl --init-views
      2. Edit views_bl.json with your views.
      3. Run the model:                    bl --views-file views_bl.json

    
    Examples
    --------
      python main.py bl --init-views
      python main.py bl --views-file views_bl.json
      python main.py bl --views-file views_bl.json --tau 0.10 --period 5y
    '''
    portfolio: Portfolio = _get_portfolio(ctx)

    if portfolio.is_empty():
        display.print_warning("Portfolio is empty.")
        return

    display.print_info("Fetching current prices...")
    try:
        portfolio.fetch_current_prices()
    except Exception:
        pass

    # --init-views: write template file and exit
    if init_views:
        out = views_file or "views_bl.json"
        save_example_views(portfolio.get_tickers(), out)
        display.print_success(
            f"Template views file created: [bold]{out}[/bold]  "
            f"Edit it, then run:  [cyan]python main.py bl --views-file {out}[/cyan]"
        )
        return

    # Load views
    if views_file is None:
        display.print_error(
            "No views file supplied. Run with [bold]--init-views[/bold] to "
            "generate a template, or pass [bold]--views-file PATH[/bold]."
        )
        return

    if not os.path.exists(views_file):
        display.print_error(f"Views file not found: {views_file}")
        return

    try:
        views = load_views(views_file)
    except Exception as exc:
        display.print_error(f"Could not parse views file: {exc}")
        return

    display.print_info(
        f"Running BL with [bold]{len(views)}[/bold] views ",
    )

    bl_model = BlackLittermanModel(
        portfolio, tau=tau, gamma=gamma, historical_period=period
    )
    try:
        result = bl_model.run(views)
    except ValueError as exc:
        display.print_error(str(exc))
        return
    except Exception as exc:
        display.print_error(f"BL computation failed: {exc}")
        if os.environ.get("DEBUG"):
            import traceback; traceback.print_exc()
        return

    display.show_bl_summary(result)

    if not no_graph:
        save_path  = save or _default_chart_path("black_litterman")
        chart_path = charts.plot_black_litterman(result, save_path=save_path)
        display.print_success(f"Chart saved to [bold]{chart_path}[/bold]")
        _open_file(chart_path)

# list  (alias for show, friendlier for newcomers)
# ---------------------------------------------------------------------------

@cli.command("list")
@click.pass_context
def list_positions(ctx):
    """Alias for [bold]show[/bold] — display all current holdings."""
    ctx.invoke(show_portfolio)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_chart_path(name: str) -> str:
    return os.path.join("charts", f"{name}_{_ts()}.png")


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _open_file(path: str) -> None:
    """Try to open the file with the OS default application (best-effort)."""
    import subprocess, platform
    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        elif platform.system() == "Linux":
            subprocess.Popen(["xdg-open", path])
        elif platform.system() == "Windows":
            os.startfile(path)
    except Exception:
        pass
