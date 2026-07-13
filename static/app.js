const page = document.body.dataset.page;
const AUTO_REFRESH_MS = 15000;
const appState = {
  paused: localStorage.getItem("iconbets-refresh-paused") === "true",
  selectedTradeId: null,
  trades: [],
  pageNumber: 1,
  graphRange: "month",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function number(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatMoney(value, digits = 2) {
  const parsed = number(value);
  if (parsed === null) return "Unavailable";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(parsed);
}

function formatCompactMoney(value) {
  const parsed = number(value);
  if (parsed === null) return "Unavailable";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: Math.abs(parsed) >= 1000 ? "compact" : "standard",
    maximumFractionDigits: 1,
  }).format(parsed);
}

function formatPercent(value, digits = 1) {
  const parsed = number(value);
  return parsed === null ? "Unavailable" : `${(parsed * 100).toFixed(digits)}%`;
}

function formatCents(value) {
  const parsed = number(value);
  if (parsed === null || parsed <= 0 || parsed >= 1) return "Unavailable";
  const cents = parsed * 100;
  return `${Number.isInteger(cents) ? cents.toFixed(0) : cents.toFixed(1)}¢`;
}

function formatUnits(value) {
  const parsed = number(value);
  return parsed === null ? "n/a" : `${parsed.toFixed(2)}u`;
}

function formatDateTime(value, fallback = "Unavailable") {
  if (!value) return fallback;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return fallback;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
    timeZoneName: "short",
  }).format(parsed);
}

function debounce(callback, delay = 250) {
  let timer;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => callback(...args), delay);
  };
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

function showToast(message, tone = "neutral") {
  const toast = document.getElementById("app-toast");
  if (!toast) return;
  toast.textContent = message;
  toast.dataset.tone = tone;
  toast.classList.add("visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("visible"), 3200);
}

function emptyState(title, copy) {
  return `<div class="empty-state"><i class="ph ph-binoculars" aria-hidden="true"></i><h2>${escapeHtml(title)}</h2><p>${escapeHtml(copy)}</p></div>`;
}

function errorState(message) {
  return `<div class="empty-state error-state"><i class="ph ph-warning-circle" aria-hidden="true"></i><h2>Could not load this view</h2><p>${escapeHtml(message)}</p></div>`;
}

function setOptions(select, values, label) {
  if (!select) return;
  const selected = select.value;
  const unique = [...new Set(values.filter(Boolean).map(String))].sort((a, b) => a.localeCompare(b));
  select.innerHTML = `<option value="">${escapeHtml(label)}</option>` + unique
    .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
    .join("");
  select.value = unique.includes(selected) ? selected : "";
}

function updateGlobalStatus(status = {}) {
  const api = document.getElementById("global-api-status");
  const dot = document.getElementById("global-api-dot");
  const refresh = document.getElementById("global-last-refresh");
  const wallets = document.getElementById("global-wallet-count");
  if (api) api.textContent = status.api_status || "Unknown";
  if (dot) dot.dataset.status = status.api_status || "unknown";
  if (refresh) refresh.textContent = formatDateTime(status.last_successful_refresh, "Waiting");
  if (wallets) wallets.textContent = status.enabled_wallet_count ?? 0;
}

async function loadGlobalStatus() {
  try {
    updateGlobalStatus(await fetchJson("/api/status"));
  } catch (error) {
    updateGlobalStatus({ api_status: "error" });
  }
}

function metricCard(label, value, detail, icon) {
  return `
    <article class="metric-card">
      <div class="metric-icon"><i class="ph ${icon}" aria-hidden="true"></i></div>
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(detail)}</small>
    </article>
  `;
}

function recommendationLabel(recommendation) {
  if (!recommendation?.available) return "Sizing unavailable";
  if (!(number(recommendation.final_recommended_fraction) > 0)) return "No bet at current entry";
  return `${formatMoney(recommendation.recommended_amount)} · ${formatUnits(recommendation.recommended_units)} · ${formatPercent(recommendation.final_recommended_fraction, 2)}`;
}

function confidenceClass(score) {
  const value = Number(score || 0);
  if (value >= 80) return "elite";
  if (value >= 70) return "strong";
  return "watch";
}

function previewTradeCard(trade) {
  return `
    <a class="preview-trade" href="/trades?selected=${encodeURIComponent(trade.id)}">
      <span class="score-badge ${confidenceClass(trade.confidence_score)}">${escapeHtml(trade.confidence_score)}</span>
      <div><small>${escapeHtml(trade.league || trade.category || "Sports")} · ${escapeHtml(trade.event_time_et || "Scheduled")}</small><strong>${escapeHtml(trade.event_title || trade.market_title)}</strong><span>${escapeHtml(trade.outcome)}</span></div>
      <div class="preview-price"><span>Current</span><strong>${formatCents(trade.recommendation?.current_user_entry_price)}</strong><small>${escapeHtml(recommendationLabel(trade.recommendation))}</small></div>
      <i class="ph ph-caret-right" aria-hidden="true"></i>
    </a>
  `;
}

async function loadOverview() {
  const metrics = document.getElementById("overview-metrics");
  const trades = document.getElementById("overview-trades");
  try {
    const payload = await fetchJson("/api/overview");
    updateGlobalStatus(payload.status);
    const data = payload.data || {};
    metrics.innerHTML = [
      metricCard("Trades to Play", String(data.trades_to_play_count ?? 0), "Verified upcoming opportunities", "ph-lightning"),
      metricCard("Enabled Wallets", String(data.enabled_wallets ?? 0), "Public wallets actively synced", "ph-wallet"),
      metricCard("Live Positions", String(data.live_position_count ?? 0), "Markets currently in progress", "ph-broadcast"),
      metricCard("Position Value", formatMoney(data.total_current_position_value ?? 0), "Current tracked value", "ph-chart-line-up"),
      metricCard("API Status", String(data.api_status || "unknown").toUpperCase(), "Polymarket data connection", "ph-plugs-connected"),
      metricCard("Last Refresh", formatDateTime(payload.status?.last_successful_refresh), "Last successful data cycle", "ph-clock"),
    ].join("");
    trades.innerHTML = payload.top_trades?.length
      ? payload.top_trades.map(previewTradeCard).join("")
      : emptyState("No verified trades today", "The tracker will surface a trade only when its start time, market state, outcome token, and executable ask are all verified.");
  } catch (error) {
    metrics.innerHTML = errorState(error.message);
    trades.innerHTML = errorState(error.message);
  }
}

function tradeFiltersFromUrl() {
  const params = new URLSearchParams(window.location.search);
  return {
    q: params.get("q") || "",
    date_range: params.get("date_range") || "today",
    min_sharps: params.get("min_sharps") || "0",
    min_confidence: params.get("min_confidence") || "0",
    sport: params.get("sport") || "",
    league: params.get("league") || "",
    wallet: params.get("wallet") || "",
    custom_start: params.get("custom_start") || "",
    custom_end: params.get("custom_end") || "",
  };
}

function applyTradeFiltersToControls(filters) {
  const mapping = {
    "trade-search": "q",
    "trade-date-range": "date_range",
    "trade-sharps": "min_sharps",
    "trade-confidence": "min_confidence",
    "trade-sport": "sport",
    "trade-league": "league",
    "trade-wallet": "wallet",
    "custom-start": "custom_start",
    "custom-end": "custom_end",
  };
  Object.entries(mapping).forEach(([id, key]) => {
    const element = document.getElementById(id);
    if (element) element.value = filters[key];
  });
  document.querySelectorAll(".custom-time").forEach((field) => {
    field.hidden = filters.date_range !== "custom";
  });
  if (filters.date_range === "custom") setMoreFiltersExpanded(true);
}

function setMoreFiltersExpanded(expanded) {
  const panel = document.getElementById("more-filters");
  const button = document.getElementById("more-filters-button");
  if (!panel || !button) return;
  panel.hidden = !expanded;
  button.setAttribute("aria-expanded", String(expanded));
}

function readTradeControls() {
  return {
    q: document.getElementById("trade-search").value.trim(),
    date_range: document.getElementById("trade-date-range").value,
    min_sharps: document.getElementById("trade-sharps").value,
    min_confidence: document.getElementById("trade-confidence").value,
    sport: document.getElementById("trade-sport").value,
    league: document.getElementById("trade-league").value,
    wallet: document.getElementById("trade-wallet").value,
    custom_start: document.getElementById("custom-start").value,
    custom_end: document.getElementById("custom-end").value,
  };
}

function updateTradeUrl(filters) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value && !((key === "min_sharps" || key === "min_confidence") && value === "0") && !(key === "date_range" && value === "today")) {
      params.set(key, value);
    }
  });
  if (appState.selectedTradeId) params.set("selected", appState.selectedTradeId);
  const query = params.toString();
  window.history.replaceState({}, "", query ? `/trades?${query}` : "/trades");
}

