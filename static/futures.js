(() => {
  "use strict";

  const storageKey = "iconlabs_futures_books_v1";
  const leagueAsset = {
    MLB: "/static/assets/leagues/mlb.png",
    NFL: "/static/assets/leagues/nfl.png",
    NCAAF: "/static/assets/leagues/ncaa.png",
    CFB: "/static/assets/leagues/ncaa.png",
    NBA: "/static/assets/leagues/nba.png",
    WNBA: "/static/assets/leagues/wnba.png",
    NCAAB: "/static/assets/leagues/ncaa.png",
    NCAAW: "/static/assets/leagues/ncaa.png",
    NHL: "/static/assets/leagues/nhl.png",
    EPL: "/static/assets/leagues/epl.png",
    MLS: "/static/assets/leagues/mls.png",
  };

  const embeddedCatalog = (() => {
    try {
      const rows = JSON.parse(document.getElementById("futures-provider-catalog")?.textContent || "[]");
      return Array.isArray(rows) ? rows : [];
    } catch (_) {
      return [];
    }
  })();

  const state = {
    rows: [],
    providers: new Map(embeddedCatalog.map(provider => [String(provider.key || "").toLowerCase(), provider])),
    selectedProviders: [],
    league: "",
    market: "",
    search: "",
    sort: "best",
    loading: false,
    payload: null,
  };

  function escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function asNumber(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function normalized(value) {
    return String(value || "").trim().toLowerCase();
  }

  function providerKey(value) {
    return normalized(value);
  }

  function providerForOption(option) {
    const key = providerKey(option?.providerKey);
    return {
      ...(state.providers.get(key) || {}),
      key,
      name: option?.providerName || state.providers.get(key)?.name || key,
      logoUrl: option?.logoUrl || state.providers.get(key)?.logoUrl || "",
    };
  }

  function bookLogo(provider, alt = "") {
    if (!provider?.logoUrl) return "";
    return `<span class="futures-book-logo"><img src="${escape(provider.logoUrl)}" alt="${escape(alt)}" loading="lazy"></span>`;
  }

  function oddsText(option) {
    const american = asNumber(option?.americanOdds);
    if (american !== null) return american > 0 ? `+${Math.round(american)}` : `${Math.round(american)}`;
    return String(option?.displayOdds || "—");
  }

  function optionLimit(option) {
    const limit = asNumber(option?.betLimit);
    const liquidity = asNumber(option?.availableLiquidity);
    const amount = limit ?? liquidity;
    if (amount === null || amount <= 0) return "";
    if (amount >= 1000) return `$${(amount / 1000).toFixed(amount >= 10000 ? 0 : 1)}k`;
    return `$${Math.round(amount).toLocaleString()}`;
  }

  function exactOptions(row, selectedOnly = true) {
    const selected = new Set(state.selectedProviders);
    return (row?.executionOptions || []).filter(option => {
      const key = providerKey(option?.providerKey);
      return (!selectedOnly || selected.has(key))
        && option?.matchingConfidence === "Exact"
        && option?.isAvailable !== false
        && option?.isStale !== true
        && (!option?.marketStatus || String(option.marketStatus).toUpperCase() === "OPEN")
        && asNumber(option?.bestExecutablePrice) !== null;
    });
  }

  function bestOption(row) {
    return exactOptions(row).sort((left, right) => {
      const leftPrice = asNumber(left.bestExecutablePrice) ?? 2;
      const rightPrice = asNumber(right.bestExecutablePrice) ?? 2;
      if (leftPrice !== rightPrice) return leftPrice - rightPrice;
      return state.selectedProviders.indexOf(providerKey(left.providerKey)) - state.selectedProviders.indexOf(providerKey(right.providerKey));
    })[0] || null;
  }

  function optionForProvider(row, key) {
    return exactOptions(row, false)
      .filter(option => providerKey(option.providerKey) === key)
      .sort((left, right) => (asNumber(left.bestExecutablePrice) ?? 2) - (asNumber(right.bestExecutablePrice) ?? 2))[0] || null;
  }

  function priceMarkup(option, {best = false} = {}) {
    if (!option) return `<span class="futures-price empty" aria-label="No price"><strong>—</strong></span>`;
    const provider = providerForOption(option);
    const secondary = optionLimit(option);
    const content = `${best ? bookLogo(provider, provider.name) : ""}<span><strong>${escape(oddsText(option))}</strong>${secondary ? `<small>${escape(secondary)} ${asNumber(option.betLimit) !== null ? "limit" : "available"}</small>` : ""}</span>`;
    const className = best ? "futures-best-price" : "futures-price";
    const title = `${provider.name} ${oddsText(option)}${secondary ? ` · ${secondary}` : ""}`;
    if (!option.deepLink) return `<span class="${className}" title="${escape(title)}">${content}</span>`;
    return `<a class="${className}" href="${escape(option.deepLink)}" target="_blank" rel="noopener noreferrer" title="Open ${escape(title)}">${content}</a>`;
  }

  function teamLogo(row) {
    const logoUrl = typeof window.oddsTeamLogoUrl === "function" ? window.oddsTeamLogoUrl(row?.outcome) : "";
    return logoUrl ? `<span class="futures-team-logo"><img src="${escape(logoUrl)}" alt="" loading="lazy"></span>` : "";
  }

  function eventDate(row) {
    const date = new Date(row?.resolution_time || row?.event_date_et || 0);
    if (Number.isNaN(date.getTime())) return "Settlement date TBD";
    return `Settles ${date.toLocaleDateString([], {month: "short", day: "numeric", year: "numeric"})}`;
  }

  function marketGroupKey(row) {
    return `${row?.event_id || "event"}|${row?.market_id || row?.market_title || "market"}`;
  }

  function filteredRows() {
    const query = normalized(state.search);
    const rows = state.rows.filter(row => {
      if (state.league && normalized(row.canonical_league_id || row.league) !== normalized(state.league)) return false;
      if (state.market && String(row.market_title || "") !== state.market) return false;
      if (!query) return true;
      return normalized(`${row.outcome || ""} ${row.market_title || ""} ${row.event_title || ""} ${row.future_type || ""} ${row.league || ""}`).includes(query);
    });
    const groups = new Map();
    rows.forEach(row => {
      const key = marketGroupKey(row);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(row);
    });
    groups.forEach(group => group.sort((left, right) => {
      if (state.sort === "name") return String(left.outcome || "").localeCompare(String(right.outcome || ""));
      const leftBest = bestOption(left);
      const rightBest = bestOption(right);
      const leftProbability = asNumber(leftBest?.bestExecutablePrice) ?? -1;
      const rightProbability = asNumber(rightBest?.bestExecutablePrice) ?? -1;
      if (state.sort === "probability") return leftProbability - rightProbability;
      return rightProbability - leftProbability || String(left.outcome || "").localeCompare(String(right.outcome || ""));
    }));
    const orderedGroups = [...groups.values()];
    if (state.sort === "market") {
      orderedGroups.sort((left, right) => String(left[0]?.market_title || "").localeCompare(String(right[0]?.market_title || "")));
    }
    return orderedGroups;
  }

  function providerCoverage() {
    const counts = new Map();
    state.rows.forEach(row => (row.executionOptions || []).forEach(option => {
      const key = providerKey(option.providerKey);
      if (key && option?.isAvailable !== false) counts.set(key, (counts.get(key) || 0) + 1);
    }));
    return counts;
  }

  function savedProviders() {
    try {
      const parsed = JSON.parse(localStorage.getItem(storageKey) || "null");
      return Array.isArray(parsed) ? parsed.map(providerKey).filter(Boolean) : null;
    } catch (_) {
      return null;
    }
  }

  function chooseInitialProviders() {
    const available = new Set([...state.providers.keys()]);
    const saved = savedProviders();
    if (saved?.some(key => available.has(key))) {
      state.selectedProviders = saved.filter(key => available.has(key));
      return;
    }
    const coverage = providerCoverage();
    state.selectedProviders = [...available]
      .sort((left, right) => (coverage.get(right) || 0) - (coverage.get(left) || 0) || String(state.providers.get(left)?.name || left).localeCompare(String(state.providers.get(right)?.name || right)))
      .slice(0, 10);
  }

  function renderProviderPicker() {
    const options = document.getElementById("futures-book-options");
    if (!options) return;
    const coverage = providerCoverage();
    const ordered = [...state.providers.values()].sort((left, right) => (coverage.get(right.key) || 0) - (coverage.get(left.key) || 0) || String(left.name || "").localeCompare(String(right.name || "")));
    options.innerHTML = ordered.map(provider => `<label><input type="checkbox" value="${escape(provider.key)}" ${state.selectedProviders.includes(provider.key) ? "checked" : ""}>${bookLogo(provider)}<span>${escape(provider.name || provider.key)}</span></label>`).join("");
    const label = document.getElementById("futures-books-label");
    if (label) label.textContent = state.selectedProviders.length === ordered.length ? "All books" : `${state.selectedProviders.length} of ${ordered.length}`;
  }

  function renderProviderHeaders() {
    const head = document.getElementById("futures-table-head");
    if (!head) return;
    head.querySelectorAll(".futures-provider-head").forEach(item => item.remove());
    state.selectedProviders.forEach(key => {
      const provider = state.providers.get(key) || {key, name: key};
      const th = document.createElement("th");
      th.className = "futures-provider-head";
      th.scope = "col";
      th.dataset.provider = key;
      th.innerHTML = `<span>${bookLogo(provider, provider.name)}</span><small>${escape(provider.name || key)}</small>`;
      head.appendChild(th);
    });
  }

  function rowMarkup(row) {
    const best = bestOption(row);
    return `<tr class="futures-selection-row">
      <td class="futures-selection-cell"><div class="futures-selection-main">${teamLogo(row)}<span class="futures-selection-copy"><strong>${escape(row.outcome || "Selection")}</strong><small>${escape(row.market_title || row.future_type || "Futures")}</small></span></div></td>
      <td class="futures-best-cell">${priceMarkup(best, {best: true})}</td>
      ${state.selectedProviders.map(key => `<td class="futures-price-cell">${priceMarkup(optionForProvider(row, key))}</td>`).join("")}
    </tr>`;
  }

  function groupMarkup(rows) {
    const first = rows[0] || {};
    const colspan = Math.max(2, state.selectedProviders.length + 2);
    const marketName = first.market_title || first.event_title || "Futures";
    const eventName = first.event_title && first.event_title !== marketName ? first.event_title : "";
    return `<tr class="futures-market-divider"><td colspan="${colspan}"><div class="futures-market-heading"><span><span class="futures-league-badge">${escape(first.canonical_league_id || first.league || "ALL")}</span><strong>${escape(marketName)}</strong>${eventName ? `<small>${escape(eventName)}</small>` : ""}</span><small>${escape(eventDate(first))} · ${rows.length} selection${rows.length === 1 ? "" : "s"}</small></div></td></tr>${rows.map(rowMarkup).join("")}`;
  }

  function updateContext(groups) {
    const selectionCount = groups.reduce((total, rows) => total + rows.length, 0);
    const title = state.market || (state.league ? `${state.league} futures` : "All available futures");
    const subtitle = [state.league || "Every league", state.market || `${groups.length} market${groups.length === 1 ? "" : "s"}`].join(" · ");
    document.getElementById("futures-board-title").textContent = title;
    document.getElementById("futures-board-subtitle").textContent = subtitle;
    document.getElementById("futures-results-label").textContent = `${selectionCount.toLocaleString()} selection${selectionCount === 1 ? "" : "s"} across ${groups.length.toLocaleString()} market${groups.length === 1 ? "" : "s"}`;
  }

  function renderBoard() {
    renderProviderHeaders();
    const groups = filteredRows();
    const body = document.getElementById("futures-table-body");
    const colspan = Math.max(2, state.selectedProviders.length + 2);
    if (!groups.length) {
      const notConfigured = state.payload?.configured === false;
      body.innerHTML = `<tr class="futures-state-row"><td colspan="${colspan}"><div class="futures-empty"><i class="ph ${notConfigured ? "ph-plugs-connected" : "ph-magnifying-glass"}" aria-hidden="true"></i><strong>${notConfigured ? "OddsEngine is not configured" : "No futures match these filters"}</strong><small>${escape(notConfigured ? state.payload?.message || "Add the production OddsEngine key to load the live inventory." : "Try another league, market, sportsbook set, or search term.")}</small>${notConfigured ? "" : `<button type="button" id="futures-reset">Reset filters</button>`}</div></td></tr>`;
    } else {
      body.innerHTML = groups.map(groupMarkup).join("");
    }
    updateContext(groups);
    document.getElementById("futures-reset")?.addEventListener("click", resetFilters);
  }

  function leagueOptionMarkup(league) {
    return `<option value="${escape(league)}">${escape(league)}</option>`;
  }

  function leagueTabMarkup(league) {
    const logo = leagueAsset[league];
    const icon = logo ? `<img src="${escape(logo)}" alt="">` : `<i class="ph ph-trophy" aria-hidden="true"></i>`;
    return `<button type="button" data-futures-league="${escape(league)}" aria-pressed="false">${icon}${escape(league)}</button>`;
  }

  function syncFilters(payload) {
    const leagues = [...new Set((payload.leagues || state.rows.map(row => row.canonical_league_id || row.league)).filter(Boolean).map(value => String(value).toUpperCase()))].sort();
    const markets = [...new Set((payload.markets || state.rows.map(row => row.market_title)).filter(Boolean).map(String))].sort((left, right) => left.localeCompare(right));
    const leagueSelect = document.getElementById("futures-league");
    const marketSelect = document.getElementById("futures-market");
    leagueSelect.innerHTML = `<option value="">All leagues</option>${leagues.map(leagueOptionMarkup).join("")}`;
    marketSelect.innerHTML = `<option value="">All futures</option>${markets.map(market => `<option value="${escape(market)}">${escape(market)}</option>`).join("")}`;
    leagueSelect.value = leagues.includes(state.league) ? state.league : "";
    marketSelect.value = markets.includes(state.market) ? state.market : "";
    document.getElementById("futures-league-tabs").innerHTML = `<button class="${state.league ? "" : "active"}" type="button" data-futures-league="" aria-pressed="${String(!state.league)}"><i class="ph ph-globe-hemisphere-west" aria-hidden="true"></i>All markets</button>${leagues.map(leagueTabMarkup).join("")}`;
    syncLeagueControls();
  }

  function syncLeagueControls() {
    const leagueSelect = document.getElementById("futures-league");
    if (leagueSelect) leagueSelect.value = state.league;
    document.querySelectorAll("[data-futures-league]").forEach(button => {
      const active = button.dataset.futuresLeague === state.league;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    const icon = document.getElementById("futures-league-icon");
    const url = leagueAsset[state.league] || "/static/assets/leagues/mlb.png";
    if (icon) { icon.src = url; icon.hidden = !state.league; }
  }

  function resetFilters() {
    state.league = "";
    state.market = "";
    state.search = "";
    document.getElementById("futures-market").value = "";
    document.getElementById("futures-search").value = "";
    document.getElementById("futures-search-clear").hidden = true;
    syncLeagueControls();
    renderBoard();
  }

  function applyPayload(payload) {
    state.payload = payload;
    state.rows = Array.isArray(payload.data) ? payload.data : [];
    (payload.providers || []).forEach(provider => {
      const key = providerKey(provider.key);
      if (key) state.providers.set(key, {...provider, key});
    });
    const availableKeys = new Set(state.rows.flatMap(row => (row.executionOptions || []).map(option => providerKey(option.providerKey))).filter(Boolean));
    state.providers = new Map([...state.providers].filter(([key]) => availableKeys.has(key)));
    if (!state.selectedProviders.length) chooseInitialProviders();
    else state.selectedProviders = state.selectedProviders.filter(key => state.providers.has(key));
    if (!state.selectedProviders.length && state.providers.size) chooseInitialProviders();
    renderProviderPicker();
    syncFilters(payload);
    renderBoard();

    const markets = new Set(state.rows.map(row => marketGroupKey(row))).size;
    document.getElementById("futures-market-count").textContent = markets.toLocaleString();
    document.getElementById("futures-selection-count").textContent = state.rows.length.toLocaleString();
    document.getElementById("futures-book-count").textContent = state.providers.size.toLocaleString();
    const status = document.getElementById("futures-live-status");
    status.classList.toggle("live", payload.complete !== false && payload.configured !== false);
    status.classList.toggle("degraded", payload.complete === false && payload.configured !== false);
    status.querySelector("strong").textContent = payload.configured === false ? "Not configured" : payload.complete === false ? "Partial inventory" : "Live inventory";
    document.getElementById("futures-inventory-state").innerHTML = `<i class="ph ${payload.complete === false ? "ph-warning-circle" : "ph-database"}" aria-hidden="true"></i>${escape(payload.complete === false ? "Partial API inventory" : "Complete API inventory")}`;
    const updated = new Date(payload.generatedAt || Date.now());
    document.getElementById("futures-updated-label").innerHTML = `<i class="ph ph-clock" aria-hidden="true"></i>${Number.isNaN(updated.getTime()) ? "Snapshot loaded" : `Updated ${escape(updated.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"}))}`}`;
  }

  async function loadFutures({force = false} = {}) {
    if (state.loading) return;
    state.loading = true;
    const refresh = document.getElementById("futures-refresh");
    refresh?.classList.add("loading");
    refresh?.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(`/api/futures?active=1${force ? `&_=${Date.now()}` : ""}`, {headers: {Accept: "application/json"}});
      const payload = await response.json().catch(() => ({}));
      if (!response.ok && !Array.isArray(payload.data)) throw new Error(payload.message || `Futures request failed (${response.status})`);
      applyPayload(payload);
    } catch (error) {
      applyPayload({configured: true, complete: false, data: [], providers: [], leagues: [], markets: [], message: error.message});
      document.getElementById("futures-live-status")?.classList.add("degraded");
    } finally {
      state.loading = false;
      refresh?.classList.remove("loading");
      refresh?.removeAttribute("aria-busy");
    }
  }

  function closeBooks() {
    const popover = document.getElementById("futures-books-popover");
    const trigger = document.getElementById("futures-books-trigger");
    if (popover) popover.hidden = true;
    trigger?.setAttribute("aria-expanded", "false");
  }

  function bindControls() {
    document.getElementById("futures-league")?.addEventListener("change", event => { state.league = event.target.value; syncLeagueControls(); renderBoard(); });
    document.getElementById("futures-market")?.addEventListener("change", event => { state.market = event.target.value; renderBoard(); });
    document.getElementById("futures-sort")?.addEventListener("change", event => { state.sort = event.target.value; renderBoard(); });
    document.getElementById("futures-search")?.addEventListener("input", event => {
      state.search = event.target.value;
      document.getElementById("futures-search-clear").hidden = !state.search;
      renderBoard();
    });
    document.getElementById("futures-search-clear")?.addEventListener("click", () => {
      state.search = "";
      const input = document.getElementById("futures-search");
      input.value = "";
      document.getElementById("futures-search-clear").hidden = true;
      input.focus();
      renderBoard();
    });
    document.getElementById("futures-league-tabs")?.addEventListener("click", event => {
      const button = event.target.closest("[data-futures-league]");
      if (!button) return;
      state.league = button.dataset.futuresLeague || "";
      syncLeagueControls();
      renderBoard();
    });
    document.getElementById("futures-refresh")?.addEventListener("click", () => loadFutures({force: true}));
    document.getElementById("futures-books-trigger")?.addEventListener("click", event => {
      event.stopPropagation();
      const popover = document.getElementById("futures-books-popover");
      const opening = popover.hidden;
      popover.hidden = !opening;
      document.getElementById("futures-books-trigger").setAttribute("aria-expanded", String(opening));
    });
    document.getElementById("futures-books-popover")?.addEventListener("click", event => event.stopPropagation());
    document.getElementById("futures-books-close")?.addEventListener("click", closeBooks);
    document.getElementById("futures-books-all")?.addEventListener("click", () => document.querySelectorAll("#futures-book-options input").forEach(input => { input.checked = true; }));
    document.getElementById("futures-books-none")?.addEventListener("click", () => document.querySelectorAll("#futures-book-options input").forEach(input => { input.checked = false; }));
    document.getElementById("futures-books-apply")?.addEventListener("click", () => {
      const selected = [...document.querySelectorAll("#futures-book-options input:checked")].map(input => input.value);
      if (!selected.length) return;
      state.selectedProviders = selected;
      try { localStorage.setItem(storageKey, JSON.stringify(selected)); } catch (_) { /* Storage can be unavailable in private browsing. */ }
      renderProviderPicker();
      closeBooks();
      renderBoard();
    });
    document.addEventListener("click", event => { if (!event.target.closest(".futures-book-filter")) closeBooks(); });
    document.addEventListener("keydown", event => { if (event.key === "Escape") closeBooks(); });
  }

  bindControls();
  loadFutures();
})();
