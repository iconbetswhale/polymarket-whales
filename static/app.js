const page = document.body.dataset.page;
const safeStorage = {
  getItem(key) {
    try {
      return window.localStorage?.getItem(key) ?? null;
    } catch (_error) {
      return null;
    }
  },
  setItem(key, value) {
    try {
      window.localStorage?.setItem(key, value);
    } catch (_error) {
      // Preferences remain session-only when browser storage is unavailable.
    }
  },
};

const PAGE_PAYLOAD_CACHE_VERSION = "v1";
function pagePayloadCacheKey(scope, query = "") {
  return `iconbets:${PAGE_PAYLOAD_CACHE_VERSION}:${scope}:${query}`;
}

function readPagePayloadCache(key, maxAgeMs = 10 * 60 * 1000) {
  try {
    const cached = JSON.parse(window.sessionStorage?.getItem(key) || "null");
    if (!cached?.savedAt || !cached?.payload || Date.now() - cached.savedAt > maxAgeMs) return null;
    return cached.payload;
  } catch (_error) {
    return null;
  }
}

function writePagePayloadCache(key, payload) {
  try {
    window.sessionStorage?.setItem(key, JSON.stringify({ savedAt: Date.now(), payload }));
  } catch (_error) {
    // A full live request still renders when session storage is unavailable.
  }
}

function latestPagePayloadCacheKey(scope) {
  return pagePayloadCacheKey(scope, "latest");
}

function cachePagePayload(scope, key, payload) {
  writePagePayloadCache(key, payload);
  writePagePayloadCache(latestPagePayloadCacheKey(scope), payload);
}

function runWhenIdle(callback) {
  if ("requestIdleCallback" in window) window.requestIdleCallback(callback, { timeout: 1200 });
  else window.setTimeout(callback, 0);
}
function storedStringArray(key) {
  try {
    const value = JSON.parse(safeStorage.getItem(key) || "[]");
    return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
  } catch (_error) {
    return [];
  }
}
const LINE_SHOP_REFRESH_MS = Math.max(2000, (number(document.body.dataset.lineShopRefreshSeconds) || 5) * 1000);
const AUTO_REFRESH_MS = page === "trades" ? LINE_SHOP_REFRESH_MS : 15000;
const appState = {
  paused: safeStorage.getItem("iconbets-refresh-paused") === "true",
  selectedTradeId: null,
  trades: [],
  pageNumber: 1,
  graphRange: "month",
  trackerVisualMode: safeStorage.getItem("iconbets-tracker-visual") === "calendar" ? "calendar" : "chart",
  trackerPerformancePayload: null,
  trackerCalendarAnchor: null,
  personalTradeId: null,
  personalSelectedTags: [],
  personalTrackerOptions: null,
  trackerDiagnostics: null,
  trackerBankroll: null,
  personalTrackerBankroll: null,
  trackerView: null,
  trackerSection: safeStorage.getItem("iconbets-tracker-section") === "bets" ? "bets" : "dashboard",
  trackerCache: { model: null, personal: null },
  trackerPage: { model: 1, personal: 1 },
  trackerSelectedBooks: { model: [], personal: [] },
  trackerBookOptions: { model: [], personal: [] },
  clvRange: ["today", "yesterday", "7d", "month", "year", "all"].includes(safeStorage.getItem("iconbets-clv-range")) ? safeStorage.getItem("iconbets-clv-range") : "7d",
  clvMethod: ["best", "novig", "custom", "respective"].includes(safeStorage.getItem("iconbets-clv-method")) ? safeStorage.getItem("iconbets-clv-method") : "respective",
  clvSelectedBooks: storedStringArray("iconbets-clv-books"),
  clvPendingBooks: [],
  clvPayload: null,
  sharpSources: {},
  sharpSourceSequence: 0,
  userSettings: null,
  sizingBankrollDirty: false,
  bankrollSavePending: false,
  account: { authenticated: false, email: null },
  appliedEntryPriceFilters: { minEntryCents: "", maxEntryCents: "" },
  executionOdds: {},
  tradeRenderSignatures: {},
  stableTradeFeed: new Map(),
  stableTradeFilterKey: "",
  latestTradeSnapshotAt: 0,
  tradeRequestSequence: 0,
  tradeRequestInFlight: false,
  tradeRefreshQueued: false,
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
    return tradeMetricChip("ph-trend-up", "N/A", "Entry slippage unavailable");
  }
  const direction = comparison.tone === "worse" ? "worse" : comparison.tone === "better" ? "better" : "unchanged";
  const aria = `${comparison.formatted} slippage, ${direction} than the tracked whale's entry`;
  return `
    <button class="trade-metric-chip slippage-chip ${comparison.tone}" type="button" data-testid="slippage-tooltip-trigger" aria-expanded="false" aria-label="${escapeHtml(aria)}">
      <i class="ph ph-trend-up" aria-hidden="true"></i>
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

function formatRefreshDateTime(value, fallback = "Waiting") {
  if (!value) return fallback;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return fallback;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  }).format(parsed);
}

function formatScheduledClock(value, fallback = "Time unavailable") {
  if (!value) return fallback;
  return String(value).replace(/:00 (?=(?:AM|PM)\b)/g, " ");
}

function upcomingPreviewStart(hour, minute = 0) {
  const now = new Date();
  const start = new Date(now);
  start.setHours(hour, minute, 0, 0);
  if (start <= now) start.setDate(start.getDate() + 1);
  return start;
}

function updateTradeSummary(payload = {}, sourceTrades = [], qualifiedTrades = []) {
  const exactProviders = new Set();
  let mappingWarnings = 0;
  let recommendedExposure = 0;
  sourceTrades.forEach((trade) => {
    const options = trade.executionOptions || [];
    const exactAvailable = options.filter((option) => option.matchingConfidence === "Exact" && option.isAvailable);
    exactAvailable.forEach((option) => exactProviders.add(String(option.providerKey || "").toLowerCase()));
    if (!exactAvailable.length || options.some((option) => option.matchingConfidence && option.matchingConfidence !== "Exact")) mappingWarnings += 1;
  });
  qualifiedTrades.forEach((trade) => {
    recommendedExposure += number(trade.card?.recommended_amount ?? trade.recommendation?.recommended_amount) || 0;
  });

  const scanned = payload.pagination?.total ?? sourceTrades.length;
  const values = {
    "trade-summary-qualified": String(qualifiedTrades.length),
    "trade-summary-scanned": Number(scanned || 0).toLocaleString(),
    "trade-summary-providers": String(exactProviders.size),
    "trade-summary-exposure": formatMoney(recommendedExposure),
    "trade-summary-warnings": String(mappingWarnings),
    "trade-activity-scan": formatDateTime(payload.status?.last_successful_refresh, "Checking"),
    "trade-activity-markets": Number(scanned || 0).toLocaleString(),
    "trade-activity-qualified": String(qualifiedTrades.length),
    "trade-activity-providers": exactProviders.size ? `${exactProviders.size} connected` : "Awaiting quotes",
  };
  Object.entries(values).forEach(([id, value]) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  });
  document.getElementById("trade-summary-warnings")?.setAttribute("data-warning", String(mappingWarnings > 0));
}

function tradeModelActivityPanel(payload = {}, sourceTrades = [], qualifiedTrades = []) {
  const exactProviders = new Set();
  sourceTrades.forEach((trade) => (trade.executionOptions || []).forEach((option) => {
    if (option.matchingConfidence === "Exact" && option.isAvailable) exactProviders.add(String(option.providerKey || "").toLowerCase());
  }));
  const status = payload.status || {};
  const feedHealthy = status.api_status === "ok" && Boolean(status.last_successful_refresh);
  const positionsMonitored = Number(status.position_count) || 0;
  const evaluated = sourceTrades.length;
  return `
    <div class="model-activity-state professional-empty-state stage2-activity-rail">
      <header class="stage2-rail-heading">
        <span class="activity-icon"><i class="ph ph-waveform" aria-hidden="true"></i></span>
        <div><span class="live-label"><i></i>${feedHealthy ? "Live" : "Checking"}</span><h2>${feedHealthy ? "No live picks" : "Scanning markets"}</h2><p>Qualified picks appear automatically.</p></div>
      </header>
      <dl class="stage2-status-grid">
        <div><dt>Last scan</dt><dd>${escapeHtml(formatDateTime(payload.status?.last_successful_refresh, "Checking"))}</dd></div>
        <div><dt>Positions monitored</dt><dd>${positionsMonitored.toLocaleString()}</dd></div>
        <div><dt>Qualified</dt><dd>${qualifiedTrades.length}</dd></div>
        <div><dt>Candidate quotes</dt><dd>${evaluated ? `${exactProviders.size} connected` : "Not required"}</dd></div>
      </dl>
      <details class="compact-scan-details"><summary>Scan details</summary><div class="empty-state-actions stage2-rail-actions"><a class="button ghost compact" href="/intelligence">Candidate Ledger</a><button class="button ghost compact" type="button" id="empty-clear-trade-filters">Clear filters</button></div></details>
    </div>`;
}

function tradeMonitoringWorkspace(payload = {}, sourceTrades = [], qualifiedTrades = []) {
  const status = payload.status || {};
  const feedHealthy = status.api_status === "ok" && Boolean(status.last_successful_refresh);
  const positionsMonitored = Number(status.position_count) || 0;
  const candidatesEvaluated = sourceTrades.length;
  const exactMapped = sourceTrades.filter((trade) => (trade.executionOptions || []).some(
    (option) => option.matchingConfidence === "Exact" && option.isAvailable,
  )).length;
  const providers = new Set();
  sourceTrades.forEach((trade) => (trade.executionOptions || []).forEach((option) => {
    if (option.matchingConfidence === "Exact" && option.isAvailable) providers.add(String(option.providerKey || "").toLowerCase());
  }));
  const recent = sourceTrades[0];
  const recentTitle = recent
    ? `${escapeHtml(recent.event_title || recent.market_title || "Candidate")} · ${escapeHtml(recent.outcome || "Selection")}`
    : "Awaiting the next market candidate";
  return `
    <section class="stage2-monitoring" aria-label="Live candidate monitoring">
      <div class="stage2-scan-hero">
        <span class="stage2-scan-orbit" aria-hidden="true"><i class="ph ph-radar"></i></span>
        <div class="stage2-scan-copy">
          <span class="live-label"><i></i>${feedHealthy ? "Live" : "Scanning"}</span>
          <h2>${feedHealthy ? "No live picks" : "Scanning markets"}</h2>
          <p>New picks appear automatically.</p>
        </div>
        <div class="stage2-scan-time"><span>Last successful scan</span><strong>${escapeHtml(formatDateTime(payload.status?.last_successful_refresh, "Checking"))}</strong></div>
      </div>
      <details class="compact-scan-details stage2-monitor-details"><summary>Scan details</summary><div class="stage2-monitor-grid">
        <section class="stage2-funnel" aria-labelledby="stage2-funnel-title">
          <header><span class="page-kicker">Candidate funnel</span><h3 id="stage2-funnel-title">Live qualification flow</h3></header>
          <ol>
            <li><span>Positions monitored</span><strong>${positionsMonitored.toLocaleString()}</strong><i style="--stage2-flow:100%"></i></li>
            <li><span>Candidates evaluated</span><strong>${candidatesEvaluated.toLocaleString()}</strong><i style="--stage2-flow:82%"></i></li>
            <li><span>Exact market mappings</span><strong>${exactMapped.toLocaleString()}</strong><i style="--stage2-flow:62%"></i></li>
            <li><span>Executable candidates</span><strong>${exactMapped.toLocaleString()}</strong><i style="--stage2-flow:44%"></i></li>
            <li class="qualified"><span>Qualified opportunities</span><strong>${qualifiedTrades.length}</strong><i style="--stage2-flow:16%"></i></li>
          </ol>
        </section>
        <section class="stage2-monitor-notes" aria-labelledby="stage2-rejections-title">
          <header><span class="page-kicker">Protection layer</span><h3 id="stage2-rejections-title">Current rejection checks</h3></header>
          <ul>
            <li><i class="ph ph-timer" aria-hidden="true"></i><span><strong>Timing &amp; market state</strong><small>Past, live, closed, and suspended markets stay excluded.</small></span></li>
            <li><i class="ph ph-intersect" aria-hidden="true"></i><span><strong>Exact mapping</strong><small>Unverified or conflicting outcome mappings cannot qualify.</small></span></li>
            <li><i class="ph ph-drop-half-bottom" aria-hidden="true"></i><span><strong>Price &amp; liquidity</strong><small>Non-executable prices and insufficient depth remain protected.</small></span></li>
          </ul>
        </section>
      </div></details>
      <footer class="stage2-recent-candidate" hidden>
        <span><i class="ph ph-clock-counter-clockwise" aria-hidden="true"></i>Most recently evaluated</span>
        <strong>${recentTitle}</strong>
        <small>${providers.size ? `${providers.size} exact provider${providers.size === 1 ? "" : "s"} available` : "Provider quotes pending"}</small>
      </footer>
    </section>`;
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
  if (refresh) refresh.textContent = formatRefreshDateTime(status.last_successful_refresh, "Waiting");
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
    username: account.username || null,
    googleOauthAvailable: Boolean(account.google_oauth_available),
    subscriptionManagementAvailable: Boolean(account.subscription_management_available),
  };
  const status = document.getElementById("account-status");
  const form = document.getElementById("account-form");
  const authenticated = document.getElementById("account-authenticated");
  const email = document.getElementById("account-email");
  const username = document.getElementById("account-username");
  const usernameInput = document.getElementById("account-username-input");
  const google = document.getElementById("account-google");
  const subscription = document.getElementById("account-subscription");
  const planStatus = document.getElementById("account-plan-status");
  if (status) status.textContent = appState.account.authenticated ? (appState.account.username || "Synced") : "Account";
  if (form) form.hidden = appState.account.authenticated;
  if (authenticated) authenticated.hidden = !appState.account.authenticated;
  if (email) email.textContent = appState.account.email || "";
  if (username) username.textContent = appState.account.username ? `@${appState.account.username}` : "Choose a username";
  if (usernameInput) usernameInput.value = appState.account.username || "";
  if (google) {
    google.classList.toggle("unavailable", !appState.account.googleOauthAvailable);
    google.setAttribute(
      "aria-label",
      appState.account.googleOauthAvailable
        ? "Continue with Google"
        : "Google sign-in requires OAuth configuration",
    );
  }
  if (subscription) subscription.classList.toggle("unavailable", !appState.account.subscriptionManagementAvailable);
  if (planStatus) planStatus.textContent = appState.account.subscriptionManagementAvailable
    ? "Subscription controls ready"
    : "Billing not connected";
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
  const requestedUsername = document.getElementById("account-username-register")?.value.trim() || "";
  if (mode === "register" && !/^[A-Za-z0-9_]{3,24}$/.test(requestedUsername)) {
    error.textContent = "Choose a 3-24 character username using letters, numbers, or underscores.";
    document.getElementById("account-username-register")?.focus();
    return;
  }
  buttons.forEach((button) => { button.disabled = true; });
  error.textContent = "";
  try {
    const account = await fetchJson(`/api/auth/${mode}`, {
      method: "POST",
      body: JSON.stringify({
        email: document.getElementById("account-email-input").value,
        username: requestedUsername,
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
  document.querySelectorAll("#account-open, [data-account-open]").forEach((button) => {
    button.addEventListener("click", openAccountDialog);
  });
  document.getElementById("account-close")?.addEventListener("click", closeAccountDialog);
  document.getElementById("account-dialog")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeAccountDialog();
  });
  document.getElementById("account-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    submitAccount("login");
  });
  document.getElementById("account-register")?.addEventListener("click", () => submitAccount("register"));
  document.getElementById("account-google")?.addEventListener("click", (event) => {
    if (appState.account.googleOauthAvailable) return;
    event.preventDefault();
    showToast("Google sign-in needs the Google OAuth client ID and secret configured in Vercel.", "error");
  });
  document.getElementById("account-subscription")?.addEventListener("click", (event) => {
    if (appState.account.subscriptionManagementAvailable) return;
    event.preventDefault();
    showToast("Subscription management will activate when the billing portal is connected.", "error");
  });
  document.getElementById("account-username-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("account-username-input");
    const error = document.getElementById("account-error");
    if (!input?.reportValidity()) return;
    try {
      const account = await fetchJson("/api/auth/username", {
        method: "PUT",
        body: JSON.stringify({ username: input.value }),
      });
      renderAccountState(account);
      showToast("Username saved.", "success");
    } catch (requestError) {
      error.textContent = requestError.message;
    }
  });
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
  const accountParams = new URLSearchParams(window.location.search);
  if (accountParams.has("auth_error")) {
    openAccountDialog();
    document.getElementById("account-error").textContent = "Google sign-in could not be completed. Check the OAuth configuration and try again.";
  } else if (accountParams.get("account") === "welcome") {
    loadAccountState().then(openAccountDialog);
  } else if (accountParams.get("account") === "signin") {
    openAccountDialog();
    document.getElementById("account-error").textContent = "Sign in to manage your subscription.";
  } else if (accountParams.get("account") === "subscription_unavailable") {
    loadAccountState().then(openAccountDialog);
    showToast("Subscription management is not connected yet.", "error");
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
  if (new URLSearchParams(window.location.search).get("preview") === "trade") {
    params.set("preview", "trade");
  }
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

const EXECUTION_PROVIDER_META = {
  polymarket: {
    name: "Polymarket",
    logoUrl: "https://polymarket.com/icons/favicon-32x32.png",
  },
  novig: {
    name: "NoVIG",
    logoUrl: "https://cdn.prod.website-files.com/642ae772b9f3360398a9d449/6436d7c4d343f31dbf62d683_favicon.png",
  },
  prophetx: {
    name: "ProphetX",
    logoUrl: "/static/assets/providers/prophetx.ico",
  },
  "4cx": {
    name: "4CX",
    logoUrl: "/static/assets/providers/4cx.png",
  },
  fourcx: {
    name: "4CX",
    logoUrl: "/static/assets/providers/4cx.png",
  },
  kalshi: {
    name: "Kalshi",
    logoUrl: "/static/assets/providers/kalshi.png",
  },
};

function canonicalExecutionProviderKey(value) {
  return String(value || "").trim().toLowerCase().replace(/^oddsapi__/, "");
}

function trackerMetricCard(label, value, icon, tone = "neutral") {
  return `
    <article class="metric-card tracker-metric-card tone-${escapeHtml(tone)}">
      <div class="metric-icon"><i class="ph ${icon}" aria-hidden="true"></i></div>
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </article>
  `;
}

function trackerMetrics(summary = {}, clv = {}) {
  const allClv = clv.periods?.all || {};
  const pnl = Number(summary.realized_profit_loss) || 0;
  const roi = Number(summary.roi) || 0;
  const drawdownUnits = Math.max(0, (Number(summary.maximum_drawdown) || 0) / 0.01);
  const stakeClv = number(allClv.stake_weighted_clv_pct);
  const averageClv = number(allClv.average_clv_pct);
  const medianClv = number(allClv.median_clv_pct);
  const positiveClv = number(allClv.positive_clv_rate);
  const clvTone = (value) => value === null ? "muted" : value > 0 ? "positive" : value < 0 ? "negative" : "neutral";
  return [
    trackerMetricCard("Realized P&L", signedMoney(pnl), "ph-currency-dollar", pnl > 0 ? "positive" : pnl < 0 ? "negative" : "neutral"),
    trackerMetricCard("ROI", formatPercent(roi), "ph-trend-up", roi > 0 ? "positive" : roi < 0 ? "negative" : "neutral"),
    trackerMetricCard("Tracked Bets", String(summary.total_tracked_bets || 0), "ph-list-checks", "info"),
    trackerMetricCard("Record", `${summary.wins || 0}-${summary.losses || 0}-${summary.pushes_voids || 0}`, "ph-trophy", "info"),
    trackerMetricCard("Win Rate", summary.win_rate === null ? "Pending" : formatPercent(summary.win_rate), "ph-target", summary.win_rate === null ? "muted" : "positive"),
    trackerMetricCard("Max Drawdown", `${drawdownUnits.toFixed(drawdownUnits % 1 ? 2 : 1)}u`, "ph-trend-down", drawdownUnits > 0 ? "warning" : "neutral"),
    trackerMetricCard("Stake-weighted CLV", stakeClv === null ? "—" : formatClvPercent(stakeClv), "ph-scales", clvTone(stakeClv)),
    trackerMetricCard("Average CLV", averageClv === null ? "—" : formatClvPercent(averageClv), "ph-chart-line", clvTone(averageClv)),
    trackerMetricCard("Median CLV", medianClv === null ? "—" : formatClvPercent(medianClv), "ph-waveform", clvTone(medianClv)),
    trackerMetricCard("Positive CLV", positiveClv === null ? "—" : formatPercent(positiveClv), "ph-check-circle", positiveClv === null ? "muted" : positiveClv >= 0.5 ? "positive" : "negative"),
  ].join("");
}

function executionProviderMeta(option = {}) {
  const providerKey = canonicalExecutionProviderKey(option.providerKey);
  const defaults = EXECUTION_PROVIDER_META[providerKey] || {};
  return {
    key: providerKey,
    name: option.providerName || defaults.name || "Exchange",
    // Keep verified local exchange marks authoritative. Provider payloads can
    // contain expired logo URLs, which previously reduced 4CX to initials.
    logoUrl: defaults.logoUrl || option.logoUrl || "",
  };
}

function executionOptionProbability(option = {}) {
  const direct = number(
    option.bestExecutablePrice
      ?? option.effectiveEntryPrice
      ?? option.effectivePrice
      ?? option.contractPrice,
  );
  if (direct !== null && direct > 0 && direct < 1) return direct;
  const american = number(option.americanOdds);
  if (american === null || american === 0) return null;
  return american > 0 ? 100 / (american + 100) : Math.abs(american) / (Math.abs(american) + 100);
}

const EXECUTION_PRICE_TIE_TOLERANCE = 1e-3;

function normalizeExecutionOption(option = {}) {
  return {
    ...option,
    providerName: option.providerName ?? option.provider_name,
    providerKey: option.providerKey ?? option.provider_key,
    matchingConfidence: option.matchingConfidence ?? option.matching_confidence ?? (option.isExactMatch ? "Exact" : ""),
    isAvailable: option.isAvailable ?? option.is_available,
    isBestPrice: option.isBestPrice ?? option.is_best_price,
    displayOdds: option.displayOdds ?? option.display_odds ?? option.nativePrice,
    americanOdds: option.americanOdds ?? option.american_odds,
    contractPrice: option.contractPrice ?? option.contract_price,
    effectiveEntryPrice: option.effectiveEntryPrice ?? option.effective_entry_price,
    bestExecutablePrice: option.bestExecutablePrice ?? option.best_executable_price,
    availableLiquidity: option.availableLiquidity ?? option.available_liquidity,
    canFillRecommendedStake: option.canFillRecommendedStake ?? option.can_fill_recommended_stake,
    isStale: option.isStale ?? option.is_stale,
    marketStatus: option.marketStatus ?? option.market_status,
    feeRate: option.feeRate ?? option.fee_rate,
    estimatedFees: option.estimatedFees ?? option.estimated_fees,
    recommendedStake: option.recommendedStake ?? option.recommended_stake,
    quoteAgeSeconds: option.quoteAgeSeconds ?? option.quote_age_seconds,
    deepLink: option.deepLink ?? option.deep_link ?? option.directMarketUrl ?? option.direct_market_url,
    logoUrl: option.logoUrl ?? option.logo_url,
  };
}

function bestExecutionOption(trade) {
  // The comparison ladder intentionally includes every connected exchange, but
  // the one-click recommendation is restricted to the backend-approved venue:
  // NoVIG, ProphetX, or a genuinely better 4CX quote.
  const supported = new Set(["4cx", "fourcx", "novig", "prophetx"]);
  const selected = normalizeExecutionOption(
    trade.selected_execution_option || trade.selectedExecutionOption || {},
  );
  const selectedKey = canonicalExecutionProviderKey(selected.providerKey);
  if (
    selectedKey
    && supported.has(selectedKey)
    && selected.isAvailable !== false
    && selected.canFillRecommendedStake !== false
    && selected.isStale !== true
    && Boolean(selected.deepLink)
  ) {
    return { ...selected, isBestPrice: true };
  }
  const options = (trade.executionOptions || [])
    .map(normalizeExecutionOption)
    .filter((option) => {
      const exact = option.matchingConfidence === "Exact" || option.isExactMatch === true;
      return exact
        && option.isAvailable === true
        && option.canFillRecommendedStake === true
        && option.isStale !== true
        && String(option.marketStatus || "").toUpperCase() === "OPEN"
        && number(option.availableLiquidity) > 0
        && Boolean(option.deepLink)
        && supported.has(canonicalExecutionProviderKey(option.providerKey));
    });
  const ranked = [...options].sort((left, right) => {
    const leftPrice = executionOptionProbability(left);
    const rightPrice = executionOptionProbability(right);
    if (leftPrice === null) return 1;
    if (rightPrice === null) return -1;
    const priceDifference = leftPrice - rightPrice;
    if (Math.abs(priceDifference) > EXECUTION_PRICE_TIE_TOLERANCE) {
      return priceDifference;
    }
    const leftIsNoVig = canonicalExecutionProviderKey(left.providerKey) === "novig";
    const rightIsNoVig = canonicalExecutionProviderKey(right.providerKey) === "novig";
    if (leftIsNoVig !== rightIsNoVig) return leftIsNoVig ? -1 : 1;
    return priceDifference;
  });
  if (ranked.length) return ranked[0];

  const explicit = options.find(option => option.isBestPrice);
  if (explicit) return explicit;

  return null;
}

function executionVenueStack(trade, best) {
  const bestKey = canonicalExecutionProviderKey(best?.providerKey);
  const venues = (trade.executionOptions || [])
    .map(normalizeExecutionOption)
    .filter(option => {
      const exact = option.matchingConfidence === "Exact" || option.isExactMatch === true;
      return exact && option.isAvailable === true;
    })
    .filter((option, index, rows) => rows.findIndex(
      candidate => canonicalExecutionProviderKey(candidate.providerKey)
        === canonicalExecutionProviderKey(option.providerKey),
    ) === index)
    .sort((left, right) => {
      const leftBest = canonicalExecutionProviderKey(left.providerKey) === bestKey ? 1 : 0;
      const rightBest = canonicalExecutionProviderKey(right.providerKey) === bestKey ? 1 : 0;
      return rightBest - leftBest;
    })
    .slice(0, 5);
  if (venues.length < 2) return "";
  return `<span class="execution-venue-stack" aria-label="Compared ${venues.length} exact exchange prices">${venues.map(option => {
    const meta = executionProviderMeta(option);
    const active = canonicalExecutionProviderKey(option.providerKey) === bestKey ? "is-best" : "";
    return `<span class="${active}" title="${escapeHtml(meta.name)}">${providerLogoMarkup({ name: meta.name, logoUrl: meta.logoUrl }, meta.name)}</span>`;
  }).join("")}<small>${venues.length} checked</small></span>`;
}

function executionOptionDisplayOdds(option = {}) {
  const providerKey = canonicalExecutionProviderKey(option.providerKey);
  const executablePrice = number(
    option.bestExecutablePrice
      ?? option.effectiveEntryPrice
      ?? option.effectivePrice
      ?? option.contractPrice,
  );
  const americanOdds = number(option.americanOdds);
  if (["polymarket", "kalshi"].includes(providerKey)) {
    return executablePrice === null
      ? (option.displayOdds || "Odds unavailable")
      : formatCents(executablePrice);
  }
  if (americanOdds !== null) {
    return americanOdds > 0 ? `+${Math.round(americanOdds)}` : `${Math.round(americanOdds)}`;
  }
  return option.displayOdds || (
    executablePrice === null ? "Odds unavailable" : formatCents(executablePrice)
  );
}

function probabilityToAmerican(probability) {
  const price = number(probability);
  if (price === null || price <= 0 || price >= 1) return null;
  return price >= 0.5
    ? Math.round((-100 * price) / (1 - price))
    : Math.round((100 * (1 - price)) / price);
}

function executionComparisonOptions(trade) {
  const supported = new Set(["polymarket", "kalshi", "novig", "prophetx", "4cx"]);
  const byProvider = new Map();
  (trade.executionOptions || []).map(normalizeExecutionOption).forEach((option) => {
    const key = canonicalExecutionProviderKey(option.providerKey);
    const exact = option.matchingConfidence === "Exact" || option.isExactMatch === true;
    if (!supported.has(key) || !exact) return;
    const current = byProvider.get(key);
    const native = !String(option.providerKey || "").toLowerCase().startsWith("oddsapi__");
    const currentNative = current
      && !String(current.providerKey || "").toLowerCase().startsWith("oddsapi__");
    const quality = (native ? 8 : 0) + (option.isAvailable ? 4 : 0)
      + (executionOptionProbability(option) !== null ? 2 : 0)
      + (number(option.availableLiquidity) !== null ? 1 : 0);
    const currentQuality = current
      ? (currentNative ? 8 : 0) + (current.isAvailable ? 4 : 0)
        + (executionOptionProbability(current) !== null ? 2 : 0)
        + (number(current.availableLiquidity) !== null ? 1 : 0)
      : -1;
    if (!current || quality > currentQuality) byProvider.set(key, option);
  });
  return [...byProvider.values()].sort((left, right) => {
    const leftAvailable = left.isAvailable === true ? 0 : 1;
    const rightAvailable = right.isAvailable === true ? 0 : 1;
    if (leftAvailable !== rightAvailable) return leftAvailable - rightAvailable;
    const leftPrice = executionOptionProbability(left);
    const rightPrice = executionOptionProbability(right);
    if (leftPrice === null) return 1;
    if (rightPrice === null) return -1;
    return leftPrice - rightPrice;
  });
}

function executionComparisonPrice(option) {
  const key = canonicalExecutionProviderKey(option.providerKey);
  const executable = executionOptionProbability(option);
  if (["polymarket", "kalshi"].includes(key)) {
    return executable === null ? "—" : formatCents(executable);
  }
  const originalAmerican = number(option.americanOdds);
  const american = originalAmerican ?? probabilityToAmerican(executable);
  if (american === null) return "—";
  return american > 0 ? `+${american}` : `${american}`;
}

function executionComparisonDetail(option) {
  const key = canonicalExecutionProviderKey(option.providerKey);
  const raw = number(option.contractPrice);
  const effective = executionOptionProbability(option);
  const fees = number(option.estimatedFees);
  if (key === "kalshi" && raw !== null && effective !== null && effective > raw + 0.0001) {
    return `${formatCents(raw)} contract + ${fees === null ? "verified fees" : `${formatMoney(fees)} fees`}`;
  }
  const liquidity = number(option.availableLiquidity);
  if (liquidity !== null) return `${formatCompactMoney(liquidity)} available`;
  return option.isAvailable ? "Exact executable quote" : "No executable quote";
}

function executionComparisonLadder(trade) {
  const options = executionComparisonOptions(trade);
  if (!options.length) return "";
  const best = bestExecutionOption(trade);
  const bestKey = canonicalExecutionProviderKey(best?.providerKey);
  return `
    <section class="exchange-comparison-card">
      <div class="section-label">
        <span><i class="ph ph-scales" aria-hidden="true"></i>Exchange line shop</span>
        <small>All-in price for this bet size</small>
      </div>
      <div class="exchange-comparison-list">
        ${options.map((option, index) => {
          const meta = executionProviderMeta(option);
          const key = canonicalExecutionProviderKey(option.providerKey);
          const isBest = key === bestKey && option.isAvailable === true;
          const body = `
            <span class="exchange-rank">${isBest ? '<i class="ph ph-crown" aria-hidden="true"></i>' : index + 1}</span>
            ${providerLogoMarkup({ name: meta.name, logoUrl: meta.logoUrl }, meta.name)}
            <span class="exchange-provider-copy"><strong>${escapeHtml(meta.name)}</strong><small>${escapeHtml(executionComparisonDetail(option))}</small></span>
            <span class="exchange-price-copy"><strong>${escapeHtml(executionComparisonPrice(option))}</strong><small>${isBest ? "Best executable" : (option.isAvailable ? "Executable" : "Unavailable")}</small></span>
            <i class="ph ph-arrow-up-right exchange-open-icon" aria-hidden="true"></i>
          `;
          return option.isAvailable && option.deepLink
            ? `<a class="exchange-comparison-row exchange-comparison-row--${escapeHtml(key)} ${isBest ? "is-best" : ""}" href="${escapeHtml(option.deepLink)}" target="_blank" rel="noopener noreferrer">${body}</a>`
            : `<div class="exchange-comparison-row exchange-comparison-row--${escapeHtml(key)} is-unavailable">${body}</div>`;
        }).join("")}
      </div>
    </section>
  `;
}

function executionOptionButton(trade, rawOption) {
  const option = normalizeExecutionOption(rawOption);
  if (option.matchingConfidence !== "Exact") return "";
  const meta = executionProviderMeta(option);
  const providerName = meta.name;
  const providerKey = meta.key || "provider";
  const nativeOdds = executionOptionDisplayOdds(option);
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
    { name: providerName, logoUrl: meta.logoUrl },
  );
  const content = `
    ${providerMark}
    <span class="execution-option-copy"><strong>${escapeHtml(displayOdds)}</strong></span>
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
  if (trade.isRefreshPending) {
    return `<span class="execution-toolbar execution-toolbar--empty"><span class="execution-empty-quote"><i class="ph ph-eye" aria-hidden="true"></i><span><small>Candidate state</small><strong>Signal changed - monitoring</strong></span></span></span>`;
  }
  const best = bestExecutionOption(trade);
  if (best) {
    return `<span class="execution-toolbar execution-toolbar--best" aria-label="Best line-shopped exchange price"><span class="execution-options-scroll">${executionOptionButton(trade, { ...best, isBestPrice: true })}</span>${executionVenueStack(trade, best)}</span>`;
  }
  return `<span class="execution-toolbar execution-toolbar--empty"><span class="execution-empty-quote"><i class="ph ph-clock" aria-hidden="true"></i><span><small>Best price</small><strong>Checking exchanges</strong></span></span></span>`;
}

