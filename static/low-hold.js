(() => {
  const pageRoot = document.querySelector(".lh-page");
  if (!pageRoot) return;

  const configNode = document.getElementById("lh-config");
  let config = { books: [] };
  try { config = JSON.parse(configNode?.textContent || "{}"); } catch (_error) { config = { books: [] }; }

  const popularBooks = new Set(["fanduel", "draftkings", "betmgm", "caesars", "fanatics", "bet365", "pinnacle", "novig", "hardrockbet", "betonline", "kalshi", "polymarket"]);
  const eligibleBooks = (config.books || []).filter((book) => book.type !== "dfs");
  const configuredMarketKeys = Object.values(config.marketGroups || {}).flat()
    .map((market) => typeof market === "string" ? market : market?.key)
    .filter(Boolean);
  const storageKey = "iconlabsLowHoldSettingsV4";
  const savedKey = "iconlabsLowHoldSavedFiltersV3";
  const hiddenKey = "iconlabsLowHoldHiddenOpportunitiesV1";
  const hiddenExpiryGraceMs = 24 * 60 * 60 * 1000;
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem(storageKey) || "{}"); } catch (_error) { stored = {}; }

  const defaultMarkets = configuredMarketKeys.length
    ? configuredMarketKeys
    : ["h2h", "spreads", "totals", "alternate_spreads", "alternate_totals", "batter_hits", "pitcher_strikeouts", "player_points"];
  const defaults = {
    stake: 100,
    stakeMode: "first-leg",
    lockedLegIndex: 0,
    maxHold: 5,
    minOdds: -5000,
    maxOdds: 5000,
    maxAge: 90,
    commissionBps: 0,
    minDistance: 0.5,
    distinctBooks: true,
    includeExact: true,
    includeMiddles: true,
    lineWarning: true,
    books: eligibleBooks.filter((book) => book.defaultExecution).map((book) => book.key),
    markets: defaultMarkets,
    sort: "hold-asc",
    requiredBook: "",
  };

  const initialBookKeys = Array.isArray(stored.books) && stored.books.length
    ? stored.books.filter((key) => eligibleBooks.some((book) => book.key === key))
    : defaults.books;
  const initialRequiredBook = typeof stored.requiredBook === "string" && initialBookKeys.includes(stored.requiredBook)
    ? stored.requiredBook
    : defaults.requiredBook;

  const state = {
    rows: [],
    diagnostics: {},
    loading: false,
    error: "",
    degraded: false,
    paused: false,
    liveActive: true,
    selectedId: null,
    search: "",
    sport: "",
    maxHours: 48,
    view: "live",
    hiddenItems: readHiddenOpportunities(),
    bookGroup: "all",
    alerts: false,
    calculationOpen: false,
    visibleLimit: 100,
    stake: numberBetween(stored.stake, 1, 10_000_000, defaults.stake),
    stakeMode: ["first-leg", "total"].includes(stored.stakeMode) ? stored.stakeMode : defaults.stakeMode,
    lockedLegIndex: numberBetween(stored.lockedLegIndex, 0, 12, defaults.lockedLegIndex),
    maxHold: numberBetween(stored.maxHold, 0, 25, defaults.maxHold),
    minOdds: numberBetween(stored.minOdds, -5000, 5000, defaults.minOdds),
    maxOdds: numberBetween(stored.maxOdds, -5000, 5000, defaults.maxOdds),
    maxAge: numberBetween(stored.maxAge, 15, 1800, defaults.maxAge),
    commissionBps: numberBetween(stored.commissionBps, 0, 2500, defaults.commissionBps),
    minDistance: numberBetween(stored.minDistance, 0.5, 20, defaults.minDistance),
    distinctBooks: stored.distinctBooks === undefined ? defaults.distinctBooks : Boolean(stored.distinctBooks),
    includeExact: stored.includeExact === undefined ? defaults.includeExact : Boolean(stored.includeExact),
    includeMiddles: stored.includeMiddles === undefined ? defaults.includeMiddles : Boolean(stored.includeMiddles),
    lineWarning: stored.lineWarning === undefined ? defaults.lineWarning : Boolean(stored.lineWarning),
    selectedBooks: new Set(initialBookKeys),
    selectedMarkets: new Set(Array.isArray(stored.markets) && stored.markets.length ? stored.markets : defaults.markets),
    sort: ["hold-asc", "time-asc"].includes(stored.sort) ? stored.sort : defaults.sort,
    requiredBook: initialRequiredBook,
    timer: null,
    stakeTimer: null,
  };

  const elements = {
    feed: document.getElementById("lh-feed"),
    detail: document.getElementById("lh-detail"),
    detailPlaceholder: document.getElementById("lh-detail-placeholder"),
    detailContent: document.getElementById("lh-detail-content"),
    search: document.getElementById("lh-search"),
    stake: document.getElementById("lh-stake"),
    stakeMode: document.getElementById("lh-stake-mode"),
    dialogStake: document.getElementById("lh-dialog-stake"),
    dialogStakeLabel: document.getElementById("lh-dialog-stake-label"),
    sport: document.getElementById("lh-sport-filter"),
    sportTrigger: document.getElementById("lh-sport-trigger"),
    sportValue: document.getElementById("lh-sport-value"),
    sportMenu: document.getElementById("lh-sport-menu"),
    time: document.getElementById("lh-time-filter"),
    sort: document.getElementById("lh-sort"),
    sortTrigger: document.getElementById("lh-sort-trigger"),
    sortValue: document.getElementById("lh-sort-value"),
    sortMenu: document.getElementById("lh-sort-menu"),
    requiredBookTrigger: document.getElementById("lh-required-book-trigger"),
    requiredBookValue: document.getElementById("lh-required-book-value"),
    requiredBookMenu: document.getElementById("lh-required-book-menu"),
    refresh: document.getElementById("lh-refresh"),
    pause: document.getElementById("lh-pause"),
    alerts: document.getElementById("lh-alerts"),
    filterDialog: document.getElementById("lh-filter-dialog"),
    filterCount: document.getElementById("lh-filter-count"),
    bookGrid: document.getElementById("lh-book-grid"),
    bookSearch: document.getElementById("lh-book-search"),
    maxHold: document.getElementById("lh-max-hold"),
    minOdds: document.getElementById("lh-min-odds"),
    maxOdds: document.getElementById("lh-max-odds"),
    minDistance: document.getElementById("lh-min-distance"),
    maxAge: document.getElementById("lh-max-age"),
    commission: document.getElementById("lh-commission"),
    distinct: document.getElementById("lh-distinct-books"),
    includeExact: document.getElementById("lh-include-exact"),
    includeMiddles: document.getElementById("lh-include-middles"),
    lineWarning: document.getElementById("lh-line-warning"),
    resultCopy: document.getElementById("lh-result-copy"),
    mobileScrim: document.getElementById("lh-mobile-scrim"),
    savedList: document.getElementById("lh-saved-list"),
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

  function marketName(row) {
    return String(row?.marketLabel || row?.marketKey || "Market")
      .replaceAll("_", " ")
      .trim()
      .toUpperCase();
  }

  function money(value, digits = 2) {
    const amount = Number(value || 0);
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(amount);
  }

  function odds(value) {
    const amount = Number(value || 0);
    return amount > 0 ? `+${Math.round(amount)}` : `${Math.round(amount)}`;
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
    const amount = Number(value || 0);
    return `${amount.toFixed(digits)}%`;
  }

  function signedMoney(value) {
    const amount = Number(value || 0);
    if (Math.abs(amount) < 0.005) return money(0);
    return `${amount > 0 ? "+" : "−"}${money(Math.abs(amount))}`;
  }

  function holdTone(row) {
    if (Number(row.holdPercent) <= 2) return "is-low";
    return "is-cost";
  }

  function lowHoldRows(value) {
    return (Array.isArray(value) ? value : []).filter((row) => Number(row?.holdPercent) >= 0);
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

  function detailTeamLogo(row, team, className = "lh-detail-team-logo") {
    const logoUrl = teamLogoUrl(row, team);
    const leagueClass = String(row?.sportKey || "").toLowerCase().includes("wnba") ? " is-wnba" : "";
    return logoUrl
      ? `<span class="${esc(className)} lh-team-logo-frame${leagueClass}" aria-hidden="true"><img src="${esc(logoUrl)}" alt="" loading="lazy" onerror="this.parentElement.hidden=true"></span>`
      : "";
  }

  function teamForSelection(row, selection, leg = {}) {
    const label = String(selection || "").trim().toLowerCase();
    const teams = [row?.awayTeam, row?.homeTeam]
      .map((team) => String(team || "").trim())
      .filter(Boolean);
    const playerTeam = String(leg?.playerTeam || row?.playerTeam || "").trim().toLowerCase();
    const matchedPlayerTeam = playerTeam && teams.find((team) => {
      const normalized = team.toLowerCase();
      return playerTeam === normalized || playerTeam.includes(normalized) || normalized.includes(playerTeam);
    });
    if (matchedPlayerTeam) return matchedPlayerTeam;
    return teams.find((team) => label === team.toLowerCase() || label.startsWith(`${team.toLowerCase()} `)) || "";
  }

  function detailMatchup(row) {
    const away = String(row?.awayTeam || "").trim();
    const home = String(row?.homeTeam || "").trim();
    if (!away || !home) return esc(row?.eventTitle || "Event");
    return `<span class="lh-detail-team lh-detail-team-away">${detailTeamLogo(row, away)}<span>${esc(away)}</span></span> <span class="lh-detail-vs">vs</span> <span class="lh-detail-team lh-detail-team-home"><span>${esc(home)}</span>${detailTeamLogo(row, home)}</span>`;
  }

  function dateTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Time unavailable";
    return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }

  function queueDateParts(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return { day: "Upcoming", time: "" };
    return {
      day: date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      time: date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }),
    };
  }

  function queueLeagueVisual(row) {
    const logoUrl = leagueLogoUrl(row?.sportKey, row?.league);
    return logoUrl
      ? `<img class="lh-queue-league-logo" src="${esc(logoUrl)}" alt="" aria-hidden="true" loading="lazy">`
      : "";
  }

  function timeUntil(value) {
    const milliseconds = new Date(value).getTime() - Date.now();
    if (!Number.isFinite(milliseconds)) return "Upcoming";
    const hours = Math.max(0, Math.round(milliseconds / 3_600_000));
    if (hours < 1) return "Starts soon";
    if (hours < 24) return `In ${hours}h`;
    return `In ${Math.round(hours / 24)}d`;
  }

  function notify(message, tone = "success", action = null) {
    const toast = document.getElementById("app-toast");
    if (!toast) return;
    window.clearTimeout(notify.timer);
    toast.replaceChildren();
    const copy = document.createElement("span");
    copy.textContent = message;
    toast.append(copy);
    if (action?.label && typeof action.onClick === "function") {
      const button = document.createElement("button");
      button.className = "lh-toast-action";
      button.type = "button";
      button.textContent = action.label;
      button.addEventListener("click", () => {
        window.clearTimeout(notify.timer);
        toast.className = "toast";
        action.onClick();
      }, { once: true });
      toast.append(button);
    }
    toast.dataset.tone = tone;
    toast.className = `toast show ${tone}`;
    notify.timer = window.setTimeout(() => { toast.className = "toast"; }, action ? 5200 : 2600);
  }

  function settingsPayload() {
    return {
      stake: state.stake,
      stakeMode: state.stakeMode,
      lockedLegIndex: state.lockedLegIndex,
      maxHold: state.maxHold,
      minOdds: state.minOdds,
      maxOdds: state.maxOdds,
      maxAge: state.maxAge,
      commissionBps: state.commissionBps,
      minDistance: state.minDistance,
      distinctBooks: state.distinctBooks,
      includeExact: state.includeExact,
      includeMiddles: state.includeMiddles,
      lineWarning: state.lineWarning,
      books: [...state.selectedBooks],
      markets: [...state.selectedMarkets],
      sort: state.sort,
      requiredBook: state.requiredBook,
    };
  }

  function saveSettings() {
    localStorage.setItem(storageKey, JSON.stringify(settingsPayload()));
  }

  function savedFilters() {
    try {
      const rows = JSON.parse(localStorage.getItem(savedKey) || "[]");
      return Array.isArray(rows) ? rows : [];
    } catch (_error) { return []; }
  }

  function opportunityKey(row) {
    const outcomes = (row?.outcomes || [])
      .map((leg) => `${String(leg.selection || "").trim().toLowerCase()}::${leg.point ?? ""}`)
      .sort();
    return JSON.stringify([
      String(row?.eventId || row?.eventTitle || "").trim().toLowerCase(),
      String(row?.marketKey || row?.marketLabel || "").trim().toLowerCase(),
      String(row?.marketContext || "").trim().toLowerCase(),
      String(row?.pairKind || "exact").trim().toLowerCase(),
      outcomes,
    ]);
  }

  function hiddenExpiry(row, hiddenAt = Date.now()) {
    const commenceAt = new Date(row?.commenceTime || "").getTime();
    return Number.isFinite(commenceAt) ? commenceAt + hiddenExpiryGraceMs : hiddenAt + (7 * hiddenExpiryGraceMs);
  }

  function readHiddenOpportunities() {
    try {
      const records = JSON.parse(localStorage.getItem(hiddenKey) || "[]");
      const now = Date.now();
      return (Array.isArray(records) ? records : []).filter((record) => (
        record && record.key && record.row && Number(record.expiresAt) > now
      ));
    } catch (_error) { return []; }
  }

  function saveHiddenOpportunities() {
    try {
      localStorage.setItem(hiddenKey, JSON.stringify(state.hiddenItems.slice(-200)));
      return true;
    } catch (_error) { return false; }
  }

  function pruneHiddenOpportunities() {
    const now = Date.now();
    const active = state.hiddenItems.filter((record) => Number(record.expiresAt) > now);
    if (active.length !== state.hiddenItems.length) {
      state.hiddenItems = active;
      saveHiddenOpportunities();
    }
  }

  function hiddenKeys() {
    return new Set(state.hiddenItems.map((record) => record.key));
  }

  function isHiddenOpportunity(row) {
    return hiddenKeys().has(opportunityKey(row));
  }

  function liveOpportunityRows() {
    const hidden = hiddenKeys();
    return state.rows.filter((row) => !hidden.has(opportunityKey(row)));
  }

  function hiddenOpportunityRows() {
    return state.hiddenItems.map((record) => record.row);
  }

  function currentViewRows() {
    return state.view === "hidden" ? hiddenOpportunityRows() : liveOpportunityRows();
  }

  function reconcileHiddenOpportunities(rows) {
    if (!state.hiddenItems.length) return;
    const current = new Map(rows.map((row) => [opportunityKey(row), row]));
    let changed = false;
    state.hiddenItems = state.hiddenItems.map((record) => {
      const refreshed = current.get(record.key);
      if (!refreshed) return record;
      changed = true;
      return { ...record, row: refreshed, expiresAt: hiddenExpiry(refreshed, record.hiddenAt) };
    });
    if (changed) saveHiddenOpportunities();
  }

  function bookLogo(row) {
    const logo = String(row.logoUrl || "");
    return logo ? `<img src="${esc(logo)}" alt="" loading="lazy">` : `<span class="arb-book-fallback"><i class="ph ph-buildings"></i></span>`;
  }

  function rowMatches(row) {
    const query = state.search.trim().toLowerCase();
    if (state.sport && row.sportKey !== state.sport) return false;
    if (state.view === "live" && state.maxHours !== null) {
      const hoursUntilStart = (new Date(row.commenceTime).getTime() - Date.now()) / 3_600_000;
      if (!Number.isFinite(hoursUntilStart) || hoursUntilStart < 0 || hoursUntilStart > state.maxHours) return false;
    }
    if (!query) return true;
    const blob = [
      row.eventTitle,
      row.league,
      row.marketLabel,
      row.marketContext,
      row.pairKind,
      ...(row.outcomes || []).flatMap((leg) => [leg.selection, leg.bookName]),
    ].join(" ").toLowerCase();
    return blob.includes(query);
  }

  function visibleRows() {
    const rows = currentViewRows().filter(rowMatches);
    if (state.sort === "time-asc") return rows.sort((left, right) => new Date(left.commenceTime) - new Date(right.commenceTime));
    return rows.sort((left, right) => left.holdPercent - right.holdPercent || right.retainedPercent - left.retainedPercent);
  }

  function opportunityCard(row, index) {
    const start = queueDateParts(row.commenceTime);
    const executable = row.executionStatus === "EXECUTABLE";
    return `
      <article class="arb-opportunity ${row.id === state.selectedId ? "active" : ""}" data-lh-id="${esc(row.id)}" role="button" tabindex="0" aria-label="${esc(`${percent(row.holdPercent)} ${executable ? "executable" : "theoretical"} hold on ${row.eventTitle}`)}">
        <span class="arb-queue-rank">${index + 1}</span>
        <div class="arb-return-cell lh-hold-cell ${holdTone(row)}"><strong>${percent(row.holdPercent)}</strong><span>${signedMoney(row.outsideNet)}</span></div>
        <div class="arb-event-cell">
          <h3 title="${esc(row.eventTitle)}">${queueLeagueVisual(row)}<span>${esc(row.eventTitle)}</span></h3>
          <p>${esc(row.league)} · ${esc(marketName(row))} · ${row.pairKind === "middle" ? "middle" : `${row.outcomeCount}-way`}</p>
        </div>
        <time class="arb-queue-date" datetime="${esc(row.commenceTime)}"><span>${esc(start.day)}</span><small>${esc(start.time)}</small></time>
      </article>`;
  }

  function renderFeed() {
    if (state.view === "live" && state.loading) {
      elements.feed.innerHTML = `<div class="arb-state arb-loading" role="status"><span class="arb-spinner" aria-hidden="true"></span><strong>Pairing opposing prices</strong><p>Calculating hold, balancing bets, and checking attainable middle outcomes.</p></div>`;
      return;
    }
    if (state.view === "live" && state.error) {
      elements.feed.innerHTML = `<div class="arb-state"><i class="ph ph-warning-circle" aria-hidden="true"></i><strong>Low Hold scan unavailable</strong><p>${esc(state.error)}</p><button class="arb-secondary-button" type="button" data-lh-retry>Try again</button></div>`;
      return;
    }
    if (state.view === "live" && !state.liveActive) {
      elements.feed.innerHTML = `<div class="arb-state"><i class="ph ph-pause-circle" aria-hidden="true"></i><strong>Low Hold scanner is paused</strong><p>Start the feed when you need it. IconLabs requests current prices only on demand to protect provider credits.</p><button class="arb-primary-button" type="button" data-lh-start><i class="ph ph-play"></i>Start scanner</button></div>`;
      return;
    }
    const rows = visibleRows();
    if (!rows.length) {
      elements.feed.innerHTML = state.view === "hidden"
        ? `<div class="arb-state"><i class="ph ph-eye-slash" aria-hidden="true"></i><strong>No hidden opportunities</strong><p>Opportunities you hide will remain here until 24 hours after their scheduled start.</p><button class="arb-secondary-button" type="button" data-lh-show-live>View live opportunities</button></div>`
        : `<div class="arb-state"><i class="ph ph-percent" aria-hidden="true"></i><strong>No live Low Hold pairs match these filters</strong><p>Try more sportsbooks, a higher maximum hold, a wider odds range, or both pair types.</p><button class="arb-secondary-button" type="button" data-lh-open-filters>Adjust filters</button></div>`;
      return;
    }
    const rendered = rows.slice(0, state.visibleLimit);
    const remaining = rows.length - rendered.length;
    elements.feed.innerHTML = (state.view === "live" && state.degraded ? `<div class="arb-detail-warning"><i class="ph ph-warning"></i><span>Showing the last verified Low Hold snapshot while the provider reconnects. Recheck every price and accepted bet.</span></div>` : "") + rendered.map(opportunityCard).join("") + (remaining > 0
      ? `<button class="arb-secondary-button lh-show-more" type="button" data-lh-show-more>Show 100 more <small>${remaining.toLocaleString()} remaining</small></button>`
      : "");
  }

  function updateSummary() {
    const rows = visibleRows();
    const liveRows = liveOpportunityRows();
    const best = [...liveRows].sort((left, right) => left.holdPercent - right.holdPercent)[0];
    const executableCount = rows.filter(row => row.executionStatus === "EXECUTABLE").length;
    document.getElementById("lh-kpi-hold").textContent = best ? percent(best.holdPercent) : "—";
    document.getElementById("lh-kpi-retained").textContent = best ? percent(best.retainedPercent, 1) : "—";
    document.getElementById("lh-kpi-opportunities").textContent = String(liveRows.length);
    document.getElementById("lh-kpi-books").textContent = String(state.selectedBooks.size);
    document.getElementById("lh-live-count").textContent = String(liveRows.length);
    document.getElementById("lh-hidden-count").textContent = String(state.hiddenItems.length);
    const visibleCount = Math.min(rows.length, state.visibleLimit);
    elements.resultCopy.textContent = visibleCount
      ? state.view === "hidden"
        ? `Showing 1–${visibleCount} of ${rows.length} hidden opportunities`
        : `Showing 1–${visibleCount} of ${rows.length} live opportunities · ${executableCount} executable`
      : state.view === "hidden" ? "No hidden opportunities" : "No live opportunities shown";
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
    menu.innerHTML = options.map((option) => `<button type="button" role="option" aria-selected="${option.value === selected.value ? "true" : "false"}" data-lh-quick-option="${esc(kind)}" data-lh-quick-value="${esc(option.value)}">${quickOptionVisual(option)}<span>${esc(option.label)}</span><i class="ph ph-check" aria-hidden="true"></i></button>`).join("");
  }

  function populateQuickFilters() {
    const currentSport = state.sport;
    const sports = [...new Map([...state.rows, ...hiddenOpportunityRows()].map((row) => [row.sportKey, row.league])).entries()].sort((left, right) => left[1].localeCompare(right[1]));
    state.sport = sports.some(([key]) => key === currentSport) ? currentSport : "";
    elements.sport.innerHTML = `<option value="">All sports</option>${sports.map(([key, label]) => `<option value="${esc(key)}">${esc(label)}</option>`).join("")}`;
    elements.sport.value = state.sport;
    renderQuickSelect("sport", [
      { value: "", label: "All sports", icon: "ph-trophy" },
      ...sports.map(([value, label]) => ({ value, label, logoUrl: leagueLogoUrl(value, label), icon: "ph-trophy" })),
    ], state.sport);

    const sortOptions = [
      { value: "hold-asc", label: "Lowest hold", icon: "ph-sort-ascending" },
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
    document.querySelectorAll("[data-lh-quick-select]").forEach((container) => {
      if (container.dataset.lhQuickSelect === except) return;
      container.classList.remove("is-open");
      container.querySelector(".lh-quick-select-trigger")?.setAttribute("aria-expanded", "false");
      const menu = container.querySelector(".lh-quick-select-menu");
      if (menu) menu.hidden = true;
    });
  }

  function toggleQuickSelect(container) {
    const kind = container.dataset.lhQuickSelect;
    const trigger = container.querySelector(".lh-quick-select-trigger");
    const menu = container.querySelector(".lh-quick-select-menu");
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
      state.visibleLimit = 100;
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
    state.visibleLimit = 100;
    closeQuickSelects();
    renderAll();
  }

  function quoteRow(quote, bestKey, targetPayout) {
    const age = quote.quoteAgeSeconds == null ? "Age n/a" : `${Math.round(quote.quoteAgeSeconds)}s`;
    const projectedStake = Number(targetPayout || 0) / decimalOdds(quote.americanOdds);
    const projectedPayout = projectedStake * decimalOdds(quote.americanOdds);
    return `<div class="arb-quote-row ${quote.bookKey === bestKey ? "best" : ""}">${bookLogo(quote)}<span title="${esc(quote.bookName)}">${esc(quote.bookName)}</span><small>${esc(age)}</small><b>${odds(quote.americanOdds)}</b><strong>${money(projectedStake)}</strong><strong>${money(projectedPayout)}</strong></div>`;
  }

  function scenarioCard(row, label, profit, detail, middle = false, team = "") {
    const amount = Number(profit || 0);
    return `<article class="lh-scenario-card ${middle ? "middle" : ""}"><div class="lh-scenario-label">${team ? detailTeamLogo(row, team, "lh-scenario-team-logo") : ""}<span>${esc(label)}</span></div><strong class="${amount >= 0 ? "positive" : "negative"}">${signedMoney(amount)}</strong><small>${esc(detail)}</small></article>`;
  }

  function renderDetail(row, openOnMobile = false) {
    if (!row) {
      elements.detailPlaceholder.hidden = false;
      elements.detailContent.hidden = true;
      return;
    }
    const lockedIndex = Number.isInteger(row.lockedOutcomeIndex) ? row.lockedOutcomeIndex : 0;
    const executable = row.executionStatus === "EXECUTABLE";
    const hidden = isHiddenOpportunity(row);
    const renderedMarket = esc(marketName(row));
    const plan = (row.outcomes || []).map((leg, index) => {
      const team = teamForSelection(row, leg.selection, leg);
      return `
      <article class="arb-plan-leg">
        <div class="arb-plan-outcome lh-plan-outcome">${team ? detailTeamLogo(row, team, "lh-plan-team-logo") : ""}<span><strong>${esc(leg.selection)}</strong><small>${row.stakeMode === "first-leg" ? (index === lockedIndex ? `<span class="lh-lock-status"><i class="ph ph-lock-key"></i>Baseline Amount · Locked</span>` : `<button class="lh-lock-leg" type="button" data-lh-lock-leg="${index}">Use as Baseline</button>`) : renderedMarket}</small></span></div>
        <div class="arb-plan-book">${bookLogo(leg)}<span><strong>${esc(leg.bookName)}</strong>${leg.capacityKnown ? `<small>${money(leg.executionCapacity)} ${leg.capacityType === "TOP_PRICE_LIQUIDITY" ? "liquidity" : "limit"}</small>` : ""}</span></div>
        <b class="arb-plan-odds">${odds(leg.americanOdds)}</b>
        <div class="arb-plan-stake"><b>${money(leg.stake)}</b></div>
        <b class="arb-plan-payout">${money(leg.payout)}</b>
        ${leg.deepLink ? `<a class="arb-bet-link" href="${esc(leg.deepLink)}" target="_blank" rel="noopener noreferrer">BET<i class="ph ph-arrow-up-right"></i></a>` : `<span class="arb-bet-link disabled">BET</span>`}
      </article>`;
    }).join("");
    const payoutMax = Math.max(...row.outcomes.map((leg) => Number(leg.payout || 0)), 1);
    const payouts = row.outcomes.map((leg) => `<div class="arb-payout-row"><span title="${esc(leg.selection)}">${esc(leg.selection)}</span><progress max="${payoutMax}" value="${Number(leg.payout)}"></progress><b class="${Number(leg.profit) >= 0 ? "positive" : "lh-negative"}">${signedMoney(leg.profit)}</b></div>`).join("");
    const outsideCards = (row.outcomes || []).slice(0, 2).map((leg) => {
      const team = teamForSelection(row, leg.selection, leg);
      return scenarioCard(row, `${leg.selection} hits`, leg.profit, `${leg.bookName} wins`, false, team);
    });
    if (row.middleScenario) {
      outsideCards.splice(1, 0, scenarioCard(row, row.middleScenario.label, row.middleProfit, `Result ${row.middleScenario.result} · ${percent(row.middleReturnPercent)} return`, true));
    }
    const comparisons = (row.allQuotes || []).map((group) => {
      const selected = row.outcomes.find((leg) => leg.selection === group.selection);
      const quotes = sortQuotesByBestPrice(group.quotes, selected?.bookKey);
      return `<section class="arb-comparison-group" data-line-shop-group><h4>${esc(group.selection)}</h4><div class="arb-quote-head"><span>Book</span><span>Age</span><span>Odds</span><span>Bet</span><span>Payout</span></div>${quotes.map((quote) => quoteRow(quote, selected?.bookKey, row.minPayout)).join("")}</section>`;
    }).join("");
    const netLabel = Number(row.outsideNet) >= 0
      ? row.executionStatus === "EXECUTABLE" ? "Verified outside profit" : "Modeled outside profit"
      : "Worst Case Cost";
    const netValue = Number(row.outsideNet) >= 0
      ? signedMoney(row.outsideNet)
      : money(Math.abs(Number(row.outsideNet)));
    const executionLabel = executable ? "Executable — all gates verified" : "Theoretical — verify limits, rules, and eligibility";
    elements.detailContent.innerHTML = `
      <header class="arb-detail-hero">
        <div class="arb-detail-main">
          <div class="arb-detail-hero-top"><div class="arb-detail-return lh-detail-hold ${holdTone(row)}"><strong>${percent(row.holdPercent)}</strong><span>hold</span></div><button class="arb-icon-button arb-detail-close" type="button" data-lh-close-detail aria-label="Close bet plan"><i class="ph ph-x"></i></button></div>
          <h2 class="lh-detail-matchup" title="${esc(row.eventTitle)}" aria-label="${esc(row.eventTitle)}">${detailMatchup(row)}</h2>
          <p>${esc(row.league)} · ${renderedMarket} · ${esc(executionLabel)}</p>
        </div>
        <dl class="arb-detail-facts"><div class="lh-market-fact"><dt>Market</dt><dd title="${renderedMarket}">${renderedMarket}</dd></div><div><dt>Start time</dt><dd>${esc(dateTime(row.commenceTime))}</dd></div></dl>
        <div class="arb-detail-actions"><button class="arb-primary-button" type="button" ${hidden ? "data-lh-restore-opportunity" : "data-lh-hide-opportunity"}><i class="ph ${hidden ? "ph-arrow-counter-clockwise" : "ph-eye-slash"}"></i>${hidden ? "Restore Opportunity" : "Hide Opportunity"}</button><button class="arb-secondary-button" type="button" data-lh-recalculate><i class="ph ph-calculator"></i>Recalculate</button></div>
      </header>
      ${executable ? "" : `<div class="arb-detail-warning"><i class="ph ph-shield-warning"></i><span>This is a mathematical low-hold pair, not an executable claim. One or more capacity, settlement, or account-eligibility gates are unverified.</span></div>`}
      <section class="arb-detail-section arb-stake-plan-section"><header><h3>${executable ? "Bet Plan" : "Verification Plan"}</h3><span>${row.outcomeCount} outcomes · ${row.bookCount} books</span></header><div class="arb-plan-head"><span>Outcome</span><span>Book</span><span>Odds</span><span>Bet</span><span>Payout</span><span class="sr-only">Action</span></div><div class="arb-plan-list">${plan}</div></section>
      <section class="arb-detail-section arb-guaranteed-section"><header><h3>Balanced Outcome</h3><span>after fees &amp; cent rounding</span></header><div class="arb-guaranteed-layout"><div class="arb-profit-proof"><div><span>Total bet</span><strong>${money(row.totalStake)}</strong></div><div><span>Capital retained</span><strong>${percent(row.retainedPercent, 1)}</strong></div><div><span>${esc(netLabel)}</span><strong class="${Number(row.outsideNet) >= 0 ? "positive" : ""}">${netValue}</strong></div></div><div class="arb-payout-list">${payouts}</div></div></section>
      <section class="arb-detail-section arb-odds-section"><header><h3>Odds Comparison</h3><span>best price first</span></header><div class="arb-comparison-grid">${comparisons}</div></section>
      <details class="arb-detail-section arb-calculation" ${state.calculationOpen ? "open" : ""}><summary><h3>Calculation Details</h3><i class="ph ph-caret-down" aria-hidden="true"></i></summary><div class="lh-scenario-grid">${outsideCards.join("")}</div><div class="arb-math-note"><i class="ph ph-function"></i><p>The opposing implied probabilities total <strong>${Number(row.impliedProbabilityPercent).toFixed(3)}%</strong>, producing a <strong>${percent(row.holdPercent, 3)}</strong> hold before cent-level payout balancing.<code>(${Number(row.inverseProbabilitySum).toFixed(6)} − 1) × 100 = ${percent(row.holdPercent, 3)}</code></p></div>${row.stakeMode === "first-leg" ? `<div class="lh-sizing-note"><i class="ph ph-lock-key"></i><span><strong>${money(row.lockedStake)}</strong> is the baseline amount; every hedge is rounded to the closest equal payout.</span></div>` : ""}${state.lineWarning ? `<div class="arb-detail-warning"><i class="ph ph-clock-countdown"></i><span>Confirm both displayed prices and accepted bets before submitting either leg.</span></div>` : ""}</details>`;
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
    const row = currentViewRows().find((item) => item.id === id);
    if (!row) return;
    state.selectedId = id;
    renderFeed();
    renderDetail(row, openOnMobile);
  }

  function renderAll() {
    pruneHiddenOpportunities();
    updateSummary();
    populateQuickFilters();
    renderFeed();
    const rows = visibleRows();
    const selected = rows.find((row) => row.id === state.selectedId) || rows[0];
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
    params.set("stake_mode", state.stakeMode);
    params.set("locked_leg", String(state.lockedLegIndex));
    params.set("max_hold", String(state.maxHold));
    params.set("min_odds", String(state.minOdds));
    params.set("max_odds", String(state.maxOdds));
    params.set("min_distance", String(state.minDistance));
    params.set("max_quote_age", String(state.maxAge));
    params.set("commission_bps", String(state.commissionBps));
    params.set("distinct_books", state.distinctBooks ? "1" : "0");
    params.set("include_exact", state.includeExact ? "1" : "0");
    params.set("include_middles", state.includeMiddles ? "1" : "0");
    params.set("books", [...state.selectedBooks].join(","));
    if (state.requiredBook) params.set("required_book", state.requiredBook);
    params.set("markets", [...state.selectedMarkets].join(","));
    return `/api/low-hold?${params.toString()}`;
  }

  async function loadBoard({ quiet = false } = {}) {
    if (state.loading || !state.liveActive) { renderAll(); return; }
    const url = endpoint();
    const cacheKey = pagePayloadCacheKey("low-hold", url);
    if (!quiet && !state.rows.length) {
      const cached = readPagePayloadCache(cacheKey, 5 * 60 * 1000);
      if (cached) {
        state.rows = lowHoldRows(cached.data);
        reconcileHiddenOpportunities(state.rows);
        state.diagnostics = cached.diagnostics || {};
        renderAll();
      }
    }
    state.loading = true;
    state.error = "";
    if (!quiet && !state.rows.length) renderFeed();
    elements.refresh.classList.add("is-spinning");
    try {
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.message || payload.error || "Unable to scan Low Hold markets.");
      writePagePayloadCache(cacheKey, payload);
      state.rows = lowHoldRows(payload.data);
      reconcileHiddenOpportunities(state.rows);
      state.diagnostics = payload.diagnostics || {};
      state.paused = Boolean(payload.paused);
      state.degraded = Boolean(payload.degraded || payload.stale);
      if (state.alerts && state.rows.length) notify(`${state.rows.length} Low Hold opportunit${state.rows.length === 1 ? "y" : "ies"} found.`);
      scheduleRefresh(Number(payload.refreshSeconds || 60));
    } catch (error) {
      if (!state.rows.length) state.diagnostics = {};
      state.degraded = state.rows.length > 0;
      state.error = state.rows.length ? "" : error.message;
      notify(state.rows.length ? "Recent Low Hold scan shown; live refresh delayed." : error.message, "error");
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
    notify(state.paused ? "Automatic Low Hold refresh paused." : "Automatic Low Hold refresh resumed.");
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
    elements.bookGrid.innerHTML = books.map((book) => `<label class="arb-book-option"><input type="checkbox" value="${esc(book.key)}" ${state.selectedBooks.has(book.key) ? "checked" : ""}>${book.logoUrl ? `<img src="${esc(book.logoUrl)}" alt="" loading="lazy">` : `<span class="arb-book-fallback"><i class="ph ph-buildings"></i></span>`}<span>${esc(book.name)}</span></label>`).join("");
    document.getElementById("lh-book-filter-count").textContent = `${state.selectedBooks.size}/${eligibleBooks.length}`;
    document.getElementById("lh-selected-summary").textContent = `${state.selectedBooks.size}/${eligibleBooks.length} selected`;
  }

  function renderSavedFilters() {
    const filters = savedFilters();
    document.getElementById("lh-saved-count").textContent = String(filters.length);
    if (!filters.length) {
      elements.savedList.innerHTML = `<div class="lh-saved-empty"><i class="ph ph-bookmark-simple"></i><strong>No filters saved yet</strong><p>Configure this scan, then use Save filter below.</p></div>`;
      return;
    }
    elements.savedList.innerHTML = filters.map((filter, index) => `<article class="lh-saved-filter"><i class="ph ph-bookmark-simple"></i><div><strong>${esc(filter.name)}</strong><small>${filter.stakeMode === "total" ? "Total bankroll" : "Baseline locked"} · ${Number(filter.maxHold).toFixed(1)}% max · ${(filter.books || []).length} books</small></div><button type="button" data-lh-load-filter="${index}">Load</button><button type="button" data-lh-delete-filter="${index}" aria-label="Delete ${esc(filter.name)}"><i class="ph ph-trash"></i></button></article>`).join("");
  }

  function syncStakeModeUI() {
    const firstLegMode = state.stakeMode === "first-leg";
    elements.stakeMode.value = state.stakeMode;
    elements.dialogStakeLabel.textContent = firstLegMode ? "Baseline Amount" : "Total Bet";
    elements.stake.setAttribute("aria-label", firstLegMode ? "Baseline Amount" : "Total Bet");
    elements.stake.step = firstLegMode ? "10" : "25";
    elements.dialogStake.step = firstLegMode ? "10" : "25";
    document.querySelectorAll('input[name="lh-stake-mode"]').forEach((input) => {
      input.checked = input.value === state.stakeMode;
    });
  }

  function syncDialog() {
    elements.dialogStake.value = state.stake;
    syncStakeModeUI();
    elements.maxHold.value = state.maxHold;
    elements.minOdds.value = state.minOdds;
    elements.maxOdds.value = state.maxOdds;
    elements.minDistance.value = state.minDistance;
    elements.maxAge.value = state.maxAge;
    elements.commission.value = state.commissionBps;
    elements.distinct.checked = state.distinctBooks;
    elements.includeExact.checked = state.includeExact;
    elements.includeMiddles.checked = state.includeMiddles;
    elements.lineWarning.checked = state.lineWarning;
    document.querySelectorAll("#lh-market-choices input").forEach((input) => { input.checked = state.selectedMarkets.has(input.value); });
    document.querySelectorAll('input[name="lh-dialog-sort"]').forEach((input) => { input.checked = input.value === state.sort; });
    renderBookGrid(elements.bookSearch.value);
    renderSavedFilters();
  }

  function activeFilterCount() {
    let count = 0;
    if (state.selectedBooks.size !== defaults.books.length) count += 1;
    if (state.maxHold !== defaults.maxHold) count += 1;
    if (state.minOdds !== defaults.minOdds || state.maxOdds !== defaults.maxOdds) count += 1;
    if (state.stake !== defaults.stake) count += 1;
    if (state.stakeMode !== defaults.stakeMode || state.lockedLegIndex !== defaults.lockedLegIndex) count += 1;
    if (state.selectedMarkets.size !== defaults.markets.length) count += 1;
    if (state.minDistance !== defaults.minDistance) count += 1;
    if (state.maxAge !== defaults.maxAge || state.commissionBps !== defaults.commissionBps) count += 1;
    if (!state.distinctBooks || !state.includeExact || !state.includeMiddles) count += 1;
    return count;
  }

  function updateFilterBadge() {
    const count = activeFilterCount();
    elements.filterCount.hidden = count === 0;
    elements.filterCount.textContent = String(count);
  }

  function applyDialog() {
    const chosenBooks = [...elements.bookGrid.closest(".arb-filter-panel").querySelectorAll('.arb-book-option input:checked')].map((input) => input.value);
    const allVisibleBookKeys = new Set(filteredBookCatalog(elements.bookSearch.value).map((book) => book.key));
    state.selectedBooks = new Set([...state.selectedBooks].filter((key) => !allVisibleBookKeys.has(key)));
    chosenBooks.forEach((key) => state.selectedBooks.add(key));
    state.stakeMode = document.querySelector('input[name="lh-stake-mode"]:checked')?.value || defaults.stakeMode;
    state.stake = numberBetween(elements.dialogStake.value, 1, 10_000_000, defaults.stake);
    state.maxHold = numberBetween(elements.maxHold.value, 0, 25, defaults.maxHold);
    state.minOdds = numberBetween(elements.minOdds.value, -5000, 5000, defaults.minOdds);
    state.maxOdds = numberBetween(elements.maxOdds.value, -5000, 5000, defaults.maxOdds);
    state.minDistance = numberBetween(elements.minDistance.value, 0.5, 20, defaults.minDistance);
    state.maxAge = numberBetween(elements.maxAge.value, 15, 1800, defaults.maxAge);
    state.commissionBps = numberBetween(elements.commission.value, 0, 2500, defaults.commissionBps);
    state.distinctBooks = elements.distinct.checked;
    state.includeExact = elements.includeExact.checked;
    state.includeMiddles = elements.includeMiddles.checked;
    state.lineWarning = elements.lineWarning.checked;
    state.selectedMarkets = new Set([...document.querySelectorAll("#lh-market-choices input:checked")].map((input) => input.value));
    state.sort = document.querySelector('input[name="lh-dialog-sort"]:checked')?.value || defaults.sort;
    if (!state.selectedBooks.size) { notify("Select at least one sportsbook or exchange.", "error"); return; }
    if (state.requiredBook && !state.selectedBooks.has(state.requiredBook)) {
      state.requiredBook = "";
      notify("Required book reset to Any selected book because it is no longer selected.");
    }
    if (!state.selectedMarkets.size) { notify("Select at least one market.", "error"); return; }
    if (!state.includeExact && !state.includeMiddles) { notify("Select exact lines, middles, or both.", "error"); return; }
    elements.stake.value = state.stake;
    syncStakeModeUI();
    elements.sort.value = state.sort;
    saveSettings();
    updateFilterBadge();
    elements.filterDialog.close();
    loadBoard();
  }

  function resetDefaults() {
    state.stake = defaults.stake;
    state.stakeMode = defaults.stakeMode;
    state.lockedLegIndex = defaults.lockedLegIndex;
    state.maxHold = defaults.maxHold;
    state.minOdds = defaults.minOdds;
    state.maxOdds = defaults.maxOdds;
    state.minDistance = defaults.minDistance;
    state.maxAge = defaults.maxAge;
    state.commissionBps = defaults.commissionBps;
    state.distinctBooks = defaults.distinctBooks;
    state.includeExact = defaults.includeExact;
    state.includeMiddles = defaults.includeMiddles;
    state.lineWarning = defaults.lineWarning;
    state.selectedBooks = new Set(defaults.books);
    state.selectedMarkets = new Set(defaults.markets);
    state.sort = defaults.sort;
    state.requiredBook = defaults.requiredBook;
    state.bookGroup = "all";
    document.querySelectorAll("[data-lh-book-group]").forEach((button) => button.classList.toggle("active", button.dataset.lhBookGroup === "all"));
    syncDialog();
    notify("Low Hold filters reset.");
  }

  function saveFilter() {
    const filters = savedFilters();
    const suggested = `Low Hold ${filters.length + 1}`;
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
    state.stake = numberBetween(filter.stake, 1, 10_000_000, defaults.stake);
    state.stakeMode = ["first-leg", "total"].includes(filter.stakeMode) ? filter.stakeMode : defaults.stakeMode;
    state.lockedLegIndex = numberBetween(filter.lockedLegIndex, 0, 12, defaults.lockedLegIndex);
    state.maxHold = numberBetween(filter.maxHold, 0, 25, defaults.maxHold);
    state.minOdds = numberBetween(filter.minOdds, -5000, 5000, defaults.minOdds);
    state.maxOdds = numberBetween(filter.maxOdds, -5000, 5000, defaults.maxOdds);
    state.minDistance = numberBetween(filter.minDistance, 0.5, 20, defaults.minDistance);
    state.maxAge = numberBetween(filter.maxAge, 15, 1800, defaults.maxAge);
    state.commissionBps = numberBetween(filter.commissionBps, 0, 2500, defaults.commissionBps);
    state.distinctBooks = Boolean(filter.distinctBooks);
    state.includeExact = filter.includeExact !== false;
    state.includeMiddles = filter.includeMiddles !== false;
    state.lineWarning = filter.lineWarning !== false;
    state.selectedBooks = new Set((filter.books || []).filter((key) => eligibleBooks.some((book) => book.key === key)));
    state.selectedMarkets = new Set(filter.markets || defaults.markets);
    state.sort = ["hold-asc", "time-asc"].includes(filter.sort) ? filter.sort : defaults.sort;
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

  function restoreOpportunity(key, { announce = true, returnToLive = false } = {}) {
    const record = state.hiddenItems.find((item) => item.key === key);
    if (!record) return;
    state.hiddenItems = state.hiddenItems.filter((item) => item.key !== key);
    saveHiddenOpportunities();
    if (returnToLive) state.view = "live";
    state.selectedId = returnToLive ? record.row.id : null;
    syncOpportunityView();
    renderAll();
    if (announce) notify("Opportunity restored.");
  }

  function hideOpportunity() {
    const row = currentViewRows().find((item) => item.id === state.selectedId);
    if (!row || isHiddenOpportunity(row)) return;
    const hiddenAt = Date.now();
    const record = {
      key: opportunityKey(row),
      hiddenAt,
      expiresAt: hiddenExpiry(row, hiddenAt),
      row,
    };
    state.hiddenItems = [...state.hiddenItems.filter((item) => item.key !== record.key), record];
    const persisted = saveHiddenOpportunities();
    state.selectedId = null;
    renderAll();
    notify(persisted ? "Opportunity hidden." : "Opportunity hidden for this session only.", persisted ? "success" : "error", {
      label: "Undo",
      onClick: () => restoreOpportunity(record.key, { returnToLive: true }),
    });
  }

  function restoreSelectedOpportunity() {
    const row = currentViewRows().find((item) => item.id === state.selectedId);
    if (!row) return;
    restoreOpportunity(opportunityKey(row));
  }

  function syncOpportunityView() {
    document.querySelectorAll("[data-lh-view]").forEach((button) => {
      const active = button.dataset.lhView === state.view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function setOpportunityView(view) {
    state.view = view === "hidden" ? "hidden" : "live";
    state.selectedId = null;
    state.visibleLimit = 100;
    syncOpportunityView();
    renderAll();
  }

  function openFilter(tab = "sportsbooks") {
    syncDialog();
    document.querySelector(`[data-lh-filter-tab="${tab}"]`)?.click();
    elements.filterDialog.showModal();
  }

  document.querySelectorAll("[data-lh-view]").forEach((button) => button.addEventListener("click", () => {
    setOpportunityView(button.dataset.lhView);
  }));

  document.querySelectorAll("[data-lh-filter-tab]").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll("[data-lh-filter-tab]").forEach((item) => item.classList.toggle("active", item === button));
    document.querySelectorAll("[data-lh-filter-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.lhFilterPanel === button.dataset.lhFilterTab));
  }));

  document.querySelectorAll("[data-lh-book-group]").forEach((button) => button.addEventListener("click", () => {
    state.bookGroup = button.dataset.lhBookGroup;
    document.querySelectorAll("[data-lh-book-group]").forEach((item) => item.classList.toggle("active", item === button));
    renderBookGrid(elements.bookSearch.value);
  }));

  elements.feed.addEventListener("click", (event) => {
    if (event.target.closest("[data-lh-show-live]")) {
      setOpportunityView("live");
      return;
    }
    if (event.target.closest("[data-lh-show-more]")) {
      state.visibleLimit += 100;
      renderAll();
      return;
    }
    const card = event.target.closest("[data-lh-id]");
    if (card) selectRow(card.dataset.lhId, true);
    if (event.target.closest("[data-lh-retry]")) loadBoard();
    if (event.target.closest("[data-lh-start]")) startScanner();
    if (event.target.closest("[data-lh-open-filters]")) openFilter();
  });
  elements.feed.addEventListener("keydown", (event) => {
    const card = event.target.closest("[data-lh-id]");
    if (card && ["Enter", " "].includes(event.key)) { event.preventDefault(); selectRow(card.dataset.lhId, true); }
  });
  elements.detail.addEventListener("click", (event) => {
    if (event.target.closest("[data-lh-close-detail]")) closeMobileDetail();
    if (event.target.closest("[data-lh-hide-opportunity]")) hideOpportunity();
    if (event.target.closest("[data-lh-restore-opportunity]")) restoreSelectedOpportunity();
    if (event.target.closest("[data-lh-recalculate]")) openFilter("hold");
    const lockLeg = event.target.closest("[data-lh-lock-leg]");
    if (lockLeg) {
      state.stakeMode = "first-leg";
      state.lockedLegIndex = numberBetween(lockLeg.dataset.lhLockLeg, 0, 12, 0);
      syncStakeModeUI();
      saveSettings();
      notify("Baseline outcome changed. Recalculating the hedge.");
      loadBoard({ quiet: true });
    }
  });
  elements.savedList.addEventListener("click", (event) => {
    const load = event.target.closest("[data-lh-load-filter]");
    const remove = event.target.closest("[data-lh-delete-filter]");
    if (load) loadSaved(Number(load.dataset.lhLoadFilter));
    if (remove) deleteSaved(Number(remove.dataset.lhDeleteFilter));
  });

  document.querySelector(".arb-board-actions")?.addEventListener("click", (event) => {
    const option = event.target.closest("[data-lh-quick-option]");
    if (option) {
      chooseQuickOption(option.dataset.lhQuickOption, option.dataset.lhQuickValue || "");
      return;
    }
    const trigger = event.target.closest(".lh-quick-select-trigger");
    if (trigger) toggleQuickSelect(trigger.closest("[data-lh-quick-select]"));
  });
  document.querySelector(".arb-board-actions")?.addEventListener("keydown", (event) => {
    const option = event.target.closest("[data-lh-quick-option]");
    if (!option || !["ArrowDown", "ArrowUp"].includes(event.key)) return;
    event.preventDefault();
    const options = [...option.parentElement.querySelectorAll("[data-lh-quick-option]")];
    const step = event.key === "ArrowDown" ? 1 : -1;
    options[(options.indexOf(option) + step + options.length) % options.length]?.focus();
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest("[data-lh-quick-select]")) closeQuickSelects();
  });
  elements.detail.addEventListener("toggle", (event) => {
    if (event.target.matches(".arb-calculation")) state.calculationOpen = event.target.open;
  }, true);

  elements.search.addEventListener("input", () => { state.search = elements.search.value; state.visibleLimit = 100; renderAll(); });
  elements.search.addEventListener("keydown", (event) => { if (event.key === "Escape") { elements.search.value = ""; state.search = ""; renderAll(); } });
  elements.stake.addEventListener("input", () => {
    window.clearTimeout(state.stakeTimer);
    state.stakeTimer = window.setTimeout(() => {
      state.stake = numberBetween(elements.stake.value, 1, 10_000_000, defaults.stake);
      saveSettings();
      loadBoard({ quiet: true });
    }, 420);
  });
  elements.stakeMode.addEventListener("change", () => {
    state.stakeMode = elements.stakeMode.value === "total" ? "total" : "first-leg";
    if (state.stakeMode === "total") state.lockedLegIndex = 0;
    syncStakeModeUI();
    saveSettings();
    loadBoard({ quiet: true });
  });
  elements.sport.addEventListener("change", () => { state.sport = elements.sport.value; state.visibleLimit = 100; renderAll(); });
  elements.time.addEventListener("change", () => { state.maxHours = elements.time.value === "all" ? null : Number(elements.time.value); state.visibleLimit = 100; renderAll(); });
  elements.sort.addEventListener("change", () => { state.sort = elements.sort.value; state.visibleLimit = 100; saveSettings(); renderAll(); });
  elements.refresh.addEventListener("click", () => { if (!state.liveActive) startScanner(); else loadBoard(); });
  elements.pause.addEventListener("click", togglePause);
  elements.alerts.addEventListener("click", () => { state.alerts = !state.alerts; elements.alerts.setAttribute("aria-pressed", state.alerts ? "true" : "false"); notify(state.alerts ? "Low Hold alerts enabled." : "Low Hold alerts disabled."); });
  document.getElementById("lh-filter-open").addEventListener("click", () => openFilter());
  document.getElementById("lh-filter-close").addEventListener("click", () => elements.filterDialog.close());
  document.getElementById("lh-apply").addEventListener("click", applyDialog);
  document.getElementById("lh-reset").addEventListener("click", resetDefaults);
  document.getElementById("lh-save-filter").addEventListener("click", saveFilter);
  document.querySelectorAll('input[name="lh-stake-mode"]').forEach((input) => input.addEventListener("change", () => {
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

  function selectAllBooks() { filteredBookCatalog(elements.bookSearch.value).forEach((book) => state.selectedBooks.add(book.key)); renderBookGrid(elements.bookSearch.value); }
  function clearBooks() { filteredBookCatalog(elements.bookSearch.value).forEach((book) => state.selectedBooks.delete(book.key)); renderBookGrid(elements.bookSearch.value); }
  document.getElementById("lh-books-all").addEventListener("click", selectAllBooks);
  document.getElementById("lh-books-all-top").addEventListener("click", () => { eligibleBooks.forEach((book) => state.selectedBooks.add(book.key)); renderBookGrid(elements.bookSearch.value); });
  document.getElementById("lh-books-clear").addEventListener("click", clearBooks);
  document.getElementById("lh-books-clear-top").addEventListener("click", () => { state.selectedBooks.clear(); renderBookGrid(elements.bookSearch.value); });

  const learnDialog = document.getElementById("lh-learn-dialog");
  document.getElementById("lh-learn-open").addEventListener("click", () => learnDialog.showModal());
  document.getElementById("lh-learn-close").addEventListener("click", () => learnDialog.close());
  document.getElementById("lh-learn-done").addEventListener("click", () => learnDialog.close());
  elements.mobileScrim.addEventListener("click", closeMobileDetail);
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && !/input|textarea|select/i.test(document.activeElement?.tagName || "")) { event.preventDefault(); elements.search.focus(); }
    if (event.key === "Escape") { closeQuickSelects(); closeMobileDetail(); }
  });

  elements.stake.value = state.stake;
  syncStakeModeUI();
  syncOpportunityView();
  elements.sort.value = state.sort;
  updateFilterBadge();
  syncDialog();
  loadBoard();
})();