function tradeCard(trade) {
  const recommendation = trade.recommendation || {};
  const selected = trade.id === appState.selectedTradeId;
  const slippage = number(recommendation.price_movement);
  const slippageClass = slippage === null ? "" : slippage <= 0 ? "positive" : "negative";
  const slippageText = slippage === null ? "n/a" : `${slippage > 0 ? "+" : ""}${(slippage * 100).toFixed(1)}¢`;
  const primary = trade.primary_trader || {};
  return `
    <article class="trade-card ${selected ? "selected" : ""}" role="button" tabindex="0" data-trade-id="${escapeHtml(trade.id)}" aria-pressed="${selected}">
      <span class="trade-score ${confidenceClass(trade.confidence_score)}"><strong>${escapeHtml(trade.confidence_score)}</strong><small>Score</small></span>
      <span class="trade-card-main">
        <span class="trade-chip-row">
          <span><i class="ph ph-calendar-blank" aria-hidden="true"></i>${escapeHtml(trade.event_time_et || "Verified time unavailable")}</span>
          <span>${formatCompactMoney(primary.amount)}</span>
          <span>${formatUnits(primary.relative_units)}</span>
          <span class="${slippageClass}">${slippageText}</span>
        </span>
        <span class="trade-kicker">${escapeHtml(trade.category || "Sports")} · ${escapeHtml(trade.league || "Market")} · ${escapeHtml(trade.sports_market_type || "Position")}</span>
        <strong class="trade-event">${escapeHtml(trade.event_title || trade.market_title)}</strong>
        <span class="trade-subline">${escapeHtml(primary.wallet_label || "Tracked Sharp")} · ${trade.agreeing_wallet_count} Sharp${trade.agreeing_wallet_count === 1 ? "" : "s"} · ${formatCompactMoney(trade.combined_exposure_exact)} exposure</span>
        <span class="trade-selection">
          <span><small>Pick</small><strong>${escapeHtml(trade.outcome)}</strong></span>
          <span><small>Recommended</small><strong>${escapeHtml(recommendationLabel(recommendation))}</strong></span>
          <a class="price-pill polymarket-price-link" href="${escapeHtml(trade.market_url || "#")}" target="_blank" rel="noopener noreferrer" aria-label="Open ${escapeHtml(trade.outcome)} on Polymarket at ${escapeHtml(formatCents(recommendation.current_user_entry_price))}">
            <img src="https://polymarket.com/icons/favicon-32x32.png" alt="" aria-hidden="true" width="18" height="18">
            <strong>${formatCents(recommendation.current_user_entry_price)}</strong>
          </a>
        </span>
      </span>
      <i class="ph ph-caret-right trade-caret" aria-hidden="true"></i>
    </article>
  `;
}

