# IconBets Polymarket Wallet Tracker

Private read-only Flask dashboard for manually selected Polymarket wallets. The app separates verified upcoming, live, and completed sports positions; calculates bankroll-based recommendations from executable CLOB asks; and keeps an immutable SQLite-backed recommendation tracker.

## Multi-PC Workflow

GitHub is the source of truth. Only one PC should actively modify `main` at a time, and each PC must pull the latest `main` before editing.

PC 1:

```powershell
git pull origin main
# work
# test
git add .
git commit
git push origin main
```

PC 2:

```powershell
git pull origin main
# work
# test
git add .
git commit
git push origin main
```

Never hand work to the other PC until the current PC has tested, committed, and pushed its intended changes. The receiving PC must pull before starting work.

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
- `execution_providers.py`: exchange-provider contract, canonical market matching, cached NoVIG feed, and deep links
- `market_lifecycle.py`: upcoming, live, completed, and uncertain classification
- `bet_sizing.py`: evidence score, executable-entry simulation, Half Kelly, and risk caps
- `bet_tracker.py`: immutable snapshots, settlement status, and bankroll replay
- `classification.py`: sports and non-sports market classification
- `database.py`: SQLite development store with durable production routing
- `durable_user_store.py`: PostgreSQL persistence for wallet-position history, shadow tracking, bankrolls, Model Tracker records, hidden trades, and personal fills
- `model_tracker_discord.py`: Model Tracker bot payloads, Discord validation, and outbox delivery
- `position_tracker.py`: refresh orchestration, event detection, consensus building, and API payload generation
- `unit_analysis.py`: betting-unit estimation and manual overrides
- `scoring.py`: position conviction scoring
- `templates/` and `static/`: dashboard UI
- `tests/`: mocked automated test suite
- `scripts/discover_nfl_wallet_candidates.py`: research-only NFL wallet screen using current game-market holders, sports leaderboards, and settled full-game history
- `scripts/ingest_top_wallets.py`: optional legacy utility only

## NFL Wallet Research Screen

Run the NFL screen without changing the live wallet registry:

```powershell
python scripts/discover_nfl_wallet_candidates.py --output outputs/nfl-wallet-candidates-latest.json
```

The scanner evaluates clean directional full-game moneylines, spreads, and
totals, includes registered NFL wallets as benchmarks, and labels candidates as
priority research, watchlist, or insufficient/negative. It never edits
`wallets.json` and never promotes a wallet automatically. Full executed-fill
extraction and forward executable-price tracking are required before any live
role review.

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

`DURABLE_DATABASE_URL=`
Optional PostgreSQL connection string for user-owned state. This is required on
serverless production hosts; `POSTGRES_URL` and `DATABASE_URL` are also detected.

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

`DISCORD_BOT_TOKEN=`
Server-only Discord bot token used for Model Tracker notifications. Never expose it to browser code, logs, or API responses.

`DISCORD_GUILD_ID=`
Discord server ID that must own the configured trade channel.

`DISCORD_TRADE_CHANNEL_ID=`
Discord channel ID that receives successfully inserted Model Tracker recommendations.

`DISCORD_NOTIFICATIONS_ENABLED=false`
Enables Model Tracker bot notifications. The bot variables can be configured while this remains false.

`DISCORD_NOTIFICATION_BATCH_SIZE=10`
Maximum persisted Discord jobs claimed during one backend reconciliation run.

The Model Tracker insert is the notification source of truth. A qualifying Today recommendation and its unique Discord outbox job are written in one database transaction. The existing scheduled Model Tracker reconciliation drains that outbox, records success or a safe error code, and retries transient failures without requiring a browser page to be open. Personal Tracker records and dashboard-only recommendations never enter this outbox.

