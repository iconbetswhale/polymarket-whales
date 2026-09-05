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
    stakeMode: "total",
    sort: "cost-asc",
    requiredBook: "",
  };
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(storageKey) || "{}"); } catch (_) { saved = {}; }

  const initialBookKeys = Array.isArray(saved.books) && saved.books.length ? saved.books : defaults.books;
  const initialRequiredBook = typeof saved.requiredBook === "string" && initialBookKeys.includes(saved.requiredBook)
    ? saved.requiredBook
    : defaults.requiredBook;

  const state = {
    rows: [],
    selectedId: "",
    search: "",
    sport: "",
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
    stakeMode: ["total", "first-leg"].includes(saved.stakeMode) ? saved.stakeMode : defaults.stakeMode,
    sort: ["cost-asc", "width-desc", "profit-desc", "time-asc"].includes(saved.sort) ? saved.sort : defaults.sort,
    requiredBook: initialRequiredBook,
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
    stakeMode: document.getElementById("mid-stake-mode"),
    scan: document.getElementById("mid-scan-toggle"),
    alerts: document.getElementById("mid-alerts"),
    refresh: document.getElementById("mid-refresh"),
    sport: document.getElementById("mid-sport"),
    sportTrigger: document.getElementById("mid-sport-trigger"),
    sportValue: document.getElementById("mid-sport-value"),
    sportMenu: document.getElementById("mid-sport-menu"),
    sort: document.getElementById("mid-sort"),
    sortTrigger: document.getElementById("mid-sort-trigger"),
    sortValue: document.getElementById("mid-sort-value"),
    sortMenu: document.getElementById("mid-sort-menu"),
    requiredBookTrigger: document.getElementById("mid-required-book-trigger"),
    requiredBookValue: document.getElementById("mid-required-book-value"),
    requiredBookMenu: document.getElementById("mid-required-book-menu"),
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

  function decimalOdds(value) {
    const amount = Number(value || 0);
    if (!amount) return 1;
    return amount > 0 ? 1 + (amount / 100) : 1 + (100 / Math.abs(amount));
  }

  function quotePrice(quote) {
    const effectivePrice = Number(quote?.effectiveDecimalOdds);
    return Number.isFinite(effectivePrice) && effectivePrice > 0
      ? effectivePrice
      : decimalOdds(quote?.americanOdds);
  }

  function sortQuotesByBestPrice(quotes, selectedBookKey) {
    return [...(quotes || [])]
      .map((quote, index) => ({ quote, index }))
      .sort((left, right) => {
        const priceDifference = quotePrice(right.quote) - quotePrice(left.quote);
        if (Math.abs(priceDifference) > Number.EPSILON) return priceDifference;
        const leftSelected = left.quote.bookKey === selectedBookKey;
        const rightSelected = right.quote.bookKey === selectedBookKey;
        if (leftSelected !== rightSelected) return leftSelected ? -1 : 1;
        return left.index - right.index;
      })
      .map(({ quote }) => quote);
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

  const leagueLogos = Object.freeze({
    nba: "/static/assets/leagues/nba.png",
    nationalbasketballassociation: "/static/assets/leagues/nba.png",
    mlb: "/static/assets/leagues/mlb.png",
    majorleaguebaseball: "/static/assets/leagues/mlb.png",
    mls: "/static/assets/leagues/mls.png",
    majorleaguesoccer: "/static/assets/leagues/mls.png",
    wnba: "/static/assets/leagues/wnba.png",
    womensnationalbasketballassociation: "/static/assets/leagues/wnba.png",
    wta: "/static/assets/leagues/wta.png",
    wtatour: "/static/assets/leagues/wta.png",
    nhl: "/static/assets/leagues/nhl.png",
    nationalhockeyleague: "/static/assets/leagues/nhl.png",
    atp: "/static/assets/leagues/atp.png",
    atptour: "/static/assets/leagues/atp.png",
    ncaa: "/static/assets/leagues/ncaa.png",
    ncaab: "/static/assets/leagues/ncaa.png",
    ncaamb: "/static/assets/leagues/ncaa.png",
    ncaaw: "/static/assets/leagues/ncaa.png",
    ncaaf: "/static/assets/leagues/ncaa.png",
    collegebasketball: "/static/assets/leagues/ncaa.png",
    collegefootball: "/static/assets/leagues/ncaa.png",
    nfl: "/static/assets/leagues/nfl.png",
    nationalfootballleague: "/static/assets/leagues/nfl.png",
    fifa: "/static/assets/leagues/fifa.png",
    fifaworldcup: "/static/assets/leagues/fifa.png",
    uefa: "/static/assets/leagues/uefa.png",
    uefachampionsleague: "/static/assets/leagues/uefa.png",
    epl: "/static/assets/leagues/epl.png",
    premierleague: "/static/assets/leagues/epl.png",
    englishpremierleague: "/static/assets/leagues/epl.png",
  });

  function leagueLogoUrl(sportKey, league) {
    const canonical = (value) => String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
    return leagueLogos[canonical(league)] || leagueLogos[canonical(sportKey)] || "";
  }

  function teamLogoUrl(row, team) {
    const logos = row?.participantLogos || row?.participant_logos || row?.teamLogos || row?.team_logos || {};
    const normalizedTeam = String(team || "").trim().toLowerCase();
    return logos[team] || logos[normalizedTeam]
      || (typeof window.oddsTeamLogoUrl === "function" ? window.oddsTeamLogoUrl(team) : "");
  }

  function detailTeamLogo(row, team, className = "mid-detail-team-logo") {
    const logoUrl = teamLogoUrl(row, team);
    const leagueClass = String(row?.sportKey || "").toLowerCase().includes("wnba") ? " is-wnba" : "";
    return logoUrl
      ? `<span class="${esc(className)} mid-team-logo-frame${leagueClass}" aria-hidden="true"><img src="${esc(logoUrl)}" alt="" loading="lazy" onerror="this.parentElement.hidden=true"></span>`
      : "";
  }

  function detailMatchup(row) {
    const away = String(row?.awayTeam || "").trim();
    const home = String(row?.homeTeam || "").trim();
    if (!away || !home) return esc(row?.eventTitle || "Event");
    return `<span class="mid-detail-team mid-detail-team-away">${detailTeamLogo(row, away)}<span>${esc(away)}</span></span> <span class="mid-detail-vs">vs</span> <span class="mid-detail-team mid-detail-team-home"><span>${esc(home)}</span>${detailTeamLogo(row, home)}</span>`;
  }

  function queueLeagueVisual(row) {
    const logoUrl = leagueLogoUrl(row?.sportKey, row?.league);
    return logoUrl
      ? `<img class="mid-queue-league-logo" src="${esc(logoUrl)}" alt="" aria-hidden="true" loading="lazy">`
      : "";
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
      distinctBooks: state.distinctBooks, alerts: state.alerts, stake: state.stake,
      stakeMode: state.stakeMode, sort: state.sort, requiredBook: state.requiredBook,
    }));
  }

  function logoMarkup(row) {
    const logo = String(row.logoUrl || "");
    if (logo) return `<span class="mid-book-logo"><img src="${esc(logo)}" alt="" decoding="async" onerror="this.hidden=true;this.parentElement.classList.add('mid-book-logo-fallback');this.nextElementSibling.hidden=false"><i class="ph ph-buildings" aria-hidden="true" hidden></i></span>`;
    return `<span class="mid-book-logo mid-book-logo-fallback"><i class="ph ph-buildings" aria-hidden="true"></i></span>`;
  }

  function rowMatches(row) {
    if (state.sport && row.sportKey !== state.sport) return false;
    if (state.requiredBook && !(row.booksUsed || []).includes(state.requiredBook)) return false;
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
          <h3 title="${esc(row.eventTitle)}">${queueLeagueVisual(row)}<span>${esc(row.eventTitle)}</span></h3>
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
    document.getElementById("mid-summary-books").textContent = String(state.selectedBooks.size);
  }

  function quickOptionVisual(option) {
    if (option.logoUrl) return `<img src="${esc(option.logoUrl)}" alt="" aria-hidden="true" loading="lazy" onerror="this.hidden=true">`;
    return `<i class="ph ${esc(option.icon || "ph-circle")}" aria-hidden="true"></i>`;
  }

  function renderQuickSelect(kind, options, selectedValue) {
    const capitalizedKind = kind === "required-book" ? "requiredBook" : kind;
    const menu = elements[`${capitalizedKind}Menu`];
    const value = elements[`${capitalizedKind}Value`];
    const selected = options.find((option) => option.value === selectedValue) || options[0];
    if (!menu || !value || !selected) return;
    value.innerHTML = `${quickOptionVisual(selected)}<span>${esc(selected.label)}</span>`;
    menu.innerHTML = options.map((option) => `<button type="button" role="option" aria-selected="${option.value === selected.value ? "true" : "false"}" data-mid-quick-option="${esc(kind)}" data-mid-quick-value="${esc(option.value)}">${quickOptionVisual(option)}<span>${esc(option.label)}</span><i class="ph ph-check" aria-hidden="true"></i></button>`).join("");
  }

  function populateQuickFilters() {
    const currentSport = state.sport;
    const sports = [...new Map(state.rows.map((row) => [row.sportKey, row.league])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
    state.sport = sports.some(([key]) => key === currentSport) ? currentSport : "";
    elements.sport.innerHTML = '<option value="">All sports</option>' + sports.map(([key, label]) => `<option value="${esc(key)}">${esc(label)}</option>`).join("");
    elements.sport.value = state.sport;
    renderQuickSelect("sport", [
      { value: "", label: "All sports", icon: "ph-trophy" },
      ...sports.map(([value, label]) => ({ value, label, logoUrl: leagueLogoUrl(value, label), icon: "ph-trophy" })),
    ], state.sport);

    const sortOptions = [
      { value: "cost-asc", label: "Lowest break-even", icon: "ph-sort-ascending" },
      { value: "width-desc", label: "Widest window", icon: "ph-arrows-out-line-vertical" },
      { value: "profit-desc", label: "Highest middle profit", icon: "ph-trend-up" },
      { value: "time-asc", label: "Starting soon", icon: "ph-clock-countdown" },
    ];
    elements.sort.value = state.sort;
    renderQuickSelect("sort", sortOptions, state.sort);

    if (state.requiredBook && !state.selectedBooks.has(state.requiredBook)) state.requiredBook = "";
    const selectedBookOptions = eligibleBooks
      .filter((book) => state.selectedBooks.has(book.key))
      .map((book) => ({ value: book.key, label: book.name, logoUrl: book.logoUrl }));
    renderQuickSelect("required-book", [
      { value: "", label: "Any selected book", icon: "ph-buildings" },
      ...selectedBookOptions,
    ], state.requiredBook);
  }

  function closeQuickSelects(except = "") {
    document.querySelectorAll("[data-mid-quick-select]").forEach((container) => {
      if (container.dataset.midQuickSelect === except) return;
      container.classList.remove("is-open");
      container.querySelector(".mid-quick-select-trigger")?.setAttribute("aria-expanded", "false");
      const menu = container.querySelector(".mid-quick-select-menu");
      if (menu) menu.hidden = true;
    });
  }

  function toggleQuickSelect(container) {
    const trigger = container.querySelector(".mid-quick-select-trigger");
    const menu = container.querySelector(".mid-quick-select-menu");
    const shouldOpen = Boolean(menu?.hidden);
    closeQuickSelects();
    if (!shouldOpen || !menu || !trigger) return;
    container.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
    menu.hidden = false;
    menu.querySelector('[aria-selected="true"]')?.focus({ preventScroll: true });
  }

  function chooseQuickOption(kind, value) {
    if (kind === "required-book") {
      state.requiredBook = state.selectedBooks.has(value) ? value : "";
      saveSettings();
      closeQuickSelects();
      populateQuickFilters();
      loadBoard();
      return;
    }
    if (kind === "sport") {
      state.sport = value;
      elements.sport.value = value;
    }
    if (kind === "sort") {
      state.sort = value;
      elements.sort.value = value;
      saveSettings();
    }
    closeQuickSelects();
    renderAll();
  }

  function quoteRow(quote, bestKey) {
    const best = quote.bookKey === bestKey;
    const age = quote.quoteAgeSeconds == null ? "Age n/a" : `${Math.round(quote.quoteAgeSeconds)}s old`;
    return `<div class="mid-quote-row${best ? " best" : ""}">${logoMarkup(quote)}<span><strong>${esc(quote.bookName)}</strong><small>${esc(age)}</small></span><b>${odds(quote.americanOdds)}</b>${quote.deepLink ? `<a href="${esc(quote.deepLink)}" target="_blank" rel="noopener noreferrer" aria-label="Open ${esc(quote.bookName)}"><i class="ph ph-arrow-square-out" aria-hidden="true"></i></a>` : ""}</div>`;
  }

  function curveTick(value, signed = false) {
    const rounded = Math.round(Number(value) * 100) / 100;
    const normalized = Object.is(rounded, -0) ? 0 : rounded;
    const compact = Number.isInteger(normalized) ? String(normalized) : String(Number(normalized.toFixed(2)));
    return `${signed && normalized > 0 ? "+" : ""}${compact}`;
  }

  function payoutRangeMap(row, legs, worstOutside) {
    const low = Number(row.window?.low);
    const high = Number(row.window?.high);
    const validWindow = Number.isFinite(low) && Number.isFinite(high) && high > low;
    const safeLow = validWindow ? low : 0;
    const safeHigh = validWindow ? high : Math.max(1, Number(row.middleWidth || 1));
    const outerSpan = Math.max(safeHigh - safeLow, 0.5);
    const tickValues = [
      safeLow - outerSpan,
      safeLow,
      (safeLow + safeHigh) / 2,
      safeHigh,
      safeHigh + outerSpan,
    ];
    const signedTicks = row.window?.kind === "spread";
    const upperWinner = legs[0]?.selection ? `${legs[0].selection} wins` : "Upper result";
    const lowerWinner = legs[1]?.selection ? `${legs[1].selection} wins` : "Lower result";
    const axisLabel = row.marketContext
      ? `${row.marketContext} result`
      : row.window?.kind === "spread" ? "Final margin" : "Final total";
    const profit = signedMoney(row.middleProfit);
    const loss = signedMoney(worstOutside);
    const middleWidth = Number(row.middleWidth || 0);
    const middleWidthLabel = `${middleWidth} ${middleWidth === 1 ? "pt" : "pts"} middle window`;
    const lowLabel = curveTick(safeLow, signedTicks);
    const highLabel = curveTick(safeHigh, signedTicks);
    const accessibleSummary = `Both bets win for a net profit of ${profit} when the result lands between ${lowLabel} and ${highLabel}. Outside that middle window, the worst-case result is ${loss}.`;
    return `
      <div class="mid-range-map" role="img" aria-label="${esc(accessibleSummary)}">
        <div class="mid-range-labels" aria-hidden="true">
          <div><strong>Below ${lowLabel}</strong><span>${esc(lowerWinner)}</span></div>
          <div class="positive"><strong>${lowLabel} to ${highLabel}</strong><span>Both bets win</span></div>
          <div><strong>Above ${highLabel}</strong><span>${esc(upperWinner)}</span></div>
        </div>
        <div class="mid-range-scale" aria-hidden="true">
          <span class="start">${curveTick(tickValues[0], signedTicks)}</span>
          <span class="low">${curveTick(tickValues[1], signedTicks)}</span>
          <span class="middle">${curveTick(tickValues[2], signedTicks)}</span>
          <span class="high">${curveTick(tickValues[3], signedTicks)}</span>
          <span class="end">${curveTick(tickValues[4], signedTicks)}</span>
        </div>
        <div class="mid-range-track" aria-hidden="true">
          <div class="mid-range-zone mid-range-loss"><strong>${loss}</strong><span>${esc(lowerWinner)}</span></div>
          <div class="mid-range-zone mid-range-middle"><small>Both bets win</small><strong>${profit}</strong><span>${middleWidthLabel}</span></div>
          <div class="mid-range-zone mid-range-loss"><strong>${loss}</strong><span>${esc(upperWinner)}</span></div>
          <i class="ph ph-record mid-range-marker edge start" aria-hidden="true"></i>
          <i class="ph ph-record mid-range-marker low" aria-hidden="true"></i>
          <i class="ph ph-record mid-range-marker high" aria-hidden="true"></i>
          <i class="ph ph-record mid-range-marker edge end" aria-hidden="true"></i>
        </div>
        <div class="mid-range-axis-label">${esc(axisLabel)}</div>
      </div>`;
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
        ${leg.deepLink ? `<a class="mid-book-link" href="${esc(leg.deepLink)}" target="_blank" rel="noopener noreferrer" aria-label="Bet ${esc(leg.selection)} at ${esc(leg.bookName)}">BET<i class="ph ph-arrow-up-right" aria-hidden="true"></i></a>` : '<span class="mid-book-link disabled" aria-disabled="true">BET</span>'}
      </article>`).join("");
    const comparisons = (row.allQuotes || []).map((group) => {
      const quotes = sortQuotesByBestPrice(group.quotes, group.bestBookKey);
      return `<section class="mid-quote-group"><header><span>${esc(group.selection)}</span><small>Best price first</small></header>${quotes.map((quote) => quoteRow(quote, group.bestBookKey)).join("")}</section>`;
    }).join("");
    const warnings = (row.warnings || []).map((warning) => `<div class="mid-detail-warning"><i class="ph ph-warning" aria-hidden="true"></i><span>${esc(warning)}</span></div>`).join("");
    const worstOutside = Math.min(...legs.map((leg) => Number(leg.outsideProfit || 0)));
    const probabilitySummary = row.probabilityModel?.status === "AVAILABLE"
      ? `<div><span>Market-implied middle</span><strong>${percent(row.estimatedMiddleProbability)}</strong><small>${Number(row.estimatedEvPercent) >= 0 ? "+" : ""}${percent(row.estimatedEvPercent)} estimated EV · ${row.probabilityModel.method === "DEVIGGED_MARKET_LADDER_CDF" ? "de-vigged line ladder" : esc(row.probabilityModel.method || "model")}</small></div>`
      : `<div><span>Middle probability</span><strong>Unavailable</strong><small>${esc(row.probabilityModel?.reason || "No paired line ladder")}</small></div>`;
    const payoutRangeMarkup = payoutRangeMap(row, legs, worstOutside);
    elements.detail.innerHTML = `
      <header class="mid-detail-header">
        <div class="mid-detail-main"><div class="mid-detail-hero-top"><div class="mid-detail-return"><strong>${percent(row.breakEvenMiddleProbability)}</strong><span>break-even middle</span></div><button type="button" data-mid-mobile-close aria-label="Close details"><i class="ph ph-x" aria-hidden="true"></i></button></div><h2 class="mid-detail-matchup">${detailMatchup(row)}</h2><p>${esc(row.league)} · ${esc(row.marketLabel)} · ${esc(dateTime(row.commenceTime))}</p></div>
        <dl class="mid-detail-facts"><div><dt>Middle window</dt><dd>${esc(row.window?.label || `${row.middleWidth} pts`)}</dd></div><div><dt>Worst case</dt><dd class="${worstOutside >= 0 ? "positive" : "warning"}">${signedMoney(worstOutside)}</dd></div><div><dt>Best case</dt><dd class="positive">${signedMoney(row.middleProfit)}</dd></div></dl>
        <div class="mid-detail-actions"><button class="mid-button primary" id="mid-track" type="button"><i class="ph ${tracked ? "ph-bookmark-simple-fill" : "ph-bookmark-simple"}" aria-hidden="true"></i>${tracked ? "Tracked" : "Track pair"}</button><button class="mid-button ghost" id="mid-copy-plan" type="button"><i class="ph ph-copy" aria-hidden="true"></i>Copy plan</button></div>
      </header>
      <section class="mid-detail-section mid-stake-plan-section"><header><h3>Equalized Bets</h3><strong>${money(row.totalStake)}</strong></header><div class="mid-plan-head"><span>Outcome</span><span>Book</span><span>Odds</span><span>Bet</span><span>Payout</span><span class="sr-only">Action</span></div><div class="mid-plan-grid">${legCards}</div></section>
      <section class="mid-detail-section mid-payout-section"><header><h3>Payout Scenarios</h3><span class="mid-cost-badge ${row.guaranteedOutsideProfit ? "positive" : "warning"}">${percent(row.breakEvenMiddleProbability)} break-even</span></header><div class="mid-range-layout"><div class="mid-detail-summary mid-range-summary"><div><span>Middle window</span><strong>${esc(row.window?.label || "")}</strong><small>${row.middleWidth} pts</small></div><div><span>Worst case</span><strong class="${worstOutside >= 0 ? "positive" : "negative"}">${signedMoney(worstOutside)}</strong><small>${percent(row.costPercent)} cost</small></div>${probabilitySummary}</div><div class="mid-range-scroll">${payoutRangeMarkup}</div></div></section>
      <section class="mid-detail-section mid-available-odds"><header><h3>Available Odds</h3><small>${row.bookCount} books</small></header><div class="mid-quote-groups">${comparisons}</div></section>
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
    if (state.requiredBook) params.set("required_book", state.requiredBook);
    params.set("markets", state.markets.join(","));
    params.set("stake", String(state.stake));
    params.set("stake_mode", state.stakeMode);
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
    if (state.requiredBook && !state.selectedBooks.has(state.requiredBook)) {
      state.requiredBook = "";
      notify("Required book reset to Any selected book because it is no longer selected.");
    }
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
    state.requiredBook = defaults.requiredBook;
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
      ...row.legs.map((leg, index) => `Leg ${index + 1}: ${leg.selection} ${odds(leg.americanOdds)} at ${leg.bookName} — bet ${money(leg.stake)}`),
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

  function syncStakeModeUI() {
    const baselineMode = state.stakeMode === "first-leg";
    elements.stakeMode.value = state.stakeMode;
    elements.stake.setAttribute("aria-label", baselineMode ? "Baseline Amount" : "Total Bet");
  }

  function bind() {
    elements.search.addEventListener("input", () => { state.search = elements.search.value; renderFeed(); });
    elements.sport.addEventListener("change", () => { state.sport = elements.sport.value; renderFeed(); });
    elements.sort.addEventListener("change", () => { state.sort = elements.sort.value; saveSettings(); renderFeed(); });
    document.querySelector(".mid-quick-filters")?.addEventListener("click", (event) => {
      const option = event.target.closest("[data-mid-quick-option]");
      if (option) {
        chooseQuickOption(option.dataset.midQuickOption, option.dataset.midQuickValue || "");
        return;
      }
      const trigger = event.target.closest(".mid-quick-select-trigger");
      if (trigger) toggleQuickSelect(trigger.closest("[data-mid-quick-select]"));
    });
    document.querySelector(".mid-quick-filters")?.addEventListener("keydown", (event) => {
      const option = event.target.closest("[data-mid-quick-option]");
      if (!option || !["ArrowDown", "ArrowUp"].includes(event.key)) return;
      event.preventDefault();
      const options = [...option.parentElement.querySelectorAll("[data-mid-quick-option]")];
      const step = event.key === "ArrowDown" ? 1 : -1;
      options[(options.indexOf(option) + step + options.length) % options.length]?.focus();
    });
    document.addEventListener("click", (event) => {
      if (!event.target.closest("[data-mid-quick-select]")) closeQuickSelects();
    });
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
    elements.stakeMode.addEventListener("change", () => {
      state.stakeMode = elements.stakeMode.value === "first-leg" ? "first-leg" : "total";
      syncStakeModeUI();
      saveSettings();
      loadBoard();
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
      if (event.key === "Escape") { closeQuickSelects(); closeMobileDetail(); }
    });
  }

  elements.stake.value = stakeInputValue(state.stake);
  syncStakeModeUI();
  syncScanButton();
  elements.alerts.setAttribute("aria-pressed", String(state.alerts));
  syncDialog();
  updateFilterCount();
  bind();
  loadBoard();
})();