function detailMetric(label, value, copy, tone = "") {
  return `<article class="detail-metric ${tone}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(copy)}</small></article>`;
}

function whySizing(recommendation, trade) {
  if (!recommendation.available) {
    return `<div class="data-warning"><i class="ph ph-warning-circle" aria-hidden="true"></i><div><strong>Sizing unavailable</strong><p>${escapeHtml(recommendation.reason || recommendation.message)}</p></div></div>`;
  }
  const rows = [
    ["Current User Entry", formatCents(recommendation.current_user_entry_price)],
    ["Baseline Probability", formatPercent(recommendation.baseline_probability)],
    ["Sharps", String(trade.agreeing_wallet_count)],
    ["Sharp Evidence Score", Number(recommendation.evidence_score).toFixed(3)],
    ["Evidence Adjustment", `+${formatPercent(recommendation.evidence_adjustment)}`],
    ["Estimated Win Probability", formatPercent(recommendation.estimated_win_probability)],
    ["Calculated Edge", formatPercent(recommendation.calculated_edge)],
    ["Full Kelly", formatPercent(recommendation.full_kelly_fraction)],
    ["Half Kelly", formatPercent(recommendation.half_kelly_fraction)],
    ["Sharp Risk Cap", formatPercent(recommendation.sharp_risk_cap)],
    ["Final Recommendation", formatPercent(recommendation.final_recommended_fraction, 2)],
    ["Bankroll", formatMoney(recommendation.bankroll)],
    ["Recommended Bet", formatMoney(recommendation.recommended_amount)],
    ["Recommended Units", formatUnits(recommendation.recommended_units)],
  ];
  return `
    <details class="calculation-details">
      <summary><span><i class="ph ph-function" aria-hidden="true"></i>Why this bet size?</span><i class="ph ph-caret-down" aria-hidden="true"></i></summary>
      <div class="calculation-grid">${rows.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div>
      <p class="calculation-note">The current executable CLOB entry is the baseline probability. Sharp evidence can add only a bounded adjustment; Half Kelly is then limited by consensus and global risk caps.</p>
    </details>
  `;
}

function supportersMarkup(trade) {
  return (trade.supporting_wallets || []).map((wallet) => `
    <a class="supporter-row" href="${escapeHtml(wallet.wallet_profile_url || "#")}" target="_blank" rel="noopener noreferrer">
      <span class="supporter-avatar"><i class="ph ph-user" aria-hidden="true"></i></span>
      <span><strong>${escapeHtml(wallet.wallet_label)}</strong><small>${escapeHtml(wallet.wallet_address)}</small></span>
      <span><strong>${formatMoney(wallet.amount)}</strong><small>${formatUnits(wallet.relative_units)}</small></span>
      <i class="ph ph-arrow-up-right" aria-hidden="true"></i>
    </a>
  `).join("");
}

function renderTradeDetail(trade) {
  const panel = document.getElementById("trade-detail");
  const recommendation = trade.recommendation || {};
  const movement = number(recommendation.price_movement);
  const movementTone = movement !== null && movement <= 0 ? "positive" : "negative";
  panel.innerHTML = `
    <div class="detail-header">
      <span class="score-badge large ${confidenceClass(trade.confidence_score)}">${escapeHtml(trade.confidence_score)}</span>
      <div><p>${escapeHtml(trade.category || "Sports")} · ${escapeHtml(trade.league || "Market")}</p><h2>${escapeHtml(trade.event_title || trade.market_title)}</h2><span>${escapeHtml(trade.market_title)} · ${escapeHtml(trade.event_time_et)}</span></div>
      <span class="live-price"><small>Executable entry</small><strong>${formatCents(recommendation.current_user_entry_price)}</strong><em>${escapeHtml(trade.agreeing_wallet_count + " Sharp" + (trade.agreeing_wallet_count === 1 ? "" : "s"))}</em></span>
    </div>
    <div class="selection-banner"><span><small>Recommended side</small><strong>${escapeHtml(trade.outcome)}</strong></span><span><small>Recommended bet</small><strong>${escapeHtml(recommendationLabel(recommendation))}</strong></span></div>
    <div class="detail-metric-grid">
      ${detailMetric("Relative Bet Size", formatUnits(trade.primary_trader?.relative_units), "Primary Sharp versus normal size")}
      ${detailMetric("Primary Position", formatMoney(trade.primary_trader?.amount), trade.primary_trader?.wallet_label || "Tracked Sharp")}
      ${detailMetric("Price Movement", movement === null ? "Unavailable" : `${movement > 0 ? "+" : ""}${(movement * 100).toFixed(1)}¢`, movement !== null && movement <= 0 ? "Better than Sharp entry" : "Worse than Sharp entry", movementTone)}
      ${detailMetric("Combined Exposure", formatMoney(trade.combined_exposure_exact), `${trade.agreeing_wallet_count} agreeing wallets`)}
      ${detailMetric("Baseline Probability", formatPercent(recommendation.baseline_probability), "Exact current user entry")}
      ${detailMetric("Estimated Win", formatPercent(recommendation.estimated_win_probability), "After bounded Sharp evidence")}
      ${detailMetric("Half Kelly", formatPercent(recommendation.half_kelly_fraction), "Before risk caps")}
      ${detailMetric("Final Stake", formatPercent(recommendation.final_recommended_fraction, 2), "Percentage frozen in tracker", recommendation.final_recommended_fraction > 0 ? "positive" : "")}
    </div>
    ${whySizing(recommendation, trade)}
    <section class="detail-section">
      <div class="section-label"><span>Price history</span><small>Polymarket CLOB · real outcome token</small></div>
      <div class="price-chart" id="price-chart"><div class="chart-loading">Loading verified price history…</div></div>
    </section>
    <section class="detail-section">
      <div class="section-label"><span>Agreeing wallets</span><small>Exact remaining active exposure</small></div>
      <div class="supporter-list">${supportersMarkup(trade)}</div>
    </section>
    <div class="detail-actions">
      <a class="button primary" href="${escapeHtml(trade.market_url || "#")}" target="_blank" rel="noopener noreferrer"><i class="ph ph-arrow-square-out" aria-hidden="true"></i>Open Polymarket</a>
      <a class="button ghost" href="${escapeHtml(trade.primary_trader?.wallet_profile_url || "#")}" target="_blank" rel="noopener noreferrer"><i class="ph ph-user" aria-hidden="true"></i>Trader Profile</a>
    </div>
  `;
  loadPriceHistory(trade.clob_token_id, recommendation.current_user_entry_price);
}

