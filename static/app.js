const state = {
  positions: [],
  trades: [],
  wallets: [],
  unitAnalysis: [],
  consensus: [],
  status: null,
  loading: false,
  autoRefreshPaused: false,
  selectedTradeKey: null,
  lastDashboardCheck: null,
};

const AUTO_REFRESH_MS = 15000;

const filterIds = [
  "search-input",
  "wallet-filter",
  "sport-filter",
  "league-filter",
  "min-position",
  "min-units",
  "min-pnl",
  "resolution-filter",
  "event-filter",
  "consensus-filter",
];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function formatMoney(value) {
  return Number(value || 0).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
}

function formatPercent(value) {
  return `${Number(value || 0).toFixed(2)}%`;
}

function formatDate(value) {
  if (!value) return "n/a";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function formatShortDate(value) {
  if (!value) return "n/a";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatConviction(position) {
  if (position.position_conviction_status === "neutral") {
    return "Neutral";
  }
  return String(position.position_conviction ?? "n/a");
}

function valueClass(value) {
  const numeric = Number(value || 0);
  if (numeric > 0) return "positive";
  if (numeric < 0) return "negative";
  return "";
}

function initials(label) {
  const words = String(label || "W").trim().split(/\s+/).filter(Boolean);
  return words.slice(0, 2).map((word) => word[0]).join("").toUpperCase() || "W";
}

function icon(name) {
  const icons = {
    wallets: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 8.5A2.5 2.5 0 0 1 5.5 6H18a3 3 0 0 1 3 3v8.5A2.5 2.5 0 0 1 18.5 20h-13A2.5 2.5 0 0 1 3 17.5v-9Z"/><path d="M17 12h4v4h-4a2 2 0 0 1 0-4Z"/></svg>',
    positions: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19V5"/><path d="M4 19h16"/><path d="m7 15 4-4 3 3 5-7"/></svg>',
    value: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2v20"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7H14a3.5 3.5 0 0 1 0 7H6"/></svg>',
    pnl: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 17 9 11l4 4 8-8"/><path d="M14 7h7v7"/></svg>',
    trades: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7h14l-4-4"/><path d="M17 17H3l4 4"/></svg>',
    exits: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/></svg>',
    consensus: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    status: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>',
  };
  return icons[name] || icons.status;
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

function syncFilter(selectId, values) {
  const select = document.getElementById(selectId);
  const current = select.value;
  const options = ['<option value="">All</option>'].concat(values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`));
  select.innerHTML = options.join("");
  if (values.includes(current)) {
    select.value = current;
  }
}

function setStatusDots(status) {
  const normalized = String(status || "idle").toLowerCase();
  ["api-status-dot", "hero-api-dot"].forEach((id) => {
    const dot = document.getElementById(id);
    if (!dot) return;
    dot.className = `status-dot ${normalized}`;
  });
}

function renderOverview() {
  const overview = state.status?.overview || {};
  const cards = [
    ["Enabled Wallets", overview.enabled_wallets ?? 0, "wallets"],
    ["Open Sports Positions", overview.open_sports_positions ?? 0, "positions"],
    ["Current Position Value", formatMoney(overview.total_current_position_value ?? 0), "value"],
    ["Unrealized P&L", formatMoney(overview.total_unrealized_pnl ?? 0), "pnl", valueClass(overview.total_unrealized_pnl)],
    ["New Trades (24h)", overview.new_trades_last_24h ?? 0, "trades"],
    ["Exits (24h)", overview.exits_last_24h ?? 0, "exits"],
    ["Consensus Markets", overview.markets_with_consensus ?? 0, "consensus"],
    ["API Status", overview.api_status ?? "idle", "status", String(overview.api_status).toLowerCase() === "ok" ? "status-ok" : ""],
  ];

  document.getElementById("overview-grid").innerHTML = cards
    .map(([label, value, iconName, cls]) => `
      <article class="metric-card">
        <div class="metric-head">
          <span class="metric-label">${escapeHtml(label)}</span>
          <span class="metric-icon">${icon(iconName)}</span>
        </div>
        <strong class="metric-value ${cls || ""}">${escapeHtml(value)}</strong>
      </article>
    `)
    .join("");
}

function recentTradeMapByPosition() {
  const map = new Map();
  state.trades.forEach((trade) => {
    const key = `${trade.wallet_address}::${trade.position_key}`;
    if (!map.has(key)) {
      map.set(key, trade.event_type);
    }
  });
  return map;
}

function activeFilterCount() {
  return filterIds.reduce((count, id) => {
    const element = document.getElementById(id);
    return count + (element && element.value ? 1 : 0);
  }, 0);
}

function updateActiveFilterCount() {
  const count = activeFilterCount();
  document.getElementById("active-filter-count").textContent = `${count} active`;
  document.querySelectorAll(".quick-filter").forEach((button) => {
    const action = button.dataset.quickFilter;
    const isActive = (
      (action === "clear" && count === 0) ||
      (action === "consensus" && document.getElementById("consensus-filter").value === "yes") ||
      (action === "large" && document.getElementById("min-position").value === "1000") ||
      (action === "profitable" && document.getElementById("min-pnl").value === "1")
    );
    button.classList.toggle("active", isActive);
  });
}

function filteredPositions() {
  const search = document.getElementById("search-input").value.trim().toLowerCase();
  const wallet = document.getElementById("wallet-filter").value;
  const sport = document.getElementById("sport-filter").value;
  const league = document.getElementById("league-filter").value;
  const minPosition = Number(document.getElementById("min-position").value || 0);
  const minUnits = Number(document.getElementById("min-units").value || 0);
  const minPnl = Number(document.getElementById("min-pnl").value || 0);
  const resolutionDate = document.getElementById("resolution-filter").value;
  const eventFilter = document.getElementById("event-filter").value;
  const consensusOnly = document.getElementById("consensus-filter").value === "yes";
  const tradeMap = recentTradeMapByPosition();

  return state.positions.filter((position) => {
    const haystack = `${position.wallet_label} ${position.market_title} ${position.outcome}`.toLowerCase();
    if (search && !haystack.includes(search)) return false;
    if (wallet && position.wallet_label !== wallet) return false;
    if (sport && position.category !== sport) return false;
    if (league && position.league !== league) return false;
    if (Number(position.position_size_usd || 0) < minPosition) return false;
    if (Number(position.estimated_units || 0) < minUnits) return false;
    if (Number(position.unrealized_pnl || 0) < minPnl) return false;
    if (resolutionDate && String(position.resolution_time || "").slice(0, 10) > resolutionDate) return false;
    if (consensusOnly && Number(position.tracked_wallets_same_side || 0) < 2) return false;
    if (eventFilter && tradeMap.get(`${position.wallet_address}::${position.position_key}`) !== eventFilter) return false;
    return true;
  });
}

function convictionTitle(position) {
  const breakdown = position.position_conviction_breakdown || {};
  if (position.position_conviction_status === "neutral") {
    return breakdown.reason || "Not enough verified data";
  }
  return [
    `Size ${breakdown.size_component || 0}`,
    `Portfolio ${breakdown.portfolio_component || 0}`,
    `Consensus ${breakdown.consensus_component || 0}`,
    `Increases ${breakdown.increase_component || 0}`,
    `Price ${breakdown.price_component || 0}`,
    `Time ${breakdown.time_component || 0}`,
    `Sport focus ${breakdown.sport_focus_component || 0}`,
  ].join(", ");
}

function detailsGrid(position) {
  const pnlPct = position.position_size_usd ? ((position.unrealized_pnl / position.position_size_usd) * 100) : 0;
  const rows = [
    ["Wallet address", position.wallet_short_address || position.wallet_address],
    ["Average entry odds", position.average_entry_odds],
    ["American odds", position.current_odds],
    ["Unrealized %", formatPercent(pnlPct)],
    ["First detected", formatDate(position.first_detected_at)],
    ["Last updated", formatDate(position.last_seen_at)],
    ["Tracked wallets same side", position.tracked_wallets_same_side],
    ["Position conviction", formatConviction(position)],
  ];
  return rows.map(([label, value]) => `<div class="detail-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
}

function renderPositions() {
  const positions = filteredPositions();
  const tbody = document.querySelector("#positions-table tbody");
  const mobile = document.getElementById("mobile-positions");
  document.getElementById("positions-count").textContent = `${positions.length} positions`;
  updateActiveFilterCount();

  if (!positions.length) {
    tbody.innerHTML = '<tr><td class="empty-row" colspan="19">No live positions match the current filters.</td></tr>';
    mobile.innerHTML = '<div class="empty-panel">No live positions match the current filters.</div>';
    return;
  }

  tbody.innerHTML = positions
    .map((position, index) => {
      const pnlClass = valueClass(position.unrealized_pnl);
      const pnlPct = position.position_size_usd ? ((position.unrealized_pnl / position.position_size_usd) * 100) : 0;
      const detailsId = `position-details-${index}`;
      return `
        <tr>
          <td>
            <div class="wallet-cell">
              <span class="avatar">${escapeHtml(initials(position.wallet_label))}</span>
              <span>
                <span class="wallet-name">${escapeHtml(position.wallet_label)}</span>
                <span class="wallet-address">${escapeHtml(position.wallet_short_address)}</span>
              </span>
            </div>
          </td>
          <td><span class="pill sport-pill">${escapeHtml(position.category)}</span></td>
          <td><span class="pill">${escapeHtml(position.league)}</span></td>
          <td class="market-cell"><span class="market-title" tabindex="0" title="${escapeHtml(position.market_title)}">${escapeHtml(position.market_title)}</span></td>
          <td><span class="outcome-badge">${escapeHtml(position.outcome)}</span></td>
          <td>${formatMoney(position.position_size_usd)}</td>
          <td>${escapeHtml(position.estimated_units ?? "n/a")}<span class="cell-sub">${escapeHtml(position.estimated_base_unit_label || "")}</span></td>
          <td>${Number(position.average_entry_price_cents || 0).toFixed(1)}c</td>
          <td>${Number(position.current_price_cents || 0).toFixed(1)}c</td>
          <td>${escapeHtml(position.current_odds)}</td>
          <td>${formatMoney(position.current_value)}</td>
          <td class="${pnlClass}">${formatMoney(position.unrealized_pnl)}</td>
          <td class="${pnlClass}">${formatPercent(pnlPct)}</td>
          <td>${escapeHtml(formatShortDate(position.resolution_time))}</td>
          <td>${escapeHtml(formatDate(position.first_detected_at))}</td>
          <td>${escapeHtml(formatDate(position.last_seen_at))}</td>
          <td>${escapeHtml(position.tracked_wallets_same_side)}</td>
          <td title="${escapeHtml(convictionTitle(position))}">
            <button class="text-button subtle row-toggle" type="button" aria-expanded="false" aria-controls="${detailsId}" data-target="${detailsId}">
              ${escapeHtml(formatConviction(position))}
            </button>
          </td>
          <td>
            <a href="${escapeHtml(position.market_url)}" target="_blank" rel="noreferrer">Market</a><br>
            <a href="${escapeHtml(position.wallet_profile_url)}" target="_blank" rel="noreferrer">Profile</a>
          </td>
        </tr>
        <tr class="row-details" id="${detailsId}" hidden>
          <td colspan="19"><div class="details-grid">${detailsGrid(position)}</div></td>
        </tr>
      `;
    })
    .join("");

  mobile.innerHTML = positions
    .map((position) => {
      const pnlClass = valueClass(position.unrealized_pnl);
      return `
        <details class="position-card">
          <summary>
            <span>
              <span class="wallet-cell">
                <span class="avatar">${escapeHtml(initials(position.wallet_label))}</span>
                <span>
                  <span class="wallet-name">${escapeHtml(position.wallet_label)}</span>
                  <span class="wallet-address">${escapeHtml(position.category)} / ${escapeHtml(position.league)}</span>
                </span>
              </span>
              <span class="market-title" title="${escapeHtml(position.market_title)}">${escapeHtml(position.market_title)}</span>
            </span>
            <span class="outcome-badge">${escapeHtml(position.outcome)}</span>
          </summary>
          <div class="mobile-card-metrics">
            <div class="card-metric"><span>Position size</span><strong>${formatMoney(position.position_size_usd)}</strong></div>
            <div class="card-metric"><span>Estimated units</span><strong>${escapeHtml(position.estimated_units ?? "n/a")}</strong></div>
            <div class="card-metric"><span>Current value</span><strong>${formatMoney(position.current_value)}</strong></div>
            <div class="card-metric"><span>Unrealized P&L</span><strong class="${pnlClass}">${formatMoney(position.unrealized_pnl)}</strong></div>
            <div class="card-metric"><span>Current odds</span><strong>${escapeHtml(position.current_odds)}</strong></div>
            <div class="card-metric"><span>Resolution</span><strong>${escapeHtml(formatShortDate(position.resolution_time))}</strong></div>
          </div>
          <div class="card-detail-grid">${detailsGrid(position)}</div>
        </details>
      `;
    })
    .join("");
}

function eventBadge(eventType) {
  const labels = {
    new_entry: ["New Entry", "new-entry"],
    size_increase: ["Increased", "increased"],
    size_decrease: ["Decreased", "decreased"],
    full_exit: ["Exit", "exit"],
    price_change: ["Price Change", "price-change"],
    avg_price_change: ["Avg Price", "price-change"],
    current_value_change: ["Value Change", "price-change"],
    unrealized_pnl_change: ["P&L Change", "price-change"],
  };
  const [label, cls] = labels[eventType] || [eventType || "Event", "price-change"];
  return `<span class="event-badge ${cls}">${escapeHtml(label)}</span>`;
}

function tradeEventLabel(eventType) {
  const labels = {
    new_entry: "New Entry",
    size_increase: "Increased",
    size_decrease: "Decreased",
    full_exit: "Exit",
    price_change: "Price Change",
    avg_price_change: "Avg Price",
    current_value_change: "Value Change",
    unrealized_pnl_change: "P&L Change",
  };
  return labels[eventType] || eventType || "Event";
}

function numberOrNull(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatCentsFromProbability(value) {
  const numeric = numberOrNull(value);
  if (numeric === null || numeric <= 0) return "n/a";
  return `${(numeric * 100).toFixed(1)}c`;
}

function tradeKey(trade, index) {
  return trade.event_hash || `${trade.wallet_address || "wallet"}::${trade.position_key || "position"}::${trade.detected_at || index}`;
}

function tradeSnapshot(trade) {
  return trade.current || trade;
}

function unitEntryForTrade(trade) {
  const address = String(trade.wallet_address || "").toLowerCase();
  const label = String(trade.wallet_label || "").toLowerCase();
  return state.unitAnalysis.find((entry) => (
    String(entry.wallet_address || "").toLowerCase() === address ||
    String(entry.wallet_label || "").toLowerCase() === label
  ));
}

function tradeSizeUsd(trade) {
  const snapshot = tradeSnapshot(trade);
  return numberOrNull(snapshot.position_size_usd) ?? numberOrNull(trade.position_size_usd) ?? 0;
}

function relativeBetSize(trade) {
  const snapshot = tradeSnapshot(trade);
  const directUnits = numberOrNull(snapshot.estimated_units);
  const unitEntry = unitEntryForTrade(trade);
  const baseUnit = numberOrNull(unitEntry?.estimated_base_unit);
  const sizeUsd = tradeSizeUsd(trade);
  const units = directUnits ?? (baseUnit && baseUnit > 0 ? sizeUsd / baseUnit : null);

  if (units === null) {
    return {
      value: "n/a",
      subtext: "Unit stats pending",
    };
  }

  const decimals = Math.abs(units) >= 10 ? 1 : 2;
  return {
    value: `${units.toFixed(decimals)}u`,
    subtext: baseUnit ? `${formatMoney(baseUnit)} unit` : "Estimated units",
  };
}

function slippageForTrade(trade) {
  const snapshot = tradeSnapshot(trade);
  const averageEntry = numberOrNull(snapshot.average_entry_price) ?? numberOrNull(trade.average_entry_price);
  const currentPrice = numberOrNull(snapshot.current_price) ?? numberOrNull(trade.current_price);

  if (!averageEntry || !currentPrice) {
    return {
      value: "n/a",
      className: "",
      note: "Needs entry and current price",
    };
  }

  const centsDelta = (currentPrice - averageEntry) * 100;
  const className = centsDelta < 0 ? "good" : centsDelta > 0 ? "bad" : "flat";
  const note = centsDelta < 0
    ? "Better price than entry"
    : centsDelta > 0
      ? "Worse price than entry"
      : "Same as entry";

  return {
    value: `${centsDelta >= 0 ? "+" : ""}${centsDelta.toFixed(1)}c`,
    className,
    note,
  };
}

function tradePriceTrackStyle(trade) {
  const snapshot = tradeSnapshot(trade);
  const averageEntry = numberOrNull(snapshot.average_entry_price) ?? numberOrNull(trade.average_entry_price) ?? 0;
  const currentPrice = numberOrNull(snapshot.current_price) ?? numberOrNull(trade.current_price) ?? 0;
  const entryPct = Math.max(4, Math.min(96, averageEntry * 100));
  const currentPct = Math.max(4, Math.min(96, currentPrice * 100));
  return `--entry-pct: ${entryPct}%; --current-pct: ${currentPct}%;`;
}

function tradeMetric(label, value, subtext, cls = "") {
  return `
    <div class="trade-detail-metric ${cls}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      ${subtext ? `<small>${escapeHtml(subtext)}</small>` : ""}
    </div>
  `;
}

function renderTradeCard(trade, index, selectedKey) {
  const key = tradeKey(trade, index);
  const snapshot = tradeSnapshot(trade);
  const selected = key === selectedKey;
  const relative = relativeBetSize(trade);
  const slippage = slippageForTrade(trade);
  const conviction = formatConviction(snapshot);
  const shares = numberOrNull(snapshot.shares) ?? numberOrNull(snapshot.token_units);
  const price = numberOrNull(snapshot.current_price) ?? numberOrNull(trade.current_price);

  return `
    <button class="trade-card ${selected ? "selected" : ""}" type="button" data-trade-key="${escapeHtml(key)}" aria-pressed="${selected}">
      <div class="trade-card-rank">${escapeHtml(conviction === "n/a" ? String(index + 1).padStart(2, "0") : conviction)}</div>
      <div class="trade-card-main">
        <div class="trade-card-meta">
          <span>${escapeHtml(formatShortDate(snapshot.resolution_time || trade.detected_at))}</span>
          <span>${escapeHtml(relative.value)}</span>
          <span class="slippage ${slippage.className}">${escapeHtml(slippage.value)}</span>
          <span>Current: ${escapeHtml(formatCentsFromProbability(price))}</span>
        </div>
        <div class="trade-card-title" title="${escapeHtml(trade.market_title)}">${escapeHtml(trade.market_title)}</div>
        <div class="trade-card-subtitle">${escapeHtml(trade.wallet_label)} / ${escapeHtml(trade.category || "Market")} / ${escapeHtml(tradeEventLabel(trade.event_type))}</div>
      </div>
      <div class="trade-card-pick">
        <span>${escapeHtml(trade.outcome || "Outcome")}</span>
        <strong>${shares ? `${shares.toFixed(shares >= 100 ? 0 : 2)} shares` : formatMoney(tradeSizeUsd(trade))}</strong>
        <small>${escapeHtml(formatCentsFromProbability(price))}</small>
      </div>
    </button>
  `;
}

function renderTradeDetail(trade) {
  if (!trade) {
    return '<div class="empty-panel">Select a recent trade to inspect the play.</div>';
  }

  const snapshot = tradeSnapshot(trade);
  const relative = relativeBetSize(trade);
  const slippage = slippageForTrade(trade);
  const averageEntry = numberOrNull(snapshot.average_entry_price) ?? numberOrNull(trade.average_entry_price);
  const currentPrice = numberOrNull(snapshot.current_price) ?? numberOrNull(trade.current_price);
  const shares = numberOrNull(snapshot.shares) ?? numberOrNull(snapshot.token_units);
  const pnl = (numberOrNull(snapshot.unrealized_pnl) ?? numberOrNull(trade.unrealized_pnl) ?? 0) + (numberOrNull(trade.realized_pnl) ?? 0);
  const sizeUsd = tradeSizeUsd(trade);
  const profileUrl = snapshot.wallet_profile_url || trade.wallet_profile_url;
  const marketUrl = snapshot.market_url || trade.market_url;

  return `
    <div class="trade-detail-header">
      <div>
        <p class="trade-detail-score">${escapeHtml(formatConviction(snapshot))}</p>
        <h3 title="${escapeHtml(trade.market_title)}">${escapeHtml(trade.market_title)}</h3>
        <span>${escapeHtml(trade.category || "Market")} / ${escapeHtml(trade.league || "League")}</span>
      </div>
      ${eventBadge(trade.event_type)}
    </div>

    <div class="trade-detail-pick">
      <div>
        <span>Trader</span>
        <strong>${escapeHtml(trade.wallet_label || "Tracked wallet")}</strong>
      </div>
      <div>
        <span>Pick</span>
        <strong>${escapeHtml(trade.outcome || "Outcome")}</strong>
      </div>
      <div>
        <span>Bet Size</span>
        <strong>${formatMoney(sizeUsd)}</strong>
        ${shares ? `<small>${escapeHtml(shares.toFixed(shares >= 100 ? 0 : 2))} shares</small>` : ""}
      </div>
      <div>
        <span>Current</span>
        <strong>${escapeHtml(formatCentsFromProbability(currentPrice))}</strong>
      </div>
    </div>

    <div class="trade-detail-metrics">
      ${tradeMetric("Rel. Bet Size", relative.value, relative.subtext)}
      ${tradeMetric("Bet Size", formatMoney(sizeUsd), "Position amount")}
      ${tradeMetric("Slippage", slippage.value, slippage.note, `slippage ${slippage.className}`)}
    </div>

    <div class="trade-stats-grid">
      ${tradeMetric("Trader", trade.wallet_label || "Tracked wallet", "Name shown in wallets.json")}
      ${tradeMetric("Top Category", trade.category || "n/a", "Placeholder until stats are added")}
      ${tradeMetric("Trader ROI", "Coming soon", "Add when you send stats")}
      ${tradeMetric("Trades", "Coming soon", "Add when you send stats")}
    </div>

    <div class="price-card">
      <div class="price-card-head">
        <strong>Price</strong>
        <span>Entry ${escapeHtml(formatCentsFromProbability(averageEntry))} / Current ${escapeHtml(formatCentsFromProbability(currentPrice))}</span>
      </div>
      <div class="price-track" style="${escapeHtml(tradePriceTrackStyle(trade))}">
        <span class="entry-marker">Entry</span>
        <span class="current-marker">Current</span>
      </div>
      <p>Negative slippage means the current price is below the trader's entry, so following now is cheaper. Positive slippage means the current price is higher than entry.</p>
    </div>

    <div class="trade-detail-footer">
      <span>Detected ${escapeHtml(formatDate(trade.detected_at))}</span>
      <span class="${valueClass(pnl)}">P&L ${formatMoney(pnl)}</span>
      <span>Value ${formatMoney(numberOrNull(snapshot.current_value) ?? numberOrNull(trade.current_value) ?? 0)}</span>
      ${marketUrl ? `<a href="${escapeHtml(marketUrl)}" target="_blank" rel="noreferrer">Open Market</a>` : ""}
      ${profileUrl ? `<a href="${escapeHtml(profileUrl)}" target="_blank" rel="noreferrer">Trader Profile</a>` : ""}
    </div>
  `;
}

function renderTrades() {
  const trades = state.trades.slice(0, 100);
  const tradeKeys = trades.map((trade, index) => tradeKey(trade, index));
  if (!tradeKeys.includes(state.selectedTradeKey)) {
    state.selectedTradeKey = tradeKeys[0] || null;
  }

  const selectedTrade = trades.find((trade, index) => tradeKey(trade, index) === state.selectedTradeKey);
  const countBadge = document.getElementById("trades-count-badge");
  if (countBadge) countBadge.textContent = trades.length;

  document.querySelector("#trades-table tbody").innerHTML = trades.length
    ? trades.map((trade) => `
      <tr>
        <td>${escapeHtml(formatDate(trade.detected_at))}</td>
        <td>${escapeHtml(trade.wallet_label)}</td>
        <td>${eventBadge(trade.event_type)}</td>
        <td class="market-cell"><span class="market-title" title="${escapeHtml(trade.market_title)}">${escapeHtml(trade.market_title)}</span></td>
        <td>${escapeHtml(trade.outcome)}</td>
        <td>${formatMoney(trade.current_value)}</td>
        <td class="${valueClass((trade.unrealized_pnl || 0) + (trade.realized_pnl || 0))}">${formatMoney((trade.unrealized_pnl || 0) + (trade.realized_pnl || 0))}</td>
      </tr>
    `).join("")
    : '<tr><td class="empty-row" colspan="7">No recent trades detected yet.</td></tr>';

  document.getElementById("trades-feed").innerHTML = trades.length
    ? trades.map((trade, index) => renderTradeCard(trade, index, state.selectedTradeKey)).join("")
    : '<div class="empty-panel">No recent trades detected yet.</div>';

  const detailPanel = document.getElementById("trade-detail-panel");
  if (detailPanel) detailPanel.innerHTML = renderTradeDetail(selectedTrade);
}

function statusClass(status) {
  if (status === "invalid") return "pill invalid";
  if (status === "disabled") return "pill disabled";
  if (status === "enabled") return "pill enabled";
  return "pill";
}

function renderWallets() {
  document.querySelector("#wallets-table tbody").innerHTML = state.wallets.length
    ? state.wallets.map((wallet) => {
      const baseUnit = wallet.base_unit ? formatMoney(wallet.base_unit) : "n/a";
      return `
        <tr>
          <td>${escapeHtml(wallet.label)}</td>
          <td>${escapeHtml(wallet.address || "n/a")}</td>
          <td><span class="${statusClass(wallet.status)}">${escapeHtml(wallet.status)}</span>${wallet.message ? `<br><span class="status-label">${escapeHtml(wallet.message)}</span>` : ""}</td>
          <td>${escapeHtml(baseUnit)}</td>
          <td>${escapeHtml(wallet.notes || "")}</td>
        </tr>
      `;
    }).join("")
    : '<tr><td class="empty-row" colspan="5">No wallets found in wallets.json.</td></tr>';

  document.getElementById("wallet-cards").innerHTML = state.wallets.length
    ? state.wallets.map((wallet) => {
      const address = wallet.address || "n/a";
      const baseUnit = wallet.base_unit ? formatMoney(wallet.base_unit) : "n/a";
      return `
        <article class="wallet-card ${wallet.status === "invalid" ? "invalid" : ""}">
          <div>
            <div class="wallet-cell">
              <span class="avatar">${escapeHtml(initials(wallet.label))}</span>
              <span>
                <span class="wallet-name">${escapeHtml(wallet.label)}</span>
                <span class="address-line">
                  <span>${escapeHtml(wallet.short_address || address)}</span>
                  <button class="copy-button" type="button" data-address="${escapeHtml(address)}" ${address === "n/a" ? "disabled" : ""}>Copy</button>
                </span>
              </span>
            </div>
            ${wallet.message ? `<p class="warning">${escapeHtml(wallet.message)}</p>` : ""}
            ${wallet.notes ? `<p class="muted">${escapeHtml(wallet.notes)}</p>` : ""}
          </div>
          <div>
            <span class="${statusClass(wallet.status)}">${escapeHtml(wallet.status)}</span>
            <span class="cell-sub">Base unit ${escapeHtml(baseUnit)}</span>
          </div>
        </article>
      `;
    }).join("")
    : '<div class="empty-panel">No wallets found in wallets.json.</div>';
}

function renderUnitAnalysis() {
  document.querySelector("#unit-table tbody").innerHTML = state.unitAnalysis.length
    ? state.unitAnalysis.map((entry) => `
      <tr>
        <td>${escapeHtml(entry.wallet_label)}</td>
        <td>${escapeHtml(entry.estimated_base_unit_label)}</td>
        <td><span class="pill">${escapeHtml(entry.confidence)}</span></td>
        <td>${escapeHtml(entry.sample_size)}</td>
        <td>${escapeHtml(entry.matched_samples)}</td>
        <td>${escapeHtml(entry.source)}</td>
        <td>${escapeHtml(entry.notes)}</td>
      </tr>
    `).join("")
    : '<tr><td class="empty-row" colspan="7">Insufficient wallet data for unit-size analysis.</td></tr>';
}

function renderConsensus() {
  document.querySelector("#consensus-table tbody").innerHTML = state.consensus.length
    ? state.consensus.map((entry) => `
      <tr>
        <td class="market-cell"><a class="market-title" href="${escapeHtml(entry.market_url)}" target="_blank" rel="noreferrer" title="${escapeHtml(entry.market_title)}">${escapeHtml(entry.market_title)}</a></td>
        <td><span class="outcome-badge">${escapeHtml(entry.outcome)}</span></td>
        <td>${escapeHtml(entry.wallet_count)}<span class="cell-sub">${escapeHtml(entry.wallet_names.join(", "))}</span></td>
        <td>${formatMoney(entry.combined_position_value)}</td>
        <td>${escapeHtml(entry.combined_estimated_units)}</td>
        <td>${escapeHtml(entry.largest_holder)}</td>
        <td>${escapeHtml(formatDate(entry.earliest_entry_time))}</td>
        <td>${escapeHtml(formatDate(entry.most_recent_increase))}</td>
      </tr>
    `).join("")
    : '<tr><td class="empty-row" colspan="8">No same-side consensus positions detected.</td></tr>';
}

function renderHistory() {
  const rows = state.trades.slice(0, 150);
  document.querySelector("#history-table tbody").innerHTML = rows.length
    ? rows.map((trade) => `
      <tr>
        <td>${escapeHtml(formatDate(trade.detected_at))}</td>
        <td>${eventBadge(trade.event_type)}</td>
        <td>${escapeHtml(trade.wallet_label)}</td>
        <td class="market-cell"><span class="market-title" title="${escapeHtml(trade.market_title)}">${escapeHtml(trade.market_title)}</span></td>
        <td>${escapeHtml(trade.outcome)}</td>
        <td>${escapeHtml(trade.category)}</td>
        <td>${formatMoney(trade.current_value)}</td>
      </tr>
    `).join("")
    : '<tr><td class="empty-row" colspan="7">No position history recorded yet.</td></tr>';
}

function renderSettings() {
  const status = state.status || {};
  const settings = [
    ["App status", status.app_status],
    ["API status", status.api_status],
    ["Enabled wallets", status.enabled_wallet_count],
    ["Valid wallets", status.valid_wallet_count],
    ["Invalid wallets", status.invalid_wallet_count],
    ["Last refresh attempt", formatDate(status.last_refresh_attempt)],
    ["Last successful refresh", formatDate(status.last_successful_refresh)],
    ["Database", status.database?.database_path || "n/a"],
  ];

  document.getElementById("settings-list").innerHTML = settings
    .map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`)
    .join("");
}

function toggleEmptyState() {
  const noEnabledWallets = (state.status?.enabled_wallet_count || 0) === 0;
  document.getElementById("empty-state").classList.toggle("hidden", !noEnabledWallets);
  document.getElementById("setup-guide").classList.toggle("hidden", !noEnabledWallets);
}

function syncSelectors() {
  syncFilter("wallet-filter", [...new Set(state.positions.map((position) => position.wallet_label))].sort());
  syncFilter("sport-filter", [...new Set(state.positions.map((position) => position.category))].sort());
  syncFilter("league-filter", [...new Set(state.positions.map((position) => position.league))].sort());
}

function renderStatusChrome(status) {
  const api = status.api_status || "idle";
  const lastCheck = formatDate(state.lastDashboardCheck);
  const dataRefresh = formatDate(status.last_successful_refresh);
  document.getElementById("api-status").textContent = api;
  document.getElementById("hero-api-status").textContent = `API ${api}`;
  document.getElementById("last-refresh").textContent = lastCheck;
  document.getElementById("hero-last-refresh").textContent = lastCheck;
  document.getElementById("last-data-refresh").textContent = dataRefresh;
  document.getElementById("hero-data-refresh").textContent = dataRefresh;
  document.getElementById("nav-enabled-wallets").textContent = status.enabled_wallet_count ?? 0;
  setStatusDots(api);
}

function renderAll() {
  renderStatusChrome(state.status || {});
  syncSelectors();
  renderOverview();
  renderPositions();
  renderTrades();
  renderWallets();
  renderUnitAnalysis();
  renderConsensus();
  renderHistory();
  renderSettings();
  toggleEmptyState();
}

async function loadDashboard() {
  if (state.loading) return;
  state.loading = true;
  document.body.classList.add("loading");
  try {
    const [positions, trades, wallets, unitAnalysis, consensus, status] = await Promise.all([
      fetchJson("/api/positions"),
      fetchJson("/api/trades"),
      fetchJson("/api/wallets"),
      fetchJson("/api/unit-analysis"),
      fetchJson("/api/consensus"),
      fetchJson("/api/status"),
    ]);

    state.positions = positions.data || [];
    state.trades = trades.data || [];
    state.wallets = wallets.data || [];
    state.unitAnalysis = unitAnalysis.data || [];
    state.consensus = consensus.data || [];
    state.status = status;
    state.lastDashboardCheck = new Date().toISOString();
    renderAll();
  } finally {
    state.loading = false;
    document.body.classList.remove("loading");
  }
}

function clearFilters() {
  filterIds.forEach((id) => {
    const element = document.getElementById(id);
    if (element) element.value = "";
  });
  renderPositions();
}

function updatePauseButton() {
  const button = document.getElementById("pause-refresh-button");
  button.setAttribute("aria-pressed", String(state.autoRefreshPaused));
  button.classList.toggle("paused", state.autoRefreshPaused);
  button.textContent = state.autoRefreshPaused ? "Resume Auto" : "Pause Auto";
  button.title = state.autoRefreshPaused ? "Resume automatic refresh" : "Pause automatic refresh";
}

function toggleAutoRefresh() {
  state.autoRefreshPaused = !state.autoRefreshPaused;
  updatePauseButton();
}

function applyQuickFilter(action) {
  clearFilters();

  if (action === "consensus") {
    document.getElementById("consensus-filter").value = "yes";
  }

  if (action === "large") {
    document.getElementById("min-position").value = "1000";
  }

  if (action === "profitable") {
    document.getElementById("min-pnl").value = "1";
  }

  renderPositions();
}

function bindInteractions() {
  filterIds.forEach((id) => {
    const element = document.getElementById(id);
    element.addEventListener("input", renderPositions);
    element.addEventListener("change", renderPositions);
  });

  document.getElementById("advanced-toggle").addEventListener("click", (event) => {
    const button = event.currentTarget;
    const panel = document.getElementById("advanced-filters");
    const expanded = button.getAttribute("aria-expanded") === "true";
    button.setAttribute("aria-expanded", String(!expanded));
    panel.hidden = expanded;
  });

  document.getElementById("clear-filters").addEventListener("click", clearFilters);
  document.getElementById("refresh-button").addEventListener("click", loadDashboard);
  document.getElementById("pause-refresh-button").addEventListener("click", toggleAutoRefresh);

  document.querySelectorAll(".quick-filter").forEach((button) => {
    button.addEventListener("click", () => applyQuickFilter(button.dataset.quickFilter));
  });

  document.addEventListener("click", async (event) => {
    const toggle = event.target.closest(".row-toggle");
    if (toggle) {
      const target = document.getElementById(toggle.dataset.target);
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!expanded));
      if (target) target.hidden = expanded;
    }

    const tradeCard = event.target.closest(".trade-card");
    if (tradeCard) {
      state.selectedTradeKey = tradeCard.dataset.tradeKey;
      renderTrades();
      return;
    }

    const copyButton = event.target.closest(".copy-button");
    if (copyButton && copyButton.dataset.address) {
      try {
        await navigator.clipboard.writeText(copyButton.dataset.address);
        copyButton.textContent = "Copied";
        setTimeout(() => {
          copyButton.textContent = "Copy";
        }, 1400);
      } catch (error) {
        copyButton.textContent = "Copy failed";
        setTimeout(() => {
          copyButton.textContent = "Copy";
        }, 1400);
      }
    }
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  bindInteractions();
  updatePauseButton();
  await loadDashboard();
  setInterval(() => {
    if (!state.autoRefreshPaused) {
      loadDashboard();
    }
  }, AUTO_REFRESH_MS);
});
