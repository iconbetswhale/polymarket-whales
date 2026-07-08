"""
app.py — Polymarket Whales Dashboard
Tracks open positions for the top 50 Polymarket wallets.
"""

import json, threading, time, os
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, render_template_string
import requests

app = Flask(__name__)

WALLETS_FILE = Path("top_wallets.json")
POSITIONS_URL = "https://data-api.polymarket.com/positions"

REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "180"))  # seconds

_lock = threading.Lock()
_cache: dict = {"data": [], "last_updated": None, "wallets": []}

# ── Category classifier ──────────────────────────────────────────────────────

CATEGORY_RULES: list[tuple[str, str]] = [
    # Politics
    ("trump", "Politics"), ("biden", "Politics"), ("harris", "Politics"),
    ("president", "Politics"), ("election", "Politics"), ("senate", "Politics"),
    ("congress", "Politics"), ("democrat", "Politics"), ("republican", "Politics"),
    ("supreme court", "Politics"), ("prime minister", "Politics"),
    ("macron", "Politics"), ("modi", "Politics"), ("zelensky", "Politics"),
    ("nato", "Politics"), (" eu ", "Politics"), ("parliament", "Politics"),
    ("governor", "Politics"), ("vote", "Politics"), ("ballot", "Politics"),

    # Crypto
    ("bitcoin", "Crypto"), (" btc ", "Crypto"), ("ethereum", "Crypto"),
    (" eth ", "Crypto"), ("solana", "Crypto"), (" sol ", "Crypto"),
    ("crypto", "Crypto"), ("defi", "Crypto"), (" nft", "Crypto"),
    ("coinbase", "Crypto"), ("binance", "Crypto"), ("dogecoin", "Crypto"),
    (" doge", "Crypto"), ("ripple", "Crypto"), (" xrp", "Crypto"),
    ("stablecoin", "Crypto"), ("blockchain", "Crypto"), ("altcoin", "Crypto"),

    # Economics / Finance
    ("federal reserve", "Economics"), (" fed ", "Economics"),
    ("inflation", "Economics"), (" gdp", "Economics"), ("recession", "Economics"),
    ("interest rate", "Economics"), ("stock market", "Economics"),
    ("s&p 500", "Economics"), ("nasdaq", "Economics"), ("dow jones", "Economics"),
    ("tariff", "Economics"), ("trade war", "Economics"), ("treasury", "Economics"),
    ("cpi ", "Economics"), ("unemployment", "Economics"),

    # Entertainment / Awards
    ("oscar", "Entertainment"), ("grammy", "Entertainment"), ("emmy", "Entertainment"),
    ("golden globe", "Entertainment"), ("box office", "Entertainment"),
    ("taylor swift", "Entertainment"), ("album", "Entertainment"),
    ("spotify", "Entertainment"), ("netflix", "Entertainment"),
    ("movie", "Entertainment"), ("award", "Entertainment"),
    ("celebrity", "Entertainment"),

    # Tech / AI
    ("openai", "Tech"), ("chatgpt", "Tech"), ("gpt-", "Tech"),
    (" ai ", "Tech"), ("artificial intelligence", "Tech"),
    ("nvidia", "Tech"), ("spacex", "Tech"), ("starship", "Tech"),
    ("apple ", "Tech"), ("google", "Tech"), ("microsoft", "Tech"),
    ("tesla", "Tech"), (" meta ", "Tech"), ("amazon aws", "Tech"),
    ("semiconductor", "Tech"), ("iphone", "Tech"),

    # Science / Environment
    ("climate", "Science"), ("hurricane", "Science"), ("earthquake", "Science"),
    ("pandemic", "Science"), ("vaccine", "Science"), ("nasa", "Science"),
    ("nobel", "Science"), ("temperature record", "Science"),

    # Sports — broad keywords (more specific ones catch most cases)
    ("nfl", "Sports"), ("nba", "Sports"), ("mlb", "Sports"), ("nhl", "Sports"),
    ("mls", "Sports"), ("ufc", "Sports"), ("mma", "Sports"),
    ("premier league", "Sports"), ("champions league", "Sports"),
    ("world cup", "Sports"), ("super bowl", "Sports"), ("stanley cup", "Sports"),
    ("wimbledon", "Sports"), ("us open", "Sports"), ("french open", "Sports"),
    ("australian open", "Sports"), ("formula 1", "Sports"), (" f1 ", "Sports"),
    ("boxing", "Sports"), ("wrestling", "Sports"), (" nascar", "Sports"),
    ("match winner", "Sports"), ("game winner", "Sports"), ("win the series", "Sports"),
]