function drawLineChart(container, points, options = {}) {
  if (!container) return;
  if (!points.length) {
    container.innerHTML = emptyState("No chart data", "Verified history is not available for this range.");
    return;
  }
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(680, container.clientWidth * window.devicePixelRatio);
  canvas.height = Math.max(220, container.clientHeight * window.devicePixelRatio);
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  container.innerHTML = "";
  container.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const pad = 44 * window.devicePixelRatio;
  const values = points.map((point) => Number(point.value));
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) { min -= 0.01; max += 0.01; }
  const x = (index) => pad + (index / Math.max(1, points.length - 1)) * (width - pad * 1.5);
  const y = (value) => height - pad - ((value - min) / (max - min)) * (height - pad * 1.7);
  ctx.strokeStyle = "rgba(120, 153, 165, 0.15)";
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i += 1) {
    const lineY = pad + (i / 3) * (height - pad * 1.7);
    ctx.beginPath(); ctx.moveTo(pad, lineY); ctx.lineTo(width - pad / 2, lineY); ctx.stroke();
  }
  const gradient = ctx.createLinearGradient(0, pad, 0, height - pad);
  gradient.addColorStop(0, "rgba(46, 235, 154, 0.26)");
  gradient.addColorStop(1, "rgba(46, 235, 154, 0)");
  ctx.beginPath();
  points.forEach((point, index) => {
    const px = x(index); const py = y(point.value);
    if (index === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  });
  ctx.lineTo(x(points.length - 1), height - pad);
  ctx.lineTo(x(0), height - pad);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();
  ctx.beginPath();
  points.forEach((point, index) => {
    const px = x(index); const py = y(point.value);
    if (index === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  });
  ctx.strokeStyle = options.color || "#35e39a";
  ctx.lineWidth = 2.5 * window.devicePixelRatio;
  ctx.stroke();
  ctx.fillStyle = "#8da0a8";
  ctx.font = `${11 * window.devicePixelRatio}px "IBM Plex Sans"`;
  ctx.fillText(options.format ? options.format(max) : String(max), 4, pad);
  ctx.fillText(options.format ? options.format(min) : String(min), 4, height - pad);
}

async function loadPriceHistory(tokenId, fallbackPrice) {
  const container = document.getElementById("price-chart");
  if (!container || !tokenId) {
    if (container) container.innerHTML = emptyState("Price history unavailable", "This trade does not have a verified outcome token.");
    return;
  }
  try {
    const payload = await fetchJson(`/api/price-history?token_id=${encodeURIComponent(tokenId)}&interval=1d`);
    const points = (payload.data || []).map((point) => ({ timestamp: point.t, value: Number(point.p) })).filter((point) => Number.isFinite(point.value));
    if (!points.length && number(fallbackPrice) !== null) points.push({ timestamp: Date.now(), value: Number(fallbackPrice) });
    drawLineChart(container, points, { format: formatCents });
  } catch (error) {
    container.innerHTML = emptyState("Live chart unavailable", "The trade remains sized from the verified order book; only chart history could not be loaded.");
  }
}

function selectTrade(id, scroll = false) {
  const trade = appState.trades.find((item) => item.id === id);
  if (!trade) return;
  appState.selectedTradeId = id;
  document.querySelectorAll(".trade-card").forEach((card) => {
    const selected = card.dataset.tradeId === id;
    card.classList.toggle("selected", selected);
    card.setAttribute("aria-pressed", String(selected));
  });
  renderTradeDetail(trade);
  updateTradeUrl(readTradeControls());
  if (scroll && window.innerWidth < 980) document.getElementById("trade-detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadTrades() {
  const list = document.getElementById("trade-list");
  const filters = readTradeControls();
  updateTradeUrl(filters);
  const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== ""));
  try {
    const payload = await fetchJson(`/api/trades-to-play?${query.toString()}`);
    appState.trades = payload.data || [];
    updateGlobalStatus(payload.status);
    document.getElementById("trade-result-count").textContent = `${payload.pagination.total} result${payload.pagination.total === 1 ? "" : "s"}`;
    document.getElementById("trade-freshness").textContent = `Live book checked ${formatDateTime(payload.status?.last_successful_refresh, "now")}`;
    const currentSport = document.getElementById("trade-sport").value;
    const currentLeague = document.getElementById("trade-league").value;
    const currentWallet = document.getElementById("trade-wallet").value;
    setOptions(document.getElementById("trade-sport"), appState.trades.map((trade) => trade.category), "All Sports");
    setOptions(document.getElementById("trade-league"), appState.trades.map((trade) => trade.league), "All leagues");
    setOptions(document.getElementById("trade-wallet"), appState.trades.flatMap((trade) => (trade.supporting_wallets || []).map((wallet) => wallet.wallet_label)), "All wallets");
    document.getElementById("trade-sport").value = currentSport;
    document.getElementById("trade-league").value = currentLeague;
    document.getElementById("trade-wallet").value = currentWallet;
    if (!appState.trades.length) {
      list.innerHTML = emptyState("No actionable trades match", "Past, live, closed, conflicted, illiquid, and unverified markets are intentionally excluded.");
      document.getElementById("trade-detail").innerHTML = emptyState("No trade selected", "Change the date or filters to inspect another verified opportunity.");
      return;
    }
    const selectedParam = new URLSearchParams(window.location.search).get("selected");
    if (!appState.trades.some((trade) => trade.id === appState.selectedTradeId)) {
      appState.selectedTradeId = appState.trades.some((trade) => trade.id === selectedParam) ? selectedParam : appState.trades[0].id;
    }
    list.innerHTML = appState.trades.map(tradeCard).join("");
    list.querySelectorAll(".trade-card").forEach((card) => {
      card.addEventListener("click", (event) => {
        if (event.target.closest("a")) return;
        selectTrade(card.dataset.tradeId, true);
      });
      card.addEventListener("keydown", (event) => {
        if (event.target.closest("a") || !["Enter", " "].includes(event.key)) return;
        event.preventDefault();
        selectTrade(card.dataset.tradeId, true);
      });
    });
    selectTrade(appState.selectedTradeId);
    if (payload.bankroll) {
      document.getElementById("bankroll-input").value = Number(payload.bankroll.starting_bankroll).toFixed(0);
      document.getElementById("unit-value").textContent = formatMoney(payload.bankroll.starting_bankroll * payload.bankroll.unit_percentage);
    }
  } catch (error) {
    list.innerHTML = errorState(error.message);
    document.getElementById("trade-detail").innerHTML = errorState(error.message);
  }
}

