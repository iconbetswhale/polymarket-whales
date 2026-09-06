(() => {
  const pageRoot = document.querySelector(".arb-page");
  if (!pageRoot) return;

  const configNode = document.getElementById("arb-config");
  let config = { books: [] };
  try { config = JSON.parse(configNode?.textContent || "{}"); } catch (_error) { config = { books: [] }; }

  const eligibleBooks = (config.books || []).filter((book) => book.type !== "dfs");
  const defaultBookKeys = eligibleBooks.filter((book) => book.defaultExecution !== false).map((book) => book.key);
  const configuredMarketKeys = Object.values(config.marketGroups || {}).flat()
    .map((market) => typeof market === "string" ? market : market?.key)
    .filter(Boolean);
  const storageKey = "iconlabsArbitrageSettingsV3";
  const hiddenStorageKey = "iconlabs-arbitrage-hidden-opportunities";
  const hiddenRowsStorageKey = "iconlabs-arbitrage-hidden-snapshots";
  const trackedStorageKey = "iconlabs-arbitrage-tracked-opportunities";
  const defaults = {
    stake: 1000,
    stakeMode: "total",
    lockedLegIndex: 0,
    minProfit: 0.1,
    maxAge: 90,
    commissionBps: 0,
    distinctBooks: true,
    books: defaultBookKeys,
    markets: configuredMarketKeys.length ? configuredMarketKeys : ["h2h", "spreads", "totals"],
    sort: "profit-desc",
    requiredBook: "",
  };
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem(storageKey) || "{}"); } catch (_error) { stored = {}; }
  let hiddenIds = new Set();
  let hiddenRows = new Map();
  let trackedIds = new Set();
  try {
    const savedHiddenIds = JSON.parse(localStorage.getItem(hiddenStorageKey) || "[]");
    if (Array.isArray(savedHiddenIds)) hiddenIds = new Set(savedHiddenIds.map(String));
    const savedHiddenRows = JSON.parse(localStorage.getItem(hiddenRowsStorageKey) || "[]");
    if (Array.isArray(savedHiddenRows)) hiddenRows = new Map(savedHiddenRows.filter((row) => row?.id).map((row) => [String(row.id), row]));
    const savedTrackedIds = JSON.parse(localStorage.getItem(trackedStorageKey) || "[]");
    if (Array.isArray(savedTrackedIds)) trackedIds = new Set(savedTrackedIds.map(String));
  } catch (_error) {
    hiddenIds = new Set();
    hiddenRows = new Map();
    trackedIds = new Set();
  }

  const initialBookKeys = Array.isArray(stored.books) && stored.books.length
    ? stored.books.filter((key) => eligibleBooks.some((book) => book.key === key))
    : defaults.books;
  const initialRequiredBook = typeof stored.requiredBook === "string" && initialBookKeys.includes(stored.requiredBook)
    ? stored.requiredBook
    : defaults.requiredBook;

  const state = {
    rows: [],
    diagnostics: {},
    error: "",
    degraded: false,
    selectedId: null,
    loading: false,
    paused: false,
    liveActive: true,
    alerts: false,
    view: "live",
    search: "",
    sport: "",
    stake: numberBetween(stored.stake, 1, 10_000_000, defaults.stake),
    stakeMode: ["first-leg", "total"].includes(stored.stakeMode) ? stored.stakeMode : defaults.stakeMode,
    lockedLegIndex: numberBetween(stored.lockedLegIndex, 0, 12, defaults.lockedLegIndex),
    minProfit: numberBetween(stored.minProfit, 0, 50, defaults.minProfit),
    maxAge: numberBetween(stored.maxAge, 15, 1800, defaults.maxAge),
    commissionBps: numberBetween(stored.commissionBps, 0, 2500, defaults.commissionBps),
    distinctBooks: stored.distinctBooks === undefined ? defaults.distinctBooks : Boolean(stored.distinctBooks),
    selectedBooks: new Set(initialBookKeys),
    selectedMarkets: new Set(Array.isArray(stored.markets) && stored.markets.length ? stored.markets : defaults.markets),
    sort: ["profit-desc", "profit-amount-desc", "time-asc"].includes(stored.sort) ? stored.sort : defaults.sort,
    requiredBook: initialRequiredBook,
    timer: null,
    stakeTimer: null,
    trackSession: null,
    calculatorSession: null,
  };

  const elements = {
    feed: document.getElementById("arb-feed"),
    detail: document.getElementById("arb-detail"),
    detailPlaceholder: document.getElementById("arb-detail-placeholder"),
    detailContent: document.getElementById("arb-detail-content"),
    search: document.getElementById("arb-search"),
    stake: document.getElementById("arb-stake"),
    stakeMode: document.getElementById("arb-stake-mode"),
    dialogStake: document.getElementById("arb-dialog-stake"),
    dialogStakeLabel: document.getElementById("arb-dialog-stake-label"),
    sport: document.getElementById("arb-sport-filter"),
    sportTrigger: document.getElementById("arb-sport-trigger"),
    sportValue: document.getElementById("arb-sport-value"),
    sportMenu: document.getElementById("arb-sport-menu"),
    sort: document.getElementById("arb-sort"),
    sortTrigger: document.getElementById("arb-sort-trigger"),
    sortValue: document.getElementById("arb-sort-value"),
    sortMenu: document.getElementById("arb-sort-menu"),
    requiredBookTrigger: document.getElementById("arb-required-book-trigger"),
    requiredBookValue: document.getElementById("arb-required-book-value"),
    requiredBookMenu: document.getElementById("arb-required-book-menu"),
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
    liveCount: document.getElementById("arb-live-count"),
    hiddenCount: document.getElementById("arb-hidden-count"),
    trackDialog: document.getElementById("arb-track-dialog"),
    trackSummary: document.getElementById("arb-track-summary"),
    trackLegs: document.getElementById("arb-track-legs"),
    trackProof: document.getElementById("arb-track-proof"),
    trackError: document.getElementById("arb-track-error"),
    recalculateDialog: document.getElementById("arb-recalculate-dialog"),
    recalculateSummary: document.getElementById("arb-recalculate-summary"),
    recalculateMode: document.getElementById("arb-recalculate-mode"),
    recalculateTotal: document.getElementById("arb-recalculate-total"),
    recalculateLegs: document.getElementById("arb-recalculate-legs"),
    recalculateProof: document.getElementById("arb-recalculate-proof"),
    recalculateError: document.getElementById("arb-recalculate-error"),
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

  function decimalOdds(value) {
    const amount = Number(value || 0);
    if (!amount) return 1;
    return amount > 0 ? 1 + (amount / 100) : 1 + (100 / Math.abs(amount));
  }

  function validAmericanOdds(value) {
    const amount = Number(value);
    return Number.isFinite(amount) && amount !== 0 && Math.abs(amount) >= 100 && Math.abs(amount) <= 100000;
  }

  function effectiveDecimal(value, commissionBps = 0) {
    const decimal = decimalOdds(value);
    const commission = numberBetween(commissionBps, 0, 2500, 0) / 10000;
    return 1 + ((decimal - 1) * (1 - commission));
  }

  function roundMoney(value) {
    return Math.round((Number(value || 0) + Number.EPSILON) * 100) / 100;
  }

  function calculateEditablePlan(session) {
    const oddsValues = session.odds.map(Number);
    if (!oddsValues.length || oddsValues.some((value) => !validAmericanOdds(value))) {
      return { error: "Enter valid American odds for every leg." };
    }
    const decimals = oddsValues.map((value, index) => effectiveDecimal(value, session.row.outcomes[index]?.commissionBps));
    let stakes = [];
    if (session.mode === "locked") {
      const anchorIndex = Math.min(Math.max(Number(session.anchorIndex || 0), 0), decimals.length - 1);
      const anchorStake = Number(session.anchorStake);
      if (!Number.isFinite(anchorStake) || anchorStake <= 0) return { error: "Enter a bet greater than zero for the locked side." };
      const targetPayout = anchorStake * decimals[anchorIndex];
      stakes = decimals.map((value, index) => index === anchorIndex ? roundMoney(anchorStake) : roundMoney(targetPayout / value));
    } else {
      const total = Number(session.total);
      if (!Number.isFinite(total) || total <= 0) return { error: "Enter a total bet greater than zero." };
      const weights = decimals.map((value) => 1 / value);
      const weightTotal = weights.reduce((sum, value) => sum + value, 0);
      stakes = weights.map((value) => roundMoney(total * value / weightTotal));
      const correction = roundMoney(total - stakes.reduce((sum, value) => sum + value, 0));
      stakes[stakes.length - 1] = roundMoney(stakes[stakes.length - 1] + correction);
    }
    const totalStake = roundMoney(stakes.reduce((sum, value) => sum + value, 0));
    const payouts = stakes.map((stake, index) => roundMoney(stake * decimals[index]));
    const minPayout = Math.min(...payouts);
    const profit = roundMoney(minPayout - totalStake);
    return {
      odds: oddsValues,
      decimals,
      stakes,
      payouts,
      totalStake,
      minPayout,
      profit,
      profitPercent: totalStake > 0 ? (profit / totalStake) * 100 : 0,
    };
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

  function sportLabel(row) {
    return String(row?.league || "").toUpperCase() === "EPL" ? "Soccer" : String(row?.league || "");
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

  function detailTeamLogo(row, team) {
    const logoUrl = teamLogoUrl(row, team);
    const leagueClass = String(row?.sportKey || "").toLowerCase().includes("wnba") ? " is-wnba" : "";
    return logoUrl
      ? `<span class="arb-detail-team-logo arb-team-logo-frame${leagueClass}" aria-hidden="true"><img src="${esc(logoUrl)}" alt="" loading="lazy" onerror="this.parentElement.hidden=true"></span>`
      : "";
  }

  function detailMatchup(row) {
    const away = String(row?.awayTeam || "").trim();
    const home = String(row?.homeTeam || "").trim();
    if (!away || !home) return esc(row?.eventTitle || "Event");
    return `<span class="arb-detail-team arb-detail-team-away">${detailTeamLogo(row, away)}<span>${esc(away)}</span></span> <span class="arb-detail-vs">vs</span> <span class="arb-detail-team arb-detail-team-home"><span>${esc(home)}</span>${detailTeamLogo(row, home)}</span>`;
  }

  function queueLeagueVisual(row) {
    const logoUrl = leagueLogoUrl(row?.sportKey, row?.league);
    return logoUrl
      ? `<img class="arb-queue-league-logo" src="${esc(logoUrl)}" alt="" aria-hidden="true" loading="lazy">`
      : "";
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
      stakeMode: state.stakeMode,
      lockedLegIndex: state.lockedLegIndex,
      minProfit: state.minProfit,
      maxAge: state.maxAge,
      commissionBps: state.commissionBps,
      distinctBooks: state.distinctBooks,
      books: [...state.selectedBooks],
      markets: [...state.selectedMarkets],
      sort: state.sort,
      requiredBook: state.requiredBook,
    };
    localStorage.setItem(storageKey, JSON.stringify(payload));
  }

  function persistHiddenState() {
    const snapshots = [...hiddenRows.values()].slice(-100);
    hiddenRows = new Map(snapshots.map((row) => [String(row.id), row]));
    localStorage.setItem(hiddenStorageKey, JSON.stringify([...hiddenIds]));
    localStorage.setItem(hiddenRowsStorageKey, JSON.stringify(snapshots));
  }

  function persistTrackedState() {
    localStorage.setItem(trackedStorageKey, JSON.stringify([...trackedIds]));
  }

  function findRow(id) {
    return state.rows.find((row) => String(row.id) === String(id)) || hiddenRows.get(String(id));
  }

  function currentSourceRows() {
    return state.view === "hidden"
      ? [...hiddenRows.values()]
      : state.rows.filter((row) => !hiddenIds.has(String(row.id)));
  }

  function bookLogo(row) {
    const logo = String(row.logoUrl || "");
    return logo ? `<img src="${esc(logo)}" alt="" loading="lazy">` : `<span class="arb-book-fallback"><i class="ph ph-buildings"></i></span>`;
  }

  function rowMatches(row) {
    const query = state.search.trim().toLowerCase();
    if (state.sport && row.sportKey !== state.sport) return false;
    if (state.requiredBook && !(row.booksUsed || []).includes(state.requiredBook)) return false;
    if (!query) return true;
    const blob = [
      row.eventTitle,
      row.league,
      sportLabel(row),
      row.marketLabel,
      row.marketContext,
      ...(row.outcomes || []).flatMap((leg) => [leg.selection, leg.bookName]),
    ].join(" ").toLowerCase();
    return blob.includes(query);
  }

  function visibleRows() {
    const rows = currentSourceRows().filter(rowMatches);
    if (state.sort === "profit-amount-desc") return rows.sort((left, right) => right.guaranteedProfit - left.guaranteedProfit);
    if (state.sort === "time-asc") return rows.sort((left, right) => new Date(left.commenceTime) - new Date(right.commenceTime));
    return rows.sort((left, right) => right.profitPercent - left.profitPercent);
  }

  function opportunityCard(row, index) {
    const start = queueDateParts(row.commenceTime);
    return `
      <article class="arb-opportunity ${row.id === state.selectedId ? "active" : ""} ${state.view === "hidden" ? "is-hidden-opportunity" : ""}" data-arb-id="${esc(row.id)}" role="button" tabindex="0" aria-label="${esc(`${percent(row.profitPercent)} ${row.executionStatus === "EXECUTABLE" ? "executable" : "theoretical"} arbitrage on ${row.eventTitle}`)}">
        <span class="arb-queue-rank">${index + 1}</span>
        <div class="arb-return-cell"><strong>${percent(row.profitPercent)}</strong><span>+${money(row.guaranteedProfit)}</span></div>
        <div class="arb-event-cell">
          <h3 title="${esc(row.eventTitle)}">${queueLeagueVisual(row)}<span>${esc(row.eventTitle)}</span></h3>
          <p>${esc(sportLabel(row))} · ${esc(row.marketLabel)} · ${row.outcomeCount}-way</p>
        </div>
        <time class="arb-queue-date" datetime="${esc(row.commenceTime)}"><span>${esc(start.day)}</span><small>${esc(start.time)}</small></time>
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
      elements.feed.innerHTML = state.view === "hidden"
        ? `<div class="arb-state"><i class="ph ph-eye-slash" aria-hidden="true"></i><strong>No hidden opportunities</strong><p>Use Track/Hide on a live opportunity, then choose Hide or Track and Hide to save it here.</p></div>`
        : `<div class="arb-state"><i class="ph ph-intersect-three" aria-hidden="true"></i><strong>No arbitrage matches these filters</strong><p>Try more sportsbooks, a lower minimum return, or a broader market selection. IconLabs never fabricates a missing opposing price.</p><button class="arb-secondary-button" type="button" data-arb-open-filters>Adjust filters</button></div>`;
      return;
    }
    elements.feed.innerHTML = (state.degraded ? `<div class="arb-detail-warning"><i class="ph ph-warning"></i><span>Showing the last verified arbitrage snapshot while the provider reconnects. Recheck every leg before betting.</span></div>` : "") + rows.map(opportunityCard).join("");
  }

  function updateSummary() {
    const liveRows = state.rows.filter((row) => !hiddenIds.has(String(row.id)));
    const top = [...liveRows].sort((left, right) => right.profitPercent - left.profitPercent)[0];
    const uniqueEvents = new Set(liveRows.map((row) => row.eventId)).size;
    document.getElementById("arb-kpi-opportunities").textContent = liveRows.length.toLocaleString();
    document.getElementById("arb-kpi-events").textContent = `${uniqueEvents} matched event${uniqueEvents === 1 ? "" : "s"}`;
    document.getElementById("arb-kpi-return").textContent = top ? percent(top.profitPercent) : "—";
    document.getElementById("arb-kpi-profit").textContent = top ? money(top.guaranteedProfit) : "—";
    document.getElementById("arb-kpi-stake").textContent = state.stakeMode === "first-leg"
      ? `With a ${money(state.stake, 0)} baseline bet`
      : `On a ${money(state.stake, 0)} total bet`;
    document.getElementById("arb-kpi-books").textContent = String(state.diagnostics.selectedBookCount ?? state.selectedBooks.size);
    elements.liveCount.textContent = String(liveRows.length);
    elements.hiddenCount.textContent = String(hiddenRows.size);
    document.querySelectorAll("[data-arb-view]").forEach((button) => {
      const active = button.dataset.arbView === state.view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    const visibleCount = visibleRows().length;
    elements.resultCopy.textContent = visibleCount
      ? `Showing 1–${visibleCount} of ${visibleCount} ${state.view === "hidden" ? "hidden" : "live"} opportunities`
      : `No ${state.view === "hidden" ? "hidden" : "live"} opportunities shown`;
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
    menu.innerHTML = options.map((option) => `<button type="button" role="option" aria-selected="${option.value === selected.value ? "true" : "false"}" data-arb-quick-option="${esc(kind)}" data-arb-quick-value="${esc(option.value)}">${quickOptionVisual(option)}<span>${esc(option.label)}</span><i class="ph ph-check" aria-hidden="true"></i></button>`).join("");
  }

  function populateQuickFilters() {
    const currentSport = state.sport;
    const sports = [...new Map(state.rows.map((row) => [row.sportKey, sportLabel(row)])).entries()].sort((left, right) => left[1].localeCompare(right[1]));
    state.sport = sports.some(([key]) => key === currentSport) ? currentSport : "";
    elements.sport.innerHTML = `<option value="">All sports</option>${sports.map(([key, label]) => `<option value="${esc(key)}">${esc(label)}</option>`).join("")}`;
    elements.sport.value = state.sport;
    renderQuickSelect("sport", [
      { value: "", label: "All sports", icon: "ph-trophy" },
      ...sports.map(([value, label]) => ({ value, label, logoUrl: leagueLogoUrl(value, label), icon: sportIcon({ sportKey: value, league: label }) })),
    ], state.sport);

    const sortOptions = [
      { value: "profit-desc", label: "Highest return", icon: "ph-sort-descending" },
      { value: "profit-amount-desc", label: "Highest profit", icon: "ph-currency-dollar" },
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
    document.querySelectorAll("[data-arb-quick-select]").forEach((container) => {
      if (container.dataset.arbQuickSelect === except) return;
      container.classList.remove("is-open");
      container.querySelector(".arb-quick-select-trigger")?.setAttribute("aria-expanded", "false");
      const menu = container.querySelector(".arb-quick-select-menu");
      if (menu) menu.hidden = true;
    });
  }

  function toggleQuickSelect(container) {
    const trigger = container.querySelector(".arb-quick-select-trigger");
    const menu = container.querySelector(".arb-quick-select-menu");
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
      if (state.liveActive) loadBoard(); else renderAll();
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

  function quoteRow(quote, bestKey, targetPayout) {
    const age = quote.quoteAgeSeconds == null ? "Age n/a" : `${Math.round(quote.quoteAgeSeconds)}s`;
    const projectedStake = Number(targetPayout || 0) / decimalOdds(quote.americanOdds);
    const projectedPayout = projectedStake * decimalOdds(quote.americanOdds);
    return `<div class="arb-quote-row ${quote.bookKey === bestKey ? "best" : ""}" draggable="true" data-line-shop-book="${esc(quote.bookKey)}">${bookLogo(quote)}<span title="${esc(quote.bookName)}">${esc(quote.bookName)}</span><small>${esc(age)}</small><b>${odds(quote.americanOdds)}</b><strong>${money(projectedStake)}</strong><strong>${money(projectedPayout)}</strong></div>`;
  }

  function quotePrice(quote) {
    const effectivePrice = Number(quote?.effectiveDecimalOdds);
    return Number.isFinite(effectivePrice) && effectivePrice > 0
      ? effectivePrice
      : decimalOdds(quote?.americanOdds);
  }

  function bestPriceFirst(quotes, selectedBookKey) {
    const ordered = window.IconLabsLineShopOrder?.sortRows(quotes || []) || quotes || [];
    return [...ordered]
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

  function renderDetail(row, openOnMobile = false) {
    if (!row) {
      elements.detailPlaceholder.hidden = false;
      elements.detailContent.hidden = true;
      return;
    }
    const executable = row.executionStatus === "EXECUTABLE";
    const hidden = hiddenIds.has(String(row.id));
    const previewOnly = String(row.eventId || "").startsWith("preview-");
    const betActionLabel = executable || previewOnly ? "BET" : "CHECK";
    const lockedIndex = Math.min(Math.max(Number(row.lockedOutcomeIndex ?? state.lockedLegIndex), 0), Math.max(0, row.outcomes.length - 1));
    const plan = (row.outcomes || []).map((leg, index) => `
      <article class="arb-plan-leg">
        <div class="arb-plan-outcome"><strong>${esc(leg.selection)}</strong><small>${row.stakeMode === "first-leg" ? (index === lockedIndex ? `<span class="arb-lock-status"><i class="ph ph-lock-key"></i>Baseline Amount · Locked</span>` : `<button class="arb-lock-leg" type="button" data-arb-lock-leg="${index}">Use as Baseline</button>`) : esc(row.marketLabel)}</small></div>
        <div class="arb-plan-book">${bookLogo(leg)}<span><strong>${esc(leg.bookName)}</strong>${leg.capacityKnown ? `<small>${money(leg.executionCapacity)} ${leg.capacityType === "TOP_PRICE_LIQUIDITY" ? "liquidity" : "limit"}</small>` : ""}</span></div>
        <b class="arb-plan-odds">${odds(leg.americanOdds)}</b>
        <div class="arb-plan-stake"><b>${money(leg.stake)}</b></div>
        <b class="arb-plan-payout">${money(leg.payout)}</b>
        ${leg.deepLink ? `<a class="arb-bet-link" href="${esc(leg.deepLink)}" target="_blank" rel="noopener noreferrer">${betActionLabel}<i class="ph ph-arrow-up-right"></i></a>` : `<span class="arb-bet-link disabled">${betActionLabel}</span>`}
      </article>`).join("");
    const payoutMax = Math.max(...row.outcomes.map((leg) => leg.payout), 1);
    const payouts = row.outcomes.map((leg) => `<div class="arb-payout-row"><span title="${esc(leg.selection)}">${esc(leg.selection)}</span><progress max="${payoutMax}" value="${Number(leg.payout)}"></progress><b>+${money(leg.profit)}</b></div>`).join("");
    const comparisons = (row.allQuotes || []).map((group) => {
      const selected = row.outcomes.find((leg) => leg.selection === group.selection);
      const quotes = bestPriceFirst(group.quotes || [], selected?.bookKey);
      const bestKey = quotes[0]?.bookKey;
      return `<section class="arb-comparison-group" data-line-shop-group><h4>${esc(group.selection)}</h4><div class="arb-quote-head"><span>Book</span><span>Age</span><span>Odds</span><span>Bet</span><span>Payout</span></div>${quotes.map((quote) => quoteRow(quote, bestKey, row.minPayout)).join("")}</section>`;
    }).join("");
    const warnings = (row.warnings || []).map((warning) => `<div class="arb-detail-warning"><i class="ph ph-warning"></i><span>${esc(warning)}</span></div>`).join("");
    const executionLabel = executable ? "Executable — all gates verified" : "Theoretical — verify limits, rules, and eligibility";
    elements.detailContent.innerHTML = `
      <header class="arb-detail-hero">
        <div class="arb-detail-main">
          <div class="arb-detail-hero-top"><div class="arb-detail-return"><strong>${percent(row.profitPercent)}</strong><span>${executable ? "executable return" : "theoretical return"}</span></div><button class="arb-icon-button arb-detail-close" type="button" data-arb-close-detail aria-label="Close execution plan"><i class="ph ph-x"></i></button></div>
          <h2 class="arb-detail-matchup" title="${esc(row.eventTitle)}" aria-label="${esc(row.eventTitle)}">${detailMatchup(row)}</h2>
          <p>${esc(sportLabel(row))} · ${esc(row.marketLabel)} · ${esc(dateTime(row.commenceTime))} · ${esc(executionLabel)}</p>
        </div>
        <dl class="arb-detail-facts"><div><dt>Market</dt><dd>${esc(row.marketLabel)}</dd></div><div><dt>Start time</dt><dd>${esc(dateTime(row.commenceTime))}</dd></div></dl>
        <div class="arb-detail-actions">${hidden ? `<button class="arb-primary-button" type="button" data-arb-restore><i class="ph ph-eye"></i>Restore</button>` : `<button class="arb-primary-button" type="button" data-arb-track-hide><i class="ph ph-eye-slash"></i>Track/Hide</button>`}<button class="arb-secondary-button" type="button" data-arb-recalculate><i class="ph ph-calculator"></i>Recalculate</button></div>
      </header>
      ${executable ? "" : `<div class="arb-detail-warning"><i class="ph ph-shield-warning"></i><span>This is a mathematical arbitrage match, not an executable claim. Verify every price, accepted stake, limit, settlement rule, and account-eligibility gate before placing either leg.</span></div>`}
      <section class="arb-detail-section arb-stake-plan-section"><header><h3>${executable ? "Stake Plan" : "Verification Plan"}</h3><span>${row.outcomeCount} outcomes · ${row.bookCount} books</span></header><div class="arb-plan-head"><span>Outcome</span><span>Book</span><span>Odds</span><span>Stake</span><span>Payout</span><span class="sr-only">Action</span></div><div class="arb-plan-list">${plan}</div></section>
      <section class="arb-detail-section arb-guaranteed-section"><header><h3>${executable ? "Guaranteed Outcome" : "Mathematical Payout"}</h3><span>${executable ? "after fee buffer &amp; cent rounding" : "only if every listed leg is accepted"}</span></header><div class="arb-guaranteed-layout"><div class="arb-profit-proof"><div><span>Total staked</span><strong>${money(row.totalStake)}</strong></div><div><span>Minimum payout</span><strong>${money(row.minPayout)}</strong></div><div><span>${executable ? "Locked profit" : "Modeled profit"}</span><strong class="positive">+${money(row.guaranteedProfit)}</strong></div></div><div class="arb-payout-list">${payouts}</div></div></section>
      <section class="arb-detail-section arb-odds-section"><header><h3>Odds Comparison</h3><span>best price first</span></header><div class="arb-comparison-grid">${comparisons}</div></section>
      <details class="arb-detail-section arb-calculation"><summary><h3>Calculation</h3><i class="ph ph-caret-down" aria-hidden="true"></i></summary><div class="arb-math-note"><i class="ph ph-function"></i><p>The inverse-probability total is <strong>${Number(row.impliedProbabilityPercent).toFixed(2)}%</strong>. Because it is below 100%, equalized stakes return more than the total amount deployed whichever outcome wins.<code>(1 ÷ ${Number(row.inverseProbabilitySum).toFixed(6)} − 1) × 100 = ${percent(row.theoreticalProfitPercent, 3)}</code></p></div>${warnings}<div class="arb-detail-warning"><i class="ph ph-clock-countdown"></i><span>Place every leg quickly and verify the displayed odds and accepted stake before submitting any wager.</span></div></details>`;
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
    const row = findRow(id);
    if (!row) return;
    state.selectedId = id;
    renderFeed();
    renderDetail(row, openOnMobile);
  }

  function renderAll() {
    updateSummary();
    populateQuickFilters();
    renderFeed();
    const shown = visibleRows();
    const selected = shown.find((row) => row.id === state.selectedId) || shown[0];
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
    params.set("min_profit", String(state.minProfit));
    params.set("max_quote_age", String(state.maxAge));
    params.set("commission_bps", String(state.commissionBps));
    params.set("distinct_books", state.distinctBooks ? "1" : "0");
    params.set("books", [...state.selectedBooks].join(","));
    if (state.requiredBook) params.set("required_book", state.requiredBook);
    params.set("markets", [...state.selectedMarkets].join(","));
    return `/api/arbitrage?${params.toString()}`;
  }

  async function loadBoard({ quiet = false } = {}) {
    if (state.loading || !state.liveActive) { renderAll(); return; }
    const url = endpoint();
    const cacheKey = pagePayloadCacheKey("arbitrage", url);
    if (!quiet && !state.rows.length) {
      const cached = readPagePayloadCache(cacheKey, 5 * 60 * 1000);
      if (cached) {
        state.rows = Array.isArray(cached.data) ? cached.data : [];
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
      if (!response.ok) throw new Error(payload.message || payload.error || "Unable to scan arbitrage markets.");
      writePagePayloadCache(cacheKey, payload);
      state.rows = Array.isArray(payload.data) ? payload.data : [];
      state.rows.forEach((row) => {
        if (hiddenIds.has(String(row.id))) hiddenRows.set(String(row.id), row);
      });
      persistHiddenState();
      state.diagnostics = payload.diagnostics || {};
      state.paused = Boolean(payload.paused);
      state.degraded = Boolean(payload.degraded || payload.stale);
      if (state.alerts && state.rows.length) notify(`${state.rows.length} arbitrage opportunit${state.rows.length === 1 ? "y" : "ies"} found.`);
      scheduleRefresh(Number(payload.refreshSeconds || 60));
    } catch (error) {
      if (!state.rows.length) state.diagnostics = {};
      state.degraded = state.rows.length > 0;
      state.error = state.rows.length ? "" : error.message;
      notify(state.rows.length ? "Recent arbitrage scan shown; live refresh delayed." : error.message, "error");
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

  function syncStakeModeUI() {
    const baselineMode = state.stakeMode === "first-leg";
    elements.stakeMode.value = state.stakeMode;
    elements.stake.setAttribute("aria-label", baselineMode ? "Baseline Amount" : "Total Bet");
    elements.stake.setAttribute("inputmode", "decimal");
    elements.dialogStakeLabel.textContent = baselineMode ? "Baseline Amount" : "Total Bet";
    elements.dialogStake.step = baselineMode ? "10" : "25";
    document.querySelectorAll('input[name="arb-stake-mode"]').forEach((input) => {
      input.checked = input.value === state.stakeMode;
    });
  }

  function syncDialog() {
    elements.dialogStake.value = String(state.stake);
    syncStakeModeUI();
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
    if (state.stakeMode !== defaults.stakeMode || state.lockedLegIndex !== defaults.lockedLegIndex) count += 1;
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
    if (state.requiredBook && !state.selectedBooks.has(state.requiredBook)) state.requiredBook = "";
    state.selectedMarkets = new Set(markets);
    state.stakeMode = document.querySelector('input[name="arb-stake-mode"]:checked')?.value === "first-leg" ? "first-leg" : "total";
    if (state.stakeMode === "total") state.lockedLegIndex = 0;
    state.stake = numberBetween(elements.dialogStake.value, 1, 10_000_000, state.stake);
    state.minProfit = numberBetween(elements.minProfit.value, 0, 50, state.minProfit);
    state.maxAge = numberBetween(elements.maxAge.value, 15, 1800, state.maxAge);
    state.commissionBps = numberBetween(elements.commission.value, 0, 2500, state.commissionBps);
    state.distinctBooks = elements.distinct.checked;
    state.sort = document.querySelector('input[name="arb-dialog-sort"]:checked')?.value || state.sort;
    elements.stake.value = stakeInputValue(state.stake);
    elements.sort.value = state.sort;
    syncStakeModeUI();
    saveSettings();
    updateFilterCount();
    return true;
  }

  function resetDialog() {
    state.stake = defaults.stake;
    state.stakeMode = defaults.stakeMode;
    state.lockedLegIndex = defaults.lockedLegIndex;
    state.minProfit = defaults.minProfit;
    state.maxAge = defaults.maxAge;
    state.commissionBps = defaults.commissionBps;
    state.distinctBooks = defaults.distinctBooks;
    state.selectedBooks = new Set(defaults.books);
    state.requiredBook = defaults.requiredBook;
    state.selectedMarkets = new Set(defaults.markets);
    state.sort = defaults.sort;
    syncDialog();
  }

  function actionSummary(row, kicker) {
    return `<div><span>${esc(kicker)}</span><h3>${esc(row.eventTitle)}</h3><p>${esc(sportLabel(row))} · ${esc(row.marketLabel)} · ${esc(dateTime(row.commenceTime))}</p></div><strong>${percent(row.profitPercent)}</strong>`;
  }

  function proofMarkup(plan) {
    const positive = plan.profit >= 0;
    return `<div><span>Total bet</span><strong>${money(plan.totalStake)}</strong></div><div><span>Minimum payout</span><strong>${money(plan.minPayout)}</strong></div><div><span>Modeled profit</span><strong class="${positive ? "positive" : "negative"}">${positive ? "+" : ""}${money(plan.profit)}</strong></div><div><span>Return</span><strong class="${positive ? "positive" : "negative"}">${percent(plan.profitPercent)}</strong></div>`;
  }

  function editorBook(leg) {
    return `<span class="arb-editor-book">${bookLogo(leg)}<span><strong>${esc(leg.bookName)}</strong><small>${esc(leg.bookKey)}</small></span></span>`;
  }

  function openTrackDialog(row) {
    if (!row || !elements.trackDialog) return;
    state.trackSession = {
      row,
      mode: "total",
      total: Number(row.totalStake || state.stake),
      odds: row.outcomes.map((leg) => Number(leg.americanOdds)),
    };
    elements.trackSummary.innerHTML = actionSummary(row, `${row.outcomeCount}-leg arbitrage`);
    elements.trackLegs.innerHTML = row.outcomes.map((leg, index) => `<div class="arb-leg-editor-row">
      <div class="arb-editor-outcome"><strong>${esc(leg.selection)}</strong><small>${esc(row.marketLabel)}</small></div>
      ${editorBook(leg)}
      <label class="arb-editor-odds"><span class="sr-only">Odds for ${esc(leg.selection)}</span><input type="text" inputmode="text" value="${odds(leg.americanOdds)}" data-arb-track-odds="${index}"></label>
      <strong class="arb-editor-value" data-arb-track-stake="${index}">${money(leg.stake)}</strong>
      <strong class="arb-editor-value positive" data-arb-track-payout="${index}">${money(leg.payout)}</strong>
    </div>`).join("");
    elements.trackError.textContent = "";
    refreshTrackPlan();
    elements.trackDialog.showModal();
  }

  function refreshTrackPlan() {
    const session = state.trackSession;
    if (!session) return null;
    const plan = calculateEditablePlan(session);
    session.plan = plan.error ? null : plan;
    elements.trackError.textContent = plan.error || "";
    if (plan.error) {
      elements.trackProof.innerHTML = "";
      return null;
    }
    plan.stakes.forEach((stake, index) => {
      const stakeNode = elements.trackLegs.querySelector(`[data-arb-track-stake="${index}"]`);
      const payoutNode = elements.trackLegs.querySelector(`[data-arb-track-payout="${index}"]`);
      if (stakeNode) stakeNode.textContent = money(stake);
      if (payoutNode) payoutNode.textContent = money(plan.payouts[index]);
    });
    elements.trackProof.innerHTML = proofMarkup(plan);
    return plan;
  }

  function hideOpportunity(row) {
    if (!row) return;
    const id = String(row.id);
    hiddenIds.add(id);
    hiddenRows.set(id, row);
    persistHiddenState();
    if (state.selectedId === id) state.selectedId = null;
    state.view = "live";
    renderAll();
    notify("Opportunity moved to Hidden.");
  }

  function restoreOpportunity(id) {
    const key = String(id || "");
    if (!key) return;
    hiddenIds.delete(key);
    hiddenRows.delete(key);
    persistHiddenState();
    state.view = "live";
    state.selectedId = state.rows.some((row) => String(row.id) === key) ? key : null;
    renderAll();
    notify("Opportunity restored to Live.");
  }

  function setView(nextView) {
    state.view = nextView === "hidden" ? "hidden" : "live";
    state.selectedId = null;
    closeMobileDetail();
    renderAll();
  }

  async function trackPlan({ hideAfter = false } = {}) {
    const session = state.trackSession;
    const plan = refreshTrackPlan();
    if (!session || !plan) return;
    const buttons = [...elements.trackDialog.querySelectorAll("[data-arb-track-action]")];
    buttons.forEach((button) => { button.disabled = true; });
    elements.trackError.textContent = "";
    try {
      for (let index = 0; index < session.row.outcomes.length; index += 1) {
        const row = session.row;
        const leg = row.outcomes[index];
        const response = await fetch("/api/arbitrage/personal-bets", {
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
            american_odds: plan.odds[index],
            stake: plan.stakes[index],
            fees: 0,
            sportsbook: leg.bookName,
            sportsbook_logo: leg.logoUrl || "",
            market_url: /^https:\/\//.test(String(leg.deepLink || "")) ? leg.deepLink : "",
            ev_percent: plan.profitPercent,
            tags: ["Arbitrage", `${row.outcomeCount}-way arbitrage`],
            confirm_duplicate: true,
            confirm_conflict: true,
          }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error || `Unable to track ${leg.selection}.`);
      }
      trackedIds.add(String(session.row.id));
      persistTrackedState();
      elements.trackDialog.close();
      if (hideAfter) hideOpportunity(session.row); else renderAll();
      notify(hideAfter ? "All legs tracked and the opportunity was hidden." : "All arbitrage legs were added to Bet Tracker.");
    } catch (error) {
      elements.trackError.textContent = error.message;
    } finally {
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  function openRecalculateDialog(row) {
    if (!row || !elements.recalculateDialog) return;
    const anchorIndex = Math.min(Math.max(Number(row.lockedOutcomeIndex ?? 0), 0), row.outcomes.length - 1);
    state.calculatorSession = {
      row,
      mode: row.stakeMode === "first-leg" ? "locked" : "total",
      total: Number(row.totalStake || state.stake),
      anchorIndex,
      anchorStake: Number(row.outcomes[anchorIndex]?.stake || 0),
      odds: row.outcomes.map((leg) => Number(leg.americanOdds)),
    };
    elements.recalculateSummary.innerHTML = actionSummary(row, "Live hedge workspace");
    elements.recalculateLegs.innerHTML = row.outcomes.map((leg, index) => `<div class="arb-leg-editor-row" data-arb-calculator-row="${index}">
      <div class="arb-editor-outcome"><strong>${esc(leg.selection)}</strong><small>${esc(row.marketLabel)}</small></div>
      ${editorBook(leg)}
      <label class="arb-editor-odds"><span class="sr-only">Odds for ${esc(leg.selection)}</span><input type="text" inputmode="text" value="${odds(leg.americanOdds)}" data-arb-calculator-odds="${index}"></label>
      <label class="arb-editor-money"><b>$</b><input type="number" min="0.01" step="0.01" inputmode="decimal" data-arb-calculator-stake="${index}" aria-label="Bet amount for ${esc(leg.selection)}"></label>
      <strong class="arb-editor-value positive" data-arb-calculator-payout="${index}">${money(leg.payout)}</strong>
      <label class="arb-editor-lock" title="Lock ${esc(leg.selection)} bet"><input type="radio" name="arb-calculator-lock" value="${index}" data-arb-calculator-lock="${index}"><i class="ph ph-lock-key" aria-hidden="true"></i><span class="sr-only">Lock ${esc(leg.selection)}</span></label>
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
      const row = elements.recalculateLegs.querySelector(`[data-arb-calculator-row="${index}"]`);
      const input = row?.querySelector(`[data-arb-calculator-stake="${index}"]`);
      const payout = row?.querySelector(`[data-arb-calculator-payout="${index}"]`);
      const lock = row?.querySelector(`[data-arb-calculator-lock="${index}"]`);
      const isAnchor = lockedMode && index === session.anchorIndex;
      row?.classList.toggle("is-locked", isAnchor);
      if (input) {
        input.readOnly = !isAnchor;
        if (document.activeElement !== input) input.value = stake.toFixed(2);
      }
      if (payout) payout.textContent = money(plan.payouts[index]);
      if (lock) lock.checked = isAnchor;
    });
    elements.recalculateProof.innerHTML = proofMarkup(plan);
    return plan;
  }

  function resetCalculator() {
    const row = state.calculatorSession?.row;
    if (!row) return;
    elements.recalculateDialog.close();
    openRecalculateDialog(row);
  }

  function bind() {
    elements.stake.value = stakeInputValue(state.stake);
    elements.sort.value = state.sort;
    syncStakeModeUI();
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
      if (event.target.closest("[data-arb-track-hide]")) openTrackDialog(findRow(state.selectedId));
      if (event.target.closest("[data-arb-restore]")) restoreOpportunity(state.selectedId);
      if (event.target.closest("[data-arb-recalculate]")) openRecalculateDialog(findRow(state.selectedId));
      const lockLeg = event.target.closest("[data-arb-lock-leg]");
      if (lockLeg) {
        state.stakeMode = "first-leg";
        state.lockedLegIndex = numberBetween(lockLeg.dataset.arbLockLeg, 0, 12, 0);
        syncStakeModeUI();
        saveSettings();
        loadBoard();
      }
    });
    window.IconLabsLineShopOrder?.bindDrag(elements.detailContent, ".arb-quote-row[data-line-shop-book]");
    window.addEventListener("iconlabs:line-shop-order", () => {
      renderDetail(state.rows.find((row) => row.id === state.selectedId), false);
    });
    elements.mobileScrim.addEventListener("click", closeMobileDetail);

    elements.search.addEventListener("input", () => { state.search = elements.search.value; renderFeed(); updateSummary(); });
    elements.sport.addEventListener("change", () => { state.sport = elements.sport.value; renderFeed(); updateSummary(); });
    elements.sort.addEventListener("change", () => { state.sort = elements.sort.value; saveSettings(); renderFeed(); });
    elements.stakeMode.addEventListener("change", () => {
      state.stakeMode = elements.stakeMode.value === "first-leg" ? "first-leg" : "total";
      if (state.stakeMode === "total") state.lockedLegIndex = 0;
      syncStakeModeUI();
      saveSettings();
      if (state.liveActive) loadBoard(); else renderAll();
    });
    elements.stake.addEventListener("input", () => {
      window.clearTimeout(state.stakeTimer);
      state.stakeTimer = window.setTimeout(() => {
        state.stake = stakeInputNumber(elements.stake.value, state.stake);
        elements.dialogStake.value = String(state.stake);
        saveSettings();
        if (state.liveActive) loadBoard();
      }, 350);
    });
    elements.stake.addEventListener("blur", () => {
      window.clearTimeout(state.stakeTimer);
      const previousStake = state.stake;
      state.stake = stakeInputNumber(elements.stake.value, state.stake);
      elements.stake.value = stakeInputValue(state.stake);
      elements.dialogStake.value = String(state.stake);
      if (state.stake !== previousStake) {
        saveSettings();
        if (state.liveActive) loadBoard();
      }
    });
    elements.refresh.addEventListener("click", () => { if (!state.liveActive) startScanner(); else loadBoard(); });
    elements.pause.addEventListener("click", togglePause);
    elements.alerts.addEventListener("click", () => {
      state.alerts = !state.alerts;
      elements.alerts.setAttribute("aria-pressed", state.alerts ? "true" : "false");
      elements.alerts.innerHTML = `<i class="ph ${state.alerts ? "ph-bell-ringing" : "ph-bell"}" aria-hidden="true"></i>`;
      notify(state.alerts ? "Opportunity alerts enabled for this page." : "Opportunity alerts muted.");
    });
    document.querySelector(".arb-mode-tabs")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-arb-view]");
      if (button) setView(button.dataset.arbView);
    });

    document.getElementById("arb-track-close")?.addEventListener("click", () => elements.trackDialog.close());
    document.getElementById("arb-track-form")?.addEventListener("submit", (event) => event.preventDefault());
    elements.trackDialog?.addEventListener("click", (event) => { if (event.target === elements.trackDialog) elements.trackDialog.close(); });
    elements.trackDialog?.addEventListener("input", (event) => {
      const input = event.target.closest("[data-arb-track-odds]");
      if (!input || !state.trackSession) return;
      state.trackSession.odds[Number(input.dataset.arbTrackOdds)] = input.value;
      refreshTrackPlan();
    });
    elements.trackDialog?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-arb-track-action]");
      if (!button || !state.trackSession) return;
      const action = button.dataset.arbTrackAction;
      if (action === "hide") {
        const row = state.trackSession.row;
        elements.trackDialog.close();
        hideOpportunity(row);
      } else {
        trackPlan({ hideAfter: action === "track-hide" });
      }
    });

    document.getElementById("arb-recalculate-close")?.addEventListener("click", () => elements.recalculateDialog.close());
    document.getElementById("arb-recalculate-form")?.addEventListener("submit", (event) => event.preventDefault());
    document.getElementById("arb-recalculate-done")?.addEventListener("click", () => elements.recalculateDialog.close());
    document.getElementById("arb-recalculate-reset")?.addEventListener("click", resetCalculator);
    elements.recalculateDialog?.addEventListener("click", (event) => { if (event.target === elements.recalculateDialog) elements.recalculateDialog.close(); });
    elements.recalculateMode?.addEventListener("change", () => {
      const session = state.calculatorSession;
      if (!session) return;
      const currentPlan = session.plan;
      session.mode = elements.recalculateMode.value === "locked" ? "locked" : "total";
      if (session.mode === "locked") session.anchorStake = currentPlan?.stakes[session.anchorIndex] || session.anchorStake;
      else session.total = currentPlan?.totalStake || session.total;
      refreshCalculatorPlan();
    });
    elements.recalculateTotal?.addEventListener("input", () => {
      if (!state.calculatorSession || state.calculatorSession.mode !== "total") return;
      state.calculatorSession.total = elements.recalculateTotal.value;
      refreshCalculatorPlan();
    });
    elements.recalculateLegs?.addEventListener("input", (event) => {
      const session = state.calculatorSession;
      if (!session) return;
      const oddsInput = event.target.closest("[data-arb-calculator-odds]");
      if (oddsInput) {
        session.odds[Number(oddsInput.dataset.arbCalculatorOdds)] = oddsInput.value;
        refreshCalculatorPlan();
        return;
      }
      const stakeInput = event.target.closest("[data-arb-calculator-stake]");
      if (stakeInput && session.mode === "locked") {
        const index = Number(stakeInput.dataset.arbCalculatorStake);
        if (index !== session.anchorIndex) return;
        session.anchorStake = stakeInput.value;
        refreshCalculatorPlan();
      }
    });
    elements.recalculateLegs?.addEventListener("change", (event) => {
      const lock = event.target.closest("[data-arb-calculator-lock]");
      const session = state.calculatorSession;
      if (!lock || !session) return;
      const index = Number(lock.dataset.arbCalculatorLock);
      session.mode = "locked";
      session.anchorIndex = index;
      session.anchorStake = session.plan?.stakes[index] || session.row.outcomes[index]?.stake || 0;
      refreshCalculatorPlan();
      elements.recalculateLegs.querySelector(`[data-arb-calculator-stake="${index}"]`)?.focus();
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
      if (state.requiredBook && !state.selectedBooks.has(state.requiredBook)) state.requiredBook = "";
      document.getElementById("arb-book-filter-count").textContent = `${state.selectedBooks.size}/${eligibleBooks.length}`;
    });
    document.querySelectorAll('input[name="arb-stake-mode"]').forEach((input) => input.addEventListener("change", () => {
      const baselineMode = input.value === "first-leg";
      elements.dialogStakeLabel.textContent = baselineMode ? "Baseline Amount" : "Total Bet";
      elements.dialogStake.step = baselineMode ? "10" : "25";
    }));
    document.querySelector(".arb-board-actions")?.addEventListener("click", (event) => {
      const option = event.target.closest("[data-arb-quick-option]");
      if (option) {
        chooseQuickOption(option.dataset.arbQuickOption, option.dataset.arbQuickValue || "");
        return;
      }
      const container = event.target.closest("[data-arb-quick-select]");
      if (container && event.target.closest(".arb-quick-select-trigger")) toggleQuickSelect(container);
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
      if (event.key === "Escape") {
        closeQuickSelects();
        if (elements.detail.classList.contains("mobile-open")) closeMobileDetail();
      }
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
    document.addEventListener("click", (event) => {
      if (!event.target.closest("[data-arb-quick-select]")) closeQuickSelects();
    });
  }

  bind();
  loadBoard();
})();