// Consensus snapshots refresh independently from the five-second execution
// line shop. Keep a previously verified card through brief wallet/API gaps so
// a venue or quote refresh updates the card instead of removing it.
const TRADE_DISAPPEARANCE_GRACE_MS = 900000;
const STABLE_TRADE_FEED_STORAGE_KEY = "iconbets-stable-trade-feed-v1";

function restoreStableTradeFeed(filterKey, now) {
  if (appState.stableTradeFeed.size) return;
  let saved;
  try {
    saved = JSON.parse(safeStorage.getItem(STABLE_TRADE_FEED_STORAGE_KEY) || "null");
  } catch (_error) {
    return;
  }
  if (!saved || saved.filterKey !== filterKey || !Array.isArray(saved.entries)) return;
  saved.entries.slice(0, 20).forEach((entry) => {
    const id = String(entry?.trade?.id || "");
    const lastSeenAt = number(entry?.lastSeenAt);
    if (!id || lastSeenAt === null || now - lastSeenAt > TRADE_DISAPPEARANCE_GRACE_MS) return;
    appState.stableTradeFeed.set(id, {
      trade: entry.trade,
      lastSeenAt,
    });
  });
  appState.latestTradeSnapshotAt = Math.max(
    appState.latestTradeSnapshotAt,
    number(saved.latestTradeSnapshotAt) || 0,
  );
}

function persistStableTradeFeed(filterKey) {
  safeStorage.setItem(STABLE_TRADE_FEED_STORAGE_KEY, JSON.stringify({
    filterKey,
    latestTradeSnapshotAt: appState.latestTradeSnapshotAt,
    entries: [...appState.stableTradeFeed.values()].slice(0, 20),
  }));
}

function visualPreviewTrade() {
  const start = upcomingPreviewStart(14, 0);
  const timestamp = new Date().toISOString();
  const makeOption = (providerName, providerKey, displayOdds, price, americanOdds, liquidity, deepLink) => ({
    providerName, providerKey, displayOdds, deepLink,
    marketId: `visual-preview:${providerKey}:moneyline`,
    selectionId: `visual-preview:${providerKey}:phillies`,
    isAvailable: true,
    lastUpdated: timestamp,
    matchingConfidence: "Exact",
    americanOdds,
    contractPrice: ["polymarket", "kalshi"].includes(providerKey) ? price : null,
    bestExecutablePrice: price,
    effectiveEntryPrice: price,
    availableLiquidity: liquidity,
    canFillRecommendedStake: true,
    quoteStatus: "OPEN",
    marketStatus: "OPEN",
    isExactMatch: true,
    isStale: false,
    isBestPrice: providerKey === "novig",
    recommendedStake: 35,
    estimatedFees: providerKey === "kalshi" ? 0.31 : 0,
    quoteAgeSeconds: providerKey === "novig" ? 2 : 4,
  });
  const supportingWallets = [
    { wallet_label: "FerrariChampion2026", wallet_address: "preview-ferrari", wallet_profile_url: "#", amount: 3390, average_entry_price: 0.43, relative_units: 1.7, role: "Lead Sharp", is_lead_sharp: true, top_category_ids: ["MLB Moneyline"], category_weight: 1 },
    { wallet_label: "WordyLittleNeck", wallet_address: "preview-wordy", wallet_profile_url: "#", amount: 2180, average_entry_price: 0.44, relative_units: 1.3, role: "Supporting Sharp", is_lead_sharp: false, top_category_ids: ["MLB"], category_weight: 1 },
    { wallet_label: "SportMaster777", wallet_address: "preview-sportmaster", wallet_profile_url: "#", amount: 1280, average_entry_price: 0.445, relative_units: 0.9, role: "Supporting Sharp", is_lead_sharp: false, top_category_ids: ["Baseball"], category_weight: 1 },
  ];
  const recommendation = {
    available: true,
    recommended_amount: 35,
    recommended_units: 0.35,
    recommended_shares: 84.34,
    current_user_entry_price: 0.415,
    sharp_average_entry_price: 0.438,
    price_slippage_fraction: -0.0525,
    raw_fair_probability: 0.468,
    fee_adjusted_fair_probability: 0.464,
    composite_fair_probability: 0.464,
    estimated_win_probability: 0.472,
    calculated_edge: 0.057,
    evidence_score: 0.81,
    edge_reliability_factor: 0.92,
    full_kelly_fraction: 0.098,
    half_kelly_fraction: 0.049,
    final_recommended_fraction: 0.0035,
    trade_grade: "A",
    confidence_score: 82,
    calculation_version: "visual-preview",
    recommendation_version: "visual-preview",
    execution_plan: { provider: "NoVIG", maximum_average_price: 0.445, effective_price_for_executable_amount: 0.415, executable_amount: 35, estimated_fees: 0 },
  };
  return {
    id: "visual-preview-trade",
    isVisualPreview: true,
    tradeFeedEligible: true,
    modelTrackerEligible: false,
    modelTrackerRejectionReason: "Visual preview only — never tracked or signaled",
    category: "Baseball",
    league: "MLB",
    canonical_sport_id: "BASEBALL",
    canonical_league_id: "MLB",
    event_title: "Philadelphia Phillies vs. New York Mets",
    market_title: "Moneyline · Philadelphia Phillies",
    sports_market_type: "Moneyline",
    outcome: "Philadelphia Phillies",
    event_time_et: formatScheduledClock(start.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })),
    event_date_et: start.toISOString(),
    resolution_time: start.toISOString(),
    confidence_score: 82,
    agreeing_wallet_count: 3,
    raw_sharp_count: 3,
    rawAgreeingSharpCount: 3,
    rawContradictingSharpCount: 0,
    lead_sharp_count: 1,
    supporting_sharp_count: 2,
    weighted_sharp_count: 3,
    supporting_wallets: supportingWallets,
    primary_trader: { ...supportingWallets[0], amount: 6850, average_entry: 0.438, relative_units: 1.7, top_category: "MLB Moneyline", adjusted_hit_rate: 0.637, sample_size: 147 },
    trade_quality: { grade: "A", score: 82 },
    recommendation,
    card: {
      recommended_amount: 35, recommended_units: 0.35, recommended_shares: 84.34,
      current_actionable_price: 0.415, trader_average_entry_price: 0.438,
      trader_bet_amount: 6850, relative_bet_size: 1.7, category_hit_rate: 0.637,
      slippage_fraction: -0.0525,
      event_time: formatScheduledClock(start.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })),
    },
    executionOptions: [
      makeOption("NoVIG", "novig", "+141", 0.415, 141, 18400, "https://novig.us/"),
      makeOption("4CX", "4cx", "+136", 0.4237, 136, 9200, "https://4cx.io/"),
      makeOption("ProphetX", "prophetx", "+133", 0.4292, 133, 7100, "https://prophetx.co/"),
      makeOption("Polymarket", "polymarket", "44¢", 0.44, 127, 32800, "https://polymarket.com/"),
      makeOption("Kalshi", "kalshi", "45¢", 0.45, 122, 12600, "https://kalshi.com/"),
    ],
    orderbook: {
      asks: [{ price: 0.44, size: 52000 }, { price: 0.45, size: 31000 }, { price: 0.46, size: 18500 }, { price: 0.47, size: 8200 }],
      bids: [{ price: 0.43, size: 41000 }, { price: 0.42, size: 33500 }, { price: 0.41, size: 19000 }, { price: 0.40, size: 9700 }],
    },
    orderbook_summary: { best_ask: 0.44, best_bid: 0.43 },
    demoPriceHistory: [
      { timestamp: Date.now() - 86400000, value: 0.402 },
      { timestamp: Date.now() - 64800000, value: 0.421 },
      { timestamp: Date.now() - 43200000, value: 0.414 },
      { timestamp: Date.now() - 21600000, value: 0.438 },
      { timestamp: Date.now(), value: 0.415 },
    ],
    personalExposureSummary: { type: "none" },
  };
}

function secondaryVisualPreviewTrade() {
  const trade = visualPreviewTrade();
  const start = upcomingPreviewStart(16, 5);
  const quoteConfig = {
    novig: { displayOdds: "+145", price: 0.4082, americanOdds: 145, liquidity: 14200 },
    "4cx": { displayOdds: "+148", price: 0.4032, americanOdds: 148, liquidity: 11800 },
    prophetx: { displayOdds: "+142", price: 0.4132, americanOdds: 142, liquidity: 9600 },
    polymarket: { displayOdds: "42¢", price: 0.42, americanOdds: 138, liquidity: 27400 },
    kalshi: { displayOdds: "43¢", price: 0.43, americanOdds: 133, liquidity: 15600 },
  };
  trade.id = "visual-preview-trade-2";
  trade.category = "MLB";
  trade.league = "MLB";
  trade.event_title = "Arizona Diamondbacks vs. Washington Nationals";
  trade.market_title = "Moneyline · Arizona Diamondbacks";
  trade.outcome = "Arizona Diamondbacks";
  trade.event_time_et = formatScheduledClock(start.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }));
  trade.event_date_et = start.toISOString();
  trade.resolution_time = start.toISOString();
  trade.confidence_score = 73;
  trade.agreeing_wallet_count = 2;
  trade.raw_sharp_count = 2;
  trade.rawAgreeingSharpCount = 2;
  trade.lead_sharp_count = 1;
  trade.supporting_sharp_count = 1;
  trade.weighted_sharp_count = 2;
  trade.supporting_wallets = trade.supporting_wallets.slice(0, 2).map((wallet, index) => ({
    ...wallet,
    amount: index === 0 ? 2780 : 1420,
    average_entry_price: index === 0 ? 0.426 : 0.432,
    relative_units: index === 0 ? 1.2 : 0.8,
  }));
  trade.primary_trader = {
    ...trade.supporting_wallets[0],
    amount: 4200,
    average_entry: 0.428,
    relative_units: 1.2,
    top_category: "MLB Moneyline",
    adjusted_hit_rate: 0.591,
    sample_size: 96,
  };
  trade.trade_quality = { grade: "B+", score: 73 };
  trade.recommendation = {
    ...trade.recommendation,
    recommended_amount: 20,
    recommended_units: 0.2,
    recommended_shares: 49.63,
    current_user_entry_price: 0.4032,
    sharp_average_entry_price: 0.428,
    price_slippage_fraction: -0.0579,
    confidence_score: 73,
    trade_grade: "B+",
    execution_plan: {
      provider: "4CX",
      maximum_average_price: 0.435,
      effective_price_for_executable_amount: 0.4032,
      executable_amount: 20,
      estimated_fees: 0,
    },
  };
  trade.card = {
    ...trade.card,
    recommended_amount: 20,
    recommended_units: 0.2,
    recommended_shares: 49.63,
    current_actionable_price: 0.4032,
    trader_average_entry_price: 0.428,
    trader_bet_amount: 4200,
    relative_bet_size: 1.2,
    category_hit_rate: 0.591,
    slippage_fraction: -0.0579,
    event_time: formatScheduledClock(start.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })),
  };
  trade.executionOptions = trade.executionOptions.map((option) => {
    const config = quoteConfig[option.providerKey];
    return {
      ...option,
      ...config,
      marketId: `visual-preview:${option.providerKey}:moneyline-2`,
      selectionId: `visual-preview:${option.providerKey}:diamondbacks`,
      contractPrice: ["polymarket", "kalshi"].includes(option.providerKey) ? config.price : null,
      bestExecutablePrice: config.price,
      effectiveEntryPrice: config.price,
      availableLiquidity: config.liquidity,
      recommendedStake: 20,
      isBestPrice: option.providerKey === "4cx",
    };
  });
  trade.orderbook = {
    asks: [{ price: 0.43, size: 39000 }, { price: 0.44, size: 24000 }, { price: 0.45, size: 13200 }],
    bids: [{ price: 0.42, size: 36000 }, { price: 0.41, size: 27000 }, { price: 0.40, size: 14500 }],
  };
  trade.orderbook_summary = { best_ask: 0.43, best_bid: 0.42 };
  trade.demoPriceHistory = [
    { timestamp: Date.now() - 86400000, value: 0.447 },
    { timestamp: Date.now() - 64800000, value: 0.438 },
    { timestamp: Date.now() - 43200000, value: 0.426 },
    { timestamp: Date.now() - 21600000, value: 0.414 },
    { timestamp: Date.now(), value: 0.4032 },
  ];
  return trade;
}