async function saveBankroll() {
  const input = document.getElementById("bankroll-input");
  const state = document.getElementById("bankroll-save-state");
  const bankroll = Number(input.value);
  if (!(bankroll > 0)) {
    state.textContent = "Enter an amount greater than zero";
    return;
  }
  state.textContent = "Saving...";
  try {
    const payload = await fetchJson("/api/user-settings", { method: "PUT", body: JSON.stringify({ starting_bankroll: bankroll }) });
    document.getElementById("unit-value").textContent = formatMoney(payload.data.unit_value);
    state.textContent = "Saved";
    await loadTrades();
  } catch (error) {
    state.textContent = error.message;
  }
}

function bindTrades() {
  const initial = tradeFiltersFromUrl();
  applyTradeFiltersToControls(initial);
  const reload = debounce(loadTrades, 280);
  ["trade-search"].forEach((id) => document.getElementById(id).addEventListener("input", reload));
  ["trade-date-range", "trade-sharps", "trade-confidence", "trade-sport", "trade-league", "trade-wallet", "custom-start", "custom-end"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => {
      if (id === "trade-date-range") {
        const custom = document.getElementById(id).value === "custom";
        document.querySelectorAll(".custom-time").forEach((field) => { field.hidden = !custom; });
        if (custom) setMoreFiltersExpanded(true);
      }
      loadTrades();
    });
  });
  document.getElementById("more-filters-button").addEventListener("click", () => {
    const panel = document.getElementById("more-filters");
    setMoreFiltersExpanded(panel.hidden);
  });
  document.getElementById("clear-trade-filters").addEventListener("click", () => {
    applyTradeFiltersToControls({ q: "", date_range: "today", min_sharps: "0", min_confidence: "0", sport: "", league: "", wallet: "", custom_start: "", custom_end: "" });
    loadTrades();
  });
  document.getElementById("save-bankroll").addEventListener("click", saveBankroll);
  document.getElementById("bankroll-input").addEventListener("keydown", (event) => { if (event.key === "Enter") saveBankroll(); });
  document.getElementById("trade-refresh-button").addEventListener("click", async () => {
    const button = document.getElementById("trade-refresh-button");
    button.classList.add("spinning");
    try {
      await fetchJson("/api/refresh", { method: "POST", body: "{}" });
      await loadTrades();
      showToast("Polymarket data refreshed", "success");
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      button.classList.remove("spinning");
    }
  });
  loadTrades();
}

