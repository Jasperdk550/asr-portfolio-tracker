# 📈 a.s.r. Investment Portfolio Tracker

A professional command-line investment portfolio tracker built in Python,
following the **Model-View-Controller (MVC)** design pattern.

Track holdings, monitor live prices, analyse risk metrics, run a 100 000-path
Monte Carlo simulation, optimise with Markowitz and Black-Litterman, and import
existing portfolios directly from Excel.

---

## Features

| Feature | Command |
|---|---|
| Import existing portfolio from Excel / CSV | `import-excel` |
| Add / remove individual positions | `add`, `remove` |
| Full portfolio table with live P&L | `show` |
| Live & historical prices + charts | `prices` |
| Weights by ticker / sector / asset class | `weights` |
| Risk metrics (Sharpe, VaR, CVaR, Beta, Drawdown) | `metrics` |
| Benchmark comparison chart | `metrics --graph` |
| Correlation matrix heatmap | `metrics --corr` |
| Monte Carlo simulation (100 000 paths, 15 years) | `simulate` |
| Markowitz Efficient Frontier + rebalancing | `optimize` |
| Black-Litterman model with investor views | `bl` |
| Export to CSV or generate all charts | `export` |

---

## Architecture — MVC

```
portfolio_tracker/
├── main.py                              ← Entry point
├── requirements.txt                     ← All dependencies
├── models/
│   ├── asset.py                         ← Asset dataclass & lot-level P&L
│   ├── portfolio.py                     ← Core: prices, weights, risk metrics
│   ├── simulation.py                    ← Monte Carlo engine (100k paths, GBM)
│   ├── optimizer.py                     ← Markowitz Efficient Frontier
│   ├── black_litterman.py               ← Black-Litterman model (1992)
│   └── excel_importer.py               ← Excel / CSV import with fuzzy matching
├── views/
│   ├── display.py                       ← Rich terminal tables & panels
│   └── charts.py                        ← Matplotlib charts (8 chart types)
├── controllers/
│   └── portfolio_controller.py          ← Click CLI — wires Model ↔ View
├── data/
│   └── portfolio.json                   ← Auto-created; persists your portfolio
└── charts/                              ← Auto-created; saved chart images
```

| Layer | Responsibility |
|---|---|
| **Model** | All data, calculations and persistence — zero UI code |
| **View** | All terminal output and chart rendering — zero business logic |
| **Controller** | CLI parsing; calls Model methods; passes results to View |

---

## Setup

### Prerequisites

- **Python >= 3.10** → https://www.python.org/downloads/
- **Windows**: tick "Add Python to PATH" on the installer's first screen.

### Installation — Windows (PowerShell)

```powershell
cd C:\path\to\portfolio_tracker
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If you get a permissions error on activation:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Installation — macOS / Linux

```bash
cd /path/to/portfolio_tracker
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Verify

```powershell
python main.py --help
```

---

## Quick Start

### Option A — Import an existing portfolio from Excel

```powershell
python main.py import-excel --create-template
# Edit portfolio_template.xlsx, then:
python main.py import-excel --file portfolio_template.xlsx
python main.py show
```

### Option B — Enter positions manually

```powershell
python main.py add AAPL  -s Technology     -c Equity    -q 10  -p 178.50
python main.py add MSFT  -s Technology     -c Equity    -q 5   -p 380.00
python main.py add BND   -s "Fixed Income" -c Bond      -q 50  -p 72.30
python main.py add GLD   -s Commodity      -c Commodity -q 8   -p 185.00
python main.py show
```

---

## Command Reference

### `import-excel` — Import from Excel or CSV

```powershell
# Generate a professional template
python main.py import-excel --create-template

# Validate without writing anything
python main.py import-excel --file my_portfolio.xlsx --dry-run

# Import (shows preview, asks confirmation)
python main.py import-excel --file my_portfolio.xlsx

# Import from a specific sheet
python main.py import-excel --file workbook.xlsx --sheet Holdings

# Import a CSV file
python main.py import-excel --file broker_export.csv --yes
```

The importer auto-recognises 40+ column name variants:

| Your column header | Mapped to |
|---|---|
| Ticker / Symbol / Stock / ISIN | `ticker` |
| Quantity / Qty / Shares / Units | `quantity` |
| Purchase Price / Avg Price / Cost | `purchase_price` |
| Sector / Industry / Category | `sector` |
| Asset Class / Type / Class | `asset_class` |
| Purchase Date / Buy Date / Trade Date | `purchase_date` |
| Currency / CCY | `currency` |

Always shows a full validation preview and error report before writing.

---

### `add` — Add a position manually

```powershell
python main.py add AAPL  -s Technology -c Equity    -q 10  -p 178.50
python main.py add BTC-USD -s Crypto   -c Crypto    -q 0.5 -p 42000 --date 2024-01-10
```

Asset classes: `Equity` | `ETF` | `Bond` | `Crypto` | `Commodity` | `Real Estate` | `Other`

### `remove` — Remove a position

