(() => {
  const pageRoot = document.querySelector(".mid-page");
  if (!pageRoot) return;

  const configNode = document.getElementById("mid-config");
  const config = configNode ? JSON.parse(configNode.textContent || "{}") : {};
  const popularBooks = new Set(["fanduel", "draftkings", "betmgm", "caesars", "fanatics", "bet365", "pinnacle", "novig", "hardrockbet", "betonline", "kalshi", "polymarket"]);
  const eligibleBooks = (config.books || []).filter((book) => book.type !== "dfs");
  const defaultBookKeys = eligibleBooks.filter((book) => book.defaultExecution !== false).map((book) => book.key);
  const configuredMiddleMarketKeys = Object.entries(config.marketGroups || {}).flatMap(([group, markets]) =>
    group === "main"
      ? (markets || []).filter((market) => (typeof market === "string" ? market : market?.key) !== "h2h")
      : (markets || [])
  ).map((market) => typeof market === "string" ? market : market?.key).filter(Boolean);
  const storageKey = "iconlabsMiddlesSettingsV3";
  const savedKey = "iconlabsMiddlesSavedFiltersV1";
  const trackedKey = "iconlabsTrackedMiddlesV1";
  const trackedPlanKey = "iconlabsTrackedMiddlePlansV1";
  const hiddenKey = "iconlabsHiddenMiddlesV1";
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
    preventDuplicateGameMarket: true,
    lineMovementWarning: false,
    liquidityWarning: false,
    settlementWarning: false,
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
    hasCompletedScan: false,
    error: "",
    view: "live",
    bookGroup: "all",
    selectedBooks: new Set(Array.isArray(saved.books) && saved.books.length ? saved.books : defaults.books),
    markets: Array.isArray(saved.markets) && saved.markets.length ? saved.markets : defaults.markets,
    minWidth: defaults.minWidth,
    maxCost: numberBetween(saved.maxCost, 0, 100, defaults.maxCost),
    maxAge: defaults.maxAge,
    commission: defaults.commission,
    distinctBooks: saved.distinctBooks === undefined ? defaults.distinctBooks : Boolean(saved.distinctBooks),
    preventDuplicateGameMarket: saved.preventDuplicateGameMarket === undefined ? defaults.preventDuplicateGameMarket : Boolean(saved.preventDuplicateGameMarket),
    lineMovementWarning: saved.lineMovementWarning === undefined ? defaults.lineMovementWarning : Boolean(saved.lineMovementWarning),
    liquidityWarning: saved.liquidityWarning === undefined ? defaults.liquidityWarning : Boolean(saved.liquidityWarning),
    settlementWarning: saved.settlementWarning === undefined ? defaults.settlementWarning : Boolean(saved.settlementWarning),
    alerts: Boolean(saved.alerts),
    stake: numberBetween(saved.stake, 1, 10_000_000, defaults.stake),
    stakeMode: ["total", "first-leg"].includes(saved.stakeMode) ? saved.stakeMode : defaults.stakeMode,
    sort: ["cost-asc", "width-desc", "profit-desc", "time-asc"].includes(saved.sort) ? saved.sort : defaults.sort,
    requiredBook: initialRequiredBook,
    lastUpdated: null,
    tracked: new Set(),
    trackedPlans: {},
    hidden: new Set(),
    trackerSession: null,
    calculatorSession: null,
    refreshTimer: null,
    stakeTimer: null,
  };
  try { state.tracked = new Set(JSON.parse(localStorage.getItem(trackedKey) || "[]").map(String)); } catch (_) { state.tracked = new Set(); }
  try { state.trackedPlans = JSON.parse(localStorage.getItem(trackedPlanKey) || "{}"); } catch (_) { state.trackedPlans = {}; }
  if (!state.trackedPlans || Array.isArray(state.trackedPlans) || typeof state.trackedPlans !== "object") state.trackedPlans = {};
  try { state.hidden = new Set(JSON.parse(localStorage.getItem(hiddenKey) || "[]").map(String)); } catch (_) { state.hidden = new Set(); }

  const elements = {
    workspace: document.querySelector(".mid-workspace"),
    valueLabEmpty: document.querySelector("[data-value-lab-empty]"),
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
    trackDialog: document.getElementById("mid-track-dialog"),
    trackSummary: document.getElementById("mid-track-summary"),
    trackTotal: document.getElementById("mid-track-total"),
    trackLegs: document.getElementById("mid-track-legs"),
    trackProof: document.getElementById("mid-track-proof"),
    trackError: document.getElementById("mid-track-error"),
    recalculateDialog: document.getElementById("mid-recalculate-dialog"),
    recalculateSummary: document.getElementById("mid-recalculate-summary"),
    recalculateMode: document.getElementById("mid-recalculate-mode"),
    recalculateTotal: document.getElementById("mid-recalculate-total"),
    recalculateLegs: document.getElementById("mid-recalculate-legs"),
    recalculateProof: document.getElementById("mid-recalculate-proof"),
    recalculateError: document.getElementById("mid-recalculate-error"),
    bookGrid: document.getElementById("mid-book-grid"),
    bookSearch: document.getElementById("mid-book-search"),
    dialogStake: document.getElementById("mid-dialog-stake"),
    dialogStakeLabel: document.getElementById("mid-dialog-stake-label"),
    savedList: document.getElementById("mid-saved-list"),
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

  function pointCount(value) {
    const amount = Number(value || 0);
    const label = amount.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return `${label} ${Math.abs(amount) === 1 ? "point" : "points"}`;
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

  function settingsPayload() {
    return {
      books: [...state.selectedBooks], markets: state.markets, minWidth: state.minWidth,
      maxCost: state.maxCost, maxAge: state.maxAge, commission: state.commission,
      distinctBooks: state.distinctBooks, preventDuplicateGameMarket: state.preventDuplicateGameMarket,
      lineMovementWarning: state.lineMovementWarning,
      liquidityWarning: state.liquidityWarning, settlementWarning: state.settlementWarning,
      alerts: state.alerts, stake: state.stake,
      stakeMode: state.stakeMode, sort: state.sort, requiredBook: state.requiredBook,
    };
  }

  function saveSettings() {
    localStorage.setItem(storageKey, JSON.stringify(settingsPayload()));
  }

  function savedFilters() {
    try {
      const rows = JSON.parse(localStorage.getItem(savedKey) || "[]");
      return Array.isArray(rows) ? rows : [];
    } catch (_) { return []; }
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
    const rows = state.rows.filter((row) => {
      const isHidden = state.hidden.has(String(row.id));
      return (state.view === "hidden" ? isHidden : !isHidden) && rowMatches(row);
    });
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
    if (elements.resultCopy) elements.resultCopy.textContent = `${visibleRows().length} ${state.view === "hidden" ? "hidden" : "shown"} · ranked by ${sortLabels[state.sort] || sortLabels["cost-asc"]}`;
    const showValueLab = state.view === "live"
      && state.hasCompletedScan
      && !state.loading
      && !state.error
      && !state.paused
      && state.rows.length === 0;
    elements.workspace?.classList.toggle("value-lab-empty-active", showValueLab);
    if (elements.valueLabEmpty) elements.valueLabEmpty.hidden = !showValueLab;
    if (showValueLab) {
      if (elements.resultCopy) elements.resultCopy.textContent = "Live scan active · waiting for a qualified play";
      return;
    }
    if (state.loading && !state.rows.length) {
      elements.feed.innerHTML = Array.from({ length: 5 }, () => '<div class="mid-skeleton"></div>').join("");
      return;
    }
    if (state.paused && state.view === "live") {
      elements.feed.innerHTML = `<div class="mid-empty"><i class="ph ph-pause-circle" aria-hidden="true"></i><strong>Middle scanner is paused</strong><span>Press play in the toolbar when you’re ready to resume the live scan.</span></div>`;
      return;
    }
    const rows = visibleRows();
    if (!rows.length) {
      if (state.view === "hidden") {
        elements.feed.innerHTML = `<div class="mid-empty"><i class="ph ph-eye-slash" aria-hidden="true"></i><strong>No hidden middles</strong><span>Use Track/Hide on any live opportunity, then choose Hide or Track and Hide.</span><button type="button" id="mid-empty-live">View live middles</button></div>`;
        document.getElementById("mid-empty-live")?.addEventListener("click", () => setView("live"));
      } else {
        elements.feed.innerHTML = `<div class="mid-empty"><i class="ph ph-binoculars" aria-hidden="true"></i><strong>No middles match these filters</strong><span>Widen the cost or window settings, add books, or clear search.</span><button type="button" id="mid-empty-filters">Adjust filters</button></div>`;
        document.getElementById("mid-empty-filters")?.addEventListener("click", () => openFilter());
      }
      return;
    }
    elements.feed.innerHTML = rows.map(opportunityCard).join("");
  }

  function updateSummary() {
    const rows = state.rows.filter((row) => !state.hidden.has(String(row.id)));
    const hiddenCount = state.rows.filter((row) => state.hidden.has(String(row.id))).length;
    const bestCost = rows.length ? Math.min(...rows.map((row) => Number(row.costPercent))) : null;
    const widest = rows.length ? Math.max(...rows.map((row) => Number(row.middleWidth))) : null;
    document.getElementById("mid-summary-count").textContent = String(rows.length);
    document.getElementById("mid-live-count").textContent = String(rows.length);
    document.getElementById("mid-hidden-count").textContent = String(hiddenCount);
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

  function executionWarningsMarkup(row) {
    const activeWarnings = [];
    const capacity = row.executionGates?.capacity || {};
    const settlement = row.executionGates?.settlement || {};
    if (state.lineMovementWarning) {
      activeWarnings.push({
        icon: "ph-trend-up",
        title: "Line Movement Confirmation",
        copy: "Recheck both displayed prices before placing either bet. The two lines can move independently.",
      });
    }
    if (state.liquidityWarning && capacity.passed === false) {
      activeWarnings.push({
        icon: "ph-gauge",
        title: "Liquidity / Limit Warning",
        copy: "The planned bet exceeds the reported limit or top price liquidity on at least one leg.",
      });
    } else if (state.liquidityWarning && capacity.verified !== true) {
      activeWarnings.push({
        icon: "ph-gauge",
        title: "Liquidity / Limit Warning",
        copy: "A verified bet limit or top price liquidity is unavailable for at least one leg.",
      });
    }
    if (state.settlementWarning && settlement.passed === false) {
      activeWarnings.push({
        icon: "ph-scales",
        title: "Settlement Rule Mismatch Warning",
        copy: "The two books report incompatible settlement rules for this market.",
      });
    } else if (state.settlementWarning && settlement.verified !== true) {
      activeWarnings.push({
        icon: "ph-scales",
        title: "Settlement Rule Mismatch Warning",
        copy: "A verified settlement rule identifier is unavailable for at least one leg. Confirm both books grade the market the same way.",
      });
    }
    if (!activeWarnings.length) return "";
    return `<section class="mid-detail-section mid-execution-warnings"><header><h3>Bet Warnings</h3><small>${activeWarnings.length} active</small></header><div>${activeWarnings.map((warning) => `<article><i class="ph ${warning.icon}" aria-hidden="true"></i><div><strong>${esc(warning.title)}</strong><p>${esc(warning.copy)}</p></div></article>`).join("")}</div></section>`;
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
    const profit = signedMoney(row.middleProfit);
    const lowerOutsideProfit = Number.isFinite(Number(legs[1]?.outsideProfit))
      ? Number(legs[1].outsideProfit)
      : worstOutside;
    const upperOutsideProfit = Number.isFinite(Number(legs[0]?.outsideProfit))
      ? Number(legs[0].outsideProfit)
      : worstOutside;
    const lowerOutsideLabel = signedMoney(lowerOutsideProfit);
    const upperOutsideLabel = signedMoney(upperOutsideProfit);
    const middleWidth = Number(row.middleWidth || 0);
    const middleWidthLabel = `${middleWidth} ${middleWidth === 1 ? "pt" : "pts"} middle window`;
    const lowLabel = curveTick(safeLow, signedTicks);
    const highLabel = curveTick(safeHigh, signedTicks);
    const accessibleSummary = `Both bets win for a net profit of ${profit} when the result lands between ${lowLabel} and ${highLabel}. Below the window returns ${lowerOutsideLabel}; above the window returns ${upperOutsideLabel}.`;
    return `
      <div class="mid-range-map" role="img" aria-label="${esc(accessibleSummary)}">
        <div class="mid-range-labels" aria-hidden="true">
          <div class="${lowerOutsideProfit >= 0 ? "positive-outside" : ""}"><strong>Below ${lowLabel}</strong><span>${esc(lowerWinner)}</span></div>
          <div class="positive"><strong>${lowLabel} to ${highLabel}</strong><span>Both bets win</span></div>
          <div class="${upperOutsideProfit >= 0 ? "positive-outside" : ""}"><strong>Above ${highLabel}</strong><span>${esc(upperWinner)}</span></div>
        </div>
        <div class="mid-range-scale" aria-hidden="true">
          <span class="start">${curveTick(tickValues[0], signedTicks)}</span>
          <span class="low">${curveTick(tickValues[1], signedTicks)}</span>
          <span class="middle">${curveTick(tickValues[2], signedTicks)}</span>
          <span class="high">${curveTick(tickValues[3], signedTicks)}</span>
          <span class="end">${curveTick(tickValues[4], signedTicks)}</span>
        </div>
        <div class="mid-range-track" aria-hidden="true">
          <div class="mid-range-zone mid-range-loss${lowerOutsideProfit >= 0 ? " positive-outside" : ""}"><strong>${lowerOutsideLabel}</strong><span>${esc(lowerWinner)}</span></div>
          <div class="mid-range-zone mid-range-middle"><small>Both bets win</small><strong>${profit}</strong><span>${middleWidthLabel}</span></div>
          <div class="mid-range-zone mid-range-loss${upperOutsideProfit >= 0 ? " positive-outside" : ""}"><strong>${upperOutsideLabel}</strong><span>${esc(upperWinner)}</span></div>
          <i class="ph ph-record mid-range-marker edge start" aria-hidden="true"></i>
          <i class="ph ph-record mid-range-marker low" aria-hidden="true"></i>
          <i class="ph ph-record mid-range-marker high" aria-hidden="true"></i>
          <i class="ph ph-record mid-range-marker edge end" aria-hidden="true"></i>
        </div>
      </div>`;
  }

  function renderDetail(row, openOnMobile = false) {
    if (!row) return;
    const tracked = state.tracked.has(String(row.id));
    const hidden = state.hidden.has(String(row.id));
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
    const worstOutside = Math.min(...legs.map((leg) => Number(leg.outsideProfit || 0)));
    const probabilitySummary = row.probabilityModel?.status === "AVAILABLE"
      ? `<div><span>Market Implied Middle</span><strong>${percent(row.estimatedMiddleProbability)}</strong><small>${Number(row.estimatedEvPercent) >= 0 ? "+" : ""}${percent(row.estimatedEvPercent)} estimated EV</small></div>`
      : `<div><span>Middle Probability</span><strong>Unavailable</strong><small>${esc(row.probabilityModel?.reason || "No paired line ladder")}</small></div>`;
    const payoutRangeMarkup = payoutRangeMap(row, legs, worstOutside);
    const executionWarnings = executionWarningsMarkup(row);
    elements.detail.innerHTML = `
      <header class="mid-detail-header">
        <div class="mid-detail-main"><div class="mid-detail-hero-top"><div class="mid-detail-return"><strong>${percent(row.breakEvenMiddleProbability)}</strong><span>break-even middle</span></div><button type="button" data-mid-mobile-close aria-label="Close details"><i class="ph ph-x" aria-hidden="true"></i></button></div><h2 class="mid-detail-matchup">${detailMatchup(row)}</h2><p>${esc(row.league)} · ${esc(row.marketLabel)} · ${esc(dateTime(row.commenceTime))}</p></div>
        <dl class="mid-detail-facts"><div><dt>Middle window</dt><dd>${esc(row.window?.label || `${row.middleWidth} pts`)}</dd></div><div><dt>Worst case</dt><dd class="${worstOutside >= 0 ? "positive" : "warning"}">${signedMoney(worstOutside)}</dd></div><div><dt>Best case</dt><dd class="positive">${signedMoney(row.middleProfit)}</dd></div></dl>
        <div class="mid-detail-actions">${hidden
          ? `<button class="mid-primary-button" id="mid-restore" type="button"><i class="ph ph-eye" aria-hidden="true"></i>Restore</button>`
          : `<button class="mid-primary-button${tracked ? " tracked" : ""}" id="mid-track" type="button" aria-pressed="${tracked}"><i class="ph ph-eye-slash" aria-hidden="true"></i>Track/Hide</button>`}
          <button class="mid-secondary-button" id="mid-recalculate" type="button"><i class="ph ph-calculator" aria-hidden="true"></i>Recalculate</button></div>
      </header>
      <section class="mid-detail-section mid-stake-plan-section"><header><h3>Equalized Bets</h3><strong>${money(row.totalStake)}</strong></header><div class="mid-plan-head"><span>Outcome</span><span>Book</span><span>Odds</span><span>Bet</span><span>Payout</span><span class="sr-only">Action</span></div><div class="mid-plan-grid">${legCards}</div></section>
      <section class="mid-detail-section mid-payout-section"><header><h3>Payout Scenarios</h3><span class="mid-cost-badge ${row.guaranteedOutsideProfit ? "positive" : "warning"}">${percent(row.breakEvenMiddleProbability)} break-even</span></header><div class="mid-range-layout"><div class="mid-detail-summary mid-range-summary"><div><span>Middle Window</span><strong>${esc(row.window?.label || "")}</strong><small>${pointCount(row.middleWidth)}</small></div>${probabilitySummary}</div><div class="mid-range-scroll">${payoutRangeMarkup}</div></div></section>
      <section class="mid-detail-section mid-available-odds"><header><h3>Available Odds</h3><small>${row.bookCount} books</small></header><div class="mid-quote-groups">${comparisons}</div></section>
      ${executionWarnings}
      `;
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

  function renderDetailEmpty() {
    const hidden = state.view === "hidden";
    elements.detail.innerHTML = `<div class="mid-detail-empty"><span><i class="ph ${hidden ? "ph-eye-slash" : "ph-cursor-click"}" aria-hidden="true"></i></span><h2>${hidden ? "No hidden middle selected" : "Execution plan"}</h2><p>${hidden ? "Hidden opportunities stay here until you restore them to the Live tab." : "Select an opportunity to see the exact bet on both sides, every payout scenario, and the best available prices."}</p></div>`;
  }

  function setView(view) {
    state.view = view === "hidden" ? "hidden" : "live";
    document.querySelectorAll("[data-mid-view]").forEach((button) => {
      const active = button.dataset.midView === state.view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    state.selectedId = visibleRows()[0]?.id || "";
    closeMobileDetail();
    renderAll();
  }

  function renderAll() {
    const visible = visibleRows();
    if (!state.selectedId || !visible.some((row) => row.id === state.selectedId)) state.selectedId = visible[0]?.id || "";
    renderFeed();
    updateSummary();
    populateQuickFilters();
    const selected = state.rows.find((row) => row.id === state.selectedId);
    if (selected) renderDetail(selected); else renderDetailEmpty();
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
        state.hasCompletedScan = true;
        state.lastUpdated = new Date();
        renderAll();
      }
    }
    state.loading = true;
    state.error = "";
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
      state.hasCompletedScan = true;
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
      state.error = error.message || "Unable to load middles";
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
      renderFeed();
    } else loadBoard();
  }

  function toggleAlerts() {
    state.alerts = !state.alerts;
    elements.alerts.setAttribute("aria-pressed", String(state.alerts));
    saveSettings();
    notify(state.alerts ? "Middle opportunity alerts enabled" : "Middle opportunity alerts muted");
  }

  function filteredBookCatalog(query = "") {
    const needle = query.trim().toLowerCase();
    return eligibleBooks.filter((book) => {
      if (state.bookGroup === "popular" && !popularBooks.has(book.key)) return false;
      if (["sportsbook", "exchange"].includes(state.bookGroup) && book.type !== state.bookGroup) return false;
      return !needle || `${book.name} ${book.key}`.toLowerCase().includes(needle);
    });
  }

  function renderBookGrid(query = "") {
    const books = filteredBookCatalog(query);
    elements.bookGrid.innerHTML = books.map((book) => `
      <label class="mid-book-option"><input type="checkbox" value="${esc(book.key)}" ${state.selectedBooks.has(book.key) ? "checked" : ""}>${logoMarkup(book)}<span>${esc(book.name)}</span></label>`).join("");
    updateBookCount();
  }

  function updateBookCount() {
    const count = state.selectedBooks.size;
    document.getElementById("mid-book-filter-count").textContent = `${count}/${eligibleBooks.length}`;
    document.getElementById("mid-selected-summary").textContent = `${count}/${eligibleBooks.length} selected`;
  }

  function renderSavedFilters() {
    const filters = savedFilters();
    document.getElementById("mid-saved-count").textContent = String(filters.length);
    if (!filters.length) {
      elements.savedList.innerHTML = `<div class="mid-saved-empty"><i class="ph ph-bookmark-simple"></i><strong>No Filters Saved Yet</strong><p>Configure this scan, then use Save Filter below.</p></div>`;
      return;
    }
    elements.savedList.innerHTML = filters.map((filter, index) => `<article class="mid-saved-filter"><i class="ph ph-bookmark-simple"></i><div><strong>${esc(filter.name)}</strong><small>${filter.stakeMode === "first-leg" ? "Baseline locked" : "Total bet"} · ${Number(filter.maxCost).toFixed(1)}% max · ${(filter.books || []).length} books</small></div><button type="button" data-mid-load-filter="${index}">Load</button><button type="button" data-mid-delete-filter="${index}" aria-label="Delete ${esc(filter.name)}"><i class="ph ph-trash"></i></button></article>`).join("");
  }

  function syncDialog() {
    elements.dialogStake.value = state.stake;
    syncStakeModeUI();
    document.getElementById("mid-max-cost").value = state.maxCost;
    document.getElementById("mid-distinct-books").checked = state.distinctBooks;
    document.getElementById("mid-duplicate-market-warning").checked = state.preventDuplicateGameMarket;
    document.getElementById("mid-line-movement-warning").checked = state.lineMovementWarning;
    document.getElementById("mid-liquidity-warning").checked = state.liquidityWarning;
    document.getElementById("mid-settlement-warning").checked = state.settlementWarning;
    document.querySelectorAll("#mid-market-choices input").forEach((input) => { input.checked = state.markets.includes(input.value); });
    renderBookGrid(elements.bookSearch.value);
    renderSavedFilters();
  }

  function updateFilterCount() {
    let count = 0;
    if (state.selectedBooks.size !== defaultBookKeys.length) count += 1;
    if (state.markets.length !== defaults.markets.length) count += 1;
    if (state.maxCost !== defaults.maxCost) count += 1;
    if (state.distinctBooks !== defaults.distinctBooks) count += 1;
    if (state.preventDuplicateGameMarket !== defaults.preventDuplicateGameMarket) count += 1;
    if (state.lineMovementWarning || state.liquidityWarning || state.settlementWarning) count += 1;
    if (state.stake !== defaults.stake || state.stakeMode !== defaults.stakeMode) count += 1;
    const node = document.getElementById("mid-filter-count");
    node.textContent = String(count);
    node.hidden = count === 0;
  }

  function readDialog() {
    const selected = [...state.selectedBooks];
    const markets = [...document.querySelectorAll("#mid-market-choices input:checked")].map((input) => input.value);
    if (!selected.length || !markets.length) {
      notify(!selected.length ? "Select at least one sportsbook" : "Select at least one market", "error");
      return false;
    }
    state.stakeMode = document.querySelector('input[name="mid-dialog-stake-mode"]:checked')?.value === "first-leg" ? "first-leg" : "total";
    state.stake = numberBetween(elements.dialogStake.value, 1, 10_000_000, defaults.stake);
    elements.stake.value = stakeInputValue(state.stake);
    syncStakeModeUI();
    if (state.requiredBook && !state.selectedBooks.has(state.requiredBook)) {
      state.requiredBook = "";
      notify("Required book reset to Any selected book because it is no longer selected.");
    }
    state.markets = markets;
    state.maxCost = numberBetween(document.getElementById("mid-max-cost").value, 0, 100, defaults.maxCost);
    state.distinctBooks = document.getElementById("mid-distinct-books").checked;
    state.preventDuplicateGameMarket = document.getElementById("mid-duplicate-market-warning").checked;
    state.lineMovementWarning = document.getElementById("mid-line-movement-warning").checked;
    state.liquidityWarning = document.getElementById("mid-liquidity-warning").checked;
    state.settlementWarning = document.getElementById("mid-settlement-warning").checked;
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
    state.preventDuplicateGameMarket = defaults.preventDuplicateGameMarket;
    state.lineMovementWarning = defaults.lineMovementWarning;
    state.liquidityWarning = defaults.liquidityWarning;
    state.settlementWarning = defaults.settlementWarning;
    state.requiredBook = defaults.requiredBook;
    state.stake = defaults.stake;
    state.stakeMode = defaults.stakeMode;
    state.bookGroup = "all";
    document.querySelectorAll("[data-mid-book-group]").forEach((button) => button.classList.toggle("active", button.dataset.midBookGroup === "all"));
    syncDialog();
  }

  function applyDialog() {
    if (!readDialog()) return;
    elements.filterDialog.close();
    loadBoard();
  }

  function roundCents(value) {
    return Math.round(Number(value || 0) * 100) / 100;
  }

  function validAmericanOdds(value) {
    const amount = Number(value);
    return Number.isFinite(amount) && amount !== 0 && Math.abs(amount) >= 100 && Math.abs(amount) <= 100000;
  }

  function calculateEditablePlan(session) {
    const prices = session.odds.map(Number);
    if (prices.length !== 2 || prices.some((price) => !validAmericanOdds(price))) {
      return { error: "Enter valid American odds for both legs." };
    }
    const decimals = prices.map(decimalOdds);
    let stakes = [];
    if (session.mode === "locked") {
      const anchorIndex = Math.min(Math.max(Number(session.anchorIndex || 0), 0), 1);
      const anchorStake = Number(session.anchorStake);
      if (!Number.isFinite(anchorStake) || anchorStake <= 0) return { error: "Enter a bet greater than zero for the locked side." };
      const targetPayout = anchorStake * decimals[anchorIndex];
      stakes = decimals.map((value, index) => index === anchorIndex ? roundCents(anchorStake) : roundCents(targetPayout / value));
    } else {
      const total = Number(session.total);
      if (!Number.isFinite(total) || total <= 0) return { error: "Enter a total bet greater than zero." };
      const weights = decimals.map((value) => 1 / value);
      const weightTotal = weights.reduce((sum, value) => sum + value, 0);
      stakes = weights.map((value) => roundCents(total * value / weightTotal));
      const correction = roundCents(total - stakes.reduce((sum, value) => sum + value, 0));
      stakes[stakes.length - 1] = roundCents(stakes[stakes.length - 1] + correction);
    }
    const totalStake = roundCents(stakes.reduce((sum, value) => sum + value, 0));
    const payouts = stakes.map((stake, index) => roundCents(stake * decimals[index]));
    const outsideProfits = payouts.map((payout) => roundCents(payout - totalStake));
    return {
      prices,
      decimals,
      stakes,
      payouts,
      totalStake,
      outsideProfits,
      worstCase: Math.min(...outsideProfits),
      bestCase: roundCents(payouts.reduce((sum, payout) => sum + payout, 0) - totalStake),
    };
  }

  function actionSummary(row, kicker) {
    return `<div><span>${esc(kicker)}</span><h3>${esc(row.eventTitle)}</h3><p>${esc(row.league)} · ${esc(row.marketLabel)} · ${esc(dateTime(row.commenceTime))}</p></div><strong>${percent(row.breakEvenMiddleProbability)}</strong>`;
  }

  function proofMarkup(plan, row) {
    return `<div><span>Total bet</span><strong>${money(plan.totalStake)}</strong></div><div><span>Worst case</span><strong class="${plan.worstCase >= 0 ? "positive" : "warning"}">${signedMoney(plan.worstCase)}</strong></div><div><span>Best case</span><strong class="positive">${signedMoney(plan.bestCase)}</strong></div><div><span>Middle window</span><strong class="positive">${esc(row.window?.label || `${row.middleWidth} pts`)}</strong></div>`;
  }

  function editorBook(leg) {
    return `<span class="mid-editor-book">${logoMarkup(leg)}<span><strong>${esc(leg.bookName)}</strong><small>${esc(leg.bookKey)}</small></span></span>`;
  }

  function openTracker(row) {
    if (!row || !elements.trackDialog) return;
    const anchorIndex = Math.min(Math.max(Number(row.baselineLegIndex ?? 0), 0), 1);
    state.trackerSession = {
      row,
      mode: "total",
      total: Number(row.totalStake || state.stake),
      anchorIndex,
      anchorStake: Number(row.legs?.[anchorIndex]?.stake || row.baselineStake || 0),
      odds: (row.legs || []).map((leg) => Number(leg.americanOdds)),
    };
    elements.trackSummary.innerHTML = actionSummary(row, "2-leg middle");
    elements.trackTotal.value = state.trackerSession.total.toFixed(2);
    elements.trackLegs.innerHTML = (row.legs || []).map((leg, index) => `<div class="mid-leg-editor-row">
      <div class="mid-editor-outcome"><strong>${esc(leg.selection)}</strong><small>${esc(row.marketLabel)}</small></div>
      ${editorBook(leg)}
      <label class="mid-editor-odds"><span class="sr-only">Odds for ${esc(leg.selection)}</span><input type="text" inputmode="text" value="${odds(leg.americanOdds)}" data-mid-track-odds="${index}"></label>
      <strong class="mid-editor-value" data-mid-track-stake="${index}">${money(leg.stake)}</strong>
      <strong class="mid-editor-value positive" data-mid-track-payout="${index}">${money(leg.outsidePayout)}</strong>
    </div>`).join("");
    elements.trackError.textContent = "";
    refreshTrackPlan();
    elements.trackDialog.showModal();
  }

  function refreshTrackPlan() {
    const session = state.trackerSession;
    if (!session) return null;
    const plan = calculateEditablePlan(session);
    session.plan = plan.error ? null : plan;
    elements.trackError.textContent = plan.error || "";
    if (plan.error) {
      elements.trackProof.innerHTML = "";
      return null;
    }
    plan.stakes.forEach((stake, index) => {
      const stakeNode = elements.trackLegs.querySelector(`[data-mid-track-stake="${index}"]`);
      const payoutNode = elements.trackLegs.querySelector(`[data-mid-track-payout="${index}"]`);
      if (stakeNode) stakeNode.textContent = money(stake);
      if (payoutNode) payoutNode.textContent = money(plan.payouts[index]);
    });
    elements.trackProof.innerHTML = proofMarkup(plan, session.row);
    return plan;
  }

  function closeTracker() {
    if (elements.trackDialog?.open) elements.trackDialog.close();
    state.trackerSession = null;
  }

  function persistTrackerState() {
    localStorage.setItem(trackedKey, JSON.stringify([...state.tracked]));
    localStorage.setItem(trackedPlanKey, JSON.stringify(state.trackedPlans));
    localStorage.setItem(hiddenKey, JSON.stringify([...state.hidden]));
  }

  async function applyTrackerAction(action) {
    const session = state.trackerSession;
    const row = session?.row;
    if (!session || !row) return;
    const id = String(row.id);
    const shouldTrack = action === "track" || action === "track-hide";
    const shouldHide = action === "hide" || action === "track-hide";
    const plan = shouldTrack ? refreshTrackPlan() : null;
    if (shouldTrack && !plan) {
      elements.trackLegs.querySelector("[data-mid-track-odds]")?.focus();
      return;
    }
    const buttons = [...elements.trackDialog.querySelectorAll("[data-mid-track-action]")];
    buttons.forEach((button) => { button.disabled = true; });
    elements.trackError.textContent = "";
    try {
      if (shouldTrack) {
        for (let index = 0; index < row.legs.length; index += 1) {
          const leg = row.legs[index];
          const response = await fetch("/api/middles/personal-bets", {
            method: "POST",
            headers: { "Accept": "application/json", "Content-Type": "application/json" },
            body: JSON.stringify({
              source_id: `${row.id}:${index}`,
              event_title: row.eventTitle,
              market_title: row.marketLabel,
              selection: leg.selection,
              event_start_time: row.commenceTime,
              sport_key: row.sportKey,
              league: row.league,
              market_key: row.marketKey,
              market_line: leg.point ?? null,
              canonical_event_id: row.eventId,
              canonical_market_id: row.id,
              canonical_outcome_id: `${row.id}:outcome:${index}`,
              american_odds: plan.prices[index],
              stake: plan.stakes[index],
              fees: 0,
              sportsbook: leg.bookName,
              sportsbook_logo: leg.logoUrl || "",
              market_url: /^https:\/\//.test(String(leg.deepLink || "")) ? leg.deepLink : "",
              ev_percent: Number(row.estimatedEvPercent || 0),
              tags: ["Middle", "2-leg middle"],
              prevent_duplicate_middle_market: state.preventDuplicateGameMarket,
              middle_pair_id: row.id,
              middle_leg_index: index,
              confirm_duplicate: true,
              confirm_conflict: true,
            }),
          });
          const payload = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(payload.error || `Unable to track ${leg.selection}.`);
        }
        state.tracked.add(id);
        state.trackedPlans[id] = {
          odds: plan.prices,
          stakes: plan.stakes,
          payouts: plan.payouts,
          totalStake: plan.totalStake,
          worstCase: plan.worstCase,
          bestCase: plan.bestCase,
          trackedAt: new Date().toISOString(),
        };
      }
      if (shouldHide) state.hidden.add(id);
      persistTrackerState();
      closeTracker();
      renderAll();
      notify(action === "track" ? "Both middle legs were added to Bet Tracker" : action === "hide" ? "Middle moved to Hidden" : "Both legs were tracked and the middle was hidden");
    } catch (error) {
      elements.trackError.textContent = error.message;
    } finally {
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  function openRecalculateDialog(row) {
    if (!row || !elements.recalculateDialog) return;
    const anchorIndex = Math.min(Math.max(Number(row.baselineLegIndex ?? 0), 0), 1);
    state.calculatorSession = {
      row,
      mode: row.stakeMode === "first-leg" ? "locked" : "total",
      total: Number(row.totalStake || state.stake),
      anchorIndex,
      anchorStake: Number(row.legs?.[anchorIndex]?.stake || row.baselineStake || 0),
      odds: (row.legs || []).map((leg) => Number(leg.americanOdds)),
    };
    elements.recalculateSummary.innerHTML = actionSummary(row, "Live middle workspace");
    elements.recalculateLegs.innerHTML = (row.legs || []).map((leg, index) => `<div class="mid-leg-editor-row" data-mid-calculator-row="${index}">
      <div class="mid-editor-outcome"><strong>${esc(leg.selection)}</strong><small>${esc(row.marketLabel)}</small></div>
      ${editorBook(leg)}
      <label class="mid-editor-odds"><span class="sr-only">Odds for ${esc(leg.selection)}</span><input type="text" inputmode="text" value="${odds(leg.americanOdds)}" data-mid-calculator-odds="${index}"></label>
      <label class="mid-editor-money"><b>$</b><input type="number" min="0.01" step="0.01" inputmode="decimal" data-mid-calculator-stake="${index}" aria-label="Bet amount for ${esc(leg.selection)}"></label>
      <strong class="mid-editor-value positive" data-mid-calculator-payout="${index}">${money(leg.outsidePayout)}</strong>
      <label class="mid-editor-lock" title="Lock ${esc(leg.selection)} bet"><input type="radio" name="mid-calculator-lock" value="${index}" data-mid-calculator-lock="${index}"><i class="ph ph-lock-key" aria-hidden="true"></i><span class="sr-only">Lock ${esc(leg.selection)}</span></label>
    </div>`).join("");
    elements.recalculateMode.value = state.calculatorSession.mode;
    elements.recalculateTotal.value = state.calculatorSession.total.toFixed(2);
    elements.recalculateError.textContent = "";
    refreshCalculatorPlan();
    elements.recalculateDialog.showModal();
  }

  function refreshCalculatorPlan() {
    const session = state.calculatorSession;
    if (!session) return null;
    const plan = calculateEditablePlan(session);
    session.plan = plan.error ? null : plan;
    elements.recalculateError.textContent = plan.error || "";
    const lockedMode = session.mode === "locked";
    elements.recalculateMode.value = session.mode;
    elements.recalculateTotal.disabled = lockedMode;
    if (plan.error) {
      elements.recalculateProof.innerHTML = "";
      return null;
    }
    if (lockedMode) elements.recalculateTotal.value = plan.totalStake.toFixed(2);
    plan.stakes.forEach((stake, index) => {
      const rowNode = elements.recalculateLegs.querySelector(`[data-mid-calculator-row="${index}"]`);
      const input = rowNode?.querySelector(`[data-mid-calculator-stake="${index}"]`);
      const payout = rowNode?.querySelector(`[data-mid-calculator-payout="${index}"]`);
      const lock = rowNode?.querySelector(`[data-mid-calculator-lock="${index}"]`);
      const isAnchor = lockedMode && index === session.anchorIndex;
      rowNode?.classList.toggle("is-locked", isAnchor);
      if (input) {
        input.readOnly = !isAnchor;
        if (document.activeElement !== input) input.value = stake.toFixed(2);
      }
      if (payout) payout.textContent = money(plan.payouts[index]);
      if (lock) lock.checked = isAnchor;
    });
    elements.recalculateProof.innerHTML = proofMarkup(plan, session.row);
    return plan;
  }

  function closeRecalculate() {
    if (elements.recalculateDialog?.open) elements.recalculateDialog.close();
    state.calculatorSession = null;
  }

  function resetCalculator() {
    const row = state.calculatorSession?.row;
    if (!row) return;
    closeRecalculate();
    openRecalculateDialog(row);
  }

  function restoreSelected() {
    if (!state.selectedId) return;
    state.hidden.delete(String(state.selectedId));
    localStorage.setItem(hiddenKey, JSON.stringify([...state.hidden]));
    renderAll();
    notify("Middle restored to Live");
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

  function saveFilter() {
    if (!readDialog()) return;
    const filters = savedFilters();
    const suggested = `Middles ${filters.length + 1}`;
    const name = window.prompt("Name this filter", suggested)?.trim();
    if (!name) return;
    filters.push({ name: name.slice(0, 40), ...settingsPayload() });
    localStorage.setItem(savedKey, JSON.stringify(filters.slice(-20)));
    renderSavedFilters();
    notify(`Saved ${name.slice(0, 40)}.`);
  }

  function loadSaved(index) {
    const filter = savedFilters()[index];
    if (!filter) return;
    state.selectedBooks = new Set((filter.books || []).filter((key) => eligibleBooks.some((book) => book.key === key)));
    state.markets = Array.isArray(filter.markets) && filter.markets.length ? filter.markets : [...defaults.markets];
    state.minWidth = defaults.minWidth;
    state.maxCost = numberBetween(filter.maxCost, 0, 100, defaults.maxCost);
    state.maxAge = defaults.maxAge;
    state.commission = defaults.commission;
    state.distinctBooks = filter.distinctBooks === undefined ? defaults.distinctBooks : Boolean(filter.distinctBooks);
    state.preventDuplicateGameMarket = filter.preventDuplicateGameMarket === undefined ? defaults.preventDuplicateGameMarket : Boolean(filter.preventDuplicateGameMarket);
    state.lineMovementWarning = filter.lineMovementWarning === undefined ? defaults.lineMovementWarning : Boolean(filter.lineMovementWarning);
    state.liquidityWarning = filter.liquidityWarning === undefined ? defaults.liquidityWarning : Boolean(filter.liquidityWarning);
    state.settlementWarning = filter.settlementWarning === undefined ? defaults.settlementWarning : Boolean(filter.settlementWarning);
    state.stake = numberBetween(filter.stake, 1, 10_000_000, defaults.stake);
    state.stakeMode = filter.stakeMode === "first-leg" ? "first-leg" : "total";
    state.sort = ["cost-asc", "width-desc", "profit-desc", "time-asc"].includes(filter.sort) ? filter.sort : defaults.sort;
    state.requiredBook = typeof filter.requiredBook === "string" && state.selectedBooks.has(filter.requiredBook) ? filter.requiredBook : defaults.requiredBook;
    syncDialog();
    notify(`Loaded ${filter.name}.`);
  }

  function deleteSaved(index) {
    const filters = savedFilters();
    const removed = filters.splice(index, 1)[0];
    localStorage.setItem(savedKey, JSON.stringify(filters));
    renderSavedFilters();
    if (removed) notify(`Deleted ${removed.name}.`);
  }

  function openFilter(tab = "sportsbooks") {
    syncDialog();
    document.querySelector(`[data-mid-filter-tab="${tab}"]`)?.click();
    elements.filterDialog.showModal();
  }

  function syncStakeModeUI() {
    const baselineMode = state.stakeMode === "first-leg";
    elements.stakeMode.value = state.stakeMode;
    elements.stake.setAttribute("aria-label", baselineMode ? "Baseline Amount" : "Total Bet");
    if (elements.dialogStakeLabel) elements.dialogStakeLabel.textContent = baselineMode ? "Baseline Amount" : "Total Bet";
    if (elements.dialogStake) elements.dialogStake.step = baselineMode ? "10" : "25";
    document.querySelectorAll('input[name="mid-dialog-stake-mode"]').forEach((input) => { input.checked = input.value === state.stakeMode; });
  }

  function bind() {
    document.querySelectorAll("[data-mid-view]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.midView)));
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
    document.querySelectorAll("[data-mid-filter-tab]").forEach((button) => button.addEventListener("click", () => {
      document.querySelectorAll("[data-mid-filter-tab]").forEach((item) => item.classList.toggle("active", item === button));
      document.querySelectorAll("[data-mid-filter-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.midFilterPanel === button.dataset.midFilterTab));
    }));
    document.querySelectorAll("[data-mid-book-group]").forEach((button) => button.addEventListener("click", () => {
      state.bookGroup = button.dataset.midBookGroup;
      document.querySelectorAll("[data-mid-book-group]").forEach((item) => item.classList.toggle("active", item === button));
      renderBookGrid(elements.bookSearch.value);
    }));
    document.getElementById("mid-filter-open").addEventListener("click", () => openFilter());
    document.getElementById("mid-filter-close").addEventListener("click", () => elements.filterDialog.close());
    document.getElementById("mid-filter-reset").addEventListener("click", resetDialog);
    document.getElementById("mid-filter-form").addEventListener("submit", (event) => { event.preventDefault(); applyDialog(); });
    document.getElementById("mid-filter-apply").addEventListener("click", applyDialog);
    document.getElementById("mid-save-filter").addEventListener("click", saveFilter);
    document.querySelectorAll('input[name="mid-dialog-stake-mode"]').forEach((input) => input.addEventListener("change", () => {
      elements.dialogStakeLabel.textContent = input.value === "first-leg" ? "Baseline Amount" : "Total Bet";
      elements.dialogStake.step = input.value === "first-leg" ? "10" : "25";
    }));
    elements.bookSearch.addEventListener("input", () => renderBookGrid(elements.bookSearch.value));
    elements.bookGrid.addEventListener("change", (event) => {
      if (!event.target.matches('input[type="checkbox"]')) return;
      if (event.target.checked) state.selectedBooks.add(event.target.value);
      else state.selectedBooks.delete(event.target.value);
      renderBookGrid(elements.bookSearch.value);
    });
    elements.savedList.addEventListener("click", (event) => {
      const load = event.target.closest("[data-mid-load-filter]");
      const remove = event.target.closest("[data-mid-delete-filter]");
      if (load) loadSaved(Number(load.dataset.midLoadFilter));
      if (remove) deleteSaved(Number(remove.dataset.midDeleteFilter));
    });
    function selectAllBooks() { filteredBookCatalog(elements.bookSearch.value).forEach((book) => state.selectedBooks.add(book.key)); renderBookGrid(elements.bookSearch.value); }
    function clearBooks() { filteredBookCatalog(elements.bookSearch.value).forEach((book) => state.selectedBooks.delete(book.key)); renderBookGrid(elements.bookSearch.value); }
    document.getElementById("mid-books-all").addEventListener("click", selectAllBooks);
    document.getElementById("mid-books-all-top").addEventListener("click", () => { eligibleBooks.forEach((book) => state.selectedBooks.add(book.key)); renderBookGrid(elements.bookSearch.value); });
    document.getElementById("mid-books-clear").addEventListener("click", clearBooks);
    document.getElementById("mid-books-clear-top").addEventListener("click", () => { state.selectedBooks.clear(); renderBookGrid(elements.bookSearch.value); });
    const learnDialog = document.getElementById("mid-learn-dialog");
    document.getElementById("mid-learn-open").addEventListener("click", () => learnDialog.showModal());
    document.getElementById("mid-learn-close").addEventListener("click", () => learnDialog.close());
    document.getElementById("mid-track-close").addEventListener("click", closeTracker);
    document.getElementById("mid-track-form").addEventListener("submit", (event) => event.preventDefault());
    elements.trackDialog.addEventListener("click", (event) => { if (event.target === elements.trackDialog) closeTracker(); });
    elements.trackTotal.addEventListener("input", () => {
      if (!state.trackerSession) return;
      state.trackerSession.total = elements.trackTotal.value;
      refreshTrackPlan();
    });
    elements.trackLegs.addEventListener("input", (event) => {
      const input = event.target.closest("[data-mid-track-odds]");
      if (!input || !state.trackerSession) return;
      state.trackerSession.odds[Number(input.dataset.midTrackOdds)] = input.value;
      refreshTrackPlan();
    });
    elements.trackDialog.addEventListener("click", (event) => {
      const button = event.target.closest("[data-mid-track-action]");
      if (!button || !state.trackerSession) return;
      applyTrackerAction(button.dataset.midTrackAction);
    });
    document.getElementById("mid-recalculate-close").addEventListener("click", closeRecalculate);
    document.getElementById("mid-recalculate-form").addEventListener("submit", (event) => event.preventDefault());
    document.getElementById("mid-recalculate-done").addEventListener("click", closeRecalculate);
    document.getElementById("mid-recalculate-reset").addEventListener("click", resetCalculator);
    elements.recalculateDialog.addEventListener("click", (event) => { if (event.target === elements.recalculateDialog) closeRecalculate(); });
    elements.recalculateMode.addEventListener("change", () => {
      const session = state.calculatorSession;
      if (!session) return;
      const currentPlan = session.plan;
      session.mode = elements.recalculateMode.value === "locked" ? "locked" : "total";
      if (session.mode === "locked") session.anchorStake = currentPlan?.stakes[session.anchorIndex] || session.anchorStake;
      else session.total = currentPlan?.totalStake || session.total;
      refreshCalculatorPlan();
    });
    elements.recalculateTotal.addEventListener("input", () => {
      if (!state.calculatorSession || state.calculatorSession.mode !== "total") return;
      state.calculatorSession.total = elements.recalculateTotal.value;
      refreshCalculatorPlan();
    });
    elements.recalculateLegs.addEventListener("input", (event) => {
      const session = state.calculatorSession;
      if (!session) return;
      const oddsInput = event.target.closest("[data-mid-calculator-odds]");
      if (oddsInput) {
        session.odds[Number(oddsInput.dataset.midCalculatorOdds)] = oddsInput.value;
        refreshCalculatorPlan();
        return;
      }
      const betInput = event.target.closest("[data-mid-calculator-stake]");
      if (betInput && session.mode === "locked") {
        const index = Number(betInput.dataset.midCalculatorStake);
        if (index !== session.anchorIndex) return;
        session.anchorStake = betInput.value;
        refreshCalculatorPlan();
      }
    });
    elements.recalculateLegs.addEventListener("change", (event) => {
      const lock = event.target.closest("[data-mid-calculator-lock]");
      const session = state.calculatorSession;
      if (!lock || !session) return;
      const index = Number(lock.dataset.midCalculatorLock);
      session.mode = "locked";
      session.anchorIndex = index;
      session.anchorStake = session.plan?.stakes[index] || session.row.legs?.[index]?.stake || 0;
      refreshCalculatorPlan();
      elements.recalculateLegs.querySelector(`[data-mid-calculator-stake="${index}"]`)?.focus();
    });
    elements.backdrop.addEventListener("click", closeMobileDetail);
    elements.mobileClose.addEventListener("click", closeMobileDetail);
    elements.detail.addEventListener("click", (event) => {
      if (event.target.closest("[data-mid-mobile-close]")) closeMobileDetail();
      if (event.target.closest("#mid-recalculate")) openRecalculateDialog(state.rows.find((item) => item.id === state.selectedId));
      if (event.target.closest("#mid-track")) openTracker(state.rows.find((item) => item.id === state.selectedId));
      if (event.target.closest("#mid-restore")) restoreSelected();
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
      if (event.key === "Escape") { closeQuickSelects(); closeMobileDetail(); closeTracker(); closeRecalculate(); }
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