function positionRow(row) {
  const pnl = number(row.unrealized_pnl) || 0;
  return `
    <tr>
      <td><strong>${escapeHtml(row.wallet_label)}</strong><small>${escapeHtml(row.wallet_short_address)}</small></td>
      <td><strong>${escapeHtml(row.event_title || row.market_title)}</strong><small>${escapeHtml(row.market_title)}</small></td>
      <td><strong>${escapeHtml(row.outcome)}</strong><small>${escapeHtml(row.sports_market_type || row.league)}</small></td>
      <td class="mono">${formatCents(row.average_entry_price)}</td>
      <td class="mono">${formatCents(row.current_price)}</td>
      <td class="mono">${formatMoney(row.position_size_usd)}</td>
      <td class="mono">${formatMoney(row.current_value)}</td>
      <td class="mono ${pnl >= 0 ? "positive" : "negative"}">${formatMoney(pnl)}</td>
      <td><span class="status-label live">Live</span></td>
    </tr>
  `;
}

function positionCard(row) {
  return `<article class="mobile-result-card"><div><span class="status-label live">Live</span><small>${escapeHtml(row.wallet_label)}</small></div><h2>${escapeHtml(row.event_title || row.market_title)}</h2><strong>${escapeHtml(row.outcome)}</strong><dl><div><dt>Position</dt><dd>${formatMoney(row.position_size_usd)}</dd></div><div><dt>Current</dt><dd>${formatCents(row.current_price)}</dd></div><div><dt>P&amp;L</dt><dd>${formatMoney(row.unrealized_pnl)}</dd></div></dl></article>`;
}

function paginationMarkup(pagination, action) {
  if (!pagination || pagination.total <= pagination.per_page) return "";
  return `<button class="button ghost compact" data-page="${pagination.page - 1}" ${pagination.has_prev ? "" : "disabled"}>Previous</button><span>Page ${pagination.page}</span><button class="button ghost compact" data-page="${pagination.page + 1}" ${pagination.has_next ? "" : "disabled"}>Next</button>`;
}

async function loadPositions() {
  const params = new URLSearchParams({
    lifecycle: "live",
    q: document.getElementById("position-search").value,
    wallet: document.getElementById("position-wallet").value,
    sport: document.getElementById("position-sport").value,
    league: document.getElementById("position-league").value,
    market: document.getElementById("position-market").value,
    sort: document.getElementById("position-sort").value,
    page: String(appState.pageNumber),
    per_page: "50",
  });
  const body = document.getElementById("positions-body");
  try {
    const payload = await fetchJson(`/api/positions?${params.toString()}`);
    const rows = payload.data || [];
    updateGlobalStatus(payload.status);
    document.getElementById("position-result-count").textContent = `${payload.pagination.total} position${payload.pagination.total === 1 ? "" : "s"}`;
    body.innerHTML = rows.length ? rows.map(positionRow).join("") : `<tr><td colspan="9">${emptyState("No live positions", "Upcoming trades remain in Trades to Play. Completed markets move to history.")}</td></tr>`;
    document.getElementById("positions-cards").innerHTML = rows.map(positionCard).join("");
    const pagination = document.getElementById("positions-pagination");
    pagination.innerHTML = paginationMarkup(payload.pagination);
    pagination.querySelectorAll("button[data-page]").forEach((button) => button.addEventListener("click", () => { appState.pageNumber = Number(button.dataset.page); loadPositions(); }));
    setOptions(document.getElementById("position-sport"), rows.map((row) => row.category), "All sports");
    setOptions(document.getElementById("position-league"), rows.map((row) => row.league), "All leagues");
    setOptions(document.getElementById("position-market"), rows.map((row) => row.sports_market_type), "All markets");
  } catch (error) {
    body.innerHTML = `<tr><td colspan="9">${errorState(error.message)}</td></tr>`;
  }
}

async function bindPositions() {
  try {
    const wallets = await fetchJson("/api/wallets");
    setOptions(document.getElementById("position-wallet"), wallets.data.map((wallet) => wallet.label), "All wallets");
  } catch {}
  document.getElementById("position-search").addEventListener("input", debounce(() => { appState.pageNumber = 1; loadPositions(); }));
  ["position-wallet", "position-sport", "position-league", "position-market", "position-sort"].forEach((id) => document.getElementById(id).addEventListener("change", () => { appState.pageNumber = 1; loadPositions(); }));
  loadPositions();
}

function walletCard(wallet) {
  const sync = wallet.sync_status || wallet.status;
  return `
    <article class="wallet-card">
      <div class="wallet-card-head"><span class="wallet-avatar"><i class="ph ph-wallet" aria-hidden="true"></i></span><div><h2>${escapeHtml(wallet.label)}</h2><span class="status-label ${escapeHtml(sync)}">${escapeHtml(sync)}</span></div></div>
      <button class="address-copy" type="button" data-copy-address="${escapeHtml(wallet.address)}"><span>${escapeHtml(wallet.address)}</span><i class="ph ph-copy" aria-hidden="true"></i></button>
      <div class="wallet-stats"><div><span>Open positions</span><strong>${wallet.open_position_count ?? 0}</strong></div><div><span>History events</span><strong>${wallet.historical_position_count ?? 0}</strong></div><div><span>Base unit</span><strong>${wallet.base_unit ? formatMoney(wallet.base_unit) : "Estimating"}</strong></div></div>
      <div class="wallet-sync"><span>Last successful sync</span><strong>${formatDateTime(wallet.last_synced_at, "Not available")}</strong></div>
      ${wallet.message ? `<p class="wallet-warning">${escapeHtml(wallet.message)}</p>` : ""}
      <a class="button ghost" href="${escapeHtml(wallet.profile_url || "#")}" target="_blank" rel="noopener noreferrer">View on Polymarket <i class="ph ph-arrow-up-right" aria-hidden="true"></i></a>
    </article>
  `;
}

