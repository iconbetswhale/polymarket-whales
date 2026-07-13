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
  tradePagination: null,
};

const AUTO_REFRESH_MS = 15000;
let tradeSearchTimer = null;

const filterIds = [
  "search-input",
  "wallet-filter",
  "sport-filter",
  "league-filter",
  "min-position",
  "min-units",
  "min-pnl",
  "date-range-filter",
  "custom-start-date",
  "custom-end-date",
  "sharps-filter",
  "sharps-filter-advanced",
  "min-confidence",
  "min-confidence-advanced",
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

function formatUnitsValue(value) {
  const numeric = numberOrNull(value);
  if (numeric === null) return "n/a";
  return `${numeric.toFixed(numeric >= 10 ? 2 : 3)}u`;
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

function formatClock(value) {
  if (!value) return "n/a";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" });
}

function timeAgo(value) {
  if (!value) return "n/a";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "n/a";
  const seconds = Math.max(0, Math.round((Date.now() - parsed.getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
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
    ["Trades to Play", state.trades.length, "trades"],
    ["Enabled Wallets", overview.enabled_wallets ?? 0, "wallets"],
    ["Open Sports Positions", overview.open_sports_positions ?? 0, "positions"],
    ["Current Position Value", formatMoney(overview.total_current_position_value ?? 0), "value"],
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
  const dateRangeMode = document.getElementById("date-range-filter").value;
  const countedIds = filterIds.filter((id) => !["sharps-filter-advanced", "min-confidence-advanced"].includes(id));
  return countedIds.reduce((count, id) => {
    const element = document.getElementById(id);
    if ((id === "custom-start-date" || id === "custom-end-date") && dateRangeMode !== "custom") {
      return count;
    }
    return count + (element && element.value ? 1 : 0);
  }, 0);
}

function updateActiveFilterCount() {
  const count = activeFilterCount();
  document.getElementById("active-filter-count").textContent = `${count} active`;
  const dateRange = document.getElementById("date-range-filter").value;
  document.querySelectorAll(".quick-filter").forEach((button) => {
    const action = button.dataset.quickFilter;
    const isActive = (
      (action === "clear" && count === 0) ||
      (action === "today" && dateRange === "today") ||
      (action === "tomorrow" && dateRange === "tomorrow") ||
      (action === "next24" && dateRange === "next24") ||
      (action === "next48" && dateRange === "next48") ||
      (action === "consensus" && document.getElementById("consensus-filter").value === "yes") ||
      (action === "large" && document.getElementById("min-position").value === "1000") ||
      (action === "profitable" && document.getElementById("min-pnl").value === "1")
    );
    button.classList.toggle("active", isActive);
  });
}

function startOfLocalDay(date) {
  const copy = new Date(date);
  copy.setHours(0, 0, 0, 0);
  return copy;
}

function addDays(date, days) {
  const copy = new Date(date);
  copy.setDate(copy.getDate() + days);
  return copy;
}

function dateInputToLocalDate(value, endOfDay = false) {
  if (!value) return null;
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return null;
  if (endOfDay) parsed.setHours(23, 59, 59, 999);
  return parsed;
}

function activeDateRange() {
  const mode = document.getElementById("date-range-filter").value;
  if (!mode) return null;

  const now = new Date();
  if (mode === "today") {
    return {
      start: startOfLocalDay(now),
      end: addDays(startOfLocalDay(now), 1),
      label: "today",
    };
  }

  if (mode === "tomorrow") {
    const tomorrow = addDays(startOfLocalDay(now), 1);
    return {
      start: tomorrow,
      end: addDays(tomorrow, 1),
      label: "tomorrow",
    };
  }

  if (mode === "next24") {
    return {
      start: now,
      end: new Date(now.getTime() + 24 * 60 * 60 * 1000),
      label: "next 24 hours",
    };
  }

  if (mode === "next48") {
    return {
      start: now,
      end: new Date(now.getTime() + 48 * 60 * 60 * 1000),
      label: "next 48 hours",
    };
  }

  if (mode === "week") {
    const end = startOfLocalDay(now);
    end.setDate(end.getDate() + (7 - end.getDay()));
    end.setHours(23, 59, 59, 999);
    return {
      start: now,
      end,
      label: "this week",
    };
  }

  if (mode === "custom") {
    return {
      start: dateInputToLocalDate(document.getElementById("custom-start-date").value),
      end: dateInputToLocalDate(document.getElementById("custom-end-date").value, true),
      label: "custom range",
    };
  }

  return null;
}

function resolutionDateForItem(item) {
  const snapshot = tradeSnapshot(item);
  const value = snapshot.resolution_time || item.resolution_time || item.event_date_et || item.endDate || "";
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function itemMatchesDateRange(item, range = activeDateRange()) {
  if (!range) return true;
  const resolution = resolutionDateForItem(item);
  if (!resolution) return false;
  if (range.start && resolution < range.start) return false;
  if (range.end && resolution > range.end) return false;
  return true;
}

function filteredPositions() {
  const search = document.getElementById("search-input").value.trim().toLowerCase();
  const wallet = document.getElementById("wallet-filter").value;
  const sport = document.getElementById("sport-filter").value;
  const league = document.getElementById("league-filter").value;
  const minPosition = Number(document.getElementById("min-position").value || 0);
  const minUnits = Number(document.getElementById("min-units").value || 0);
  const minPnl = Number(document.getElementById("min-pnl").value || 0);
  const dateRange = activeDateRange();
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
    if (!itemMatchesDateRange(position, dateRange)) return false;
    if (consensusOnly && Number(position.tracked_wallets_same_side || 0) < 2) return false;
    if (eventFilter && tradeMap.get(`${position.wallet_address}::${position.position_key}`) !== eventFilter) return false;
    return true;
  });
}

function filteredTrades() {
  return state.trades;
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

function renderFilteredViews() {
  renderPositions();
  renderTrades();
  updateCustomDateFields();
}

function pairedFilterValue(primaryId, secondaryId) {
  return document.getElementById(primaryId)?.value || document.getElementById(secondaryId)?.value || "";
}

function syncPairedFilters(sourceId) {
  const pairs = [
    ["sharps-filter", "sharps-filter-advanced"],
    ["min-confidence", "min-confidence-advanced"],
  ];
  pairs.forEach(([a, b]) => {
    if (sourceId !== a && sourceId !== b) return;
    const source = document.getElementById(sourceId);
    const target = document.getElementById(sourceId === a ? b : a);
    if (source && target) target.value = source.value;
  });
}

function tradeFilterQuery() {
  const params = new URLSearchParams();
  const search = document.getElementById("search-input")?.value.trim();
  const minSharps = pairedFilterValue("sharps-filter", "sharps-filter-advanced");
  const minConfidence = pairedFilterValue("min-confidence", "min-confidence-advanced");
  const mappings = [
    ["q", search],
    ["wallet", document.getElementById("wallet-filter")?.value],
    ["sport", document.getElementById("sport-filter")?.value],
    ["league", document.getElementById("league-filter")?.value],
    ["date_range", document.getElementById("date-range-filter")?.value],
    ["custom_start", document.getElementById("custom-start-date")?.value],
    ["custom_end", document.getElementById("custom-end-date")?.value],
    ["min_sharps", minSharps],
    ["min_confidence", minConfidence],
    ["per_page", "100"],
  ];
  mappings.forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  if (document.getElementById("consensus-filter")?.value === "yes" && !params.get("min_sharps")) {
    params.set("min_sharps", "2");
  }
  return params.toString();
}

async function loadTradesToPlay() {
  const query = tradeFilterQuery();
  const response = await fetchJson(`/api/trades-to-play${query ? `?${query}` : ""}`);
  state.trades = response.data || [];
  state.tradePagination = response.pagination || null;
  if (response.status) state.status = response.status;
  renderOverview();
  renderTrades();
}

function scheduleTradeRefresh(delay = 250) {
  window.clearTimeout(tradeSearchTimer);
  tradeSearchTimer = window.setTimeout(() => {
    loadTradesToPlay().catch(() => renderTrades());
  }, delay);
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

function formatTakePriceFromProbability(value) {
  const numeric = numberOrNull(value);
  if (numeric === null || numeric <= 0 || numeric > 1) return "Unavailable";
  const cents = numeric * 100;
  const formatted = Math.abs(cents - Math.round(cents)) < 0.05 ? String(Math.round(cents)) : cents.toFixed(1);
  return `${formatted}\u00a2`;
}

function formatShares(value) {
  const numeric = numberOrNull(value);
  if (numeric === null) return "n/a";
  return `${numeric.toFixed(numeric >= 100 ? 0 : 2)} shares`;
}

function tradeKey(trade, index) {
  return trade.id || trade.event_hash || `${trade.wallet_address || "wallet"}::${trade.position_key || "position"}::${trade.detected_at || index}`;
}

function tradeSnapshot(trade) {
  return trade.current || trade;
}

function unitEntryForTrade(trade) {
  const address = String(trade.primary_trader?.wallet_address || trade.wallet_address || "").toLowerCase();
  const label = String(trade.primary_trader?.wallet_label || trade.wallet_label || "").toLowerCase();
  return state.unitAnalysis.find((entry) => (
    String(entry.wallet_address || "").toLowerCase() === address ||
    String(entry.wallet_label || "").toLowerCase() === label
  ));
}

function tradeSizeUsd(trade) {
  const snapshot = tradeSnapshot(trade);
  return numberOrNull(trade.combined_exposure_exact) ?? numberOrNull(trade.total_amount_bet) ?? numberOrNull(snapshot.position_size_usd) ?? numberOrNull(trade.position_size_usd) ?? 0;
}

function primaryTradeSizeUsd(trade) {
  return numberOrNull(trade.primary_trader?.amount) ?? numberOrNull(trade.position_size_usd) ?? tradeSizeUsd(trade);
}

function relativeBetSize(trade) {
  const primaryUnits = numberOrNull(trade.primary_trader?.relative_units);
  if (primaryUnits !== null) {
    return {
      value: formatUnitsValue(primaryUnits),
      subtext: "Primary sharp unit size",
    };
  }
  if (numberOrNull(trade.strongest_relative_units) !== null) {
    const units = numberOrNull(trade.strongest_relative_units);
    return {
      value: formatUnitsValue(units),
      subtext: "Strongest agreeing wallet",
    };
  }
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

function tradeMetric(label, value, subtext, cls = "", iconText = "") {
  return `
    <div class="trade-detail-metric ${cls}">
      <span>${iconText ? `<b aria-hidden="true">${escapeHtml(iconText)}</b>` : ""}${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      ${subtext ? `<small>${escapeHtml(subtext)}</small>` : ""}
    </div>
  `;
}

function scoreLine(label, value, maxValue) {
  return `
    <div>
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value ?? 0)}/${escapeHtml(maxValue ?? 0)}</strong>
    </div>
  `;
}

function scoreTextLine(label, value) {
  return `
    <div>
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value ?? "n/a")}</strong>
    </div>
  `;
}

function qualityLabel(value) {
  const numeric = numberOrNull(value);
  if (numeric === null) return "n/a";
  if (numeric >= 0.8) return "strong";
  if (numeric >= 0.55) return "above avg";
  if (numeric >= 0.3) return "average";
  return "light";
}

const traderStats = {
  "1winstreak1": {
    topCategory: "MLB",
    categoryRank: "#4",
    categoryWinRate: "61.2%",
    totalTrades: "12,899",
    categoryGainsLosses: "+$1.8M / -$816.7K",
  },
  "0xbca08c1bc204a34f2fddbe47b438b9bd42ac9705": {
    topCategory: "MLB",
    categoryRank: "#4",
    categoryWinRate: "61.2%",
    totalTrades: "12,899",
    categoryGainsLosses: "+$1.8M / -$816.7K",
  },
  "0x4f2": {
    topCategory: "Baseball",
    categoryRank: "#7",
    categoryWinRate: "55.5%",
    totalTrades: "7,225",
    categoryGainsLosses: "+$3.1M / -$2.4M",
  },
  "0x4f29e103339919c4baaea2a60195cf1c8bb27a7e": {
    topCategory: "Baseball",
    categoryRank: "#7",
    categoryWinRate: "55.5%",
    totalTrades: "7,225",
    categoryGainsLosses: "+$3.1M / -$2.4M",
  },
};

function traderStatsForTrade(trade) {
  const label = String(trade.wallet_label || "").toLowerCase();
  const address = String(trade.wallet_address || "").toLowerCase();
  return traderStats[label] || traderStats[address] || null;
}

function renderTradeCard(trade, index, selectedKey) {
  const key = tradeKey(trade, index);
  const selected = key === selectedKey;
  const relative = relativeBetSize(trade);
  const slippage = slippageForTrade(trade);
  const price = numberOrNull(trade.current_price);
  const priceLabel = formatTakePriceFromProbability(price);
  const priceUnavailable = priceLabel === "Unavailable";
  const primaryAmount = primaryTradeSizeUsd(trade);
  const combinedAmount = tradeSizeUsd(trade);
  const primaryUnits = formatUnitsValue(trade.primary_trader?.relative_units);
  const sharpsCount = Number(trade.agreeing_wallet_count || 1);
  const sharpsLabel = `${sharpsCount} Sharp${sharpsCount === 1 ? "" : "s"}`;
  const eventTime = trade.event_time_et || "Time unavailable";
  const category = trade.category || trade.league || "Market";

  return `
    <button class="trade-card ${selected ? "selected" : ""} ${priceUnavailable ? "price-unavailable" : ""}" type="button" data-trade-key="${escapeHtml(key)}" aria-pressed="${selected}">
      <div class="trade-card-rank score-rank">
        <span>${escapeHtml(trade.confidence_score ?? 0)}</span>
        <small>SCORE</small>
      </div>
      <div class="trade-card-main">
        <div class="trade-card-meta">
          <span>${escapeHtml(eventTime)}</span>
          <span>${escapeHtml(formatMoney(primaryAmount))}</span>
          <span>${escapeHtml(primaryUnits)}</span>
          <span class="slippage ${slippage.className}">${escapeHtml(slippage.value)}</span>
          <span class="trade-card-current">Current: ${escapeHtml(priceLabel)}</span>
        </div>
        <div class="trade-card-sport">${escapeHtml(category)}</div>
        <div class="trade-card-title" title="${escapeHtml(trade.market_title)}">${escapeHtml(trade.market_title)}</div>
        <div class="trade-card-subtitle">${escapeHtml(trade.market_type || "Moneyline")} / ${escapeHtml(trade.primary_trader?.wallet_label || "Tracked wallet")} / ${escapeHtml(sharpsLabel)} / ${escapeHtml(formatMoney(combinedAmount))} combined</div>
        <div class="trade-card-pick">
          <div>
            <span>Pick</span>
            <strong>${escapeHtml(trade.outcome || "Outcome")}</strong>
            <em>${escapeHtml(sharpsLabel)} / ${escapeHtml(relative.value)} rel. size</em>
          </div>
          <small class="${priceUnavailable ? "unavailable" : ""}">
            <b aria-hidden="true">PM</b>
            ${escapeHtml(priceLabel)}
          </small>
        </div>
      </div>
      <span class="trade-card-arrow" aria-hidden="true">&gt;</span>
    </button>
  `;
}

function renderTradeDetail(trade) {
  if (!trade) {
    return '<div class="empty-panel">No actionable trades to play match the current filters.</div>';
  }

  const relative = relativeBetSize(trade);
  const slippage = slippageForTrade(trade);
  const averageEntry = numberOrNull(trade.average_entry_price);
  const currentPrice = numberOrNull(trade.current_price);
  const sizeUsd = tradeSizeUsd(trade);
  const primaryUsd = primaryTradeSizeUsd(trade);
  const primaryUnits = formatUnitsValue(trade.primary_trader?.relative_units);
  const profileUrl = trade.primary_trader?.wallet_profile_url;
  const marketUrl = trade.market_url;
  const breakdown = trade.score_breakdown || {};
  const weights = trade.score_weights || {};
  const supporters = trade.supporting_wallets || [];

  return `
    <div class="trade-detail-header">
      <div class="trade-detail-score">${escapeHtml(trade.confidence_score ?? 0)}</div>
      <div>
        <h3 title="${escapeHtml(trade.market_title)}">${escapeHtml(trade.market_title)}</h3>
        <span>${escapeHtml(trade.category || "Market")} <b aria-hidden="true">/</b> ${escapeHtml(trade.league || "League")} <b aria-hidden="true">/</b> ${escapeHtml(trade.event_time_et || "Time unavailable")}</span>
      </div>
      ${trade.sharps_badge ? `<span class="event-badge new-entry sharps-badge">${escapeHtml(trade.sharps_badge)}</span>` : `<span class="event-badge new-entry">Actionable</span>`}
    </div>

    <div class="trade-detail-pick">
      <div>
        <span>Primary Trader</span>
        <strong>${escapeHtml(trade.primary_trader?.wallet_label || "Tracked wallet")}</strong>
        <small>${escapeHtml(formatMoney(primaryUsd))} / ${escapeHtml(primaryUnits)}</small>
      </div>
      <div>
        <span>Pick</span>
        <strong>${escapeHtml(trade.outcome || "Outcome")}</strong>
      </div>
      <div>
        <span>Combined Exposure</span>
        <strong>${formatMoney(sizeUsd)}</strong>
        <small>${escapeHtml(trade.agreeing_wallet_count || 1)} agreeing wallet${Number(trade.agreeing_wallet_count || 1) === 1 ? "" : "s"}</small>
      </div>
      <div>
        <span>Current</span>
        <strong>${escapeHtml(formatTakePriceFromProbability(currentPrice))}<i aria-hidden="true"></i></strong>
      </div>
    </div>

    <div class="trade-detail-metrics">
      ${tradeMetric("Rel. Bet Size", relative.value, relative.subtext)}
      ${tradeMetric("Primary Sharp", formatMoney(primaryUsd), `${trade.primary_trader?.wallet_label || "Tracked wallet"} exact active amount`)}
      ${tradeMetric("Combined Exposure", formatMoney(sizeUsd), "Sum of displayed agreeing wallets")}
      ${tradeMetric("Slippage", slippage.value, slippage.note, `slippage ${slippage.className}`)}
      ${tradeMetric("Price At Entry", formatCentsFromProbability(averageEntry), "Average fill price")}
    </div>

    <div class="trade-stats-grid">
      ${tradeMetric("Sharps", trade.sharps_badge || `${trade.agreeing_wallet_count || 1} Wallet`, "Consensus integrated", "positive", "S")}
      ${tradeMetric("Trader History", trade.primary_trader?.sample_size || "n/a", "Primary trader sample", "", "TR")}
      ${tradeMetric("Adj. Hitrate", `${((trade.primary_trader?.adjusted_hit_rate || 0) * 100).toFixed(1)}%`, "Shrunk by sample size", "positive", "HR")}
      ${tradeMetric("Entered", timeAgo(trade.entered_at), "Tracked entry time", "", "ET")}
    </div>

    <details class="score-breakdown">
      <summary>Why this score?</summary>
      <div class="score-breakdown-grid">
        ${scoreTextLine("Consensus band", `${breakdown.consensus_band || "n/a"} / ${breakdown.band_start ?? "?"}-${breakdown.band_end ?? "?"}`)}
        ${scoreTextLine("Consensus floor", breakdown.consensus_floor)}
        ${scoreTextLine("Secondary points", `${breakdown.secondary_points ?? 0}/${breakdown.available_secondary_points ?? 0}`)}
        ${scoreTextLine("Combined amount", `${qualityLabel(breakdown.combined_amount)} / ${Math.round((weights.combined_amount || 0) * 100)}% weight`)}
        ${scoreTextLine("Relative size", `${qualityLabel(breakdown.relative_size)} / ${Math.round((weights.relative_size || 0) * 100)}% weight`)}
        ${scoreTextLine("Trader history", `${qualityLabel(breakdown.trader_history)} / ${Math.round((weights.trader_history || 0) * 100)}% weight`)}
        ${scoreTextLine("Adjusted hit rate", `${qualityLabel(breakdown.adjusted_hit_rate)} / ${Math.round((weights.adjusted_hit_rate || 0) * 100)}% weight`)}
        ${scoreTextLine("Slippage", `${qualityLabel(breakdown.slippage)} / ${Math.round((weights.slippage || 0) * 100)}% weight`)}
        ${scoreLine("Final score", trade.confidence_score, 100)}
      </div>
      <p>${escapeHtml(breakdown.explanation || "Consensus selected the score band first; secondary metrics placed the trade inside that range.")}</p>
    </details>

    <details class="supporter-breakdown">
      <summary>Agreeing wallets</summary>
      <div class="supporter-list">
        ${supporters.map((supporter) => `
          <div>
            <strong>${escapeHtml(supporter.wallet_label)}</strong>
            <span>${formatMoney(supporter.amount)} / ${escapeHtml(formatUnitsValue(supporter.relative_units))}</span>
            <small>Entry ${escapeHtml(formatCentsFromProbability(supporter.average_entry_price))} / Current ${escapeHtml(formatCentsFromProbability(supporter.current_price))} / Shares ${escapeHtml(formatShares(supporter.shares))} / Updated ${escapeHtml(formatDate(supporter.last_changed_at))}</small>
          </div>
        `).join("")}
      </div>
    </details>

    <div class="price-card">
      <div class="price-card-head">
        <strong>Price &amp; Slippage</strong>
        <span class="price-legend">
          <em class="entry-line"></em> Entry Price <b>${escapeHtml(formatCentsFromProbability(averageEntry))}</b>
          <em class="current-line"></em> Current Price <b>${escapeHtml(formatTakePriceFromProbability(currentPrice))}</b>
          <em class="slip-line"></em> Slippage <b class="slippage ${slippage.className}">${escapeHtml(slippage.value)}</b>
        </span>
      </div>
      <div class="price-track" style="${escapeHtml(tradePriceTrackStyle(trade))}">
        <span class="axis-label axis-60">60c</span>
        <span class="axis-label axis-45">45c</span>
        <span class="axis-label axis-30">30c</span>
        <span class="axis-label axis-15">15c</span>
        <span class="axis-label axis-0">0c</span>
        <span class="entry-marker">Entry</span>
        <span class="current-marker">Current</span>
      </div>
      <p>Negative slippage means the current price is below the trader's entry, so following now is cheaper. Positive slippage means the current price is higher than entry.</p>
    </div>

    <div class="trade-detail-footer">
      <div><span>Game Time</span><strong>${escapeHtml(trade.event_time_et || "Time unavailable")}</strong></div>
      <div><span>Total Bet</span><strong>${formatMoney(sizeUsd)}</strong></div>
      <div><span>Wallets</span><strong>${escapeHtml(trade.agreeing_wallet_count || 1)}</strong></div>
      <div><span>Status</span><strong class="status-open">Pregame</strong></div>
      ${marketUrl ? `<a class="trade-action" href="${escapeHtml(marketUrl)}" target="_blank" rel="noreferrer">Open Market</a>` : ""}
      ${profileUrl ? `<a class="trade-action profile" href="${escapeHtml(profileUrl)}" target="_blank" rel="noreferrer">Trader Profile</a>` : ""}
      <button class="trade-action overflow" type="button" aria-label="More actions">...</button>
    </div>
  `;
}

function renderTrades() {
  const trades = filteredTrades().slice(0, 100);
  const tradeKeys = trades.map((trade, index) => tradeKey(trade, index));
  if (!tradeKeys.includes(state.selectedTradeKey)) {
    state.selectedTradeKey = tradeKeys[0] || null;
  }

  const selectedTrade = trades.find((trade, index) => tradeKey(trade, index) === state.selectedTradeKey);
  const countBadge = document.getElementById("trades-count-badge");
  const totalMatches = state.tradePagination?.total ?? trades.length;
  if (countBadge) countBadge.textContent = totalMatches;

  const tableBody = document.querySelector("#trades-table tbody");
  if (tableBody) {
    tableBody.innerHTML = trades.length
      ? trades.map((trade) => `
        <tr>
          <td>${escapeHtml(trade.event_time_et || "n/a")}</td>
          <td>${escapeHtml(trade.primary_trader?.wallet_label || "n/a")}</td>
          <td>${escapeHtml(trade.sharps_badge || "Actionable")}</td>
          <td class="market-cell"><span class="market-title" title="${escapeHtml(trade.market_title)}">${escapeHtml(trade.market_title)}</span></td>
          <td>${escapeHtml(trade.outcome)}</td>
          <td>${formatMoney(trade.combined_exposure_exact ?? trade.total_amount_bet)}</td>
          <td>${escapeHtml(trade.confidence_score)}</td>
        </tr>
      `).join("")
      : '<tr><td class="empty-row" colspan="7">No trades to play match the current filters.</td></tr>';
  }

  document.getElementById("trades-feed").innerHTML = trades.length
    ? trades.map((trade, index) => renderTradeCard(trade, index, state.selectedTradeKey)).join("")
    : '<div class="empty-panel">No recent trades match the current filters.</div>';

  const detailPanel = document.getElementById("trade-detail-panel");
  if (detailPanel) detailPanel.innerHTML = renderTradeDetail(selectedTrade);
}

function statusClass(status) {
  if (status === "invalid") return "pill invalid";
  if (status === "disabled") return "pill disabled";
  if (status === "failed" || status === "stale") return "pill invalid";
  if (status === "ready") return "pill enabled";
  if (status === "enabled") return "pill enabled";
  return "pill";
}

function renderWallets() {
  document.querySelector("#wallets-table tbody").innerHTML = state.wallets.length
    ? state.wallets.map((wallet) => {
      const baseUnit = wallet.base_unit ? formatMoney(wallet.base_unit) : "n/a";
      const syncStatus = wallet.sync_status || "pending";
      return `
        <tr>
          <td>${escapeHtml(wallet.label)}</td>
          <td>${escapeHtml(wallet.address || "n/a")}</td>
          <td>
            <span class="${statusClass(wallet.status)}">${escapeHtml(wallet.status)}</span>
            <span class="${statusClass(syncStatus)}">${escapeHtml(syncStatus)}</span>
            ${wallet.message ? `<br><span class="status-label">${escapeHtml(wallet.message)}</span>` : ""}
            <br><span class="status-label">${escapeHtml(wallet.open_position_count ?? 0)} open / ${escapeHtml(wallet.closed_position_count ?? 0)} historical</span>
          </td>
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
      const syncStatus = wallet.sync_status || "pending";
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
            <span class="${statusClass(syncStatus)}">${escapeHtml(syncStatus)}</span>
            <span class="cell-sub">Base unit ${escapeHtml(baseUnit)}</span>
            <span class="cell-sub">${escapeHtml(wallet.open_position_count ?? 0)} open / ${escapeHtml(wallet.closed_position_count ?? 0)} historical</span>
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
  const tradeWallets = state.trades.flatMap((trade) => (trade.supporting_wallets || []).map((entry) => entry.wallet_label).filter(Boolean));
  syncFilter("wallet-filter", [...new Set(state.positions.map((position) => position.wallet_label).concat(tradeWallets).filter(Boolean))].sort());
  syncFilter("sport-filter", [...new Set(state.positions.map((position) => position.category).concat(state.trades.map((trade) => trade.category)).filter(Boolean))].sort());
  syncFilter("league-filter", [...new Set(state.positions.map((position) => position.league).concat(state.trades.map((trade) => trade.league)).filter(Boolean))].sort());
}

function renderStatusChrome(status) {
  const api = status.api_status || "idle";
  const lastCheck = formatDate(state.lastDashboardCheck);
  const dataRefresh = formatDate(status.last_successful_refresh);
  const setText = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  };
  setText("api-status", api);
  setText("hero-api-status", `API ${api}`);
  setText("last-refresh", lastCheck);
  setText("hero-last-refresh", lastCheck);
  setText("last-data-refresh", dataRefresh);
  setText("hero-data-refresh", dataRefresh);
  setText("nav-enabled-wallets", status.enabled_wallet_count ?? 0);
  setStatusDots(api);
}

function renderAll() {
  renderStatusChrome(state.status || {});
  syncSelectors();
  renderOverview();
  renderFilteredViews();
  renderWallets();
  renderUnitAnalysis();
  renderSettings();
  toggleEmptyState();
}

async function loadDashboard() {
  if (state.loading) return;
  state.loading = true;
  document.body.classList.add("loading");
  try {
    const tradeQuery = tradeFilterQuery();
    const [positions, trades, wallets, unitAnalysis, status] = await Promise.all([
      fetchJson("/api/positions"),
      fetchJson(`/api/trades-to-play${tradeQuery ? `?${tradeQuery}` : ""}`),
      fetchJson("/api/wallets"),
      fetchJson("/api/unit-analysis"),
      fetchJson("/api/status"),
    ]);

    state.positions = positions.data || [];
    state.trades = trades.data || [];
    state.tradePagination = trades.pagination || null;
    state.wallets = wallets.data || [];
    state.unitAnalysis = unitAnalysis.data || [];
    state.consensus = [];
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
  state.selectedTradeKey = null;
  renderFilteredViews();
  scheduleTradeRefresh(0);
}

function updateCustomDateFields() {
  const isCustom = document.getElementById("date-range-filter").value === "custom";
  document.querySelectorAll(".custom-date-field").forEach((field) => {
    field.classList.toggle("active", isCustom);
  });
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

  if (action === "today" || action === "tomorrow" || action === "next24" || action === "next48" || action === "week") {
    document.getElementById("date-range-filter").value = action;
  }

  if (action === "large") {
    document.getElementById("min-position").value = "1000";
  }

  if (action === "profitable") {
    document.getElementById("min-pnl").value = "1";
  }

  renderFilteredViews();
  scheduleTradeRefresh(0);
}

function bindInteractions() {
  filterIds.forEach((id) => {
    const element = document.getElementById(id);
    if (!element) return;
    const handler = () => {
      syncPairedFilters(id);
      renderFilteredViews();
      scheduleTradeRefresh(id === "search-input" ? 300 : 0);
    };
    element.addEventListener("input", handler);
    element.addEventListener("change", handler);
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