function stableTradeFilterKey(filters) {
  const copy = { ...filters };
  delete copy.sort;
  return JSON.stringify(copy);
}

function officialIdentityKeys(value, snapshot = false) {
  const source = snapshot ? value : (value.validation_ids || {});
  const eventId = snapshot
    ? value.canonical_event_id || value.canonical_event_slug
    : source.event_id || value.event_slug;
  const marketId = snapshot
    ? value.canonical_market_id || value.canonical_market_slug
    : source.condition_id || value.canonical_market_key || source.market_slug;
  const outcomeId = snapshot
    ? value.outcome_id || value.recommended_side
    : value.clob_token_id || source.outcome || value.canonical_side_key || value.outcome;
  const line = snapshot ? value.market_line : value.market_line;
  const normalize = (part) => String(part ?? "").trim().toLowerCase();
  const keys = new Set();
  if (eventId && marketId && outcomeId) {
    keys.add(["canonical", eventId, marketId, line, outcomeId].map(normalize).join("::"));
  }
  const eventTitle = snapshot ? value.event_title : value.event_title;
  const marketTitle = snapshot ? value.market_title : value.market_title;
  const side = snapshot ? value.recommended_side : value.outcome;
  if (eventTitle && marketTitle && side) {
    keys.add(["text", eventTitle, marketTitle, line, side].map(normalize).join("::"));
  }
  return keys;
}

function frozenOfficialTrade(record, liveTrade = null) {
  const frozen = record.snapshot || {};
  const originalPrice = number(
    frozen.effective_entry_price
    ?? frozen.provider_entry_price
    ?? frozen.current_executable_entry_price,
  );
  const amount = number(frozen.original_displayed_amount) || 0;
  const units = number(frozen.original_recommended_units) || 0;
  const shares = originalPrice && originalPrice > 0 ? amount / originalPrice : null;
  const supportingWallets = (frozen.agreeing_sharps || []).map((sharp, index) => ({
    ...sharp,
    wallet_address: sharp.wallet_address || (frozen.agreeing_wallet_ids || [])[index],
    wallet_label: sharp.wallet_label || (frozen.agreeing_wallet_labels || [])[index],
  }));
  const base = liveTrade || {
    id: `official:${frozen.snapshot_id}`,
    event_title: frozen.event_title,
    market_title: frozen.market_title,
    outcome: frozen.recommended_side,
    category: frozen.category,
    league: frozen.league,
    canonical_category_id: frozen.canonical_category_id,
    event_date_et: frozen.event_start_time,
    event_start_time: frozen.event_start_time,
    resolution_time: frozen.event_start_time,
    market_line: frozen.market_line,
    clob_token_id: frozen.outcome_id,
    sports_market_type: frozen.market_title,
    primary_trader: frozen.primary_sharp || {},
    supporting_wallets: supportingWallets,
    executionOptions: [],
    tradeFeedEligible: true,
    modelTrackerEligible: true,
    isHidden: false,
    isPinnedByCurrentUser: false,
  };
  const liveQualified = Boolean(liveTrade);
  return {
    ...base,
    confidence_score: frozen.confidence_score,
    agreeing_wallet_count: frozen.sharps_count || 0,
    raw_sharp_count: frozen.raw_sharp_count || frozen.sharps_count || 0,
    lead_sharp_count: frozen.lead_sharp_count || 0,
    supporting_sharp_count: frozen.supporting_sharp_count || 0,
    weighted_sharp_count: frozen.weighted_sharp_count || 0,
    isOfficialTracked: true,
    officialLiveQualified: liveQualified,
    officialSnapshot: frozen,
    candidateState: liveQualified ? "OFFICIAL_LIVE" : "OFFICIAL_MONITORING",
    isRefreshPending: false,
    recommendation: {
      ...(base.recommendation || {}),
      recommended_amount: amount,
      recommended_units: units,
      recommended_shares: shares,
      original_displayed_amount: amount,
      original_recommended_units: units,
      current_user_entry_price: liveQualified
        ? base.recommendation?.current_user_entry_price
        : originalPrice,
      effective_entry_price: originalPrice,
      final_recommended_fraction: frozen.final_recommended_fraction,
      estimated_win_probability: frozen.estimated_win_probability,
      sharp_average_entry_price: frozen.sharp_average_entry_price,
    },
    card: {
      ...(base.card || {}),
      recommended_amount: amount,
      recommended_units: units,
      recommended_shares: shares,
      event_time: frozen.event_start_time,
      current_actionable_price: liveQualified
        ? base.card?.current_actionable_price
        : originalPrice,
      trader_average_entry_price: frozen.sharp_average_entry_price,
    },
  };
}

function mergeOfficialTrackedTrades(liveTrades, officialRecords) {
  const unmatched = new Set(officialRecords || []);
  const merged = (liveTrades || []).map((trade) => {
    const liveKeys = officialIdentityKeys(trade);
    const record = [...unmatched].find((candidate) => {
      const frozenKeys = officialIdentityKeys(candidate.snapshot || {}, true);
      return [...liveKeys].some((key) => frozenKeys.has(key));
    });
    if (!record) return trade;
    unmatched.delete(record);
    return frozenOfficialTrade(record, trade);
  });
  unmatched.forEach((record) => merged.push(frozenOfficialTrade(record)));
  return merged;
}

function stabilizeTradeFeed(incoming, filters, status = {}) {
  const filterKey = stableTradeFilterKey(filters);
  if (filterKey !== appState.stableTradeFilterKey) {
    appState.stableTradeFeed.clear();
    appState.stableTradeFilterKey = filterKey;
    appState.latestTradeSnapshotAt = 0;
  }
  const now = Date.now();
  restoreStableTradeFeed(filterKey, now);
  const snapshotAt = Date.parse(status.last_successful_refresh || "") || 0;
  if (snapshotAt && snapshotAt < appState.latestTradeSnapshotAt) {
    return [...appState.stableTradeFeed.values()].map(entry => entry.trade);
  }
  appState.latestTradeSnapshotAt = Math.max(appState.latestTradeSnapshotAt, snapshotAt);
  const seen = new Set();
  incoming.forEach((trade) => {
    const id = String(trade.id);
    seen.add(id);
    appState.stableTradeFeed.set(id, {
      trade: {
        ...trade,
        isRefreshPending: false,
        candidateState: trade.candidateState || "QUALIFIED",
      },
      lastSeenAt: now,
    });
  });
  for (const [id, entry] of appState.stableTradeFeed) {
    const eventAt = Date.parse(
      entry.trade.event_date_et
      || entry.trade.event_start_time
      || entry.trade.resolution_time
      || "",
    );
    const expired = Number.isFinite(eventAt) && eventAt <= now;
    if (
      expired
      || (!seen.has(id) && now - entry.lastSeenAt > TRADE_DISAPPEARANCE_GRACE_MS)
    ) {
      appState.stableTradeFeed.delete(id);
      continue;
    }
    if (!seen.has(id)) {
      entry.trade = {
        ...entry.trade,
        isRefreshPending: true,
        candidateState: "REVIEWING",
      };
    }
  }
  persistStableTradeFeed(filterKey);
  return [...appState.stableTradeFeed.values()].map(entry => entry.trade);
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

function recommendedBetMarkup(amount, units, shares, variant = "") {
  return `
    <span class="trade-bet-size ${variant}">
      <strong>${escapeHtml(formatOptionalMoney(amount))}</strong>
      <em>${escapeHtml(formatShares(shares))} shares</em>
    </span>
  `;
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
  const eventTime = formatScheduledClock(card.event_time);
  const sportLeagueLabel = [...new Map(
    [trade.category, trade.league]
      .filter(Boolean)
      .map((label) => [String(label).trim().toLowerCase(), String(label).trim()])
  ).values()].join(" · ") || "Sports";
  const amountTooltip = number(betAmount) === null
    ? "Trader active exposure unavailable"
    : `Trader active exposure: ${formatMoney(betAmount)}`;
  const relativeTooltip = number(relativeSize) === null
    ? "Relative bet size unavailable"
    : `${formatRelativeSize(relativeSize)} the trader's normal position size`;
  const hitRateText = number(categoryHitRate) === null ? "N/A" : formatPercent(categoryHitRate, 2);
  return `
    <article class="trade-card ${selected ? "selected" : ""} ${trade.isHidden ? "hidden-trade" : ""} ${trade.isRefreshPending ? "refresh-pending" : ""} ${trade.isOfficialTracked ? "official-trade" : ""} ${trade.isVisualPreview ? "visual-preview-trade" : ""}" role="button" tabindex="0" data-testid="trade-card" data-trade-id="${escapeHtml(trade.id)}" aria-pressed="${selected}" aria-label="Open details for ${escapeHtml(trade.event_title || trade.market_title)}, ${escapeHtml(trade.outcome)}">
      <span class="trade-identity">
        <span class="trade-score-cluster"><span class="trade-score ${confidenceClass(trade.confidence_score)}"><strong>${escapeHtml(trade.confidence_score)}</strong></span>${personalExposureWarning(trade)}${trade.isHidden ? '<span class="hidden-badge">Hidden</span>' : ""}</span>
        <span class="trade-event-copy">
          ${trade.isOfficialTracked ? '<span class="official-play-label"><i class="ph ph-lock-key" aria-hidden="true"></i>Official · stake locked</span>' : ""}
          ${trade.isOfficialTracked && !trade.officialLiveQualified ? '<span class="official-live-status caution"><i class="ph ph-waveform" aria-hidden="true"></i>Live signal changed · official bet remains tracked</span>' : ""}
          ${trade.isOfficialTracked && trade.officialLiveQualified ? '<span class="official-live-status"><i class="ph ph-waveform" aria-hidden="true"></i>Still qualifies live</span>' : ""}
          ${trade.isRefreshPending ? '<span class="refresh-pending-label"><i class="ph ph-eye" aria-hidden="true"></i>No longer qualified · monitoring</span>' : ""}
          <span class="trade-kicker"><i class="ph ${sportIcon(trade.category)}" aria-hidden="true"></i>${escapeHtml(sportLeagueLabel)}${trade.isVisualPreview ? '<em class="visual-preview-badge">Design preview</em>' : ""}</span>
          <span class="research-badges">${researchBadges(trade)}${trade.hasContradictingSharps ? `<small>${trade.rawAgreeingSharpCount || 0} For / ${trade.rawContradictingSharpCount || 0} Against</small>` : ""}</span>
          <strong class="trade-event">${escapeHtml(trade.event_title || trade.market_title)}</strong>
          <span class="trade-market">${escapeHtml(humanizeMarketType(trade.sports_market_type))}</span>
        </span>
      </span>
      <span class="trade-decision">
        <span class="trade-metrics-row">
          ${tradeMetricChip("ph-calendar-blank", eventTime, "Scheduled event start in Eastern Time", "time")}
          ${tradeMetricChip("ph-bag", formatOptionalMoney(betAmount, true), amountTooltip)}
          ${tradeMetricChip("ph-ticket", formatOptionalCents(traderEntry), "Tracked Sharp average entry price")}
          ${slippageMetricChip(slippage)}
          ${tradeMetricChip("ph-gauge", formatRelativeSize(relativeSize), relativeTooltip)}
          ${tradeMetricChip("ph-target", hitRateText, "Adjusted trader hit rate in this category")}
        </span>
        <span class="trade-selection">
          <span class="trade-pick"><strong>${escapeHtml(trade.outcome)}</strong></span>
          ${recommendedBetMarkup(recommendedAmount, recommendedUnits, recommendedShares)}
          ${executionToolbar(trade)}
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
  const preferredBook = safeStorage.getItem("iconbets-personal-sportsbook") || "Polymarket";
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
  const preferredBook = sportsbook?.value || safeStorage.getItem("iconbets-personal-sportsbook") || "Polymarket";
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
    safeStorage.setItem("iconbets-personal-sportsbook", document.getElementById("personal-sportsbook").value);
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
    const shadow = String(wallet.registry_status || "").toUpperCase() === "RESEARCH_SHADOW";
    const category = (wallet.top_category_ids || []).join(", ") || "Top category unresolved";
    const categoryWeight = number(wallet.category_weight);
    const weight = `${(categoryWeight === null ? 0.5 : categoryWeight).toFixed(1)}x model weight`;
    return `
    <a class="supporter-row ${wallet.is_lead_sharp ? "lead-sharp" : "supporting-sharp"}" href="${escapeHtml(wallet.wallet_profile_url || "#")}" target="_blank" rel="noopener noreferrer">
      <span class="supporter-avatar"><i class="ph ph-user" aria-hidden="true"></i></span>
      <span><strong>${escapeHtml(wallet.wallet_label)}${shadow ? ' · SHADOW' : ""}</strong><small>${escapeHtml(`${role} | ${category} | ${weight}${wallet.two_sided_status && wallet.two_sided_status !== "CLEAN_DIRECTIONAL" ? ` | ${wallet.two_sided_status.replaceAll("_", " ")}` : ""}`)}</small></span>
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
      <span class="detail-selection-copy"><strong>${escapeHtml(trade.outcome)}</strong></span>
      ${recommendedBetMarkup(
        card.recommended_amount ?? recommendation.recommended_amount,
        card.recommended_units ?? recommendation.recommended_units,
        card.recommended_shares ?? recommendation.recommended_shares,
        "detail-bet-size",
      )}
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
  const selectedExecution = bestExecutionOption(trade);
  const executableEntryLabel = selectedExecution
    ? executionComparisonPrice(selectedExecution)
    : formatOptionalCents(currentPrice);
  panel.innerHTML = `
    <div class="mobile-detail-sheet-header">
      <span aria-hidden="true"></span>
      <button type="button" data-mobile-detail-close aria-label="Close selected trade details"><i class="ph ph-x" aria-hidden="true"></i></button>
    </div>
    <div class="detail-header">
      <span class="score-badge large ${confidenceClass(trade.confidence_score)}">${escapeHtml(trade.confidence_score)}</span>
      <div class="detail-title-copy"><p>${escapeHtml(trade.category || "Sports")} · ${escapeHtml(trade.league || "Market")}</p><h2>${escapeHtml(trade.event_title || trade.market_title)}</h2><span>${escapeHtml(humanizeMarketType(trade.sports_market_type))} · ${escapeHtml(trade.event_time_et || "Time unavailable")}</span></div>
      <span class="detail-header-actions">${trade.isVisualPreview ? "" : `${personalExposureWarning(trade)}<button class="trade-pin-action ${trade.isPinnedByCurrentUser ? "active" : ""}" id="detail-pin-action" type="button" aria-label="${trade.isPinnedByCurrentUser ? "Unpin this trade from" : "Pin this trade to"} your Whiteboard"><i class="ph ${trade.isPinnedByCurrentUser ? "ph-push-pin-fill" : "ph-push-pin"}" aria-hidden="true"></i></button><button class="trade-hide-action" id="detail-hide-action" type="button" aria-label="${trade.isHidden ? "Restore" : "Hide"} this trade"><i class="ph ${trade.isHidden ? "ph-arrow-counter-clockwise" : "ph-eye-slash"}" aria-hidden="true"></i></button><button class="tracker-quick-action" id="detail-track-action" type="button" aria-label="Track this personal trade"><i class="ph ph-plus" aria-hidden="true"></i></button>`}</span>
      <span class="live-price"><small>Executable entry</small><strong>${escapeHtml(executableEntryLabel)}</strong><em>${escapeHtml(trade.agreeing_wallet_count + " Sharp" + (trade.agreeing_wallet_count === 1 ? "" : "s"))}</em></span>
    </div>
    ${trade.isOfficialTracked ? `
      <section class="official-play-notice">
        <span><i class="ph ph-lock-key" aria-hidden="true"></i><strong>Official play locked</strong></span>
        <p>The original ${escapeHtml(formatOptionalMoney(card.recommended_amount ?? recommendation.recommended_amount))} stake and ${escapeHtml(String(trade.confidence_score))} confidence are frozen when the play enters the 30-minute tracking window. Live dashboard pricing and Sharp status continue to refresh.</p>
        <small>${trade.officialLiveQualified ? "Live status: still qualifies for a new entry." : "Live status: no longer qualifies as a new entry right now."}</small>
      </section>
    ` : ""}
    ${detailSelectionPanel(trade)}
    ${executionComparisonLadder(trade)}
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
    <footer class="mobile-trade-detail-actions">
      <button type="button" data-mobile-detail-hide><i class="ph ph-eye-slash" aria-hidden="true"></i><span>Hide</span></button>
      <button type="button" data-mobile-detail-track><i class="ph ph-plus-circle" aria-hidden="true"></i><span>Track</span></button>
    </footer>
  `;
  panel.querySelectorAll("[data-mobile-detail-close]").forEach((button) => button.addEventListener("click", closeMobileTradeDetail));
  panel.querySelector("[data-mobile-detail-track]")?.addEventListener("click", () => openPersonalTracker(trade));
  panel.querySelector("[data-mobile-detail-hide]")?.addEventListener("click", () => {
    if (trade.isVisualPreview) closeMobileTradeDetail();
    else if (trade.isHidden) restoreHiddenTrade(trade.hiddenRecordId);
    else hideTrade(trade.id);
  });
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
    if (trade.isVisualPreview) {
      drawLineChart(
        document.getElementById("price-chart"),
        trade.demoPriceHistory || [],
        { format: formatCents },
      );
    } else {
      loadPriceHistory(trade.clob_token_id, currentPrice, button.dataset.priceRange);
    }
  }));
  if (trade.isVisualPreview) {
    drawLineChart(
      document.getElementById("price-chart"),
      trade.demoPriceHistory || [],
      { format: formatCents },
    );
    const exposure = document.getElementById("personal-exposure-detail");
    if (exposure) exposure.innerHTML = '<p class="personal-exposure-empty"><i class="ph ph-shield-check"></i>Preview data is isolated from Personal Tracker.</p>';
  } else {
    loadPriceHistory(trade.clob_token_id, currentPrice);
    loadPersonalExposureDetails(trade.id);
    loadTradeEdgeEvidence(trade);
  }
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
  ctx.strokeStyle = options.gridColor || "rgba(195, 183, 238, 0.10)";
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i += 1) {
    const lineY = pad + (i / 3) * (height - pad * 1.7);
    ctx.beginPath(); ctx.moveTo(pad, lineY); ctx.lineTo(width - pad / 2, lineY); ctx.stroke();
  }
  const gradient = ctx.createLinearGradient(0, pad, 0, height - pad);
  gradient.addColorStop(0, options.areaColor || "rgba(19, 183, 237, 0.2)");
  gradient.addColorStop(1, options.areaFade || "rgba(105, 199, 232, 0)");
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
  ctx.fillStyle = options.labelColor || "#81798f";
  ctx.font = `${11 * window.devicePixelRatio}px ${options.fontFamily || '"Roboto Condensed"'}`;
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

function closeMobileTradeDetail() {
  document.body.classList.remove("mobile-trade-detail-open");
  const backdrop = document.getElementById("mobile-trade-detail-backdrop");
  if (backdrop) backdrop.hidden = true;
  const panel = document.getElementById("trade-detail");
  panel?.removeAttribute("aria-modal");
}

