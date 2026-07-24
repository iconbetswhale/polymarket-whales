const page = document.body.dataset.page;
const LINE_SHOP_REFRESH_MS = Math.max(2000, (number(document.body.dataset.lineShopRefreshSeconds) || 5) * 1000);
const AUTO_REFRESH_MS = page === "trades" ? LINE_SHOP_REFRESH_MS : 15000;
const appState = {
  paused: localStorage.getItem("iconbets-refresh-paused") === "true",
  selectedTradeId: null,
  trades: [],
  pageNumber: 1,
  graphRange: "month",
  personalTradeId: null,
  personalSelectedTags: [],
  personalTrackerOptions: null,
  trackerDiagnostics: null,
  trackerBankroll: null,
  personalTrackerBankroll: null,
  trackerView: null,
  trackerCache: { model: null, personal: null },
  trackerPage: { model: 1, personal: 1 },
  trackerSelectedBooks: { model: [], personal: [] },
  trackerBookOptions: { model: [], personal: [] },
  sharpSources: {},
  sharpSourceSequence: 0,
  userSettings: null,
  sizingBankrollDirty: false,
  bankrollSavePending: false,
  account: { authenticated: false, email: null },
  appliedEntryPriceFilters: { minEntryCents: "", maxEntryCents: "" },
  executionOdds: {},
  tradeRenderSignatures: {},
  tradesView: "feed",
  whiteboard: [],
  workspaceTab: "trades",
  personalPositions: [],
  personalClosed: [],
  selectedPersonalPositionId: null,
  selectedClosedPositionId: null,
  closureFilter: "all",
  pnlPeriod: "week",
  sellPosition: null,
  intelligence: { candidates: [], proposals: [], violations: [], diagnostics: null },
};

function researchBadges(trade) {
  const badges = [];
  if (trade.hasContradictingSharps) badges.push('<span class="research-badge"><i class="ph ph-warning" aria-hidden="true"></i>Contradicting Sharps</span>');
  if (trade.isNonCategoryConsensus) badges.push('<span class="research-badge"><i class="ph ph-warning" aria-hidden="true"></i>Sharp Non-Category</span>');
  return badges.join("");
}

function researchTrackerWarning(trade) {
  if (!trade.isResearchOnly) return "";
  const lines = [];
  if (trade.hasContradictingSharps) lines.push(`<strong>Research-only signal: Contradicting Sharps</strong><span>${trade.rawAgreeingSharpCount || 0} tracked wallets support this outcome and ${trade.rawContradictingSharpCount || 0} tracked wallets hold an opposing outcome.</span>`);
  if (trade.isNonCategoryConsensus) lines.push('<strong>Research-only signal: Sharp Non-Category</strong><span>Multiple wallets agree, but none has this market as a verified top category.</span>');
  lines.push("<span>This trade will not be included in Model Tracker.</span>");
  return lines.join("");
}

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

function formatExitCents(value) {
  const parsed = number(value);
  if (parsed === null || parsed < 0 || parsed > 1) return "N/A";
  const cents = parsed * 100;
  return `${Number.isInteger(cents) ? cents.toFixed(0) : cents.toFixed(1)}¢`;
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
    classification: params.get("classification") || "",
    minEntryCents: params.get("minEntryCents") || "",
    maxEntryCents: params.get("maxEntryCents") || "",
    custom_start: params.get("custom_start") || "",
    custom_end: params.get("custom_end") || "",
    show_hidden: params.get("show_hidden") === "true",
    execution: params.get("execution") || "",
    min_bet: params.get("min_bet") || "0",
    max_slippage: params.get("max_slippage") || "",
    sort: params.get("sort") || "confidence-desc",
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
    "trade-classification": "classification",
    "min-entry-cents": "minEntryCents",
    "max-entry-cents": "maxEntryCents",
    "custom-start": "custom_start",
    "custom-end": "custom_end",
    "show-hidden-trades": "show_hidden",
    "trade-execution": "execution",
    "trade-min-bet": "min_bet",
    "trade-max-slippage": "max_slippage",
    "trade-sort": "sort",
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
  updateActiveFilterCount();
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
  const backdrop = document.getElementById("trades-drawer-backdrop");
  if (!panel || !button) return;
  panel.hidden = !expanded;
  if (backdrop) backdrop.hidden = !expanded;
  document.body.classList.toggle("trades-settings-open", expanded);
  button.setAttribute("aria-expanded", String(expanded));
  if (expanded) panel.querySelector("select, input, button")?.focus();
}

function togglePopover(buttonId, panelId, expanded) {
  const button = document.getElementById(buttonId);
  const panel = document.getElementById(panelId);
  if (!button || !panel) return;
  panel.hidden = !expanded;
  button.setAttribute("aria-expanded", String(expanded));
}

function updateActiveFilterCount() {
  const count = [
    document.getElementById("trade-date-range")?.value !== "today",
    document.getElementById("trade-sharps")?.value !== "0",
    document.getElementById("trade-confidence")?.value !== "0",
    Boolean(document.getElementById("trade-sport")?.value),
    Boolean(document.getElementById("trade-league")?.value),
    Boolean(document.getElementById("trade-wallet")?.value),
    Boolean(document.getElementById("trade-classification")?.value),
    Boolean(document.getElementById("trade-execution")?.value),
    document.getElementById("trade-min-bet")?.value !== "0",
    Boolean(document.getElementById("trade-max-slippage")?.value),
    Boolean(appState.appliedEntryPriceFilters.minEntryCents),
    Boolean(appState.appliedEntryPriceFilters.maxEntryCents),
    Boolean(document.getElementById("show-hidden-trades")?.checked),
    document.getElementById("trade-sort")?.value !== "confidence-desc",
  ].filter(Boolean).length;
  const badge = document.getElementById("active-filter-count");
  if (badge) {
    badge.textContent = String(count);
    badge.classList.toggle("active", count > 0);
  }
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
    classification: document.getElementById("trade-classification").value,
    minEntryCents: appState.appliedEntryPriceFilters.minEntryCents,
    maxEntryCents: appState.appliedEntryPriceFilters.maxEntryCents,
    custom_start: document.getElementById("custom-start").value,
    custom_end: document.getElementById("custom-end").value,
    show_hidden: document.getElementById("show-hidden-trades").checked,
    execution: document.getElementById("trade-execution").value,
    min_bet: document.getElementById("trade-min-bet").value,
    max_slippage: document.getElementById("trade-max-slippage").value,
    sort: document.getElementById("trade-sort").value,
  };
}

function updateTradeUrl(filters) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    const isDefaultZero = ["min_sharps", "min_confidence", "min_bet"].includes(key) && value === "0";
    const isDefaultPreset = (key === "date_range" && value === "today") || (key === "sort" && value === "confidence-desc");
    if (value && !isDefaultZero && !isDefaultPreset) {
      params.set(key, value);
    }
  });
  if (appState.selectedTradeId) params.set("selected", appState.selectedTradeId);
  if (appState.workspaceTab !== "trades") params.set("tab", appState.workspaceTab);
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
  const nativeProviderKey = providerKey.replace(/^oddsapi__/, "");
  const contractPrice = number(option.contractPrice);
  const americanOdds = number(option.americanOdds);
  const nativeOdds = ["polymarket", "kalshi"].includes(nativeProviderKey)
    ? (contractPrice === null ? option.displayOdds : formatCents(contractPrice))
    : (americanOdds === null ? option.displayOdds : (americanOdds > 0 ? `+${Math.round(americanOdds)}` : `${Math.round(americanOdds)}`));
  const displayOdds = option.isAvailable ? nativeOdds : "Unavailable";
  const movement = option.priceMovement || "";
  const polymarketClass = providerKey === "polymarket" ? " polymarket-price-link" : "";
  const bestClass = option.isBestPrice ? " best-execution-price" : "";
  const classes = `execution-option execution-option--${providerKey}${polymarketClass}${bestClass} ${movement}`.trim();
  const age = number(option.quoteAgeSeconds);
  const details = [
    `Top ${nativeOdds || "Unavailable"}`,
    `Effective ${formatOptionalCents(option.effectiveEntryPrice ?? option.effectivePrice)}`,
    `Liquidity ${formatOptionalMoney(option.availableLiquidity)}`,
    `Stake ${formatOptionalMoney(option.recommendedStake)}`,
    `Fees ${number(option.estimatedFees) === null ? "Unavailable" : formatMoney(option.estimatedFees)}`,
    `Age ${age === null ? "Unknown" : `${Math.round(age)}s`}`,
  ].join(" · ");
  const tooltip = `${option.tooltip || `${providerName} executable quote`} · ${details}`;
  const plan = trade.recommendation?.execution_plan || {};
  const effective = number(option.effectiveEntryPrice ?? option.effectivePrice ?? option.contractPrice ?? plan.effective_price_for_executable_amount ?? trade.recommendation?.current_user_entry_price);
  const maximum = number(plan.maximum_average_price);
  const aboveMaximum = effective !== null && maximum !== null && effective > maximum;
  const providerMark = providerLogoMarkup(
    { name: providerName, logoUrl: option.logoUrl },
  );
  const content = `
    ${providerMark}
    <span><small>${escapeHtml(providerName)}</small><strong>${escapeHtml(displayOdds)}</strong></span>
    ${option.isBestPrice ? '<em class="best-price-label">Best Price</em>' : ""}
    <span class="execution-option-tooltip" role="tooltip">${escapeHtml(tooltip)}</span>
  `;
  if (!option.isAvailable || !option.deepLink || aboveMaximum) {
    return `<button class="${escapeHtml(classes)} ${aboveMaximum ? "above-maximum" : ""}" type="button" disabled aria-disabled="true" aria-label="${escapeHtml(aboveMaximum ? "Above maximum approved price" : `${providerName} is unavailable`)}">${content}${aboveMaximum ? '<em>Above maximum approved price</em>' : ""}</button>`;
  }
  return `
    <a class="${escapeHtml(classes)}" href="${escapeHtml(option.deepLink)}" target="_blank" rel="noopener noreferrer" data-execution-trade-id="${escapeHtml(trade.id)}" aria-label="Open ${escapeHtml(trade.outcome)} on ${escapeHtml(providerName)} at ${escapeHtml(displayOdds)}">
      ${content}
    </a>
  `;
}

function executionToolbar(trade) {
  const supported = new Set(["polymarket", "kalshi", "4cx", "fourcx", "novig", "prophetx"]);
  const options = (trade.executionOptions || []).filter((option) => {
    const key = String(option.providerKey || "").toLowerCase();
    const canonicalKey = key.replace(/^oddsapi__/, "");
    return option.matchingConfidence === "Exact" && supported.has(canonicalKey);
  });
  const best = options.find(option => option.isBestPrice && option.isAvailable);
  if (best) {
    return `<span class="execution-toolbar execution-toolbar--best" aria-label="Best line-shopped exchange price"><span class="execution-options-scroll">${executionOptionButton(trade, best)}</span><small class="line-shop-status ready"><i class="ph ph-check-circle"></i>Best exchange price</small></span>`;
  }
  const hasStale = options.some(option => option.isStale);
  const status = options.length
    ? (hasStale ? "Exchange quotes stale · waiting for refresh" : "No exchange can fill this stake")
    : "No exact exchange market";
  return `<span class="execution-toolbar execution-toolbar--empty"><small class="line-shop-status waiting"><i class="ph ph-clock"></i>${status}</small></span>`;
}

function applyClientTradeFilters(trades, filters) {
  const minimumBet = number(filters.min_bet) || 0;
  const maximumSlippage = number(filters.max_slippage);
  const filtered = trades.filter((trade) => {
    const recommendation = trade.recommendation || {};
    const card = trade.card || {};
    const recommendedAmount = number(card.recommended_amount ?? recommendation.recommended_amount) || 0;
    if (recommendedAmount < minimumBet) return false;
    if (filters.execution) {
      const exactProviders = (trade.executionOptions || [])
        .filter((option) => option.matchingConfidence === "Exact")
        .map((option) => String(option.providerKey || "").toLowerCase().replace(/^oddsapi__/, ""));
      if (!exactProviders.includes(filters.execution)) return false;
    }
    if (maximumSlippage !== null) {
      const comparison = slippageComparison(
        card.current_actionable_price ?? recommendation.current_user_entry_price,
        card.trader_average_entry_price ?? recommendation.sharp_average_entry_price ?? trade.average_entry_price,
        card.slippage_fraction ?? recommendation.price_slippage_fraction,
      );
      if (!comparison || comparison.fraction > maximumSlippage) return false;
    }
    return true;
  });
  const value = (trade, path, fallback = -Infinity) => {
    const parsed = number(path(trade));
    return parsed === null ? fallback : parsed;
  };
  const sorters = {
    "confidence-desc": (a, b) => value(b, (trade) => trade.confidence_score) - value(a, (trade) => trade.confidence_score),
    "sharps-desc": (a, b) => value(b, (trade) => trade.raw_sharp_count ?? trade.agreeing_wallet_count) - value(a, (trade) => trade.raw_sharp_count ?? trade.agreeing_wallet_count),
    "consensus-desc": (a, b) => value(b, (trade) => trade.weighted_sharp_count) - value(a, (trade) => trade.weighted_sharp_count),
    "recommendation-desc": (a, b) => value(b, (trade) => trade.card?.recommended_amount ?? trade.recommendation?.recommended_amount) - value(a, (trade) => trade.card?.recommended_amount ?? trade.recommendation?.recommended_amount),
    "trader-bet-desc": (a, b) => value(b, (trade) => trade.card?.trader_bet_amount ?? trade.primary_trader?.amount) - value(a, (trade) => trade.card?.trader_bet_amount ?? trade.primary_trader?.amount),
    "relative-desc": (a, b) => value(b, (trade) => trade.card?.relative_bet_size ?? trade.primary_trader?.relative_units) - value(a, (trade) => trade.card?.relative_bet_size ?? trade.primary_trader?.relative_units),
    "start-asc": (a, b) => new Date(a.resolution_time || a.event_start_time || 0) - new Date(b.resolution_time || b.event_start_time || 0),
    "price-asc": (a, b) => value(a, (trade) => trade.card?.current_actionable_price ?? trade.recommendation?.current_user_entry_price, Infinity) - value(b, (trade) => trade.card?.current_actionable_price ?? trade.recommendation?.current_user_entry_price, Infinity),
    "slippage-asc": (a, b) => value(a, (trade) => trade.card?.slippage_fraction ?? trade.recommendation?.price_slippage_fraction, Infinity) - value(b, (trade) => trade.card?.slippage_fraction ?? trade.recommendation?.price_slippage_fraction, Infinity),
  };
  return filtered.sort(sorters[filters.sort] || sorters["confidence-desc"]);
}

function syncTradeRows(list, trades) {
  const existing = new Map(
    [...list.querySelectorAll(":scope > .trade-card")].map((card) => [card.dataset.tradeId, card]),
  );
  const fragment = document.createDocumentFragment();
  const nextSignatures = {};
  trades.forEach((trade) => {
    const signature = JSON.stringify(trade);
    nextSignatures[trade.id] = signature;
    let card = existing.get(String(trade.id));
    if (!card || appState.tradeRenderSignatures[trade.id] !== signature) {
      const template = document.createElement("template");
      template.innerHTML = tradeCard(trade).trim();
      card = template.content.firstElementChild;
    } else {
      const selected = trade.id === appState.selectedTradeId;
      card.classList.toggle("selected", selected);
      card.setAttribute("aria-pressed", String(selected));
    }
    fragment.append(card);
  });
  list.replaceChildren(fragment);
  appState.tradeRenderSignatures = nextSignatures;
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
  const executionPlan = recommendation.execution_plan || {};
  const portfolioRisk = recommendation.portfolio_risk || {};
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
        <span class="trade-score-cluster"><span class="trade-score ${confidenceClass(trade.confidence_score)}"><strong>${escapeHtml(trade.confidence_score)}</strong><small>${escapeHtml(trade.trade_quality?.grade || recommendation.trade_grade || "Trade Quality")}</small></span>${personalExposureWarning(trade)}${trade.isHidden ? '<span class="hidden-badge">Hidden</span>' : ""}</span>
        <span class="trade-event-copy">
          <span class="trade-kicker"><i class="ph ${sportIcon(trade.category)}" aria-hidden="true"></i>${escapeHtml(trade.category || "Sports")} · ${escapeHtml(trade.league || "Market")}</span>
          <span class="research-badges">${researchBadges(trade)}${trade.hasContradictingSharps ? `<small>${trade.rawAgreeingSharpCount || 0} For / ${trade.rawContradictingSharpCount || 0} Against</small>` : ""}</span>
          <strong class="trade-event">${escapeHtml(trade.event_title || trade.market_title)}</strong>
          <span class="trade-market">${escapeHtml(humanizeMarketType(trade.sports_market_type))} · ${escapeHtml(trade.market_title || "Market")}</span>
        </span>
      </span>
      <span class="trade-decision">
        <span class="trade-metrics-row">
          ${tradeMetricChip("ph-calendar-blank", eventTime, "Scheduled event start in Eastern Time", "time")}
          ${tradeMetricChip("ph-coins", formatOptionalMoney(betAmount, true), amountTooltip)}
          ${tradeMetricChip("ph-ticket", formatOptionalCents(traderEntry), "Tracked Sharp average entry price")}
          ${slippageMetricChip(slippage)}
          ${tradeMetricChip("ph-arrow-up-right", formatRelativeSize(relativeSize), relativeTooltip)}
          ${tradeMetricChip("ph-target", hitRateText, "Adjusted trader hit rate in this category")}
          <span class="trade-current-price">Current: <strong>${escapeHtml(formatOptionalCents(currentPrice))}</strong></span>
        </span>
        <span class="trade-selection">
          <span class="trade-pick"><small>Pick · ${escapeHtml(sharpLabel)}</small><strong>${escapeHtml(trade.outcome)}</strong></span>
          <span class="trade-recommendation"><small>Recommended</small><strong>${escapeHtml(formatShares(recommendedShares))} shares</strong><em>${escapeHtml(formatOptionalMoney(recommendedAmount))} · ${escapeHtml(formatUnits(recommendedUnits))}</em><em>${escapeHtml(executionPlan.recommended_execution_method || "Execution unavailable")} · Max ${escapeHtml(formatOptionalCents(executionPlan.maximum_average_price))} · ${escapeHtml(portfolioRisk.risk_state?.state || "Risk unavailable")}</em><em>Fair ${escapeHtml(formatOptionalCents(recommendation.raw_fair_probability))} · Edge ${escapeHtml(formatPercent(recommendation.calculated_edge))} · Liquidity ${escapeHtml(trade.liquidity_quality?.grade || trade.liquidity_quality?.status || "Unavailable")}</em></span>
          ${executionToolbar(trade)}
          <span class="trade-card-actions">
            <button class="trade-pin-action ${trade.isPinnedByCurrentUser ? "active" : ""}" type="button" data-trade-id="${escapeHtml(trade.id)}" data-pin-id="${escapeHtml(trade.whiteboardPinId || "")}" title="${trade.isPinnedByCurrentUser ? "Unpin from Whiteboard" : "Pin to Whiteboard"}" aria-label="${trade.isPinnedByCurrentUser ? "Unpin this trade from your Whiteboard" : "Pin this trade to your Whiteboard"}"><i class="ph ${trade.isPinnedByCurrentUser ? "ph-push-pin-fill" : "ph-push-pin"}" aria-hidden="true"></i></button>
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
  appState.personalSelectedTags = [];
  renderPersonalSelectedTags();
  const preferredBook = localStorage.getItem("iconbets-personal-sportsbook") || "Polymarket";
  setSelectOptions(document.getElementById("personal-sportsbook"), [preferredBook], preferredBook);
  loadPersonalTrackerOptions();
  document.getElementById("personal-conflict-check").checked = false;
  updatePersonalPurchaseTotal();
  renderPurchaseExposureNotice(trade.personalExposureSummary || {});
  const researchWarning = document.getElementById("personal-research-warning");
  researchWarning.innerHTML = researchTrackerWarning(trade);
  researchWarning.hidden = !trade.isResearchOnly;
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
}