`ODDSENGINE_API_KEY=`
Server-only OddsEngine key used as the preferred live all-book feed for Positive EV, Arbitrage, Middles, Low Hold, Odds Screen, Fantasy Optimizer, Sharp Money comparisons, model fair pricing, and sportsbook line shopping. Requests authenticate with `X-API-Key`; the key is never sent to the browser or included in diagnostics. The standard event and odds endpoints feed IconLabs' existing calculators and models, so provider changes do not alter their math.

`ODDSENGINE_API_BASE_URL=https://api.oddsengine.dev/v1`
OddsEngine API base URL. One shared raw-event cache serves every compatible live page, so a league schedule and event snapshot are reused across calculators, model cards, DFS, Sharp Money, and the always-on Odds Screen. Scans are capped at 5 upcoming events per league and 20 total events to reserve the plan's per-minute budget across the always-on screens. The adapter records the provider's rate-limit headers and returns already-fetched events as a partial snapshot if a scan reaches the limit. SportsGameOdds and The Odds API remain automatic fallbacks when an OddsEngine request fails; historical close and score settlement continue using providers with those specialized endpoints.

`SPORTSGAMEODDS_API_KEY=`
Server-side SportsGameOdds All Lines API key for the Positive EV feed and normalized NoVIG prices. `NOVIG_ODDS_API_KEY` remains a backward-compatible alias. When no key is configured, the Positive EV live scan and NoVIG options remain unavailable while Polymarket execution is unaffected.

`SPORTSGAMEODDS_API_BASE_URL=https://api.sportsgameodds.com/v2`
All-book market-feed base URL. `NOVIG_ODDS_API_BASE_URL` remains a backward-compatible alias. Override only for a compatible proxy or test service.

`SPORTSGAMEODDS_CACHE_TTL_SECONDS=45`
Maximum in-memory age for the all-book feed and live NoVIG prices. `NOVIG_ODDS_CACHE_TTL_SECONDS` remains a backward-compatible alias. One cached provider feed powers the Positive EV board and matches all visible trades, avoiding per-card API requests.

`NOVIG_CLIENT_ID=` and `NOVIG_CLIENT_SECRET=`
Server-only OAuth client credentials for NoVIG's production NBX exchange API.
The direct NBX adapter is read-only and is separate from SportsGameOdds. It
loads authoritative events, markets, and CASH order books, preserves NoVIG's
event/market/outcome identifiers, and never exposes credentials or JWTs in API
responses, logs, browser assets, or diagnostics.

`NOVIG_ENABLED=true`
Global kill switch for the direct NBX provider. Turning it off does not affect
SportsGameOdds, Polymarket, Kalshi, ProphetX, 4CX, or The Odds API.

`NOVIG_AUTH_URL=https://api.novig.us/nbx/v1/auth/emm-token`,
`NOVIG_REST_BASE_URL=https://api.novig.us/nbx/v2`, and
`NOVIG_WEBSOCKET_URL=wss://api.novig.us/tape`
Production endpoints. Tokens are cached server-side and renewed before their
30-minute expiry. REST retries once after a 401 and honors NoVIG's millisecond
`Retry-After` value on a 429.

`NOVIG_STATE_DATABASE_URL=`
Shared PostgreSQL connection used by the persistent NoVIG feed worker and the
serverless Flask API. It defaults to `DURABLE_DATABASE_URL`, `POSTGRES_URL`, or
`DATABASE_URL`. The worker owns the permanent WebSocket because Vercel request
functions cannot safely hold it; Vercel reads the worker's current book state
from PostgreSQL and falls back to authenticated REST when state is unavailable.

`NOVIG_STALE_AFTER_SECONDS=30`
Age after which a NoVIG quote is marked stale and excluded from current-price
selection. REST is reloaded before every WebSocket connection/reconnection,
then global tape and lifecycle deltas update the authoritative snapshot.

Run the sanitized read-only production check from a process that already has
the two credentials in its environment:

```powershell
python scripts/novig_smoke.py
```