function openMobileTradeDetail() {
  if (window.innerWidth > 860) return;
  document.body.classList.add("mobile-trade-detail-open");
  const backdrop = document.getElementById("mobile-trade-detail-backdrop");
  if (backdrop) backdrop.hidden = false;
  const panel = document.getElementById("trade-detail");
  if (!panel) return;
  panel.setAttribute("aria-modal", "true");
  panel.scrollTop = 0;
  window.requestAnimationFrame(() => panel.querySelector("[data-mobile-detail-close]")?.focus({ preventScroll: true }));
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
  if (scroll && window.innerWidth <= 860) openMobileTradeDetail();
  else if (scroll && window.innerWidth < 980) document.getElementById("trade-detail").scrollIntoView({ behavior: "smooth", block: "start" });
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

function renderTradesPayload(payload, filters, list) {
  const incomingTrades = payload.data || [];
  const mergedTrades = mergeOfficialTrackedTrades(
    incomingTrades,
    payload.officialTracked || [],
  );
  const sourceTrades = stabilizeTradeFeed(
    mergedTrades,
    filters,
    payload.status || {},
  );
  annotateExecutionMovements(sourceTrades);
  appState.trades = applyClientTradeFilters(sourceTrades, filters);
  updateTradeSummary(payload, sourceTrades, appState.trades);
  if (payload.bankroll) applySizingBankroll(payload.bankroll);
  updateGlobalStatus(payload.status);
  document.getElementById("hidden-trades-count").textContent = String(payload.hiddenCount || 0);
  document.getElementById("whiteboard-count").textContent = String(payload.whiteboardCount || 0);
  document.getElementById("trades-tab-count").textContent = String(appState.trades.length);
  document.getElementById("trade-result-count").textContent = `${appState.trades.length} Pick${appState.trades.length === 1 ? "" : "s"}`;
  document.getElementById("trade-freshness").textContent = payload.fastMode
    ? "Loading live prices in the background"
    : `Live book checked ${formatDateTime(payload.status?.last_successful_refresh, "now")}`;
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
    list.innerHTML = tradeMonitoringWorkspace(payload, sourceTrades, appState.trades);
    document.getElementById("trade-detail").innerHTML = tradeModelActivityPanel(payload, sourceTrades, appState.trades);
    document.getElementById("empty-clear-trade-filters")?.addEventListener("click", () => document.getElementById("clear-trade-filters")?.click());
    return;
  }
  const selectedParam = new URLSearchParams(window.location.search).get("selected");
  if (!appState.trades.some((trade) => trade.id === appState.selectedTradeId)) {
    appState.selectedTradeId = appState.trades.some((trade) => trade.id === selectedParam) ? selectedParam : appState.trades[0].id;
  }
  syncTradeRows(list, appState.trades);
  selectTrade(appState.selectedTradeId);
}

