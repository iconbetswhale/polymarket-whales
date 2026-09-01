(() => {
  const pageRoot = document.querySelector(".mid-page");
  if (!pageRoot) return;

  const configNode = document.getElementById("mid-config");
  const config = configNode ? JSON.parse(configNode.textContent || "{}") : {};
  const eligibleBooks = (config.books || []).filter((book) => book.type !== "dfs");
  const defaultBookKeys = eligibleBooks.filter((book) => book.defaultExecution !== false).map((book) => book.key);
  const configuredMiddleMarketKeys = Object.entries(config.marketGroups || {}).flatMap(([group, markets]) =>
    group === "main"
      ? (markets || []).filter((market) => (typeof market === "string" ? market : market?.key) !== "h2h")
      : (markets || [])
  ).map((market) => typeof market === "string" ? market : market?.key).filter(Boolean);
  const storageKey = "iconlabsMiddlesSettingsV3";
  const trackedKey = "iconlabsTrackedMiddlesV1";
  const defaults = {
    books: defaultBookKeys,
    markets: configuredMiddleMarketKeys.length
      ? configuredMiddleMarketKeys
      : ["spreads", "alternate_spreads", "totals", "alternate_totals", "player_points", "pitcher_strikeouts"],
    minWidth: 0.5,
    maxCost: 12,
    maxAge: 90,
    commission: 0,
    distinctBooks: true,
    alerts: false,
    stake: 1000,
    sort: "cost-asc",
  };
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(storageKey) || "{}"); } catch (_) { saved = {}; }

  const state = {
    rows: [],
    selectedId: "",
    search: "",
    sport: "",
    market: "",
    paused: false,
    loading: false,
    selectedBooks: new Set(Array.isArray(saved.books) && saved.books.length ? saved.books : defaults.books),
    markets: Array.isArray(saved.markets) && saved.markets.length ? saved.markets : defaults.markets,
    minWidth: numberBetween(saved.minWidth, 0.01, 1000, defaults.minWidth),
    maxCost: numberBetween(saved.maxCost, 0, 100, defaults.maxCost),
    maxAge: numberBetween(saved.maxAge, 15, 1800, defaults.maxAge),
    commission: numberBetween(saved.commission, 0, 25, defaults.commission),
    distinctBooks: saved.distinctBooks === undefined ? defaults.distinctBooks : Boolean(saved.distinctBooks),
    alerts: Boolean(saved.alerts),
    stake: numberBetween(saved.stake, 1, 10_000_000, defaults.stake),
    sort: ["cost-asc", "width-desc", "profit-desc", "time-asc"].includes(saved.sort) ? saved.sort : defaults.sort,
    lastUpdated: null,
    tracked: new Set(),
    refreshTimer: null,
    stakeTimer: null,
  };
  try { state.tracked = new Set(JSON.parse(localStorage.getItem(trackedKey) || "[]")); } catch (_) { state.tracked = new Set(); }

  const elements = {
    feed: document.getElementById("mid-feed"),
    detail: document.getElementById("mid-detail"),
    status: document.getElementById("mid-feed-status"),
    search: document.getElementById("mid-search"),
    stake: document.getElementById("mid-stake"),
    scan: document.getElementById("mid-scan-toggle"),
    alerts: document.getElementById("mid-alerts"),
    refresh: document.getElementById("mid-refresh"),
    sport: document.getElementById("mid-sport"),
    market: document.getElementById("mid-market"),
    sort: document.getElementById("mid-sort"),
    filterDialog: document.getElementById("mid-filter-dialog"),
    bookGrid: document.getElementById("mid-book-grid"),
    resultCopy: document.getElementById("mid-result-copy"),
    backdrop: document.getElementById("mid-mobile-backdrop"),
    mobileClose: document.getElementById("mid-mobile-close"),
  };

  function numberBetween(value, low, high, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? Math.min(high, Math.max(low, parsed)) : fallback;
  }

  function esc(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
    })[char]);
  }

  function money(value, digits = 2) {
    const amount = Number(value || 0);
    const sign = amount < 0 ? "−" : "";
    return `${sign}$${Math.abs(amount).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
  }

  function signedMoney(value) {
    const amount = Number(value || 0);
    return `${amount >= 0 ? "+" : "−"}$${Math.abs(amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function odds(value) {
    const amount = Number(value || 0);
    return `${amount > 0 ? "+" : ""}${amount}`;
  }

  function percent(value, digits = 2) {
    return `${Number(value || 0).toFixed(digits)}%`;
  }

  function stakeInputValue(value) {
    return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(Number(value || 0));
  }

  function stakeInputNumber(value, fallback) {
    return numberBetween(String(value ?? "").replaceAll(",", "").trim(), 1, 10_000_000, fallback);
  }

  function sportIcon(row) {
    const sport = `${row?.sportKey || ""} ${row?.league || ""}`.toLowerCase();
    if (sport.includes("baseball") || sport.includes("mlb")) return "ph-baseball";
    if (sport.includes("basketball") || sport.includes("nba") || sport.includes("wnba")) return "ph-basketball";
    if (sport.includes("soccer") || sport.includes("epl") || sport.includes("mls")) return "ph-soccer-ball";
    if (sport.includes("football") || sport.includes("nfl") || sport.includes("ncaaf")) return "ph-football";
    if (sport.includes("hockey") || sport.includes("nhl")) return "ph-hockey";
    if (sport.includes("tennis")) return "ph-tennis-ball";
    if (sport.includes("golf") || sport.includes("pga")) return "ph-golf";
    return "ph-trophy";
  }

  function dateTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Time unavailable";
    return new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" }).format(date);
  }

  function timeUntil(value) {
    const milliseconds = new Date(value).getTime() - Date.now();
    if (!Number.isFinite(milliseconds)) return "";
    const hours = Math.max(0, Math.round(milliseconds / 3_600_000));
    if (hours < 1) return "Starting soon";
    if (hours < 24) return `In ${hours}h`;
    return `In ${Math.round(hours / 24)}d`;
  }

  function queueDateParts(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return { day: "Upcoming", time: "" };
    return {
      day: date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      time: date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }),
    };
  }

  function notify(message, tone = "success") {
    const toast = document.getElementById("app-toast");
    if (!toast) return;
    toast.textContent = message;
    toast.dataset.tone = tone;
    toast.classList.add("show");
    window.setTimeout(() => toast.classList.remove("show"), 2600);
  }

  function saveSettings() {
    localStorage.setItem(storageKey, JSON.stringify({
      books: [...state.selectedBooks], markets: state.markets, minWidth: state.minWidth,
      maxCost: state.maxCost, maxAge: state.maxAge, commission: state.commission,
      distinctBooks: state.distinctBooks, alerts: state.alerts, stake: state.stake, sort: state.sort,
    }));
  }

  function logoMarkup(row) {
    const logo = String(row.logoUrl || "");
    if (logo) return `<span class="mid-book-logo"><img src="${esc(logo)}" alt="" decoding="async" onerror="this.hidden=true;this.parentElement.classList.add('mid-book-logo-fallback');this.nextElementSibling.hidden=false"><i class="ph ph-buildings" aria-hidden="true" hidden></i></span>`;
    return `<span class="mid-book-logo mid-book-logo-fallback"><i class="ph ph-buildings" aria-hidden="true"></i></span>`;
  }

  function rowMatches(row) {
    if (state.sport && row.sportKey !== state.sport) return false;
    if (state.market && row.marketKey !== state.market) return false;
    const query = state.search.trim().toLowerCase();
    if (!query) return true;
    const blob = [row.eventTitle, row.league, row.marketLabel, row.marketContext, row.window?.label,
      ...(row.legs || []).flatMap((leg) => [leg.selection, leg.bookName])].join(" ").toLowerCase();
    return blob.includes(query);
  }

  function visibleRows() {
    const rows = state.rows.filter(rowMatches);
    if (state.sort === "width-desc") return rows.sort((left, right) => Number(right.middleWidth) - Number(left.middleWidth));
    if (state.sort === "profit-desc") return rows.sort((left, right) => Number(right.middleProfit) - Number(left.middleProfit));
    if (state.sort === "time-asc") return rows.sort((left, right) => new Date(left.commenceTime) - new Date(right.commenceTime));
    return rows.sort((left, right) => Number(left.breakEvenMiddleProbability) - Number(right.breakEvenMiddleProbability));
  }

  function opportunityCard(row, index) {
    const start = queueDateParts(row.commenceTime);
    return `
      <article class="mid-opportunity-card ${row.id === state.selectedId ? "selected" : ""}" data-mid-id="${esc(row.id)}" role="button" tabindex="0" aria-label="${esc(`${percent(row.breakEvenMiddleProbability)} break-even middle on ${row.eventTitle}`)}">
        <span class="mid-queue-rank">${index + 1}</span>
        <div class="mid-card-score"><strong>${percent(row.breakEvenMiddleProbability)}</strong><span>${Number(row.middleWidth || 0).toFixed(1)} pts</span></div>
        <div class="mid-card-event">
          <h3 title="${esc(row.eventTitle)}"><i class="ph ${sportIcon(row)}" aria-hidden="true"></i><span>${esc(row.eventTitle)}</span></h3>
          <p>${esc(row.league)} · ${esc(row.marketLabel)} · ${esc(row.window?.label || "middle window")}</p>
        </div>
        <time class="mid-queue-date" datetime="${esc(row.commenceTime)}"><span>${esc(start.day)}</span><small>${esc(start.time)}</small></time>
      </article>`;
  }

  function renderFeed() {
    const sortLabels = { "cost-asc": "lowest break-even", "width-desc": "widest window", "profit-desc": "highest middle profit", "time-asc": "start time" };
    if (elements.resultCopy) elements.resultCopy.textContent = `${visibleRows().length} shown · ranked by ${sortLabels[state.sort] || sortLabels["cost-asc"]}`;
    if (state.loading && !state.rows.length) {
      elements.feed.innerHTML = Array.from({ length: 5 }, () => '<div class="mid-skeleton"></div>').join("");
      return;
    }
    const rows = visibleRows();
    if (!rows.length) {
      elements.feed.innerHTML = `<div class="mid-empty"><i class="ph ph-binoculars" aria-hidden="true"></i><strong>No middles match these filters</strong><span>Widen the cost or window settings, add books, or clear search.</span><button type="button" id="mid-empty-filters">Adjust filters</button></div>`;
      document.getElementById("mid-empty-filters")?.addEventListener("click", () => elements.filterDialog.showModal());
      return;
    }
    elements.feed.innerHTML = rows.map(opportunityCard).join("");
  }

  function updateSummary() {
    const rows = state.rows;
    const bestCost = rows.length ? Math.min(...rows.map((row) => Number(row.costPercent))) : null;
    const widest = rows.length ? Math.max(...rows.map((row) => Number(row.middleWidth))) : null;
    document.getElementById("mid-summary-count").textContent = String(rows.length);
    document.getElementById("mid-mode-count").textContent = String(rows.length);
    document.getElementById("mid-summary-cost").textContent = bestCost == null ? "—" : percent(bestCost);
    document.getElementById("mid-summary-width").textContent = widest == null ? "—" : `${Number(widest.toFixed(2))} pts`;
    document.getElementById("mid-summary-status").textContent = state.paused ? "Paused" : state.loading ? "Scanning" : "Ready";
    document.getElementById("mid-summary-fresh").textContent = state.lastUpdated ? `Updated ${new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" }).format(state.lastUpdated)}` : "Waiting for board";
    document.querySelector(".mid-scan-status")?.classList.toggle("is-ready", !state.loading && !state.paused);
  }

  function populateQuickFilters() {
    const sport = state.sport;
    const market = state.market;
    const sports = [...new Map(state.rows.map((row) => [row.sportKey, row.league])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
    const markets = [...new Map(state.rows.map((row) => [row.marketKey, row.marketLabel])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
    elements.sport.innerHTML = '<option value="">All sports</option>' + sports.map(([key, label]) => `<option value="${esc(key)}">${esc(label)}</option>`).join("");
    elements.market.innerHTML = '<option value="">All markets</option>' + markets.map(([key, label]) => `<option value="${esc(key)}">${esc(label)}</option>`).join("");
    elements.sport.value = sport;
    elements.market.value = market;
    elements.sort.value = state.sort;
  }

  function quoteRow(quote, bestKey) {
    const best = quote.bookKey === bestKey;
    const age = quote.quoteAgeSeconds == null ? "Age n/a" : `${Math.round(quote.quoteAgeSeconds)}s old`;
    return `<div class="mid-quote-row${best ? " best" : ""}" draggable="true" data-line-shop-book="${esc(quote.bookKey)}">${logoMarkup(quote)}<span><strong>${esc(quote.bookName)}</strong><small>${esc(age)}</small></span><b>${odds(quote.americanOdds)}</b>${quote.deepLink ? `<a href="${esc(quote.deepLink)}" target="_blank" rel="noopener" aria-label="Open ${esc(quote.bookName)}"><i class="ph ph-arrow-square-out" aria-hidden="true"></i></a>` : ""}</div>`;
  }

  function scenarioRow(label, detail, profit, featured = false) {
    const tone = Number(profit) >= 0 ? "positive" : "negative";
    return `<div class="mid-scenario-row${featured ? " featured" : ""}"><span><strong>${esc(label)}</strong><small>${esc(detail)}</small></span><b class="${tone}">${signedMoney(profit)}</b></div>`;
  }

  function renderDetail(row, openOnMobile = false) {
    if (!row) return;
    const tracked = state.tracked.has(row.id);
    const legs = row.legs || [];
    const legCards = legs.map((leg) => `
      <article class="mid-plan-leg">
        <div class="mid-plan-outcome"><strong>${esc(leg.selection)}</strong><small>${esc(row.marketLabel)}</small></div>
        <div class="mid-plan-book">${logoMarkup(leg)}<span><strong>${esc(leg.bookName)}</strong><small>${leg.quoteAgeSeconds == null ? "Age unavailable" : `${Math.round(leg.quoteAgeSeconds)}s old`}</small></span></div>
        <b class="mid-plan-odds">${odds(leg.americanOdds)}</b>
        <div class="mid-plan-stake"><strong>${money(leg.stake)}</strong></div>
        <b class="mid-plan-payout">${money(leg.outsidePayout)}</b>
        ${leg.deepLink ? `<a class="mid-book-link" href="${esc(leg.deepLink)}" target="_blank" rel="noopener">BET<i class="ph ph-arrow-up-right" aria-hidden="true"></i></a>` : '<span class="mid-book-link disabled">BET</span>'}
      </article>`).join("");
    const outsideOne = legs[0] ? scenarioRow(`${legs[0].selection} wins`, "Result lands above / outside the middle", legs[0].outsideProfit) : "";
    const middle = scenarioRow("Both bets win", row.window?.label || "Inside the middle window", row.middleProfit, true);
    const outsideTwo = legs[1] ? scenarioRow(`${legs[1].selection} wins`, "Result lands below / outside the middle", legs[1].outsideProfit) : "";
    const comparisons = (row.allQuotes || []).map((group) => {
      const quotes = window.IconLabsLineShopOrder?.sortRows(group.quotes || []) || group.quotes || [];
      return `<section class="mid-quote-group" data-line-shop-group><header><span>${esc(group.selection)}</span><small>Drag to reorder</small></header>${quotes.map((quote) => quoteRow(quote, group.bestBookKey)).join("")}</section>`;
    }).join("");
    const warnings = (row.warnings || []).map((warning) => `<div class="mid-detail-warning"><i class="ph ph-warning" aria-hidden="true"></i><span>${esc(warning)}</span></div>`).join("");
    const worstOutside = Math.min(...legs.map((leg) => Number(leg.outsideProfit || 0)));
    const probabilitySummary = row.probabilityModel?.status === "AVAILABLE"
      ? `<div><span>Market-implied middle</span><strong>${percent(row.estimatedMiddleProbability)}</strong><small>${Number(row.estimatedEvPercent) >= 0 ? "+" : ""}${percent(row.estimatedEvPercent)} estimated EV · ${row.probabilityModel.method === "DEVIGGED_MARKET_LADDER_CDF" ? "de-vigged line ladder" : esc(row.probabilityModel.method || "model")}</small></div>`
      : `<div><span>Middle probability</span><strong>Unavailable</strong><small>${esc(row.probabilityModel?.reason || "No paired line ladder")}</small></div>`;
    elements.detail.innerHTML = `
      <header class="mid-detail-header">
        <div class="mid-detail-main"><div class="mid-detail-hero-top"><div class="mid-detail-return"><strong>${percent(row.breakEvenMiddleProbability)}</strong><span>break-even middle</span></div><button type="button" data-mid-mobile-close aria-label="Close details"><i class="ph ph-x" aria-hidden="true"></i></button></div><h2>${esc(row.eventTitle)}</h2><p>${esc(row.league)} · ${esc(row.marketLabel)} · ${esc(dateTime(row.commenceTime))}</p></div>
        <dl class="mid-detail-facts"><div><dt>Middle window</dt><dd>${esc(row.window?.label || `${row.middleWidth} pts`)}</dd></div><div><dt>Worst case</dt><dd class="${worstOutside >= 0 ? "positive" : "warning"}">${signedMoney(worstOutside)}</dd></div><div><dt>Best case</dt><dd class="positive">${signedMoney(row.middleProfit)}</dd></div></dl>
        <div class="mid-detail-actions"><button class="mid-button primary" id="mid-track" type="button"><i class="ph ${tracked ? "ph-bookmark-simple-fill" : "ph-bookmark-simple"}" aria-hidden="true"></i>${tracked ? "Tracked" : "Track pair"}</button><button class="mid-button ghost" id="mid-copy-plan" type="button"><i class="ph ph-copy" aria-hidden="true"></i>Copy plan</button></div>
      </header>
      <section class="mid-detail-section mid-stake-plan-section"><header><h3>Equalized stakes</h3><strong>${money(row.totalStake)}</strong></header><div class="mid-plan-head"><span>Outcome</span><span>Book</span><span>Odds</span><span>Stake</span><span>Payout</span><span class="sr-only">Action</span></div><div class="mid-plan-grid">${legCards}</div></section>
      <section class="mid-detail-section mid-payout-section"><header><h3>Payout scenarios</h3><span class="mid-cost-badge ${row.guaranteedOutsideProfit ? "positive" : "warning"}">${percent(row.breakEvenMiddleProbability)} break-even</span></header><div class="mid-guaranteed-layout"><div class="mid-detail-summary"><div><span>Middle window</span><strong>${esc(row.window?.label || "")}</strong><small>${row.middleWidth} pts</small></div><div><span>Worst case</span><strong class="${worstOutside >= 0 ? "positive" : "warning"}">${signedMoney(worstOutside)}</strong><small>${percent(row.costPercent)} cost</small></div>${probabilitySummary}</div><div class="mid-scenario-list">${outsideOne}${middle}${outsideTwo}</div></div></section>
      <section class="mid-detail-section"><header><h3>Available odds</h3><small>${row.bookCount} books</small></header><div class="mid-quote-groups">${comparisons}</div></section>
      ${warnings}`;
    if (openOnMobile && window.matchMedia("(max-width: 1080px)").matches) {
      document.body.classList.add("mid-detail-open");
      elements.backdrop.hidden = false;
    }
  }

  function closeMobileDetail() {
    document.body.classList.remove("mid-detail-open");
    elements.backdrop.hidden = true;
  }

  function selectRow(id, openOnMobile = false) {
    const row = state.rows.find((item) => item.id === id);
    if (!row) return;
    const changed = state.selectedId !== id;
    state.selectedId = id;
    renderFeed();
    if (changed || openOnMobile) elements.detail.scrollTop = 0;
    renderDetail(row, openOnMobile);
  }

  function renderAll() {
    if (!state.selectedId || !state.rows.some((row) => row.id === state.selectedId)) state.selectedId = state.rows[0]?.id || "";
    renderFeed();
    updateSummary();
    populateQuickFilters();
    const selected = state.rows.find((row) => row.id === state.selectedId);
    if (selected) renderDetail(selected);
  }

  function endpoint() {
    const params = new URLSearchParams();
    if (!state.paused) params.set("active", "1");
    params.set("books", [...state.selectedBooks].join(","));
    params.set("markets", state.markets.join(","));
    params.set("stake", String(state.stake));
    params.set("min_width", String(state.minWidth));
    params.set("max_cost", String(state.maxCost));
    params.set("max_quote_age", String(state.maxAge));
    params.set("commission_bps", String(state.commission * 100));
    if (state.distinctBooks) params.set("distinct_books", "1");
    return `/api/middles?${params.toString()}`;
  }

  async function loadBoard({ quiet = false } = {}) {
    if (state.loading) return;
    const url = endpoint();
    const cacheKey = pagePayloadCacheKey("middles", url);
    if (!quiet && !state.rows.length) {
      const cached = readPagePayloadCache(cacheKey, 5 * 60 * 1000);
      if (cached) {
        state.rows = Array.isArray(cached.data) ? cached.data : [];
        state.lastUpdated = new Date();
        renderAll();
      }
    }
    state.loading = true;
    elements.status.className = "mid-feed-status loading";
    elements.status.innerHTML = '<i class="ph ph-spinner-gap" aria-hidden="true"></i><span>Calculating executable middle windows…</span>';
    if (!quiet && !state.rows.length) renderFeed();
    updateSummary();
    try {
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.message || payload.error || "Middle scan failed");
      writePagePayloadCache(cacheKey, payload);
      state.rows = Array.isArray(payload.data) ? payload.data : [];
      state.lastUpdated = new Date(payload.lastVerifiedAt || payload.generatedAt || Date.now());
      if (state.alerts && state.rows.length) notify(`${state.rows.length} middle opportunit${state.rows.length === 1 ? "y" : "ies"} found.`);
      const paused = Boolean(payload.paused);
      const degraded = Boolean(payload.degraded);
      elements.status.className = `mid-feed-status ${paused ? "paused" : degraded ? "error" : "ready"}`;
      elements.status.innerHTML = paused
        ? '<i class="ph ph-pause-circle" aria-hidden="true"></i><span>Scanner paused · press play to request current prices</span>'
        : degraded
          ? `<i class="ph ph-warning-circle" aria-hidden="true"></i><span>${esc(payload.message || "Recent verified middles shown; live refresh delayed")}</span>`
        : `<i class="ph ph-check-circle" aria-hidden="true"></i><span>${state.rows.length} qualified windows · ${payload.diagnostics?.eventsScanned ?? 0} events scanned</span>`;
      renderAll();
      scheduleRefresh(Number(payload.refreshSeconds || 0));
    } catch (error) {
      elements.status.className = "mid-feed-status error";
      elements.status.innerHTML = `<i class="ph ph-warning-circle" aria-hidden="true"></i><span>${esc(error.message || "Unable to load middles")}</span>`;
      notify(error.message || "Unable to load middles", "error");
    } finally {
      state.loading = false;
      renderFeed();
      updateSummary();
    }
  }

  function scheduleRefresh(seconds) {
    window.clearTimeout(state.refreshTimer);
    if (state.paused || seconds <= 0) return;
    state.refreshTimer = window.setTimeout(() => loadBoard({ quiet: true }), Math.max(15, seconds) * 1000);
  }

  function syncScanButton() {
    elements.scan.setAttribute("aria-pressed", String(state.paused));
    elements.scan.setAttribute("aria-label", state.paused ? "Start automatic refresh" : "Pause automatic refresh");
    elements.scan.innerHTML = state.paused
      ? '<i class="ph ph-play" aria-hidden="true"></i>'
      : '<i class="ph ph-pause" aria-hidden="true"></i>';
  }

  function togglePause() {
    state.paused = !state.paused;
    syncScanButton();
    if (state.paused) {
      window.clearTimeout(state.refreshTimer);
      elements.status.className = "mid-feed-status paused";
      elements.status.innerHTML = '<i class="ph ph-pause-circle" aria-hidden="true"></i><span>Scanner paused</span>';
      updateSummary();
    } else loadBoard();
  }

  function toggleAlerts() {
    state.alerts = !state.alerts;
    elements.alerts.setAttribute("aria-pressed", String(state.alerts));
    saveSettings();
    notify(state.alerts ? "Middle opportunity alerts enabled" : "Middle opportunity alerts muted");
  }

  function renderBookGrid(query = "") {
    const needle = query.trim().toLowerCase();
    const books = eligibleBooks.filter((book) => !needle || `${book.name} ${book.key}`.toLowerCase().includes(needle));
    elements.bookGrid.innerHTML = books.map((book) => `
      <label class="mid-book-choice"><input type="checkbox" value="${esc(book.key)}" ${state.selectedBooks.has(book.key) ? "checked" : ""}><span>${logoMarkup(book)}<b>${esc(book.name)}</b><small>${book.type === "exchange" ? "Exchange" : "Sportsbook"}</small></span></label>`).join("");
    updateBookCount();
  }

  function updateBookCount() {
    const count = elements.bookGrid.querySelectorAll("input:checked").length;
    document.getElementById("mid-book-count").textContent = `${count} selected`;
  }

  function syncDialog() {
    document.getElementById("mid-min-width").value = state.minWidth;
    document.getElementById("mid-max-cost").value = state.maxCost;
    document.getElementById("mid-max-age").value = state.maxAge;
    document.getElementById("mid-commission").value = state.commission;
    document.getElementById("mid-distinct-books").checked = state.distinctBooks;
    document.querySelectorAll("#mid-market-choices input").forEach((input) => { input.checked = state.markets.includes(input.value); });
    renderBookGrid();
  }

  function updateFilterCount() {
    let count = 0;
    if (state.selectedBooks.size !== defaultBookKeys.length) count += 1;
    if (state.markets.length !== defaults.markets.length) count += 1;
    if (state.minWidth !== defaults.minWidth) count += 1;
    if (state.maxCost !== defaults.maxCost) count += 1;
    if (state.maxAge !== defaults.maxAge || state.commission !== defaults.commission || state.distinctBooks) count += 1;
    const node = document.getElementById("mid-filter-count");
    node.textContent = String(count);
    node.hidden = count === 0;
  }

  function readDialog() {
    const selected = [...elements.bookGrid.querySelectorAll("input:checked")].map((input) => input.value);
    const markets = [...document.querySelectorAll("#mid-market-choices input:checked")].map((input) => input.value);
    if (!selected.length || !markets.length) {
      notify(!selected.length ? "Select at least one sportsbook" : "Select at least one market", "error");
      return false;
    }
    state.selectedBooks = new Set(selected);
    state.markets = markets;
    state.minWidth = numberBetween(document.getElementById("mid-min-width").value, 0.01, 1000, defaults.minWidth);
    state.maxCost = numberBetween(document.getElementById("mid-max-cost").value, 0, 100, defaults.maxCost);
    state.maxAge = numberBetween(document.getElementById("mid-max-age").value, 15, 1800, defaults.maxAge);
    state.commission = numberBetween(document.getElementById("mid-commission").value, 0, 25, defaults.commission);
    state.distinctBooks = document.getElementById("mid-distinct-books").checked;
    saveSettings();
    updateFilterCount();
    return true;
  }

  function resetDialog() {
    state.selectedBooks = new Set(defaults.books);
    state.markets = [...defaults.markets];
    state.minWidth = defaults.minWidth;
    state.maxCost = defaults.maxCost;
    state.maxAge = defaults.maxAge;
    state.commission = defaults.commission;
    state.distinctBooks = defaults.distinctBooks;
    syncDialog();
  }

  function applyDialog() {
    if (!readDialog()) return;
    elements.filterDialog.close();
    loadBoard();
  }

  function copyPlan() {
    const row = state.rows.find((item) => item.id === state.selectedId);
    if (!row) return;
    const text = [
      `IconLabs middle · ${row.eventTitle} · ${row.marketLabel}`,
      ...row.legs.map((leg, index) => `Leg ${index + 1}: ${leg.selection} ${odds(leg.americanOdds)} at ${leg.bookName} — stake ${money(leg.stake)}`),
      `Middle: ${row.window.label} · profit ${money(row.middleProfit)}`,
      `Worst outside result: ${signedMoney(row.worstCaseProfit)} · break-even ${percent(row.breakEvenMiddleProbability)}`,
    ].join("\n");
    navigator.clipboard.writeText(text).then(() => notify("Execution plan copied")).catch(() => notify("Copy failed", "error"));
  }

  function toggleTracked() {
    if (!state.selectedId) return;
    if (state.tracked.has(state.selectedId)) state.tracked.delete(state.selectedId); else state.tracked.add(state.selectedId);
    localStorage.setItem(trackedKey, JSON.stringify([...state.tracked]));
    const row = state.rows.find((item) => item.id === state.selectedId);
    renderFeed();
    renderDetail(row);
    notify(state.tracked.has(state.selectedId) ? "Middle added to your watchlist" : "Middle removed from your watchlist");
  }

  function commitStake({ normalize = false } = {}) {
    const value = stakeInputNumber(elements.stake.value, state.stake);
    if (value === state.stake) {
      if (normalize) elements.stake.value = stakeInputValue(state.stake);
      return;
    }
    state.stake = value;
    if (normalize) elements.stake.value = stakeInputValue(state.stake);
    saveSettings();
    loadBoard();
  }

  function bind() {
    elements.search.addEventListener("input", () => { state.search = elements.search.value; renderFeed(); });
    elements.sport.addEventListener("change", () => { state.sport = elements.sport.value; renderFeed(); });
    elements.market.addEventListener("change", () => { state.market = elements.market.value; renderFeed(); });
    elements.sort.addEventListener("change", () => { state.sort = elements.sort.value; saveSettings(); renderFeed(); });
    elements.feed.addEventListener("click", (event) => { const card = event.target.closest("[data-mid-id]"); if (card) selectRow(card.dataset.midId, true); });
    elements.feed.addEventListener("keydown", (event) => {
      if (!["Enter", " "].includes(event.key)) return;
      const card = event.target.closest("[data-mid-id]");
      if (!card) return;
      event.preventDefault();
      selectRow(card.dataset.midId, true);
    });
    elements.scan.addEventListener("click", togglePause);
    elements.alerts.addEventListener("click", toggleAlerts);
    elements.refresh.addEventListener("click", () => loadBoard());
    elements.stake.addEventListener("input", () => {
      window.clearTimeout(state.stakeTimer);
      if (!elements.stake.value) return;
      state.stakeTimer = window.setTimeout(() => commitStake(), 350);
    });
    elements.stake.addEventListener("change", () => {
      window.clearTimeout(state.stakeTimer);
      commitStake({ normalize: true });
    });
    document.getElementById("mid-filter-open").addEventListener("click", () => { syncDialog(); elements.filterDialog.showModal(); });
    document.getElementById("mid-filter-close").addEventListener("click", () => elements.filterDialog.close());
    document.getElementById("mid-filter-reset").addEventListener("click", resetDialog);
    document.getElementById("mid-filter-form").addEventListener("submit", (event) => { event.preventDefault(); applyDialog(); });
    document.getElementById("mid-filter-apply").addEventListener("click", applyDialog);
    document.getElementById("mid-book-search").addEventListener("input", (event) => renderBookGrid(event.target.value));
    elements.bookGrid.addEventListener("change", updateBookCount);
    document.getElementById("mid-books-all").addEventListener("click", () => { elements.bookGrid.querySelectorAll("input").forEach((input) => { input.checked = true; }); updateBookCount(); });
    document.getElementById("mid-books-default").addEventListener("click", () => { elements.bookGrid.querySelectorAll("input").forEach((input) => { input.checked = defaultBookKeys.includes(input.value); }); updateBookCount(); });
    const learnDialog = document.getElementById("mid-learn-dialog");
    document.getElementById("mid-learn-open").addEventListener("click", () => learnDialog.showModal());
    document.getElementById("mid-learn-close").addEventListener("click", () => learnDialog.close());
    elements.backdrop.addEventListener("click", closeMobileDetail);
    elements.mobileClose.addEventListener("click", closeMobileDetail);
    elements.detail.addEventListener("click", (event) => {
      if (event.target.closest("[data-mid-mobile-close]")) closeMobileDetail();
      if (event.target.closest("#mid-copy-plan")) copyPlan();
      if (event.target.closest("#mid-track")) toggleTracked();
    });
    window.IconLabsLineShopOrder?.bindDrag(elements.detail, ".mid-quote-row[data-line-shop-book]");
    window.addEventListener("iconlabs:line-shop-order", () => {
      const selected = state.rows.find((row) => row.id === state.selectedId);
      if (selected) renderDetail(selected);
    });
    document.addEventListener("keydown", (event) => {
      const editable = event.target.matches("input, textarea, select") || event.target.isContentEditable;
      if (event.key === "/" && !editable) { event.preventDefault(); elements.search.focus(); }
      if (["j", "k", "ArrowDown", "ArrowUp"].includes(event.key) && !editable) {
        const rows = visibleRows();
        if (!rows.length) return;
        event.preventDefault();
        const current = Math.max(0, rows.findIndex((row) => row.id === state.selectedId));
        const direction = ["j", "ArrowDown"].includes(event.key) ? 1 : -1;
        selectRow(rows[(current + direction + rows.length) % rows.length].id);
      }
      if (event.key === "Escape") closeMobileDetail();
    });
  }

  elements.stake.value = stakeInputValue(state.stake);
  syncScanButton();
  elements.alerts.setAttribute("aria-pressed", String(state.alerts));
  syncDialog();
  updateFilterCount();
  bind();
  loadBoard();
})();
