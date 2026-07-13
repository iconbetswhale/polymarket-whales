# IconBets Polymarket Wallet Tracker

Private read-only Flask dashboard for manually selected Polymarket wallets. The app separates verified upcoming, live, and completed sports positions; calculates bankroll-based recommendations from executable CLOB asks; and keeps an immutable SQLite-backed recommendation tracker.

## What Changed

The old leaderboard-driven `top_wallets.json` flow is no longer used by the app.

The new source of truth is `wallets.json`, which lets you manually choose the exact public wallets you want to track.

The dashboard now tracks:

- Open positions
- New entries
- Position increases
- Position decreases
- Full exits
- Average entry price
- Current price
- Current value
- Unrealized P&L
- Realized P&L when available from Polymarket's closed positions endpoint
- Wallet consensus on the same market and outcome
- Wallet-level estimated unit size
- Position conviction based only on verified data
- Verified event lifecycle and Eastern Time start times
- Exact executable ask and volume-weighted entry pricing
- Evidence-bounded Half Kelly recommendations
- Automatic Today-only Bet Tracker snapshots
- Bankroll replay, realized P&L, ROI, and drawdown

## Repository Layout

- `app.py`: Flask application and API routes
- `config.py`: environment variable loading
- `wallet_loader.py`: manual wallet validation, normalization, duplicate detection
- `polymarket_client.py`: public Polymarket API client with timeouts, retries, and event/profile helpers
- `market_lifecycle.py`: upcoming, live, completed, and uncertain classification
- `bet_sizing.py`: evidence score, executable-entry simulation, Half Kelly, and risk caps
- `bet_tracker.py`: immutable snapshots, settlement status, and bankroll replay
- `classification.py`: sports and non-sports market classification
- `database.py`: SQLite persistence for tracked positions and position events
- `position_tracker.py`: refresh orchestration, event detection, consensus building, and API payload generation
- `unit_analysis.py`: betting-unit estimation and manual overrides
- `scoring.py`: position conviction scoring
- `templates/` and `static/`: dashboard UI
- `tests/`: mocked automated test suite
- `scripts/ingest_top_wallets.py`: optional legacy utility only

## Install Python

Install Python 3.10 or newer from the official installer:

- [Windows Python Downloads](https://www.python.org/downloads/windows/)

During install, enable "Add Python to PATH".

## Local Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Copy environment variables:

```powershell
Copy-Item .env.example .env
```

## Configure `wallets.json`

The app ships with a disabled placeholder entry:

```json
[
  {
    "address": "REPLACE_WITH_WALLET_ADDRESS",
    "label": "Trader 1",
    "enabled": false,
    "base_unit": null,
    "notes": ""
  }
]
```

Replace that with your real public Polymarket wallets.

Rules:

- Addresses must start with `0x`
- Addresses must contain exactly 40 hexadecimal characters after `0x`
- Addresses are normalized to lowercase
- Duplicate addresses are rejected
- Invalid entries are reported in the UI and `/health`
- Disabled wallets are never queried
- No private keys, seed phrases, or authentication are required

Example with a manual unit override:

```json
[
  {
    "address": "0x204f72f35326db932158cba6adff0b9a1da95e14",
    "label": "Swiss Tony",
    "enabled": true,
    "base_unit": 100,
    "notes": "Manual 1u = $100"
  }
]
```

## Environment Variables

`DASHBOARD_REFRESH=15`
Backend wallet refresh cadence in seconds. The browser also polls the dashboard API every 15 seconds unless auto-refresh is paused.

`DASHBOARD_PORT=5000`
Local Flask port. In production, the app prefers Render's `PORT`.

`WALLETS_FILE=wallets.json`
Manual wallet file path.

`DATABASE_PATH=polymarket_tracker.db`
SQLite database path.

`SPORTS_ONLY=true`
Default sports-only mode.

`RESOLVE_HOURS=168`
Only show positions resolving within this many hours.

`MIN_AMERICAN_ODDS=`
Optional minimum displayed American odds filter.

`MAX_AMERICAN_ODDS=`
Optional maximum displayed American odds filter.

`REQUEST_TIMEOUT=15`
Public API timeout in seconds.

`MAX_RETRIES=3`
Retry count for rate limits, timeouts, and transient failures.

`DEFAULT_BANKROLL=10000`
Starting bankroll used for a new anonymous browser profile.

`UNIT_PERCENTAGE=0.01`
Bankroll percentage represented by one displayed unit. The default is 1%.

`ADMIN_PASSWORD=`
Reserved only if you later add authenticated wallet editing. The current app does not expose write endpoints.

`DISCORD_WEBHOOK_URL=`
Optional Discord channel webhook for wallet play alerts. Keep this secret out of Git history.

`DISCORD_ALERT_TYPES=new_entry,size_increase,full_exit`
Comma-separated event types to send to Discord. Price-change events are intentionally excluded by default to avoid noisy alerts.

`DISCORD_MIN_POSITION_USD=0`
Minimum position size required before an event sends a Discord alert.

`DISCORD_NOTIFY_ON_INITIAL_SCAN=false`
When false, the first scan after adding a wallet records existing open positions without sending Discord alerts. This helps prevent old positions from spamming the channel.

## Run Locally

Development server:

```powershell
python app.py
```

Open:

- `http://localhost:5000/trades`
- `http://localhost:5000/overview`
- `http://localhost:5000/live-positions`
- `http://localhost:5000/wallets`
- `http://localhost:5000/position-history`
- `http://localhost:5000/bet-tracker`
- `http://localhost:5000/health`

Production-style local startup:

```powershell
gunicorn --bind 0.0.0.0:5000 --workers 1 app:app
```

## Run Tests

The tests use mocked Polymarket responses and do not depend on live APIs.

```powershell
pytest
```

Covered areas include:

- Wallet validation and normalization
- Duplicate detection
- Disabled-wallet behavior
- Missing wallet file and invalid JSON
- Sports classification
- American odds conversion
- Position change detection
- New trade detection
- Increase, decrease, and exit detection
- Duplicate event prevention
- Unit-size estimation
- Manual unit overrides
- Consensus grouping
- Application startup
- Health and API endpoints
- Lifecycle separation and stale-status exclusion
- Executable-entry and insufficient-liquidity handling
- Evidence scoring, Half Kelly math, and all risk caps
- Tracker deduplication, immutable snapshots, settlement, and bankroll replay

## How Unit Estimates Work

The estimator uses recent sports trade amounts and current sports positions, then looks for repeated sizing patterns across:

- 0.25u
- 0.5u
- 0.75u
- 1u
- 1.25u
- 1.5u
- 2u
- 3u
- 4u
- 5u
- 6u
- 8u
- 10u

Tiny test trades and obvious outliers are filtered out first.

If there is not enough data, the UI shows:

`Insufficient data to estimate unit size`

If you set `base_unit` in `wallets.json`, that manual override wins and is labeled as `manual`.

## How Position Conviction Works

The tracker does not invent win rate, ROI, or profitability data.

It scores conviction only from verified information such as:

- Position size relative to the wallet's estimated unit
- Percentage of the wallet's visible sports portfolio
- Number of tracked wallets on the same side
- Observed position increases
- Entry price versus current price
- Time remaining until resolution
- Sports concentration of the visible wallet portfolio

If there is not enough verified data, conviction is shown as `Neutral`.

## Wallet Consensus

Consensus groups only wallets holding the same `conditionId` and same outcome.

Opposite outcomes are never grouped together.

Each consensus row shows:

- Market
- Outcome
- Number of tracked wallets
- Combined position value
- Combined estimated units
- Average entry price
- Current price
- Wallet names
- Largest holder
- Earliest entry time
- Most recent increase

## Recommendation Sizing

Recommendations use the current executable ask as the baseline probability. For a positive stake, the app walks the real Polymarket CLOB ask levels and recalculates the effective volume-weighted entry price for that stake.

The evidence score is a weighted sum of normalized components:

- Sharps consensus: 45%
- Exact combined amount: 20%
- Relative bet size: 15%
- Proven top category: 8%
- Bayesian-adjusted category hit rate: 8%
- Settled category sample size: 4%

Only evidence above the neutral score of `0.50` increases the estimated probability. That increase is capped at `+2pp`, `+4pp`, `+7pp`, or `+10pp` for one, two, three, or four-plus Sharps. A truly unanimous tracked-wallet signal is capped at `+12pp`.

For effective entry price `p`, estimated probability `q`, and net decimal odds `b = (1 - p) / p`, the full Kelly fraction is:

```text
((b * q) - (1 - q)) / b
```

The app uses Half Kelly, never a negative stake, and applies Sharp-count bankroll caps of 1%, 2%, 3%, or 4%. A unanimous signal may reach 5%, and the global cap is always 5%. If the verified evidence does not produce positive edge, the result is `No recommended bet at the current entry`. If a token or executable ask is missing, sizing is explicitly unavailable.

## Event Lifecycle

An active trade is classified into exactly one state. Verified future starts are Upcoming. Explicit game or market status terms mark Live. Official closed, ended, graded, settled, canceled, or void states mark Completed. Gamma's generic event `live` publication flag is not treated as proof that a sporting event is in progress.

Missing or contradictory status is marked uncertain. Obviously stale live flags and past events without reliable status are logged and hidden from active pages rather than shown incorrectly. Completed positions remain available only through Position History and Bet Tracker history.

## Bet Tracker

Positive recommendations are added automatically only when they are in the Today window. Next 24 Hours and Next 7 Days are preview ranges and are not tracked early.

The immutable snapshot includes the event, market, line, outcome token, recommendation version, current and effective entry, Sharp entry, evidence inputs, probability adjustment, Kelly values, risk cap, original bankroll percentage, and source wallet IDs. The stable event/market/line/outcome/version key prevents duplicate refreshes from creating duplicate bets.

Changing bankroll replays the stored recommended percentage against the original effective entry; it does not rerun the model with future information. Wins use `stake * ((1 / entry) - 1)`, losses use `-stake`, and pushes, voids, or cancellations return zero profit.

## Database Behavior

The app creates `polymarket_tracker.db` automatically on first start.

SQLite tables include:

- `tracked_positions`: latest open or closed snapshot per wallet and position
- `position_events`: meaningful changes over time
- `refresh_state`: last refresh metadata
- `user_settings`: anonymous per-browser bankroll settings
- `bet_tracker`: immutable recommendation snapshots and settlement state
- `hidden_trades`: exact user-scoped event/market/line/outcome preferences
- `personal_bet_fills`: separate confirmed Personal Tracker fills and settlement state

Hidden trades are keyed by the current browser user plus canonical event ID,
market ID, normalized market line, and outcome token ID. Personal Tracker fills
use the same identity but remain separate rows so repeat purchases preserve their
individual entry price, shares, fees, and timestamp. Model Tracker snapshots in
`bet_tracker` never create personal-exposure warnings.

Events are only added when there is a meaningful change, such as:

- New entry
- Size increase
- Size decrease
- Average entry price change
- Current price change
- Current value change
- Unrealized P&L change
- Full exit

Repeated refreshes without meaningful changes do not create duplicate events.

## Vercel Deployment

`vercel.json` rewrites every frontend route to the Flask function, so direct route visits and browser refreshes work. The current deployment can run the application, but Vercel's function filesystem is ephemeral. Local SQLite data is not guaranteed to survive a cold start or redeploy.

For durable hosted Bet Tracker history, point the persistence layer at a managed database such as Postgres before treating production records as permanent. Render's persistent disk configuration below supports durable SQLite as an alternative.

## Render Deployment

The included `render.yaml` uses:

- `pip install -r requirements.txt`
- `gunicorn --bind 0.0.0.0:$PORT --workers 1 app:app`
- `GET /health` as the health check
- A persistent disk mounted at `/var/data`

Important SQLite limitation:

Render web services normally use ephemeral storage. Without a persistent disk, your SQLite database is lost on restart or redeploy.

The Blueprint includes a persistent disk and sets:

- `DATABASE_PATH=/var/data/polymarket_tracker.db`

Deployment steps:

1. Push the repository to GitHub.
2. Create a new Render Blueprint deployment from the repo.
3. Confirm the persistent disk is created.
4. Add your real `wallets.json` content before deploying, or commit it to your private repo.
5. Set any optional environment overrides in Render.

## Optional Legacy Script

`ingest_top_wallets.py` still exists as a wrapper around `scripts/ingest_top_wallets.py`, but it is optional only.

The application does not run it during build, startup, or refresh.

## Troubleshooting

Empty dashboard:

- Make sure at least one wallet in `wallets.json` is valid and `enabled: true`
- Check `/health` for invalid wallet count
- Confirm the wallet actually has current positions on Polymarket
- If `SPORTS_ONLY=true`, non-sports positions are intentionally filtered out

API failures:

- Check `/health` and `/api/status`
- Increase `REQUEST_TIMEOUT`
- Review `MAX_RETRIES`
- One failed wallet should fall back to last-known-good data from SQLite

Wallet marked invalid:

- Confirm lowercase or uppercase hex is fine, but it must still be a real `0x` address with exactly 40 hex characters

Verify health manually:

```powershell
curl http://localhost:5000/health
```

## Security Notes

This is a read-only analytics dashboard.

It does not include:

- Private keys
- Seed phrases
- Trading credentials
- Automated trading
- Order placement
- Withdrawals

The current application also does not expose write endpoints for modifying wallets from the browser.
