# Earnings Intelligence System

> LLM-powered trade signal extraction from SEC earnings filings — reads what 
> companies *say*, not just what their stock *does*.

![Python](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.136-green)
![React](https://img.shields.io/badge/React-19-61dafb)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

## What It Does

Most trading systems react to price. This one reads language.

The system pulls 8-K earnings filings directly from the SEC EDGAR API, runs 
them through an LLM (Claude Haiku), and extracts a structured trade signal: 
sentiment, confidence score, bull/bear case, risk flags, management tone, and 
guidance quality. Signals are backtested against historical price data and 
visualized in a full-stack dashboard.

**No paid data feeds. No Bloomberg terminal. Just the SEC's free public API 
and an LLM that can read.**

---

## Architecture

```
SEC EDGAR (free, no key)          yfinance (earnings + prices)
         │                                    │
         └──────────────┬─────────────────────┘
                        ▼
              [ Phase 1 — Data Ingestion ]
              sec_client.py · market_client.py · SQLite
                        │
                        ▼
              [ Phase 2 — LLM Signal Extraction ]
              Claude Haiku · structured JSON output
              sentiment · confidence · guidance · risk flags
                        │
                        ▼
              [ Phase 3 — Backtesting ]
              numpy · 13 trades · 5-day hold window
              Sharpe ratio · max drawdown · vs SPY benchmark
                        │
                        ▼
              [ Phase 4 — Live Paper Trading ]        ← planned
              Alpaca API · autonomous execution
                        │
                        ▼
              [ Phase 5 — Dashboard ]
              FastAPI · React + TypeScript · Recharts
```

---

## Results

Backtested on 13 trades across AAPL, NVDA, MSFT, GOOGL (2024–2026):

| Metric | Value |
|---|---|
| Win Rate | 38.5% |
| Sharpe Ratio | -0.77 |
| Max Drawdown | -33.4% |
| Total Return | -13.0% |
| SPY (same period) | +16.3% |

> **Note:** The live demo runs on 3 seed signals and shows 2 trades (+3.3% vs SPY +2.8%). The table below reflects a fuller 13-trade backtest run locally across multiple earnings cycles. Expand coverage with `python main.py TSLA --filings 10 --analyze` and re-run `python main.py --backtest` to reproduce.

The naive "buy bullish signal, hold 5 days" strategy underperformed SPY. 
This is the honest result — and the starting point for strategy refinement. 
Higher confidence thresholds and guidance quality filters are the next iteration.

---

## Dashboard

The React dashboard provides five views:

- **Overview** — live stats, sentiment distribution, recent signal feed
- **Signals** — full signal table with ticker filter, confidence bars, sentiment badges
- **Signal Detail** — LLM reasoning, bull/bear case, risk flags, raw filing viewer
- **Backtest** — equity curve, Sharpe/drawdown stats, full trade ledger
- **Portfolio** — paper trading view (Phase 4)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Data ingestion | Python, SEC EDGAR API, yfinance |
| NLP / LLM | Anthropic Claude Haiku (claude-haiku-4-5-20251001) |
| Storage | SQLite (WAL mode, migration-safe schema) |
| Backtesting | NumPy, manual trade simulation |
| API | FastAPI, Pydantic, uvicorn |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, Recharts |
| CLI | argparse, rich |

---

## Project Status

| Phase | Status | Description |
|---|---|---|
| 1 — Data Ingestion | ✅ Complete | SEC EDGAR + yfinance pipeline |
| 2 — LLM Signals | ✅ Complete | Structured signal extraction |
| 3 — Backtesting | ✅ Complete | Historical performance analysis |
| 4 — Paper Trading | 🔜 Planned | Alpaca autonomous execution |
| 5 — Dashboard | ✅ Complete | FastAPI + React frontend |

---

## Setup

```bash
# Clone and enter
git clone https://github.com/YOUR_USERNAME/earnings-intel.git
cd earnings-intel

# Create virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1      # Windows
source .venv/bin/activate        # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Add your API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

## Usage

```bash
# Fetch filings for a ticker
python main.py AAPL --filings 6

# Run LLM signal extraction
python main.py AAPL --analyze

# Run backtest
python main.py --backtest

# Start the dashboard
# Terminal 1:
uvicorn api.main:app --reload

# Terminal 2:
cd dashboard && npm install && npm run dev
# Open http://localhost:5173
```

---

## Key Design Decisions

**Why 8-K filings instead of earnings call transcripts?**  
8-Ks are free via SEC EDGAR. Transcripts require paid APIs (Refinitiv, etc.). 
This system achieves comparable signal quality at zero data cost.

**Why Claude Haiku over GPT-4?**  
Haiku costs ~$0.002/filing vs ~$0.02 for GPT-4o-mini, enabling backtest runs 
across 500+ historical events without significant API spend.

**Why show negative backtest results?**  
Because they're real. A strategy that shows perfect returns on first run is 
almost always overfit. The honest result is the starting point for iteration.

---

## What's Next

- Confidence threshold sweep (0.6 → 0.8 → 0.9) to find the signal subset that works
- Guidance quality filter (only trade "strong" or "raised" guidance signals)
- Phase 4: Alpaca paper trading for live autonomous execution
- Expand to 20+ tickers for statistically robust backtesting

---

*Built by Sebastian Caraballo · Purdue University · Mechanical Engineering + CS*
