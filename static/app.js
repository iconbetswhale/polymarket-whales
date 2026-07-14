const page = document.body.dataset.page;
const AUTO_REFRESH_MS = 15000;
const appState = {
  paused: localStorage.getItem("iconbets-refresh-paused") === "true",
  selectedTradeId: null,
  trades: [],
  pageNumber: 1,
  graphRange: "month",
  personalTradeId: null,
  trackerDiagnostics: null,
  trackerBankroll: null,
  personalTrackerBankroll: null,
  trackerView: null,
  trackerCache: { model: null, personal: null },
  trackerPage: { model: 1, personal: 1 },
  userSettings: null,
  sizingBankrollDirty: false,
  bankrollSavePending: false,
  account: { authenticated: false, email: null },
  appliedEntryPriceFilters: { minEntryCents: "", maxEntryCents: "" },
  executionOdds: {},
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

function formatOptionalMoney(value, compact = false) {
  return number(value) === null ? "N/A" : compact ? formatCompactMoney(value) : formatMoney(value);
}

function formatOptionalCents(value) {
  return number(value) === null ? "N/A" : formatCents(value);
}

function formatRelativeSize(value) {
  const parsed = number(value);
  return parsed === null ? "N/A" : `${parsed.toFixed(1)}x`;
}

function formatShares(value) {
  const parsed = number(value);
  if (parsed === null) return "N/A";
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: parsed >= 100 ? 0 : 1,
  }).format(parsed);
}