function setSelectOptions(select, values, selectedValue = "", emptyLabel = null) {
  if (!select) return;
  const normalizedValues = [...new Set((values || []).filter(Boolean))];
  const options = emptyLabel === null ? [] : [`<option value="">${escapeHtml(emptyLabel)}</option>`];
  options.push(...normalizedValues.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`));
  select.innerHTML = options.join("");
  if (selectedValue && normalizedValues.some((value) => value === selectedValue)) select.value = selectedValue;
}

function renderPersonalTrackingOptions(options = {}) {
  appState.personalTrackerOptions = options;
  const sportsbook = document.getElementById("personal-sportsbook");
  const preferredBook = sportsbook?.value || localStorage.getItem("iconbets-personal-sportsbook") || "Polymarket";
  const sportsbookChoices = options.sportsbook_choices?.length ? options.sportsbook_choices : ["Polymarket"];
  if (!sportsbookChoices.includes(preferredBook)) sportsbookChoices.push(preferredBook);
  setSelectOptions(sportsbook, sportsbookChoices, preferredBook);
  renderPersonalSelectedTags();
}

async function loadPersonalTrackerOptions({ force = false } = {}) {
  if (appState.personalTrackerOptions && !force) {
    renderPersonalTrackingOptions(appState.personalTrackerOptions);
    return;
  }
  try {
    const payload = await fetchJson("/api/personal-tracker/options");
    renderPersonalTrackingOptions(payload.data || {});
  } catch (_error) {
    renderPersonalTrackingOptions({ sportsbook_choices: ["Polymarket"], tags: [] });
  }
}

function addPersonalTag(rawTag) {
  const tag = String(rawTag || "").trim().replace(/^#+/, "").replace(/\s+/g, " ");
  if (!tag) return;
  if (tag.length > 32) {
    showToast("Tags must be 32 characters or fewer", "error");
    return;
  }
  if (appState.personalSelectedTags.some((item) => item.toLowerCase() === tag.toLowerCase())) return;
  if (appState.personalSelectedTags.length >= 8) {
    showToast("Choose no more than 8 tags per bet", "error");
    return;
  }
  appState.personalSelectedTags.push(tag);
  renderPersonalSelectedTags();
}

function renderPersonalSelectedTags() {
  const container = document.getElementById("personal-selected-tags");
  const count = document.getElementById("personal-tag-count");
  const existing = document.getElementById("personal-existing-tag");
  if (!container || !count || !existing) return;
  count.textContent = `${appState.personalSelectedTags.length} selected`;
  container.innerHTML = appState.personalSelectedTags.length
    ? appState.personalSelectedTags.map((tag) => `<button type="button" data-remove-personal-tag="${escapeHtml(tag)}" title="Remove ${escapeHtml(tag)}"><span>#${escapeHtml(tag)}</span><i class="ph ph-x" aria-hidden="true"></i></button>`).join("")
    : "<span>No tags selected</span>";
  const availableTags = (appState.personalTrackerOptions?.tags || []).filter((tag) => !appState.personalSelectedTags.some((selected) => selected.toLowerCase() === tag.toLowerCase()));
  setSelectOptions(existing, availableTags, "", "Select an existing tag");
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
        sportsbook: document.getElementById("personal-sportsbook").value,
        tags: appState.personalSelectedTags,
        confirm_duplicate: Boolean(exposure.hasExactPersonalPosition),
        confirm_conflict: document.getElementById("personal-conflict-check").checked,
      }),
    });
    localStorage.setItem("iconbets-personal-sportsbook", document.getElementById("personal-sportsbook").value);
    appState.personalTrackerOptions = null;
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
  appState.personalSelectedTags = [];
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
    ["Independent Fair Probability", formatPercent(recommendation.raw_fair_probability)],
    ["Fee-adjusted Fair Probability", formatPercent(recommendation.fee_adjusted_fair_probability)],
    ["Raw Sharps", String(trade.raw_sharp_count ?? trade.agreeing_wallet_count)],
    ["Lead Sharps", String(trade.lead_sharp_count ?? 0)],
    ["Supporting Sharps", String(trade.supporting_sharp_count ?? 0)],
    ["Weighted Consensus", weightedSharpLabel(trade.weighted_sharp_count)],
    ["Category Weighting", (trade.supporting_sharp_count || 0) > 0 ? "Supporting counted at 0.5x" : "All Sharps counted at 1.0x"],
    ["Sharp Evidence Score", Number(recommendation.evidence_score).toFixed(3)],
    ["Edge Reliability", formatPercent(recommendation.edge_reliability_factor)],
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
      <p class="calculation-note">Kelly uses the independently sourced, no-vig fair probability after verified fees and an uncertainty haircut. The final amount is then capped by bankroll bucket, drawdown, correlation, provider exposure, and executable depth.</p>
    </details>
  `;
}

function executionRiskDetails(recommendation) {
  const execution = recommendation.execution_plan || {};
  const risk = recommendation.portfolio_risk || {};
  const related = risk.existing_related_exposure || {};
  const remaining = risk.remaining_capacity || {};
  const state = risk.risk_state || {};
  const rows = [
    ["Execution method", execution.recommended_execution_method || "Unavailable"],
    ["Execution reason", execution.execution_reason_code || "Unavailable"],
    ["Maximum average price", formatOptionalCents(execution.maximum_average_price)],
    ["Effective executable price", formatOptionalCents(execution.effective_price_for_executable_amount)],
    ["Executable below max", formatOptionalMoney(execution.amount_executable_below_max)],
    ["Unfilled amount", formatOptionalMoney(execution.unfilled_amount)],
    ["Quote freshness", execution.quote_fresh ? `${Number(execution.quote_age_seconds || 0).toFixed(0)}s` : "Unavailable / stale"],
    ["Before portfolio risk", formatOptionalMoney(risk.recommended_before_risk)],
    ["Same-game exposure", formatOptionalMoney(related.same_game)],
    ["Same-game capacity", formatOptionalMoney(remaining.same_game)],
    ["Correlation multiplier", formatPercent(risk.correlation_multiplier)],
    ["Bankroll bucket", risk.bucket || "Unavailable"],
    ["Risk state", state.state || "Unavailable"],
    ["Drawdown", formatPercent(state.drawdown_fraction)],
  ];
  return `<details class="detail-accordion execution-risk-panel" open><summary><span><i class="ph ph-shield-check" aria-hidden="true"></i>Execution and portfolio risk</span><small>${escapeHtml(execution.recommended_execution_method || "Unavailable")}</small><i class="ph ph-caret-down" aria-hidden="true"></i></summary><div class="calculation-grid">${rows.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div><p class="calculation-note">${escapeHtml(execution.execution_explanation || "A verified execution plan is unavailable.")}</p></details>`;
}

function completionTradeDetails(trade, recommendation) {
  const fair = trade.fair_price || {};
  const liquidity = trade.liquidity_quality || {};
  const policy = recommendation.applied_segment_policy || {};
  const sections = [
    ["Trade decision", [["Quality / grade", `${trade.confidence_score ?? "Unavailable"} / ${trade.trade_quality?.grade || recommendation.trade_grade || "Unavailable"}`], ["Action", recommendation.execution_plan?.recommended_execution_method || "Unavailable"], ["Model Tracker", trade.modelTrackerEligible ? "Eligible" : "Excluded"], ["Primary reason", trade.modelTrackerRejectionReason || recommendation.reason || "Approved"]]],
    ["Price validation", [["Sharp entry", formatOptionalCents(recommendation.sharp_average_entry_price)], ["Executable entry", formatOptionalCents(recommendation.current_user_entry_price)], ["Composite fair", formatOptionalCents(fair.fair_probability)], ["Fee-adjusted edge", formatPercent(recommendation.calculated_edge)], ["Source count", String(fair.source_count ?? 0)], ["Dispersion", fair.source_dispersion === null || fair.source_dispersion === undefined ? "Unavailable" : formatPercent(fair.source_dispersion)]]],
    ["Liquidity", [["Quality score", String(liquidity.score ?? "Unavailable")], ["Grade", liquidity.grade || liquidity.status || "Unavailable"], ["Top-of-book", String(liquidity.components?.top_of_book ?? "Unavailable")], ["Ladder", String(liquidity.components?.ladder ?? "Unavailable")], ["Stability", String(liquidity.components?.stability ?? "Unavailable")], ["Cross-market", String(liquidity.components?.cross_market ?? "Unavailable")]]],
    ["Context", [["Time to event", trade.event_time_et || "Unavailable"], ["News status", trade.news_status || "Unavailable"], ["Mapping confidence", fair.mapping_confidence || trade.mapping_confidence || "Unavailable"], ["Settlement rules", trade.settlement_rules || "Unavailable"], ["Applied policy", policy.stake_multiplier === undefined ? "None" : `${formatPercent(policy.stake_multiplier)} multiplier`]]],
  ];
  return `${sections.map(([title, rows]) => `<details class="detail-accordion"><summary><span>${escapeHtml(title)}</span><i class="ph ph-caret-down"></i></summary><div class="calculation-grid">${rows.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div></details>`).join("")}<details class="detail-accordion"><summary><span>Tracker evidence</span><small>Similar segment history</small><i class="ph ph-caret-down"></i></summary><div id="trade-edge-evidence"><div class="chart-loading">Loading Edge Map evidence…</div></div></details>`;
}

async function loadTradeEdgeEvidence(trade) {
  const target = document.getElementById("trade-edge-evidence");
  if (!target) return;
  try {
    const payload = await fetchJson("/api/edge-map?dimension=sport");
    const row = (payload.data?.segments || []).find((item) => String(item.segment_value).toLowerCase() === String(trade.category || "").toLowerCase());
    target.innerHTML = row ? `<div class="calculation-grid"><div><span>Status</span><strong>${escapeHtml(row.status.replaceAll("_", " "))}</strong></div><div><span>Candidate sample</span><strong>${row.candidate_count}</strong></div><div><span>Played / Passed</span><strong>${row.played_count} / ${row.passed_count}</strong></div><div><span>Exchange CLV</span><strong>${edgeMetric(row.stake_weighted_exchange_clv)}</strong></div><div><span>Composite CLV</span><strong>${edgeMetric(row.stake_weighted_composite_clv)}</strong></div><div><span>Reliability</span><strong>${formatPercent(row.statistical_reliability)}</strong></div></div>` : '<p class="calculation-note">No comparable Edge Map segment exists yet.</p>';
  } catch (error) {
    target.innerHTML = `<p class="calculation-note">${escapeHtml(error.message)}</p>`;
  }
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

function detailStripMetric(icon, value, label, tone = "") {
  return `<span class="detail-strip-metric ${tone}"><i class="ph ${icon}" aria-hidden="true"></i><span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(label)}</small></span></span>`;
}

function tradeOrderBook(trade) {
  const book = trade.orderbook || {};
  const asks = (book.asks || []).map((level) => ({ price: number(level.price), size: number(level.size) })).filter((level) => level.price !== null && level.size !== null).slice(0, 4).reverse();
  const bids = (book.bids || []).map((level) => ({ price: number(level.price), size: number(level.size) })).filter((level) => level.price !== null && level.size !== null).slice(0, 4);
  if (!asks.length && !bids.length) {
    return `<div class="orderbook-empty"><i class="ph ph-chart-bar-horizontal" aria-hidden="true"></i><span><strong>Order book unavailable</strong><small>No verified depth levels are available for this outcome.</small></span></div>`;
  }
  const allLiquidity = [...asks, ...bids].map((level) => level.price * level.size);
  const maxLiquidity = Math.max(...allLiquidity, 1);
  const rows = (levels, tone) => levels.map((level) => {
    const liquidity = level.price * level.size;
    const depth = Math.max(4, (liquidity / maxLiquidity) * 100);
    return `<div class="orderbook-row ${tone}" style="--depth:${depth.toFixed(1)}%"><span>${escapeHtml(formatCents(level.price))}</span><span class="orderbook-depth"><i aria-hidden="true"></i></span><strong>${escapeHtml(formatCompactMoney(liquidity))}</strong></div>`;
  }).join("");
  const bestAsk = asks.length ? asks[asks.length - 1].price : number(trade.orderbook_summary?.best_ask);
  const bestBid = bids.length ? bids[0].price : number(trade.orderbook_summary?.best_bid);
  const spread = bestAsk !== null && bestBid !== null && bestAsk >= bestBid
    ? `${((bestAsk - bestBid) * 100).toFixed(1)}¢`
    : "N/A";
  const lastPrice = trade.card?.current_actionable_price ?? trade.recommendation?.current_user_entry_price;
  return `
    <div class="orderbook-side"><small>ASKS</small>${rows(asks, "ask")}</div>
    <div class="orderbook-summary"><span>Spread <strong>${escapeHtml(spread)}</strong></span><span>Last price <strong>${escapeHtml(formatOptionalCents(lastPrice))}</strong></span></div>
    <div class="orderbook-side"><small>BIDS</small>${rows(bids, "bid")}</div>
  `;
}

function detailSelectionPanel(trade) {
  const recommendation = trade.recommendation || {};
  const card = trade.card || {};
  return `
    <section class="detail-selection-panel">
      <span class="detail-selection-copy"><small>Recommended side</small><strong>${escapeHtml(trade.outcome)}</strong></span>
      <span class="detail-selection-size"><strong>${escapeHtml(formatShares(card.recommended_shares ?? recommendation.recommended_shares))} shares</strong><small>${escapeHtml(formatOptionalMoney(card.recommended_amount ?? recommendation.recommended_amount))} · ${escapeHtml(formatUnits(card.recommended_units ?? recommendation.recommended_units))}</small></span>
      ${executionToolbar(trade)}
    </section>
  `;
}

function contradictorsMarkup(trade) {
  const wallets = trade.contradicting_wallets || [];
  if (!wallets.length) return "";
  return `<details class="detail-accordion research-opposition" open><summary><span><i class="ph ph-warning" aria-hidden="true"></i>Contradicting Sharps</span><small>${formatMoney(trade.contradictingExposureDollars || 0)} opposing exposure</small><i class="ph ph-caret-down" aria-hidden="true"></i></summary><div class="supporter-list">${wallets.map((wallet) => `<div class="supporter-row"><span><strong>${escapeHtml(wallet.wallet_label || wallet.wallet_address)}</strong><small>${escapeHtml(wallet.opposing_selection || "Opposing selection")} / ${escapeHtml(wallet.top_category || "Category unavailable")}</small></span><span><strong>${formatMoney(wallet.amount)}</strong><small>${formatUnits(wallet.relative_units)} / ${formatOptionalCents(wallet.average_entry_price)}</small></span></div>`).join("")}</div></details>`;
}

function renderTradeDetail(trade) {
  const panel = document.getElementById("trade-detail");
  const recommendation = trade.recommendation || {};
  const card = trade.card || {};
  const primary = trade.primary_trader || {};
  const slippage = slippageComparison(
    card.current_actionable_price ?? recommendation.current_user_entry_price,
    card.trader_average_entry_price ?? recommendation.sharp_average_entry_price ?? trade.average_entry_price,
    card.slippage_fraction ?? recommendation.price_slippage_fraction,
  );
  const slippageTone = slippage?.tone === "better" ? "positive" : slippage?.tone === "worse" ? "negative" : "";
  const categoryHitRate = card.category_hit_rate ?? primary.adjusted_hit_rate;
  const currentPrice = card.current_actionable_price ?? recommendation.current_user_entry_price;
  panel.innerHTML = `
    <div class="detail-header">
      <span class="score-badge large ${confidenceClass(trade.confidence_score)}">${escapeHtml(trade.confidence_score)}</span>
      <div class="detail-title-copy"><p>${escapeHtml(trade.category || "Sports")} · ${escapeHtml(trade.league || "Market")}</p><h2>${escapeHtml(trade.event_title || trade.market_title)}</h2><span>${escapeHtml(humanizeMarketType(trade.sports_market_type))} · ${escapeHtml(trade.event_time_et || "Time unavailable")}</span></div>
      <span class="detail-header-actions">${personalExposureWarning(trade)}<button class="trade-pin-action ${trade.isPinnedByCurrentUser ? "active" : ""}" id="detail-pin-action" type="button" aria-label="${trade.isPinnedByCurrentUser ? "Unpin this trade from" : "Pin this trade to"} your Whiteboard"><i class="ph ${trade.isPinnedByCurrentUser ? "ph-push-pin-fill" : "ph-push-pin"}" aria-hidden="true"></i></button><button class="trade-hide-action" id="detail-hide-action" type="button" aria-label="${trade.isHidden ? "Restore" : "Hide"} this trade"><i class="ph ${trade.isHidden ? "ph-arrow-counter-clockwise" : "ph-eye-slash"}" aria-hidden="true"></i></button><button class="tracker-quick-action" id="detail-track-action" type="button" aria-label="Track this personal trade"><i class="ph ph-plus" aria-hidden="true"></i></button></span>
      <span class="live-price"><small>Executable entry</small><strong>${escapeHtml(formatOptionalCents(currentPrice))}</strong><em>${escapeHtml(trade.agreeing_wallet_count + " Sharp" + (trade.agreeing_wallet_count === 1 ? "" : "s"))}</em></span>
    </div>
    ${detailSelectionPanel(trade)}
    <section class="detail-strip-card">
      <div class="section-label"><span>Why this bet?</span></div>
      <div class="detail-strip">
        ${detailStripMetric("ph-arrow-up-right", formatRelativeSize(card.relative_bet_size ?? primary.relative_units), "Relative bet size")}
        ${detailStripMetric("ph-coins", formatOptionalMoney(card.trader_bet_amount ?? primary.amount, true), "Sharp bet size")}
        ${detailStripMetric("ph-arrows-left-right", slippage?.formatted || "N/A", "Entry slippage", slippageTone)}
      </div>
    </section>
    <section class="detail-strip-card trader-stats-card">
      <div class="section-label"><span>Trader stats</span></div>
      <div class="detail-strip">
        ${detailStripMetric("ph-trophy", primary.top_category || trade.category || "N/A", "Top category")}
        ${detailStripMetric("ph-chart-line-up", number(categoryHitRate) === null ? "N/A" : formatPercent(categoryHitRate, 2), "Adjusted hit rate")}
        ${detailStripMetric("ph-list-numbers", number(primary.sample_size) === null ? "N/A" : String(primary.sample_size), "Settled sample")}
      </div>
    </section>
    <section class="detail-section price-panel">
      <div class="section-label"><span><i class="ph ph-chart-line-up" aria-hidden="true"></i>Price</span><span class="price-range-controls"><button class="active" data-price-range="1d" type="button">1D</button><button data-price-range="1w" type="button">1W</button><button data-price-range="1m" type="button">1M</button><button data-price-range="max" type="button">MAX</button></span></div>
      <div class="price-legend"><span class="trader-entry">Trader entry <strong>${escapeHtml(formatOptionalCents(slippage?.whalePrice))}</strong></span><span class="recommended-entry">Rec entry <strong>${escapeHtml(formatOptionalCents(currentPrice))}</strong></span></div>
      <div class="price-chart" id="price-chart"><div class="chart-loading">Loading verified price history…</div></div>
    </section>
    <section class="detail-section orderbook-panel">
      <div class="section-label"><span><i class="ph ph-chart-bar-horizontal" aria-hidden="true"></i>Order book</span><small>Verified Polymarket CLOB depth</small></div>
      <div class="orderbook">${tradeOrderBook(trade)}</div>
    </section>
    <details class="detail-accordion"><summary><span><i class="ph ph-users-three" aria-hidden="true"></i>Sharps on this trade</span><small>${escapeHtml(sharpCompositionLabel(trade))}</small><i class="ph ph-caret-down" aria-hidden="true"></i></summary><div class="research-badges">${researchBadges(trade)}</div><div class="supporter-list">${supportersMarkup(trade)}</div></details>
    ${contradictorsMarkup(trade)}
    ${whyScore(trade, recommendation)}
    ${whySizing(recommendation, trade)}
    ${executionRiskDetails(recommendation)}
    ${completionTradeDetails(trade, recommendation)}
    <details class="detail-accordion personal-exposure-section"><summary><span><i class="ph ph-user-focus" aria-hidden="true"></i>Personal exposure</span><small>Confirmed fills only</small><i class="ph ph-caret-down" aria-hidden="true"></i></summary><div id="personal-exposure-detail"><div class="chart-loading">Loading personal exposure...</div></div></details>
    <details class="detail-accordion"><summary><span><i class="ph ph-cpu" aria-hidden="true"></i>Model and market details</span><small>${trade.modelTrackerEligible ? "Tracker eligible" : "Not tracker eligible"}</small><i class="ph ph-caret-down" aria-hidden="true"></i></summary><div class="calculation-grid"><div><span>Weighted consensus</span><strong>${escapeHtml(weightedSharpLabel(trade.weighted_sharp_count))}</strong></div><div><span>Lead / Supporting</span><strong>${escapeHtml(`${trade.lead_sharp_count || 0} / ${trade.supporting_sharp_count || 0}`)}</strong></div><div><span>Estimated win</span><strong>${escapeHtml(formatPercent(recommendation.estimated_win_probability))}</strong></div><div><span>Final stake</span><strong>${escapeHtml(formatPercent(recommendation.final_recommended_fraction, 2))}</strong></div><div><span>Model Tracker</span><strong>${trade.modelTrackerEligible ? "Eligible" : "Excluded"}</strong></div><div><span>Market type</span><strong>${escapeHtml(humanizeMarketType(trade.sports_market_type))}</strong></div></div>${trade.modelTrackerRejectionReason ? `<p class="calculation-note">${escapeHtml(trade.modelTrackerRejectionReason)}</p>` : ""}</details>
  `;
  panel.querySelector("#detail-track-action")?.addEventListener("click", () => openPersonalTracker(trade));
  panel.querySelector("#detail-pin-action")?.addEventListener("click", () => pinTrade(trade.id, trade.whiteboardPinId || ""));
  panel.querySelector("#detail-hide-action")?.addEventListener("click", () => {
    if (trade.isHidden) restoreHiddenTrade(trade.hiddenRecordId);
    else hideTrade(trade.id);
  });
  panel.querySelector(".personal-warning")?.addEventListener("click", (event) => {
    const button = event.currentTarget;
    button.setAttribute("aria-expanded", String(button.getAttribute("aria-expanded") !== "true"));
  });
  panel.querySelectorAll("[data-price-range]").forEach((button) => button.addEventListener("click", () => {
    panel.querySelectorAll("[data-price-range]").forEach((item) => item.classList.toggle("active", item === button));
    loadPriceHistory(trade.clob_token_id, currentPrice, button.dataset.priceRange);
  }));
  loadPriceHistory(trade.clob_token_id, currentPrice);
  loadPersonalExposureDetails(trade.id);
  loadTradeEdgeEvidence(trade);
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
  ctx.strokeStyle = "rgba(184, 169, 137, 0.15)";
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i += 1) {
    const lineY = pad + (i / 3) * (height - pad * 1.7);
    ctx.beginPath(); ctx.moveTo(pad, lineY); ctx.lineTo(width - pad / 2, lineY); ctx.stroke();
  }
  const gradient = ctx.createLinearGradient(0, pad, 0, height - pad);
  gradient.addColorStop(0, "rgba(19, 183, 237, 0.2)");
  gradient.addColorStop(1, "rgba(19, 183, 237, 0)");
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
  ctx.strokeStyle = options.color || "#13b7ed";
  ctx.lineWidth = 2.5 * window.devicePixelRatio;
  ctx.stroke();
  ctx.fillStyle = "#aaa69d";
  ctx.font = `${11 * window.devicePixelRatio}px "Roboto Condensed"`;
  ctx.fillText(options.format ? options.format(max) : String(max), 4, pad);
  ctx.fillText(options.format ? options.format(min) : String(min), 4, height - pad);
}

async function loadPriceHistory(tokenId, fallbackPrice, interval = "1d") {
  const container = document.getElementById("price-chart");
  if (!container || !tokenId) {
    if (container) container.innerHTML = emptyState("Price history unavailable", "This trade does not have a verified outcome token.");
    return;
  }
  try {
    const payload = await fetchJson(`/api/price-history?token_id=${encodeURIComponent(tokenId)}&interval=${encodeURIComponent(interval)}`);
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
    const toolbarValue = document.getElementById("bankroll-toolbar-value");
    if (toolbarValue) toolbarValue.textContent = formatMoney(bankroll, bankroll >= 100 ? 0 : 2);
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
  updateActiveFilterCount();
  updateTradeUrl(filters);
  const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== "" && value !== false));
  try {
    const payload = await fetchJson(`/api/trades-to-play?${query.toString()}`);
    const sourceTrades = payload.data || [];
    annotateExecutionMovements(sourceTrades);
    appState.trades = applyClientTradeFilters(sourceTrades, filters);
    if (payload.bankroll) applySizingBankroll(payload.bankroll);
    updateGlobalStatus(payload.status);
    document.getElementById("hidden-trades-count").textContent = String(payload.hiddenCount || 0);
    document.getElementById("whiteboard-count").textContent = String(payload.whiteboardCount || 0);
    document.getElementById("trades-tab-count").textContent = String(payload.pagination?.total ?? appState.trades.length);
    document.getElementById("trade-result-count").textContent = `${appState.trades.length} Pick${appState.trades.length === 1 ? "" : "s"}`;
    document.getElementById("trade-freshness").textContent = `Live book checked ${formatDateTime(payload.status?.last_successful_refresh, "now")}`;
    const currentSport = document.getElementById("trade-sport").value;
    const currentLeague = document.getElementById("trade-league").value;
    const currentWallet = document.getElementById("trade-wallet").value;
    setOptions(document.getElementById("trade-sport"), sourceTrades.map((trade) => trade.category), "All Sports");
    setOptions(document.getElementById("trade-league"), sourceTrades.map((trade) => trade.league), "All leagues");
    setOptions(document.getElementById("trade-wallet"), sourceTrades.flatMap((trade) => (trade.supporting_wallets || []).map((wallet) => wallet.wallet_label)), "All wallets");
    document.getElementById("trade-sport").value = currentSport;
    document.getElementById("trade-league").value = currentLeague;
    document.getElementById("trade-wallet").value = currentWallet;
    const lowInventory = document.getElementById("low-inventory-state");
    if (lowInventory) lowInventory.hidden = appState.trades.length === 0 || appState.trades.length >= 5;
    if (!appState.trades.length) {
      appState.tradeRenderSignatures = {};
      list.innerHTML = emptyState("No actionable trades match", "Past, live, closed, conflicted, illiquid, and unverified markets are intentionally excluded.");
      document.getElementById("trade-detail").innerHTML = emptyState("No trade selected", "Change the date or filters to inspect another verified opportunity.");
      return;
    }
    const selectedParam = new URLSearchParams(window.location.search).get("selected");
    if (!appState.trades.some((trade) => trade.id === appState.selectedTradeId)) {
      appState.selectedTradeId = appState.trades.some((trade) => trade.id === selectedParam) ? selectedParam : appState.trades[0].id;
    }
    syncTradeRows(list, appState.trades);
    selectTrade(appState.selectedTradeId);
  } catch (error) {
    list.innerHTML = errorState(error.message);
    document.getElementById("trade-detail").innerHTML = errorState(error.message);
  }
}

function whiteboardCard(row) {
  const frozen = row.snapshot || {};
  const dynamic = row.dynamic || {};
  const warningTrade = {
    hasContradictingSharps: frozen.warning_flags?.has_contradicting_sharps,
    isNonCategoryConsensus: frozen.warning_flags?.is_non_category_consensus,
  };
  const executionTrade = row.currentTrade || {
    outcome: frozen.selection,
    executionOptions: dynamic.execution_options || [],
  };
  return `<article class="whiteboard-card ${dynamic.above_max_slippage ? "above-slippage" : ""}">
    <header><span class="pinned-label"><i class="ph ph-push-pin-fill" aria-hidden="true"></i>Pinned ${escapeHtml(formatDateTime(row.pinned_at))}</span><span class="research-badges">${researchBadges(warningTrade)}</span><button class="whiteboard-unpin" type="button" data-pin-id="${escapeHtml(row.id)}" aria-label="Unpin this trade"><i class="ph ph-x" aria-hidden="true"></i></button></header>
    <div class="whiteboard-main"><div><small>${escapeHtml(frozen.sport || "Sports")} / ${escapeHtml(frozen.league || "Market")}</small><h3>${escapeHtml(frozen.event_title || frozen.market_title)}</h3><strong>${escapeHtml(frozen.selection)}</strong></div><span class="whiteboard-score"><small>Frozen score</small><strong>${escapeHtml(frozen.confidence_score ?? "N/A")}</strong></span></div>
    <div class="whiteboard-prices"><span><small>Sharp Entry</small><strong>${formatOptionalCents(frozen.sharp_reference_entry)}</strong></span><span><small>Entry When Pinned</small><strong>${formatOptionalCents(frozen.entry_when_pinned)}</strong></span><span><small>Current Entry</small><strong>${formatOptionalCents(dynamic.current_entry)}</strong></span><span><small>Current Slippage</small><strong>${number(dynamic.current_unfavorable_slippage_pct) === null ? "N/A" : `${Number(dynamic.current_unfavorable_slippage_pct).toFixed(2)}%`}</strong></span><span><small>Frozen recommendation</small><strong>${formatOptionalMoney(frozen.recommended_dollar_amount)}</strong></span></div>
    ${dynamic.above_max_slippage ? '<p class="whiteboard-slippage-warning"><i class="ph ph-warning" aria-hidden="true"></i>Above 5% slippage. The frozen research snapshot remains available, but execution may no longer be reasonable.</p>' : ""}
    <footer><span>${escapeHtml(formatDateTime(dynamic.official_event_start_time))}</span><span>${escapeHtml(dynamic.official_event_status || "Unavailable")}</span>${executionToolbar(executionTrade)}${row.currentTrade ? `<button class="whiteboard-track" type="button" data-trade-id="${escapeHtml(row.currentTrade.id)}"><i class="ph ph-plus" aria-hidden="true"></i>Personal Track</button>` : ""}</footer>
  </article>`;
}

async function loadWhiteboard() {
  const list = document.getElementById("whiteboard-list");
  try {
    const sort = document.getElementById("whiteboard-sort")?.value || "event";
    const payload = await fetchJson(`/api/whiteboard?sort=${encodeURIComponent(sort)}`);
    appState.whiteboard = payload.data || [];
    document.getElementById("whiteboard-count").textContent = String(payload.total || 0);
    list.innerHTML = appState.whiteboard.length ? appState.whiteboard.map(whiteboardCard).join("") : emptyState("Your Whiteboard is empty", "Pin any upcoming trade to preserve its research snapshot here.");
  } catch (error) {
    list.innerHTML = errorState(error.message);
  }
}

async function pinTrade(tradeId, pinId = "") {
  try {
    if (pinId) await fetchJson(`/api/whiteboard/${encodeURIComponent(pinId)}`, { method: "DELETE" });
    else await fetchJson("/api/whiteboard", { method: "POST", body: JSON.stringify({ trade_id: tradeId }) });
    showToast(pinId ? "Trade removed from Whiteboard" : "Trade pinned to Whiteboard", "success");
    await Promise.all([loadTrades(), loadWhiteboard()]);
  } catch (error) {
    showToast(error.message, "error");
  }
}

function selectTradesView(view) {
  appState.tradesView = view === "whiteboard" ? "whiteboard" : "feed";
  document.querySelector(".trade-workspace").hidden = appState.tradesView !== "feed";
  document.getElementById("whiteboard-workspace").hidden = appState.tradesView !== "whiteboard";
  document.querySelectorAll("[data-trades-view]").forEach((button) => {
    const active = button.dataset.tradesView === appState.tradesView;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  if (appState.tradesView === "whiteboard") loadWhiteboard();
}

function signedMoney(value) {
  const parsed = number(value) || 0;
  return `${parsed > 0 ? "+" : ""}${formatMoney(parsed)}`;
}

function pnlTone(value) {
  const parsed = number(value) || 0;
  return parsed > 0 ? "positive" : parsed < 0 ? "negative" : "neutral";
}

function positionReturn(position) {
  const value = number(position.returnPct);
  return value === null ? "N/A" : `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
}