async function loadWallets() {
  const params = new URLSearchParams({ q: document.getElementById("wallet-search").value, status: document.getElementById("wallet-status").value, sort: document.getElementById("wallet-sort").value });
  const grid = document.getElementById("wallet-grid");
  try {
    const payload = await fetchJson(`/api/wallets?${params.toString()}`);
    updateGlobalStatus(payload.status);
    document.getElementById("wallet-result-count").textContent = `${payload.total} wallet${payload.total === 1 ? "" : "s"}`;
    grid.innerHTML = payload.data.length ? payload.data.map(walletCard).join("") : emptyState("No wallets match", "Try another name, address, or sync status.");
    grid.querySelectorAll("[data-copy-address]").forEach((button) => button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(button.dataset.copyAddress);
      showToast("Public wallet address copied", "success");
    }));
  } catch (error) {
    grid.innerHTML = errorState(error.message);
  }
}

function bindWallets() {
  document.getElementById("wallet-search").addEventListener("input", debounce(loadWallets));
  ["wallet-status", "wallet-sort"].forEach((id) => document.getElementById(id).addEventListener("change", loadWallets));
  loadWallets();
}

function historyRow(event) {
  return `
    <tr>
      <td><strong>${formatDateTime(event.detected_at)}</strong></td>
      <td><span class="event-type">${escapeHtml(String(event.event_type || "").replaceAll("_", " "))}</span></td>
      <td><strong>${escapeHtml(event.wallet_label)}</strong><small>${escapeHtml(event.wallet_address)}</small></td>
      <td><strong>${escapeHtml(event.market_title)}</strong></td>
      <td>${escapeHtml(event.outcome)}</td>
      <td>${escapeHtml(event.league || event.category)}</td>
      <td class="mono">${formatMoney(event.current_value ?? event.position_size_usd)}</td>
    </tr>
  `;
}

async function loadHistory() {
  const params = new URLSearchParams({
    q: document.getElementById("history-search").value,
    wallet: document.getElementById("history-wallet").value,
    sport: document.getElementById("history-sport").value,
    league: document.getElementById("history-league").value,
    event_type: document.getElementById("history-event-type").value,
    start: document.getElementById("history-start").value,
    end: document.getElementById("history-end").value ? document.getElementById("history-end").value + "T23:59:59" : "",
    sort: document.getElementById("history-sort").value,
    page: String(appState.pageNumber),
    per_page: "50",
  });
  const body = document.getElementById("history-body");
  try {
    const payload = await fetchJson(`/api/history?${params.toString()}`);
    document.getElementById("history-result-count").textContent = `${payload.total} event${payload.total === 1 ? "" : "s"}`;
    body.innerHTML = payload.data.length ? payload.data.map(historyRow).join("") : `<tr><td colspan="7">${emptyState("No history matches", "Adjust the search, wallet, league, or date range.")}</td></tr>`;
    setOptions(document.getElementById("history-sport"), payload.data.map((row) => row.category), "All sports");
    setOptions(document.getElementById("history-league"), payload.data.map((row) => row.league), "All leagues");
    const pagination = document.getElementById("history-pagination");
    pagination.innerHTML = paginationMarkup(payload);
    pagination.querySelectorAll("button[data-page]").forEach((button) => button.addEventListener("click", () => { appState.pageNumber = Number(button.dataset.page); loadHistory(); }));
  } catch (error) {
    body.innerHTML = `<tr><td colspan="7">${errorState(error.message)}</td></tr>`;
  }
}

async function bindHistory() {
  try {
    const wallets = await fetchJson("/api/wallets");
    setOptions(document.getElementById("history-wallet"), wallets.data.map((wallet) => wallet.label), "All wallets");
  } catch {}
  document.getElementById("history-search").addEventListener("input", debounce(() => { appState.pageNumber = 1; loadHistory(); }));
  ["history-wallet", "history-sport", "history-league", "history-event-type", "history-start", "history-end", "history-sort"].forEach((id) => document.getElementById(id).addEventListener("change", () => { appState.pageNumber = 1; loadHistory(); }));
  loadHistory();
}

function trackerRow(row) {
  const snapshot = row.snapshot || {};
  const pnl = number(row.profit_loss);
  return `
    <tr>
      <td><strong>${escapeHtml(snapshot.event_title || snapshot.market_title)}</strong><small>${escapeHtml(snapshot.market_title)} · ${formatDateTime(snapshot.event_start_time)}</small></td>
      <td><strong>${escapeHtml(snapshot.recommended_side)}</strong><small>Sharp avg ${formatCents(snapshot.sharp_average_entry_price)}</small></td>
      <td class="mono">${snapshot.sharps_count ?? 0}</td>
      <td class="mono">${snapshot.confidence_score ?? "n/a"}</td>
      <td class="mono">${formatCents(snapshot.effective_entry_price)}</td>
      <td class="mono">${formatPercent(snapshot.estimated_win_probability)}</td>
      <td><strong>${formatMoney(row.recommended_amount)}</strong><small>${formatPercent(snapshot.final_recommended_fraction)} · ${formatUnits(row.recommended_units)}</small></td>
      <td><span class="status-label ${escapeHtml(row.status)}">${escapeHtml(row.status)}</span></td>
      <td class="mono ${pnl === null ? "" : pnl >= 0 ? "positive" : "negative"}">${pnl === null ? "Open" : formatMoney(pnl)}</td>
      <td class="mono">${formatMoney(row.running_bankroll)}</td>
    </tr>
  `;
}

