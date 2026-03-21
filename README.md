# 📈 a.s.r. Investment Portfolio Tracker

A command-line investment portfolio tracker built in Python, following the **Model-View-Controller (MVC)** design pattern.  
Track holdings, monitor live prices, analyse risk metrics, and run a 100 000-path Monte Carlo simulation over a 15-year horizon.

---

## Features

| Feature | Command |
|---|---|
| Add / remove positions | `add`, `remove` |
| Live & historical prices + charts | `prices` |
| Full portfolio table with P&L | `show` |
| Weights by ticker / sector / asset class | `weights` |
| Risk metrics (Sharpe, VaR, CVaR, Beta, Drawdown) | `metrics` |
| Benchmark comparison chart | `metrics --graph` |
| Correlation matrix heatmap | `metrics --corr` |
| Monte Carlo simulation (100 000 paths, 15 years) | `simulate` |
| Export to CSV or all charts at once | `export` |

---

## Architecture — MVC

```
portfolio_tracker/
├── main.py                          ← Entry point
├── models/
│   ├── asset.py                     ← Asset dataclass & P&L helpers
│   ├── portfolio.py                 ← Portfolio logic, yfinance, persistence
│   └── simulation.py                ← Monte Carlo simulation engine
├── views/
│   ├── display.py                   ← Rich terminal tables & panels
│   └── charts.py                    ← Matplotlib / seaborn charts
├── controllers/
│   └── portfolio_controller.py      ← Click CLI — wires Model ↔ View
├── data/
│   └── portfolio.json               ← Auto-created; persists your portfolio
└── charts/                          ← Auto-created; saved chart images
```

| Layer | Responsibility |
|---|---|
| **Model** | Stores & calculates all portfolio data; owns yfinance calls; saves to JSON |
| **View** | Renders Rich tables, panels, and Matplotlib charts — no business logic |
| **Controller** | Parses CLI arguments, calls Model, hands results to View |

---

## Setup

### Prerequisites

- Python ≥ 3.10  →  https://www.python.org/downloads/
  - **Windows**: on the installer's first screen, tick **"Add Python to PATH"**
- Internet connection (for live price data)

---

### Installation — Windows (PowerShell)

```powershell
# 1. Unzip and navigate into the project folder
cd C:\path\to\portfolio_tracker

# 2. Create a virtual environment
python -m venv .venv

# 3. Activate it  (if you get a permissions error, see note below)
.venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r requirements.txt
```

> **Permissions error?**  Run this once, then retry step 3:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

---

### Installation — macOS / Linux (Terminal)

```bash
# 1. Navigate into the project folder
cd /path/to/portfolio_tracker

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Quick Start

```bash
# Add some positions
python main.py add AAPL  -s Technology     -c Equity -q 10   -p 178.50
python main.py add MSFT  -s Technology     -c Equity -q 5    -p 380.00
python main.py add BND   -s "Fixed Income" -c Bond   -q 50   -p 72.30
python main.py add GLD   -s Commodity      -c Commodity -q 8 -p 185.00 --date 2024-01-15

# View your portfolio (fetches live prices)
python main.py show

# See weight breakdowns
python main.py weights --by sector
python main.py weights --by asset_class --graph

# Check prices with a chart
python main.py prices AAPL MSFT --period 2y --graph

# Risk analytics
python main.py metrics --graph --corr

# Run the simulation (100 000 paths × 15 years)
python main.py simulate

# Export everything
python main.py export --format charts-all
python main.py export --format csv --output my_portfolio.csv
```

---

## Command Reference

### `add` — Add a position

```
python main.py add <TICKER> [OPTIONS]

Options:
  -s, --sector TEXT          Business sector  [required]
  -c, --asset-class TEXT     Asset class (Equity|ETF|Bond|Crypto|Commodity|Real Estate|Other)  [required]
  -q, --quantity FLOAT       Number of units  [required]
  -p, --purchase-price FLOAT Price per unit   [required]
  -d, --date TEXT            Purchase date YYYY-MM-DD  [default: today]
  --currency TEXT            Currency  [default: USD]
