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
  };

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
    market: "",
    maxHours: 48,
    mode: "all",
    bookGroup: "all",
    alerts: false,
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
    selectedBooks: new Set(Array.isArray(stored.books) && stored.books.length ? stored.books.filter((key) => eligibleBooks.some((book) => book.key === key)) : defaults.books),
    selectedMarkets: new Set(Array.isArray(stored.markets) && stored.markets.length ? stored.markets : defaults.markets),
    sort: ["hold-asc", "retained-desc", "middle-desc", "time-asc"].includes(stored.sort) ? stored.sort : defaults.sort,
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
    market: document.getElementById("lh-market-filter"),
    time: document.getElementById("lh-time-filter"),
    sort: document.getElementById("lh-sort"),
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
    if (Number(row.holdPercent) < -0.005) return "is-arb";
    if (Math.abs(Number(row.holdPercent)) <= 0.05) return "is-zero";
    return "is-cost";
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

  function bookLogo(row) {
    const logo = String(row.logoUrl || "");
    return logo ? `<img src="${esc(logo)}" alt="" loading="lazy">` : `<span class="arb-book-fallback"><i class="ph ph-buildings"></i></span>`;
  }

  function rowMatches(row) {
    const query = state.search.trim().toLowerCase();
    if (state.mode !== "all" && row.pairKind !== state.mode) return false;
    if (state.sport && row.sportKey !== state.sport) return false;
    if (state.market && row.marketKey !== state.market) return false;
    if (state.maxHours !== null) {
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
    const rows = state.rows.filter(rowMatches);
    if (state.sort === "retained-desc") return rows.sort((left, right) => right.retainedPercent - left.retainedPercent);
    if (state.sort === "middle-desc") return rows.sort((left, right) => Number(right.middleProfit || -Infinity) - Number(left.middleProfit || -Infinity));
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
          <h3 title="${esc(row.eventTitle)}"><i class="ph ${sportIcon(row)}" aria-hidden="true"></i><span>${esc(row.eventTitle)}</span></h3>
          <p>${esc(row.league)} · ${esc(row.marketLabel)} · ${row.pairKind === "middle" ? "middle" : `${row.outcomeCount}-way`}</p>
        </div>
        <time class="arb-queue-date" datetime="${esc(row.commenceTime)}"><span>${esc(start.day)}</span><small>${esc(start.time)}</small></time>
      </article>`;
  }

  function renderFeed() {
    if (state.loading) {
      elements.feed.innerHTML = `<div class="arb-state arb-loading" role="status"><span class="arb-spinner" aria-hidden="true"></span><strong>Pairing opposing prices</strong><p>Calculating hold, balancing stakes, and checking attainable middle outcomes.</p></div>`;
      return;
    }
    if (state.error) {
      elements.feed.innerHTML = `<div class="arb-state"><i class="ph ph-warning-circle" aria-hidden="true"></i><strong>Low Hold scan unavailable</strong><p>${esc(state.error)}</p><button class="arb-secondary-button" type="button" data-lh-retry>Try again</button></div>`;
      return;
    }
    if (!state.liveActive) {
      elements.feed.innerHTML = `<div class="arb-state"><i class="ph ph-pause-circle" aria-hidden="true"></i><strong>Low Hold scanner is paused</strong><p>Start the feed when you need it. IconLabs requests current prices only on demand to protect provider credits.</p><button class="arb-primary-button" type="button" data-lh-start><i class="ph ph-play"></i>Start scanner</button></div>`;
      return;
    }
    const rows = visibleRows();
    if (!rows.length) {
      elements.feed.innerHTML = `<div class="arb-state"><i class="ph ph-percent" aria-hidden="true"></i><strong>No Low Hold pairs match these filters</strong><p>Try more sportsbooks, a higher maximum hold, a wider odds range, or both pair types.</p><button class="arb-secondary-button" type="button" data-lh-open-filters>Adjust filters</button></div>`;
      return;
    }
    const rendered = rows.slice(0, state.visibleLimit);
    const remaining = rows.length - rendered.length;
    elements.feed.innerHTML = (state.degraded ? `<div class="arb-detail-warning"><i class="ph ph-warning"></i><span>Showing the last verified Low Hold snapshot while the provider reconnects. Recheck every price and accepted stake.</span></div>` : "") + rendered.map(opportunityCard).join("") + (remaining > 0
      ? `<button class="arb-secondary-button lh-show-more" type="button" data-lh-show-more>Show 100 more <small>${remaining.toLocaleString()} remaining</small></button>`
      : "");
  }

  function updateSummary() {
    const rows = visibleRows();
    const best = [...state.rows].sort((left, right) => left.holdPercent - right.holdPercent)[0];
    const executableCount = state.rows.filter(row => row.executionStatus === "EXECUTABLE").length;
    document.getElementById("lh-kpi-hold").textContent = best ? percent(best.holdPercent) : "—";
    document.getElementById("lh-kpi-retained").textContent = best ? percent(best.retainedPercent, 1) : "—";
    document.getElementById("lh-kpi-opportunities").textContent = String(state.rows.length);
    document.getElementById("lh-kpi-books").textContent = String(state.selectedBooks.size);
    document.getElementById("lh-mode-count").textContent = String(state.rows.length);
    const visibleCount = Math.min(rows.length, state.visibleLimit);
    elements.resultCopy.textContent = visibleCount
      ? `Showing 1–${visibleCount} of ${rows.length} opportunities · ${executableCount} executable`
      : "No opportunities shown";
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

  function quoteRow(quote, bestKey, targetPayout) {
    const age = quote.quoteAgeSeconds == null ? "Age n/a" : `${Math.round(quote.quoteAgeSeconds)}s`;
    const projectedStake = Number(targetPayout || 0) / decimalOdds(quote.americanOdds);
    const projectedPayout = projectedStake * decimalOdds(quote.americanOdds);
    return `<div class="arb-quote-row ${quote.bookKey === bestKey ? "best" : ""}" draggable="true" data-line-shop-book="${esc(quote.bookKey)}">${bookLogo(quote)}<span title="${esc(quote.bookName)}">${esc(quote.bookName)}</span><small>${esc(age)}</small><b>${odds(quote.americanOdds)}</b><strong>${money(projectedStake)}</strong><strong>${money(projectedPayout)}</strong></div>`;
  }

  function scenarioCard(label, profit, detail, middle = false) {
    const amount = Number(profit || 0);
    return `<article class="lh-scenario-card ${middle ? "middle" : ""}"><span>${esc(label)}</span><strong class="${amount >= 0 ? "positive" : "negative"}">${signedMoney(amount)}</strong><small>${esc(detail)}</small></article>`;
  }

  function renderDetail(row, openOnMobile = false) {
    if (!row) {
      elements.detailPlaceholder.hidden = false;
      elements.detailContent.hidden = true;
      return;
    }
    const lockedIndex = Number.isInteger(row.lockedOutcomeIndex) ? row.lockedOutcomeIndex : 0;
    const executable = row.executionStatus === "EXECUTABLE";
    const plan = (row.outcomes || []).map((leg, index) => `
      <article class="arb-plan-leg">
        <div class="arb-plan-outcome"><strong>${esc(leg.selection)}</strong><small>${row.stakeMode === "first-leg" ? (index === lockedIndex ? `<span class="lh-lock-status"><i class="ph ph-lock-key"></i>Bet 1 · Locked</span>` : `<button class="lh-lock-leg" type="button" data-lh-lock-leg="${index}">Use as Bet 1</button>`) : esc(row.marketLabel)}</small></div>
        <div class="arb-plan-book">${bookLogo(leg)}<span><strong>${esc(leg.bookName)}</strong>${leg.capacityKnown ? `<small>${money(leg.executionCapacity)} ${leg.capacityType === "TOP_PRICE_LIQUIDITY" ? "liquidity" : "limit"}</small>` : ""}</span></div>
        <b class="arb-plan-odds">${odds(leg.americanOdds)}</b>
        <div class="arb-plan-stake"><b>${money(leg.stake)}</b></div>
        <b class="arb-plan-payout">${money(leg.payout)}</b>
        ${leg.deepLink ? `<a class="arb-bet-link" href="${esc(leg.deepLink)}" target="_blank" rel="noopener noreferrer">${executable ? "BET" : "CHECK"}<i class="ph ph-arrow-up-right"></i></a>` : `<span class="arb-bet-link disabled">${executable ? "BET" : "CHECK"}</span>`}
      </article>`).join("");
    const payoutMax = Math.max(...row.outcomes.map((leg) => Number(leg.payout || 0)), 1);
    const payouts = row.outcomes.map((leg) => `<div class="arb-payout-row"><span title="${esc(leg.selection)}">${esc(leg.selection)}</span><progress max="${payoutMax}" value="${Number(leg.payout)}"></progress><b class="${Number(leg.profit) >= 0 ? "positive" : "lh-negative"}">${signedMoney(leg.profit)}</b></div>`).join("");
    const outsideCards = (row.outcomes || []).slice(0, 2).map((leg) => scenarioCard(`${leg.selection} hits`, leg.profit, `${leg.bookName} wins`));
    if (row.middleScenario) {
      outsideCards.splice(1, 0, scenarioCard(row.middleScenario.label, row.middleProfit, `Result ${row.middleScenario.result} · ${percent(row.middleReturnPercent)} return`, true));
    }
    const comparisons = (row.allQuotes || []).map((group) => {
      const selected = row.outcomes.find((leg) => leg.selection === group.selection);
      const quotes = window.IconLabsLineShopOrder?.sortRows(group.quotes || []) || group.quotes || [];
      return `<section class="arb-comparison-group" data-line-shop-group><h4>${esc(group.selection)}</h4><div class="arb-quote-head"><span>Book</span><span>Age</span><span>Odds</span><span>Stake</span><span>Payout</span></div>${quotes.map((quote) => quoteRow(quote, selected?.bookKey, row.minPayout)).join("")}</section>`;
    }).join("");
    const warnings = (row.warnings || []).map((warning) => `<div class="arb-detail-warning"><i class="ph ph-warning"></i><span>${esc(warning)}</span></div>`).join("");
    const netLabel = Number(row.outsideNet) >= 0
      ? row.executionStatus === "EXECUTABLE" ? "Verified outside profit" : "Modeled outside profit"
      : "Worst-case cost";
    const context = row.marketContext ? esc(row.marketContext) : esc(row.marketLabel);
    const executionLabel = executable ? "Executable — all gates verified" : "Theoretical — verify limits, rules, and eligibility";
    elements.detailContent.innerHTML = `
      <header class="arb-detail-hero">
        <div class="arb-detail-main">
          <div class="arb-detail-hero-top"><div class="arb-detail-return lh-detail-hold ${holdTone(row)}"><strong>${percent(row.holdPercent)}</strong><span>hold</span></div><button class="arb-icon-button arb-detail-close" type="button" data-lh-close-detail aria-label="Close bet plan"><i class="ph ph-x"></i></button></div>
          <h2>${esc(row.eventTitle)}</h2>
          <p>${esc(row.league)} · ${esc(row.marketLabel)} · ${esc(executionLabel)}</p>
        </div>
        <dl class="arb-detail-facts"><div><dt>Market</dt><dd>${context}</dd></div><div><dt>Start time</dt><dd>${esc(dateTime(row.commenceTime))}</dd></div></dl>
        <div class="arb-detail-actions"><button class="arb-primary-button" type="button" data-lh-copy-plan><i class="ph ph-copy"></i>${executable ? "Copy bet plan" : "Copy verification checklist"}</button><button class="arb-secondary-button" type="button" data-lh-recalculate><i class="ph ph-calculator"></i>Recalculate</button></div>
      </header>
      ${executable ? "" : `<div class="arb-detail-warning"><i class="ph ph-shield-warning"></i><span>This is a mathematical low-hold pair, not an executable claim. One or more capacity, settlement, or account-eligibility gates are unverified.</span></div>`}
      <section class="arb-detail-section arb-stake-plan-section"><header><h3>${executable ? "Bet Plan" : "Verification Plan"}</h3><span>${row.outcomeCount} outcomes · ${row.bookCount} books</span></header><div class="arb-plan-head"><span>Outcome</span><span>Book</span><span>Odds</span><span>Stake</span><span>Payout</span><span class="sr-only">Action</span></div><div class="arb-plan-list">${plan}</div></section>
      <section class="arb-detail-section arb-guaranteed-section"><header><h3>Balanced Outcome</h3><span>after fees &amp; cent rounding</span></header><div class="arb-guaranteed-layout"><div class="arb-profit-proof"><div><span>Total staked</span><strong>${money(row.totalStake)}</strong></div><div><span>Capital retained</span><strong>${percent(row.retainedPercent, 1)}</strong></div><div><span>${esc(netLabel)}</span><strong class="${Number(row.outsideNet) >= 0 ? "positive" : ""}">${signedMoney(row.outsideNet)}</strong></div></div><div class="arb-payout-list">${payouts}</div></div></section>
      <section class="arb-detail-section arb-odds-section"><header><h3>Odds Comparison</h3><span>best price highlighted</span></header><div class="arb-comparison-grid">${comparisons}</div></section>
      <details class="arb-detail-section arb-calculation"><summary><h3>Calculation Details</h3><i class="ph ph-caret-down" aria-hidden="true"></i></summary><div class="lh-scenario-grid">${outsideCards.join("")}</div><div class="arb-math-note"><i class="ph ph-function"></i><p>The opposing implied probabilities total <strong>${Number(row.impliedProbabilityPercent).toFixed(3)}%</strong>, producing a <strong>${percent(row.holdPercent, 3)}</strong> hold before cent-level payout balancing.<code>(${Number(row.inverseProbabilitySum).toFixed(6)} − 1) × 100 = ${percent(row.holdPercent, 3)}</code></p></div>${row.stakeMode === "first-leg" ? `<div class="lh-sizing-note"><i class="ph ph-lock-key"></i><span><strong>${money(row.lockedStake)}</strong> stays fixed on Bet 1; every hedge is rounded to the closest equal payout.</span></div>` : ""}${warnings}${state.lineWarning ? `<div class="arb-detail-warning"><i class="ph ph-clock-countdown"></i><span>Confirm both displayed prices and accepted stakes before submitting either leg.</span></div>` : ""}</details>`;
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
    const selected = state.rows.find((row) => row.id === state.selectedId) || visibleRows()[0] || state.rows[0];
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
      if (!response.ok) throw new Error(payload.message || payload.error || "Unable to scan Low Hold markets.");
      writePagePayloadCache(cacheKey, payload);
      state.rows = Array.isArray(payload.data) ? payload.data : [];
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
    elements.savedList.innerHTML = filters.map((filter, index) => `<article class="lh-saved-filter"><i class="ph ph-bookmark-simple"></i><div><strong>${esc(filter.name)}</strong><small>${filter.stakeMode === "total" ? "Total bankroll" : "Bet 1 locked"} · ${Number(filter.maxHold).toFixed(1)}% max · ${(filter.books || []).length} books</small></div><button type="button" data-lh-load-filter="${index}">Load</button><button type="button" data-lh-delete-filter="${index}" aria-label="Delete ${esc(filter.name)}"><i class="ph ph-trash"></i></button></article>`).join("");
  }

  function syncStakeModeUI() {
    const firstLegMode = state.stakeMode === "first-leg";
    elements.stakeMode.value = state.stakeMode;
    elements.dialogStakeLabel.textContent = firstLegMode ? "Bet 1 stake" : "Total stake";
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
    state.sort = filter.sort || defaults.sort;
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

  function copyPlan() {
    const row = state.rows.find((item) => item.id === state.selectedId);
    if (!row) return;
    const executable = row.executionStatus === "EXECUTABLE";
    const lines = [
      executable ? "EXECUTABLE — RECHECK PRICES BEFORE SUBMISSION" : "THEORETICAL — VERIFY PRICES, LIMITS, SETTLEMENT, AND ELIGIBILITY BEFORE BETTING",
      `${row.eventTitle} · ${row.marketLabel}${row.marketContext ? ` · ${row.marketContext}` : ""}`,
      `Hold ${percent(row.holdPercent, 3)} · ${row.stakeMode === "first-leg" ? `Bet 1 ${money(row.lockedStake)} · ` : ""}Total ${money(row.totalStake)} · Outside ${signedMoney(row.outsideNet)}`,
      ...(row.outcomes || []).map((leg, index) => `${row.stakeMode === "first-leg" ? (index === row.lockedOutcomeIndex ? "Bet 1" : "Hedge") : "Stake"} · ${leg.selection}: ${money(leg.stake)} at ${odds(leg.americanOdds)} on ${leg.bookName}`),
    ];
    if (row.middleScenario) lines.push(`${row.middleScenario.label} at ${row.middleScenario.result}: ${signedMoney(row.middleProfit)}`);
    navigator.clipboard?.writeText(lines.join("\n")).then(() => notify(executable ? "Bet plan copied." : "Verification checklist copied.")).catch(() => notify("Copy is unavailable in this browser.", "error"));
  }

  function openFilter(tab = "sportsbooks") {
    syncDialog();
    document.querySelector(`[data-lh-filter-tab="${tab}"]`)?.click();
    elements.filterDialog.showModal();
  }

  document.querySelectorAll("[data-lh-mode]").forEach((button) => button.addEventListener("click", () => {
    state.mode = button.dataset.lhMode;
    document.querySelectorAll("[data-lh-mode]").forEach((item) => {
      const active = item === button;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", active ? "true" : "false");
    });
    renderAll();
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
    if (event.target.closest("[data-lh-copy-plan]")) copyPlan();
    if (event.target.closest("[data-lh-recalculate]")) openFilter("hold");
    const lockLeg = event.target.closest("[data-lh-lock-leg]");
    if (lockLeg) {
      state.stakeMode = "first-leg";
      state.lockedLegIndex = numberBetween(lockLeg.dataset.lhLockLeg, 0, 12, 0);
      syncStakeModeUI();
      saveSettings();
      notify("Bet 1 changed. Recalculating the hedge.");
      loadBoard({ quiet: true });
    }
  });
  window.IconLabsLineShopOrder?.bindDrag(elements.detailContent, ".arb-quote-row[data-line-shop-book]");
  window.addEventListener("iconlabs:line-shop-order", () => {
    renderDetail(state.rows.find((row) => row.id === state.selectedId), false);
  });
  elements.savedList.addEventListener("click", (event) => {
    const load = event.target.closest("[data-lh-load-filter]");
    const remove = event.target.closest("[data-lh-delete-filter]");
    if (load) loadSaved(Number(load.dataset.lhLoadFilter));
    if (remove) deleteSaved(Number(remove.dataset.lhDeleteFilter));
  });

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
  elements.market.addEventListener("change", () => { state.market = elements.market.value; state.visibleLimit = 100; renderAll(); });
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
    elements.dialogStakeLabel.textContent = input.value === "first-leg" ? "Bet 1 stake" : "Total stake";
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
    if (event.key === "Escape") closeMobileDetail();
  });

  elements.stake.value = state.stake;
  syncStakeModeUI();
  elements.sort.value = state.sort;
  updateFilterBadge();
  syncDialog();
  loadBoard();
})();