function personalSellButton(position, compact = false) {
  const quote = position.quote || {};
  const price = number(quote.effectiveSellPrice);
  const manualVenue = String(position.provider).toLowerCase() !== "polymarket";
  const unavailable = price === null || ["unavailable", "stale"].includes(quote.quoteFreshness);
  const disabled = unavailable && !manualVenue;
  const label = manualVenue ? "Record exit manually" : unavailable ? "Exit quote unavailable" : `Record sell ${formatCents(price)}`;
  return `<button class="personal-sell-button ${compact ? "compact" : ""}" type="button" data-sell-position="${escapeHtml(position.positionId)}" ${disabled ? "disabled" : ""}><i class="ph ph-arrow-square-out" aria-hidden="true"></i><span>${escapeHtml(position.provider)}<strong>${label}</strong></span></button>`;
}

function personalPositionRow(position, closed = false) {
  const pnl = closed ? position.realizedPnl : position.totalPnl;
  const selectedId = closed ? appState.selectedClosedPositionId : appState.selectedPersonalPositionId;
  const status = closed ? (position.closureMethod || "closed") : position.status;
  return `<article class="personal-position-row ${String(selectedId) === String(position.positionId) ? "selected" : ""}" data-position-id="${escapeHtml(position.positionId)}" data-position-state="${closed ? "closed" : "open"}" tabindex="0">
    <div class="position-return ${pnlTone(pnl)}"><strong>${closed ? signedMoney(pnl) : positionReturn(position)}</strong><small>${closed ? positionReturn(position) : signedMoney(position.unrealizedPnl)}</small></div>
    <div class="position-copy"><span class="position-status ${closed ? "closed" : ""}">${escapeHtml(String(status).replaceAll("_", " "))}</span><small>${escapeHtml(position.provider)} · ${escapeHtml(formatDateTime(position.eventStartTime))}</small><h3>${escapeHtml(position.eventTitle || position.marketTitle)}</h3><p>${escapeHtml(position.marketTitle || "Market")}</p></div>
    <div class="position-selection"><span><strong>${escapeHtml(position.selection)}</strong><small>${formatShares(closed ? position.totalPurchasedShares : position.remainingShares)} shares · ${formatCents(position.averageBuyEntry)} entry</small></span>${closed ? `<strong class="closure-price">${number(position.averageSellEntry) !== null ? formatExitCents(position.averageSellEntry) : number(position.settlementPrice) !== null ? `${formatExitCents(position.settlementPrice)} settled` : "Closed"}</strong>` : personalSellButton(position, true)}</div>
  </article>`;
}

function depthMarkup(position) {
  const quote = position.quote || {};
  if (!quote.bestBid) return '<div class="position-empty-section">Executable bid depth is unavailable for this provider.</div>';
  return `<div class="position-depth"><span><small>Best visible bid</small><strong>${formatCents(quote.bestBid)}</strong></span><span><small>Effective exit</small><strong>${formatCents(quote.effectiveSellPrice)}</strong></span><span><small>Executable shares</small><strong>${formatShares(quote.executableShares)}</strong></span><span><small>Unfilled shares</small><strong>${formatShares(quote.unfilledShares)}</strong></span></div>`;
}

function renderPersonalPositionDetail(position, closed = false) {
  const target = document.getElementById(closed ? "personal-closed-detail" : "personal-position-detail");
  if (!position) {
    target.innerHTML = emptyState(closed ? "Select a closed position" : "Select an open position", "Choose a personal position to inspect its cashflows and pricing.");
    return;
  }
  const pnl = closed ? position.realizedPnl : position.totalPnl;
  target.innerHTML = `<div class="position-detail-header"><span class="position-detail-return ${pnlTone(pnl)}">${closed ? signedMoney(pnl) : positionReturn(position)}</span><div><small>PERSONAL TRACKER · ${escapeHtml(position.provider)}</small><h2>${escapeHtml(position.eventTitle || position.marketTitle)}</h2><p>${escapeHtml(position.marketTitle || "Market")}</p></div></div>
    <section class="position-detail-selection"><span><small>Selection</small><strong>${escapeHtml(position.selection)}</strong></span><span><strong>${formatShares(closed ? position.totalPurchasedShares : position.remainingShares)} shares</strong><small>${closed ? "Total purchased" : `${formatOptionalMoney(position.currentMarketValue)} current value`}</small></span>${closed ? "" : personalSellButton(position)}</section>
    <section class="position-pnl-strip"><span><small>Your entry</small><strong>${formatCents(position.averageBuyEntry)}</strong></span><span><small>${closed ? "Final exit" : "Executable exit"}</small><strong>${closed ? formatExitCents(position.averageSellEntry ?? position.settlementPrice) : formatOptionalCents(position.quote?.effectiveSellPrice)}</strong></span><span><small>Total return</small><strong class="${pnlTone(pnl)}">${positionReturn(position)}</strong></span></section>
    <section class="position-detail-card position-price-history"><header><span><i class="ph ph-chart-line" aria-hidden="true"></i> Price</span><span class="position-chart-ranges"><button class="active" data-position-range="1d">1D</button><button data-position-range="1w">1W</button><button data-position-range="1m">1M</button><button data-position-range="max">MAX</button></span></header><div class="position-history-chart" id="personal-position-chart-${closed ? "closed" : "open"}"><div class="chart-loading">Loading verified price history…</div></div></section>
    <section class="position-detail-card"><header><span><i class="ph ph-receipt" aria-hidden="true"></i> Position cashflows</span></header><div class="position-cashflow-grid"><span><small>Purchase cost</small><strong>${formatMoney(position.grossPurchaseCost)}</strong></span><span><small>Buy fees</small><strong>${formatMoney(position.buyFees)}</strong></span><span><small>Sale proceeds</small><strong>${formatMoney(position.netSaleProceeds)}</strong></span><span><small>Sell fees</small><strong>${formatMoney(position.sellFees)}</strong></span><span><small>Realized P&amp;L</small><strong class="${pnlTone(position.realizedPnl)}">${signedMoney(position.realizedPnl)}</strong></span><span><small>${closed ? "Closure" : "Unrealized P&L"}</small><strong class="${pnlTone(position.unrealizedPnl)}">${closed ? escapeHtml(position.closureMethod || "Closed") : signedMoney(position.unrealizedPnl)}</strong></span></div></section>
    ${closed ? "" : `<section class="position-detail-card"><header><span><i class="ph ph-list-dashes" aria-hidden="true"></i> Executable sell depth</span><small>Bids are used to value exits</small></header>${depthMarkup(position)}</section>`}`;
  loadPersonalPositionHistory(position, closed);
}

async function loadPersonalPositionHistory(position, closed, interval = "1d") {
  const container = document.getElementById(`personal-position-chart-${closed ? "closed" : "open"}`);
  if (!container) return;
  try {
    const payload = await fetchJson(`/api/personal-positions/${encodeURIComponent(position.positionId)}/price-history?interval=${encodeURIComponent(interval)}`);
    const points = (payload.data || []).map((point) => ({ timestamp: point.t, value: Number(point.p) })).filter((point) => Number.isFinite(point.value));
    drawLineChart(container, points, { format: formatExitCents });
  } catch (error) {
    container.innerHTML = emptyState("Price history unavailable", "This provider does not expose verified price history here.");
  }
}

async function loadPersonalPositions(state = "open") {
  const closed = state === "closed";
  const list = document.getElementById(closed ? "personal-closed-list" : "personal-position-list");
  const params = new URLSearchParams({ state });
  if (closed) params.set("closure", appState.closureFilter);
  const query = document.getElementById("trade-search")?.value.trim();
  if (query) params.set("q", query);
  try {
    const payload = await fetchJson(`/api/personal-positions?${params.toString()}`);
    document.getElementById("positions-tab-count").textContent = String(payload.counts.positions);
    document.getElementById("closed-tab-count").textContent = String(payload.counts.closed);
    const rows = payload.data || [];
    if (closed) appState.personalClosed = rows;
    else appState.personalPositions = rows;
    const selectedKey = closed ? "selectedClosedPositionId" : "selectedPersonalPositionId";
    if (!rows.some((item) => item.positionId === appState[selectedKey])) appState[selectedKey] = rows[0]?.positionId || null;
    list.innerHTML = rows.length ? rows.map((item) => personalPositionRow(item, closed)).join("") : emptyState(closed ? "No closed personal positions yet" : "No open personal positions", closed ? "Sold and resolved Personal Tracker bets will appear here." : "Bets you manually track will appear here until they are sold or resolved.");
    renderPersonalPositionDetail(rows.find((item) => item.positionId === appState[selectedKey]), closed);
  } catch (error) {
    list.innerHTML = errorState(error.message);
  }
}

function selectPersonalPosition(positionId, closed) {
  if (closed) appState.selectedClosedPositionId = positionId;
  else appState.selectedPersonalPositionId = positionId;
  const rows = closed ? appState.personalClosed : appState.personalPositions;
  const list = document.getElementById(closed ? "personal-closed-list" : "personal-position-list");
  list.querySelectorAll(".personal-position-row").forEach((row) => row.classList.toggle("selected", row.dataset.positionId === positionId));
  renderPersonalPositionDetail(rows.find((item) => item.positionId === positionId), closed);
}