function humanizeMarketType(value) {
  if (!value) return "Market";
  return String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function sportIcon(category) {
  const icons = {
    baseball: "ph-baseball",
    basketball: "ph-basketball",
    football: "ph-football",
    hockey: "ph-hockey",
    soccer: "ph-soccer-ball",
    tennis: "ph-tennis-ball",
  };
  return icons[String(category || "").toLowerCase()] || "ph-trophy";
}

function tradeMetricChip(icon, value, tooltip, tone = "") {
  return `<span class="trade-metric-chip ${tone}" title="${escapeHtml(tooltip)}" aria-label="${escapeHtml(tooltip)}: ${escapeHtml(value)}"><i class="ph ${icon}" aria-hidden="true"></i><strong>${escapeHtml(value)}</strong></span>`;
}

function slippageComparison(userEntry, whaleEntry, providedFraction = null) {
  const userPrice = number(userEntry);
  const whalePrice = number(whaleEntry);
  const supplied = number(providedFraction);
  if (userPrice === null || whalePrice === null || whalePrice <= 0) return null;
  const fraction = supplied ?? ((userPrice - whalePrice) / whalePrice);
  const percent = fraction * 100;
  const formatted = `${percent > 0 ? "+" : ""}${percent.toFixed(1)}%`;
  const tone = percent > 0.0001 ? "worse" : percent < -0.0001 ? "better" : "same";
  const severity = Math.abs(percent) < 3 ? "slightly worse" : Math.abs(percent) <= 5 ? "worse" : "much worse";
  const comparison = tone === "worse"
    ? severity
    : tone === "better"
      ? "better"
      : "the same";
  return { fraction, percent, formatted, tone, comparison, userPrice, whalePrice };
}

function slippageMetricChip(comparison) {
  if (!comparison) {
    return tradeMetricChip("ph-arrows-left-right", "N/A", "Entry slippage unavailable");
  }
  const direction = comparison.tone === "worse" ? "worse" : comparison.tone === "better" ? "better" : "unchanged";
  const aria = `${comparison.formatted} slippage, ${direction} than the tracked whale's entry`;
  return `
    <button class="trade-metric-chip slippage-chip ${comparison.tone}" type="button" data-testid="slippage-tooltip-trigger" aria-expanded="false" aria-label="${escapeHtml(aria)}">
      <i class="ph ph-arrows-left-right" aria-hidden="true"></i>
      <strong>${escapeHtml(comparison.formatted)}</strong>
      <span class="slippage-tooltip" role="tooltip">
        <span>You're now getting a <strong>${escapeHtml(comparison.comparison)}</strong> price of <strong>${escapeHtml(formatCents(comparison.userPrice))}</strong>, compared to the tracked whale's <strong>${escapeHtml(formatCents(comparison.whalePrice))}</strong>.</span>
        <span class="slippage-tier ideal"><i class="ph ph-circle" aria-hidden="true"></i><strong>Under 3%</strong><em>- ideal</em></span>
        <span class="slippage-tier acceptable"><i class="ph ph-circle" aria-hidden="true"></i><strong>3-5%</strong><em>- acceptable</em></span>
        <span class="slippage-tier danger"><i class="ph ph-circle" aria-hidden="true"></i><strong>Over 5%</strong><em>- edge likely gone</em></span>
      </span>
    </button>
  `;
}

function walletMeta(label, value, tooltip = "") {
  if (!value && value !== 0) return "";
  const tooltipAttributes = tooltip
    ? ` title="${escapeHtml(tooltip)}" aria-label="${escapeHtml(`${label}: ${value}. ${tooltip}`)}"`
    : "";
  return `<span${tooltipAttributes}><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></span>`;
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
  if (!response.ok) {
    const error = new Error(payload.error || `Request failed (${response.status})`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
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

function trackerEmptyState() {
  return `<div class="empty-state"><i class="ph ph-binoculars" aria-hidden="true"></i><h2>No model recommendations tracked yet</h2><p>The shared Model Tracker automatically records every positive-stake recommendation from the Today tab.</p></div>`;
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

function renderAccountState(account = {}) {
  appState.account = {
    authenticated: Boolean(account.authenticated),
    email: account.email || null,
  };
  const status = document.getElementById("account-status");
  const form = document.getElementById("account-form");
  const authenticated = document.getElementById("account-authenticated");
  const email = document.getElementById("account-email");
  if (status) status.textContent = appState.account.authenticated ? "Synced" : "Account";
  if (form) form.hidden = appState.account.authenticated;
  if (authenticated) authenticated.hidden = !appState.account.authenticated;
  if (email) email.textContent = appState.account.email || "";
}

async function loadAccountState() {
  try {
    renderAccountState(await fetchJson("/api/auth/session"));
  } catch (_error) {
    renderAccountState({ authenticated: false });
  }
}

function openAccountDialog() {
  const dialog = document.getElementById("account-dialog");
  if (!dialog) return;
  document.getElementById("account-error").textContent = "";
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  if (!appState.account.authenticated) document.getElementById("account-email-input")?.focus();
}

function closeAccountDialog() {
  const dialog = document.getElementById("account-dialog");
  if (!dialog) return;
  document.getElementById("account-form")?.reset();
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
}

async function submitAccount(mode) {
  const form = document.getElementById("account-form");
  const error = document.getElementById("account-error");
  const buttons = form.querySelectorAll("button");
  if (!form.reportValidity()) return;
  buttons.forEach((button) => { button.disabled = true; });
  error.textContent = "";
  try {
    const account = await fetchJson(`/api/auth/${mode}`, {
      method: "POST",
      body: JSON.stringify({
        email: document.getElementById("account-email-input").value,
        password: document.getElementById("account-password").value,
      }),
    });
    renderAccountState(account);
    closeAccountDialog();
    showToast(mode === "register" ? "Account created. Your settings are now synced." : "Signed in. Your synced settings are loaded.", "success");
    window.location.reload();
  } catch (requestError) {
    error.textContent = requestError.message;
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

function bindAccount() {
  document.getElementById("account-open")?.addEventListener("click", openAccountDialog);
  document.getElementById("account-close")?.addEventListener("click", closeAccountDialog);
  document.getElementById("account-dialog")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeAccountDialog();
  });
  document.getElementById("account-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    submitAccount("login");
  });
  document.getElementById("account-register")?.addEventListener("click", () => submitAccount("register"));
  document.getElementById("account-logout")?.addEventListener("click", async () => {
    try {
      await fetchJson("/api/auth/logout", { method: "POST" });
      showToast("Signed out. This browser now uses a new private profile.", "success");
      window.location.reload();
    } catch (error) {
      showToast(error.message, "error");
    }
  });
  loadAccountState();
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

function weightedSharpLabel(value) {
  const parsed = number(value);
  return parsed === null ? "N/A" : parsed.toFixed(1);
}

function sharpCompositionLabel(trade) {
  const raw = number(trade.raw_sharp_count ?? trade.agreeing_wallet_count) || 0;
  const leads = number(trade.lead_sharp_count) || 0;
  const supporting = number(trade.supporting_sharp_count) || 0;
  return `${raw} Sharps | ${leads} Lead | ${supporting} Supporting | ${weightedSharpLabel(trade.weighted_sharp_count)} weighted`;
}

function confidenceClass(score) {
  const value = Number(score || 0);
  if (value >= 100) return "premium";
  if (value >= 90) return "elite";
  if (value >= 80) return "high";
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
    minEntryCents: params.get("minEntryCents") || "",
    maxEntryCents: params.get("maxEntryCents") || "",
    custom_start: params.get("custom_start") || "",
    custom_end: params.get("custom_end") || "",
    show_hidden: params.get("show_hidden") === "true",
  };
}

function applyTradeFiltersToControls(filters) {
  appState.appliedEntryPriceFilters = {
    minEntryCents: filters.minEntryCents || "",
    maxEntryCents: filters.maxEntryCents || "",
  };
  const mapping = {
    "trade-search": "q",
    "trade-date-range": "date_range",
    "trade-sharps": "min_sharps",
    "trade-confidence": "min_confidence",
    "trade-sport": "sport",
    "trade-league": "league",
    "trade-wallet": "wallet",
    "min-entry-cents": "minEntryCents",
    "max-entry-cents": "maxEntryCents",
    "custom-start": "custom_start",
    "custom-end": "custom_end",
    "show-hidden-trades": "show_hidden",
  };
  Object.entries(mapping).forEach(([id, key]) => {
    const element = document.getElementById(id);
    if (!element) return;
    if (element.type === "checkbox") element.checked = Boolean(filters[key]);
    else element.value = filters[key];
  });
  document.querySelectorAll(".custom-time").forEach((field) => {
    field.hidden = filters.date_range !== "custom";
  });
  updateSharePriceSummary();
  if (filters.date_range === "custom") setMoreFiltersExpanded(true);
}

function formatEntryCents(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "";
  return `${Number.isInteger(parsed) ? parsed.toFixed(0) : parsed.toFixed(1)}¢`;
}

function updateSharePriceSummary() {
  const minimum = document.getElementById("min-entry-cents")?.value.trim() || "";
  const maximum = document.getElementById("max-entry-cents")?.value.trim() || "";
  const summary = document.getElementById("share-price-summary");
  const filter = document.getElementById("share-price-filter");
  if (!summary || !filter) return;
  if (minimum && maximum) summary.textContent = `${formatEntryCents(minimum)}–${formatEntryCents(maximum)}`;
  else if (minimum) summary.textContent = `${formatEntryCents(minimum)} minimum`;
  else if (maximum) summary.textContent = `${formatEntryCents(maximum)} maximum`;
  else summary.textContent = "All";
  filter.classList.toggle("active", Boolean(minimum || maximum));
}

function validateSharePriceControls() {
  const minimumValue = document.getElementById("min-entry-cents").value.trim();
  const maximumValue = document.getElementById("max-entry-cents").value.trim();
  const minimum = minimumValue === "" ? null : Number(minimumValue);
  const maximum = maximumValue === "" ? null : Number(maximumValue);
  const error = document.getElementById("share-price-error");
  let message = "";
  const validPrecision = (value) => Math.abs((value * 10) - Math.round(value * 10)) < 1e-9;
  if (minimum !== null && (!(minimum > 0 && minimum < 100) || !validPrecision(minimum))) {
    message = "Minimum must be between 0 and 100 cents with at most one decimal place.";
  } else if (maximum !== null && (!(maximum > 0 && maximum < 100) || !validPrecision(maximum))) {
    message = "Maximum must be between 0 and 100 cents with at most one decimal place.";
  } else if (minimum !== null && maximum !== null && minimum > maximum) {
    message = "Minimum share price cannot exceed maximum share price.";
  }
  error.textContent = message;
  updateSharePriceSummary();
  return message === "";
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
    minEntryCents: appState.appliedEntryPriceFilters.minEntryCents,
    maxEntryCents: appState.appliedEntryPriceFilters.maxEntryCents,
    custom_start: document.getElementById("custom-start").value,
    custom_end: document.getElementById("custom-end").value,
    show_hidden: document.getElementById("show-hidden-trades").checked,
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

function personalExposureWarning(trade) {
  const exposure = trade.personalExposureSummary || {};
  if (!exposure.type || exposure.type === "none") return "";
  const aggregate = exposure.aggregate || {};
  const red = exposure.type === "exact" || exposure.type === "opposing";
  const icon = red ? "ph-warning" : "ph-warning-circle";
  const tone = red ? "danger" : "caution";
  const details = [
    aggregate.entryCount ? `${aggregate.entryCount} personal ${aggregate.entryCount === 1 ? "entry" : "entries"}` : null,
    number(aggregate.averageEntry) !== null ? `Average entry ${formatCents(aggregate.averageEntry)}` : null,
    number(aggregate.totalShares) !== null && aggregate.totalShares > 0 ? `${formatShares(aggregate.totalShares)} shares` : null,
    number(aggregate.totalPositionCost) !== null && aggregate.totalPositionCost > 0 ? `${formatMoney(aggregate.totalPositionCost)} position cost` : null,
    aggregate.latestTrackedAt ? `Tracked ${formatDateTime(aggregate.latestTrackedAt)}` : null,
  ].filter(Boolean);
  return `
    <button class="personal-warning ${tone}" type="button" data-testid="personal-exposure-warning" aria-expanded="false" aria-label="${escapeHtml(exposure.title)}">
      <i class="ph ${icon}" aria-hidden="true"></i>
      <span class="exposure-tooltip" role="tooltip"><strong>${escapeHtml(exposure.title)}</strong><span>${escapeHtml(exposure.message)}</span>${details.length ? `<small>${escapeHtml(details.join(" | "))}</small>` : ""}</span>
    </button>
  `;
}

function annotateExecutionMovements(trades) {
  const nextOdds = { ...appState.executionOdds };
  trades.forEach((trade) => {
    (trade.executionOptions || []).forEach((option) => {
      const current = number(option.americanOdds);
      const key = `${trade.id}:${option.providerKey}:${option.selectionId}`;
      const previous = number(appState.executionOdds[key]);
      option.priceMovement = "";
      if (current !== null && previous !== null && current !== previous) {
        option.priceMovement = current > previous ? "price-improved" : "price-worsened";
      }
      if (current !== null) nextOdds[key] = current;
    });
  });
  appState.executionOdds = nextOdds;
}

function executionOptionButton(trade, option) {
  if (option.matchingConfidence !== "Exact") return "";
  const providerName = option.providerName || "Exchange";
  const providerKey = String(option.providerKey || "provider").toLowerCase();
  const displayOdds = option.isAvailable ? option.displayOdds : "Unavailable";
  const movement = option.priceMovement || "";
  const polymarketClass = providerKey === "polymarket" ? " polymarket-price-link" : "";
  const classes = `execution-option execution-option--${providerKey}${polymarketClass} ${movement}`.trim();
  const tooltip = option.tooltip || `${providerName} Current Best Price`;
  const content = `
    <img src="${escapeHtml(option.logoUrl || "")}" alt="" aria-hidden="true" width="18" height="18">
    <span><small>${escapeHtml(providerName)}</small><strong>${escapeHtml(displayOdds)}</strong></span>
    <span class="execution-option-tooltip" role="tooltip">${escapeHtml(tooltip)}</span>
  `;
  if (!option.isAvailable || !option.deepLink) {
    return `<button class="${escapeHtml(classes)}" type="button" disabled aria-disabled="true" aria-label="${escapeHtml(providerName)} is unavailable">${content}</button>`;
  }
  return `
    <a class="${escapeHtml(classes)}" href="${escapeHtml(option.deepLink)}" target="_blank" rel="noopener noreferrer" aria-label="Open ${escapeHtml(trade.outcome)} on ${escapeHtml(providerName)} at ${escapeHtml(displayOdds)}">
      ${content}
    </a>
  `;
}

function executionToolbar(trade) {
  const options = (trade.executionOptions || []).filter((option) => option.matchingConfidence === "Exact");
  return `<span class="execution-toolbar" aria-label="Execution options">${options.map((option) => executionOptionButton(trade, option)).join("")}</span>`;
}

function tradeCard(trade) {
  const recommendation = trade.recommendation || {};
  const card = trade.card || {};
  const selected = trade.id === appState.selectedTradeId;
  const primary = trade.primary_trader || {};
  const betAmount = card.trader_bet_amount ?? primary.amount;
  const traderEntry = card.trader_average_entry_price ?? recommendation.sharp_average_entry_price;
  const relativeSize = card.relative_bet_size ?? primary.relative_units;
  const categoryHitRate = card.category_hit_rate;
  const currentPrice = card.current_actionable_price ?? recommendation.current_user_entry_price;
  const slippage = slippageComparison(
    currentPrice,
    traderEntry,
    card.slippage_fraction ?? recommendation.price_slippage_fraction,
  );
  const recommendedAmount = card.recommended_amount ?? recommendation.recommended_amount;
  const recommendedUnits = card.recommended_units ?? recommendation.recommended_units;
  const recommendedShares = card.recommended_shares ?? recommendation.recommended_shares;
  const eventTime = card.event_time || "Time unavailable";
  const sharpLabel = `${trade.agreeing_wallet_count} Sharp${trade.agreeing_wallet_count === 1 ? "" : "s"}`;
  const amountTooltip = number(betAmount) === null
    ? "Trader active exposure unavailable"
    : `Trader active exposure: ${formatMoney(betAmount)}`;
  const relativeTooltip = number(relativeSize) === null
    ? "Relative bet size unavailable"
    : `${formatRelativeSize(relativeSize)} the trader's normal position size`;
  const hitRateText = number(categoryHitRate) === null ? "N/A" : formatPercent(categoryHitRate, 2);
  return `
    <article class="trade-card ${selected ? "selected" : ""} ${trade.isHidden ? "hidden-trade" : ""}" role="button" tabindex="0" data-testid="trade-card" data-trade-id="${escapeHtml(trade.id)}" aria-pressed="${selected}" aria-label="Open details for ${escapeHtml(trade.event_title || trade.market_title)}, ${escapeHtml(trade.outcome)}">
      <span class="trade-identity">
        <span class="trade-score-cluster"><span class="trade-score ${confidenceClass(trade.confidence_score)}"><strong>${escapeHtml(trade.confidence_score)}</strong><small>Confidence</small></span>${personalExposureWarning(trade)}${trade.isHidden ? '<span class="hidden-badge">Hidden</span>' : ""}</span>
        <span class="trade-event-copy">
          <span class="trade-kicker"><i class="ph ${sportIcon(trade.category)}" aria-hidden="true"></i>${escapeHtml(trade.category || "Sports")} · ${escapeHtml(trade.league || "Market")}</span>
          <strong class="trade-event">${escapeHtml(trade.event_title || trade.market_title)}</strong>
          <span class="trade-market">${escapeHtml(humanizeMarketType(trade.sports_market_type))} · ${escapeHtml(trade.market_title || "Market")}</span>
        </span>
      </span>
      <span class="trade-decision">
        <span class="trade-metrics-row">
          ${tradeMetricChip("ph-calendar-blank", eventTime, "Scheduled event start in Eastern Time", "time")}
          ${tradeMetricChip("ph-coins", formatOptionalMoney(betAmount, true), amountTooltip)}
          ${slippageMetricChip(slippage)}
          ${tradeMetricChip("ph-arrow-up-right", formatRelativeSize(relativeSize), relativeTooltip)}
          ${tradeMetricChip("ph-target", hitRateText, "Adjusted trader hit rate in this category")}
        </span>
        <span class="trade-selection">
          <span class="trade-pick"><small>Pick · ${escapeHtml(sharpLabel)}</small><strong>${escapeHtml(trade.outcome)}</strong></span>
          <span class="trade-recommendation"><small>Recommended</small><strong>${escapeHtml(formatShares(recommendedShares))} shares</strong><em>${escapeHtml(formatOptionalMoney(recommendedAmount))} · ${escapeHtml(formatUnits(recommendedUnits))}</em></span>
          ${executionToolbar(trade)}
          <span class="trade-card-actions">
            ${trade.isHidden
              ? `<button class="trade-restore-action" type="button" data-testid="restore-trade-action" data-hidden-id="${escapeHtml(trade.hiddenRecordId)}" title="Restore this trade" aria-label="Restore this trade to Trades to Play"><i class="ph ph-arrow-counter-clockwise" aria-hidden="true"></i></button>`
              : `<button class="trade-hide-action" type="button" data-testid="hide-trade-action" data-trade-id="${escapeHtml(trade.id)}" title="Hide this trade" aria-label="Hide this trade from Trades to Play"><i class="ph ph-eye-slash" aria-hidden="true"></i></button>`}
            <button class="tracker-quick-action" type="button" data-testid="personal-tracker-action" data-trade-id="${escapeHtml(trade.id)}" title="Track this personal trade" aria-label="Track ${escapeHtml(trade.outcome)} in Personal Tracking"><i class="ph ph-plus" aria-hidden="true"></i><span>Track</span></button>
          </span>
        </span>
      </span>
      <i class="ph ph-caret-right trade-caret" aria-hidden="true"></i>
    </article>
  `;
}

function openPersonalTracker(trade) {
  const dialog = document.getElementById("personal-tracker-dialog");
  const summary = document.getElementById("personal-tracker-summary");
  if (!dialog || !summary) return;
  appState.personalTradeId = trade.id;
  const recommendation = trade.recommendation || {};
  const card = trade.card || {};
  const currentEntry = card.current_actionable_price ?? recommendation.current_user_entry_price;
  const recommendedShares = card.recommended_shares ?? recommendation.recommended_shares;
  summary.innerHTML = `
    <div><span>Event</span><strong>${escapeHtml(trade.event_title || trade.market_title)}</strong></div>
    <div><span>Selection</span><strong>${escapeHtml(trade.outcome)}</strong></div>
    <div><span>Recommendation</span><strong>${escapeHtml(formatOptionalMoney(card.recommended_amount ?? recommendation.recommended_amount))}</strong></div>
    <div><span>Current entry</span><strong>${escapeHtml(formatOptionalCents(currentEntry))}</strong></div>
  `;
  document.getElementById("personal-entry-price").value = number(currentEntry) === null ? "" : (Number(currentEntry) * 100).toFixed(1);
  document.getElementById("personal-shares").value = number(recommendedShares) === null ? "" : Number(recommendedShares).toFixed(2);
  document.getElementById("personal-fees").value = "0";
  document.getElementById("personal-conflict-check").checked = false;
  updatePersonalPurchaseTotal();
  renderPurchaseExposureNotice(trade.personalExposureSummary || {});
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
}

function renderPurchaseExposureNotice(exposure) {
  const notice = document.getElementById("personal-tracker-exposure");
  const conflict = document.getElementById("personal-conflict-confirmation");
  const conflictCheck = document.getElementById("personal-conflict-check");
  const submit = document.getElementById("personal-tracker-submit");
  if (!notice || !conflict || !submit) return;
  const aggregate = exposure.aggregate || {};
  conflict.hidden = exposure.type !== "opposing";
  conflictCheck.required = exposure.type === "opposing";
  if (!exposure.type || exposure.type === "none") {
    notice.hidden = true;
    notice.innerHTML = "";
    submit.innerHTML = '<i class="ph ph-check" aria-hidden="true"></i>Track purchase';
    return;
  }
  const tone = exposure.type === "same_event" ? "caution" : "danger";
  const icon = exposure.type === "same_event" ? "ph-warning-circle" : "ph-warning";
  const existing = aggregate.entryCount
    ? `${aggregate.entryCount} ${aggregate.entryCount === 1 ? "fill" : "fills"} | ${formatShares(aggregate.totalShares)} shares | ${formatMoney(aggregate.totalPositionCost)} position cost | ${formatCents(aggregate.averageEntry)} average entry | ${formatMoney(aggregate.totalFees)} fees`
    : "";
  notice.className = `personal-exposure-notice ${tone}`;
  notice.hidden = false;
  notice.innerHTML = `<i class="ph ${icon}" aria-hidden="true"></i><span><strong>${escapeHtml(exposure.type === "opposing" ? "Conflicting personal position" : exposure.title)}</strong>${escapeHtml(exposure.message)}${existing ? `<small>${escapeHtml(existing)}</small>` : ""}</span>`;
  submit.innerHTML = exposure.type === "opposing"
    ? '<i class="ph ph-warning" aria-hidden="true"></i>Add opposing purchase'
    : exposure.type === "exact"
      ? '<i class="ph ph-plus" aria-hidden="true"></i>Add another purchase'
      : '<i class="ph ph-check" aria-hidden="true"></i>Track purchase';
}

function updatePersonalPurchaseTotal() {
  const entryCents = number(document.getElementById("personal-entry-price")?.value) || 0;
  const shares = number(document.getElementById("personal-shares")?.value) || 0;
  const fees = number(document.getElementById("personal-fees")?.value) || 0;
  const cost = (entryCents / 100) * shares;
  const total = cost + fees;
  const container = document.getElementById("personal-purchase-total");
  if (container) container.innerHTML = `<span>Position Cost</span><strong>${formatMoney(cost)}</strong><small>Total paid ${formatMoney(total)}</small>`;
}

async function savePersonalPurchase(event) {
  event.preventDefault();
  const trade = appState.trades.find((item) => item.id === appState.personalTradeId);
  if (!trade) return;
  const exposure = trade.personalExposureSummary || {};
  const submit = document.getElementById("personal-tracker-submit");
  submit.disabled = true;
  try {
    await fetchJson("/api/personal-bets", {
      method: "POST",
      body: JSON.stringify({
        trade_id: trade.id,
        entry_price: Number(document.getElementById("personal-entry-price").value) / 100,
        shares: Number(document.getElementById("personal-shares").value),
        fees: Number(document.getElementById("personal-fees").value || 0),
        confirm_duplicate: Boolean(exposure.hasExactPersonalPosition),
        confirm_conflict: document.getElementById("personal-conflict-check").checked,
      }),
    });
    closePersonalTracker();
    showToast("Personal purchase tracked", "success");
    await loadTrades();
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    submit.disabled = false;
  }
}

function closePersonalTracker() {
  const dialog = document.getElementById("personal-tracker-dialog");
  if (!dialog) return;
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
  appState.personalTradeId = null;
}

async function hideTrade(tradeId) {
  try {
    await fetchJson("/api/hidden-trades", {
      method: "POST",
      body: JSON.stringify({ trade_id: tradeId }),
    });
    showToast("Trade hidden from your feed", "success");
    await loadTrades();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function restoreHiddenTrade(hiddenId, reopenManager = false) {
  try {
    await fetchJson(`/api/hidden-trades/${encodeURIComponent(hiddenId)}`, { method: "DELETE" });
    showToast("Trade restored", "success");
    await loadTrades();
    if (reopenManager) await loadHiddenTrades();
  } catch (error) {
    showToast(error.message, "error");
  }
}

function hiddenTradeRow(record) {
  return `
    <article class="hidden-trade-row">
      <span><strong>${escapeHtml(record.event_title || record.market_title || "Trade")}</strong><small>${escapeHtml(record.market_title || "Market")} | ${escapeHtml(record.selection || "Selection")}</small></span>
      <span class="hidden-trade-meta"><small>${escapeHtml(record.status)}</small><time>${escapeHtml(formatDateTime(record.hidden_at))}</time></span>
      <button class="button compact ${record.active ? "primary" : "ghost"}" type="button" data-restore-hidden-id="${escapeHtml(record.id)}"><i class="ph ph-arrow-counter-clockwise" aria-hidden="true"></i>Restore</button>
    </article>
  `;
}

async function loadHiddenTrades() {
  const list = document.getElementById("hidden-trades-list");
  if (!list) return;
  list.innerHTML = '<div class="chart-loading">Loading hidden trades...</div>';
  try {
    const payload = await fetchJson("/api/hidden-trades");
    const rows = payload.data || [];
    list.innerHTML = rows.length
      ? rows.map(hiddenTradeRow).join("")
      : emptyState("No hidden trades", "Use the eye-off action on any trade card to hide that exact market and selection.");
    list.querySelectorAll("[data-restore-hidden-id]").forEach((button) => {
      button.addEventListener("click", () => restoreHiddenTrade(button.dataset.restoreHiddenId, true));
    });
    document.getElementById("restore-all-hidden").disabled = rows.length === 0;
  } catch (error) {
    list.innerHTML = errorState(error.message);
  }
}

async function openHiddenTrades() {
  const dialog = document.getElementById("hidden-trades-dialog");
  if (!dialog) return;
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  await loadHiddenTrades();
}

function closeHiddenTrades() {
  const dialog = document.getElementById("hidden-trades-dialog");
  if (!dialog) return;
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
}

async function restoreAllHiddenTrades() {
  try {
    await fetchJson("/api/hidden-trades", { method: "DELETE" });
    showToast("All hidden trades restored", "success");
    closeHiddenTrades();
    await loadTrades();
  } catch (error) {
    showToast(error.message, "error");
  }
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
    ["Raw Sharps", String(trade.raw_sharp_count ?? trade.agreeing_wallet_count)],
    ["Lead Sharps", String(trade.lead_sharp_count ?? 0)],
    ["Supporting Sharps", String(trade.supporting_sharp_count ?? 0)],
    ["Weighted Consensus", weightedSharpLabel(trade.weighted_sharp_count)],
    ["Category Weighting", (trade.supporting_sharp_count || 0) > 0 ? "Supporting counted at 0.5x" : "All Sharps counted at 1.0x"],
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
      <p class="calculation-note">The executable CLOB entry is the baseline probability. Lead Sharps contribute 1.0x and Supporting Sharps contribute 0.5x to evidence before the probability adjustment, Half Kelly, and risk caps are applied.</p>
    </details>
  `;
}

function whyScore(trade, recommendation) {
  const breakdown = trade.score_breakdown || {};
  const slippage = slippageComparison(
    recommendation.current_user_entry_price,
    recommendation.sharp_average_entry_price ?? trade.average_entry_price,
    recommendation.price_slippage_fraction,
  );
  const rows = [
    ["Confidence Score", String(trade.confidence_score ?? "N/A")],
    ["Raw Consensus", `${trade.raw_sharp_count ?? trade.agreeing_wallet_count ?? 0} unique Sharps`],
    ["Lead Sharps", String(trade.lead_sharp_count ?? 0)],
    ["Supporting Sharps", String(trade.supporting_sharp_count ?? 0)],
    ["Weighted Consensus", weightedSharpLabel(trade.weighted_sharp_count)],
    ["Consensus Band", breakdown.consensus_band || "Unavailable"],
    ["Category Composition", formatPercent(breakdown.category_composition)],
    ["Weighted Amount Signal", formatPercent(trade.weighted_amount_signal)],
    ["Weighted Relative Size", formatPercent(trade.weighted_relative_size_signal)],
    ["Entry Slippage", slippage?.formatted || "Unavailable"],
  ];
  return `
    <details class="calculation-details score-details">
      <summary><span><i class="ph ph-chart-line-up" aria-hidden="true"></i>Why this score?</span><i class="ph ph-caret-down" aria-hidden="true"></i></summary>
      <div class="calculation-grid">${rows.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div>
      <p class="calculation-note">Raw unique-wallet agreement sets the score band. Lead and Supporting composition determines how strongly category evidence, amount, relative size, history, and category performance place the trade inside that band.</p>
    </details>
  `;
}

function supportersMarkup(trade) {
  return (trade.supporting_wallets || []).map((wallet) => {
    const role = wallet.is_lead_sharp ? "Lead Sharp" : "Supporting Sharp";
    const category = (wallet.top_category_ids || []).join(", ") || "Top category unresolved";
    const categoryWeight = number(wallet.category_weight);
    const weight = `${(categoryWeight === null ? 0.5 : categoryWeight).toFixed(1)}x model weight`;
    return `
    <a class="supporter-row ${wallet.is_lead_sharp ? "lead-sharp" : "supporting-sharp"}" href="${escapeHtml(wallet.wallet_profile_url || "#")}" target="_blank" rel="noopener noreferrer">
      <span class="supporter-avatar"><i class="ph ph-user" aria-hidden="true"></i></span>
      <span><strong>${escapeHtml(wallet.wallet_label)}</strong><small>${escapeHtml(`${role} | ${category} | ${weight}`)}</small></span>
      <span><strong>${formatMoney(wallet.amount)}</strong><small>${formatUnits(wallet.relative_units)}</small></span>
      <i class="ph ph-arrow-up-right" aria-hidden="true"></i>
    </a>
  `;
  }).join("");
}

function renderTradeDetail(trade) {
  const panel = document.getElementById("trade-detail");
  const recommendation = trade.recommendation || {};
  const slippage = slippageComparison(
    recommendation.current_user_entry_price,
    recommendation.sharp_average_entry_price ?? trade.average_entry_price,
    recommendation.price_slippage_fraction,
  );
  const slippageTone = slippage?.tone === "better" ? "positive" : slippage?.tone === "worse" ? "negative" : "";
  panel.innerHTML = `
    <div class="detail-header">
      <span class="score-badge large ${confidenceClass(trade.confidence_score)}">${escapeHtml(trade.confidence_score)}</span>
      <div><p>${escapeHtml(trade.category || "Sports")} · ${escapeHtml(trade.league || "Market")}</p><h2>${escapeHtml(trade.event_title || trade.market_title)}</h2><span>${escapeHtml(trade.market_title)} · ${escapeHtml(trade.event_time_et)}</span></div>
      <span class="live-price"><small>Executable entry</small><strong>${formatCents(recommendation.current_user_entry_price)}</strong><em>${escapeHtml(trade.agreeing_wallet_count + " Sharp" + (trade.agreeing_wallet_count === 1 ? "" : "s"))}</em></span>
    </div>
    <div class="selection-banner"><span><small>Recommended side</small><strong>${escapeHtml(trade.outcome)}</strong></span><span><small>Recommended bet</small><strong>${escapeHtml(recommendationLabel(recommendation))}</strong></span></div>
    <div class="detail-metric-grid">
      ${detailMetric("Relative Bet Size", formatUnits(trade.primary_trader?.relative_units), "Primary Sharp versus normal size")}
      ${detailMetric("Primary Lead Sharp", formatMoney(trade.primary_trader?.amount), trade.primary_trader?.wallet_label || "Tracked Sharp")}
      ${detailMetric("Entry Slippage", slippage?.formatted || "Unavailable", slippage ? `${formatCents(slippage.userPrice)} user entry vs ${formatCents(slippage.whalePrice)} whale entry` : "Price comparison unavailable", slippageTone)}
      ${detailMetric("Combined Exposure", formatMoney(trade.combined_exposure_exact), `${trade.agreeing_wallet_count} agreeing wallets`)}
      ${detailMetric("Weighted Consensus", weightedSharpLabel(trade.weighted_sharp_count), `${trade.lead_sharp_count || 0} Lead | ${trade.supporting_sharp_count || 0} Supporting`)}
      ${detailMetric("Baseline Probability", formatPercent(recommendation.baseline_probability), "Exact current user entry")}
      ${detailMetric("Estimated Win", formatPercent(recommendation.estimated_win_probability), "After bounded Sharp evidence")}
      ${detailMetric("Half Kelly", formatPercent(recommendation.half_kelly_fraction), "Before risk caps")}
      ${detailMetric("Final Stake", formatPercent(recommendation.final_recommended_fraction, 2), "Percentage frozen in tracker", recommendation.final_recommended_fraction > 0 ? "positive" : "")}
    </div>
    <section class="detail-section personal-exposure-section">
      <div class="section-label"><span>Personal Exposure</span><small>Confirmed Personal Tracker fills only</small></div>
      <div id="personal-exposure-detail"><div class="chart-loading">Loading personal exposure...</div></div>
    </section>
    ${whyScore(trade, recommendation)}
    ${whySizing(recommendation, trade)}
    <section class="detail-section">
      <div class="section-label"><span>Price history</span><small>Polymarket CLOB · real outcome token</small></div>
      <div class="price-chart" id="price-chart"><div class="chart-loading">Loading verified price history…</div></div>
    </section>
    <section class="detail-section">
      <div class="section-label"><span>Sharps on this trade</span><small>${escapeHtml(sharpCompositionLabel(trade))} | exact exposure shown</small></div>
      <div class="supporter-list">${supportersMarkup(trade)}</div>
    </section>
    <div class="detail-actions">
      <a class="button primary" href="${escapeHtml(trade.market_url || "#")}" target="_blank" rel="noopener noreferrer"><i class="ph ph-arrow-square-out" aria-hidden="true"></i>Open Polymarket</a>
      <a class="button ghost" href="${escapeHtml(trade.primary_trader?.wallet_profile_url || "#")}" target="_blank" rel="noopener noreferrer"><i class="ph ph-user" aria-hidden="true"></i>Trader Profile</a>
    </div>
  `;
  loadPriceHistory(trade.clob_token_id, recommendation.current_user_entry_price);
  loadPersonalExposureDetails(trade.id);
}

function personalExposureGroup(title, group, tone = "") {
  const entries = group?.entries || [];
  if (!entries.length) {
    return `<section class="personal-exposure-group"><h3>${escapeHtml(title)}</h3><p>No active personal positions.</p></section>`;
  }
  const aggregate = group.aggregate || {};
  return `
    <section class="personal-exposure-group ${tone}">
      <h3>${escapeHtml(title)}</h3>
      <div class="personal-exposure-aggregate"><strong>${formatShares(aggregate.totalShares)} shares</strong><span>${formatMoney(aggregate.totalPositionCost)} cost</span><span>${formatCents(aggregate.averageEntry)} average</span><span>${formatMoney(aggregate.totalFees)} fees</span></div>
      <div class="personal-fill-list">${entries.map((entry) => `
        <div class="personal-fill-row">
          <span><strong>${escapeHtml(entry.selection || "Selection")}</strong><small>${escapeHtml(entry.marketTitle || "Market")} | ${escapeHtml(formatDateTime(entry.trackedAt))}</small></span>
          <span><strong>${formatShares(entry.shares)} shares</strong><small>${formatCents(entry.entryPrice)} | ${formatMoney(entry.totalPaid)} paid</small></span>
          <button class="personal-fill-remove" type="button" data-fill-id="${escapeHtml(entry.fillId)}" aria-label="Remove this personal fill" title="Remove this personal fill"><i class="ph ph-trash" aria-hidden="true"></i></button>
        </div>
      `).join("")}</div>
    </section>
  `;
}

async function loadPersonalExposureDetails(tradeId) {
  const container = document.getElementById("personal-exposure-detail");
  if (!container) return;
  try {
    const payload = await fetchJson(`/api/personal-exposure?trade_id=${encodeURIComponent(tradeId)}`);
    const groups = payload.data?.groups || {};
    const hasEntries = [groups.exact, groups.opposing, groups.other].some((group) => group?.entries?.length);
    container.innerHTML = hasEntries
      ? [
          personalExposureGroup("Exact Selection", groups.exact, "exact"),
          personalExposureGroup("Opposing Selection", groups.opposing, "opposing"),
          personalExposureGroup("Other Markets on This Event", groups.other, "other"),
        ].join("")
      : '<p class="personal-exposure-empty"><i class="ph ph-shield-check" aria-hidden="true"></i>No active personal exposure is connected to this trade.</p>';
    container.querySelectorAll("[data-fill-id]").forEach((button) => {
      button.addEventListener("click", () => removePersonalFill(button.dataset.fillId));
    });
  } catch (error) {
    container.innerHTML = `<p class="personal-exposure-empty">${escapeHtml(error.message)}</p>`;
  }
}

async function removePersonalFill(fillId) {
  try {
    await fetchJson(`/api/personal-bets/${encodeURIComponent(fillId)}`, { method: "DELETE" });
    showToast("Personal fill removed from active exposure", "success");
    if (page === "tracker" && appState.trackerView === "personal") await loadPersonalTracker();
    else await loadTrades();
  } catch (error) {
    showToast(error.message, "error");
  }
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

function applySizingBankroll(settings, { forceInput = false } = {}) {
  if (!settings) return;
  appState.userSettings = settings;
  const bankroll = number(settings.trades_to_play_bankroll ?? settings.starting_bankroll);
  const input = document.getElementById("bankroll-input");
  const button = document.getElementById("save-bankroll");
  const state = document.getElementById("bankroll-save-state");
  if (input) {
    input.disabled = false;
    input.closest(".money-input")?.classList.remove("bankroll-loading");
    if (forceInput || !appState.sizingBankrollDirty) input.value = bankroll === null ? "" : bankroll.toFixed(2);
  }
  if (button) button.disabled = false;
  if (bankroll !== null) {
    document.getElementById("unit-value").textContent = formatMoney(bankroll * Number(settings.unit_percentage || 0.01));
  }
  if (state && !appState.sizingBankrollDirty) {
    state.textContent = settings.sizing_bankroll_configured
      ? settings.account_authenticated ? "Saved to your account" : "Saved to this browser - sign in to sync"
      : "Configured default - save to make permanent";
    state.dataset.state = settings.sizing_bankroll_configured ? "saved" : "default";
  }
}

async function loadSizingBankroll() {
  const input = document.getElementById("bankroll-input");
  const button = document.getElementById("save-bankroll");
  if (input) input.disabled = true;
  if (button) button.disabled = true;
  try {
    const payload = await fetchJson("/api/user-settings");
    applySizingBankroll(payload.data, { forceInput: true });
  } catch (error) {
    document.getElementById("bankroll-save-state").textContent = `Could not load saved bankroll: ${error.message}`;
  }
}

async function loadTrades() {
  const list = document.getElementById("trade-list");
  const filters = readTradeControls();
  updateTradeUrl(filters);
  const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== "" && value !== false));
  try {
    const payload = await fetchJson(`/api/trades-to-play?${query.toString()}`);
    const trades = payload.data || [];
    annotateExecutionMovements(trades);
    appState.trades = trades;
    if (payload.bankroll) applySizingBankroll(payload.bankroll);
    updateGlobalStatus(payload.status);
    document.getElementById("hidden-trades-count").textContent = String(payload.hiddenCount || 0);
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
        if (event.target.closest("a, button")) return;
        selectTrade(card.dataset.tradeId, true);
      });
      card.addEventListener("keydown", (event) => {
        if (event.target.closest("a, button") || !["Enter", " "].includes(event.key)) return;
        event.preventDefault();
        selectTrade(card.dataset.tradeId, true);
      });
    });
    list.querySelectorAll(".tracker-quick-action").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const trade = appState.trades.find((item) => item.id === button.dataset.tradeId);
        if (trade) openPersonalTracker(trade);
      });
    });
    list.querySelectorAll(".trade-hide-action").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        hideTrade(button.dataset.tradeId);
      });
    });
    list.querySelectorAll(".trade-restore-action").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        restoreHiddenTrade(button.dataset.hiddenId);
      });
    });
    list.querySelectorAll(".slippage-chip").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const expanded = button.getAttribute("aria-expanded") === "true";
        list.querySelectorAll(".slippage-chip").forEach((chip) => chip.setAttribute("aria-expanded", "false"));
        button.setAttribute("aria-expanded", String(!expanded));
      });
    });
    list.querySelectorAll(".personal-warning").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const expanded = button.getAttribute("aria-expanded") === "true";
        list.querySelectorAll(".personal-warning").forEach((warning) => warning.setAttribute("aria-expanded", "false"));
        button.setAttribute("aria-expanded", String(!expanded));
      });
    });
    selectTrade(appState.selectedTradeId);
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
    state.dataset.state = "error";
    return;
  }
  if (appState.bankrollSavePending) return;
  appState.bankrollSavePending = true;
  const button = document.getElementById("save-bankroll");
  button.disabled = true;
  state.textContent = "Saving...";
  state.dataset.state = "saving";
  try {
    const payload = await fetchJson("/api/user-settings", {
      method: "PUT",
      body: JSON.stringify({
        trades_to_play_bankroll: bankroll,
        expected_version: appState.userSettings?.settings_version,
      }),
    });
    appState.sizingBankrollDirty = false;
    applySizingBankroll(payload.data, { forceInput: true });
    state.textContent = "Saved";
    state.dataset.state = "saved";
    await loadTrades();
  } catch (error) {
    if (error.status === 409 && error.payload?.data) {
      appState.sizingBankrollDirty = false;
      applySizingBankroll(error.payload.data, { forceInput: true });
    }
    state.textContent = `Save failed: ${error.message}`;
    state.dataset.state = "error";
  } finally {
    appState.bankrollSavePending = false;
    button.disabled = false;
  }
}

function bindTrades() {
  const initial = tradeFiltersFromUrl();
  applyTradeFiltersToControls(initial);
  const reload = debounce(loadTrades, 280);
  ["trade-search"].forEach((id) => document.getElementById(id).addEventListener("input", reload));
  ["trade-date-range", "trade-sharps", "trade-confidence", "trade-sport", "trade-league", "trade-wallet", "custom-start", "custom-end", "show-hidden-trades"].forEach((id) => {
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
    applyTradeFiltersToControls({ q: "", date_range: "today", min_sharps: "0", min_confidence: "0", sport: "", league: "", wallet: "", minEntryCents: "", maxEntryCents: "", custom_start: "", custom_end: "", show_hidden: false });
    document.getElementById("share-price-error").textContent = "";
    loadTrades();
  });
  document.getElementById("apply-share-price").addEventListener("click", () => {
    if (validateSharePriceControls()) {
      appState.appliedEntryPriceFilters = {
        minEntryCents: document.getElementById("min-entry-cents").value.trim(),
        maxEntryCents: document.getElementById("max-entry-cents").value.trim(),
      };
      loadTrades();
    }
  });
  document.getElementById("clear-share-price").addEventListener("click", () => {
    document.getElementById("min-entry-cents").value = "";
    document.getElementById("max-entry-cents").value = "";
    appState.appliedEntryPriceFilters = { minEntryCents: "", maxEntryCents: "" };
    document.getElementById("share-price-error").textContent = "";
    updateSharePriceSummary();
    loadTrades();
  });
  ["min-entry-cents", "max-entry-cents"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
      document.getElementById("share-price-error").textContent = "";
      updateSharePriceSummary();
    });
    document.getElementById(id).addEventListener("keydown", (event) => {
      if (event.key === "Enter" && validateSharePriceControls()) {
        appState.appliedEntryPriceFilters = {
          minEntryCents: document.getElementById("min-entry-cents").value.trim(),
          maxEntryCents: document.getElementById("max-entry-cents").value.trim(),
        };
        loadTrades();
      }
    });
  });
  document.getElementById("save-bankroll").addEventListener("click", saveBankroll);
  document.getElementById("bankroll-input").addEventListener("input", () => {
    appState.sizingBankrollDirty = true;
    const state = document.getElementById("bankroll-save-state");
    state.textContent = "Unsaved changes";
    state.dataset.state = "unsaved";
  });
  document.getElementById("bankroll-input").addEventListener("keydown", (event) => { if (event.key === "Enter") saveBankroll(); });
  document.getElementById("personal-tracker-close")?.addEventListener("click", closePersonalTracker);
  document.getElementById("personal-tracker-dismiss")?.addEventListener("click", closePersonalTracker);
  document.getElementById("personal-tracker-dialog")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closePersonalTracker();
  });
  document.getElementById("personal-tracker-form")?.addEventListener("submit", savePersonalPurchase);
  ["personal-entry-price", "personal-shares", "personal-fees"].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", updatePersonalPurchaseTotal);
  });
  document.getElementById("hidden-trades-button")?.addEventListener("click", openHiddenTrades);
  document.getElementById("hidden-trades-close")?.addEventListener("click", closeHiddenTrades);
  document.getElementById("hidden-trades-dismiss")?.addEventListener("click", closeHiddenTrades);
  document.getElementById("restore-all-hidden")?.addEventListener("click", restoreAllHiddenTrades);
  document.getElementById("hidden-trades-dialog")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeHiddenTrades();
  });
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
  if (validateSharePriceControls()) loadSizingBankroll().finally(loadTrades);
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
      <button class="address-copy" type="button" data-copy-address="${escapeHtml(wallet.address)}"><span>${escapeHtml(wallet.display_address || wallet.address)}</span><i class="ph ph-copy" aria-hidden="true"></i></button>
      <div class="wallet-stats"><div><span>Open positions</span><strong>${wallet.open_position_count ?? 0}</strong></div><div><span>History events</span><strong>${wallet.historical_position_count ?? 0}</strong></div><div><span>Base unit</span><strong>${wallet.base_unit ? formatMoney(wallet.base_unit) : "Estimating"}</strong></div></div>
      <div class="wallet-sync wallet-meta">${[
        walletMeta("Top category", wallet.top_category_display || wallet.top_category),
        walletMeta("Half unit", wallet.minimum_actionable_exposure_dollars ? formatMoney(wallet.minimum_actionable_exposure_dollars) : null),
        walletMeta("Execution tranche", wallet.typical_execution_tranche_dollars ? `Approx. ${formatMoney(wallet.typical_execution_tranche_dollars)}` : null, "An execution tranche is not a full unit. Individual small fills are aggregated and should not be copied independently."),
        walletMeta("Actionable exposure", wallet.minimum_actionable_exposure_dollars ? `${formatMoney(wallet.minimum_actionable_exposure_dollars)} / ${(wallet.actionable_position_units || 0).toFixed(2)}u` : null, "Signals become actionable only after completed fills are aggregated to this net exposure."),
        walletMeta("Type", wallet.bettor_type),
        walletMeta("Selectivity", wallet.selectivity),
        walletMeta("Hold", wallet.hold_tendency),
        walletMeta("Copyability", wallet.copyability),
        walletMeta("Execution", wallet.execution_style),
        walletMeta("Synced fills", wallet.requires_fill_aggregation ? wallet.deduplicated_fill_count : null),
        walletMeta("Avg. fills / position", wallet.requires_fill_aggregation ? wallet.average_fills_per_aggregated_position : null),
        walletMeta("Settled positions", wallet.requires_fill_aggregation ? wallet.settled_aggregated_position_count : null),
        walletMeta("Fill backfill", wallet.requires_fill_aggregation ? wallet.historical_backfill_status : null),
      ].join("")}</div>
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

function renderTrackerState(tracking = {}) {
  const badge = document.getElementById("tracker-job-state");
  if (!badge) return;
  const state = tracking.status || "stale";
  const labels = { running: "Tracking: Active", paused: "Tracking: Paused", failed: "Tracking: Failed", stale: "Tracking: Stale" };
  badge.textContent = labels[state] || "Tracking: Stale";
  badge.className = `status-label ${state === "running" ? "ready" : state}`;
}

function renderTrackerDiagnostics(diagnostics = {}) {
  appState.trackerDiagnostics = diagnostics;
  renderTrackerState(diagnostics);
  const panel = document.getElementById("tracker-diagnostics");
  if (!panel) return;
  panel.hidden = appState.trackerView !== "model";
  document.getElementById("tracker-diagnostic-grid").innerHTML = [
    metricCard("Last successful run", formatDateTime(diagnostics.last_successful_run, "Never"), "Most recent completed backend job", "ph-check-circle"),
    metricCard("Evaluated", String(diagnostics.recommendations_evaluated || 0), "Today recommendations checked", "ph-magnifying-glass"),
    metricCard("Inserted", String(diagnostics.records_inserted || 0), "New immutable snapshots", "ph-database"),
    metricCard("Duplicates", String(diagnostics.records_skipped_duplicates || 0), "Existing canonical records", "ph-copy"),
    metricCard("Rejected", String(diagnostics.records_rejected || 0), "Explicit eligibility failures", "ph-funnel-x"),
    metricCard("Errors", String(diagnostics.errors || 0), `Next run ${formatDateTime(diagnostics.next_scheduled_run, "Paused")}`, "ph-warning-circle"),
  ].join("");
  const pause = document.getElementById("tracker-pause-job");
  pause.textContent = diagnostics.paused ? "Resume tracking" : "Pause tracking";
  const body = document.getElementById("tracker-rejection-body");
  const rejections = diagnostics.rejections || [];
  body.innerHTML = rejections.length ? rejections.map((row) => `
    <tr>
      <td><strong>${escapeHtml(row.event || "Unknown event")}</strong><small>${escapeHtml(row.market || "Unknown market")}</small></td>
      <td>${escapeHtml(row.selection || "Unavailable")}</td>
      <td>${escapeHtml(formatDateTime(row.event_time))}</td>
      <td class="mono">${formatCents(row.entry_price)}</td>
      <td class="mono">${formatPercent(row.recommended_fraction, 3)}</td>
      <td class="mono">${formatMoney(row.recommended_amount)}</td>
      <td><span class="status-label failed">${escapeHtml(row.rejection_reason)}</span></td>
      <td>${escapeHtml(formatDateTime(row.last_evaluated_at))}</td>
    </tr>`).join("") : `<tr><td colspan="8">${emptyState("No rejected Today recommendations", "The latest backend run did not reject any Today candidates for this bankroll.")}</td></tr>`;
}

function openTrackerAdminDialog() {
  const dialog = document.getElementById("tracker-admin-dialog");
  if (!dialog) return;
  document.getElementById("tracker-admin-error").textContent = "";
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  document.getElementById("tracker-admin-password").focus();
}

function closeTrackerAdminDialog() {
  const dialog = document.getElementById("tracker-admin-dialog");
  if (!dialog) return;
  document.getElementById("tracker-admin-form").reset();
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
}

function openTrackerBankrollDialog() {
  const dialog = document.getElementById("tracker-bankroll-dialog");
  const input = document.getElementById("tracker-bankroll-input");
  if (!dialog || !input) return;
  document.getElementById("tracker-bankroll-error").textContent = "";
  input.value = number(appState.trackerBankroll)?.toFixed(2) || "";
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  input.focus();
  input.select();
}

function closeTrackerBankrollDialog() {
  const dialog = document.getElementById("tracker-bankroll-dialog");
  if (!dialog) return;
  document.getElementById("tracker-bankroll-form").reset();
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
}

async function saveTrackerBankroll(event) {
  event.preventDefault();
  const form = document.getElementById("tracker-bankroll-form");
  const submit = form.querySelector('button[type="submit"]');
  const error = document.getElementById("tracker-bankroll-error");
  const trackerBankroll = number(document.getElementById("tracker-bankroll-input").value);
  if (trackerBankroll === null || trackerBankroll <= 0) {
    error.textContent = "Enter a bankroll greater than zero.";
    return;
  }
  submit.disabled = true;
  error.textContent = "";
  try {
    await fetchJson("/api/model-tracker/settings", {
      method: "PUT",
      body: JSON.stringify({ tracker_bankroll: trackerBankroll }),
    });
    closeTrackerBankrollDialog();
    await loadTracker();
    showToast("Model Tracker replay bankroll updated. Trades to Play is unchanged.", "success");
  } catch (requestError) {
    error.textContent = requestError.message;
  } finally {
    submit.disabled = false;
  }
}

async function loadTrackerDiagnostics(showLogin = false) {
  const response = await fetch("/api/admin/model-tracker/diagnostics", { headers: { "Accept": "application/json" } });
  if (response.status === 403 && showLogin) {
    openTrackerAdminDialog();
    return;
  }
  if (!response.ok) {
    if (showLogin) showToast("Administrator access is required", "error");
    return;
  }
  const payload = await response.json();
  renderTrackerDiagnostics(payload.data || {});
}

function personalTrackerRow(row) {
  const status = String(row.status || "unresolved").toLowerCase();
  const pnl = number(row.profit_loss);
  const active = ["scheduled", "live", "unresolved"].includes(status);
  const eventCopy = `<strong>${escapeHtml(row.event_title || "Unknown event")}</strong><small>${escapeHtml(row.market_title || "Market")} | ${escapeHtml(formatDateTime(row.event_start_time))}</small>`;
  const eventMarkup = row.market_url
    ? `<a class="personal-market-link" href="${escapeHtml(row.market_url)}" target="_blank" rel="noopener noreferrer">${eventCopy}</a>`
    : eventCopy;
  return `
    <tr>
      <td>${eventMarkup}</td>
      <td><strong>${escapeHtml(row.selection || "Selection")}</strong></td>
      <td class="mono">${escapeHtml(formatShares(row.shares))}</td>
      <td class="mono">${escapeHtml(formatCents(row.entry_price))}</td>
      <td class="mono">${escapeHtml(formatMoney(row.position_cost))}</td>
      <td class="mono">${escapeHtml(formatMoney(row.fees))}</td>
      <td><span class="status-label ${escapeHtml(status)}">${escapeHtml(status)}</span></td>
      <td class="mono ${pnl === null ? "" : pnl >= 0 ? "positive" : "negative"}">${pnl === null ? "Open" : escapeHtml(formatMoney(pnl))}</td>
      <td>${escapeHtml(formatDateTime(row.created_at))}</td>
      <td>${active ? `<button class="personal-fill-remove personal-tracker-remove" type="button" data-personal-fill-remove="${escapeHtml(row.fill_id)}" aria-label="Remove ${escapeHtml(row.selection || "personal trade")}" title="Remove this open personal trade"><i class="ph ph-trash" aria-hidden="true"></i></button>` : '<span class="muted">Settled</span>'}</td>
    </tr>
  `;
}

function drawPersonalTrackerChart(graph, hasTrackedBets) {
  const container = document.getElementById("tracker-chart");
  if (!hasTrackedBets) {
    container.innerHTML = emptyState("No personal results yet", "Track a trade from Trades to Play to begin your private bankroll history.");
    return;
  }
  const points = (graph || [])
    .map((point, index) => ({ timestamp: point.timestamp || index, value: Number(point.bankroll) }))
    .filter((point) => Number.isFinite(point.value));
  drawLineChart(container, points, { format: (value) => formatCompactMoney(value) });
}

function renderModelTracker(payload) {
  if (appState.trackerView !== "model") return;
  const summary = payload.summary || {};
  appState.trackerBankroll = payload.bankroll?.tracker_bankroll ?? summary.starting_bankroll;
  document.getElementById("tracker-result-count").textContent = `${payload.pagination.total} tracked`;
  document.getElementById("tracker-starting-bankroll").textContent = formatMoney(summary.starting_bankroll);
  renderTrackerState(payload.tracking || {});
  document.getElementById("tracker-metrics").innerHTML = [
    metricCard("Starting Bankroll", formatMoney(summary.starting_bankroll), "Model replay baseline", "ph-bank"),
    metricCard("Current Bankroll", formatMoney(summary.current_bankroll), "Replayed from frozen stake percentages", "ph-vault"),
    metricCard("Realized P/L", formatMoney(summary.realized_profit_loss), "Settled Model bets only", "ph-chart-line"),
    metricCard("ROI", formatPercent(summary.roi), "Realized return on Model bankroll", "ph-percent"),
    metricCard("Model Bets", String(summary.total_tracked_bets || 0), "Immutable recommendation snapshots", "ph-list-checks"),
    metricCard("Record", `${summary.wins || 0}-${summary.losses || 0}`, `${summary.pushes_voids || 0} pushes or voids`, "ph-trophy"),
    metricCard("Win Rate", summary.win_rate === null ? "Pending" : formatPercent(summary.win_rate), "Resolved Model wins and losses", "ph-target"),
    metricCard("Open Exposure", formatMoney(summary.open_exposure), "Not included in realized P/L", "ph-lock-open"),
    metricCard("Max Drawdown", formatPercent(summary.maximum_drawdown), "Peak-to-trough replay decline", "ph-trend-down"),
  ].join("");
  const body = document.getElementById("tracker-body");
  body.innerHTML = payload.data.length ? payload.data.map(trackerRow).join("") : `<tr><td colspan="10">${trackerEmptyState()}</td></tr>`;
  drawTrackerChart(payload.graph);
  renderTrackerPagination(payload.pagination, "model");
}

function renderPersonalTracker(payload) {
  if (appState.trackerView !== "personal") return;
  const summary = payload.summary || {};
  appState.personalTrackerBankroll = payload.bankroll?.personal_tracker_bankroll ?? summary.starting_bankroll;
  document.getElementById("tracker-result-count").textContent = `${payload.pagination.total} tracked`;
  document.getElementById("personal-starting-bankroll").textContent = formatMoney(summary.starting_bankroll);
  document.getElementById("tracker-metrics").innerHTML = [
    metricCard("Starting Bankroll", formatMoney(summary.starting_bankroll), "Personal performance baseline", "ph-bank"),
    metricCard("Current Bankroll", formatMoney(summary.current_bankroll), "Starting bankroll plus realized P/L", "ph-vault"),
    metricCard("Realized P/L", formatMoney(summary.realized_profit_loss), "Settled personal trades after fees", "ph-chart-line"),
    metricCard("ROI", formatPercent(summary.roi), "Return on Personal starting bankroll", "ph-percent"),
    metricCard("Personal Bets", String(summary.total_tracked_bets || 0), "Manual confirmed purchases only", "ph-list-checks"),
    metricCard("Record", `${summary.wins || 0}-${summary.losses || 0}`, `${summary.pushes_voids || 0} pushes, voids, or canceled`, "ph-trophy"),
    metricCard("Win Rate", summary.win_rate === null ? "Pending" : formatPercent(summary.win_rate), "Resolved personal wins and losses", "ph-target"),
    metricCard("Open Exposure", formatMoney(summary.open_exposure), "Amount paid on unresolved trades", "ph-lock-open"),
    metricCard("Max Drawdown", formatPercent(summary.maximum_drawdown), "Peak-to-trough personal decline", "ph-trend-down"),
  ].join("");
  const body = document.getElementById("tracker-body");
  body.innerHTML = payload.data.length
    ? payload.data.map(personalTrackerRow).join("")
    : `<tr><td colspan="10"><div class="empty-state"><i class="ph ph-user-plus" aria-hidden="true"></i><h2>No personal trades match</h2><p>Use the Track button on a Trades to Play card to add a confirmed purchase.</p><a class="button primary compact" href="/trades"><i class="ph ph-plus" aria-hidden="true"></i>Browse Trades to Play</a></div></td></tr>`;
  body.querySelectorAll("[data-personal-fill-remove]").forEach((button) => {
    button.addEventListener("click", () => removePersonalFill(button.dataset.personalFillRemove));
  });
  drawPersonalTrackerChart(payload.graph, Number(summary.total_tracked_bets || 0) > 0);
  renderTrackerPagination(payload.pagination, "personal");
}

function renderTrackerPagination(pagination, view) {
  const container = document.getElementById("tracker-pagination");
  container.innerHTML = paginationMarkup(pagination);
  container.querySelectorAll("button[data-page]").forEach((button) => button.addEventListener("click", () => {
    appState.trackerPage[view] = Number(button.dataset.page);
    loadTrackerView();
  }));
}

function trackerRequestParams(view) {
  const params = {
    q: document.getElementById("tracker-search").value,
    status: document.getElementById("tracker-status").value,
    result: document.getElementById("tracker-result").value,
    graph_range: appState.graphRange,
    page: String(appState.trackerPage[view]),
    per_page: "50",
  };
  if (view === "model") params.min_sharps = document.getElementById("tracker-sharps").value;
  return new URLSearchParams(params);
}

async function loadTracker() {
  try {
    const payload = await fetchJson(`/api/model-tracker?${trackerRequestParams("model").toString()}`);
    appState.trackerCache.model = payload;
    renderModelTracker(payload);
    if (appState.trackerView === "model" && !document.getElementById("tracker-diagnostics")?.hidden) loadTrackerDiagnostics();
  } catch (error) {
    if (appState.trackerView === "model") document.getElementById("tracker-body").innerHTML = `<tr><td colspan="10">${errorState(error.message)}<button class="button compact tracker-retry" type="button">Retry Model Tracker</button></td></tr>`;
  }
}

async function loadPersonalTracker() {
  const params = new URLSearchParams({
    ...Object.fromEntries(trackerRequestParams("personal")),
  });
  try {
    const payload = await fetchJson(`/api/personal-tracker?${params.toString()}`);
    appState.trackerCache.personal = payload;
    renderPersonalTracker(payload);
  } catch (error) {
    if (appState.trackerView === "personal") document.getElementById("tracker-body").innerHTML = `<tr><td colspan="10">${errorState(error.message)}<button class="button compact tracker-retry" type="button">Retry Personal Tracker</button></td></tr>`;
  }
}

function loadTrackerView() {
  return appState.trackerView === "personal" ? loadPersonalTracker() : loadTracker();
}

function configureTrackerShell(view) {
  const model = view === "model";
  const copy = model ? {
    eyebrow: "SIMULATED MODEL PERFORMANCE",
    subtitle: "Automatically tracked performance from model recommendations",
    title: "Global recommendation ledger",
    context: "Every eligible recommendation is frozen at its original entry, stake percentage, confidence, and Sharp evidence. Personal purchases never enter these results.",
    icon: "ph-robot",
    chartEyebrow: "BANKROLL REPLAY",
    chartTitle: "Simulated Model bankroll",
  } : {
    eyebrow: "YOUR CONFIRMED TRADES",
    subtitle: "Performance from bets you manually tracked",
    title: "Your private trade log",
    context: "Only purchases you manually confirm from Trades to Play appear here. Model recommendations never enter these totals.",
    icon: "ph-user-focus",
    chartEyebrow: "PERSONAL PERFORMANCE",
    chartTitle: "Personal bankroll",
  };
  document.getElementById("tracker-eyebrow").textContent = copy.eyebrow;
  document.getElementById("tracker-subtitle").textContent = copy.subtitle;
  document.getElementById("tracker-context-title").textContent = copy.title;
  document.getElementById("tracker-context-copy").textContent = copy.context;
  document.getElementById("tracker-context-icon").className = `ph ${copy.icon}`;
  document.getElementById("tracker-chart-eyebrow").textContent = copy.chartEyebrow;
  document.getElementById("tracker-chart-title").textContent = copy.chartTitle;
  document.getElementById("model-bankroll-control").hidden = !model;
  document.getElementById("personal-bankroll-control").hidden = model;
  document.getElementById("tracker-admin-open").hidden = !model;
  document.getElementById("personal-track-action").hidden = model;
  document.getElementById("tracker-job-state").hidden = !model;
  document.getElementById("tracker-sharps").hidden = !model;
  document.querySelector('#tracker-status option[value="canceled"]').hidden = model;
  document.querySelector('#tracker-result option[value="canceled"]').hidden = model;
  if (model && document.getElementById("tracker-status").value === "canceled") document.getElementById("tracker-status").value = "";
  if (model && document.getElementById("tracker-result").value === "canceled") document.getElementById("tracker-result").value = "";
  document.getElementById("tracker-search").placeholder = model ? "Search event, market, trader" : "Search event, market, selection";
  document.getElementById("tracker-table-head").innerHTML = model
    ? "<th>Event / Market</th><th>Selection</th><th>Sharps</th><th>Score</th><th>User Entry</th><th>Est. Win</th><th>Bet</th><th>Status</th><th>P&amp;L</th><th>Bankroll</th>"
    : "<th>Event / Market</th><th>Selection</th><th>Shares</th><th>Entry</th><th>Position Cost</th><th>Fees</th><th>Status</th><th>P&amp;L</th><th>Tracked</th><th>Action</th>";
  document.getElementById("tracker-diagnostics").hidden = !model || !appState.trackerDiagnostics;
  document.querySelectorAll("[data-tracker-view]").forEach((button) => {
    const selected = button.dataset.trackerView === view;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
}

async function selectTrackerView(view, { persist = true } = {}) {
  const normalized = view === "personal" ? "personal" : "model";
  appState.trackerView = normalized;
  configureTrackerShell(normalized);
  const url = new URL(window.location.href);
  url.searchParams.set("view", normalized);
  window.history.replaceState({}, "", `${url.pathname}?${url.searchParams.toString()}`);
  const cached = appState.trackerCache[normalized];
  if (cached) {
    if (normalized === "model") renderModelTracker(cached);
    else renderPersonalTracker(cached);
  } else {
    document.getElementById("tracker-result-count").textContent = "Loading";
    document.getElementById("tracker-metrics").innerHTML = '<div class="tracker-loading-state metric-loading"><span></span><span></span><span></span></div>';
    document.getElementById("tracker-chart").innerHTML = '<div class="tracker-loading-state"><span></span><span></span><span></span></div>';
    document.getElementById("tracker-body").innerHTML = '<tr><td colspan="10"><div class="tracker-loading-state"><span></span><span></span><span></span></div></td></tr>';
  }
  loadTrackerView();
  if (persist) {
    fetchJson("/api/tracker-preference", { method: "PUT", body: JSON.stringify({ view: normalized }) }).catch(() => {});
  }
}

function openPersonalBankrollDialog() {
  const dialog = document.getElementById("personal-bankroll-dialog");
  const input = document.getElementById("personal-bankroll-input");
  document.getElementById("personal-bankroll-error").textContent = "";
  input.value = number(appState.personalTrackerBankroll)?.toFixed(2) || "";
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  input.focus();
  input.select();
}

function closePersonalBankrollDialog() {
  const dialog = document.getElementById("personal-bankroll-dialog");
  document.getElementById("personal-bankroll-form")?.reset();
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
}

async function savePersonalTrackerBankroll(event) {
  event.preventDefault();
  const form = document.getElementById("personal-bankroll-form");
  const submit = form.querySelector('button[type="submit"]');
  const error = document.getElementById("personal-bankroll-error");
  const bankroll = number(document.getElementById("personal-bankroll-input").value);
  if (bankroll === null || bankroll <= 0) {
    error.textContent = "Enter a bankroll greater than zero.";
    return;
  }
  submit.disabled = true;
  error.textContent = "";
  try {
    await fetchJson("/api/personal-tracker/settings", { method: "PUT", body: JSON.stringify({ personal_tracker_bankroll: bankroll }) });
    closePersonalBankrollDialog();
    appState.trackerCache.personal = null;
    await loadPersonalTracker();
    showToast("Personal starting bankroll updated. Purchases and Model results are unchanged.", "success");
  } catch (requestError) {
    error.textContent = requestError.message;
  } finally {
    submit.disabled = false;
  }
}

async function initializeTrackerView() {
  let settings = {};
  try {
    settings = (await fetchJson("/api/user-settings")).data || {};
  } catch (_error) {
    // Tracker APIs can still load independently if settings retrieval fails.
  }
  const params = new URLSearchParams(window.location.search);
  const requested = params.get("view");
  const view = requested === null
    ? (["model", "personal"].includes(settings.tracker_view) ? settings.tracker_view : "model")
    : (["model", "personal"].includes(requested) ? requested : "model");
  selectTrackerView(view, { persist: requested !== null });
}

function bindTracker() {
  document.getElementById("tracker-search").addEventListener("input", debounce(() => { appState.trackerPage[appState.trackerView] = 1; loadTrackerView(); }));
  ["tracker-status", "tracker-sharps", "tracker-result"].forEach((id) => document.getElementById(id).addEventListener("change", () => { appState.trackerPage[appState.trackerView] = 1; loadTrackerView(); }));
  document.querySelectorAll("#graph-range button").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll("#graph-range button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    appState.graphRange = button.dataset.range;
    loadTrackerView();
  }));
  document.querySelectorAll("[data-tracker-view]").forEach((button) => {
    button.addEventListener("click", () => selectTrackerView(button.dataset.trackerView));
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" || event.key === "ArrowLeft" ? "model" : "personal";
      selectTrackerView(next);
      document.querySelector(`[data-tracker-view="${next}"]`).focus();
    });
  });
  document.getElementById("tracker-body").addEventListener("click", (event) => {
    if (event.target.closest(".tracker-retry")) loadTrackerView();
  });
  document.getElementById("tracker-admin-open")?.addEventListener("click", () => loadTrackerDiagnostics(true));
  document.getElementById("tracker-bankroll-edit")?.addEventListener("click", openTrackerBankrollDialog);
  document.getElementById("tracker-bankroll-form")?.addEventListener("submit", saveTrackerBankroll);
  document.getElementById("tracker-bankroll-close")?.addEventListener("click", closeTrackerBankrollDialog);
  document.getElementById("tracker-bankroll-dismiss")?.addEventListener("click", closeTrackerBankrollDialog);
  document.getElementById("tracker-bankroll-dialog")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeTrackerBankrollDialog();
  });
  document.getElementById("personal-bankroll-edit")?.addEventListener("click", openPersonalBankrollDialog);
  document.getElementById("personal-bankroll-form")?.addEventListener("submit", savePersonalTrackerBankroll);
  document.getElementById("personal-bankroll-close")?.addEventListener("click", closePersonalBankrollDialog);
  document.getElementById("personal-bankroll-dismiss")?.addEventListener("click", closePersonalBankrollDialog);
  document.getElementById("personal-bankroll-dialog")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closePersonalBankrollDialog();
  });
  document.getElementById("tracker-admin-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = document.getElementById("tracker-admin-error");
    try {
      await fetchJson("/api/admin/login", { method: "POST", body: JSON.stringify({ password: document.getElementById("tracker-admin-password").value }) });
      closeTrackerAdminDialog();
      await loadTrackerDiagnostics();
    } catch (requestError) {
      error.textContent = requestError.message;
    }
  });
  document.getElementById("tracker-admin-close")?.addEventListener("click", closeTrackerAdminDialog);
  document.getElementById("tracker-admin-dismiss")?.addEventListener("click", closeTrackerAdminDialog);
  document.getElementById("tracker-admin-dialog")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeTrackerAdminDialog();
  });
  document.getElementById("tracker-reconcile")?.addEventListener("click", async () => {
    const button = document.getElementById("tracker-reconcile");
    button.disabled = true;
    try {
      const payload = await fetchJson("/api/admin/model-tracker/reconcile", { method: "POST", body: JSON.stringify({ force: true }) });
      showToast(`Reconciled: ${payload.data.records_inserted || 0} inserted, ${payload.data.records_skipped_duplicates || 0} existing`, "success");
      appState.trackerCache.model = null;
      await Promise.all([loadTracker(), loadTrackerDiagnostics()]);
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });
  document.getElementById("tracker-pause-job")?.addEventListener("click", async () => {
    try {
      const paused = !Boolean(appState.trackerDiagnostics?.paused);
      const payload = await fetchJson("/api/admin/model-tracker/pause", { method: "POST", body: JSON.stringify({ paused }) });
      renderTrackerDiagnostics({ ...appState.trackerDiagnostics, ...payload.data });
      showToast(paused ? "Automatic tracking paused" : "Automatic tracking resumed", "success");
    } catch (error) {
      showToast(error.message, "error");
    }
  });
  loadTrackerDiagnostics();
  initializeTrackerView();
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
        ? "Page refresh: Paused"
        : "Page refresh: Active";
      control.title = appState.paused ? "Resume automatic 15-second page refresh" : "Pause automatic 15-second page refresh";
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
  if (page === "tracker") loadTrackerView();
  loadGlobalStatus();
}

function initialize() {
  bindNavigation();
  bindAccount();
  loadGlobalStatus();
  if (page === "overview") loadOverview();
  if (page === "trades") bindTrades();
  if (page === "live-positions") bindPositions();
  if (page === "wallets") bindWallets();
  if (page === "position-history") bindHistory();
  if (page === "tracker") bindTracker();
  window.setInterval(refreshCurrentPage, AUTO_REFRESH_MS);
}

initialize();