function drawTrackerChart(graph) {
  const points = (graph || []).map((point, index) => ({ timestamp: point.timestamp || index, value: Number(point.bankroll) })).filter((point) => Number.isFinite(point.value));
  drawLineChart(document.getElementById("tracker-chart"), points, { format: (value) => formatCompactMoney(value) });
}

async function loadTracker() {
  const params = new URLSearchParams({
    q: document.getElementById("tracker-search").value,
    status: document.getElementById("tracker-status").value,
    min_sharps: document.getElementById("tracker-sharps").value,
    result: document.getElementById("tracker-result").value,
    graph_range: appState.graphRange,
    page: String(appState.pageNumber),
    per_page: "50",
  });
  const body = document.getElementById("tracker-body");
  try {
    const payload = await fetchJson(`/api/bet-tracker?${params.toString()}`);
    const summary = payload.summary || {};
    document.getElementById("tracker-result-count").textContent = `${payload.pagination.total} tracked`;
    document.getElementById("tracker-starting-bankroll").textContent = formatMoney(summary.starting_bankroll);
    document.getElementById("tracker-metrics").innerHTML = [
      metricCard("Current Bankroll", formatMoney(summary.current_bankroll), "Replayed from frozen stake percentages", "ph-vault"),
      metricCard("Realized P/L", formatMoney(summary.realized_profit_loss), "Settled bets only", "ph-chart-line"),
      metricCard("ROI", formatPercent(summary.roi), "Realized return on starting bankroll", "ph-percent"),
      metricCard("Tracked Bets", String(summary.total_tracked_bets || 0), "Immutable recommendation snapshots", "ph-list-checks"),
      metricCard("Record", `${summary.wins || 0}-${summary.losses || 0}`, `${summary.pushes_voids || 0} pushes or voids`, "ph-trophy"),
      metricCard("Win Rate", summary.win_rate === null ? "Pending" : formatPercent(summary.win_rate), "Resolved wins and losses", "ph-target"),
      metricCard("Open Exposure", formatMoney(summary.open_exposure), "Not included in realized P/L", "ph-lock-open"),
      metricCard("Max Drawdown", formatPercent(summary.maximum_drawdown), "Peak-to-trough replay decline", "ph-trend-down"),
    ].join("");
    body.innerHTML = payload.data.length ? payload.data.map(trackerRow).join("") : `<tr><td colspan="10">${emptyState("No tracked recommendations yet", "A verified Today trade is added automatically only when its calculated stake is positive.")}</td></tr>`;
    drawTrackerChart(payload.graph);
    const pagination = document.getElementById("tracker-pagination");
    pagination.innerHTML = paginationMarkup(payload.pagination);
    pagination.querySelectorAll("button[data-page]").forEach((button) => button.addEventListener("click", () => { appState.pageNumber = Number(button.dataset.page); loadTracker(); }));
  } catch (error) {
    body.innerHTML = `<tr><td colspan="10">${errorState(error.message)}</td></tr>`;
  }
}

function bindTracker() {
  document.getElementById("tracker-search").addEventListener("input", debounce(() => { appState.pageNumber = 1; loadTracker(); }));
  ["tracker-status", "tracker-sharps", "tracker-result"].forEach((id) => document.getElementById(id).addEventListener("change", () => { appState.pageNumber = 1; loadTracker(); }));
  document.querySelectorAll("#graph-range button").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll("#graph-range button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    appState.graphRange = button.dataset.range;
    loadTracker();
  }));
  loadTracker();
}

function bindNavigation() {
  const toggle = document.getElementById("mobile-nav-toggle");
  toggle?.addEventListener("click", () => {
    const links = document.getElementById("primary-links");
    links.classList.toggle("open");
    toggle.setAttribute("aria-expanded", String(links.classList.contains("open")));
  });
  const pauseControls = document.querySelectorAll("[data-refresh-toggle]");
  if (pauseControls.length) {
    const renderPause = () => pauseControls.forEach((control) => {
      const mobile = control.classList.contains("mobile-nav-pause");
      control.setAttribute("aria-pressed", String(appState.paused));
      control.querySelector("i").className = appState.paused ? "ph ph-play" : "ph ph-pause";
      control.querySelector("span").textContent = appState.paused
        ? (mobile ? "Resume refresh" : "Resume")
        : (mobile ? "Pause refresh" : "Pause");
      control.title = appState.paused ? "Resume automatic 15-second refresh" : "Pause automatic 15-second refresh";
    });
    renderPause();
    pauseControls.forEach((control) => control.addEventListener("click", () => {
      appState.paused = !appState.paused;
      localStorage.setItem("iconbets-refresh-paused", String(appState.paused));
      renderPause();
      showToast(appState.paused ? "Automatic refresh paused" : "Automatic refresh resumed", "success");
      if (!appState.paused) refreshCurrentPage();
    }));
  }
}

function refreshCurrentPage() {
  if (appState.paused) return;
  if (page === "overview") loadOverview();
  if (page === "trades") loadTrades();
  if (page === "live-positions") loadPositions();
  if (page === "wallets") loadWallets();
  if (page === "position-history") loadHistory();
  if (page === "bet-tracker") loadTracker();
  loadGlobalStatus();
}

function initialize() {
  bindNavigation();
  loadGlobalStatus();
  if (page === "overview") loadOverview();
  if (page === "trades") bindTrades();
  if (page === "live-positions") bindPositions();
  if (page === "wallets") bindWallets();
  if (page === "position-history") bindHistory();
  if (page === "bet-tracker") bindTracker();
  window.setInterval(refreshCurrentPage, AUTO_REFRESH_MS);
}

initialize();
