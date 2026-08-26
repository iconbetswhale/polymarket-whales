(() => {
  const pageRoot = document.querySelector(".arb-page");
  if (!pageRoot) return;

  const configNode = document.getElementById("arb-config");
  let config = { books: [] };
  try { config = JSON.parse(configNode?.textContent || "{}"); } catch (_error) { config = { books: [] }; }

  const eligibleBooks = (config.books || []).filter((book) => book.type !== "dfs");
  const defaultBookKeys = eligibleBooks.filter((book) => book.defaultExecution !== false).map((book) => book.key);
  const storageKey = "iconlabsArbitrageSettingsV1";
  const defaults = {
    stake: 1000,
    minProfit: 0.1,
    maxAge: 180,
    commissionBps: 0,
    distinctBooks: false,
    books: defaultBookKeys,
    markets: ["h2h", "spreads", "totals"],
    sort: "profit-desc",
  };
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem(storageKey) || "{}"); } catch (_error) { stored = {}; }

  const state = {
    rows: [],
    diagnostics: {},
    error: "",
    selectedId: null,
    loading: false,
    paused: false,
    liveActive: true,
    alerts: false,
    search: "",
    sport: "",
    market: "",
    stake: numberBetween(stored.stake, 1, 10_000_000, defaults.stake),
    minProfit: numberBetween(stored.minProfit, 0, 50, defaults.minProfit),
    maxAge: numberBetween(stored.maxAge, 15, 1800, defaults.maxAge),
    commissionBps: numberBetween(stored.commissionBps, 0, 2500, defaults.commissionBps),
    distinctBooks: Boolean(stored.distinctBooks),
    selectedBooks: new Set(Array.isArray(stored.books) && stored.books.length ? stored.books.filter((key) => eligibleBooks.some((book) => book.key === key)) : defaults.books),
    selectedMarkets: new Set(Array.isArray(stored.markets) && stored.markets.length ? stored.markets : defaults.markets),
    sort: ["profit-desc", "profit-amount-desc", "time-asc"].includes(stored.sort) ? stored.sort : defaults.sort,
    timer: null,
    stakeTimer: null,
  };

  const elements = {
    feed: document.getElementById("arb-feed"),
    detail: document.getElementById("arb-detail"),
    detailPlaceholder: document.getElementById("arb-detail-placeholder"),
    detailContent: document.getElementById("arb-detail-content"),
    search: document.getElementById("arb-search"),
    stake: document.getElementById("arb-stake"),
    dialogStake: document.getElementById("arb-dialog-stake"),
    sport: document.getElementById("arb-sport-filter"),
    market: document.getElementById("arb-market-filter"),
    sort: document.getElementById("arb-sort"),
    refresh: document.getElementById("arb-refresh"),
    pause: document.getElementById("arb-pause"),
    alerts: document.getElementById("arb-alerts"),
    filterDialog: document.getElementById("arb-filter-dialog"),
    filterCount: document.getElementById("arb-filter-count"),
    bookGrid: document.getElementById("arb-book-grid"),
    bookSearch: document.getElementById("arb-book-search"),
    minProfit: document.getElementById("arb-min-profit"),
    maxAge: document.getElementById("arb-max-age"),
    commission: document.getElementById("arb-commission"),
    distinct: document.getElementById("arb-distinct-books"),
    resultCopy: document.getElementById("arb-result-copy"),
    mobileScrim: document.getElementById("arb-mobile-scrim"),
  };

  function numberBetween(value, low, high, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? Math.min(high, Math.max(low, parsed)) : fallback;
  }

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function money(value, digits = 2) {
    const amount = Number(value || 0);
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(amount);
  }

  function odds(value) {
    const amount = Number(value || 0);
    return amount > 0 ? `+${Math.round(amount)}` : `${Math.round(amount)}`;
  }

  function percent(value, digits = 2) {
    return `${Number(value || 0).toFixed(digits)}%`;
  }

  function dateTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Time unavailable";
    return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }

  function timeUntil(value) {
    const milliseconds = new Date(value).getTime() - Date.now();
    if (!Number.isFinite(milliseconds)) return "Upcoming";
    const hours = Math.max(0, Math.round(milliseconds / 3_600_000));
    if (hours < 1) return "Starts soon";
    if (hours < 24) return `In ${hours}h`;
    return `In ${Math.round(hours / 24)}d`;
  }

  function notify(message, tone = "success") {
    const toast = document.getElementById("app-toast");
    if (!toast) return;
    toast.textContent = message;
    toast.className = `toast show ${tone}`;
    window.setTimeout(() => { toast.className = "toast"; }, 2600);
  }

  function saveSettings() {
    const payload = {
      stake: state.stake,
      minProfit: state.minProfit,
      maxAge: state.maxAge,
      commissionBps: state.commissionBps,
      distinctBooks: state.distinctBooks,
      books: [...state.selectedBooks],
      markets: [...state.selectedMarkets],
      sort: state.sort,
    };
    localStorage.setItem(storageKey, JSON.stringify(payload));
  }

  function bookLogo(row) {
    const logo = String(row.logoUrl || "");
    return logo ? `<img src="${esc(logo)}" alt="" loading="lazy">` : `<span class="arb-book-fallback"><i class="ph ph-buildings"></i></span>`;
  }

  function rowMatches(row) {
    const query = state.search.trim().toLowerCase();
    if (state.sport && row.sportKey !== state.sport) return false;
    if (state.market && row.marketKey !== state.market) return false;
    if (!query) return true;
    const blob = [
      row.eventTitle,
      row.league,
      row.marketLabel,
      row.marketContext,
      ...(row.outcomes || []).flatMap((leg) => [leg.selection, leg.bookName]),
    ].join(" ").toLowerCase();
    return blob.includes(query);
  }

  function visibleRows() {
    const rows = state.rows.filter(rowMatches);
    if (state.sort === "profit-amount-desc") return rows.sort((left, right) => right.guaranteedProfit - left.guaranteedProfit);
    if (state.sort === "time-asc") return rows.sort((left, right) => new Date(left.commenceTime) - new Date(right.commenceTime));
    return rows.sort((left, right) => right.profitPercent - left.profitPercent);
  }

  function outcomeSummary(leg) {
    return `
      <div class="arb-leg-summary">
        <span title="${esc(leg.selection)}">${esc(leg.selection)}</span>
        <b>${money(leg.stake, 0)}</b>
        ${bookLogo(leg)}
        <span class="arb-odds-pill">${odds(leg.americanOdds)}</span>
      </div>`;
  }

  function opportunityCard(row) {
    const context = row.marketContext ? ` · ${row.marketContext}` : "";
    return `
      <article class="arb-opportunity ${row.id === state.selectedId ? "active" : ""}" data-arb-id="${esc(row.id)}" role="button" tabindex="0" aria-label="${esc(`${percent(row.profitPercent)} arbitrage on ${row.eventTitle}`)}">
        <div class="arb-return-cell"><strong>${percent(row.profitPercent)}</strong><span>+${money(row.guaranteedProfit)}</span><small>${row.outcomeCount}-way arb</small></div>
        <div class="arb-event-cell">
          <span class="arb-event-meta"><i class="ph ph-circle" aria-hidden="true"></i>${esc(row.league)} · ${esc(timeUntil(row.commenceTime))}</span>
          <h3 title="${esc(row.eventTitle)}">${esc(row.eventTitle)}</h3>
          <p>${esc(dateTime(row.commenceTime))} · ${row.bookCount} book${row.bookCount === 1 ? "" : "s"}</p>
        </div>
        <div class="arb-market-cell"><span><i class="ph ph-chart-line-up" aria-hidden="true"></i>MARKET</span><strong>${esc(row.marketLabel)}</strong><small>${esc(context.replace(/^ · /, "")) || "Main line"}</small></div>
        <div class="arb-legs-cell">${(row.outcomes || []).map(outcomeSummary).join("")}</div>
        <div class="arb-open-cell"><i class="ph ph-caret-right" aria-hidden="true"></i></div>
      </article>`;
  }

  function renderFeed() {
    if (state.loading) {
      elements.feed.innerHTML = `<div class="arb-state arb-loading" role="status"><span class="arb-spinner" aria-hidden="true"></span><strong>Scanning complete markets</strong><p>Comparing selected sportsbooks and equalizing the after-fee payout.</p></div>`;
      return;
    }
    if (state.error) {
      elements.feed.innerHTML = `<div class="arb-state"><i class="ph ph-warning-circle" aria-hidden="true"></i><strong>Arbitrage scan unavailable</strong><p>${esc(state.error)}</p><button class="arb-secondary-button" type="button" data-arb-retry>Try again</button></div>`;
      return;
    }
    if (!state.liveActive) {
      elements.feed.innerHTML = `<div class="arb-state"><i class="ph ph-pause-circle" aria-hidden="true"></i><strong>Arbitrage scanner is paused</strong><p>Start the feed when you need it. IconLabs will request current prices only on demand to protect provider credits.</p><button class="arb-primary-button" type="button" data-arb-start><i class="ph ph-play"></i>Start scanner</button></div>`;
      return;
    }
    const rows = visibleRows();
    if (!rows.length) {
      elements.feed.innerHTML = `<div class="arb-state"><i class="ph ph-intersect-three" aria-hidden="true"></i><strong>No arbitrage matches these filters</strong><p>Try more sportsbooks, a lower minimum return, or a broader market selection. IconLabs never fabricates a missing opposing price.</p><button class="arb-secondary-button" type="button" data-arb-open-filters>Adjust filters</button></div>`;
      return;
    }
    elements.feed.innerHTML = rows.map(opportunityCard).join("");
  }

  function updateSummary() {
    const top = state.rows[0];
    const uniqueEvents = new Set(state.rows.map((row) => row.eventId)).size;
    document.getElementById("arb-kpi-opportunities").textContent = state.rows.length.toLocaleString();
    document.getElementById("arb-kpi-events").textContent = `${uniqueEvents} matched event${uniqueEvents === 1 ? "" : "s"}`;
    document.getElementById("arb-kpi-return").textContent = top ? percent(top.profitPercent) : "—";
    document.getElementById("arb-kpi-profit").textContent = top ? money(top.guaranteedProfit) : "—";
    document.getElementById("arb-kpi-stake").textContent = `On a ${money(state.stake, 0)} stake`;
    document.getElementById("arb-kpi-books").textContent = String(state.diagnostics.selectedBookCount ?? state.selectedBooks.size);
    document.getElementById("arb-mode-count").textContent = String(state.rows.length);
    elements.resultCopy.textContent = `${visibleRows().length} shown · ranked by guaranteed return`;
  }

  function populateQuickFilters() {
    const currentSport = state.sport;
    const currentMarket = state.market;
    const sports = [...new Map(state.rows.map((row) => [row.sportKey, row.league])).entries()].sort((left, right) => left[1].localeCompare(right[1]));
    const markets = [...new Map(state.rows.map((row) => [row.marketKey, row.marketLabel])).entries()].sort((left, right) => left[1].localeCompare(right[1]));
    elements.sport.innerHTML = `<option value="">All sports</option>${sports.map(([key, label]) => `<option value="${esc(key)}">${esc(label)}</option>`).join("")}`;
    elements.market.innerHTML = `<option value="">All markets</option>${markets.map(([key, label]) => `<option value="${esc(key)}">${esc(label)}</option>`).join("")}`;
    elements.sport.value = sports.some(([key]) => key === currentSport) ? currentSport : "";
    elements.market.value = markets.some(([key]) => key === currentMarket) ? currentMarket : "";
  }

  function quoteRow(quote, bestKey) {
    const age = quote.quoteAgeSeconds == null ? "Age n/a" : `${Math.round(quote.quoteAgeSeconds)}s`;
    return `<div class="arb-quote-row ${quote.bookKey === bestKey ? "best" : ""}">${bookLogo(quote)}<span title="${esc(quote.bookName)}">${esc(quote.bookName)}</span><small>${esc(age)}</small><b>${odds(quote.americanOdds)}</b></div>`;
  }

  function renderDetail(row, openOnMobile = false) {
    if (!row) {
      elements.detailPlaceholder.hidden = false;
      elements.detailContent.hidden = true;
      return;
    }
    const plan = (row.outcomes || []).map((leg) => `
      <article class="arb-plan-leg">
        ${bookLogo(leg)}
        <div><strong>${esc(leg.selection)}</strong><small>${esc(leg.bookName)} · ${odds(leg.americanOdds)} · pays ${money(leg.payout)}</small></div>
        <div class="arb-plan-stake"><span>Stake</span><b>${money(leg.stake)}</b></div>
        ${leg.deepLink ? `<a class="arb-bet-link" href="${esc(leg.deepLink)}" target="_blank" rel="noopener noreferrer">BET<i class="ph ph-arrow-up-right"></i></a>` : `<span class="arb-bet-link disabled">BET</span>`}
      </article>`).join("");
    const payoutMax = Math.max(...row.outcomes.map((leg) => leg.payout), 1);
    const payouts = row.outcomes.map((leg) => `<div class="arb-payout-row"><span title="${esc(leg.selection)}">${esc(leg.selection)}</span><progress max="${payoutMax}" value="${Number(leg.payout)}"></progress><b>+${money(leg.profit)}</b></div>`).join("");
    const comparisons = (row.allQuotes || []).map((group) => {
      const selected = row.outcomes.find((leg) => leg.selection === group.selection);
      return `<section class="arb-comparison-group"><h4>${esc(group.selection)}</h4>${(group.quotes || []).slice(0, 8).map((quote) => quoteRow(quote, selected?.bookKey)).join("")}</section>`;
    }).join("");
    const warnings = (row.warnings || []).map((warning) => `<div class="arb-detail-warning"><i class="ph ph-warning"></i><span>${esc(warning)}</span></div>`).join("");
    elements.detailContent.innerHTML = `
      <header class="arb-detail-hero">
        <div class="arb-detail-hero-top"><div class="arb-detail-return"><strong>${percent(row.profitPercent)}</strong><span>guaranteed return</span></div><button class="arb-icon-button arb-detail-close" type="button" data-arb-close-detail aria-label="Close execution plan"><i class="ph ph-x"></i></button></div>
        <h2>${esc(row.eventTitle)}</h2>
        <p>${esc(row.league)} · ${esc(row.marketLabel)}${row.marketContext ? ` · ${esc(row.marketContext)}` : ""} · ${esc(dateTime(row.commenceTime))}</p>
        <div class="arb-detail-actions"><button class="arb-primary-button" type="button" data-arb-copy-plan><i class="ph ph-copy"></i>Copy stake plan</button><button class="arb-secondary-button" type="button" data-arb-recalculate><i class="ph ph-calculator"></i>Recalculate</button></div>
      </header>
      <section class="arb-detail-section"><header><h3>Stake plan</h3><span>${row.outcomeCount} outcomes · ${row.bookCount} books</span></header><div class="arb-plan-list">${plan}</div></section>
      <section class="arb-detail-section"><header><h3>Guaranteed outcome</h3><span>after fee buffer &amp; cent rounding</span></header><div class="arb-profit-proof"><div><span>Total staked</span><strong>${money(row.totalStake)}</strong></div><div><span>Minimum payout</span><strong>${money(row.minPayout)}</strong></div><div><span>Locked profit</span><strong class="positive">+${money(row.guaranteedProfit)}</strong></div></div><div class="arb-payout-list">${payouts}</div></section>
      <section class="arb-detail-section"><header><h3>Odds comparison</h3><span>best price highlighted</span></header>${comparisons}</section>
      <section class="arb-detail-section"><header><h3>Calculation</h3><span>${esc(row.calculationVersion)}</span></header><div class="arb-math-note"><i class="ph ph-function"></i><p>The inverse-probability total is <strong>${Number(row.impliedProbabilityPercent).toFixed(2)}%</strong>. Because it is below 100%, equalized stakes return more than the total amount deployed whichever outcome wins.<code>(1 ÷ ${Number(row.inverseProbabilitySum).toFixed(6)} − 1) × 100 = ${percent(row.theoreticalProfitPercent, 3)}</code></p></div>${warnings}<div class="arb-detail-warning"><i class="ph ph-clock-countdown"></i><span>Place every leg quickly and verify the displayed odds and accepted stake before submitting any wager.</span></div></section>`;
    elements.detailPlaceholder.hidden = true;
    elements.detailContent.hidden = false;
    if (openOnMobile && window.matchMedia("(max-width: 1080px)").matches) {
      elements.detail.classList.add("mobile-open");
      elements.mobileScrim.hidden = false;
    }
  }

  function closeMobileDetail() {
    elements.detail.classList.remove("mobile-open");
    elements.mobileScrim.hidden = true;
  }

  function selectRow(id, openOnMobile = false) {
    const row = state.rows.find((item) => item.id === id);
    if (!row) return;
    state.selectedId = id;
    renderFeed();
    renderDetail(row, openOnMobile);
  }

  function renderAll() {
    updateSummary();
    populateQuickFilters();
    renderFeed();
    const selected = state.rows.find((row) => row.id === state.selectedId) || state.rows[0];
    if (selected) {
      state.selectedId = selected.id;
      renderDetail(selected, false);
      renderFeed();
    } else {
      state.selectedId = null;
      renderDetail(null);
    }
  }

  function endpoint() {
    const params = new URLSearchParams();
    params.set("active", "1");
    params.set("stake", String(state.stake));
    params.set("min_profit", String(state.minProfit));
    params.set("max_quote_age", String(state.maxAge));
    params.set("commission_bps", String(state.commissionBps));
    params.set("distinct_books", state.distinctBooks ? "1" : "0");
    params.set("books", [...state.selectedBooks].join(","));
    params.set("markets", [...state.selectedMarkets].join(","));
    return `/api/arbitrage?${params.toString()}`;
  }

  async function loadBoard({ quiet = false } = {}) {
    if (state.loading || !state.liveActive) { renderAll(); return; }
    state.loading = true;
    state.error = "";
    if (!quiet) renderFeed();
    elements.refresh.classList.add("is-spinning");
    try {
      const response = await fetch(endpoint(), { headers: { Accept: "application/json" } });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.message || payload.error || "Unable to scan arbitrage markets.");
      state.rows = Array.isArray(payload.data) ? payload.data : [];
      state.diagnostics = payload.diagnostics || {};
      state.paused = Boolean(payload.paused);
      if (state.alerts && state.rows.length) notify(`${state.rows.length} arbitrage opportunit${state.rows.length === 1 ? "y" : "ies"} found.`);
      scheduleRefresh(Number(payload.refreshSeconds || 60));
    } catch (error) {
      state.rows = [];
      state.diagnostics = {};
      state.error = error.message;
      notify(error.message, "error");
    } finally {
      state.loading = false;
      elements.refresh.classList.remove("is-spinning");
      renderAll();
    }
  }

  function scheduleRefresh(seconds) {
    window.clearTimeout(state.timer);
    if (!seconds || state.paused || !state.liveActive) return;
    state.timer = window.setTimeout(() => loadBoard({ quiet: true }), seconds * 1000);
  }

  function startScanner() {
    state.liveActive = true;
    state.paused = false;
    elements.pause.setAttribute("aria-pressed", "false");
    elements.pause.innerHTML = `<i class="ph ph-pause" aria-hidden="true"></i>`;
    loadBoard();
  }

  function togglePause() {
    if (!state.liveActive) { startScanner(); return; }
    state.paused = !state.paused;
    elements.pause.setAttribute("aria-pressed", state.paused ? "true" : "false");
    elements.pause.innerHTML = `<i class="ph ${state.paused ? "ph-play" : "ph-pause"}" aria-hidden="true"></i>`;
    window.clearTimeout(state.timer);
    if (!state.paused) loadBoard({ quiet: true });
    notify(state.paused ? "Automatic arbitrage refresh paused." : "Automatic arbitrage refresh resumed.");
  }

  function renderBookGrid(query = "") {
    const needle = query.trim().toLowerCase();
    const books = eligibleBooks.filter((book) => !needle || `${book.name} ${book.key}`.toLowerCase().includes(needle));
    elements.bookGrid.innerHTML = books.map((book) => `<label class="arb-book-option"><input type="checkbox" value="${esc(book.key)}" ${state.selectedBooks.has(book.key) ? "checked" : ""}>${book.logoUrl ? `<img src="${esc(book.logoUrl)}" alt="" loading="lazy">` : `<span class="arb-book-fallback"><i class="ph ph-buildings"></i></span>`}<span>${esc(book.name)}</span></label>`).join("");
    document.getElementById("arb-book-filter-count").textContent = `${state.selectedBooks.size}/${eligibleBooks.length}`;
  }

  function syncDialog() {
    elements.dialogStake.value = String(state.stake);
    elements.minProfit.value = String(state.minProfit);
    elements.maxAge.value = String(state.maxAge);
    elements.commission.value = String(state.commissionBps);
    elements.distinct.checked = state.distinctBooks;
    document.querySelectorAll("#arb-market-choices input").forEach((input) => { input.checked = state.selectedMarkets.has(input.value); });
    document.querySelectorAll('input[name="arb-dialog-sort"]').forEach((input) => { input.checked = input.value === state.sort; });
    renderBookGrid();
  }

  function updateFilterCount() {
    let count = 0;
    if (state.selectedBooks.size !== eligibleBooks.length) count += 1;
    if (state.minProfit !== defaults.minProfit) count += 1;
    if (state.maxAge !== defaults.maxAge) count += 1;
    if (state.commissionBps !== defaults.commissionBps) count += 1;
    if (state.distinctBooks) count += 1;
    if ([...state.selectedMarkets].sort().join() !== [...defaults.markets].sort().join()) count += 1;
    elements.filterCount.hidden = count === 0;
    elements.filterCount.textContent = String(count);
  }

  function readDialog() {
    const selected = [...state.selectedBooks];
    if (!selected.length) { notify("Select at least one sportsbook.", "error"); return false; }
    const markets = [...document.querySelectorAll("#arb-market-choices input:checked")].map((input) => input.value);
    if (!markets.length) { notify("Select at least one market.", "error"); return false; }
    state.selectedBooks = new Set(selected);
    state.selectedMarkets = new Set(markets);
    state.stake = numberBetween(elements.dialogStake.value, 1, 10_000_000, state.stake);
    state.minProfit = numberBetween(elements.minProfit.value, 0, 50, state.minProfit);
    state.maxAge = numberBetween(elements.maxAge.value, 15, 1800, state.maxAge);
    state.commissionBps = numberBetween(elements.commission.value, 0, 2500, state.commissionBps);
    state.distinctBooks = elements.distinct.checked;
    state.sort = document.querySelector('input[name="arb-dialog-sort"]:checked')?.value || state.sort;
    elements.stake.value = String(state.stake);
    elements.sort.value = state.sort;
    saveSettings();
    updateFilterCount();
    return true;
  }

  function resetDialog() {
    state.stake = defaults.stake;
    state.minProfit = defaults.minProfit;
    state.maxAge = defaults.maxAge;
    state.commissionBps = defaults.commissionBps;
    state.distinctBooks = defaults.distinctBooks;
    state.selectedBooks = new Set(defaults.books);
    state.selectedMarkets = new Set(defaults.markets);
    state.sort = defaults.sort;
    syncDialog();
  }

  function copyPlan() {
    const row = state.rows.find((item) => item.id === state.selectedId);
    if (!row) return;
    const text = [
      `${row.eventTitle} · ${row.marketLabel}${row.marketContext ? ` · ${row.marketContext}` : ""}`,
      ...row.outcomes.map((leg) => `${leg.bookName}: ${leg.selection} ${odds(leg.americanOdds)} — stake ${money(leg.stake)}`),
      `Total ${money(row.totalStake)} · Minimum payout ${money(row.minPayout)} · Guaranteed profit ${money(row.guaranteedProfit)} (${percent(row.profitPercent)})`,
    ].join("\n");
    navigator.clipboard?.writeText(text).then(() => notify("Stake plan copied.")).catch(() => notify("Copy failed. Select and copy the plan manually.", "error"));
  }

  function bind() {
    elements.stake.value = String(state.stake);
    elements.sort.value = state.sort;
    syncDialog();
    updateFilterCount();

    elements.feed.addEventListener("click", (event) => {
      if (event.target.closest("[data-arb-start]")) { startScanner(); return; }
      if (event.target.closest("[data-arb-open-filters]")) { syncDialog(); elements.filterDialog.showModal(); return; }
      if (event.target.closest("[data-arb-retry]")) { loadBoard(); return; }
      const card = event.target.closest("[data-arb-id]");
      if (card) selectRow(card.dataset.arbId, true);
    });
    elements.feed.addEventListener("keydown", (event) => {
      const card = event.target.closest("[data-arb-id]");
      if (card && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); selectRow(card.dataset.arbId, true); }
    });
    elements.detail.addEventListener("click", (event) => {
      if (event.target.closest("[data-arb-close-detail]")) closeMobileDetail();
      if (event.target.closest("[data-arb-copy-plan]")) copyPlan();
      if (event.target.closest("[data-arb-recalculate]")) loadBoard();
    });
    elements.mobileScrim.addEventListener("click", closeMobileDetail);

    elements.search.addEventListener("input", () => { state.search = elements.search.value; renderFeed(); updateSummary(); });
    elements.sport.addEventListener("change", () => { state.sport = elements.sport.value; renderFeed(); updateSummary(); });
    elements.market.addEventListener("change", () => { state.market = elements.market.value; renderFeed(); updateSummary(); });
    elements.sort.addEventListener("change", () => { state.sort = elements.sort.value; saveSettings(); renderFeed(); });
    elements.stake.addEventListener("input", () => {
      window.clearTimeout(state.stakeTimer);
      state.stakeTimer = window.setTimeout(() => {
        state.stake = numberBetween(elements.stake.value, 1, 10_000_000, state.stake);
        elements.dialogStake.value = String(state.stake);
        saveSettings();
        if (state.liveActive) loadBoard();
      }, 350);
    });
    elements.refresh.addEventListener("click", () => { if (!state.liveActive) startScanner(); else loadBoard(); });
    elements.pause.addEventListener("click", togglePause);
    elements.alerts.addEventListener("click", () => {
      state.alerts = !state.alerts;
      elements.alerts.setAttribute("aria-pressed", state.alerts ? "true" : "false");
      elements.alerts.innerHTML = `<i class="ph ${state.alerts ? "ph-bell-ringing" : "ph-bell"}" aria-hidden="true"></i>`;
      notify(state.alerts ? "Opportunity alerts enabled for this page." : "Opportunity alerts muted.");
    });

    document.getElementById("arb-filter-open").addEventListener("click", () => { syncDialog(); elements.filterDialog.showModal(); });
    document.getElementById("arb-filter-close").addEventListener("click", () => elements.filterDialog.close());
    document.getElementById("arb-apply").addEventListener("click", (event) => {
      event.preventDefault();
      if (!readDialog()) return;
      elements.filterDialog.close();
      if (state.liveActive) loadBoard(); else renderAll();
    });
    document.getElementById("arb-reset").addEventListener("click", resetDialog);
    document.getElementById("arb-books-all").addEventListener("click", () => { state.selectedBooks = new Set(eligibleBooks.map((book) => book.key)); renderBookGrid(elements.bookSearch.value); });
    document.getElementById("arb-books-clear").addEventListener("click", () => { state.selectedBooks.clear(); renderBookGrid(elements.bookSearch.value); });
    elements.bookSearch.addEventListener("input", () => renderBookGrid(elements.bookSearch.value));
    elements.bookGrid.addEventListener("change", (event) => {
      if (!event.target.matches('input[type="checkbox"]')) return;
      if (event.target.checked) state.selectedBooks.add(event.target.value); else state.selectedBooks.delete(event.target.value);
      document.getElementById("arb-book-filter-count").textContent = `${state.selectedBooks.size}/${eligibleBooks.length}`;
    });
    document.querySelectorAll("[data-arb-filter-tab]").forEach((button) => button.addEventListener("click", () => {
      document.querySelectorAll("[data-arb-filter-tab]").forEach((item) => item.classList.toggle("active", item === button));
      document.querySelectorAll("[data-arb-filter-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.arbFilterPanel === button.dataset.arbFilterTab));
    }));

    const learn = document.getElementById("arb-learn-dialog");
    document.getElementById("arb-learn-open").addEventListener("click", () => learn.showModal());
    document.getElementById("arb-learn-close").addEventListener("click", () => learn.close());
    document.getElementById("arb-learn-done").addEventListener("click", () => learn.close());

    document.addEventListener("keydown", (event) => {
      const editable = event.target.matches("input, textarea, select") || event.target.isContentEditable;
      if (event.key === "/" && !editable) { event.preventDefault(); elements.search.focus(); }
      if (event.key === "Escape" && elements.detail.classList.contains("mobile-open")) closeMobileDetail();
      if (!editable && ["j", "k", "ArrowDown", "ArrowUp"].includes(event.key)) {
        const rows = visibleRows();
        if (!rows.length) return;
        const current = Math.max(0, rows.findIndex((row) => row.id === state.selectedId));
        const direction = ["j", "ArrowDown"].includes(event.key) ? 1 : -1;
        const next = rows[(current + direction + rows.length) % rows.length];
        selectRow(next.id, false);
        document.querySelector(`[data-arb-id="${CSS.escape(next.id)}"]`)?.scrollIntoView({ block: "nearest" });
      }
    });
  }

  bind();
  loadBoard();
})();