```powershell
python main.py remove <8-CHAR-ID>         # ID shown in the show table
python main.py remove a1b2c3d4 --yes      # skip confirmation
```

### `show` — View holdings with live prices

```powershell
python main.py show
```

### `prices` — Historical prices and charts

```powershell
python main.py prices AAPL
python main.py prices AAPL MSFT --period 2y --graph
```

### `weights` — Portfolio allocation breakdown

```powershell
python main.py weights --by sector
python main.py weights --by asset_class --graph
```

### `simulate` — Monte Carlo simulation

```powershell
python main.py simulate
python main.py simulate --paths 50000 --years 10
```

Geometric Brownian Motion with correlated shocks (Cholesky of Σ).
Output: fan chart, terminal histogram, CDF, and scenario probabilities.

### `metrics` — Risk analytics

```powershell
python main.py metrics
python main.py metrics --benchmark ^FTSE --period 2y --graph --corr
```

Sharpe ratio, Max Drawdown, VaR, CVaR (95%), Beta vs benchmark.

### `optimize` — Markowitz Efficient Frontier

```powershell
python main.py optimize
python main.py optimize --period 5y
```

Finds the Maximum Sharpe Ratio and Minimum Variance portfolios.
Plots the full frontier with your current portfolio marked, and
produces a concrete rebalancing table.

### `bl` — Black-Litterman model

```powershell
# Step 1: generate a views template
python main.py bl --init-views

# Step 2: edit views_bl.json with your views, then:
python main.py bl --views-file views_bl.json
python main.py bl --views-file views_bl.json --tau 0.10 --period 5y
```

Implements the full Black & Litterman (1992) model:
- Reverse-optimised equilibrium: `mu_eq = gamma * Sigma * w`
- Idzorek confidence method for Omega (intuitive 0-100% confidence)
- Bayesian posterior: `mu_BL = [(tau*Sigma)^-1 + P'*Omega^-1*P]^-1 * [...]`
- Long-only constrained optimal weights

Views file (`views_bl.json`) format:
```json
{
  "views": [
    {
      "description": "AAPL will outperform MSFT by 2%",
      "type": "relative",
      "assets": ["AAPL", "MSFT"],
      "weights": [1, -1],
      "expected_return": 0.02,
      "confidence": 0.65
    }
  ]
}
```

### `export` — Export data

```powershell
python main.py export
python main.py export --format csv --output my_portfolio.csv
python main.py export --format charts-all --output charts/
```

---

## Charts

| Chart | File | Description |
|---|---|---|
| Price history | `price_history.png` | Line chart, normalised for multi-ticker comparison |
| Allocation | `allocation.png` | Sector & asset-class donut charts |
| Holdings | `holdings_bar.png` | Market value horizontal bars |
| Simulation | `simulation.png` | Fan chart + histogram + CDF |
| Correlation | `correlation.png` | Return correlation heatmap |
| Benchmark | `benchmark.png` | Portfolio vs index cumulative return |
| Efficient Frontier | `efficient_frontier.png` | Frontier scatter + weight bars |
| Black-Litterman | `black_litterman.png` | Return revisions + weight shifts + P matrix |

---

## Data Persistence

Positions are saved to `data/portfolio.json` after every write operation.
The file is plain JSON — human-readable and safe to back up or commit.

The Python and R versions share the same file format and can be used
interchangeably on the same `portfolio.json`.

Multiple portfolios:
```powershell
python main.py --data-file data/work.json show
python main.py --data-file data/personal.json simulate
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `click` | CLI argument parsing |
| `rich` | Terminal tables, panels, progress bars |
| `yfinance` | Live & historical market data |
| `matplotlib` | All charts |
| `numpy` | Simulation and linear algebra |
| `pandas` | Time-series data manipulation |
| `scipy` | Optimisation (Markowitz, Black-Litterman) |
| `openpyxl` | Excel template generation and reading |
| `xlrd` | Legacy .xls file support |

---

## Version Control

```bash
git init
git add .
git commit -m "feat: initial MVC project structure"
git remote add origin https://github.com/YOUR-USERNAME/asr-portfolio-tracker.git
git branch -M main
git push -u origin main
```

---

## Design Decisions

**Why MVC?** Clean separation means the model never prints, the view never
calculates, and the controller never accesses data directly. Adding
Black-Litterman required only a new model file, one display function, and
one CLI command — nothing else changed.

**Why Black-Litterman over plain Markowitz?** Markowitz produces weights like
+208% Canada, -352% Italy when fed historical returns — useless in practice.
Black-Litterman anchors on equilibrium so assets with no view stay near market
weights. Deviations are proportional to conviction. For an insurance company
like a.s.r., this is the difference between a presentable portfolio and one
that would never pass an investment committee.

**Why 100 000 simulation paths?** The 5th-percentile path (worst-case tail
risk) requires far more paths to converge than the median. At 10 000 paths
the tail is still noisy; at 100 000 it is stable to within 0.1% across runs.