```

### `remove` — Remove a position

```
python main.py remove <POSITION_ID> [--yes]
```

The 8-character `POSITION_ID` is shown in the ID column of `show`.

### `show` / `list` — View holdings

```
python main.py show [--refresh]
```

Displays a full table with: ticker, name, sector, asset class, quantity,
buy price, current price, cost basis, market value, absolute and relative P&L, and portfolio weight.

### `prices` — Price history

```
python main.py prices <TICKER> [TICKER ...] [OPTIONS]

Options:
  -p, --period   1d|5d|1mo|3mo|6mo|1y|2y|5y|10y|max  [default: 1y]
  --interval     1d|1wk|1mo  [default: 1d]
  -g, --graph    Save and open a price-history chart
  -s, --save     Save chart to a specific file path
```

When multiple tickers are supplied, prices are **normalised to 100** so
returns are directly comparable.

### `weights` — Portfolio allocation

```
python main.py weights [--by ticker|sector|asset_class] [-g] [-s PATH]
```

### `simulate` — Monte Carlo simulation

```
python main.py simulate [OPTIONS]

Options:
  --paths  INT   Number of paths  [default: 100000]
  --years  INT   Forecast horizon  [default: 15]
  --period TEXT  History used for calibration  [default: 5y]
  -s, --save     Save chart path
  --no-graph     Skip chart generation
```

**Methodology:**
- Per-asset drift (μ) and volatility (σ) estimated from historical daily log-returns.
- Cholesky decomposition of the historical correlation matrix used to generate correlated shocks.
- Geometric Brownian Motion for each asset; portfolio value computed from weighted asset paths.
- 100 000 paths simulated in memory-efficient batches of 5 000.
- Fan chart shows 5 / 10 / 25 / 50 / 75 / 90 / 95th percentile paths.
- Terminal histogram and CDF included.

### `metrics` — Risk analytics

```
python main.py metrics [OPTIONS]

Options:
  --benchmark TEXT  Benchmark ticker  [default: ^GSPC (S&P 500)]
  --period TEXT     Look-back period  [default: 1y]
  -g, --graph       Plot portfolio vs benchmark
  --corr            Generate correlation matrix heatmap
```

Metrics computed:
- Annualised return & volatility
- Sharpe ratio (risk-free rate assumed 4.5 %)
- Maximum drawdown
- 1-day VaR and CVaR at 95 % confidence (historical simulation)
- Beta relative to benchmark

### `export` — Data export

```
python main.py export [--format csv|charts-all] [-o OUTPUT]
```

---

## Charts Generated

| Chart | Description |
|---|---|
| `price_history.png` | Closing price lines (normalised for multi-ticker) with daily return bar |
| `allocation.png` | Side-by-side sector & asset-class donut charts |
| `holdings_bar.png` | Horizontal bar chart of position market values |
| `simulation.png` | Fan chart + terminal histogram + CDF |
| `correlation.png` | Heatmap of pairwise return correlations |
| `benchmark.png` | Cumulative return vs benchmark with over/underperformance shading |

All charts use a dark theme and are saved as high-resolution PNG (150 dpi).

---

## Data Persistence

All positions are automatically saved to `data/portfolio.json` after every `add` or `remove`.
The file is human-readable and can be backed up or committed to version control.

To use a different file (e.g. separate work and personal portfolios):

```bash
python main.py --data-file data/work_portfolio.json show
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `click` | CLI argument parsing |
| `rich` | Terminal tables, panels, progress bars |
| `yfinance` | Live & historical market data |
| `matplotlib` | All charts |
| `seaborn` | Optional enhanced aesthetics |
| `numpy` | Numerical simulation |
| `pandas` | Time-series data manipulation |
| `scipy` | Statistical helpers |

---

## Version Control

This project uses Git.  Suggested workflow:

```bash
git init
git add .
git commit -m "Initial project structure"

# After adding positions:
git add data/portfolio.json
git commit -m "chore: update portfolio holdings"
```

---

## Extending the Application

Ideas for further development:

- **Dividend reinvestment** — track dividend income separately.
- **Tax-lot accounting** — FIFO/LIFO/specific-lot realised gain calculation.
- **Efficient frontier** — plot the Markowitz frontier for the current holdings.
- **Alert system** — email / Slack notification when a position moves > X %.
- **Multi-currency support** — FX conversion to a base currency.
- **Options overlay** — add call/put positions alongside equity lots.