def classify(title: str) -> str:
    t = title.lower()
    for kw, cat in CATEGORY_RULES:
        if kw in t:
            return cat
    return "Other"


# ── Position fetcher ─────────────────────────────────────────────────────────

def _float(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def fetch_wallet_positions(addr: str, label: str) -> list[dict]:
    rows, offset, limit = [], 0, 500
    while True:
        try:
            r = requests.get(
                POSITIONS_URL,
                params={"user": addr, "limit": limit, "offset": offset, "sizeThreshold": 0},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=20,
            )
            if r.status_code != 200:
                break
            batch = r.json()
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < limit:
                break
            offset += limit
        except Exception:
            break
    return rows


def build_position(addr: str, label: str, rank: int, pos: dict) -> dict | None:
    title = pos.get("title") or pos.get("market") or ""
    if not title:
        return None

    size = _float(pos.get("size"))
    if size <= 0:
        return None

    cur = _float(pos.get("curPrice"))
    initial = _float(pos.get("initialValue") or pos.get("cashInvested") or pos.get("cost"))
    cur_val = size * cur
    pnl = cur_val - initial if initial > 0 else 0.0

    outcome = pos.get("outcome") or pos.get("side") or ""
    icon = "YES" if str(outcome).upper() in ("YES", "TRUE", "1") else "NO" if str(outcome).upper() in ("NO", "FALSE", "0") else str(outcome)

    end_date = (pos.get("endDate") or "")[:10]

    return {
        "wallet_address": addr,
        "wallet_label": label,
        "wallet_rank": rank,
        "title": title,
        "category": classify(title),
        "outcome": icon,
        "cur_price": cur,
        "size": size,
        "cur_value": cur_val,
        "initial_value": initial,
        "unrealized_pnl": pnl,
        "end_date": end_date,
        "url": pos.get("url") or "",
        "slug": pos.get("slug") or pos.get("conditionId") or "",
    }


def refresh_all():
    wallets = _cache.get("wallets") or []
    if not wallets:
        return

    all_positions = []
    for w in wallets:
        addr = w.get("address", "")
        label = w.get("label", "") or addr[:8]
        rank = w.get("rank", 0)
        if not addr:
            continue
        raw = fetch_wallet_positions(addr, label)
        for pos in raw:
            row = build_position(addr, label, rank, pos)
            if row:
                all_positions.append(row)

    with _lock:
        _cache["data"] = all_positions
        _cache["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Refreshed: {len(all_positions)} open positions across {len(wallets)} wallets")


def refresh_loop():
    while True:
        try:
            refresh_all()
        except Exception as e:
            print(f"Refresh error: {e}")
        time.sleep(REFRESH_INTERVAL)


# ── Routes ───────────────────────────────────────────────────────────────────

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Polymarket Whales</title>
<style>
:root {
  --bg: #0b0f0e;
  --surface: #141a19;
  --border: #1f2a28;
  --text: #e4ede9;
  --muted: #6b8a80;
  --accent: #00d68f;
  --accent-dim: rgba(0,214,143,.12);
  --red: #f05252;
  --yellow: #f5a623;

  --cat-politics: #6b7fee;
  --cat-crypto:   #f5a623;
  --cat-economics:#7ec8e3;
  --cat-sports:   #00d68f;
  --cat-tech:     #c97bff;
  --cat-entertainment: #ff7ab8;
  --cat-science:  #5ce65c;
  --cat-other:    #8a9a95;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font: 14px/1.5 'Inter', system-ui, sans-serif; }

header {
  display: flex; align-items: center; gap: 16px;
  padding: 14px 24px; border-bottom: 1px solid var(--border);
  position: sticky; top: 0; background: var(--bg); z-index: 10;
}
header h1 { font-size: 18px; font-weight: 700; letter-spacing: -.3px; color: var(--accent); }
header .subtitle { color: var(--muted); font-size: 12px; }
header .meta { margin-left: auto; font-size: 11px; color: var(--muted); text-align: right; }

.toolbar {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 12px 24px; border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.toolbar input {
  background: var(--bg); border: 1px solid var(--border); color: var(--text);
  border-radius: 6px; padding: 5px 10px; font-size: 13px; width: 220px;
  outline: none;
}
.toolbar input:focus { border-color: var(--accent); }
.filter-tabs { display: flex; gap: 6px; flex-wrap: wrap; }
.tab {
  padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 600;
  cursor: pointer; border: 1px solid var(--border); color: var(--muted);
  background: transparent; transition: all .15s;
}
.tab:hover, .tab.active { color: var(--text); background: var(--accent-dim); border-color: var(--accent); }
.sort-btn {
  margin-left: auto; padding: 4px 10px; border-radius: 6px; font-size: 11px;
  cursor: pointer; border: 1px solid var(--border); color: var(--muted);
  background: transparent;
}
.sort-btn:hover { border-color: var(--accent); color: var(--text); }

.stats-bar {
  display: flex; gap: 24px; padding: 10px 24px;
  border-bottom: 1px solid var(--border); background: var(--bg);
}
.stat { font-size: 11px; color: var(--muted); }
.stat b { font-size: 14px; color: var(--text); display: block; font-variant-numeric: tabular-nums; }

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 12px;
  padding: 16px 24px;
}

.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 14px; position: relative; transition: border-color .15s;
}
.card:hover { border-color: var(--accent); }

.card-top { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 10px; }
.rank-badge {
  width: 28px; height: 28px; border-radius: 50%; background: var(--accent-dim);
  color: var(--accent); font-size: 11px; font-weight: 700; display: flex;
  align-items: center; justify-content: center; flex-shrink: 0;
}
.card-meta { flex: 1; min-width: 0; }
.card-wallet { font-size: 12px; font-weight: 700; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card-title { font-size: 13px; color: var(--text); line-height: 1.4; margin-top: 2px; }
.card-title a { color: var(--text); text-decoration: none; }
.card-title a:hover { color: var(--accent); }

.cat-pill {
  display: inline-block; padding: 2px 8px; border-radius: 12px;
  font-size: 10px; font-weight: 700; letter-spacing: .4px; text-transform: uppercase;
}
.cat-Politics     { background: rgba(107,127,238,.18); color: var(--cat-politics); }
.cat-Crypto       { background: rgba(245,166,35,.15);  color: var(--cat-crypto); }
.cat-Economics    { background: rgba(126,200,227,.15); color: var(--cat-economics); }
.cat-Sports       { background: rgba(0,214,143,.15);   color: var(--cat-sports); }
.cat-Tech         { background: rgba(201,123,255,.15); color: var(--cat-tech); }
.cat-Entertainment{ background: rgba(255,122,184,.15); color: var(--cat-entertainment); }
.cat-Science      { background: rgba(92,230,92,.15);   color: var(--cat-science); }
.cat-Other        { background: rgba(138,154,149,.15); color: var(--cat-other); }

.outcome-badge {
  padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;
}
.outcome-YES { background: rgba(0,214,143,.18); color: var(--accent); }
.outcome-NO  { background: rgba(240,82,82,.18);  color: var(--red); }
.outcome-other { background: rgba(255,255,255,.08); color: var(--muted); }

.metrics {
  display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8px;
  margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border);
}
.metric { text-align: center; }
.metric .val { font-size: 14px; font-weight: 700; font-variant-numeric: tabular-nums; }
.metric .lbl { font-size: 10px; color: var(--muted); margin-top: 2px; }
.pos { color: var(--accent); }
.neg { color: var(--red); }
.neu { color: var(--text); }

.price-bar {
  height: 3px; border-radius: 2px; background: var(--border); margin-top: 8px; overflow: hidden;
}
.price-fill { height: 100%; border-radius: 2px; background: var(--accent); }

.empty { padding: 60px 24px; text-align: center; color: var(--muted); font-size: 15px; }

@media(max-width:600px) {
  .grid { grid-template-columns: 1fr; padding: 12px; }
  .toolbar { padding: 10px 12px; }
  .stats-bar { padding: 8px 12px; gap: 16px; }
  header { padding: 12px; }
}
</style>
</head>
<body>

<header>
  <div>
    <h1>🐳 Polymarket Whales</h1>
    <div class="subtitle">Top {{ wallets|length }} traders &bull; live open positions</div>
  </div>
  <div class="meta">
    {{ positions|length }} positions tracked<br>
    {{ last_updated or "loading..." }}
  </div>
</header>

<div class="toolbar">
  <input type="text" id="search" placeholder="Search market or wallet..." oninput="filterCards()">
  <div class="filter-tabs" id="cat-tabs">
    <button class="tab active" data-cat="" onclick="setTab(this,'')">All</button>
    {% for c in categories %}
    <button class="tab" data-cat="{{ c }}" onclick="setTab(this,'{{ c }}')">{{ c }}</button>
    {% endfor %}
  </div>
  <button class="sort-btn" onclick="cycleSort()">Sort: <span id="sort-lbl">Value ↓</span></button>
</div>

<div class="stats-bar">
  <div class="stat"><b id="s-count">{{ positions|length }}</b>open positions</div>
  <div class="stat"><b id="s-value">${{ "{:,.0f}".format(total_value) }}</b>total cur value</div>
  <div class="stat"><b id="s-pnl" class="{{ 'pos' if total_pnl >= 0 else 'neg' }}">${{ "{:+,.0f}".format(total_pnl) }}</b>unrealized P&amp;L</div>
  <div class="stat"><b>{{ wallets|length }}</b>wallets</div>
</div>

<div class="grid" id="card-grid">
{% for p in positions %}
<div class="card"
  data-cat="{{ p.category }}"
  data-wallet="{{ p.wallet_label|lower }}"
  data-title="{{ p.title|lower }}"
  data-value="{{ p.cur_value }}"
  data-pnl="{{ p.unrealized_pnl }}"
  data-price="{{ p.cur_price }}"
  data-rank="{{ p.wallet_rank }}">

  <div class="card-top">
    <div class="rank-badge">#{{ p.wallet_rank }}</div>
    <div class="card-meta">
      <div class="card-wallet">{{ p.wallet_label or (p.wallet_address[:8] + "…") }}</div>
      <div class="card-title">
        {% if p.url %}
          <a href="{{ p.url }}" target="_blank">{{ p.title }}</a>
        {% else %}
          {{ p.title }}
        {% endif %}
      </div>
    </div>
  </div>

  <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
    <span class="cat-pill cat-{{ p.category }}">{{ p.category }}</span>
    <span class="outcome-badge outcome-{{ p.outcome if p.outcome in ('YES','NO') else 'other' }}">{{ p.outcome }}</span>
    {% if p.end_date %}<span style="font-size:10px;color:var(--muted);margin-left:auto">{{ p.end_date }}</span>{% endif %}
  </div>

  <div class="metrics">
    <div class="metric">
      <div class="val neu">${{ "{:,.0f}".format(p.cur_value) }}</div>
      <div class="lbl">Value</div>
    </div>
    <div class="metric">
      <div class="val {{ 'pos' if p.unrealized_pnl >= 0 else 'neg' }}">${{ "{:+,.0f}".format(p.unrealized_pnl) }}</div>
      <div class="lbl">P&amp;L</div>
    </div>
    <div class="metric">
      <div class="val neu">{{ "{:.1f}%".format(p.cur_price * 100) }}</div>
      <div class="lbl">Price</div>
    </div>
    <div class="metric">
      <div class="val neu">{{ "{:,.0f}".format(p.size) }}</div>
      <div class="lbl">Shares</div>
    </div>
  </div>
  <div class="price-bar"><div class="price-fill" style="width:{{ (p.cur_price*100)|int }}%"></div></div>
</div>
{% else %}
<div class="empty" style="grid-column:1/-1">Loading positions… refresh in a moment.</div>
{% endfor %}
</div>

<script>
let activeCat = "";
let sortMode = 0;
const sortModes = ["Value ↓", "P&L ↓", "Price ↓", "Rank ↑"];
const sortKeys  = ["value",   "pnl",   "price",  "rank"];
const sortDir   = [-1,        -1,       -1,        1];

function filterCards() {
  const q = document.getElementById("search").value.toLowerCase();
  const grid = document.getElementById("card-grid");
  let count = 0, totalValue = 0, totalPnl = 0;
  for (const card of grid.querySelectorAll(".card")) {
    const catOk = !activeCat || card.dataset.cat === activeCat;
    const qOk   = !q || card.dataset.title.includes(q) || card.dataset.wallet.includes(q);
    const show  = catOk && qOk;
    card.style.display = show ? "" : "none";
    if (show) {
      count++;
      totalValue += parseFloat(card.dataset.value) || 0;
      totalPnl   += parseFloat(card.dataset.pnl) || 0;
    }
  }
  document.getElementById("s-count").textContent = count;
  document.getElementById("s-value").textContent = "$" + totalValue.toLocaleString(undefined, {maximumFractionDigits:0});
  const pnlEl = document.getElementById("s-pnl");
  pnlEl.textContent = "$" + (totalPnl >= 0 ? "+" : "") + totalPnl.toLocaleString(undefined, {maximumFractionDigits:0});
  pnlEl.className = totalPnl >= 0 ? "pos" : "neg";
  sortCards();
}

function setTab(el, cat) {
  activeCat = cat;
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  el.classList.add("active");
  filterCards();
}

function cycleSort() {
  sortMode = (sortMode + 1) % sortModes.length;
  document.getElementById("sort-lbl").textContent = sortModes[sortMode];
  sortCards();
}

function sortCards() {
  const grid = document.getElementById("card-grid");
  const cards = Array.from(grid.querySelectorAll(".card:not([style*='display: none'])"));
  const key = sortKeys[sortMode];
  const dir = sortDir[sortMode];
  cards.sort((a, b) => dir * ((parseFloat(a.dataset[key]) || 0) - (parseFloat(b.dataset[key]) || 0)));
  cards.forEach(c => grid.appendChild(c));
}

setTimeout(() => location.reload(), {{ refresh_interval }} * 1000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    with _lock:
        positions = list(_cache.get("data") or [])
        last_updated = _cache.get("last_updated")
        wallets = list(_cache.get("wallets") or [])

    categories = sorted({p["category"] for p in positions})
    total_value = sum(p["cur_value"] for p in positions)
    total_pnl = sum(p["unrealized_pnl"] for p in positions)

    return render_template_string(
        TEMPLATE,
        positions=sorted(positions, key=lambda x: x["cur_value"], reverse=True),
        wallets=wallets,
        categories=categories,
        total_value=total_value,
        total_pnl=total_pnl,
        last_updated=last_updated,
        refresh_interval=REFRESH_INTERVAL,
    )


@app.route("/api/positions")
def api_positions():
    with _lock:
        data = _cache.get("data") or []
    from flask import jsonify
    return jsonify(data)


@app.route("/api/wallets")
def api_wallets():
    with _lock:
        wallets = _cache.get("wallets") or []
    from flask import jsonify
    return jsonify(wallets)


# ── Startup ──────────────────────────────────────────────────────────────────

def load_wallets() -> list[dict]:
    if WALLETS_FILE.exists():
        return json.loads(WALLETS_FILE.read_text())
    print(f"WARNING: {WALLETS_FILE} not found. Run `python ingest_top_wallets.py` first.")
    return []


if __name__ == "__main__":
    wallets = load_wallets()
    with _lock:
        _cache["wallets"] = wallets

    print(f"Loaded {len(wallets)} wallets from {WALLETS_FILE}")
    print("Starting background refresh thread...")

    t = threading.Thread(target=refresh_loop, daemon=True)
    t.start()

    # Do an immediate first load before serving
    print("Fetching initial positions (this may take a minute)...")
    try:
        refresh_all()
    except Exception as e:
        print(f"Initial refresh error: {e}")

    print("Dashboard ready: http://localhost:5000")
    app.run(debug=False, host="0.0.0.0", port=5000)