function selectWorkspaceTab(tab, { syncUrl = true } = {}) {
  appState.workspaceTab = ["trades", "positions", "closed"].includes(tab) ? tab : "trades";
  localStorage.setItem("iconbets-trades-workspace-tab", appState.workspaceTab);
  document.querySelector(".trade-workspace").hidden = appState.workspaceTab !== "trades";
  document.getElementById("whiteboard-workspace").hidden = true;
  document.getElementById("personal-positions-workspace").hidden = appState.workspaceTab !== "positions";
  document.getElementById("personal-closed-workspace").hidden = appState.workspaceTab !== "closed";
  document.querySelectorAll("[data-workspace-tab]").forEach((button) => {
    const active = button.dataset.workspaceTab === appState.workspaceTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.getElementById("trade-result-count").hidden = appState.workspaceTab !== "trades";
  document.querySelector(".model-status-pill").hidden = appState.workspaceTab !== "trades";
  document.getElementById("trade-search").placeholder = appState.workspaceTab === "trades" ? "Search" : "Search personal positions";
  if (appState.workspaceTab === "positions") loadPersonalPositions("open");
  if (appState.workspaceTab === "closed") loadPersonalPositions("closed");
  if (syncUrl) updateTradeUrl(readTradeControls());
}

function openWhiteboard() {
  document.querySelector(".trade-workspace").hidden = true;
  document.getElementById("personal-positions-workspace").hidden = true;
  document.getElementById("personal-closed-workspace").hidden = true;
  document.getElementById("whiteboard-workspace").hidden = false;
  loadWhiteboard();
}

function pnlChart(points) {
  if (!points.length) return emptyState("No realized P&L yet", "Sold and resolved Personal Tracker positions will build this chart.");
  const values = [0, ...points.map((point) => Number(point.profitLoss) || 0)];
  const min = Math.min(...values); const max = Math.max(...values); const span = Math.max(max - min, 1);
  const path = values.map((value, index) => `${index ? "L" : "M"} ${(index / Math.max(values.length - 1, 1)) * 320} ${110 - ((value - min) / span) * 90}`).join(" ");
  const zeroY = 110 - ((0 - min) / span) * 90;
  const tone = values[values.length - 1] < 0 ? "negative" : "positive";
  return `<svg viewBox="0 0 320 125" role="img" aria-label="Cumulative realized Personal Tracker profit and loss"><line x1="0" y1="${zeroY}" x2="320" y2="${zeroY}" class="pnl-zero-line"/><path d="${path}" class="pnl-line ${tone}" fill="none"/><path d="${path} L 320 115 L 0 115 Z" class="pnl-area ${tone}"/></svg>`;
}

async function loadPersonalPnl(period = appState.pnlPeriod) {
  appState.pnlPeriod = period;
  const payload = await fetchJson(`/api/personal-pnl?period=${encodeURIComponent(period)}`);
  const data = payload.data;
  const labels = { today: "TODAY", week: "PAST WEEK", month: "THIS MONTH", year: "THIS YEAR", all: "ALL TIME" };
  document.getElementById("personal-pnl-period-label").textContent = labels[period] || labels.week;
  [["personal-pnl-period-value", data.realizedPnl], ["personal-pnl-today-value", data.todayPnl], ["personal-pnl-expanded-value", data.realizedPnl], ["personal-pnl-expanded-today", data.todayPnl], ["personal-pnl-yesterday", data.yesterdayPnl]].forEach(([id, value]) => { const node = document.getElementById(id); node.textContent = `${signedMoney(value)}${id.includes("today") ? " Today" : id.includes("yesterday") ? " Yesterday" : ""}`; node.className = pnlTone(value); });
  document.getElementById("personal-pnl-chart").innerHTML = pnlChart(data.graph || []);
  document.querySelectorAll("[data-pnl-period]").forEach((button) => button.classList.toggle("active", button.dataset.pnlPeriod === period));
}

function openSellDialog(position) {
  appState.sellPosition = position;
  const dialog = document.getElementById("personal-sell-dialog");
  document.getElementById("personal-sell-summary").innerHTML = `<strong>${escapeHtml(position.eventTitle)}</strong><span>${escapeHtml(position.selection)} · ${escapeHtml(position.provider)}</span><small>${formatShares(position.remainingShares)} open shares · ${formatCents(position.averageBuyEntry)} average entry</small>`;
  document.getElementById("personal-sell-shares").value = position.remainingShares;
  document.getElementById("personal-sell-price").value = number(position.quote?.effectiveSellPrice) ? (position.quote.effectiveSellPrice * 100).toFixed(1) : "";
  document.getElementById("personal-sell-fees").value = "0";
  const link = document.getElementById("personal-sell-provider-link");
  link.href = position.marketUrl || "#"; link.hidden = !position.marketUrl;
  updateSellCalculation();
  dialog.showModal();
}

function updateSellCalculation() {
  const position = appState.sellPosition; if (!position) return;
  const shares = number(document.getElementById("personal-sell-shares").value) || 0;
  const price = (number(document.getElementById("personal-sell-price").value) || 0) / 100;
  const fee = number(document.getElementById("personal-sell-fees").value) || 0;
  const gross = shares * price; const cost = shares * (position.totalPaid / position.totalPurchasedShares); const realized = gross - fee - cost;
  document.getElementById("personal-sell-calculation").innerHTML = `<span><small>Gross proceeds</small><strong>${formatMoney(gross)}</strong></span><span><small>Net proceeds</small><strong>${formatMoney(gross - fee)}</strong></span><span><small>Estimated realized P&amp;L</small><strong class="${pnlTone(realized)}">${signedMoney(realized)}</strong></span><span><small>Remaining shares</small><strong>${formatShares(Math.max(position.remainingShares - shares, 0))}</strong></span>`;
}

async function recordPersonalExit(event) {
  event.preventDefault(); const position = appState.sellPosition; if (!position) return;
  const submit = document.getElementById("personal-sell-submit"); submit.disabled = true;
  try {
    await fetchJson(`/api/personal-positions/${encodeURIComponent(position.positionId)}/exits`, { method: "POST", body: JSON.stringify({ shares: Number(document.getElementById("personal-sell-shares").value), sell_price: Number(document.getElementById("personal-sell-price").value) / 100, fees: Number(document.getElementById("personal-sell-fees").value) || 0, idempotency_key: crypto.randomUUID() }) });
    document.getElementById("personal-sell-dialog").close(); showToast("Personal Tracker exit recorded", "success");
    await Promise.all([loadPersonalPositions("open"), loadPersonalPositions("closed"), loadPersonalPnl()]);
  } catch (error) { showToast(error.message, "error"); } finally { submit.disabled = false; }
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
  const reload = debounce(() => {
    if (appState.workspaceTab === "positions") loadPersonalPositions("open");
    else if (appState.workspaceTab === "closed") loadPersonalPositions("closed");
    else loadTrades();
  }, 280);
  const filterDefaults = { q: "", date_range: "today", min_sharps: "0", min_confidence: "0", sport: "", league: "", wallet: "", classification: "", minEntryCents: "", maxEntryCents: "", custom_start: "", custom_end: "", show_hidden: false, execution: "", min_bet: "0", max_slippage: "", sort: "confidence-desc" };
  const applyPriceFields = () => {
    appState.appliedEntryPriceFilters = {
      minEntryCents: document.getElementById("min-entry-cents").value.trim(),
      maxEntryCents: document.getElementById("max-entry-cents").value.trim(),
    };
    updateActiveFilterCount();
  };
  const resetFilters = () => {
    applyTradeFiltersToControls(filterDefaults);
    appState.appliedEntryPriceFilters = { minEntryCents: "", maxEntryCents: "" };
    document.getElementById("share-price-error").textContent = "";
    updateSharePriceSummary();
    updateActiveFilterCount();
    loadTrades();
  };
  document.getElementById("trade-search").addEventListener("input", reload);
  ["trade-date-range", "trade-sharps", "trade-confidence", "trade-sport", "trade-league", "trade-wallet", "trade-classification", "custom-start", "custom-end", "show-hidden-trades", "trade-execution", "trade-min-bet", "trade-max-slippage", "trade-sort"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => {
      if (id === "trade-date-range") {
        const custom = document.getElementById(id).value === "custom";
        document.querySelectorAll(".custom-time").forEach((field) => { field.hidden = !custom; });
      }
      updateActiveFilterCount();
    });
  });
  document.getElementById("more-filters-button").addEventListener("click", () => {
    const panel = document.getElementById("more-filters");
    setMoreFiltersExpanded(panel.hidden);
  });
  document.getElementById("trade-settings-close").addEventListener("click", () => setMoreFiltersExpanded(false));
  document.getElementById("trades-drawer-backdrop").addEventListener("click", () => setMoreFiltersExpanded(false));
  document.getElementById("apply-trade-settings").addEventListener("click", () => {
    if (!validateSharePriceControls()) return;
    applyPriceFields();
    setMoreFiltersExpanded(false);
    loadTrades();
  });
  document.getElementById("clear-trade-filters").addEventListener("click", resetFilters);
  document.getElementById("low-inventory-clear").addEventListener("click", resetFilters);
  document.getElementById("apply-share-price").addEventListener("click", () => {
    if (validateSharePriceControls()) {
      applyPriceFields();
    }
  });
  document.getElementById("clear-share-price").addEventListener("click", () => {
    document.getElementById("min-entry-cents").value = "";
    document.getElementById("max-entry-cents").value = "";
    appState.appliedEntryPriceFilters = { minEntryCents: "", maxEntryCents: "" };
    document.getElementById("share-price-error").textContent = "";
    updateSharePriceSummary();
    updateActiveFilterCount();
  });
  ["min-entry-cents", "max-entry-cents"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
      document.getElementById("share-price-error").textContent = "";
      updateSharePriceSummary();
    });
    document.getElementById(id).addEventListener("keydown", (event) => {
      if (event.key === "Enter" && validateSharePriceControls()) {
        applyPriceFields();
      }
    });
  });
  document.getElementById("save-trade-view").addEventListener("click", () => {
    if (!validateSharePriceControls()) return;
    applyPriceFields();
    localStorage.setItem("iconbets-saved-trade-view", JSON.stringify(readTradeControls()));
    document.getElementById("saved-filter-status").textContent = "Saved in this browser";
    showToast("Trade view saved", "success");
  });
  document.getElementById("load-trade-view").addEventListener("click", () => {
    try {
      const saved = JSON.parse(localStorage.getItem("iconbets-saved-trade-view") || "null");
      if (!saved) {
        showToast("No saved trade view yet", "neutral");
        return;
      }
      applyTradeFiltersToControls({ ...filterDefaults, ...saved });
      updateActiveFilterCount();
      document.getElementById("saved-filter-status").textContent = "Saved view loaded";
      loadTrades();
    } catch (error) {
      showToast("Saved trade view could not be loaded", "error");
    }
  });
  document.getElementById("bankroll-popover-button").addEventListener("click", () => {
    const panel = document.getElementById("bankroll-popover");
    togglePopover("bankroll-popover-button", "bankroll-popover", panel.hidden);
  });
  document.getElementById("trades-more-button").addEventListener("click", () => {
    const panel = document.getElementById("trades-more-menu");
    togglePopover("trades-more-button", "trades-more-menu", panel.hidden);
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
  document.getElementById("personal-existing-tag")?.addEventListener("change", (event) => {
    addPersonalTag(event.target.value);
    event.target.value = "";
  });
  document.getElementById("personal-add-tag")?.addEventListener("click", () => {
    const input = document.getElementById("personal-new-tag");
    addPersonalTag(input.value);
    input.value = "";
    input.focus();
  });
  document.getElementById("personal-new-tag")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    addPersonalTag(event.currentTarget.value);
    event.currentTarget.value = "";
  });
  document.getElementById("personal-selected-tags")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-personal-tag]");
    if (!button) return;
    appState.personalSelectedTags = appState.personalSelectedTags.filter((tag) => tag !== button.dataset.removePersonalTag);
    renderPersonalSelectedTags();
  });
  ["personal-entry-price", "personal-shares", "personal-fees"].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", updatePersonalPurchaseTotal);
  });
  document.getElementById("hidden-trades-button")?.addEventListener("click", () => {
    togglePopover("trades-more-button", "trades-more-menu", false);
    openHiddenTrades();
  });
  document.getElementById("hidden-trades-close")?.addEventListener("click", closeHiddenTrades);
  document.getElementById("hidden-trades-dismiss")?.addEventListener("click", closeHiddenTrades);
  document.getElementById("restore-all-hidden")?.addEventListener("click", restoreAllHiddenTrades);
  document.getElementById("hidden-trades-dialog")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeHiddenTrades();
  });
  const list = document.getElementById("trade-list");
  list.addEventListener("click", (event) => {
    const target = event.target;
    const executionLink = target.closest("[data-execution-trade-id]");
    if (executionLink) {
      const trade = appState.trades.find((item) => String(item.id) === executionLink.dataset.executionTradeId);
      if (trade && !confirmExecutionViolations(executionLink, trade)) event.preventDefault();
      return;
    }
    const tracker = target.closest(".tracker-quick-action");
    if (tracker) {
      const trade = appState.trades.find((item) => String(item.id) === tracker.dataset.tradeId);
      if (trade) openPersonalTracker(trade);
      return;
    }
    const pin = target.closest(".trade-pin-action");
    if (pin) { pinTrade(pin.dataset.tradeId, pin.dataset.pinId); return; }
    const hide = target.closest(".trade-hide-action");
    if (hide) { hideTrade(hide.dataset.tradeId); return; }
    const restore = target.closest(".trade-restore-action");
    if (restore) { restoreHiddenTrade(restore.dataset.hiddenId); return; }
    const expandable = target.closest(".slippage-chip, .personal-warning");
    if (expandable) {
      const selector = expandable.classList.contains("slippage-chip") ? ".slippage-chip" : ".personal-warning";
      const expanded = expandable.getAttribute("aria-expanded") === "true";
      list.querySelectorAll(selector).forEach((item) => item.setAttribute("aria-expanded", "false"));
      expandable.setAttribute("aria-expanded", String(!expanded));
      return;
    }
    if (target.closest("a, button")) return;
    const card = target.closest(".trade-card");
    if (card) selectTrade(card.dataset.tradeId, true);
  });
  document.querySelectorAll("[data-workspace-tab]").forEach((button) => button.addEventListener("click", () => selectWorkspaceTab(button.dataset.workspaceTab)));
  document.getElementById("open-whiteboard-button")?.addEventListener("click", () => { togglePopover("trades-more-button", "trades-more-menu", false); openWhiteboard(); });
  document.getElementById("close-whiteboard-button")?.addEventListener("click", () => selectWorkspaceTab("trades"));
  document.getElementById("whiteboard-list")?.addEventListener("click", (event) => {
    const unpin = event.target.closest(".whiteboard-unpin");
    if (unpin) pinTrade("", unpin.dataset.pinId);
    const track = event.target.closest(".whiteboard-track");
    if (track) {
      const row = appState.whiteboard.find((item) => String(item.currentTrade?.id) === String(track.dataset.tradeId));
      if (row?.currentTrade) openPersonalTracker(row.currentTrade);
    }
  });
  document.getElementById("whiteboard-sort")?.addEventListener("change", () => loadWhiteboard());
  ["personal-position-list", "personal-closed-list"].forEach((id) => document.getElementById(id)?.addEventListener("click", (event) => {
    const sell = event.target.closest("[data-sell-position]");
    const closed = id === "personal-closed-list";
    const rows = closed ? appState.personalClosed : appState.personalPositions;
    if (sell) { const position = rows.find((item) => item.positionId === sell.dataset.sellPosition); if (position) openSellDialog(position); return; }
    const row = event.target.closest(".personal-position-row"); if (row) selectPersonalPosition(row.dataset.positionId, closed);
  }));
  ["personal-position-detail", "personal-closed-detail"].forEach((id) => document.getElementById(id)?.addEventListener("click", (event) => {
    const sell = event.target.closest("[data-sell-position]");
    const closed = id === "personal-closed-detail";
    const rows = closed ? appState.personalClosed : appState.personalPositions;
    if (sell) { const position = rows.find((item) => item.positionId === sell.dataset.sellPosition); if (position) openSellDialog(position); return; }
    const range = event.target.closest("[data-position-range]");
    if (range) { const positionId = closed ? appState.selectedClosedPositionId : appState.selectedPersonalPositionId; const position = rows.find((item) => item.positionId === positionId); if (position) { event.currentTarget.querySelectorAll("[data-position-range]").forEach((item) => item.classList.toggle("active", item === range)); loadPersonalPositionHistory(position, closed, range.dataset.positionRange); } }
  }));
  document.querySelectorAll("[data-closure-filter]").forEach((button) => button.addEventListener("click", () => { appState.closureFilter = button.dataset.closureFilter; document.querySelectorAll("[data-closure-filter]").forEach((item) => item.classList.toggle("active", item === button)); loadPersonalPositions("closed"); }));
  document.getElementById("personal-pnl-button")?.addEventListener("click", () => { const panel = document.getElementById("personal-pnl-popover"); togglePopover("personal-pnl-button", "personal-pnl-popover", panel.hidden); });
  document.querySelectorAll("[data-pnl-period]").forEach((button) => button.addEventListener("click", () => loadPersonalPnl(button.dataset.pnlPeriod)));
  document.getElementById("personal-sell-form")?.addEventListener("submit", recordPersonalExit);
  document.getElementById("personal-sell-close")?.addEventListener("click", () => document.getElementById("personal-sell-dialog").close());
  document.getElementById("personal-sell-dismiss")?.addEventListener("click", () => document.getElementById("personal-sell-dialog").close());
  ["personal-sell-shares", "personal-sell-price", "personal-sell-fees"].forEach((id) => document.getElementById(id)?.addEventListener("input", updateSellCalculation));
  document.getElementById("sell-full-position")?.addEventListener("click", () => { document.getElementById("personal-sell-shares").value = appState.sellPosition?.remainingShares || ""; updateSellCalculation(); });
  document.getElementById("sell-half-position")?.addEventListener("click", () => { document.getElementById("personal-sell-shares").value = ((appState.sellPosition?.remainingShares || 0) / 2).toFixed(2); updateSellCalculation(); });
  list.addEventListener("keydown", (event) => {
    if (!['Enter', ' '].includes(event.key) || event.target.closest("a, button")) return;
    const card = event.target.closest(".trade-card");
    if (!card) return;
    event.preventDefault();
    selectTrade(card.dataset.tradeId, true);
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".toolbar-popover-shell")) {
      togglePopover("bankroll-popover-button", "bankroll-popover", false);
      togglePopover("trades-more-button", "trades-more-menu", false);
      togglePopover("personal-pnl-button", "personal-pnl-popover", false);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    setMoreFiltersExpanded(false);
    togglePopover("bankroll-popover-button", "bankroll-popover", false);
    togglePopover("trades-more-button", "trades-more-menu", false);
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
  const requestedTab = new URLSearchParams(window.location.search).get("tab") || localStorage.getItem("iconbets-trades-workspace-tab") || "trades";
  selectWorkspaceTab(requestedTab, { syncUrl: false });
  loadPersonalPnl();
  loadPersonalPositions("open");
  loadPersonalPositions("closed");
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
  const unit = number(wallet.base_unit);
  const actionableUnits = number(wallet.actionable_position_units);
  const explicitActionableExposure = number(wallet.minimum_actionable_exposure_dollars);
  const actionableExposure = explicitActionableExposure ?? (unit !== null && actionableUnits !== null ? unit * actionableUnits : null);
  const categoryStats = wallet.top_category_stats || {};
  const categorySample = number(categoryStats.sample_size);
  const categoryRecord = categorySample === null
    ? "Awaiting settled history"
    : `${categoryStats.wins || 0}-${categoryStats.losses || 0} | ${categorySample} settled`;
  const subCategoryStats = wallet.sub_top_category_stats || [];
  const subCategoryRecord = subCategoryStats.length
    ? subCategoryStats.map((stats) => `${stats.category} ${stats.wins || 0}-${stats.losses || 0} | ${stats.sample_size || 0} settled`).join(" · ")
    : "Awaiting settled history";
  return `
    <article class="wallet-card">
      <div class="wallet-card-head"><span class="wallet-avatar"><i class="ph ph-wallet" aria-hidden="true"></i></span><div><h2>${escapeHtml(wallet.label)}</h2><span class="status-label ${escapeHtml(sync)}">${escapeHtml(sync)}</span></div></div>
      <button class="address-copy" type="button" data-copy-address="${escapeHtml(wallet.address)}"><span>${escapeHtml(wallet.display_address || wallet.address)}</span><i class="ph ph-copy" aria-hidden="true"></i></button>
      <div class="wallet-stats"><div><span>Open positions</span><strong>${wallet.open_position_count ?? 0}</strong></div><div><span>History events</span><strong>${wallet.historical_position_count ?? 0}</strong></div><div><span>Base unit</span><strong>${wallet.base_unit ? formatMoney(wallet.base_unit) : "Estimating"}</strong></div></div>
      <div class="wallet-sync wallet-meta">${[
        walletMeta("Top category", wallet.top_category_display || wallet.top_category || "Awaiting classification"),
        walletMeta("Sub-top categories", (wallet.sub_top_categories || []).join(", ") || "None configured"),
        walletMeta("Sub-category record", subCategoryRecord),
        walletMeta("Category record", categoryRecord),
        walletMeta("Adjusted hit rate", number(categoryStats.adjusted_hit_rate) === null ? "Awaiting settled history" : formatPercent(categoryStats.adjusted_hit_rate)),
        walletMeta("Category P/L", number(categoryStats.profit_loss) === null ? "Awaiting settled history" : formatMoney(categoryStats.profit_loss)),
        walletMeta("Category source", wallet.top_category_source ? String(wallet.top_category_source).replaceAll("_", " ") : "Awaiting classification"),
        walletMeta("Half unit", unit === null ? "Estimating" : formatMoney(unit / 2)),
        walletMeta("Execution tranche", wallet.typical_execution_tranche_dollars ? `Approx. ${formatMoney(wallet.typical_execution_tranche_dollars)}` : "Not separately configured", "An execution tranche is not a full unit. Individual small fills are aggregated and should not be copied independently."),
        walletMeta("Actionable exposure", actionableExposure === null ? "Uses global threshold" : `${formatMoney(actionableExposure)} / ${(actionableUnits || 0).toFixed(2)}u`, "Signals become actionable only after completed fills are aggregated to this net exposure."),
        walletMeta("Type", wallet.bettor_type || "Not yet classified"),
        walletMeta("Selectivity", wallet.selectivity || "Not yet classified"),
        walletMeta("Hold", wallet.hold_tendency || "Not yet classified"),
        walletMeta("Copyability", wallet.copyability || "Not yet classified"),
        walletMeta("Execution", wallet.execution_style || "Not yet classified"),
        walletMeta("Strategy", wallet.general_strategy || "Not yet classified"),
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

function formatClvPercent(value) {
  const parsed = number(value);
  if (parsed === null) return "Unavailable";
  return `${parsed > 0 ? "+" : ""}${parsed.toFixed(2)}%`;
}

function formatClvCents(value) {
  const parsed = number(value);
  if (parsed === null) return "Unavailable";
  return `${parsed > 0 ? "+" : ""}${parsed.toFixed(1)}\u00a2`;
}

function clvCell(row) {
  const clv = row.clv || {};
  const status = String(clv.clv_status || "pending").toLowerCase();
  if (status !== "captured") {
    const labels = {
      pending: "CLV Pending",
      unavailable: "CLV Unavailable",
      void: "CLV Void",
      stale_quote: "Stale quote",
      market_mapping_error: "Mapping error",
    };
    return `<span class="clv-status neutral" title="${escapeHtml(clv.clv_unavailable_reason || "Closing line has not been captured")}">${escapeHtml(labels[status] || "CLV Unavailable")}</span>`;
  }
  const pct = number(clv.clv_pct);
  const tone = pct > 0 ? "positive" : pct < 0 ? "negative" : "neutral";
  const entryMarker = Math.max(1, Math.min(99, (number(clv.entry_price) || 0) * 100));
  const closeMarker = Math.max(1, Math.min(99, (number(clv.closing_effective_price) || 0) * 100));
  return `<details class="clv-details ${tone}">
    <summary><strong>${escapeHtml(formatClvPercent(pct))} CLV</strong><small>${escapeHtml(formatClvCents(clv.clv_cents))}</small></summary>
    <span><b>Provider</b>${escapeHtml(clv.provider || "Polymarket")}</span>
    <span><b>Entry</b>${escapeHtml(formatCents(clv.entry_price))}</span>
    <span><b>Executable close</b>${escapeHtml(formatCents(clv.closing_effective_price))}</span>
    <span><b>Closing midpoint</b>${escapeHtml(formatCents(clv.closing_midpoint))}</span>
    <span><b>Midpoint CLV</b>${escapeHtml(formatClvPercent(clv.midpoint_clv_pct))}</span>
    <span><b>Closing snapshot</b>${escapeHtml(formatDateTime(clv.closing_snapshot_timestamp))}</span>
    <span><b>Event start</b>${escapeHtml(formatDateTime(clv.official_event_start_timestamp))}</span>
    <span><b>Settlement</b>${escapeHtml(formatDateTime(row.settled_at, "Pending"))}</span>
    <span><b>Quote freshness</b>${escapeHtml(clv.quote_age_ms === null || clv.quote_age_ms === undefined ? "Unavailable" : `${(Number(clv.quote_age_ms) / 1000).toFixed(0)}s`)}</span>
    <span><b>Comparison stake</b>${escapeHtml(formatMoney(clv.comparison_stake || clv.entry_stake))}</span>
    <span><b>Liquidity</b>${escapeHtml(clv.liquidity_quality || "Unavailable")}</span>
    <span class="clv-marker-chart"><b>Price markers</b><i class="entry" style="left:${entryMarker}%">Entry</i><i class="close" style="left:${closeMarker}%">Close</i></span>
  </details>`;
}

function sharpCell(snapshot = {}) {
  const primary = snapshot.primary_sharp || null;
  const wallets = Array.isArray(snapshot.agreeing_sharps) ? snapshot.agreeing_sharps : [];
  const sourceStatus = String(snapshot.sharp_source_status || "unavailable");
  if (!primary) return `<span class="sharp-unavailable">${sourceStatus === "manual_entry" ? "Manual entry" : "Sharp unavailable"}</span>`;
  const sourceId = `sharp-source-${++appState.sharpSourceSequence}`;
  appState.sharpSources[sourceId] = snapshot;
  const primaryAddress = String(primary.wallet_address || "").toLowerCase();
  const additional = Math.max(wallets.filter((wallet) => String(wallet.wallet_address || "").toLowerCase() !== primaryAddress).length, 0);
  const walletRows = wallets.map((wallet) => {
    const units = number(wallet.units);
    const relative = number(wallet.relative_bet_size);
    return `<span class="sharp-wallet-detail">
      <strong>${escapeHtml(wallet.display_name || wallet.wallet_address || "Unknown Sharp")}</strong>
      <code>${escapeHtml(wallet.wallet_address || "Address unavailable")}</code>
      <em>${escapeHtml(wallet.role || "Supporting Sharp")}${wallet.top_category ? ` | ${escapeHtml(wallet.top_category)} primary` : ""}${(wallet.sub_top_categories || []).length ? ` | ${escapeHtml(wallet.sub_top_categories.join(", "))} secondary` : ""}</em>
      <span><b>Amount</b>${escapeHtml(number(wallet.amount) === null ? "Unavailable" : formatMoney(wallet.amount))}</span>
      <span><b>Units</b>${escapeHtml(units === null ? "Unavailable" : formatUnits(units))}</span>
      <span><b>Average entry</b>${escapeHtml(number(wallet.average_entry) === null ? "Unavailable" : formatCents(wallet.average_entry))}</span>
      <span><b>Relative bet size</b>${escapeHtml(relative === null ? "Unavailable" : `${relative.toFixed(2)}x normal`)}</span>
    </span>`;
  }).join("");
  const contradictingRows = (snapshot.contradicting_sharps || []).map((wallet) => `<span class="sharp-wallet-detail contradicting">
    <strong>${escapeHtml(wallet.display_name || wallet.wallet_address || "Unknown Sharp")}</strong>
    <code>${escapeHtml(wallet.wallet_address || "Address unavailable")}</code>
    <em>Contradicting Sharp${wallet.top_category ? ` | ${escapeHtml(wallet.top_category)}` : ""}</em>
  </span>`).join("");
  return `<span class="sharp-cell-actions"><details class="sharp-details">
    <summary aria-label="Show all agreeing Sharps"><strong>${escapeHtml(primary.display_name || primary.wallet_address || "Unknown Sharp")}</strong>${additional ? `<small>+${additional}</small>` : ""}</summary>
    <span class="sharp-popover"><b class="sharp-popover-title">Sharp Source</b>${walletRows || '<span class="sharp-unavailable">Wallet details unavailable</span>'}${contradictingRows ? `<b class="sharp-popover-title warning">Contradicting Sharps</b>${contradictingRows}` : ""}</span>
  </details><button class="sharp-source-open" type="button" data-sharp-source-id="${sourceId}" aria-label="Open Sharp Source for ${escapeHtml(primary.display_name || primary.wallet_address || "Sharp")}" title="Open frozen Sharp Source details"><i class="ph ph-arrow-square-out" aria-hidden="true"></i></button></span>`;
}

function sharpSourceWalletMarkup(wallet, heading) {
  if (!wallet) return "";
  return `<article class="sharp-source-wallet">
    <span class="sharp-source-heading">${escapeHtml(heading)}</span>
    <strong>${escapeHtml(wallet.display_name || wallet.wallet_address || "Unknown Sharp")}</strong>
    <code>${escapeHtml(wallet.wallet_address || "Address unavailable")}</code>
    <div><span>Role</span><b>${escapeHtml(wallet.role || "Supporting Sharp")}</b></div>
    <div><span>Top Category</span><b>${escapeHtml(wallet.top_category || "Unavailable")}</b></div>
    <div><span>Sharp Position</span><b>${escapeHtml(number(wallet.amount) === null ? "Unavailable" : `${formatMoney(wallet.amount)} · ${formatUnits(wallet.units)}`)}</b></div>
    <div><span>Sharp Entry</span><b>${escapeHtml(number(wallet.average_entry) === null ? "Unavailable" : formatCents(wallet.average_entry))}</b></div>
  </article>`;
}

function openSharpSourceDialog(sourceId) {
  const snapshot = appState.sharpSources[sourceId] || {};
  const primary = snapshot.primary_sharp || null;
  const agreeing = snapshot.agreeing_sharps || [];
  const primaryAddress = String(primary?.wallet_address || "").toLowerCase();
  const additional = agreeing.filter((wallet) => String(wallet.wallet_address || "").toLowerCase() !== primaryAddress);
  const contradicting = snapshot.contradicting_sharps || [];
  const flags = [
    snapshot.is_research_only ? "Research-only" : "",
    snapshot.is_non_category_consensus ? "Sharp Non-Category" : "",
    snapshot.trade_classification && snapshot.trade_classification !== "STANDARD" ? snapshot.trade_classification.replaceAll("_", " ") : "",
  ].filter(Boolean);
  document.getElementById("sharp-source-content").innerHTML = `${flags.length ? `<div class="sharp-source-flags">${flags.map((flag) => `<span>${escapeHtml(flag)}</span>`).join("")}</div>` : ""}
    ${sharpSourceWalletMarkup(primary, primary?.role === "Research Anchor" ? "Research Anchor" : "Primary Sharp")}
    <section class="sharp-source-group"><h3>Additional Sharps</h3>${additional.length ? additional.map((wallet) => sharpSourceWalletMarkup(wallet, wallet.role || "Supporting Sharp")).join("") : '<p class="muted">No additional agreeing Sharps.</p>'}</section>
    ${contradicting.length ? `<section class="sharp-source-group warning"><h3>Contradicting Sharps</h3>${contradicting.map((wallet) => sharpSourceWalletMarkup(wallet, "Contradicting Sharp")).join("")}</section>` : ""}`;
  document.getElementById("sharp-source-dialog").showModal();
}

function closeSharpSourceDialog() {
  document.getElementById("sharp-source-dialog")?.close();
}

function trackerRow(row) {
  const snapshot = row.snapshot || {};
  const dual = row.dual_clv || {};
  const pnl = number(row.profit_loss);
  const compositeClv = number(dual.composite_probability_point_clv);
  const intended = number(snapshot.intended_entry_price ?? snapshot.current_executable_entry_price);
  const actual = number(snapshot.actual_weighted_entry_price ?? snapshot.effective_entry_price);
  const correlation = number(snapshot.correlation_multiplier);
  return `
    <tr>
      <td><strong>${escapeHtml(snapshot.event_title || snapshot.market_title)}</strong><small>${escapeHtml(snapshot.market_title)} · ${formatDateTime(snapshot.event_start_time)}</small></td>
      <td data-label="Selection"><strong>${escapeHtml(snapshot.recommended_side)}</strong><small>Sharp avg ${formatCents(snapshot.sharp_average_entry_price)}</small></td>
      <td data-label="Book"><strong>${escapeHtml(snapshot.sportsbook || snapshot.entry_price_source || "Polymarket")}</strong><small>${escapeHtml(snapshot.provider_display_odds || formatCents(snapshot.provider_entry_price ?? intended))}</small></td>
      <td data-label="Grade / Score"><strong>${escapeHtml(snapshot.trade_grade || "Unavailable")}</strong><small>${snapshot.trade_quality_score ?? snapshot.confidence_score ?? "n/a"} score</small></td>
      <td data-label="Sharp">${sharpCell(row.sharp_snapshot || snapshot.sharp_snapshot || {})}</td>
      <td data-label="Entry"><strong>${intended === null ? "Unavailable" : formatCents(intended)}</strong><small>Actual ${actual === null ? "Unavailable" : formatCents(actual)}</small></td>
      <td data-label="Fair / Edge"><strong>${number(snapshot.composite_fair_probability) === null ? "Unavailable" : formatPercent(snapshot.composite_fair_probability)}</strong><small>Edge ${number(snapshot.calculated_edge) === null ? "Unavailable" : formatPercent(snapshot.calculated_edge)}</small></td>
      <td data-label="Liquidity / Execution"><strong>${escapeHtml(snapshot.liquidity_grade || "Unavailable")}</strong><small>${escapeHtml(String(snapshot.execution_method || "Unavailable").replaceAll("_", " "))}</small></td>
      <td data-label="Max / Correlation"><strong>${number(snapshot.maximum_average_price) === null ? "Unavailable" : formatCents(snapshot.maximum_average_price)}</strong><small>${correlation === null ? "Correlation unavailable" : `${correlation.toFixed(2)}x correlation`}</small></td>
      <td><strong>${formatMoney(row.recommended_amount)}</strong><small>${formatPercent(snapshot.final_recommended_fraction)} · ${formatUnits(row.recommended_units)}</small></td>
      <td data-label="Decision"><span class="status-label ${escapeHtml(row.status)}">${escapeHtml(snapshot.decision_class || "PLAYED")}</span><small>${escapeHtml(snapshot.decision_reason || row.status)}</small></td>
      <td data-label="P&amp;L" class="mono ${pnl === null ? "" : pnl >= 0 ? "positive" : "negative"}">${pnl === null ? "Open" : formatMoney(pnl)}</td>
      <td data-label="Exchange CLV">${clvCell(row)}</td>
      <td data-label="Composite CLV"><strong>${compositeClv === null ? "Unavailable" : formatPercent(compositeClv)}</strong><small>${escapeHtml(String(dual.composite_clv_status || "UNAVAILABLE").replaceAll("_", " "))}</small></td>
      <td data-label="Execution Loss" class="mono">${number(dual.execution_loss) === null ? "Unavailable" : formatMoney(dual.execution_loss)}</td>
      <td data-label="Bankroll" class="mono">${formatMoney(row.running_bankroll)}</td>
    </tr>
  `;
}

function drawTrackerChart(graph) {
  const points = (graph || []).map((point, index) => ({ timestamp: point.timestamp || index, value: Number(point.bankroll) })).filter((point) => Number.isFinite(point.value));
  drawLineChart(document.getElementById("tracker-chart"), points, { format: (value) => formatCompactMoney(value) });
}

function renderClvAnalytics(payload = {}) {
  const analytics = payload.clv || {};
  const periods = analytics.periods || {};
  const all = periods.all || {};
  const cards = [
    ["Stake-weighted CLV", formatClvPercent(all.stake_weighted_clv_pct), "Original stake weighted"],
    ["Average CLV", formatClvPercent(all.average_clv_pct), "Simple average"],
    ["Median CLV", formatClvPercent(all.median_clv_pct), "Measured bets"],
    ["Positive CLV Rate", all.positive_clv_rate === null || all.positive_clv_rate === undefined ? "Unavailable" : formatPercent(all.positive_clv_rate), `${all.positive_clv_count || 0} positive`],
    ["Bets Measured", String(all.bets_measured || 0), formatMoney(all.total_stake_represented || 0)],
    ["CLV Unavailable", String(all.missing_clv_count || 0), "Excluded from CLV averages"],
  ];
  const metrics = document.getElementById("tracker-metrics");
  metrics.insertAdjacentHTML("beforeend", cards.map(([label, value, note]) => metricCard(label, value, note, "ph-crosshair")).join(""));
  document.getElementById("clv-period-strip").innerHTML = [
    ["Today", periods.today], ["Past 7 Days", periods["7d"]], ["This Week", periods.week],
    ["This Month", periods.month], ["This Year", periods.year], ["All Time", periods.all],
  ].map(([label, value]) => `<span><small>${escapeHtml(label)}</small><strong class="${number(value?.stake_weighted_clv_pct) > 0 ? "positive" : number(value?.stake_weighted_clv_pct) < 0 ? "negative" : ""}">${escapeHtml(formatClvPercent(value?.stake_weighted_clv_pct))}</strong><em>${value?.bets_measured || 0} bets | ${escapeHtml(formatMoney(value?.total_stake_represented || 0))}</em></span>`).join("");
  const trend = (analytics.trend || []).map((point) => ({ timestamp: point.date, value: Number(point.stake_weighted_clv_pct) })).filter((point) => Number.isFinite(point.value));
  if (trend.length) drawLineChart(document.getElementById("clv-chart"), trend, { format: (value) => formatClvPercent(value) });
  else document.getElementById("clv-chart").innerHTML = emptyState("CLV capture is pending", "Reliable provider-specific pregame closes will appear here after monitored events begin.");
}

function renderTrackerState(tracking = {}) {
  const badge = document.getElementById("tracker-job-state");
  if (!badge) return;
  const state = tracking.status || "stale";
  const labels = { running: "Tracking: Active", paused: "Tracking: Paused", failed: "Tracking: Failed", stale: "Tracking: Stale" };
  badge.textContent = labels[state] || "Tracking: Stale";
  badge.className = `status-label ${state === "running" ? "ready" : state}`;
}

async function loadTrackerAdvancedAnalytics() {
  try {
    const payload = await fetchJson("/api/tracker/advanced-analytics");
    const data = payload.data || {};
    const dimension = document.getElementById("tracker-analytics-dimension")?.value || "sport";
    const rows = (data.segments || []).filter((row) => row.dimension === dimension);
    const counts = data.played_vs_passed || {};
    document.getElementById("tracker-analytics-summary").innerHTML = [["Played", counts.played || 0], ["Passed", counts.passed || 0], ["Research only", counts.research_only || 0]].map(([label, value]) => `<span><small>${label}</small><strong>${value}</strong></span>`).join("");
    document.getElementById("tracker-analytics-body").innerHTML = rows.length ? rows.map((row) => `<tr><td><strong>${escapeHtml(row.segment_value)}</strong></td><td>${escapeHtml(row.status.replaceAll("_", " "))}</td><td>${row.candidate_count}</td><td>${row.played_count}</td><td>${row.passed_count}</td><td>${row.settled_count}</td><td>${edgeMetric(row.roi)}</td><td>${edgeMetric(row.stake_weighted_composite_clv)}</td><td>${formatMoney(row.execution_loss || 0)}</td></tr>`).join("") : `<tr><td colspan="9">${emptyState("No segment observations", "Candidate Ledger records will appear here without fabricated metrics.")}</td></tr>`;
  } catch (error) {
    document.getElementById("tracker-analytics-body").innerHTML = `<tr><td colspan="9">${errorState(error.message)}</td></tr>`;
  }
}

function renderTrackerDiagnostics(diagnostics = {}) {
  appState.trackerDiagnostics = diagnostics;
  renderTrackerState(diagnostics);
  const panel = document.getElementById("tracker-diagnostics");
  if (!panel) return;
  panel.hidden = appState.trackerView !== "model";
  const clv = diagnostics.clv || {};
  document.getElementById("tracker-diagnostic-grid").innerHTML = [
    metricCard("Last successful run", formatDateTime(diagnostics.last_successful_run, "Never"), "Most recent completed backend job", "ph-check-circle"),
    metricCard("Evaluated", String(diagnostics.recommendations_evaluated || 0), "Today recommendations checked", "ph-magnifying-glass"),
    metricCard("Inserted", String(diagnostics.records_inserted || 0), "New immutable snapshots", "ph-database"),
    metricCard("Duplicates", String(diagnostics.records_skipped_duplicates || 0), "Existing canonical records", "ph-copy"),
    metricCard("Rejected", String(diagnostics.records_rejected || 0), "Explicit eligibility failures", "ph-funnel-x"),
    metricCard("Errors", String(diagnostics.errors || 0), `Next run ${formatDateTime(diagnostics.next_scheduled_run, "Paused")}`, "ph-warning-circle"),
    metricCard("CLV markets monitored", String(clv.markets_currently_monitored || 0), `${(clv.next_expected_event_starts || []).length} upcoming starts`, "ph-radar"),
    metricCard("Last CLV quote", formatDateTime(clv.last_snapshot_time, "None yet"), "Persistent provider snapshot", "ph-clock-counter-clockwise"),
    metricCard("Closing lines captured", String(clv.closing_snapshots_captured || 0), `Version ${clv.calculation_version || "clv-v1"}`, "ph-crosshair"),
    metricCard("Stale CLV quotes", String(clv.stale_quotes || 0), `${clv.freshness_threshold_seconds || 300}s freshness threshold`, "ph-hourglass"),
    metricCard("CLV mapping errors", String(clv.missing_provider_mappings || 0), "No cross-provider substitution", "ph-link-break"),
    metricCard("Failed CLV captures", String(clv.failed_captures || 0), `Last job ${formatDateTime(clv.last_successful_clv_job_run, "Never")}`, "ph-warning"),
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
  const tags = Array.isArray(row.tags) ? row.tags : [];
  const metadata = `<span class="personal-bet-metadata"><span class="personal-book-badge"><i class="ph ph-buildings" aria-hidden="true"></i>${escapeHtml(row.sportsbook || "Polymarket")}</span>${tags.map((tag) => `<span class="personal-tag-badge">#${escapeHtml(tag)}</span>`).join("")}</span>`;
  const eventCopy = `<strong>${escapeHtml(row.event_title || "Unknown event")}</strong><small>${escapeHtml(row.market_title || "Market")} | ${escapeHtml(formatDateTime(row.event_start_time))}</small>${metadata}`;
  const eventMarkup = row.market_url
    ? `<a class="personal-market-link" href="${escapeHtml(row.market_url)}" target="_blank" rel="noopener noreferrer">${eventCopy}</a>`
    : eventCopy;
  return `
    <tr>
      <td data-label="Event / Market">${eventMarkup}</td>
      <td data-label="Selection"><strong>${escapeHtml(row.selection || "Selection")}</strong></td>
      <td data-label="Sharp">${sharpCell(row.sharp_snapshot || {})}</td>
      <td data-label="Shares" class="mono">${escapeHtml(formatShares(row.shares))}</td>
      <td data-label="Entry" class="mono">${escapeHtml(formatCents(row.entry_price))}</td>
      <td data-label="Position Cost" class="mono">${escapeHtml(formatMoney(row.position_cost))}</td>
      <td data-label="Fees" class="mono">${escapeHtml(formatMoney(row.fees))}</td>
      <td data-label="Status"><span class="status-label ${escapeHtml(status)}">${escapeHtml(status)}</span></td>
      <td data-label="P&amp;L" class="mono ${pnl === null ? "" : pnl >= 0 ? "positive" : "negative"}">${pnl === null ? "Open" : escapeHtml(formatMoney(pnl))}</td>
      <td data-label="Entry CLV">${clvCell(row)}</td>
      <td data-label="Tracked">${escapeHtml(formatDateTime(row.created_at))}</td>
      <td data-label="Action">${active ? `<button class="personal-fill-remove personal-tracker-remove" type="button" data-personal-fill-remove="${escapeHtml(row.fill_id)}" aria-label="Remove ${escapeHtml(row.selection || "personal trade")}" title="Remove this open personal trade"><i class="ph ph-trash" aria-hidden="true"></i></button>` : '<span class="muted">Settled</span>'}</td>
    </tr>
  `;
}

function renderPersonalTrackerFilters(options = {}) {
  const tag = document.getElementById("tracker-tag");
  const selectedTag = tag.value;
  renderTrackerBookFilter(options.sportsbooks || []);
  setSelectOptions(tag, options.tags || [], selectedTag, "All tags");
  renderSharpTrackerFilter(options);
}

function renderTrackerBookFilter(books = []) {
  const view = appState.trackerView || "model";
  const normalized = [...new Set((books || []).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  appState.trackerBookOptions[view] = normalized;
  const selected = appState.trackerSelectedBooks[view] || [];
  document.getElementById("tracker-book-filter-options").innerHTML = normalized.length
    ? normalized.map((book) => `<label><input type="checkbox" value="${escapeHtml(book)}" ${selected.includes(book) ? "checked" : ""}><span>${escapeHtml(book)}</span></label>`).join("")
    : '<span class="muted">No tracked books yet</span>';
  const label = document.getElementById("tracker-book-filter-label");
  label.textContent = selected.length === 0
    ? "All books"
    : selected.length === 1
      ? selected[0]
      : `${selected.length} books`;
}

function renderTrackerBookSummaries(summaries = []) {
  const container = document.getElementById("tracker-book-summary");
  if (appState.trackerView !== "model" || !summaries.length) {
    container.hidden = true;
    container.innerHTML = "";
    return;
  }
  container.hidden = false;
  container.innerHTML = summaries.map((summary) => {
    const pnl = number(summary.realized_profit_loss) || 0;
    return `<article><span>${escapeHtml(summary.sportsbook)}</span><strong class="${pnlTone(pnl)}">${escapeHtml(signedMoney(pnl))}</strong><small>${summary.wins || 0}-${summary.losses || 0} · ${summary.total_tracked_bets || 0} bets</small></article>`;
  }).join("");
}

function renderSharpTrackerFilter(options = {}) {
  const select = document.getElementById("tracker-sharp-wallet");
  const selected = select.value;
  setSelectOptions(select, options.sharps || [], selected, "All Sharps");
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
  appState.sharpSources = {};
  appState.sharpSourceSequence = 0;
  renderSharpTrackerFilter(payload.filter_options || {});
  renderTrackerBookFilter(payload.filter_options?.sportsbooks || []);
  renderTrackerBookSummaries(payload.sportsbook_summaries || []);
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
  renderClvAnalytics(payload);
  const body = document.getElementById("tracker-body");
  body.innerHTML = payload.data.length ? payload.data.map(trackerRow).join("") : `<tr><td colspan="15">${trackerEmptyState()}</td></tr>`;
  drawTrackerChart(payload.graph);
  renderTrackerPagination(payload.pagination, "model");
  loadTrackerAdvancedAnalytics();
}

function renderPersonalTracker(payload) {
  if (appState.trackerView !== "personal") return;
  const summary = payload.summary || {};
  appState.personalTrackerBankroll = payload.bankroll?.personal_tracker_bankroll ?? summary.starting_bankroll;
  appState.sharpSources = {};
  appState.sharpSourceSequence = 0;
  renderPersonalTrackerFilters(payload.filter_options || {});
  renderTrackerBookSummaries([]);
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
  renderClvAnalytics(payload);
  const body = document.getElementById("tracker-body");
  body.innerHTML = payload.data.length
    ? payload.data.map(personalTrackerRow).join("")
    : `<tr><td colspan="12"><div class="empty-state"><i class="ph ph-user-plus" aria-hidden="true"></i><h2>No personal trades match</h2><p>Use the Track button on a Trades to Play card to add a confirmed purchase.</p><a class="button primary compact" href="/trades"><i class="ph ph-plus" aria-hidden="true"></i>Browse Trades to Play</a></div></td></tr>`;
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
    clv_status: document.getElementById("tracker-clv-status").value,
    min_clv: document.getElementById("tracker-clv-min").value,
    max_clv: document.getElementById("tracker-clv-max").value,
    clv_sort: document.getElementById("tracker-clv-sort").value,
    sharp: document.getElementById("tracker-sharp-wallet").value,
    grade: document.getElementById("tracker-grade").value,
    liquidity_grade: document.getElementById("tracker-liquidity-grade").value,
    execution_method: document.getElementById("tracker-execution-method").value,
    tracker_range: document.getElementById("tracker-date-range").value,
    tracker_start: document.getElementById("tracker-custom-start").value,
    tracker_end: document.getElementById("tracker-custom-end").value,
  };
  const selectedBooks = appState.trackerSelectedBooks[view] || [];
  if (selectedBooks.length) params.sportsbook = selectedBooks.join(",");
  if (view === "model") params.min_sharps = document.getElementById("tracker-sharps").value;
  if (view === "personal") {
    params.tag = document.getElementById("tracker-tag").value;
  }
  return new URLSearchParams(params);
}

async function loadTracker() {
  try {
    const payload = await fetchJson(`/api/model-tracker?${trackerRequestParams("model").toString()}`);
    appState.trackerCache.model = payload;
    renderModelTracker(payload);
    if (appState.trackerView === "model" && !document.getElementById("tracker-diagnostics")?.hidden) loadTrackerDiagnostics();
  } catch (error) {
    if (appState.trackerView === "model") document.getElementById("tracker-body").innerHTML = `<tr><td colspan="12">${errorState(error.message)}<button class="button compact tracker-retry" type="button">Retry Model Tracker</button></td></tr>`;
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
    if (appState.trackerView === "personal") document.getElementById("tracker-body").innerHTML = `<tr><td colspan="12">${errorState(error.message)}<button class="button compact tracker-retry" type="button">Retry Personal Tracker</button></td></tr>`;
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
  document.getElementById("personal-manual-action").hidden = model;
  document.getElementById("personal-track-action").hidden = model;
  document.getElementById("tracker-job-state").hidden = !model;
  document.getElementById("tracker-sharps").hidden = !model;
  document.getElementById("tracker-tag").hidden = model;
  document.querySelectorAll(".model-tracker-filter").forEach((element) => { element.hidden = !model; });
  document.querySelector('#tracker-status option[value="canceled"]').hidden = model;
  document.querySelector('#tracker-result option[value="canceled"]').hidden = model;
  if (model && document.getElementById("tracker-status").value === "canceled") document.getElementById("tracker-status").value = "";
  if (model && document.getElementById("tracker-result").value === "canceled") document.getElementById("tracker-result").value = "";
  document.getElementById("tracker-search").placeholder = model ? "Search event, market, Sharp" : "Search event, selection, Sharp";
  document.getElementById("tracker-table-head").innerHTML = model
    ? "<th>Event / Market</th><th>Selection</th><th>Book</th><th>Grade / Score</th><th>Sharp</th><th>Intended / Actual</th><th>Composite Fair / Edge</th><th>Liquidity / Execution</th><th>Max Avg / Correlation</th><th>Bet</th><th>Decision</th><th>P&amp;L</th><th>Exchange CLV</th><th>Composite CLV</th><th>Execution Loss</th><th>Bankroll</th>"
    : "<th>Event / Market</th><th>Selection</th><th>Sharp</th><th>Shares</th><th>Entry</th><th>Position Cost</th><th>Fees</th><th>Status</th><th>P&amp;L</th><th>Entry CLV</th><th>Tracked</th><th>Action</th>";
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
    document.getElementById("tracker-body").innerHTML = '<tr><td colspan="12"><div class="tracker-loading-state"><span></span><span></span><span></span></div></td></tr>';
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

function openPersonalManualDialog() {
  const dialog = document.getElementById("personal-manual-dialog");
  document.getElementById("personal-manual-error").textContent = "";
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  document.getElementById("personal-manual-event").focus();
}

function closePersonalManualDialog() {
  const dialog = document.getElementById("personal-manual-dialog");
  document.getElementById("personal-manual-form")?.reset();
  document.getElementById("personal-manual-fees").value = "0";
  document.getElementById("personal-manual-sportsbook").value = "Polymarket";
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
}

async function saveManualPersonalBet(event) {
  event.preventDefault();
  const form = document.getElementById("personal-manual-form");
  const submit = form.querySelector('button[type="submit"]');
  const error = document.getElementById("personal-manual-error");
  submit.disabled = true;
  error.textContent = "";
  try {
    await fetchJson("/api/personal-bets/manual", {
      method: "POST",
      body: JSON.stringify({
        event_title: document.getElementById("personal-manual-event").value,
        market_title: document.getElementById("personal-manual-market").value,
        selection: document.getElementById("personal-manual-selection").value,
        entry_price: Number(document.getElementById("personal-manual-entry").value) / 100,
        stake: Number(document.getElementById("personal-manual-stake").value),
        fees: Number(document.getElementById("personal-manual-fees").value || 0),
        status: document.getElementById("personal-manual-status").value,
        sportsbook: document.getElementById("personal-manual-sportsbook").value,
        tags: document.getElementById("personal-manual-tags").value.split(",").map((tag) => tag.trim()).filter(Boolean),
        market_url: document.getElementById("personal-manual-url").value,
        canonical_event_id: document.getElementById("personal-manual-event-id").value,
        canonical_market_id: document.getElementById("personal-manual-market-id").value,
        canonical_outcome_id: document.getElementById("personal-manual-outcome-id").value,
        event_slug: document.getElementById("personal-manual-event-slug").value,
        market_slug: document.getElementById("personal-manual-market-slug").value,
        event_start_time: document.getElementById("personal-manual-start").value,
      }),
    });
    closePersonalManualDialog();
    appState.trackerCache.personal = null;
    await loadPersonalTracker();
    showToast("Manual personal bet saved", "success");
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
  document.getElementById("tracker-analytics-dimension")?.addEventListener("change", loadTrackerAdvancedAnalytics);
  document.getElementById("tracker-search").addEventListener("input", debounce(() => { appState.trackerPage[appState.trackerView] = 1; loadTrackerView(); }));
  ["tracker-status", "tracker-sharps", "tracker-sharp-wallet", "tracker-grade", "tracker-liquidity-grade", "tracker-execution-method", "tracker-result", "tracker-tag", "tracker-clv-status", "tracker-clv-sort"].forEach((id) => document.getElementById(id).addEventListener("change", () => { appState.trackerPage[appState.trackerView] = 1; loadTrackerView(); }));
  document.querySelectorAll("[data-tracker-books]").forEach((button) => button.addEventListener("click", () => {
    const checked = button.dataset.trackerBooks === "all";
    document.querySelectorAll("#tracker-book-filter-options input").forEach((input) => { input.checked = checked; });
  }));
  document.getElementById("tracker-book-filter-apply").addEventListener("click", () => {
    appState.trackerSelectedBooks[appState.trackerView] = [...document.querySelectorAll("#tracker-book-filter-options input:checked")].map((input) => input.value);
    document.getElementById("tracker-book-filter").removeAttribute("open");
    renderTrackerBookFilter(appState.trackerBookOptions[appState.trackerView]);
    appState.trackerPage[appState.trackerView] = 1;
    loadTrackerView();
  });
  document.getElementById("tracker-date-range").addEventListener("change", event => {
    const custom = event.target.value === "custom";
    document.getElementById("tracker-custom-start-wrap").hidden = !custom;
    document.getElementById("tracker-custom-end-wrap").hidden = !custom;
    appState.trackerPage[appState.trackerView] = 1;
    if (!custom || (document.getElementById("tracker-custom-start").value && document.getElementById("tracker-custom-end").value)) loadTrackerView();
  });
  ["tracker-custom-start", "tracker-custom-end"].forEach(id => document.getElementById(id).addEventListener("change", () => {
    if (document.getElementById("tracker-custom-start").value && document.getElementById("tracker-custom-end").value) {
      appState.trackerPage[appState.trackerView] = 1;
      loadTrackerView();
    }
  }));
  ["tracker-clv-min", "tracker-clv-max"].forEach((id) => document.getElementById(id).addEventListener("input", debounce(() => { appState.trackerPage[appState.trackerView] = 1; loadTrackerView(); })));
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
    const sourceButton = event.target.closest("[data-sharp-source-id]");
    if (sourceButton) openSharpSourceDialog(sourceButton.dataset.sharpSourceId);
  });
  document.getElementById("sharp-source-close")?.addEventListener("click", closeSharpSourceDialog);
  document.getElementById("sharp-source-dialog")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeSharpSourceDialog();
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
  document.getElementById("personal-manual-action")?.addEventListener("click", openPersonalManualDialog);
  document.getElementById("personal-manual-form")?.addEventListener("submit", saveManualPersonalBet);
  document.getElementById("personal-manual-close")?.addEventListener("click", closePersonalManualDialog);
  document.getElementById("personal-manual-dismiss")?.addEventListener("click", closePersonalManualDialog);
  document.getElementById("personal-manual-dialog")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closePersonalManualDialog();
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
  const links = document.getElementById("primary-links");
  const closeMobileNavigation = () => {
    links?.classList.remove("open");
    document.body.classList.remove("mobile-nav-open");
    toggle?.setAttribute("aria-expanded", "false");
  };
  toggle?.addEventListener("click", () => {
    const isOpen = !links?.classList.contains("open");
    links?.classList.toggle("open", isOpen);
    document.body.classList.toggle("mobile-nav-open", isOpen);
    toggle.setAttribute("aria-expanded", String(isOpen));
  });
  links?.querySelectorAll("a").forEach((link) => link.addEventListener("click", closeMobileNavigation));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMobileNavigation();
  });
  window.addEventListener("resize", () => {
    if (window.innerWidth > 900) closeMobileNavigation();
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

function executionViolationWarnings(trade) {
  const recommendation = trade.recommendation || {};
  const plan = recommendation.execution_plan || trade.execution_plan || {};
  const risk = recommendation.portfolio_risk || {};
  const warnings = [];
  const effective = number(plan.effective_price_for_executable_amount ?? recommendation.current_user_entry_price);
  const maximum = number(plan.maximum_average_price);
  if (effective !== null && maximum !== null && effective > maximum) warnings.push("ABOVE_MAXIMUM_PRICE");
  if ((number(recommendation.price_slippage_fraction) || 0) > 0.05) warnings.push("ABOVE_FIVE_PERCENT_SLIPPAGE");
  const riskReasons = risk.reason_codes || [];
  if (riskReasons.some((reason) => String(reason).includes("CORRELATION") || String(reason).includes("PORTFOLIO_RISK_CAP"))) warnings.push("CORRELATION_CAP_EXCEEDED");
  if (riskReasons.some((reason) => String(reason).includes("DAILY_EXPOSURE"))) warnings.push("DAILY_EXPOSURE_CAP_EXCEEDED");
  if ((trade.reason_codes || []).some((reason) => String(reason).includes("OPPOSING_SPECIALIST")) || trade.hasContradictingSharps) warnings.push("STRONG_OPPOSING_SPECIALIST");
  if ((trade.reason_codes || []).some((reason) => String(reason).includes("MAPPING_UNCERTAIN"))) warnings.push("MAPPING_UNCERTAINTY");
  if (String(trade.fair_price?.status || recommendation.fair_price_status || "").toUpperCase() !== "AVAILABLE") warnings.push("NO_FAIR_PRICE_CONFIRMATION");
  if ((number(trade.liquidity_quality?.score) ?? 100) < 40) warnings.push("POOR_LIQUIDITY");
  if (String(risk.risk_state?.state || "").toUpperCase() === "STRATEGY_STOP") warnings.push("STRATEGY_STOP_ACTIVE");
  return [...new Set(warnings)];
}

function confirmExecutionViolations(link, trade) {
  const warnings = executionViolationWarnings(trade);
  if (!warnings.length) return true;
  const message = `This action proceeds despite: ${warnings.map((warning) => warning.replaceAll("_", " ")).join(", ")}. Confirm that you understand these warnings.`;
  if (!window.confirm(message)) return false;
  warnings.forEach((warning) => {
    fetchJson("/api/rule-violations", {method:"POST", body:JSON.stringify({trade_id:String(trade.id), candidate_id:trade.candidate_id || null, warning_code:warning, confirmed_action:`OPEN_${link.hostname || "EXECUTION_VENUE"}`, confirmed:true, confirmation_text:message, entry_price:number(trade.recommendation?.current_user_entry_price), outcome:trade.outcome, context:{execution_method:trade.recommendation?.execution_plan?.recommended_execution_method || null}})}).catch((error) => showToast(`Warning audit failed: ${error.message}`, "error"));
  });
  return true;
}

function edgeMetric(value, style = "percent") {
  const parsed = number(value);
  if (parsed === null) return '<span class="metric-unavailable">Unavailable</span>';
  if (style === "count") return String(Math.round(parsed));
  return `${parsed >= 0 ? "+" : ""}${(parsed * 100).toFixed(2)}%`;
}

function renderEdgeMap(payload) {
  const run = payload.run || {};
  const rows = payload.segments || [];
  document.getElementById("edge-map-run-time").textContent = run.created_at ? formatDateTime(run.created_at) : "Live preview";
  document.getElementById("edge-map-candidate-count").textContent = `${run.candidate_count || 0} candidates`;
  const counts = rows.reduce((result, row) => ({ ...result, [row.status]: (result[row.status] || 0) + 1 }), {});
  document.getElementById("edge-map-validated").textContent = counts.VALIDATED || 0;
  document.getElementById("edge-map-promising").textContent = counts.PROMISING || 0;
  document.getElementById("edge-map-discovery").textContent = counts.DISCOVERY || 0;
  document.getElementById("edge-map-insufficient").textContent = counts.INSUFFICIENT_SAMPLE || 0;
  const body = document.getElementById("edge-map-body");
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="9" class="edge-map-empty"><strong>No measured segments yet</strong><span>Candidate Ledger observations will appear here without fabricated CLV.</span></td></tr>';
    return;
  }
  body.innerHTML = rows.map((row) => `<tr>
    <td><strong>${escapeHtml(row.segment_value)}</strong><span>${escapeHtml(row.dimension.replaceAll("_", " "))}</span></td>
    <td><span class="edge-status" data-status="${escapeHtml(row.status)}">${escapeHtml(row.status.replaceAll("_", " "))}</span></td>
    <td>${row.candidate_count}</td><td>${row.played_count} / ${row.passed_count}</td><td>${row.settled_count}</td>
    <td>${edgeMetric(row.roi)}</td><td>${edgeMetric(row.stake_weighted_exchange_clv)}</td><td>${edgeMetric(row.stake_weighted_composite_clv)}</td>
    <td><div class="reliability-meter"><span style="width:${Math.max(0, Math.min(100, Number(row.statistical_reliability || 0) * 100))}%"></span></div><small>${(Number(row.statistical_reliability || 0) * 100).toFixed(0)}%</small></td>
  </tr>`).join("");
}

async function loadEdgeMap() {
  const dimension = document.getElementById("edge-map-dimension")?.value || "";
  try {
    const payload = await fetchJson(`/api/edge-map${dimension ? `?dimension=${encodeURIComponent(dimension)}` : ""}`);
    renderEdgeMap(payload.data);
  } catch (error) {
    document.getElementById("edge-map-body").innerHTML = `<tr><td colspan="9" class="edge-map-empty"><strong>Edge Map unavailable</strong><span>${escapeHtml(error.message)}</span></td></tr>`;
  }
}

function bindEdgeMap() {
  document.getElementById("edge-map-dimension")?.addEventListener("change", loadEdgeMap);
  loadEdgeMap();
}

function intelCandidateRow(row) {
  const reasons = row.reason_codes || [];
  return `<article class="intel-row"><span><strong>${escapeHtml(row.event_title || row.market_title || "Candidate")}</strong><small>${escapeHtml(row.market_title || "Market")} · ${escapeHtml(row.selection || "Selection unavailable")}</small></span><span><b>${escapeHtml(row.current_decision)}</b><small>${escapeHtml(reasons.join(", ") || "No rejection reason")}</small></span><span><small>${escapeHtml(formatDateTime(row.last_seen_at))}</small><button class="button ghost compact" data-intel-trace="${escapeHtml(row.candidate_id)}">Explain</button></span></article>`;
}

function intelProposalRow(row) {
  const multiplier = number(row.proposed_config?.stake_multiplier);
  return `<article class="intel-row"><span><strong>${escapeHtml(row.segment_value)}</strong><small>${escapeHtml(row.segment_dimension.replaceAll("_", " "))} · ${escapeHtml(row.proposal_type)}</small></span><span><b>${escapeHtml(row.status)}</b><small>${multiplier === null ? "No stake multiplier" : `${(multiplier * 100).toFixed(0)}% stake multiplier`}</small></span><span><small>${escapeHtml(formatDateTime(row.updated_at))}</small>${row.status === "APPROVED" ? `<button class="button primary compact" data-intel-apply="${escapeHtml(row.proposal_id)}">Apply safely</button>` : ""}</span></article>`;
}

function intelViolationRow(row) {
  return `<article class="intel-row"><span><strong>${escapeHtml(row.warning_code.replaceAll("_", " "))}</strong><small>${escapeHtml(row.trade_id)} · ${escapeHtml(row.confirmed_action)}</small></span><span><b>${row.profit_loss === null ? "Unsettled" : formatMoney(row.profit_loss)}</b><small>Composite CLV ${escapeHtml(formatClvPercent(row.composite_clv))}</small></span><span><small>${escapeHtml(formatDateTime(row.created_at))}</small></span></article>`;
}

function renderIntelligence() {
  const data = appState.intelligence;
  const counts = data.diagnostics?.measurement?.candidate_counts || {};
  document.getElementById("intel-summary").innerHTML = [
    ["Candidates", Object.values(counts).reduce((sum,value)=>sum+Number(value||0),0)],
    ["Passed", counts.PASSED || 0], ["Research only", counts.RESEARCH_ONLY || 0],
    ["Active policies", data.diagnostics?.active_policies?.length || 0],
    ["Violations", data.violations.length], ["Proposals", data.proposals.length],
  ].map(([label,value])=>`<article><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>`).join("");
  const decision = document.getElementById("intel-candidate-filter").value;
  const candidates = decision ? data.candidates.filter(row=>row.current_decision===decision) : data.candidates;
  document.getElementById("intel-candidates").innerHTML = candidates.length ? candidates.map(intelCandidateRow).join("") : emptyState("No candidates match", "Change the decision filter.");
  document.getElementById("intel-proposals").innerHTML = data.proposals.length ? data.proposals.map(intelProposalRow).join("") : emptyState("No configuration proposals", "Edge Map evidence can support a versioned proposal.");
  document.getElementById("intel-violations").innerHTML = data.violations.length ? data.violations.map(intelViolationRow).join("") : emptyState("No confirmed rule violations", "Warnings remain enforced and auditable.");
  document.getElementById("intel-diagnostics").textContent = JSON.stringify(data.diagnostics, null, 2);
}

async function loadIntelligence() {
  const [candidates, proposals, violations, diagnostics] = await Promise.all([
    fetchJson("/api/admin/candidate-ledger?limit=500"), fetchJson("/api/admin/configuration-proposals"),
    fetchJson("/api/admin/rule-violations"), fetchJson("/api/admin/completion/diagnostics"),
  ]);
  appState.intelligence = {candidates:candidates.data||[], proposals:proposals.data||[], violations:violations.data||[], diagnostics:diagnostics.data||{}};
  document.getElementById("intel-login").hidden = true;
  document.getElementById("intel-workspace").hidden = false;
  document.getElementById("intel-access-state").textContent = "Authorized";
  renderIntelligence();
}

async function openIntelTrace(candidateId) {
  const payload = await fetchJson(`/api/admin/explainability/${encodeURIComponent(candidateId)}`);
  document.getElementById("intel-trace").innerHTML = payload.data.stages.map((row,index)=>`<article class="trace-stage"><span>${index+1}</span><div><strong>${escapeHtml(row.stage.replaceAll("_", " "))}</strong><small>${escapeHtml(row.status)}</small><pre>${escapeHtml(JSON.stringify(row.data, null, 2))}</pre></div></article>`).join("");
  document.getElementById("intel-trace-dialog").showModal();
}

function bindIntelligence() {
  document.getElementById("intel-login-form")?.addEventListener("submit", async(event)=>{event.preventDefault();try{await fetchJson("/api/admin/login",{method:"POST",body:JSON.stringify({password:document.getElementById("intel-password").value})});await loadIntelligence();}catch(error){document.getElementById("intel-login-error").textContent=error.message;}});
  document.getElementById("intel-candidate-filter")?.addEventListener("change",renderIntelligence);
  document.querySelectorAll("[data-intel-tab]").forEach(button=>button.addEventListener("click",()=>{document.querySelectorAll("[data-intel-tab]").forEach(item=>item.classList.toggle("active",item===button));document.querySelectorAll("[data-intel-panel]").forEach(panel=>panel.hidden=panel.dataset.intelPanel!==button.dataset.intelTab);}));
  document.getElementById("intel-workspace")?.addEventListener("click",async(event)=>{const trace=event.target.closest("[data-intel-trace]");if(trace)await openIntelTrace(trace.dataset.intelTrace);const apply=event.target.closest("[data-intel-apply]");if(apply){try{await fetchJson(`/api/admin/configuration-proposals/${encodeURIComponent(apply.dataset.intelApply)}/apply`,{method:"POST"});showToast("Risk-reducing segment policy activated","success");await loadIntelligence();}catch(error){showToast(error.message,"error");}}});
  document.getElementById("intel-trace-close")?.addEventListener("click",()=>document.getElementById("intel-trace-dialog").close());
  loadIntelligence().catch(()=>{});
}

const ODDS_BASE_PROVIDER_CATALOG = {
  polymarket: {key:"polymarket", name:"Polymarket", logoUrl:"https://polymarket.com/icons/favicon-32x32.png", source:"exchange"},
  kalshi: {key:"kalshi", name:"Kalshi", logoUrl:"/static/assets/providers/kalshi.png", source:"exchange"},
  "4cx": {key:"4cx", name:"4CX", logoUrl:"/static/assets/providers/4cx.png", source:"exchange"},
};
const ODDS_PROVIDER_KEYS = Object.keys(ODDS_BASE_PROVIDER_CATALOG);
const ODDS_PROVIDER_ORDER_KEY = "iconbets_odds_provider_order";
const ODDS_PROVIDER_SELECTION_KEY = "iconbets_odds_provider_selection";

function savedOddsProviderOrder() {
  try {
    const saved = JSON.parse(localStorage.getItem(ODDS_PROVIDER_ORDER_KEY) || "[]");
    const valid = Array.isArray(saved) ? saved.filter((key, index) => typeof key === "string" && /^[a-z0-9_]+$/.test(key) && saved.indexOf(key) === index) : [];
    return [...valid, ...ODDS_PROVIDER_KEYS.filter(key => !valid.includes(key)), ...(valid.includes("best") ? [] : ["best"])];
  } catch (_) {
    return [...ODDS_PROVIDER_KEYS, "best"];
  }
}

const initialOddsProviderOrder = savedOddsProviderOrder();
let savedOddsProviderSelection = null;
try {
  const saved = JSON.parse(localStorage.getItem(ODDS_PROVIDER_SELECTION_KEY) || "null");
  savedOddsProviderSelection = Array.isArray(saved)
    ? saved.filter(key => typeof key === "string" && /^[a-z0-9_]+$/.test(key))
    : null;
} catch (_) {
  savedOddsProviderSelection = null;
}
const initialOddsProviders = savedOddsProviderSelection
  ? initialOddsProviderOrder.filter(key => savedOddsProviderSelection.includes(key))
  : initialOddsProviderOrder.filter(key => ODDS_PROVIDER_KEYS.includes(key));
const oddsState = { rows: [], sport: "", league: "", kind: "", search: "", favoritesOnly: false, catalog: {...ODDS_BASE_PROVIDER_CATALOG}, providerOrder: initialOddsProviderOrder, providers: initialOddsProviders, draggedProvider: "", loading: false, timer: null };

function oddsProviderInitials(name) {
  return String(name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join("").toUpperCase();
}

function providerLogoMarkup(provider, alt = "") {
  const name = provider?.name || provider?.providerName || "Sportsbook";
  const logoUrl = provider?.logoUrl || "";
  const initials = escapeHtml(oddsProviderInitials(name));
  if (!logoUrl) return `<span class="provider-logo-mark"><b class="book-initials">${initials}</b></span>`;
  return `<span class="provider-logo-mark"><img src="${escapeHtml(logoUrl)}" alt="${escapeHtml(alt)}" loading="lazy" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><b class="book-initials" hidden>${initials}</b></span>`;
}

function syncOddsProviderCatalog(entries = []) {
  entries.forEach(entry => {
    const key = String(entry?.key || "").toLowerCase();
    if (!key || !/^[a-z0-9_]+$/.test(key)) return;
    const isNew = !oddsState.catalog[key];
    oddsState.catalog[key] = {key, name: entry.name || key, logoUrl: entry.logoUrl || "", source: entry.source || "sportsbook"};
    if (!oddsState.providerOrder.includes(key)) oddsState.providerOrder.splice(Math.max(oddsState.providerOrder.indexOf("best"), 0), 0, key);
    if (isNew && savedOddsProviderSelection === null && !oddsState.providers.includes(key)) oddsState.providers.push(key);
  });
  if (!oddsState.providerOrder.includes("best")) oddsState.providerOrder.push("best");

  const header = document.querySelector(".odds-grid-head");
  const bestHeader = header?.querySelector('[data-odds-column="best"]');
  const list = document.querySelector(".odds-book-list");
  Object.values(oddsState.catalog).forEach(provider => {
    if (header && !header.querySelector(`[data-odds-column="${provider.key}"]`)) {
      const column = document.createElement("span");
      column.className = "book-head sportsbook";
      column.dataset.oddsColumn = provider.key;
      column.dataset.bookColumn = provider.key;
      column.draggable = true;
      column.title = `Drag to reorder ${provider.name}`;
      column.setAttribute("aria-label", `${provider.name} column. Drag to reorder.`);
      column.innerHTML = `${providerLogoMarkup(provider, provider.name)}<small>${escapeHtml(provider.name.toUpperCase())}</small>`;
      header.insertBefore(column, bestHeader || null);
      bindOddsColumnDrag(column);
    }
    if (list && !list.querySelector(`input[value="${provider.key}"]`)) {
      const label = document.createElement("label");
      const checked = oddsState.providers.includes(provider.key);
      label.innerHTML = `<input type="checkbox" value="${escapeHtml(provider.key)}" ${checked ? "checked" : ""}>${providerLogoMarkup(provider)}${escapeHtml(provider.name)}`;
      list.appendChild(label);
    }
  });
  document.getElementById("odds-books-count").textContent = `${oddsState.providers.length} selected`;
  document.querySelector(".odds-footer span:first-child").innerHTML = `<i class="status-dot"></i> ${Object.keys(oddsState.catalog).length} read-only exchange and sportsbook feeds`;
  applyOddsProviderOrder();
  persistOddsProviderOrder();
}

function applyOddsProviderOrder() {
  const header = document.querySelector(".odds-grid-head");
  if (!header) return;
  oddsState.providerOrder.forEach(key => {
    const column = header.querySelector(`[data-odds-column="${key}"]`);
    if (column) header.appendChild(column);
  });
  header.querySelectorAll("[data-book-column]").forEach(column => { column.hidden = !oddsState.providers.includes(column.dataset.bookColumn); });
}

function persistOddsProviderOrder() {
  localStorage.setItem(ODDS_PROVIDER_ORDER_KEY, JSON.stringify(oddsState.providerOrder));
}

function oddsProvider(row, key) {
  return (row.executionOptions || []).find(option => String(option.providerKey || "").toLowerCase() === key);
}

function oddsPriceCell(option, provider) {
  if (!option || option.matchingConfidence !== "Exact" || !option.isAvailable) return `<span class="odds-price empty" data-provider="${provider}">—<small>No exact market</small></span>`;
  const liquidity = number(option.availableLiquidity);
  const price = number(option.contractPrice);
  const american = number(option.americanOdds);
  const liquidityLabel = String(provider).startsWith("oddsapi__") ? "Bet limit unavailable" : "Depth unavailable";
  const contractAndAmerican = [price === null ? null : formatCents(price), american === null ? null : (american > 0 ? `+${Math.round(american)}` : `${Math.round(american)}`)].filter(Boolean).join(" / ");
  const headline = ["polymarket", "kalshi"].includes(provider) ? (contractAndAmerican || option.displayOdds || "—") : (option.displayOdds || contractAndAmerican || "—");
  return `<a class="odds-price" data-provider="${provider}" href="${escapeHtml(option.deepLink || "#")}" ${option.deepLink ? 'target="_blank" rel="noopener noreferrer"' : ""}>
    <strong>${escapeHtml(headline)}</strong><small>${liquidity === null ? liquidityLabel : `$${Math.round(liquidity).toLocaleString()}`}</small>
  </a>`;
}

function oddsGameRow(inputRows) {
  const rows = orderedOddsSelections(inputRows);
  const primary = rows[0] || {};
  const id = String(primary.id || "");
  const favorites = JSON.parse(localStorage.getItem("iconbets_odds_favorites") || "[]");
  const isFavorite = favorites.includes(id);
  const start = new Date(primary.event_date_et || primary.resolution_time || primary.event_start_time || 0);
  return `<article class="odds-market-row" data-odds-id="${escapeHtml(id)}">
    <span class="odds-start"><b>${Number.isNaN(start.getTime()) ? "TBD" : start.toLocaleTimeString([], {hour:"numeric", minute:"2-digit"})}</b><small>${Number.isNaN(start.getTime()) ? "" : start.toLocaleDateString([], {month:"short", day:"numeric"})}</small><button data-odds-star="${escapeHtml(id)}" class="${isFavorite ? "active" : ""}" aria-label="Favorite"><i class="ph ${isFavorite ? "ph-star-fill" : "ph-star"}"></i></button></span>
    <span class="odds-team odds-team-stack">${rows.map(row => `<span class="odds-team-selection"><strong>${escapeHtml(oddsSelectionLabel(row))}</strong><small>${escapeHtml(oddsMarketLabel(row))}</small></span>`).join("")}</span>
    ${oddsState.providerOrder.filter(key => key === "best" || oddsState.providers.includes(key)).map(key => key === "best" ? `<span class="odds-best odds-best-stack" data-provider-stack="best">${rows.map(oddsBestLine).join("")}</span>` : `<span class="odds-price-stack" data-provider-stack="${key}">${rows.map(row => oddsPriceCell(oddsProvider(row, key), key)).join("")}</span>`).join("")}
  </article>`;
}

function oddsBestLine(row) {
  const selected = new Set(oddsState.providers);
  const best = (row.executionOptions || [])
    .filter(option => {
      const providerKey = String(option?.providerKey || "").toLowerCase();
      const price = number(option?.bestExecutablePrice);
      return selected.has(providerKey)
        && option?.isAvailable
        && option?.matchingConfidence === "Exact"
        && option?.isStale !== true
        && (!option?.marketStatus || option.marketStatus === "OPEN")
        && price !== null
        && price > 0
        && price < 1;
    })
    .sort((left, right) => {
      const priceDifference = number(left.bestExecutablePrice) - number(right.bestExecutablePrice);
      if (priceDifference) return priceDifference;
      return oddsState.providerOrder.indexOf(String(left.providerKey || "").toLowerCase())
        - oddsState.providerOrder.indexOf(String(right.providerKey || "").toLowerCase());
    })[0];
  return `<span>${best ? `<strong>${escapeHtml(best.providerName)}</strong><small>${escapeHtml(best.displayOdds)}</small>` : "<strong>—</strong><small>Waiting</small>"}</span>`;
}

function orderedOddsSelections(rows) {
  const participants = String(rows[0]?.event_title || "").split(/\s+(?:vs\.?|versus|@)\s+/i).map(value => value.trim().toLowerCase());
  return [...rows].sort((a, b) => {
    const ai = participants.indexOf(String(a.outcome || "").toLowerCase());
    const bi = participants.indexOf(String(b.outcome || "").toLowerCase());
    if (ai >= 0 || bi >= 0) return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
    const order = {yes:0, over:0, no:1, under:1};
    return (order[String(a.outcome || "").toLowerCase()] ?? 2) - (order[String(b.outcome || "").toLowerCase()] ?? 2);
  });
}

function oddsMarketGroupKey(row) {
  return String(row.market_id || row.condition_id || `${row.event_id || row.event_title}|${oddsMarketKind(row)}|${row.market_line ?? ""}`);
}

const mlbSportsbookNames = {"arizona diamondbacks":"Diamondbacks","atlanta braves":"Braves","baltimore orioles":"Orioles","boston red sox":"Red Sox","chicago cubs":"Cubs","chicago white sox":"White Sox","cincinnati reds":"Reds","cleveland guardians":"Guardians","colorado rockies":"Rockies","detroit tigers":"Tigers","houston astros":"Astros","kansas city royals":"Royals","los angeles angels":"Angels","los angeles dodgers":"Dodgers","miami marlins":"Marlins","milwaukee brewers":"Brewers","minnesota twins":"Twins","new york mets":"Mets","new york yankees":"Yankees","athletics":"Athletics","oakland athletics":"Athletics","philadelphia phillies":"Phillies","pittsburgh pirates":"Pirates","san diego padres":"Padres","san francisco giants":"Giants","seattle mariners":"Mariners","st. louis cardinals":"Cardinals","st louis cardinals":"Cardinals","tampa bay rays":"Rays","texas rangers":"Rangers","toronto blue jays":"Blue Jays","washington nationals":"Nationals"};

function oddsSelectionLabel(row) {
  const outcome = String(row.outcome || "Selection").trim();
  const normalized = outcome.toLowerCase();
  const kind = oddsMarketKind(row);
  if (normalized === "yes" || normalized === "no") return normalized === "yes" ? "Yes" : "No";
  const team = mlbSportsbookNames[normalized] || outcome;
  if (kind === "moneyline") return `${team} ML`;
  if (kind === "spread" || kind === "alternate_spread") return `${team} ${number(row.market_line) !== null && number(row.market_line) > 0 ? "+" : ""}${row.market_line ?? ""}`.trim();
  if (kind === "game_total" || kind === "alternate_total") return `${team} ${row.market_line ?? ""}`.trim();
  return team;
}

function oddsMarketLabel(row) {
  return ({moneyline:"Moneyline",spread:"Run Line / Spread",alternate_spread:"Alt Spread",game_total:"Total",alternate_total:"Alt Total",yes_no:"Yes / No"})[oddsMarketKind(row)] || String(row.sports_market_type || "Market");
}

function renderOddsScreen() {
  const favorites = JSON.parse(localStorage.getItem("iconbets_odds_favorites") || "[]");
  const rows = oddsState.rows.filter(row => {
    if (oddsState.sport && canonicalOddsSport(row.canonical_sport_id || row.category) !== canonicalOddsSport(oddsState.sport)) return false;
    if (oddsState.league && String(row.canonical_league_id || row.league || "").toLowerCase() !== oddsState.league.toLowerCase()) return false;
    if (oddsState.kind && oddsMarketKind(row) !== oddsState.kind) return false;
    if (oddsState.favoritesOnly && !favorites.includes(String(row.id || ""))) return false;
    const text = `${row.outcome || ""} ${row.event_title || ""} ${row.market_title || ""}`.toLowerCase();
    return !oddsState.search || text.includes(oddsState.search);
  });
  const grid = document.getElementById("odds-grid");
  document.querySelector(".odds-screen-page")?.style.setProperty("--odds-column-count", oddsState.providers.length + 1);
  applyOddsProviderOrder();
  const groups = new Map();
  rows.forEach(row => {
    const start = new Date(row.event_date_et || row.resolution_time || 0);
    const key = row.schedule_date_et || (Number.isNaN(start.getTime()) ? "TBD" : start.toLocaleDateString("en-CA"));
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  });
  grid.innerHTML = rows.length ? [...groups.entries()].map(([date, group]) => {
    const markets = new Map();
    group.forEach(row => { const key = oddsMarketGroupKey(row); if (!markets.has(key)) markets.set(key, []); markets.get(key).push(row); });
    return `${oddsDateDivider(date)}${[...markets.values()].map(oddsGameRow).join("")}`;
  }).join("") : `<div class="odds-loading">No exact markets match these filters.</div>`;
}

function canonicalOddsSport(value) {
  const raw = String(value || "").toLowerCase();
  return ({mlb:"baseball", baseball:"baseball", nba:"basketball", wnba:"basketball", nfl:"football", nhl:"hockey"})[raw] || raw;
}

function oddsDateDivider(value) {
  if (value === "TBD") return `<div class="odds-date-divider">DATE TO BE ANNOUNCED</div>`;
  const date = new Date(`${value}T12:00:00`);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const tomorrow = new Date(today); tomorrow.setDate(today.getDate() + 1);
  const prefix = date.toDateString() === today.toDateString() ? "TODAY" : date.toDateString() === tomorrow.toDateString() ? "TOMORROW" : date.toLocaleDateString([], {weekday:"long"}).toUpperCase();
  return `<div class="odds-date-divider">${prefix}, ${date.toLocaleDateString([], {month:"long", day:"numeric"}).toUpperCase()}</div>`;
}

function oddsMarketKind(row) {
  const raw = `${row.sports_market_type || ""} ${row.market_title || ""}`.toLowerCase();
  if ((raw.includes("alternate") || raw.includes(" alt ")) && (raw.includes("spread") || raw.includes("run line") || raw.includes("handicap"))) return "alternate_spread";
  if ((raw.includes("alternate") || raw.includes(" alt ")) && raw.includes("total")) return "alternate_total";
  if (raw.includes("first half") || raw.includes("1st half")) {
    if (raw.includes("moneyline") || raw.includes("winner")) return "first_half_moneyline";
    if (raw.includes("spread") || raw.includes("handicap")) return "first_half_spread";
    if (raw.includes("total")) return "first_half_total";
  }
  if (raw.includes("first period") || raw.includes("1st period")) return raw.includes("total") ? "first_period_total" : "first_period_moneyline";
  if (raw.includes("team total")) return "team_total";
  if (raw.includes("spread") || raw.includes("run line") || raw.includes("handicap")) return "spread";
  if (raw.includes("total")) return "game_total";
  if (raw.includes("moneyline") || raw.includes("winner")) return "moneyline";
  if (raw.includes("yes") || raw.includes("no")) return "yes_no";
  return String(row.sports_market_type || "").toLowerCase().replaceAll(" ", "_");
}

function closeOddsMenus(except = null) {
  document.querySelectorAll("#odds-league-menu,#odds-market-menu,#odds-books-menu").forEach(menu => { if (menu !== except) menu.hidden = true; });
  document.querySelectorAll("#odds-league-trigger,#odds-market-trigger,#odds-books-trigger").forEach(trigger => trigger.setAttribute("aria-expanded", String(except && trigger.getAttribute("aria-controls") === except.id)));
}

function toggleOddsMenu(trigger, menu) {
  const opening = menu.hidden;
  closeOddsMenus(opening ? menu : null);
  menu.hidden = !opening;
  trigger.setAttribute("aria-expanded", String(opening));
}

async function loadOddsScreen() {
  if (oddsState.loading || document.hidden) return;
  oddsState.loading = true;
  const started = performance.now();
  try {
    const params = new URLSearchParams();
    if (oddsState.sport) params.set("sport", oddsState.sport);
    if (oddsState.league) params.set("league", oddsState.league);
    if (["moneyline", "spread", "game_total", "alternate_spread", "alternate_total"].includes(oddsState.kind)) params.set("market", oddsState.kind);
    const payload = await fetchJson(`/api/odds-screen${params.size ? `?${params}` : ""}`);
    oddsState.rows = payload.data || [];
    syncOddsProviderCatalog(payload.providers || []);
    document.getElementById("odds-latency").textContent = `${Math.round(performance.now() - started)}ms refresh`;
    document.getElementById("odds-updated").textContent = `Updated ${new Date().toLocaleTimeString()}`;
    renderOddsScreen();
  } catch (error) {
    document.getElementById("odds-latency").textContent = "Feed degraded";
    if (!oddsState.rows.length) document.getElementById("odds-grid").innerHTML = `<div class="odds-loading">${escapeHtml(error.message)}</div>`;
  } finally { oddsState.loading = false; }
}

let oddsDragScrollFrame = 0;
let oddsDragScrollSpeed = 0;

function stopOddsDragAutoScroll() {
  if (oddsDragScrollFrame) cancelAnimationFrame(oddsDragScrollFrame);
  oddsDragScrollFrame = 0;
  oddsDragScrollSpeed = 0;
  document.querySelector(".odds-grid-shell")?.classList.remove("auto-scroll-left", "auto-scroll-right");
}

function updateOddsDragAutoScroll(clientX) {
  const shell = document.querySelector(".odds-grid-shell");
  if (!shell || !oddsState.draggedProvider) return stopOddsDragAutoScroll();
  const bounds = shell.getBoundingClientRect();
  const edgeWidth = Math.min(130, Math.max(72, bounds.width * 0.12));
  let direction = 0;
  let intensity = 0;
  if (clientX < bounds.left + edgeWidth) {
    direction = -1;
    intensity = Math.min(1, Math.max(0, (bounds.left + edgeWidth - clientX) / edgeWidth));
  } else if (clientX > bounds.right - edgeWidth) {
    direction = 1;
    intensity = Math.min(1, Math.max(0, (clientX - (bounds.right - edgeWidth)) / edgeWidth));
  }
  if (!direction) return stopOddsDragAutoScroll();
  oddsDragScrollSpeed = direction * Math.round(5 + (31 * intensity));
  shell.classList.toggle("auto-scroll-left", direction < 0);
  shell.classList.toggle("auto-scroll-right", direction > 0);
  if (oddsDragScrollFrame) return;
  const initialPosition = shell.scrollLeft;
  shell.scrollLeft += oddsDragScrollSpeed;
  if (shell.scrollLeft === initialPosition) return stopOddsDragAutoScroll();
  const scrollStep = () => {
    if (!oddsState.draggedProvider || !oddsDragScrollSpeed) return stopOddsDragAutoScroll();
    const previous = shell.scrollLeft;
    shell.scrollLeft += oddsDragScrollSpeed;
    if (shell.scrollLeft === previous) return stopOddsDragAutoScroll();
    oddsDragScrollFrame = requestAnimationFrame(scrollStep);
  };
  oddsDragScrollFrame = requestAnimationFrame(scrollStep);
}

function bindOddsDragAutoScroll() {
  const shell = document.querySelector(".odds-grid-shell");
  if (!shell || shell.dataset.dragScrollBound === "true") return;
  shell.dataset.dragScrollBound = "true";
  shell.addEventListener("dragover", event => {
    if (!oddsState.draggedProvider) return;
    event.preventDefault();
    updateOddsDragAutoScroll(event.clientX);
  });
  shell.addEventListener("drop", stopOddsDragAutoScroll);
  document.addEventListener("dragend", stopOddsDragAutoScroll);
}

function bindOddsColumnDrag(header) {
  if (!header || header.dataset.dragBound === "true") return;
  header.dataset.dragBound = "true";
  header.addEventListener("dragstart", event => {
    oddsState.draggedProvider = header.dataset.oddsColumn;
    header.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", oddsState.draggedProvider);
  });
  header.addEventListener("dragover", event => {
    if (!oddsState.draggedProvider || oddsState.draggedProvider === header.dataset.oddsColumn) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    const after = event.clientX > header.getBoundingClientRect().left + (header.getBoundingClientRect().width / 2);
    header.classList.toggle("drop-before", !after);
    header.classList.toggle("drop-after", after);
  });
  header.addEventListener("dragleave", () => header.classList.remove("drop-before", "drop-after"));
  header.addEventListener("drop", event => {
    event.preventDefault();
    stopOddsDragAutoScroll();
    const source = oddsState.draggedProvider || event.dataTransfer.getData("text/plain");
    const target = header.dataset.oddsColumn;
    const after = event.clientX > header.getBoundingClientRect().left + (header.getBoundingClientRect().width / 2);
    if (source && target && source !== target) {
      const next = oddsState.providerOrder.filter(key => key !== source);
      const targetIndex = next.indexOf(target);
      next.splice(targetIndex + (after ? 1 : 0), 0, source);
      oddsState.providerOrder = next;
      oddsState.providers = next.filter(key => oddsState.providers.includes(key));
      persistOddsProviderOrder();
      renderOddsScreen();
    }
    document.querySelectorAll("[data-odds-column]").forEach(item => item.classList.remove("dragging", "drop-before", "drop-after"));
  });
  header.addEventListener("dragend", () => {
    stopOddsDragAutoScroll();
    oddsState.draggedProvider = "";
    document.querySelectorAll("[data-odds-column]").forEach(item => item.classList.remove("dragging", "drop-before", "drop-after"));
  });
}

function bindOddsScreen() {
  const leagueTrigger = document.getElementById("odds-league-trigger");
  const leagueMenu = document.getElementById("odds-league-menu");
  const marketTrigger = document.getElementById("odds-market-trigger");
  const marketMenu = document.getElementById("odds-market-menu");
  const booksTrigger = document.getElementById("odds-books-trigger");
  const booksMenu = document.getElementById("odds-books-menu");
  const bookHeaders = document.querySelectorAll("[data-odds-column]");
  bindOddsDragAutoScroll();
  leagueTrigger.addEventListener("click", () => toggleOddsMenu(leagueTrigger, leagueMenu));
  marketTrigger.addEventListener("click", () => toggleOddsMenu(marketTrigger, marketMenu));
  booksTrigger.addEventListener("click", () => toggleOddsMenu(booksTrigger, booksMenu));
  document.querySelectorAll("[data-close-menu]").forEach(button => button.addEventListener("click", () => closeOddsMenus()));
  leagueMenu.addEventListener("click", event => { const choice = event.target.closest("[data-odds-sport]"); if (!choice) return; oddsState.sport = choice.dataset.oddsSport || ""; oddsState.league = choice.dataset.oddsLeague || ""; document.getElementById("odds-league-label").textContent = oddsState.league || oddsState.sport || "All Leagues"; closeOddsMenus(); loadOddsScreen(); });
  marketMenu.addEventListener("click", event => { const choice = event.target.closest("[data-market-kind]"); if (!choice) return; oddsState.kind = choice.dataset.marketKind || ""; document.getElementById("odds-market-label").textContent = choice.childNodes[0].textContent.trim() || "All Markets"; closeOddsMenus(); document.querySelectorAll("[data-odds-kind]").forEach(item => item.classList.toggle("active", item.dataset.oddsKind === oddsState.kind)); loadOddsScreen(); });
  document.getElementById("odds-search").addEventListener("input", event => { oddsState.search = event.target.value.trim().toLowerCase(); renderOddsScreen(); });
  document.getElementById("odds-refresh").addEventListener("click", loadOddsScreen);
  document.querySelectorAll("[data-odds-kind]").forEach(button => button.addEventListener("click", () => { document.querySelectorAll("[data-odds-kind]").forEach(item => item.classList.toggle("active", item === button)); oddsState.kind = button.dataset.oddsKind; document.getElementById("odds-market-label").textContent = button.textContent.trim(); loadOddsScreen(); }));
  document.querySelector("[data-odds-all]").addEventListener("click", () => { oddsState.sport = ""; oddsState.league = ""; oddsState.kind = ""; oddsState.favoritesOnly = false; document.getElementById("odds-league-label").textContent = "All Leagues"; document.getElementById("odds-market-label").textContent = "All Markets"; document.querySelector("[data-odds-favorite]").classList.remove("active"); loadOddsScreen(); });
  document.querySelector("[data-odds-favorite]").addEventListener("click", event => { oddsState.favoritesOnly = !oddsState.favoritesOnly; event.currentTarget.classList.toggle("active", oddsState.favoritesOnly); renderOddsScreen(); });
  document.getElementById("odds-grid").addEventListener("click", event => { const star = event.target.closest("[data-odds-star]"); if (!star) return; event.preventDefault(); const values = JSON.parse(localStorage.getItem("iconbets_odds_favorites") || "[]"); const next = values.includes(star.dataset.oddsStar) ? values.filter(id => id !== star.dataset.oddsStar) : [...values, star.dataset.oddsStar]; localStorage.setItem("iconbets_odds_favorites", JSON.stringify(next)); renderOddsScreen(); });
  document.getElementById("odds-books-all").addEventListener("click", () => { booksMenu.querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = true; }); document.getElementById("odds-books-count").textContent = `${booksMenu.querySelectorAll('input[type="checkbox"]').length} selected`; });
  document.getElementById("odds-books-none").addEventListener("click", () => { booksMenu.querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = false; }); document.getElementById("odds-books-count").textContent = "0 selected"; });
  booksMenu.addEventListener("change", () => { const count = booksMenu.querySelectorAll('input[type="checkbox"]:checked').length; document.getElementById("odds-books-count").textContent = `${count} selected`; });
  document.getElementById("odds-books-search").addEventListener("input", event => { const query = event.target.value.trim().toLowerCase(); booksMenu.querySelectorAll(".odds-book-list label").forEach(label => { label.hidden = query && !label.textContent.toLowerCase().includes(query); }); });
  document.getElementById("odds-books-apply").addEventListener("click", () => { const selected = new Set([...booksMenu.querySelectorAll('input[type="checkbox"]:checked')].map(input => input.value)); if (!selected.size) return showToast("Select at least one sportsbook", "error"); oddsState.providers = oddsState.providerOrder.filter(key => selected.has(key)); savedOddsProviderSelection = [...oddsState.providers]; localStorage.setItem(ODDS_PROVIDER_SELECTION_KEY, JSON.stringify(savedOddsProviderSelection)); document.getElementById("odds-books-count").textContent = `${oddsState.providers.length} selected`; closeOddsMenus(); renderOddsScreen(); });
  bookHeaders.forEach(header => {
    header.addEventListener("dragstart", event => {
      oddsState.draggedProvider = header.dataset.oddsColumn;
      header.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", oddsState.draggedProvider);
    });
    header.addEventListener("dragover", event => {
      if (!oddsState.draggedProvider || oddsState.draggedProvider === header.dataset.oddsColumn) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      const after = event.clientX > header.getBoundingClientRect().left + (header.getBoundingClientRect().width / 2);
      header.classList.toggle("drop-before", !after);
      header.classList.toggle("drop-after", after);
    });
    header.addEventListener("dragleave", () => header.classList.remove("drop-before", "drop-after"));
    header.addEventListener("drop", event => {
      event.preventDefault();
      const source = oddsState.draggedProvider || event.dataTransfer.getData("text/plain");
      const target = header.dataset.oddsColumn;
      const after = event.clientX > header.getBoundingClientRect().left + (header.getBoundingClientRect().width / 2);
      if (source && target && source !== target) {
        const next = oddsState.providerOrder.filter(key => key !== source);
        const targetIndex = next.indexOf(target);
        next.splice(targetIndex + (after ? 1 : 0), 0, source);
        oddsState.providerOrder = next;
        oddsState.providers = next.filter(key => oddsState.providers.includes(key));
        persistOddsProviderOrder();
        renderOddsScreen();
      }
      bookHeaders.forEach(item => item.classList.remove("dragging", "drop-before", "drop-after"));
    });
    header.addEventListener("dragend", () => {
      oddsState.draggedProvider = "";
      bookHeaders.forEach(item => item.classList.remove("dragging", "drop-before", "drop-after"));
    });
  });
  document.addEventListener("click", event => { if (!event.target.closest(".odds-menu-shell")) closeOddsMenus(); });
  loadOddsScreen();
  oddsState.timer = window.setInterval(loadOddsScreen, 15000);
}

function refreshCurrentPage() {
  if (appState.paused) return;
  if (page === "overview") loadOverview();
  if (page === "trades") {
    if (appState.workspaceTab === "positions") loadPersonalPositions("open");
    else if (appState.workspaceTab === "closed") loadPersonalPositions("closed");
    else loadTrades();
    loadPersonalPnl();
  }
  if (page === "live-positions") loadPositions();
  if (page === "wallets") loadWallets();
  if (page === "position-history") loadHistory();
  if (page === "tracker") loadTrackerView();
  if (page === "edge-map") loadEdgeMap();
  if (page === "intelligence") loadIntelligence().catch(()=>{});
  if (page === "odds-screen") loadOddsScreen();
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
  if (page === "edge-map") bindEdgeMap();
  if (page === "intelligence") bindIntelligence();
  if (page === "odds-screen") bindOddsScreen();
  window.setInterval(refreshCurrentPage, AUTO_REFRESH_MS);
}

initialize();