The command prints only success/failure, HTTP status, market and market-type
counts, a small public sample, initial book/quantity metadata, and WebSocket
snapshot/update flags. It never prints the credentials or access token.
Vercel Sensitive variables are intentionally unreadable to local `env pull`
and `env run` commands; verify those through a new deployment or provide
separate Development-scoped credentials to the local process without writing
them to a repository file.

`POSITIVE_EV_ENABLED=true`
Enables paid Positive EV scans. Leave this false to pause the scanner without removing the API key or making upstream requests.

Positive EV fair odds default to the Power devig method. Users can switch to Power, Additive, Multiplicative, or Shin, and can allocate exactly 100% across Pinnacle, Circa, Bookmaker.eu, FanDuel, and Betfair Exchange; every other subscribed book remains available for execution-price comparison without influencing the fair-price consensus.

`PROPHETX_ACCESS_KEY=` and `PROPHETX_SECRET_KEY=`
Server-only credentials generated from the ProphetX sandbox account under **Menu → API Integration**. Authentication responses are cached for nine minutes so the ten-minute access token is renewed before expiry. Credential values and upstream error bodies are never logged or returned by the provider-health endpoint.

`PROPHETX_API_BASE_URL=https://api-ss-sandbox.betprophet.co/partner`
ProphetX Trading API base URL. Keep the sandbox URL until ProphetX explicitly grants production access. Order submission remains disabled; IconBets uses only authenticated read-only tournament, event, market, odds, and liquidity endpoints.

`PROPHETX_TRADE_URL=https://ss-sandbox.betprophet.co/`
Destination opened by an exact ProphetX execution option. Change this to the production lobby only after ProphetX grants production access.

`PROPHETX_CACHE_TTL_SECONDS=30`
Maximum in-memory age for the batched ProphetX market feed. The provider never performs one request per trade card.

## Execution Options

Trades to Play exposes execution providers through an ordered provider registry. Polymarket is always first. NoVIG is included only when the normalized sport, league, participants, event time, market type, period, line, side, alternate-line status, and settlement rules all match exactly.

When direct NBX credentials are absent, the legacy NoVIG comparison continues
to use the paginated SportsGameOdds event feed. When NBX is configured, direct
REST/WebSocket prices and full CASH order-book depth become authoritative for
NoVIG while SportsGameOdds continues powering the all-books Positive EV feed.
Probable and ambiguous matches are never silently merged; sanitized unmatched
records are available through the protected diagnostic endpoint.

The backend exposes direct NoVIG data at `GET /api/providers/novig/markets`,
lazy full ladders at `GET /api/providers/novig/book/{marketId}`, and protected
health/smoke diagnostics at `GET|POST /api/provider-health/novig`. The worker is
started separately with `python scripts/run_novig_feed.py`; it is never started
inside the Vercel request process.

The ProphetX integration exchanges the server-only key pair for a short-lived token, batch-loads the affiliate tournament/event/v3 market feed, converts decimal prices to American odds, and uses the same exact canonical matcher. Only one exact match is shown; mismatched periods, sides, lines, participants, start times, or ambiguous selections remain hidden.

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

The app creates `polymarket_tracker.db` automatically on first start. When a
durable PostgreSQL URL is configured, wallet positions, position events,
Shadow Lab history, recommendation ledgers, and user-owned state are all written
to PostgreSQL. SQLite remains the local-development fallback.

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

`vercel.json` rewrites every frontend route to the Flask function, so direct route visits and browser refreshes work. Vercel's function filesystem is ephemeral,
so production must set `DURABLE_DATABASE_URL`, `POSTGRES_URL`, or `DATABASE_URL`.
Live API responses can be rebuilt after a cold start, while wallet-position
history, Shadow Lab samples, Bet Tracker history, and other user-owned records
remain in PostgreSQL.

The `/health` response reports `user_data_persistent: true`,
`position_history_persistent: true`, and a healthy `durable_user_store` when
production persistence is correctly configured.
Render's persistent disk configuration below remains a durable SQLite alternative.

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
