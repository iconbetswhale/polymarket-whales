# 🐳 Polymarket Whales

A live dashboard tracking the open positions of the **top 50 traders** on [Polymarket](https://polymarket.com) by overall profit.

![Dashboard preview](https://img.shields.io/badge/status-live-brightgreen)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Flask](https://img.shields.io/badge/flask-3.x-lightgrey)

## Features

- Aggregates top traders across **10 categories**: Politics, Crypto, Sports, Economics, Tech, Entertainment, Science, and more
- Shows **all open positions** in real time — no category filter
- Auto-refreshes every 3 minutes
- Filter by category or search by market/wallet
- Sort by current value, P&L, price, or wallet rank
- Tracks unrealized P&L and current position value

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/YOUR_USERNAME/polymarket-whales.git
cd polymarket-whales
pip install -r requirements.txt

# 2. Build the wallet list (queries Polymarket Analytics API)
python ingest_top_wallets.py

# 3. Run the dashboard
python app.py
# → http://localhost:5000
```

## How it works

### Wallet ingestion (`ingest_top_wallets.py`)
Queries the [Polymarket Analytics API](https://legacy.polymarketanalytics.com) across 10 major categories, collects the top 100 traders per category, deduplicates by wallet address, sums P&L across categories, and keeps the top 50 by total profit. Saves to `top_wallets.json`.

Re-run periodically to refresh the wallet list as rankings change:
```bash
python ingest_top_wallets.py --top 50 --per-tag 100
```

### Dashboard (`app.py`)
Loads `top_wallets.json`, then polls the [Polymarket positions API](https://data-api.polymarket.com) for each wallet in a background thread. The Flask app serves a live-updating grid of open positions categorized automatically by market title.

### API endpoints
| Endpoint | Description |
|---|---|
| `GET /` | Dashboard UI |
| `GET /api/positions` | All open positions as JSON |
| `GET /api/wallets` | Top wallet list as JSON |

## Configuration

Copy `.env.example` to `.env`:
```
REFRESH_INTERVAL=180   # seconds between position refreshes
```

## Deployment (Render)

The included `render.yaml` deploys to [Render.com](https://render.com) for free:
1. Push this repo to GitHub
2. Connect it on Render → "New Web Service" → select the repo
3. It uses `render.yaml` automatically

## Data sources
- **Wallet rankings**: [Polymarket Analytics](https://legacy.polymarketanalytics.com) — public API, no key required
- **Open positions**: [Polymarket Data API](https://data-api.polymarket.com) — public API, no key required

## License

MIT