async function loadTrades({ initial = false } = {}) {
  if (appState.tradeRequestInFlight) {
    appState.tradeRefreshQueued = true;
    return;
  }
  appState.tradeRequestInFlight = true;
  appState.tradeRefreshQueued = false;
  const requestSequence = ++appState.tradeRequestSequence;
  const list = document.getElementById("trade-list");
  const filters = readTradeControls();
  updateActiveFilterCount();
  updateTradeUrl(filters);
  const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== "" && value !== false));
  const cacheKey = pagePayloadCacheKey("trades", query.toString());
  const cachedPayload = initial
    ? readPagePayloadCache(cacheKey) || readPagePayloadCache(latestPagePayloadCacheKey("trades"))
    : null;
  if (cachedPayload) renderTradesPayload(cachedPayload, filters, list);
  const requestQuery = new URLSearchParams(query);
  if (initial && !cachedPayload) requestQuery.set("fast", "1");
  try {
    const payload = await fetchJson(`/api/trades-to-play?${requestQuery.toString()}`);
    if (requestSequence !== appState.tradeRequestSequence) return;
    cachePagePayload("trades", cacheKey, payload);
    renderTradesPayload(payload, filters, list);
  } catch (error) {
    if (requestSequence !== appState.tradeRequestSequence) return;
    if (cachedPayload) return;
    updateTradeSummary({}, [], []);
    list.innerHTML = errorState(error.message);
    document.getElementById("trade-detail").innerHTML = `<div class="professional-empty-state error-state"><span class="activity-icon"><i class="ph ph-warning-circle" aria-hidden="true"></i></span><div><span class="page-kicker">Connection interrupted</span><h2>Live model data is temporarily unavailable</h2><p>${escapeHtml(error.message)}. Your filters and saved settings are unchanged.</p></div><button class="button ghost compact" type="button" onclick="window.location.reload()"><i class="ph ph-arrows-clockwise" aria-hidden="true"></i>Retry connection</button></div>`;
  } finally {
    appState.tradeRequestInFlight = false;
    if (appState.tradeRefreshQueued && !appState.paused) {
      appState.tradeRefreshQueued = false;
      window.setTimeout(loadTrades, 0);
    } else if (initial && !cachedPayload && !appState.paused) {
      window.setTimeout(loadTrades, 0);
    }
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
  safeStorage.setItem("iconbets-trades-workspace-tab", appState.workspaceTab);
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
    safeStorage.setItem("iconbets-saved-trade-view", JSON.stringify(readTradeControls()));
    document.getElementById("saved-filter-status").textContent = "Saved in this browser";
    showToast("Trade view saved", "success");
  });
  document.getElementById("load-trade-view").addEventListener("click", () => {
    try {
      const saved = JSON.parse(safeStorage.getItem("iconbets-saved-trade-view") || "null");
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
  document.getElementById("mobile-trade-detail-backdrop")?.addEventListener("click", closeMobileTradeDetail);
  window.addEventListener("resize", () => {
    if (window.innerWidth > 860) closeMobileTradeDetail();
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
    closeMobileTradeDetail();
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
  const requestedTab = new URLSearchParams(window.location.search).get("tab") || safeStorage.getItem("iconbets-trades-workspace-tab") || "trades";
  selectWorkspaceTab(requestedTab, { syncUrl: false });
  if (validateSharePriceControls()) loadTrades({ initial: true });
  runWhenIdle(() => {
    loadPersonalPnl();
    if (requestedTab === "positions") loadPersonalPositions("open");
    if (requestedTab === "closed") loadPersonalPositions("closed");
  });
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
    const wallets = await fetchJson("/api/wallets?view=all");
    setOptions(document.getElementById("position-wallet"), wallets.data.map((wallet) => wallet.label), "All wallets");
  } catch {}
  document.getElementById("position-search").addEventListener("input", debounce(() => { appState.pageNumber = 1; loadPositions(); }));
  ["position-wallet", "position-sport", "position-league", "position-market", "position-sort"].forEach((id) => document.getElementById(id).addEventListener("change", () => { appState.pageNumber = 1; loadPositions(); }));
  loadPositions();
}

function legacyWalletCard(wallet) {
  const sync = wallet.sync_status || wallet.status;
  const unit = number(wallet.base_unit);
  const shadow = String(wallet.registry_status || "").toUpperCase() === "RESEARCH_SHADOW";
  const validation = wallet.wallet_validation || {};
  const forensics = wallet.wallet_forensics || {};
  const secondaryForensics = forensics.secondary_category_forensics || {};
  const hasForensics = Boolean(forensics.version);
  const distribution = validation.relative_size_distribution || {};
  const proposedBaseline = validation.proposed_baseline || {};
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
      <div class="wallet-card-head"><span class="wallet-avatar"><i class="ph ph-wallet" aria-hidden="true"></i></span><div><h2>${escapeHtml(wallet.label)}</h2><span class="status-label ${escapeHtml(sync)}">${escapeHtml(sync)}</span>${shadow ? '<span class="status-label shadow">SHADOW</span>' : ""}${hasForensics ? '<span class="status-label">MLB AUDITED</span>' : ""}</div></div>
      <button class="address-copy" type="button" data-copy-address="${escapeHtml(wallet.address)}"><span>${escapeHtml(wallet.display_address || wallet.address)}</span><i class="ph ph-copy" aria-hidden="true"></i></button>
      <div class="wallet-stats"><div><span>Open positions</span><strong>${wallet.open_position_count ?? 0}</strong></div><div><span>History events</span><strong>${wallet.historical_position_count ?? 0}</strong></div><div><span>${wallet.provisional_unit ? "Provisional unit" : "Base unit"}</span><strong>${wallet.base_unit ? formatMoney(wallet.base_unit) : "Estimating"}</strong></div></div>
      ${wallet.provisional_unit ? `<div class="wallet-provisional-unit">PROVISIONAL UNIT · ${escapeHtml(formatMoney(wallet.base_unit, 0))}</div>` : ""}
      <div class="wallet-sync wallet-meta">${[
        walletMeta("Registry status", shadow ? "Research / Shadow" : wallet.registry_status || "Active"),
        walletMeta("Lead eligible", wallet.lead_sharp_eligible === false ? "No" : "Yes"),
        walletMeta("Supporting eligible", wallet.supporting_sharp_eligible === false ? "No" : `Yes · ${Number(wallet.supporting_weight || 0.5).toFixed(1)}x`),
        walletMeta("Standard originator", wallet.standard_originator_eligible === false ? "No" : "Yes"),
        walletMeta("Top category", wallet.top_category_display || wallet.top_category || "Awaiting classification"),
        walletMeta("Sub-top categories", (wallet.sub_top_categories || []).join(", ") || "None configured"),
        walletMeta("Sub-category record", subCategoryRecord),
        walletMeta("Category record", categoryRecord),
        walletMeta("Adjusted hit rate", number(categoryStats.adjusted_hit_rate) === null ? "Awaiting settled history" : formatPercent(categoryStats.adjusted_hit_rate)),
        walletMeta("Category P/L", number(categoryStats.profit_loss) === null ? "Awaiting settled history" : formatMoney(categoryStats.profit_loss)),
        walletMeta("Category ROI", number(categoryStats.roi) === null ? "Unavailable" : formatPercent(categoryStats.roi)),
        walletMeta("Win rate", number(categoryStats.raw_hit_rate) === null ? "Unavailable" : formatPercent(categoryStats.raw_hit_rate)),
        walletMeta("Positive P/L rate", number(categoryStats.positive_pnl_rate) === null ? "Unavailable" : formatPercent(categoryStats.positive_pnl_rate)),
        walletMeta("Maximum drawdown", number(categoryStats.maximum_drawdown) === null ? "Unavailable" : formatMoney(categoryStats.maximum_drawdown)),
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
        walletMeta("Forensic coverage", hasForensics ? `${forensics.markets || 0} markets / ${forensics.events || 0} events` : null),
        walletMeta("MLB turnover ROI", hasForensics && number(forensics.gross_turnover_roi) !== null ? formatPercent(forensics.gross_turnover_roi) : null),
        walletMeta("MLB realized P/L", hasForensics && number(forensics.realized_pnl_usd) !== null ? formatMoney(forensics.realized_pnl_usd) : null),
        walletMeta("Clean directional", hasForensics ? `${forensics.clean_directional_markets || 0} markets / ${formatPercent(forensics.clean_directional_roi)}` : null, "Only market-level net exposure with less than 10% opposing exposure is classified as clean directional."),
        walletMeta("Hedged / two-sided", hasForensics ? `${(forensics.minor_hedge_markets || 0) + (forensics.material_hedge_markets || 0)} / ${forensics.two_sided_markets || 0}` : null),
        walletMeta("Event portfolio conflicts", hasForensics && wallet.event_portfolio_netting_required ? `${forensics.events_with_both_moneyline_teams || 0} dual moneylines / ${forensics.events_with_both_spread_teams || 0} dual spreads` : null, "These markets are netted together before Sportsmaster can support or originate a recommendation."),
        walletMeta("Totals / middling evidence", hasForensics && wallet.event_portfolio_netting_required ? `${forensics.events_with_over_and_under || 0} two-sided totals / ${forensics.events_with_total_middle_corridor || 0} middle corridors` : null),
        walletMeta("Markets per active day", hasForensics ? `Median ${forensics.median_markets_per_active_day || 0} / P90 ${forensics.p90_markets_per_active_day || 0}` : null),
        walletMeta("Measured unit evidence", hasForensics ? `${formatMoney(forensics.measured_unit_usd)} / ${String(forensics.unit_confidence || "").toUpperCase()} confidence` : null),
        walletMeta("Clean position range", hasForensics ? `P25 ${formatMoney(forensics.clean_net_p25_usd)} / Median ${formatMoney(forensics.clean_net_median_usd)} / P75 ${formatMoney(forensics.clean_net_p75_usd)}` : null),
        walletMeta("Automation", hasForensics ? String(forensics.automation_classification || "").replaceAll("_", " ") : null),
        walletMeta("Directional behavior", hasForensics ? String(forensics.directional_classification || "").replaceAll("_", " ") : null),
        walletMeta("Sample execution", hasForensics ? `${forensics.fill_sample_count || 0} fills / median ${forensics.median_fills_per_market || 0} per market` : null),
        walletMeta("Opposite-side timing", hasForensics ? (number(forensics.median_opposite_side_delay_minutes) === null ? "Unavailable from BUY-only export" : `Median ${forensics.median_opposite_side_delay_minutes} min / ${formatPercent(forensics.opposite_side_within_five_minutes_rate || 0)} within 5 min`) : null),
        walletMeta("Peak activity (ET)", hasForensics ? forensics.peak_fill_window_et : null),
        walletMeta("CLV", hasForensics ? "Unavailable - not fabricated" : null),
        walletMeta("Secondary category audit", secondaryForensics.category ? `${secondaryForensics.category} / ${secondaryForensics.markets || 0} markets` : null),
        walletMeta("Secondary clean ROI", secondaryForensics.category && number(secondaryForensics.clean_directional_roi) !== null ? `${formatPercent(secondaryForensics.clean_directional_roi)} / ${String(secondaryForensics.signal_policy || "RESEARCH_ONLY").replaceAll("_", " ")}` : null, "A profitable hedged portfolio is not automatically a profitable copyable directional signal."),
        walletMeta("Synced fills", wallet.requires_fill_aggregation ? wallet.deduplicated_fill_count : null),
        walletMeta("Avg. fills / position", wallet.requires_fill_aggregation ? wallet.average_fills_per_aggregated_position : null),
        walletMeta("Settled positions", wallet.requires_fill_aggregation ? wallet.settled_aggregated_position_count : null),
        walletMeta("Fill backfill", wallet.requires_fill_aggregation ? wallet.historical_backfill_status : null),
        walletMeta("Directional sample", shadow ? validation.eligible_directional_sample ?? 0 : null),
        walletMeta("Hedged / two-sided", shadow ? `${validation.hedged_sample ?? 0} / ${validation.two_sided_sample ?? 0}` : null),
        walletMeta("Dust / test", shadow ? validation.dust_test_sample ?? 0 : null),
        walletMeta("Median meaningful position", shadow ? (number(validation.median_meaningful_position) === null ? "Unavailable" : formatMoney(validation.median_meaningful_position)) : null),
        walletMeta("Relative-size distribution", shadow ? (number(distribution.median) === null ? "Unavailable" : `P25 ${formatUnits(distribution.p25 / wallet.base_unit)} · Median ${formatUnits(distribution.median / wallet.base_unit)} · P75 ${formatUnits(distribution.p75 / wallet.base_unit)} · P90 ${formatUnits(distribution.p90 / wallet.base_unit)}`) : null),
        walletMeta("Baseline proposal", shadow ? String(proposedBaseline.status || "INSUFFICIENT_SAMPLE").replaceAll("_", " ") : null, "A proposed baseline never changes production sizing without admin approval."),
        walletMeta("Exchange CLV", shadow ? "Unavailable until measured" : null),
        walletMeta("Composite CLV", shadow ? "Unavailable until measured" : null),
      ].join("")}</div>
      <div class="wallet-sync"><span>Last successful sync</span><strong>${formatDateTime(wallet.last_synced_at, "Not available")}</strong></div>
      ${wallet.message ? `<p class="wallet-warning">${escapeHtml(wallet.message)}</p>` : ""}
      <a class="button ghost" href="${escapeHtml(wallet.profile_url || "#")}" target="_blank" rel="noopener noreferrer">View on Polymarket <i class="ph ph-arrow-up-right" aria-hidden="true"></i></a>
    </article>
  `;
}

async function legacyLoadWallets() {
  const params = new URLSearchParams({ q: document.getElementById("wallet-search").value, status: document.getElementById("wallet-status").value, sort: document.getElementById("wallet-sort").value });
  const grid = document.getElementById("wallet-grid");
  try {
    const payload = await fetchJson(`/api/wallets?${params.toString()}`);
    updateGlobalStatus(payload.status);
    document.getElementById("wallet-result-count").textContent = `${payload.total} wallet${payload.total === 1 ? "" : "s"}`;
    grid.innerHTML = payload.data.length ? payload.data.map(legacyWalletCard).join("") : emptyState("No wallets match", "Try another name, address, or sync status.");
    grid.querySelectorAll("[data-copy-address]").forEach((button) => button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(button.dataset.copyAddress);
      showToast("Public wallet address copied", "success");
    }));
  } catch (error) {
    grid.innerHTML = errorState(error.message);
  }
}

function legacyBindWallets() {
  document.getElementById("wallet-search").addEventListener("input", debounce(legacyLoadWallets));
  ["wallet-status", "wallet-sort"].forEach((id) => document.getElementById(id).addEventListener("change", legacyLoadWallets));
  legacyLoadWallets();
}

function walletRosterMetric(label, value, icon, tone = "") {
  return `<div class="wallet-roster-metric ${tone}"><i class="ph ${icon}" aria-hidden="true"></i><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function walletCard(wallet) {
  const summary = wallet.roster_summary || {};
  const active = Boolean(wallet.is_active_sharp);
  const clv = number(summary.clv_probability_points);
  const clvValue = clv === null ? "Collecting" : `${clv >= 0 ? "+" : ""}${(clv * 100).toFixed(2)} pts`;
  const clvTone = clv === null ? "collecting" : (clv >= 0 ? "positive" : "negative");
  const sync = String(wallet.sync_status || wallet.status || "pending").toLowerCase();
  const address = wallet.short_address || wallet.display_address || wallet.address || "";
  const roi = number(summary.roi);
  return `
    <article class="wallet-card wallet-roster-card ${active ? "is-active-sharp" : "is-hidden-wallet"}">
      <header class="wallet-roster-card-head">
        <div class="wallet-identity">
          ${providerLogoMarkup({ name: "Polymarket", logoUrl: "https://polymarket.com/icons/favicon-32x32.png" }, "Polymarket")}
          <div><span>POLYMARKET SHARP</span><h2>${escapeHtml(wallet.label)}</h2></div>
        </div>
        <div class="wallet-card-badges"><strong class="wallet-sport-badge">${escapeHtml(summary.sport || "MLB")}</strong><span class="wallet-sync-dot ${escapeHtml(sync)}" title="${escapeHtml(sync)}"></span></div>
      </header>
      <div class="wallet-roster-metrics">
        ${walletRosterMetric("Unit size", number(summary.unit_size) === null ? "Estimating" : formatMoney(summary.unit_size, 0), "ph-coins")}
        ${walletRosterMetric("ROI", roi === null ? "Unavailable" : formatPercent(roi), "ph-trend-up", roi === null ? "" : (roi >= 0 ? "positive" : "negative"))}
        ${walletRosterMetric("Win rate", number(summary.win_rate) === null ? "Unavailable" : formatPercent(summary.win_rate), "ph-target")}
        ${walletRosterMetric("Tracked plays", String(summary.play_count || 0), "ph-receipt")}
      </div>
      <div class="wallet-clv-band ${clvTone}">
        <div><i class="ph ph-chart-line-up" aria-hidden="true"></i><span>Polymarket CLV<small>${escapeHtml(summary.clv_source || "Provider closing price")}</small></span></div>
        <div><strong>${escapeHtml(clvValue)}</strong><small>${summary.clv_sample ? `${summary.clv_sample} measured` : "Forward collection active"}</small></div>
      </div>
      <footer class="wallet-roster-footer">
        <button class="wallet-address-button" type="button" data-copy-address="${escapeHtml(wallet.address)}"><span>${escapeHtml(address)}</span><i class="ph ph-copy" aria-hidden="true"></i></button>
        <a href="${escapeHtml(wallet.profile_url || "#")}" target="_blank" rel="noopener noreferrer">Open profile <i class="ph ph-arrow-up-right" aria-hidden="true"></i></a>
      </footer>
    </article>
  `;
}

let walletRosterView = "active";

async function loadWallets() {
  const search = document.getElementById("wallet-search");
  const status = document.getElementById("wallet-status");
  const sort = document.getElementById("wallet-sort");
  const params = new URLSearchParams({
    view: walletRosterView,
    q: search?.value || "",
    status: status?.value || "",
    sort: sort?.value || "label-asc",
  });
  const grid = document.getElementById("wallet-grid");
  try {
    const payload = await fetchJson(`/api/wallets?${params.toString()}`);
    updateGlobalStatus(payload.status);
    document.getElementById("wallet-active-count").textContent = payload.active_total;
    document.getElementById("wallet-active-tab-count").textContent = payload.active_total;
    document.getElementById("wallet-hidden-tab-count").textContent = payload.hidden_total;
    document.getElementById("wallet-result-count").textContent = `${payload.total} wallet${payload.total === 1 ? "" : "s"}`;
    document.getElementById("wallet-section-eyebrow").textContent = walletRosterView === "active" ? "ACTIVE MODEL ROSTER" : "PRESERVED RESEARCH";
    document.getElementById("wallet-section-title").textContent = walletRosterView === "active" ? "Three MLB Sharps" : "Hidden Wallets";
    grid.classList.toggle("is-hidden-view", walletRosterView === "hidden");
    grid.innerHTML = payload.data.length ? payload.data.map(walletCard).join("") : emptyState(walletRosterView === "hidden" ? "No hidden wallets match" : "Active roster unavailable", walletRosterView === "hidden" ? "Try another wallet name or status." : "The three approved Sharp addresses were not found in the registry.");
    grid.querySelectorAll("[data-copy-address]").forEach((button) => button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(button.dataset.copyAddress);
      showToast("Public wallet address copied", "success");
    }));
  } catch (error) {
    grid.innerHTML = errorState(error.message);
  }
}

function bindWallets() {
  document.querySelectorAll("[data-wallet-view]").forEach((button) => button.addEventListener("click", () => {
    walletRosterView = button.dataset.walletView || "active";
    document.querySelectorAll("[data-wallet-view]").forEach((tab) => {
      const selected = tab === button;
      tab.classList.toggle("is-active", selected);
      tab.setAttribute("aria-selected", String(selected));
    });
    document.getElementById("wallet-hidden-toolbar").hidden = walletRosterView !== "hidden";
    loadWallets();
  }));
  document.getElementById("wallet-search")?.addEventListener("input", debounce(loadWallets));
  ["wallet-status", "wallet-sort"].forEach((id) => document.getElementById(id)?.addEventListener("change", loadWallets));
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
    const wallets = await fetchJson("/api/wallets?view=all");
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

function probabilityToAmerican(probability) {
  const parsed = number(probability);
  if (parsed === null || parsed <= 0 || parsed >= 1) return null;
  return parsed < 0.5
    ? Math.round((100 * (1 - parsed)) / parsed)
    : Math.round((-100 * parsed) / (1 - parsed));
}

function formatAmericanOdds(value) {
  const parsed = number(value);
  if (parsed === null) return "Unavailable";
  return `${parsed > 0 ? "+" : ""}${Math.round(parsed)}`;
}

function oddsDifference(entryOdds, closingOdds) {
  const entry = number(entryOdds);
  const close = number(closingOdds);
  if (entry === null || close === null) return "Unavailable";
  const difference = Math.round(entry - close);
  return `${difference > 0 ? "+" : ""}${difference} odds`;
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
  const entryOdds = clv.entry_native_odds
    ?? row.snapshot?.provider_display_odds
    ?? probabilityToAmerican(clv.entry_price);
  const closingOdds = probabilityToAmerican(clv.closing_effective_price);
  const entryMarker = Math.max(1, Math.min(99, (number(clv.entry_price) || 0) * 100));
  const closeMarker = Math.max(1, Math.min(99, (number(clv.closing_effective_price) || 0) * 100));
  return `<details class="clv-details ${tone}">
    <summary><strong>${escapeHtml(formatClvPercent(pct))} CLV</strong><small>${escapeHtml(formatClvCents(clv.clv_cents))}</small></summary>
    <span><b>Provider</b>${escapeHtml(clv.provider || "Polymarket")}</span>
    <span><b>Entry odds</b>${escapeHtml(formatAmericanOdds(entryOdds))}</span>
    <span><b>Closing odds</b>${escapeHtml(formatAmericanOdds(closingOdds))}</span>
    <span><b>Odds improvement</b>${escapeHtml(oddsDifference(entryOdds, closingOdds))}</span>
    <span><b>Entry</b>${escapeHtml(formatCents(clv.entry_price))}</span>
    <span><b>Executable close</b>${escapeHtml(formatCents(clv.closing_effective_price))}</span>
    <span><b>Probability CLV</b>${escapeHtml(formatClvCents(clv.clv_probability_points ?? clv.clv_cents))}</span>
    <span><b>Price value CLV</b>${escapeHtml(formatClvPercent(pct))}</span>
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

function trackerSportsbookName(snapshot = {}) {
  const raw = String(snapshot.sportsbook || snapshot.entry_price_source || "Polymarket").trim();
  return raw.toLowerCase().includes("polymarket") ? "Polymarket" : raw.slice(0, 64);
}

function trackerProviderMeta(name = "Polymarket") {
  const normalized = String(name || "Polymarket").toLowerCase().replace(/[^a-z0-9]/g, "");
  if (normalized.includes("novig")) return { name: "NoVIG", logoUrl: "https://cdn.prod.website-files.com/642ae772b9f3360398a9d449/6436d7c4d343f31dbf62d683_favicon.png" };
  if (normalized.includes("prophet")) return { name: "ProphetX", logoUrl: "/static/assets/providers/prophetx.ico" };
  if (normalized.includes("kalshi")) return { name: "Kalshi", logoUrl: "/static/assets/providers/kalshi.png" };
  if (normalized.includes("4cx")) return { name: "4CX", logoUrl: "/static/assets/providers/4cx.png" };
  if (normalized.includes("poly")) return { name: "Polymarket", logoUrl: "https://polymarket.com/icons/favicon-32x32.png" };
  return { name: String(name || "Sportsbook"), logoUrl: "" };
}

function trackerProviderBadge(name, href = "") {
  const meta = trackerProviderMeta(name);
  const content = `${providerLogoMarkup(meta, meta.name)}<span>${escapeHtml(meta.name)}</span>`;
  return href
    ? `<a class="tracker-provider-badge" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer" title="Open ${escapeHtml(meta.name)} market">${content}</a>`
    : `<span class="tracker-provider-badge" title="${escapeHtml(meta.name)}">${content}</span>`;
}

function trackerShortMatchup(value = "") {
  const normalized = String(value || "Market").replace(/\s+(?:versus|at|@)\s+/i, " vs ").replace(/\s+vs\.?\s+/i, " vs ").trim();
  const sides = normalized.split(/\s+vs\s+/i);
  return sides.length === 2 ? `${trackerTeamShort(sides[0])} vs ${trackerTeamShort(sides[1])}` : normalized;
}

function trackerTeamShort(value = "") {
  const team = String(value || "").trim();
  const compound = team.match(/(?:Red Sox|White Sox|Blue Jays|Trail Blazers|Golden Knights|Maple Leafs|Red Wings|Blue Jackets)$/i);
  if (compound) return compound[0];
  const tokens = team.split(/\s+/);
  return tokens.length > 1 ? tokens[tokens.length - 1] : team;
}

function trackerSharpCompact(snapshot = {}) {
  const primary = snapshot.primary_sharp || null;
  if (!primary) return '<span class="sharp-unavailable">—</span>';
  const address = String(primary.wallet_address || "").trim();
  const href = primary.wallet_profile_url || (address ? `https://polymarket.com/profile/${encodeURIComponent(address)}` : "");
  const label = primary.display_name || address || "Sharp";
  const content = `${providerLogoMarkup(trackerProviderMeta("Polymarket"), "Polymarket")}<strong>${escapeHtml(label)}</strong>`;
  return href
    ? `<a class="tracker-sharp-compact" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer" title="Open ${escapeHtml(label)} on Polymarket">${content}</a>`
    : `<span class="tracker-sharp-compact">${content}</span>`;
}

function trackerResultBadge(status = "unresolved") {
  const normalized = String(status || "unresolved").toLowerCase();
  const label = normalized === "won" ? "Won" : normalized === "lost" ? "Lost" : normalized === "push" ? "Push" : normalized === "void" ? "Void" : "Open";
  return `<span class="tracker-result-pill ${escapeHtml(normalized)}">${label}</span>`;
}

function trackerCompactBetLabel(selection = "Selection", market = "", line = null) {
  const side = String(selection || "Selection").trim();
  const normalizedMarket = String(market || "").toLowerCase();
  const compactSide = trackerTeamShort(side);
  if (/money\s*line|moneyline|h2h|(^|\s)ml($|\s)/.test(normalizedMarket)) return `${compactSide} ML`;
  if (/run\s*line|spread|handicap/.test(normalizedMarket)) {
    const numericLine = number(line);
    return numericLine === null ? compactSide : `${compactSide} ${numericLine > 0 ? "+" : ""}${numericLine}`;
  }
  if (/total|over|under/.test(normalizedMarket)) return side;
  return `${trackerTeamShort(side)} ML`;
}

function trackerMobileDetail(label, value, className = "") {
  return `<div class="tracker-mobile-detail ${className}"><span>${escapeHtml(label)}</span><div>${value}</div></div>`;
}

function trackerMobileModelBet(row) {
  const snapshot = row.snapshot || {};
  const sharpSnapshot = row.sharp_snapshot || snapshot.sharp_snapshot || {};
  const primary = sharpSnapshot.primary_sharp || {};
  const providerName = trackerSportsbookName(snapshot);
  const provider = trackerProviderMeta(providerName);
  const marketUrl = snapshot.market_url || snapshot.provider_market_url || row.market_url || "";
  const intended = number(snapshot.intended_entry_price ?? snapshot.current_executable_entry_price);
  const actual = number(snapshot.actual_weighted_entry_price ?? snapshot.effective_entry_price);
  const entry = actual ?? intended ?? number(snapshot.provider_entry_price);
  const displayEntry = snapshot.provider_display_odds || (entry === null ? "—" : formatCents(entry));
  const selection = snapshot.recommended_side || "Selection";
  const market = snapshot.market_type || snapshot.market_kind || snapshot.market_title || snapshot.canonical_market_slug || "";
  const sharpEntry = number(primary.average_entry ?? snapshot.sharp_average_entry_price);
  const sharpStake = number(primary.amount);
  const pnl = number(row.profit_loss);
  const trackedAt = row.settled_at || row.tracked_at || row.created_at;
  const providerIcon = marketUrl
    ? `<a class="tracker-mobile-provider" href="${escapeHtml(marketUrl)}" target="_blank" rel="noopener noreferrer" aria-label="Open ${escapeHtml(provider.name)} market">${providerLogoMarkup(provider, provider.name)}</a>`
    : `<span class="tracker-mobile-provider" title="${escapeHtml(provider.name)}">${providerLogoMarkup(provider, provider.name)}</span>`;
  return `<details class="tracker-mobile-bet">
    <summary>${providerIcon}<strong>${escapeHtml(trackerCompactBetLabel(selection, market, snapshot.market_line))}</strong><b>${escapeHtml(displayEntry)}</b><i class="ph ph-caret-down" aria-hidden="true"></i></summary>
    <div class="tracker-mobile-details">
      ${trackerMobileDetail("Event", `<strong>${escapeHtml(trackerShortMatchup(snapshot.event_title || snapshot.market_title || "Market"))}</strong>`, "wide")}
      ${trackerMobileDetail("Sharp", trackerSharpCompact(sharpSnapshot))}
      ${trackerMobileDetail("Sharp entry", `<strong>${sharpEntry === null ? "—" : escapeHtml(formatCents(sharpEntry))}</strong>`)}
      ${trackerMobileDetail("Sharp stake", `<strong>${sharpStake === null ? "—" : escapeHtml(formatMoney(sharpStake))}</strong>`)}
      ${trackerMobileDetail("Bet", `<strong>${escapeHtml(formatMoney(row.recommended_amount))}</strong>`)}
      ${trackerMobileDetail("Result", trackerResultBadge(row.result || row.status))}
      ${trackerMobileDetail("P&L", `<strong class="${pnl === null ? "" : pnl >= 0 ? "positive" : "negative"}">${pnl === null ? "Open" : escapeHtml(formatMoney(pnl))}</strong>`)}
      ${trackerMobileDetail("Entry CLV", clvCell(row), "wide")}
      ${trackerMobileDetail("Tracked", `<span class="tracker-timestamp">${escapeHtml(formatDateTime(trackedAt))}</span>`, "wide")}
    </div>
  </details>`;
}

function trackerMobilePersonalBet(row) {
  const sharpSnapshot = row.sharp_snapshot || {};
  const primary = sharpSnapshot.primary_sharp || {};
  const provider = trackerProviderMeta(row.sportsbook || "Polymarket");
  const pnl = number(row.profit_loss);
  const status = String(row.status || "unresolved").toLowerCase();
  const active = ["scheduled", "live", "unresolved"].includes(status);
  const providerIcon = row.market_url
    ? `<a class="tracker-mobile-provider" href="${escapeHtml(row.market_url)}" target="_blank" rel="noopener noreferrer" aria-label="Open ${escapeHtml(provider.name)} market">${providerLogoMarkup(provider, provider.name)}</a>`
    : `<span class="tracker-mobile-provider" title="${escapeHtml(provider.name)}">${providerLogoMarkup(provider, provider.name)}</span>`;
  return `<details class="tracker-mobile-bet">
    <summary>${providerIcon}<strong>${escapeHtml(trackerCompactBetLabel(row.selection || "Selection", row.market_title || row.market_type || "", row.market_line ?? row.line))}</strong><b>${escapeHtml(formatCents(row.entry_price))}</b><i class="ph ph-caret-down" aria-hidden="true"></i></summary>
    <div class="tracker-mobile-details">
      ${trackerMobileDetail("Event", `<strong>${escapeHtml(trackerShortMatchup(row.event_title || "Market"))}</strong>`, "wide")}
      ${trackerMobileDetail("Sharp", trackerSharpCompact(sharpSnapshot))}
      ${trackerMobileDetail("Sharp entry", `<strong>${number(primary.average_entry) === null ? "—" : escapeHtml(formatCents(primary.average_entry))}</strong>`)}
      ${trackerMobileDetail("Sharp stake", `<strong>${number(primary.amount) === null ? "—" : escapeHtml(formatMoney(primary.amount))}</strong>`)}
      ${trackerMobileDetail("Bet", `<strong>${escapeHtml(formatMoney(row.position_cost))}</strong>`)}
      ${trackerMobileDetail("Result", trackerResultBadge(status))}
      ${trackerMobileDetail("P&L", `<strong class="${pnl === null ? "" : pnl >= 0 ? "positive" : "negative"}">${pnl === null ? "Open" : escapeHtml(formatMoney(pnl))}</strong>`)}
      ${trackerMobileDetail("Entry CLV", clvCell(row), "wide")}
      ${trackerMobileDetail("Tracked", `<span class="tracker-timestamp">${escapeHtml(formatDateTime(row.created_at))}</span>`, active ? "" : "wide")}
      ${active ? trackerMobileDetail("Action", `<button class="personal-fill-remove personal-tracker-remove" type="button" data-personal-fill-remove="${escapeHtml(row.fill_id)}" aria-label="Remove ${escapeHtml(row.selection || "personal trade")}"><i class="ph ph-trash" aria-hidden="true"></i> Remove</button>`) : ""}
    </div>
  </details>`;
}

function renderTrackerMobileBets(rows = [], personal = false) {
  const container = document.getElementById("tracker-mobile-bet-list");
  if (!container) return;
  container.innerHTML = rows.length
    ? rows.map(personal ? trackerMobilePersonalBet : trackerMobileModelBet).join("")
    : `<div class="tracker-mobile-empty"><i class="ph ph-receipt" aria-hidden="true"></i><strong>No tracked bets match</strong></div>`;
}

function compositeClvCell(row) {
  const dual = row.dual_clv || {};
  const status = String(dual.composite_clv_status || "UNAVAILABLE").toUpperCase();
  if (status !== "CAPTURED") {
    return `<span class="clv-status neutral" title="${escapeHtml(dual.composite_missing_reason || "Composite close has not been captured")}">${escapeHtml(status.replaceAll("_", " "))}</span>`;
  }
  const snapshot = dual.snapshot || {};
  const closes = Array.isArray(snapshot.provider_closes) ? snapshot.provider_closes : [];
  const probabilityPoints = number(dual.composite_probability_point_clv);
  const priceValue = number(dual.composite_stake_return_clv);
  const entryProbability = number(dual.entry_price ?? row.snapshot?.provider_entry_price);
  const closeProbability = number(dual.composite_closing_probability);
  const entryOdds = row.snapshot?.provider_display_odds ?? probabilityToAmerican(entryProbability);
  const closeOdds = probabilityToAmerican(closeProbability);
  const tone = probabilityPoints > 0 ? "positive" : probabilityPoints < 0 ? "negative" : "neutral";
  const venueRows = closes.map((close) => `<span>
    <b>${escapeHtml(close.provider_name || close.provider || "Exchange")}</b>
    ${escapeHtml(close.display_odds || formatAmericanOdds(close.american_odds ?? probabilityToAmerican(close.closing_probability)))}
  </span>`).join("");
  return `<details class="clv-details ${tone}">
    <summary><strong>${escapeHtml(formatClvPercent(priceValue === null ? null : priceValue * 100))} CLV</strong><small>${escapeHtml(formatClvCents(probabilityPoints))}</small></summary>
    <span><b>Entry odds</b>${escapeHtml(formatAmericanOdds(entryOdds))}</span>
    <span><b>Composite close</b>${escapeHtml(formatAmericanOdds(closeOdds))}</span>
    <span><b>Odds improvement</b>${escapeHtml(oddsDifference(entryOdds, closeOdds))}</span>
    <span><b>Entry probability</b>${entryProbability === null ? "Unavailable" : escapeHtml(formatPercent(entryProbability))}</span>
    <span><b>Composite probability</b>${closeProbability === null ? "Unavailable" : escapeHtml(formatPercent(closeProbability))}</span>
    <span><b>Probability CLV</b>${escapeHtml(formatClvCents(probabilityPoints))}</span>
    <span><b>Price value CLV</b>${escapeHtml(formatClvPercent(priceValue === null ? null : priceValue * 100))}</span>
    <span><b>Closing venues</b>${closes.length}</span>
    ${venueRows}
  </details>`;
}

function trackerRow(row) {
  const snapshot = row.snapshot || {};
  const pnl = number(row.profit_loss);
  const intended = number(snapshot.intended_entry_price ?? snapshot.current_executable_entry_price);
  const actual = number(snapshot.actual_weighted_entry_price ?? snapshot.effective_entry_price);
  const sharpSnapshot = row.sharp_snapshot || snapshot.sharp_snapshot || {};
  const primary = sharpSnapshot.primary_sharp || {};
  const provider = trackerSportsbookName(snapshot);
  const marketUrl = snapshot.market_url || snapshot.provider_market_url || row.market_url || "";
  const entry = actual ?? intended ?? number(snapshot.provider_entry_price);
  const sharpEntry = number(primary.average_entry ?? snapshot.sharp_average_entry_price);
  const sharpStake = number(primary.amount);
  const trackedAt = row.settled_at || row.tracked_at || row.created_at;
  return `
    <tr>
      <td data-label="Market"><div class="tracker-market-cell">${trackerProviderBadge(provider, marketUrl)}<strong>${escapeHtml(trackerShortMatchup(snapshot.event_title || snapshot.market_title))}</strong></div></td>
      <td data-label="Selection"><strong>${escapeHtml(snapshot.recommended_side || "Selection")}</strong></td>
      <td data-label="Sharp">${trackerSharpCompact(sharpSnapshot)}</td>
      <td data-label="Entry"><strong>${entry === null ? "—" : escapeHtml(snapshot.provider_display_odds || formatCents(entry))}</strong><small>Sharp ${sharpEntry === null ? "—" : formatCents(sharpEntry)}</small></td>
      <td data-label="Stake"><strong>${sharpStake === null ? "—" : formatMoney(sharpStake)}</strong><small>Bet ${formatMoney(row.recommended_amount)}</small></td>
      <td data-label="Result">${trackerResultBadge(row.result || row.status)}</td>
      <td data-label="P&amp;L" class="mono ${pnl === null ? "" : pnl >= 0 ? "positive" : "negative"}">${pnl === null ? "Open" : formatMoney(pnl)}</td>
      <td data-label="Entry CLV">${clvCell(row)}</td>
      <td data-label="Tracked"><span class="tracker-timestamp">${escapeHtml(formatDateTime(trackedAt))}</span></td>
    </tr>
  `;
}

function trackerPerformancePoints(graph = []) {
  let previousBankroll = null;
  return graph.map((point) => {
    const bankroll = Number(point.bankroll);
    const timestamp = point.timestamp || null;
    const explicitDaily = Number(point.daily_profit);
    const dailyProfit = Number.isFinite(explicitDaily)
      ? explicitDaily
      : previousBankroll === null || !Number.isFinite(bankroll)
        ? 0
        : bankroll - previousBankroll;
    if (Number.isFinite(bankroll)) previousBankroll = bankroll;
    return { timestamp, bankroll, dailyProfit };
  }).filter((point) => Number.isFinite(point.bankroll));
}

function trackerPeriodLabel(points = []) {
  const dated = points.filter((point) => point.timestamp);
  const latest = dated.length ? new Date(dated[dated.length - 1].timestamp) : new Date();
  if (appState.graphRange === "today") return latest.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  if (appState.graphRange === "week") return "Past 7 Days";
  if (appState.graphRange === "year") return latest.toLocaleDateString(undefined, { year: "numeric" });
  return latest.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function trackerPeriodProfit(points = [], fallback = 0) {
  const dated = points.filter((point) => point.timestamp);
  if (!dated.length) return Number(fallback) || 0;
  return dated.reduce((total, point) => total + (Number(point.dailyProfit) || 0), 0);
}

function drawTrackerProfitChart(points = [], startingBankroll = 0) {
  const container = document.getElementById("tracker-chart");
  if (!container) return;
  const dated = points.filter((point) => point.timestamp);
  if (!dated.length) {
    container.innerHTML = emptyState("No settled results yet", "Your verified profit line will appear after the first result settles.");
    return;
  }
  const canvas = document.createElement("canvas");
  const ratio = Math.max(1, window.devicePixelRatio || 1);
  const rect = container.getBoundingClientRect();
  canvas.width = Math.max(620, Math.round((rect.width || 760) * ratio));
  canvas.height = Math.max(300, Math.round((rect.height || 380) * ratio));
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  container.replaceChildren(canvas);
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const padX = 24 * ratio;
  const padTop = 54 * ratio;
  const padBottom = 48 * ratio;
  const base = Number(startingBankroll) || dated[0].bankroll;
  const values = dated.map((point) => point.bankroll - base);
  let min = Math.min(0, ...values);
  let max = Math.max(0, ...values);
  const spread = Math.max(max - min, Math.max(Math.abs(max), Math.abs(min)) * 0.18, 1);
  min -= spread * 0.12;
  max += spread * 0.12;
  const x = (index) => padX + (index / Math.max(1, values.length - 1)) * (width - padX * 2);
  const y = (value) => padTop + ((max - value) / (max - min)) * (height - padTop - padBottom);
  const coords = values.map((value, index) => ({ x: x(index), y: y(value), value }));

  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  coords.forEach((point, index) => {
    if (!index) ctx.moveTo(point.x, point.y);
    else {
      const previous = coords[index - 1];
      const midpoint = (previous.x + point.x) / 2;
      ctx.bezierCurveTo(midpoint, previous.y, midpoint, point.y, point.x, point.y);
    }
  });
  ctx.strokeStyle = "#00e565";
  ctx.lineWidth = 4 * ratio;
  ctx.shadowColor = "rgba(0, 229, 101, 0.18)";
  ctx.shadowBlur = 8 * ratio;
  ctx.stroke();
  ctx.shadowBlur = 0;

  const highest = coords.reduce((best, point) => point.value > best.value ? point : best, coords[0]);
  const lowest = coords.reduce((best, point) => point.value < best.value ? point : best, coords[0]);
  ctx.fillStyle = "#8f9199";
  ctx.font = `${18 * ratio}px Inter, system-ui, sans-serif`;
  ctx.textBaseline = "middle";
  const highLabel = signedMoney(highest.value);
  const lowLabel = signedMoney(lowest.value);
  ctx.textAlign = highest.x > width * 0.72 ? "right" : highest.x < width * 0.28 ? "left" : "center";
  ctx.fillText(highLabel, Math.min(width - padX, Math.max(padX, highest.x)), Math.max(24 * ratio, highest.y - 28 * ratio));
  if (Math.abs(lowest.value - highest.value) > 0.005) {
    ctx.textAlign = lowest.x > width * 0.62 ? "right" : "left";
    ctx.fillText(lowLabel, Math.min(width - padX, Math.max(padX, lowest.x)), Math.min(height - 18 * ratio, lowest.y + 30 * ratio));
  }
}

function renderTrackerCalendar(points = []) {
  const container = document.getElementById("tracker-calendar");
  if (!container) return;
  const dated = points.filter((point) => point.timestamp);
  if (!appState.trackerCalendarAnchor) {
    appState.trackerCalendarAnchor = dated.length ? new Date(dated[dated.length - 1].timestamp) : new Date();
  }
  const anchor = appState.trackerCalendarAnchor;
  const year = anchor.getFullYear();
  const month = anchor.getMonth();
  const daily = new Map();
  dated.forEach((point) => {
    const date = new Date(point.timestamp);
    if (date.getFullYear() !== year || date.getMonth() !== month) return;
    const day = date.getDate();
    daily.set(day, (daily.get(day) || 0) + (Number(point.dailyProfit) || 0));
  });
  const days = new Date(year, month + 1, 0).getDate();
  const leading = new Date(year, month, 1).getDay();
  const today = new Date();
  const weekday = ["S", "M", "T", "W", "T", "F", "S"].map((label) => `<span class="tracker-calendar-weekday" role="columnheader">${label}</span>`).join("");
  const blanks = Array.from({ length: leading }, () => '<span class="tracker-calendar-blank" aria-hidden="true"></span>').join("");
  const cells = Array.from({ length: days }, (_, index) => {
    const day = index + 1;
    const amount = daily.get(day);
    const future = new Date(year, month, day) > new Date(today.getFullYear(), today.getMonth(), today.getDate());
    const tone = amount > 0 ? "positive" : amount < 0 ? "negative" : "neutral";
    const displayValue = Number.isFinite(amount) ? formatCompactMoney(Math.abs(amount)) : "-";
    const displaySign = amount > 0 ? "+" : amount < 0 ? "-" : "";
    const value = Number.isFinite(amount) ? formatCompactMoney(Math.abs(amount)) : "—";
    const sign = amount > 0 ? "+" : amount < 0 ? "−" : "";
    return `<span class="tracker-calendar-day ${tone}${future ? " future" : ""}" role="gridcell" aria-label="${anchor.toLocaleDateString(undefined, { month: "long" })} ${day}: ${Number.isFinite(amount) ? signedMoney(amount) : "no settled bets"}"><small>${day}</small><strong>${displaySign}${displayValue}</strong></span>`;
  }).join("");
  container.innerHTML = `<div class="tracker-calendar-grid">${weekday}${blanks}${cells}</div>`;
}

function renderTrackerPerformance(payload = {}) {
  appState.trackerPerformancePayload = payload;
  const summary = payload.summary || {};
  const periodSummary = payload.period_summary || {};
  const points = trackerPerformancePoints(payload.graph || []);
  const mode = appState.trackerVisualMode;
  const panel = document.querySelector(".tracker-bankroll-panel");
  const chart = document.getElementById("tracker-chart");
  const calendar = document.getElementById("tracker-calendar");
  if (!panel || !chart || !calendar) return;
  panel.dataset.performanceView = mode;
  document.querySelectorAll(".tracker-period-step").forEach((button) => { button.hidden = mode !== "calendar"; });
  chart.hidden = mode !== "chart";
  calendar.hidden = mode !== "calendar";
  document.querySelectorAll("[data-tracker-visual]").forEach((button) => {
    const active = button.dataset.trackerVisual === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  const periodProfit = trackerPeriodProfit(points, periodSummary.realized_profit_loss);
  const periodLabel = mode === "calendar" && appState.trackerCalendarAnchor
    ? appState.trackerCalendarAnchor.toLocaleDateString(undefined, { month: "long", year: "numeric" })
    : trackerPeriodLabel(points);
  document.getElementById("tracker-chart-title").textContent = periodLabel;
  const periodProfitNode = document.getElementById("tracker-period-profit");
  periodProfitNode.textContent = signedMoney(periodProfit);
  periodProfitNode.className = pnlTone(periodProfit);
  document.getElementById("tracker-summary-profit").textContent = signedMoney(periodProfit);
  document.getElementById("tracker-summary-profit").className = pnlTone(periodProfit);
  const periodKey = appState.graphRange === "today" ? "today" : appState.graphRange === "week" ? "7d" : appState.graphRange === "year" ? "year" : "month";
  const clvPeriod = payload.clv?.periods?.[periodKey] || {};
  const clvValue = number(clvPeriod.stake_weighted_clv_pct);
  const clvNode = document.getElementById("tracker-summary-clv");
  clvNode.textContent = clvValue === null ? "—" : formatClvPercent(clvValue);
  clvNode.className = clvValue > 0 ? "positive" : clvValue < 0 ? "negative" : "";
  document.getElementById("tracker-summary-clv-bets").textContent = `${clvPeriod.bets_measured || 0} bets`;
  const periodRoi = Number(periodSummary.roi) || 0;
  document.getElementById("tracker-summary-roi").textContent = formatPercent(periodRoi);
  document.getElementById("tracker-summary-roi").className = pnlTone(periodRoi);
  document.getElementById("tracker-summary-record").textContent = `${periodSummary.wins || 0}-${periodSummary.losses || 0}-${periodSummary.pushes_voids || 0}`;
  document.getElementById("tracker-performance-updated").textContent = `Updated: ${new Date().toLocaleString(undefined, { month: "numeric", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" })}`;
  if (mode === "calendar") renderTrackerCalendar(points);
  else drawTrackerProfitChart(points, summary.starting_bankroll);
}

function renderClvAnalytics(payload = {}) {
  appState.clvPayload = payload;
  renderTrackerClv(payload);
  return payload.clv?.periods?.all || {};
}

const CLV_METHOD_LABELS = {
  best: "Best Available",
  novig: "No-Vig Fair Odds",
  custom: "Custom Book Selection",
  respective: "Respective Sportsbook",
};

function normalizedBookName(value = "") {
  let compact = String(value || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  if (compact.startsWith("oddsapi")) compact = compact.slice("oddsapi".length);
  const aliases = { poly: "polymarket", betonlineag: "betonline" };
  return aliases[compact] || compact;
}

function clvRangeBounds(range, now = new Date()) {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (range === "today") return [startOfToday, null];
  if (range === "yesterday") return [new Date(startOfToday.getTime() - 86400000), startOfToday];
  if (range === "7d") return [new Date(now.getTime() - (7 * 86400000)), null];
  if (range === "month") return [new Date(now.getFullYear(), now.getMonth(), 1), null];
  if (range === "year") return [new Date(now.getFullYear(), 0, 1), null];
  return [null, null];
}

function clvRecordTimestamp(record = {}) {
  const value = record.clv?.closing_snapshot_timestamp || record.dual_clv?.closing_timestamp || record.record_timestamp;
  const parsed = value ? new Date(value) : null;
  return parsed && Number.isFinite(parsed.getTime()) ? parsed : null;
}

function clvRecordsForPreference(payload = {}) {
  const method = appState.clvMethod;
  const chosen = new Set(appState.clvSelectedBooks.map(normalizedBookName));
  return (payload.clv_records || []).map((record) => {
    const clv = record.clv || {};
    let preference = record.clv_preferences?.[method] || null;
    if (method === "custom") {
      const entry = number(clv.entry_price);
      const closes = (clv.provider_closes || [])
        .map((close) => ({
          provider: normalizedBookName(close.provider || close.provider_name),
          probability: number(close.closing_probability),
          mapping: String(close.mapping_confidence || "EXACT").toUpperCase(),
        }))
        .filter((close) => chosen.has(close.provider) && close.probability > 0 && close.probability < 1 && close.mapping === "EXACT");
      const best = closes.sort((left, right) => left.probability - right.probability)[0];
      preference = best && entry > 0 && entry < 1
        ? { status: "captured", clv_pct: ((best.probability / entry) - 1) * 100 }
        : { status: "unavailable", missing_reason: chosen.size ? "NO_SELECTED_VERIFIED_CLOSE" : "NO_CUSTOM_BOOKS_SELECTED" };
    }
    if (preference) {
      const pct = number(preference.clv_pct);
      return {
        timestamp: clvRecordTimestamp(record),
        captured: String(preference.status || "").toLowerCase() === "captured" && pct !== null,
        pct,
        stake: number(clv.entry_stake) || 1,
        missingReason: preference.missing_reason || null,
      };
    }
    return {
      timestamp: clvRecordTimestamp(record),
      captured: String(clv.clv_status || "").toLowerCase() === "captured" && number(clv.clv_pct) !== null,
      pct: number(clv.clv_pct),
      stake: number(clv.entry_stake) || 1,
    };
  });
}

function clvSummary(payload = {}) {
  const [from, to] = clvRangeBounds(appState.clvRange);
  const records = clvRecordsForPreference(payload).filter((record) => {
    if (!from) return true;
    if (!record.timestamp) return false;
    return record.timestamp >= from && (!to || record.timestamp < to);
  });
  const measured = records.filter((record) => record.captured && record.pct !== null);
  const totalStake = measured.reduce((sum, record) => sum + record.stake, 0);
  const expectedValue = totalStake ? measured.reduce((sum, record) => sum + (record.pct * record.stake), 0) / totalStake : null;
  const positive = measured.filter((record) => record.pct > 0.005).length;
  const negative = measured.filter((record) => record.pct < -0.005).length;
  const even = measured.length - positive - negative;
  return {
    expectedValue,
    measured: measured.length,
    total: records.length,
    positive,
    negative,
    even,
    beating: measured.length ? positive / measured.length : null,
  };
}

function clvPercent(value, digits = 2) {
  return value === null || !Number.isFinite(Number(value)) ? "—" : `${Number(value).toFixed(digits)}%`;
}

function setClvTone(node, value) {
  if (!node) return;
  node.classList.toggle("positive", value !== null && value > 0.005);
  node.classList.toggle("negative", value !== null && value < -0.005);
}

function renderClvDonut(summary) {
  const node = document.getElementById("tracker-clv-donut");
  if (!node) return;
  const circumference = 100;
  const positive = summary.measured ? (summary.positive / summary.measured) * 100 : 0;
  const negative = summary.measured ? (summary.negative / summary.measured) * 100 : 0;
  const even = Math.max(0, 100 - positive - negative);
  node.innerHTML = `<svg viewBox="0 0 42 42" aria-hidden="true"><circle class="track" cx="21" cy="21" r="15.9155"></circle><circle class="positive" cx="21" cy="21" r="15.9155" stroke-dasharray="${positive} ${circumference - positive}" stroke-dashoffset="0"></circle><circle class="negative" cx="21" cy="21" r="15.9155" stroke-dasharray="${negative} ${circumference - negative}" stroke-dashoffset="${-positive}"></circle><circle class="even" cx="21" cy="21" r="15.9155" stroke-dasharray="${even} ${circumference - even}" stroke-dashoffset="${-(positive + negative)}"></circle></svg><span><small>+CLV</small><strong>${clvPercent(summary.beating === null ? null : summary.beating * 100, 1)}</strong></span>`;
}

function renderTrackerClv(payload = {}) {
  const summary = clvSummary(payload);
  const evText = clvPercent(summary.expectedValue);
  const beatText = summary.beating === null ? "—" : clvPercent(summary.beating * 100);
  ["tracker-clv-card-ev", "tracker-clv-detail-ev"].forEach((id) => {
    const node = document.getElementById(id);
    if (!node) return;
    node.textContent = evText;
    setClvTone(node, summary.expectedValue);
  });
  ["tracker-clv-card-beat", "tracker-clv-detail-beat"].forEach((id) => {
    const node = document.getElementById(id);
    if (node) node.textContent = beatText;
  });
  document.querySelectorAll("[data-clv-range]").forEach((button) => {
    const active = button.dataset.clvRange === appState.clvRange;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  const label = document.getElementById("tracker-clv-method-label");
  if (label) label.textContent = CLV_METHOD_LABELS[appState.clvMethod] || CLV_METHOD_LABELS.respective;
  const coverage = document.getElementById("tracker-clv-coverage");
  if (coverage) coverage.textContent = `Data from ${summary.measured} (out of ${summary.total}) bets with CLV data`;
  const unavailable = document.getElementById("tracker-clv-unavailable");
  const breakdown = document.querySelector(".tracker-clv-breakdown");
  if (unavailable) unavailable.hidden = summary.measured > 0;
  if (breakdown) breakdown.hidden = summary.measured === 0;
  const parts = [
    ["positive", summary.positive],
    ["negative", summary.negative],
    ["even", summary.even],
  ];
  parts.forEach(([key, count]) => {
    const value = summary.measured ? (count / summary.measured) * 100 : 0;
    const bar = document.getElementById(`tracker-clv-${key}-bar`);
    const output = document.getElementById(`tracker-clv-${key}-value`);
    if (bar) bar.style.width = `${value}%`;
    if (output) output.textContent = clvPercent(value, 1);
  });
  renderClvDonut(summary);
  renderClvBookGrid(payload);
}

function clvBookNames(payload = {}) {
  const names = new Set(["NoVIG", "ProphetX", "4CX", "Kalshi", "Polymarket"]);
  (appState.trackerBookOptions[appState.trackerView] || []).forEach((name) => names.add(String(name)));
  (payload.clv_records || []).forEach((record) => {
    names.add(String(record.sportsbook || record.clv?.closing_provider || "Sportsbook"));
    (record.clv?.provider_closes || []).forEach((close) => names.add(String(close.provider_name || close.provider || "Sportsbook")));
  });
  return [...names].filter(Boolean).sort((a, b) => a.localeCompare(b));
}

function renderClvBookGrid(payload = {}) {
  const grid = document.getElementById("tracker-clv-book-grid");
  if (!grid) return;
  const pending = new Set(appState.clvPendingBooks.map(normalizedBookName));
  grid.innerHTML = clvBookNames(payload).map((name) => {
    const meta = trackerProviderMeta(name);
    const selected = pending.has(normalizedBookName(name));
    return `<button type="button" class="${selected ? "selected" : ""}" data-clv-book="${escapeHtml(name)}" aria-pressed="${selected}">${providerLogoMarkup(meta, meta.name)}<span>${escapeHtml(meta.name)}</span><i class="ph-fill ph-check-circle" aria-hidden="true"></i></button>`;
  }).join("");
  const label = document.getElementById("tracker-clv-books-label");
  if (label) label.textContent = appState.clvSelectedBooks.length ? `${appState.clvSelectedBooks.length} sportsbooks selected` : "Choose sportsbooks";
}

function renderTrackerProfitSummary(payload = {}) {
  const summary = payload.summary || {};
  const period = payload.period_summary || {};
  const periodKey = appState.graphRange === "today" ? "today" : appState.graphRange === "week" ? "7d" : appState.graphRange === "year" ? "year" : "month";
  const clvPeriod = payload.clv?.periods?.[periodKey] || payload.clv?.periods?.all || {};
  const realized = Number(period.realized_profit_loss ?? summary.realized_profit_loss) || 0;
  const totalStake = Number(summary.total_wagered ?? summary.settled_wagered) || 0;
  const settledStake = Number(period.settled_wagered ?? summary.settled_wagered) || 0;
  const openExposure = Number(summary.open_exposure) || 0;
  const potentialPayout = Number(summary.potential_payout) || 0;
  const wins = Number(period.wins ?? summary.wins) || 0;
  const losses = Number(period.losses ?? summary.losses) || 0;
  const pushes = Number(period.pushes_voids ?? summary.pushes_voids) || 0;
  const settled = wins + losses;
  const profitMargin = settledStake > 0 ? realized / settledStake : 0;
  const beatClv = number(clvPeriod.positive_clv_rate);
  const values = {
    "tracker-profit-total": [signedMoney(realized), pnlTone(realized)],
    "tracker-total-stake": [formatMoney(totalStake), ""],
    "tracker-pending-bets": [formatMoney(openExposure), ""],
    "tracker-potential-payout": [formatMoney(potentialPayout), ""],
    "tracker-profit-margin": [formatPercent(profitMargin), pnlTone(profitMargin)],
    "tracker-beat-clv": [beatClv === null ? "—" : formatPercent(beatClv), beatClv === null ? "" : beatClv >= 0.5 ? "positive" : "negative"],
    "tracker-total-bets": [String(wins + losses + pushes || summary.total_tracked_bets || 0), ""],
    "tracker-bets-won": [settled ? formatPercent(wins / settled) : "—", settled ? (wins >= losses ? "positive" : "negative") : ""],
  };
  Object.entries(values).forEach(([id, [value, tone]]) => {
    const node = document.getElementById(id);
    if (!node) return;
    node.textContent = value;
    node.className = tone;
  });
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
  const sharpSnapshot = row.sharp_snapshot || {};
  const primary = sharpSnapshot.primary_sharp || {};
  const eventMarkup = `<div class="tracker-market-cell">${trackerProviderBadge(row.sportsbook || "Polymarket", row.market_url || "")}<strong>${escapeHtml(trackerShortMatchup(row.event_title || "Unknown event"))}</strong></div>`;
  return `
    <tr>
      <td data-label="Market">${eventMarkup}</td>
      <td data-label="Selection"><strong>${escapeHtml(row.selection || "Selection")}</strong></td>
      <td data-label="Sharp">${trackerSharpCompact(sharpSnapshot)}</td>
      <td data-label="Entry"><strong>${escapeHtml(formatCents(row.entry_price))}</strong><small>Sharp ${number(primary.average_entry) === null ? "—" : formatCents(primary.average_entry)}</small></td>
      <td data-label="Stake"><strong>${escapeHtml(formatMoney(row.position_cost))}</strong><small>${number(primary.amount) === null ? "" : `Sharp ${formatMoney(primary.amount)}`}</small></td>
      <td data-label="Result">${trackerResultBadge(status)}</td>
      <td data-label="P&amp;L" class="mono ${pnl === null ? "" : pnl >= 0 ? "positive" : "negative"}">${pnl === null ? "Open" : escapeHtml(formatMoney(pnl))}</td>
      <td data-label="Entry CLV">${clvCell(row)}</td>
      <td data-label="Tracked"><span class="tracker-timestamp">${escapeHtml(formatDateTime(row.created_at))}</span></td>
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
  drawLineChart(container, points, {
    format: (value) => formatCompactMoney(value),
    color: "#a99af5",
    areaColor: "rgba(169, 154, 245, 0.20)",
    areaFade: "rgba(169, 154, 245, 0)",
    gridColor: "rgba(195, 183, 238, 0.09)",
  });
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
  document.getElementById("tracker-metrics").innerHTML = trackerMetrics(summary, payload.clv || {});
  renderClvAnalytics(payload);
  const body = document.getElementById("tracker-body");
  body.innerHTML = payload.data.length ? payload.data.map(trackerRow).join("") : `<tr><td colspan="16">${trackerEmptyState()}</td></tr>`;
  renderTrackerMobileBets(payload.data || [], false);
  renderTrackerPerformance(payload);
  renderTrackerProfitSummary(payload);
  renderTrackerPagination(payload.pagination, "model");
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
  document.getElementById("tracker-metrics").innerHTML = trackerMetrics(summary, payload.clv || {});
  renderClvAnalytics(payload);
  const body = document.getElementById("tracker-body");
  body.innerHTML = payload.data.length
    ? payload.data.map(personalTrackerRow).join("")
    : `<tr><td colspan="12"><div class="empty-state"><i class="ph ph-user-plus" aria-hidden="true"></i><h2>No personal trades match</h2><p>Use the Track button on a Trades to Play card to add a confirmed purchase.</p><a class="button primary compact" href="/trades"><i class="ph ph-plus" aria-hidden="true"></i>Browse Trades to Play</a></div></td></tr>`;
  renderTrackerMobileBets(payload.data || [], true);
  body.querySelectorAll("[data-personal-fill-remove]").forEach((button) => {
    button.addEventListener("click", () => removePersonalFill(button.dataset.personalFillRemove));
  });
  document.getElementById("tracker-mobile-bet-list")?.querySelectorAll("[data-personal-fill-remove]").forEach((button) => {
    button.addEventListener("click", () => removePersonalFill(button.dataset.personalFillRemove));
  });
  renderTrackerPerformance(payload);
  renderTrackerProfitSummary(payload);
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

async function loadTracker({ initial = false } = {}) {
  const params = trackerRequestParams("model");
  const cacheKey = pagePayloadCacheKey("tracker-model", params.toString());
  if (initial) {
    const cachedPayload = readPagePayloadCache(cacheKey, 30 * 60 * 1000)
      || readPagePayloadCache(latestPagePayloadCacheKey("tracker-model"), 30 * 60 * 1000);
    if (cachedPayload) {
      appState.trackerCache.model = cachedPayload;
      renderModelTracker(cachedPayload);
    }
  }
  try {
    const payload = await fetchJson(`/api/model-tracker?${params.toString()}`);
    appState.trackerCache.model = payload;
    cachePagePayload("tracker-model", cacheKey, payload);
    renderModelTracker(payload);
    if (appState.trackerView === "model" && !document.getElementById("tracker-diagnostics")?.hidden) loadTrackerDiagnostics();
  } catch (error) {
    if (appState.trackerView === "model") document.getElementById("tracker-body").innerHTML = `<tr><td colspan="12">${errorState(error.message)}<button class="button compact tracker-retry" type="button">Retry Model Tracker</button></td></tr>`;
  }
}

async function loadPersonalTracker({ initial = false } = {}) {
  const params = new URLSearchParams({
    ...Object.fromEntries(trackerRequestParams("personal")),
  });
  const cacheKey = pagePayloadCacheKey("tracker-personal", params.toString());
  if (initial) {
    const cachedPayload = readPagePayloadCache(cacheKey, 30 * 60 * 1000)
      || readPagePayloadCache(latestPagePayloadCacheKey("tracker-personal"), 30 * 60 * 1000);
    if (cachedPayload) {
      appState.trackerCache.personal = cachedPayload;
      renderPersonalTracker(cachedPayload);
    }
  }
  try {
    const payload = await fetchJson(`/api/personal-tracker?${params.toString()}`);
    appState.trackerCache.personal = payload;
    cachePagePayload("tracker-personal", cacheKey, payload);
    renderPersonalTracker(payload);
  } catch (error) {
    if (appState.trackerView === "personal") document.getElementById("tracker-body").innerHTML = `<tr><td colspan="12">${errorState(error.message)}<button class="button compact tracker-retry" type="button">Retry Personal Tracker</button></td></tr>`;
  }
}

function loadTrackerView(options = {}) {
  return appState.trackerView === "personal" ? loadPersonalTracker(options) : loadTracker(options);
}

function selectTrackerSection(section, { updateUrl = true } = {}) {
  const normalized = section === "bets" ? "bets" : "dashboard";
  appState.trackerSection = normalized;
  safeStorage.setItem("iconbets-tracker-section", normalized);
  document.querySelectorAll("[data-tracker-section-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.trackerSectionPanel !== normalized;
  });
  document.querySelectorAll("[data-tracker-section]").forEach((button) => {
    const active = button.dataset.trackerSection === normalized;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  const title = document.getElementById("tracker-page-title");
  if (title) title.textContent = normalized === "dashboard" ? "Dashboard" : "Bet Tracker";
  if (updateUrl) {
    const url = new URL(window.location.href);
    url.searchParams.set("section", normalized);
    window.history.replaceState({}, "", `${url.pathname}?${url.searchParams.toString()}`);
  }
}

function configureTrackerShell(view) {
  const model = view === "model";
  const copy = model ? {
    eyebrow: "PERFORMANCE",
    subtitle: "",
    title: "Model results",
    context: "Automatic picks only.",
    icon: "ph-robot",
    chartEyebrow: "BANKROLL REPLAY",
    chartTitle: "Model bankroll",
  } : {
    eyebrow: "PERFORMANCE",
    subtitle: "",
    title: "Personal results",
    context: "Confirmed bets only.",
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
  const trackerAdminOpen = document.getElementById("tracker-admin-open");
  if (trackerAdminOpen) trackerAdminOpen.hidden = true;
  document.getElementById("personal-manual-action").hidden = model;
  document.getElementById("personal-track-action").hidden = model;
  document.getElementById("tracker-job-state").hidden = true;
  document.getElementById("tracker-sharps").hidden = !model;
  document.getElementById("tracker-tag").hidden = model;
  document.querySelectorAll(".model-tracker-filter").forEach((element) => { element.hidden = !model; });
  document.querySelector('#tracker-status option[value="canceled"]').hidden = model;
  document.querySelector('#tracker-result option[value="canceled"]').hidden = model;
  if (model && document.getElementById("tracker-status").value === "canceled") document.getElementById("tracker-status").value = "";
  if (model && document.getElementById("tracker-result").value === "canceled") document.getElementById("tracker-result").value = "";
  document.getElementById("tracker-search").placeholder = model ? "Search event, market, Sharp" : "Search event, selection, Sharp";
  document.getElementById("tracker-table-head").innerHTML = model
    ? "<th>Market</th><th>Selection</th><th>Sharp</th><th>Entry</th><th>Stake</th><th>Result</th><th>P&amp;L</th><th>Entry CLV</th><th>Tracked</th>"
    : "<th>Market</th><th>Selection</th><th>Sharp</th><th>Entry</th><th>Stake</th><th>Result</th><th>P&amp;L</th><th>Entry CLV</th><th>Tracked</th><th>Action</th>";
  document.getElementById("tracker-diagnostics").hidden = !model || !appState.trackerDiagnostics;
  document.querySelectorAll("[data-tracker-view]").forEach((button) => {
    const selected = button.dataset.trackerView === view;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
}

async function selectTrackerView(view, { persist = true, initial = false } = {}) {
  const normalized = view === "personal" ? "personal" : "model";
  appState.trackerView = normalized;
  safeStorage.setItem("iconbets-tracker-view", normalized);
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
  loadTrackerView({ initial });
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

function initializeTrackerView() {
  const params = new URLSearchParams(window.location.search);
  const requested = params.get("view");
  const requestedSection = params.get("section");
  const initialSection = ["dashboard", "bets"].includes(requestedSection)
    ? requestedSection
    : appState.trackerSection;
  selectTrackerSection(initialSection, { updateUrl: requestedSection !== null });
  const view = requested === null
    ? (["model", "personal"].includes(safeStorage.getItem("iconbets-tracker-view")) ? safeStorage.getItem("iconbets-tracker-view") : "model")
    : (["model", "personal"].includes(requested) ? requested : "model");
  selectTrackerView(view, { persist: requested !== null, initial: true });
}

function bindTracker() {
  document.querySelectorAll("[data-tracker-section]").forEach((button) => {
    button.addEventListener("click", () => selectTrackerSection(button.dataset.trackerSection));
  });
  document.querySelectorAll("[data-clv-range]").forEach((button) => button.addEventListener("click", () => {
    appState.clvRange = button.dataset.clvRange;
    safeStorage.setItem("iconbets-clv-range", appState.clvRange);
    renderTrackerClv(appState.clvPayload || {});
  }));
  const clvDialog = document.getElementById("tracker-clv-dialog");
  const clvPreferences = document.getElementById("tracker-clv-preferences-dialog");
  const clvBooks = document.getElementById("tracker-clv-books-dialog");
  const openClvDialog = () => { if (!clvDialog?.open) clvDialog?.showModal(); };
  ["tracker-clv-open", "tracker-clv-view-more"].forEach((id) => document.getElementById(id)?.addEventListener("click", openClvDialog));
  document.getElementById("tracker-clv-close")?.addEventListener("click", () => clvDialog?.close());
  document.getElementById("tracker-clv-view-bets")?.addEventListener("click", () => {
    clvDialog?.close();
    selectTrackerSection("bets");
  });
  document.getElementById("tracker-clv-preferences-open")?.addEventListener("click", () => {
    document.querySelectorAll('input[name="clv-method"]').forEach((input) => { input.checked = input.value === appState.clvMethod; });
    clvDialog?.close();
    clvPreferences?.showModal();
  });
  document.getElementById("tracker-clv-preferences-close")?.addEventListener("click", () => {
    clvPreferences?.close();
    openClvDialog();
  });
  document.getElementById("tracker-clv-preferences-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    appState.clvMethod = document.querySelector('input[name="clv-method"]:checked')?.value || "respective";
    safeStorage.setItem("iconbets-clv-method", appState.clvMethod);
    clvPreferences?.close();
    renderTrackerClv(appState.clvPayload || {});
    openClvDialog();
  });
  document.getElementById("tracker-clv-books-open")?.addEventListener("click", () => {
    appState.clvPendingBooks = [...appState.clvSelectedBooks];
    renderClvBookGrid(appState.clvPayload || {});
    clvPreferences?.close();
    clvBooks?.showModal();
  });
  document.getElementById("tracker-clv-book-grid")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-clv-book]");
    if (!button) return;
    const name = button.dataset.clvBook;
    const key = normalizedBookName(name);
    const exists = appState.clvPendingBooks.some((item) => normalizedBookName(item) === key);
    appState.clvPendingBooks = exists
      ? appState.clvPendingBooks.filter((item) => normalizedBookName(item) !== key)
      : [...appState.clvPendingBooks, name];
    renderClvBookGrid(appState.clvPayload || {});
  });
  document.getElementById("tracker-clv-books-close")?.addEventListener("click", () => {
    clvBooks?.close();
    clvPreferences?.showModal();
  });
  document.getElementById("tracker-clv-books-save")?.addEventListener("click", () => {
    appState.clvSelectedBooks = [...appState.clvPendingBooks];
    safeStorage.setItem("iconbets-clv-books", JSON.stringify(appState.clvSelectedBooks));
    appState.clvMethod = "custom";
    safeStorage.setItem("iconbets-clv-method", appState.clvMethod);
    clvBooks?.close();
    renderTrackerClv(appState.clvPayload || {});
    openClvDialog();
  });
  document.getElementById("tracker-clv-books-reset")?.addEventListener("click", () => {
    appState.clvPendingBooks = [];
    renderClvBookGrid(appState.clvPayload || {});
  });
  [clvDialog, clvPreferences, clvBooks].forEach((dialog) => dialog?.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  }));
  document.getElementById("tracker-dashboard-tag-filter")?.addEventListener("change", (event) => {
    const value = event.target.value;
    document.getElementById("tracker-status").value = value === "live" ? "live" : "";
    document.getElementById("tracker-result").value = ["won", "lost"].includes(value) ? value : "";
    appState.trackerPage[appState.trackerView] = 1;
    loadTrackerView();
  });
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
  document.querySelectorAll("[data-tracker-visual]").forEach((button) => button.addEventListener("click", () => {
    appState.trackerVisualMode = button.dataset.trackerVisual === "calendar" ? "calendar" : "chart";
    safeStorage.setItem("iconbets-tracker-visual", appState.trackerVisualMode);
    if (appState.trackerVisualMode === "calendar") {
      const points = trackerPerformancePoints(appState.trackerPerformancePayload?.graph || []);
      const dated = points.filter((point) => point.timestamp);
      appState.trackerCalendarAnchor = dated.length ? new Date(dated[dated.length - 1].timestamp) : new Date();
    }
    renderTrackerPerformance(appState.trackerPerformancePayload || {});
  }));
  document.getElementById("tracker-period-previous")?.addEventListener("click", () => {
    const anchor = appState.trackerCalendarAnchor || new Date();
    appState.trackerCalendarAnchor = new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1);
    renderTrackerPerformance(appState.trackerPerformancePayload || {});
  });
  document.getElementById("tracker-period-next")?.addEventListener("click", () => {
    const anchor = appState.trackerCalendarAnchor || new Date();
    const next = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1);
    const now = new Date();
    if (next > new Date(now.getFullYear(), now.getMonth(), 1)) return;
    appState.trackerCalendarAnchor = next;
    renderTrackerPerformance(appState.trackerPerformancePayload || {});
  });
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
  document.getElementById("personal-bankroll-control")?.addEventListener("click", openPersonalBankrollDialog);
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
      safeStorage.setItem("iconbets-refresh-paused", String(appState.paused));
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
  "oddsapi__novig": {key:"oddsapi__novig", name:"NoVIG", logoUrl:"https://cdn.prod.website-files.com/642ae772b9f3360398a9d449/6436d7c4d343f31dbf62d683_favicon.png", source:"exchange"},
};
const ODDS_PROVIDER_KEYS = Object.keys(ODDS_BASE_PROVIDER_CATALOG);
const REQUIRED_LINE_SHOP_PROVIDER_KEYS = new Set(["polymarket", "4cx", "oddsapi__novig"]);
const ODDS_PROVIDER_ORDER_KEY = "iconbets_odds_provider_order";
const ODDS_PROVIDER_SELECTION_KEY = "iconbets_odds_provider_selection";

function savedOddsProviderOrder() {
  try {
    const saved = JSON.parse(safeStorage.getItem(ODDS_PROVIDER_ORDER_KEY) || "[]");
    const valid = Array.isArray(saved) ? saved.filter((key, index) => typeof key === "string" && /^[a-z0-9_]+$/.test(key) && saved.indexOf(key) === index) : [];
    return [...valid, ...ODDS_PROVIDER_KEYS.filter(key => !valid.includes(key)), ...(valid.includes("best") ? [] : ["best"])];
  } catch (_) {
    return [...ODDS_PROVIDER_KEYS, "best"];
  }
}

const initialOddsProviderOrder = savedOddsProviderOrder();
let savedOddsProviderSelection = null;
try {
  const saved = JSON.parse(safeStorage.getItem(ODDS_PROVIDER_SELECTION_KEY) || "null");
  savedOddsProviderSelection = Array.isArray(saved)
    ? saved.filter(key => typeof key === "string" && /^[a-z0-9_]+$/.test(key))
    : null;
} catch (_) {
  savedOddsProviderSelection = null;
}
const initialOddsProviders = savedOddsProviderSelection
  ? initialOddsProviderOrder.filter(key => savedOddsProviderSelection.includes(key) || REQUIRED_LINE_SHOP_PROVIDER_KEYS.has(key))
  : initialOddsProviderOrder.filter(key => ODDS_PROVIDER_KEYS.includes(key));
const oddsState = { rows: [], sport: "", league: "", kind: "", search: "", favoritesOnly: false, catalog: {...ODDS_BASE_PROVIDER_CATALOG}, providerOrder: initialOddsProviderOrder, providers: initialOddsProviders, draggedProvider: "", loading: false, timer: null, feedActive: false, mobileEventKey: "", mobileMarketKind: "main" };

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
  safeStorage.setItem(ODDS_PROVIDER_ORDER_KEY, JSON.stringify(oddsState.providerOrder));
}

function oddsProvider(row, key) {
  return (row.executionOptions || []).find(option => String(option.providerKey || "").toLowerCase() === key);
}

function oddsPriceCell(option, provider, bestProviderKey = "") {
  if (!option || option.matchingConfidence !== "Exact") return `<span class="odds-price empty" data-provider="${provider}" role="img" title="No exact market match" aria-label="No exact market match"><strong>—</strong></span>`;
  const liquidity = number(option.availableLiquidity);
  const price = number(option.contractPrice);
  const american = number(option.americanOdds);
  const marketStatus = String(option.marketStatus || "OPEN").toUpperCase();
  const suspended = marketStatus !== "OPEN" || !option.isAvailable;
  const stale = option.isStale === true || String(option.quoteFreshness || "").toLowerCase() === "stale";
  const isBest = String(provider).toLowerCase() === String(bestProviderKey || "").toLowerCase() && !stale && !suspended;
  const liquidityLabel = String(provider).startsWith("oddsapi__") ? "Bet limit unavailable" : "Liquidity unavailable";
  const contractAndAmerican = [price === null ? null : formatCents(price), american === null ? null : (american > 0 ? `+${Math.round(american)}` : `${Math.round(american)}`)].filter(Boolean).join(" / ");
  const headline = ["polymarket", "kalshi"].includes(provider) ? (contractAndAmerican || option.displayOdds || "—") : (option.displayOdds || contractAndAmerican || "—");
  const stateClass = [isBest ? "best-price" : "", stale ? "stale" : "", suspended ? "suspended" : ""].filter(Boolean).join(" ");
  const age = number(option.quoteAgeSeconds);
  const title = suspended ? `Market ${marketStatus.toLowerCase()}` : stale ? `Stale quote${age === null ? "" : ` · ${Math.round(age)} seconds old`}` : `${option.providerName || provider} executable quote`;
  const meta = liquidity === null
    ? `<small class="price-meta" title="${escapeHtml(liquidityLabel)}"><i class="ph ph-info" aria-hidden="true"></i><span class="sr-only">${escapeHtml(liquidityLabel)}</span></small>`
    : `<small>$${Math.round(liquidity).toLocaleString()}</small>`;
  const content = `<strong>${escapeHtml(headline)}</strong>${meta}`;
  if (suspended || !option.deepLink) return `<span class="odds-price ${stateClass}" data-provider="${provider}" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}">${content}</span>`;
  return `<a class="odds-price ${stateClass}" data-provider="${provider}" href="${escapeHtml(option.deepLink)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(title)}" aria-label="Open ${escapeHtml(option.providerName || provider)} at ${escapeHtml(headline)}">${content}</a>`;
}

function oddsGameRow(inputRows) {
  const rows = orderedOddsSelections(inputRows);
  const primary = rows[0] || {};
  const id = String(primary.id || "");
  const favorites = JSON.parse(safeStorage.getItem("iconbets_odds_favorites") || "[]");
  const isFavorite = favorites.includes(id);
  const start = new Date(primary.event_date_et || primary.resolution_time || primary.event_start_time || 0);
  return `<article class="odds-market-row" data-odds-id="${escapeHtml(id)}">
    <span class="odds-start"><b>${Number.isNaN(start.getTime()) ? "TBD" : start.toLocaleTimeString([], {hour:"numeric", minute:"2-digit"})}</b><small>${Number.isNaN(start.getTime()) ? "" : start.toLocaleDateString([], {month:"short", day:"numeric"})}</small><button data-odds-star="${escapeHtml(id)}" class="${isFavorite ? "active" : ""}" aria-label="Favorite"><i class="ph ${isFavorite ? "ph-star-fill" : "ph-star"}"></i></button></span>
    <span class="odds-team odds-team-stack">${rows.map(row => `<span class="odds-team-selection"><strong>${escapeHtml(oddsSelectionLabel(row))}</strong><small>${escapeHtml(oddsMarketLabel(row))}</small></span>`).join("")}</span>
    ${oddsState.providerOrder.filter(key => key === "best" || oddsState.providers.includes(key)).map(key => key === "best" ? `<span class="odds-best odds-best-stack" data-provider-stack="best">${rows.map(oddsBestLine).join("")}</span>` : `<span class="odds-price-stack" data-provider-stack="${key}">${rows.map(row => oddsPriceCell(oddsProvider(row, key), key, bestOddsProviderKey(row))).join("")}</span>`).join("")}
  </article>`;
}

function bestOddsProvider(row) {
  const selected = new Set(oddsState.providers);
  return (row.executionOptions || [])
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
}

function bestOddsProviderKey(row) {
  return String(bestOddsProvider(row)?.providerKey || "").toLowerCase();
}

function oddsBestLine(row) {
  const best = bestOddsProvider(row);
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

function oddsEventKey(row) {
  return String(row.event_id || row.event_slug || row.condition_id || `${row.event_title || "event"}|${row.event_date_et || row.resolution_time || ""}`);
}

function oddsEventParticipants(rows) {
  const primary = rows[0] || {};
  const fromTitle = String(primary.event_title || "")
    .split(/\s+(?:vs\.?|versus|@)\s+/i)
    .map(value => value.trim())
    .filter(Boolean);
  if (fromTitle.length >= 2) return fromTitle.slice(0, 2);
  const outcomes = rows
    .filter(row => ["moneyline", "spread", "alternate_spread"].includes(oddsMarketKind(row)))
    .map(row => String(row.outcome || "").trim())
    .filter((value, index, values) => value && values.indexOf(value) === index);
  return outcomes.length >= 2 ? outcomes.slice(0, 2) : [String(primary.event_title || "Event"), "Opponent"];
}

function oddsEventStart(row) {
  return new Date(row?.event_date_et || row?.resolution_time || row?.event_start_time || 0);
}

function oddsMobileDateLabel(row) {
  const start = oddsEventStart(row);
  if (Number.isNaN(start.getTime())) return "Time TBD";
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const eventDay = new Date(start); eventDay.setHours(0, 0, 0, 0);
  const tomorrow = new Date(today); tomorrow.setDate(today.getDate() + 1);
  const day = eventDay.getTime() === today.getTime() ? "Today" : eventDay.getTime() === tomorrow.getTime() ? "Tomorrow" : start.toLocaleDateString([], {month:"short", day:"numeric"});
  const time = start.toLocaleTimeString([], {hour:"numeric", minute:"2-digit"});
  const league = row?.canonical_league_id || row?.league || row?.category || "";
  return [day, time, league].filter(Boolean).join(" · ");
}

function oddsMobileEventGroups(rows) {
  const groups = new Map();
  rows.forEach(row => {
    const key = oddsEventKey(row);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  });
  return [...groups.entries()].sort((left, right) => oddsEventStart(left[1][0]) - oddsEventStart(right[1][0]));
}

function oddsMobileMarketGroups(rows, filter = "main") {
  const accepted = filter === "moneyline"
    ? new Set(["moneyline"])
    : filter === "spread"
      ? new Set(["spread", "alternate_spread"])
      : filter === "total"
        ? new Set(["game_total", "alternate_total"])
        : new Set(["moneyline", "spread", "game_total"]);
  const groups = new Map();
  rows.forEach(row => {
    if (!accepted.has(oddsMarketKind(row))) return;
    const key = oddsMarketGroupKey(row);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  });
  const kindOrder = {moneyline:0, spread:1, game_total:2, alternate_spread:3, alternate_total:4};
  return [...groups.values()].sort((left, right) => {
    const kindDifference = (kindOrder[oddsMarketKind(left[0])] ?? 9) - (kindOrder[oddsMarketKind(right[0])] ?? 9);
    if (kindDifference) return kindDifference;
    return (number(left[0]?.market_line) ?? 0) - (number(right[0]?.market_line) ?? 0);
  });
}

function oddsMobileMainGroup(rows, kind) {
  return oddsMobileMarketGroups(rows, kind === "game_total" ? "total" : kind)
    .find(group => oddsMarketKind(group[0]) === kind) || [];
}

function oddsMobilePrice(option) {
  const american = number(option?.americanOdds);
  if (american !== null) return american > 0 ? `+${Math.round(american)}` : `${Math.round(american)}`;
  return String(option?.displayOdds || "—");
}

function oddsMobileProviderLogo(option) {
  const key = String(option?.providerKey || "").toLowerCase();
  const provider = {
    ...(oddsState.catalog[key] || {}),
    key,
    name: option?.providerName || oddsState.catalog[key]?.name || key,
    logoUrl: option?.logoUrl || oddsState.catalog[key]?.logoUrl || "",
  };
  return providerLogoMarkup(provider, provider.name);
}

function oddsMobileBestQuote(row, kind) {
  if (!row) return `<span class="mobile-odds-no-line">—</span>`;
  const best = bestOddsProvider(row);
  if (!best) return `<span class="mobile-odds-no-line">—</span>`;
  const marketLine = number(row.market_line);
  const prefix = kind === "game_total"
    ? `${String(row.outcome || "").toLowerCase() === "under" ? "U" : "O"}${marketLine === null ? "" : ` ${marketLine}`} `
    : kind === "spread"
      ? `${marketLine === null ? "" : `${marketLine > 0 ? "+" : ""}${marketLine} `}`
      : "";
  return `<span class="mobile-odds-best-quote">${oddsMobileProviderLogo(best)}<span><b>${escapeHtml(prefix)}${escapeHtml(oddsMobilePrice(best))}</b></span></span>`;
}

function oddsMobileOutcomeForParticipant(group, participant, index) {
  const normalized = String(participant || "").toLowerCase();
  return group.find(row => String(row.outcome || "").toLowerCase() === normalized)
    || orderedOddsSelections(group)[index]
    || null;
}

function oddsMobileGameCard(eventKey, rows) {
  const participants = oddsEventParticipants(rows);
  const moneyline = oddsMobileMainGroup(rows, "moneyline");
  const spread = oddsMobileMainGroup(rows, "spread");
  const total = oddsMobileMainGroup(rows, "game_total");
  const first = rows[0] || {};
  const teamRows = participants.map((participant, index) => {
    const ml = oddsMobileOutcomeForParticipant(moneyline, participant, index);
    const runLine = oddsMobileOutcomeForParticipant(spread, participant, index);
    const totalRow = orderedOddsSelections(total)[index] || null;
    return `<div class="mobile-odds-team-name">${escapeHtml(participant)}</div>
      <div class="mobile-odds-team-prices">
        <span>${oddsMobileBestQuote(ml, "moneyline")}</span>
        <span>${oddsMobileBestQuote(runLine, "spread")}</span>
        <span>${oddsMobileBestQuote(totalRow, "game_total")}</span>
      </div>`;
  }).join("");
  return `<article class="mobile-odds-game" data-mobile-odds-event="${escapeHtml(eventKey)}" role="button" tabindex="0" aria-label="Open all markets for ${escapeHtml(first.event_title || participants.join(" versus "))}">
    <div class="mobile-odds-game-meta">${escapeHtml(oddsMobileDateLabel(first))}<i class="ph ph-caret-right" aria-hidden="true"></i></div>
    <div class="mobile-odds-column-head"><span>MONEYLINE</span><span>SPREAD</span><span>TOTAL</span></div>
    ${teamRows}
  </article>`;
}

function renderMobileOddsBoard(rows) {
  const board = document.getElementById("mobile-odds-games");
  const status = document.getElementById("mobile-odds-status");
  if (!board) return;
  if (status) {
    status.classList.toggle("live", oddsState.feedActive);
    status.querySelector("span").textContent = oddsState.feedActive ? "Live" : "Paused";
  }
  if (!rows.length) {
    board.innerHTML = oddsState.feedActive
      ? `<div class="mobile-odds-empty"><i class="ph ph-magnifying-glass"></i><strong>No matching games</strong><span>Try another league or search.</span></div>`
      : `<div class="mobile-odds-empty"><i class="ph ph-pause-circle"></i><strong>Odds screen paused</strong><span>The Trade Tool remains active while this board saves credits.</span><button type="button" data-mobile-start-feed><i class="ph ph-play"></i> Start live odds</button></div>`;
    return;
  }
  board.innerHTML = oddsMobileEventGroups(rows).map(([key, eventRows]) => oddsMobileGameCard(key, eventRows)).join("");
}

function oddsMobileSheetCell(option, bestProviderKey) {
  if (!option || option.matchingConfidence !== "Exact") return `<span class="mobile-odds-sheet-price empty"><b>—</b></span>`;
  const key = String(option.providerKey || "").toLowerCase();
  const available = option.isAvailable && (!option.marketStatus || option.marketStatus === "OPEN");
  const stale = option.isStale === true;
  const classes = [key === bestProviderKey && available && !stale ? "best" : "", !available ? "disabled" : "", stale ? "stale" : ""].filter(Boolean).join(" ");
  const liquidity = number(option.availableLiquidity);
  const content = `<b>${escapeHtml(oddsMobilePrice(option))}</b>${liquidity === null ? "" : `<small>Liq $${Math.round(liquidity).toLocaleString()}</small>`}<i class="ph ph-arrow-up-right"></i>`;
  if (!available || !option.deepLink) return `<span class="mobile-odds-sheet-price ${classes}">${content}</span>`;
  return `<a class="mobile-odds-sheet-price ${classes}" href="${escapeHtml(option.deepLink)}" target="_blank" rel="noopener noreferrer" aria-label="Open ${escapeHtml(option.providerName || key)} at ${escapeHtml(oddsMobilePrice(option))}">${content}</a>`;
}

function oddsMobileSheetGroup(group) {
  const rows = orderedOddsSelections(group);
  const kind = oddsMarketKind(rows[0] || {});
  const participants = oddsEventParticipants(group);
  const left = rows[0] || null;
  const right = rows[1] || null;
  const label = kind === "moneyline" ? "MONEYLINE" : ["spread", "alternate_spread"].includes(kind) ? "RUN LINE" : "TOTAL RUNS";
  const columnLabel = row => {
    if (!row) return "Unavailable";
    if (kind === "moneyline") return oddsSelectionLabel(row).replace(/\s+ML$/i, "");
    if (["spread", "alternate_spread"].includes(kind)) return oddsSelectionLabel(row);
    const line = number(row.market_line);
    return `${String(row.outcome || "").toLowerCase() === "under" ? "Under" : "Over"}${line === null ? "" : ` ${line}`}`;
  };
  const providerKeys = oddsState.providerOrder.filter(key => {
    if (key === "best" || !oddsState.providers.includes(key)) return false;
    return rows.some(row => oddsProvider(row, key)?.matchingConfidence === "Exact");
  });
  if (!providerKeys.length) return "";
  return `<section class="mobile-odds-sheet-market">
    <h3>${label}</h3>
    <div class="mobile-odds-sheet-sides"><strong>${escapeHtml(columnLabel(left))}</strong><span></span><strong>${escapeHtml(columnLabel(right))}</strong></div>
    <div class="mobile-odds-sheet-books">${providerKeys.map(key => {
      const leftOption = oddsProvider(left || {}, key);
      const rightOption = oddsProvider(right || {}, key);
      const provider = leftOption || rightOption || oddsState.catalog[key] || {providerKey:key, providerName:key};
      return `<div class="mobile-odds-sheet-book-row">
        ${oddsMobileSheetCell(leftOption, bestOddsProviderKey(left || {}))}
        <span class="mobile-odds-sheet-provider">${oddsMobileProviderLogo(provider)}<small>${escapeHtml(provider.providerName || oddsState.catalog[key]?.name || key)}</small></span>
        ${oddsMobileSheetCell(rightOption, bestOddsProviderKey(right || {}))}
      </div>`;
    }).join("")}</div>
  </section>`;
}

function renderMobileOddsSheet() {
  const sheet = document.getElementById("mobile-odds-sheet");
  if (!sheet || sheet.hidden || !oddsState.mobileEventKey) return;
  const rows = oddsState.rows.filter(row => oddsEventKey(row) === oddsState.mobileEventKey);
  if (!rows.length) return closeMobileOddsSheet();
  const first = rows[0];
  document.getElementById("mobile-odds-sheet-meta").textContent = oddsMobileDateLabel(first);
  document.getElementById("mobile-odds-sheet-event").textContent = first.event_title || oddsEventParticipants(rows).join(" vs ");
  document.querySelectorAll("[data-mobile-market-kind]").forEach(button => button.classList.toggle("active", button.dataset.mobileMarketKind === oddsState.mobileMarketKind));
  const groups = oddsMobileMarketGroups(rows, oddsState.mobileMarketKind);
  document.getElementById("mobile-odds-sheet-content").innerHTML = groups.map(oddsMobileSheetGroup).filter(Boolean).join("")
    || `<div class="mobile-odds-empty"><i class="ph ph-chart-line-down"></i><strong>No exact lines available</strong><span>This market has not been posted by the selected books.</span></div>`;
}

function openMobileOddsSheet(eventKey) {
  oddsState.mobileEventKey = eventKey;
  oddsState.mobileMarketKind = "main";
  const sheet = document.getElementById("mobile-odds-sheet");
  const backdrop = document.getElementById("mobile-odds-sheet-backdrop");
  sheet.hidden = false;
  backdrop.hidden = false;
  document.body.classList.add("mobile-odds-sheet-open");
  renderMobileOddsSheet();
  sheet.querySelector("#mobile-odds-sheet-close")?.focus({preventScroll:true});
}

function closeMobileOddsSheet() {
  const sheet = document.getElementById("mobile-odds-sheet");
  const backdrop = document.getElementById("mobile-odds-sheet-backdrop");
  if (sheet) sheet.hidden = true;
  if (backdrop) backdrop.hidden = true;
  document.body.classList.remove("mobile-odds-sheet-open");
  oddsState.mobileEventKey = "";
}

function renderOddsScreen() {
  const favorites = JSON.parse(safeStorage.getItem("iconbets_odds_favorites") || "[]");
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
  }).join("") : `<div class="professional-empty-state odds-empty-state"><span class="activity-icon"><i class="ph ph-magnifying-glass" aria-hidden="true"></i></span><div><span class="page-kicker">Exact-market filter</span><h2>No matching lines</h2><p>No exact markets match the current league, market, favorites, sportsbook, and search filters.</p></div><button class="button ghost compact" type="button" id="odds-empty-reset"><i class="ph ph-funnel-x" aria-hidden="true"></i>Reset filters</button></div>`;
  renderMobileOddsBoard(rows);
  renderMobileOddsSheet();
  document.getElementById("odds-empty-reset")?.addEventListener("click", () => {
    oddsState.sport = "";
    oddsState.league = "";
    oddsState.kind = "";
    oddsState.search = "";
    oddsState.favoritesOnly = false;
    const search = document.getElementById("odds-search");
    if (search) search.value = "";
    renderOddsScreen();
  });
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
  if (!oddsState.feedActive || oddsState.loading || document.hidden) return;
  oddsState.loading = true;
  const started = performance.now();
  try {
    const params = new URLSearchParams();
    if (oddsState.sport) params.set("sport", oddsState.sport);
    if (oddsState.league) params.set("league", oddsState.league);
    if (["moneyline", "spread", "game_total", "alternate_spread", "alternate_total"].includes(oddsState.kind)) params.set("market", oddsState.kind);
    params.set("active", "1");
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

function setOddsFeedActive(active) {
  oddsState.feedActive = Boolean(active);
  const toggle = document.getElementById("odds-feed-toggle");
  const state = document.getElementById("odds-live-state");
  const label = document.getElementById("odds-live-label");
  if (oddsState.timer) window.clearInterval(oddsState.timer);
  oddsState.timer = null;
  state?.classList.toggle("paused", !oddsState.feedActive);
  if (label) label.textContent = oddsState.feedActive ? "LIVE" : "PAUSED";
  if (toggle) {
    toggle.innerHTML = oddsState.feedActive
      ? '<i class="ph ph-pause"></i><span>Pause feed</span>'
      : '<i class="ph ph-play"></i><span>Start feed</span>';
    toggle.title = oddsState.feedActive
      ? "Pause the live odds feed"
      : "Start the live odds feed";
  }
  if (oddsState.feedActive) {
    document.getElementById("odds-latency").textContent = "Starting";
    loadOddsScreen();
    oddsState.timer = window.setInterval(loadOddsScreen, 60000);
  } else {
    document.getElementById("odds-latency").textContent = "Credit saver";
    document.getElementById("odds-updated").textContent = "Paused to protect credits";
  }
  renderMobileOddsBoard(oddsState.rows);
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
  document.getElementById("odds-feed-toggle").addEventListener("click", () => setOddsFeedActive(!oddsState.feedActive));
  document.querySelectorAll("[data-odds-kind]").forEach(button => button.addEventListener("click", () => { document.querySelectorAll("[data-odds-kind]").forEach(item => item.classList.toggle("active", item === button)); oddsState.kind = button.dataset.oddsKind; document.getElementById("odds-market-label").textContent = button.textContent.trim(); loadOddsScreen(); }));
  document.querySelector("[data-odds-all]").addEventListener("click", () => { oddsState.sport = ""; oddsState.league = ""; oddsState.kind = ""; oddsState.favoritesOnly = false; document.getElementById("odds-league-label").textContent = "All Leagues"; document.getElementById("odds-market-label").textContent = "All Markets"; document.querySelector("[data-odds-favorite]").classList.remove("active"); loadOddsScreen(); });
  document.querySelector("[data-odds-favorite]").addEventListener("click", event => { oddsState.favoritesOnly = !oddsState.favoritesOnly; event.currentTarget.classList.toggle("active", oddsState.favoritesOnly); renderOddsScreen(); });
  document.getElementById("odds-grid").addEventListener("click", event => { const star = event.target.closest("[data-odds-star]"); if (!star) return; event.preventDefault(); const values = JSON.parse(safeStorage.getItem("iconbets_odds_favorites") || "[]"); const next = values.includes(star.dataset.oddsStar) ? values.filter(id => id !== star.dataset.oddsStar) : [...values, star.dataset.oddsStar]; safeStorage.setItem("iconbets_odds_favorites", JSON.stringify(next)); renderOddsScreen(); });
  document.getElementById("odds-books-all").addEventListener("click", () => { booksMenu.querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = true; }); document.getElementById("odds-books-count").textContent = `${booksMenu.querySelectorAll('input[type="checkbox"]').length} selected`; });
  document.getElementById("odds-books-none").addEventListener("click", () => { booksMenu.querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = false; }); document.getElementById("odds-books-count").textContent = "0 selected"; });
  booksMenu.addEventListener("change", () => { const count = booksMenu.querySelectorAll('input[type="checkbox"]:checked').length; document.getElementById("odds-books-count").textContent = `${count} selected`; });
  document.getElementById("odds-books-search").addEventListener("input", event => { const query = event.target.value.trim().toLowerCase(); booksMenu.querySelectorAll(".odds-book-list label").forEach(label => { label.hidden = query && !label.textContent.toLowerCase().includes(query); }); });
  document.getElementById("odds-books-apply").addEventListener("click", () => { const selected = new Set([...booksMenu.querySelectorAll('input[type="checkbox"]:checked')].map(input => input.value)); if (!selected.size) return showToast("Select at least one sportsbook", "error"); oddsState.providers = oddsState.providerOrder.filter(key => selected.has(key)); savedOddsProviderSelection = [...oddsState.providers]; safeStorage.setItem(ODDS_PROVIDER_SELECTION_KEY, JSON.stringify(savedOddsProviderSelection)); document.getElementById("odds-books-count").textContent = `${oddsState.providers.length} selected`; closeOddsMenus(); renderOddsScreen(); });
  const mobileLeague = document.getElementById("mobile-odds-league");
  const mobileSearch = document.getElementById("mobile-odds-search");
  mobileLeague?.addEventListener("change", () => {
    const [sport = "", league = ""] = mobileLeague.value.split("|");
    oddsState.sport = sport;
    oddsState.league = league;
    document.getElementById("odds-league-label").textContent = league || sport || "All Leagues";
    if (oddsState.feedActive) loadOddsScreen();
    else renderOddsScreen();
  });
  mobileSearch?.addEventListener("input", event => {
    oddsState.search = event.target.value.trim().toLowerCase();
    const desktopSearch = document.getElementById("odds-search");
    if (desktopSearch) desktopSearch.value = event.target.value;
    renderOddsScreen();
  });
  document.getElementById("mobile-odds-refresh")?.addEventListener("click", () => {
    if (oddsState.feedActive) loadOddsScreen();
    else setOddsFeedActive(true);
  });
  const mobileBoard = document.getElementById("mobile-odds-games");
  mobileBoard?.addEventListener("click", event => {
    if (event.target.closest("[data-mobile-start-feed]")) return setOddsFeedActive(true);
    const game = event.target.closest("[data-mobile-odds-event]");
    if (game) openMobileOddsSheet(game.dataset.mobileOddsEvent);
  });
  mobileBoard?.addEventListener("keydown", event => {
    if (!["Enter", " "].includes(event.key)) return;
    const game = event.target.closest("[data-mobile-odds-event]");
    if (!game) return;
    event.preventDefault();
    openMobileOddsSheet(game.dataset.mobileOddsEvent);
  });
  document.getElementById("mobile-odds-sheet-close")?.addEventListener("click", closeMobileOddsSheet);
  document.getElementById("mobile-odds-sheet-backdrop")?.addEventListener("click", closeMobileOddsSheet);
  document.querySelectorAll("[data-mobile-market-kind]").forEach(button => button.addEventListener("click", () => {
    oddsState.mobileMarketKind = button.dataset.mobileMarketKind;
    renderMobileOddsSheet();
  }));
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !document.getElementById("mobile-odds-sheet")?.hidden) closeMobileOddsSheet();
  });
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
  setOddsFeedActive(false);
}

function shadowStrategyRow(strategy, target) {
  const summary = strategy.summary || {};
  const tracked = number(strategy.tracked_bets) || 0;
  const settled = number(summary.settled_bets ?? summary.settled_count) || 0;
  const roi = number(summary.roi);
  const pnl = number(summary.total_profit_loss ?? summary.profit_loss) || 0;
  const drawdown = number(summary.maximum_drawdown);
  return `<tr>
    <td><strong>${escapeHtml(strategy.strategy)}</strong></td>
    <td><strong>${tracked} / ${target}</strong><small>${Math.min(100, (tracked / target) * 100).toFixed(0)}% collected</small></td>
    <td>${settled}</td>
    <td class="${roi === null ? "" : roi >= 0 ? "positive" : "negative"}">${roi === null ? "Pending" : formatPercent(roi)}</td>
    <td class="${pnl >= 0 ? "positive" : "negative"}">${formatMoney(pnl)}</td>
    <td>${drawdown === null ? "Pending" : formatPercent(drawdown)}</td>
  </tr>`;
}

async function loadShadowTest() {
  const summary = document.getElementById("shadow-summary");
  const comparison = document.getElementById("shadow-comparison");
  const wallets = document.getElementById("wallet-contributions");
  try {
    const payload = await fetchJson("/api/shadow-test");
    const data = payload.data || {};
    const target = number(data.target_bets) || 100;
    summary.innerHTML = [
      metricCard("Live Progress", `${data.live.tracked_bets} / ${target}`, "Hybrid consensus frozen bets", "ph-crosshair"),
      metricCard("Shadow Progress", `${data.shadow.tracked_bets} / ${target}`, "Broad consensus frozen bets", "ph-flask"),
      metricCard("Comparison Mode", "Forward Only", "No hindsight or reconstructed entries", "ph-lock-key"),
    ].join("");
    comparison.innerHTML = [
      shadowStrategyRow(data.live, target),
      shadowStrategyRow(data.shadow, target),
    ].join("");
    wallets.innerHTML = (data.wallet_contributions || []).length
      ? data.wallet_contributions.map((row) => `<tr>
          <td><strong>${escapeHtml(row.display_name || row.wallet_address)}</strong><small>${escapeHtml(row.wallet_address || "")}</small></td>
          <td>${row.settled_bets}</td>
          <td>${formatPercent(row.shrunk_win_rate)}</td>
          <td class="${number(row.roi) >= 0 ? "positive" : "negative"}">${number(row.roi) === null ? "Unavailable" : formatPercent(row.roi)}</td>
          <td>${number(row.average_composite_probability_point_clv) === null ? "Pending" : formatClvCents(row.average_composite_probability_point_clv)}</td>
          <td><span class="status-label">${escapeHtml(String(row.verdict).replaceAll("_", " "))}</span></td>
        </tr>`).join("")
      : `<tr><td colspan="6">${emptyState("Contribution scoring is collecting", "Scores appear after the first live model bets settle.")}</td></tr>`;
  } catch (error) {
    comparison.innerHTML = `<tr><td colspan="6">${errorState(error.message)}</td></tr>`;
  }
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
  if (page === "shadow-test") loadShadowTest();
  if (page !== "sharp-money") loadGlobalStatus();
  if (page !== "sharp-money") loadGlobalRiskState();
}

async function loadGlobalRiskState() {
  const banner = document.getElementById("global-risk-banner");
  if (!banner) return;
  try {
    const payload = await fetchJson("/api/risk-state");
    const data = payload.data || {};
    const risk = data.risk_state || {};
    const state = String(risk.state || "NORMAL").toUpperCase();
    const stopped = state === "STRATEGY_STOP" || data.tracking_paused;
    const reduced = ["DEFENSIVE", "REDUCED"].includes(state);
    banner.hidden = !stopped && !reduced;
    banner.classList.toggle("reduced", !stopped && reduced);
    if (banner.hidden) return;
    document.getElementById("global-risk-title").textContent = stopped
      ? "MODEL TRACKING STOPPED"
      : `MODEL RISK MODE: ${state}`;
    const reasons = [
      data.tracking_paused ? "Tracker is manually paused" : "",
      risk.reason || risk.manual_reason || "",
      data.last_successful_run ? `Last successful run ${formatDateTime(data.last_successful_run)}` : "",
    ].filter(Boolean);
    document.getElementById("global-risk-detail").textContent = reasons.join(" | ");
  } catch {
    banner.hidden = true;
  }
}

function prewarmInstantPages() {
  if (page !== "trades" && !readPagePayloadCache(latestPagePayloadCacheKey("trades"))) {
    fetchJson("/api/trades-to-play?fast=1")
      .then((payload) => writePagePayloadCache(latestPagePayloadCacheKey("trades"), payload))
      .catch(() => {});
  }

  if (page !== "tracker") {
    const savedView = safeStorage.getItem("iconbets-tracker-view") === "personal" ? "personal" : "model";
    const scope = savedView === "personal" ? "tracker-personal" : "tracker-model";
    const endpoint = savedView === "personal" ? "/api/personal-tracker" : "/api/model-tracker";
    if (!readPagePayloadCache(latestPagePayloadCacheKey(scope), 30 * 60 * 1000)) {
      fetchJson(endpoint)
        .then((payload) => writePagePayloadCache(latestPagePayloadCacheKey(scope), payload))
        .catch(() => {});
    }
  }
}

function initialize() {
  bindNavigation();
  bindAccount();
  // Sharp Money is an isolated static sandbox until a real liquidity feed exists.
  if (page !== "sharp-money") {
    const loadGlobalChrome = () => {
      loadGlobalStatus();
      loadGlobalRiskState();
    };
    if (page === "trades" || page === "tracker") runWhenIdle(loadGlobalChrome);
    else loadGlobalChrome();
  }
  if (page === "overview") loadOverview();
  if (page === "trades") bindTrades();
  if (page === "live-positions") bindPositions();
  if (page === "wallets") bindWallets();
  if (page === "position-history") bindHistory();
  if (page === "tracker") bindTracker();
  if (page === "edge-map") bindEdgeMap();
  if (page === "intelligence") bindIntelligence();
  if (page === "shadow-test") loadShadowTest();
  if (page === "odds-screen") bindOddsScreen();
  if (page !== "trades" && page !== "tracker" && page !== "sharp-money") {
    runWhenIdle(prewarmInstantPages);
  }
  window.setInterval(refreshCurrentPage, AUTO_REFRESH_MS);
}

initialize();
