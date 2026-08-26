(() => {
  "use strict";

  const state = {
    payload: null,
    signals: [],
    visible: [],
    selectedId: null,
    sport: "",
    search: "",
    controlling: false,
    filters: { minimumLiquidity: 0, flow: "", marketType: "" },
    sortDescending: true,
    detailVisible: true,
    preview: new URLSearchParams(window.location.search).get("preview") === "1",
    placeholderSignals: [],
  };
  const $ = id => document.getElementById(id);

  const escapeHtml = value => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  function money(value, compact = true) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "N/A";
    return new Intl.NumberFormat("en-US", {
      style: "currency", currency: "USD",
      notation: compact && Math.abs(number) >= 1000 ? "compact" : "standard",
      maximumFractionDigits: compact ? 1 : 0,
    }).format(number);
  }

  function liquidityMoney(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "N/A";
    const absolute = Math.abs(number);
    const sign = number < 0 ? "-" : "";
    if (absolute >= 1000000) return `${sign}$${(absolute / 1000000).toFixed(1)}M`;
    if (absolute >= 1000) return `${sign}$${(absolute / 1000).toFixed(1)}K`;
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(number);
  }

  function odds(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    return number > 0 ? `+${Math.round(number)}` : `${Math.round(number)}`;
  }

  function pct(value, signed = false) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "0.0%";
    const formatted = `${(number * 100).toFixed(1)}%`;
    return signed && number > 0 ? `+${formatted}` : formatted;
  }

  function timeLabel(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "TBA";
    return new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      weekday: "short", hour: "numeric", minute: "2-digit",
    }).format(date);
  }

  function ageLabel(value) {
    if (!value) return "No live request has started";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Waiting for first snapshot";
    const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
    return seconds < 2 ? "Updated now" : `Updated ${seconds}s ago`;
  }

  function logo(row, fallback = "PX") {
    const localLogos = {
      pinnacle: "/static/assets/providers/pinnacle.png",
      betonline: "/static/assets/sportsbooks/betonline.png",
      betonlineag: "/static/assets/sportsbooks/betonline.png",
      fanduel: "/static/assets/sportsbooks/fanduel.png",
      draftkings: "/static/assets/sportsbooks/draftkings.png",
      betmgm: "/static/assets/sportsbooks/betmgm.png",
      caesars: "/static/assets/sportsbooks/caesars.png",
      novig: "/static/assets/providers/novig.png",
      prophetx: "/static/assets/providers/prophetx.ico",
    };
    const url = localLogos[providerKey(row)] || row?.logoUrl || row?.providerLogo;
    return url
      ? `<img src="${escapeHtml(url)}" alt="" loading="lazy">`
      : `<span>${escapeHtml(fallback)}</span>`;
  }

  function pinnacleLimit(signal) {
    const row = (signal.comparisonLines || []).find(item =>
      String(item.providerKey || item.providerName || "").toLowerCase().includes("pinnacle")
    );
    const value = row?.marketLimit ?? row?.betLimit ?? row?.availableLiquidity;
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : null;
  }

  function pinnacleLimitLabel(signal) {
    const value = pinnacleLimit(signal);
    return value == null ? "P Limit unavailable" : `${money(value, false)} P Limit`;
  }

  function marketSides(signal) {
    const outcomes = Array.isArray(signal.outcomes) ? signal.outcomes : [];
    const selected = outcomes.find(row => row.name === signal.selection) || outcomes[0] || {};
    const opposite = outcomes.find(row => row !== selected) || {};
    return {
      selected: selected.name || signal.selection || "Selection",
      opposite: opposite.name || "Opposing side",
      oppositeOdds: opposite.americanOdds,
      oppositeLiquidity: opposite.liquidity,
    };
  }

  const MARKET_INTELLIGENCE_PROVIDERS = new Set([
    "novig", "prophetx", "4cx", "fourcx", "polymarket", "kalshi",
  ]);
  const DEPTH_PROVIDER_ORDER = ["novig", "prophetx"];

  function providerKey(row) {
    const raw = row?.providerKey || row?.providerName || row?.provider || "";
    const normalized = String(raw).toLowerCase().replace(/[^a-z0-9]/g, "");
    return normalized === "fourcx" ? "4cx" : normalized;
  }

  function isMarketIntelligenceProvider(row) {
    return MARKET_INTELLIGENCE_PROVIDERS.has(providerKey(row));
  }

  function bestQuote(rows) {
    return (rows || []).reduce((best, row) => {
      const price = Number(row?.americanOdds);
      return Number.isFinite(price) && (!best || price > Number(best.americanOdds)) ? row : best;
    }, null);
  }

  function primaryQuote(signal) {
    const rows = Array.isArray(signal.comparisonLines) ? signal.comparisonLines : [];
    return bestQuote(rows.filter(row => !isMarketIntelligenceProvider(row)));
  }

  function depthQuotes(signal) {
    const rows = Array.isArray(signal.comparisonLines) ? signal.comparisonLines : [];
    const byProvider = new Map(rows.map(row => [providerKey(row), row]));
    const quotes = DEPTH_PROVIDER_ORDER.map(key => ({ key, row: byProvider.get(key) || null }));
    const best = bestQuote(quotes.map(item => item.row).filter(Boolean));
    return quotes.map(item => ({ ...item, isBest: item.row === best }));
  }

  function combinedDepthLiquidity(signal) {
    const values = depthQuotes(signal)
      .map(item => Number(item.row?.availableLiquidity))
      .filter(value => Number.isFinite(value) && value >= 0);
    return values.length ? values.reduce((total, value) => total + value, 0) : null;
  }

  function sportsbookAction(quote, fallbackOdds) {
    if (!quote) {
      return `<span class="sharp-sportsbook-action unavailable"><small>Sportsbook</small><b>Awaiting line</b></span>`;
    }
    return `<a class="sharp-sportsbook-action" href="${escapeHtml(quote.deepLink || "#")}" ${quote.deepLink ? 'target="_blank" rel="noopener noreferrer"' : 'aria-disabled="true"'}>${logo(quote, String(quote.providerName || "?").slice(0, 2))}<span><small>${escapeHtml(quote.providerName || "Sportsbook")}</small><b>${escapeHtml(odds(quote.americanOdds ?? fallbackOdds))}</b></span></a>`;
  }

  function depthStrip(signal) {
    return `<div class="sharp-depth-pair" aria-label="NoVIG and ProphetX liquidity intelligence">
      ${depthQuotes(signal).map(({ key, row, isBest }) => {
        const label = key === "novig" ? "NoVIG" : "ProphetX";
        return `<div class="sharp-depth-chip${isBest ? " best" : ""}${row ? "" : " unavailable"}">
          <span class="sharp-depth-chip-logo">${logo(row, key === "novig" ? "N" : "PX")}</span>
          <span class="sharp-depth-chip-copy"><strong>${label}</strong><small>${row?.availableLiquidity == null ? "Liquidity unavailable" : `${money(row.availableLiquidity)} liquidity`}</small></span>
          <b>${escapeHtml(row ? odds(row.americanOdds) : "—")}</b>
        </div>`;
      }).join("")}
    </div>`;
  }

  function signalCard(signal) {
    const sides = marketSides(signal);
    const quote = primaryQuote(signal);
    const recBet = Math.max(20, Math.round(Number(signal.confidence || 0) / 4) * 5);
    const league = String(signal.league || "").trim();
    const sport = String(signal.sport || "").trim();
    const competition = league && sport && league.toLowerCase() === sport.toLowerCase()
      ? league
      : [league, sport].filter(Boolean).join(" · ");
    return `
      <article class="sharp-signal-card${signal.id === state.selectedId ? " selected" : ""}" data-sharp-signal="${escapeHtml(signal.id)}" tabindex="0">
        <div class="sharp-signal-money sharp-liquidity-score">
          <strong title="Combined NoVIG + ProphetX liquidity">${escapeHtml(liquidityMoney(combinedDepthLiquidity(signal)))}</strong>
          <span>${escapeHtml(pinnacleLimitLabel(signal))}</span>
        </div>
        <div class="sharp-card-body">
          <div class="sharp-card-heading">
            <div><small>${escapeHtml(competition)}</small><strong>${escapeHtml(signal.event)}</strong><em>${escapeHtml(signal.market?.name)}</em></div>
            <time>${escapeHtml(timeLabel(signal.startsAt))}</time>
          </div>
          <div class="sharp-card-market">
            <div class="sharp-card-market-row primary"><strong>${escapeHtml(sides.selected)}</strong><span><b>${money(recBet, false)}</b><small>Rec Bet</small></span>${sportsbookAction(quote, signal.americanOdds)}</div>
            ${depthStrip(signal)}
          </div>
        </div>
      </article>`;
  }

  function outcomeRows(signal) {
    const max = Math.max(...(signal.outcomes || []).map(row => Number(row.liquidity) || 0), 1);
    return (signal.outcomes || []).map(row => `
      <div class="sharp-depth-row">
        <span class="sharp-depth-source"><span class="sharp-book-mark" style="--book-color:#12bca7">PX</span><span>${escapeHtml(row.name)}</span></span>
        <strong>${escapeHtml(odds(row.americanOdds))}</strong>
        <span class="sharp-depth-track"><i style="--depth:${Math.max(3, (Number(row.liquidity || 0) / max) * 100).toFixed(1)}%"></i></span>
        <strong>${escapeHtml(money(row.liquidity))}</strong>
      </div>`).join("");
  }

  function flowRows(signal) {
    const rows = depthQuotes(signal).map(item => item.row).filter(row => row?.availableLiquidity != null);
    const max = Math.max(...rows.map(row => Number(row.availableLiquidity) || 0), 1);
    return rows.map(row => `
      <div class="sharp-flow-depth-row">
        <span class="sharp-flow-book">${logo(row, String(row.providerName || "?").slice(0, 2))}</span>
        <strong>${escapeHtml(odds(row.americanOdds))}</strong>
        <span class="sharp-flow-bar"><i style="--flow-width:${Math.max(4, (Number(row.availableLiquidity || 0) / max) * 100).toFixed(1)}%"></i></span>
        <small>${escapeHtml(money(row.availableLiquidity))}</small>
      </div>`).join("") || `<div class="sharp-awaiting-lines">Awaiting quoted depth</div>`;
  }

  function twoSidedComparison(signal) {
    const sides = marketSides(signal);
    const rows = [...(signal.comparisonLines || [])].sort((a, b) => {
      const aIntel = isMarketIntelligenceProvider(a) ? 1 : 0;
      const bIntel = isMarketIntelligenceProvider(b) ? 1 : 0;
      return aIntel - bIntel;
    });
    const sportsbookRows = rows.filter(row => !isMarketIntelligenceProvider(row));
    const bestLeft = Math.max(...sportsbookRows.map(row => Number(row.americanOdds) || -99999));
    const finiteRight = sportsbookRows.filter(row => Number.isFinite(Number(row.oppositeAmericanOdds)));
    const bestRight = finiteRight.length ? Math.max(...finiteRight.map(row => Number(row.oppositeAmericanOdds))) : null;
    return `
      <div class="sharp-market-table-head"><strong>${escapeHtml(sides.selected)}</strong><button type="button" aria-label="Swap sides"><i class="ph ph-arrows-down-up"></i></button><strong>${escapeHtml(sides.opposite)}</strong></div>
      <div class="sharp-market-table">
        ${rows.map(row => {
          const leftBest = Number(row.americanOdds) === bestLeft;
          const rightBest = bestRight != null && Number(row.oppositeAmericanOdds) === bestRight;
          return `<div class="sharp-market-table-row${isMarketIntelligenceProvider(row) ? " intelligence" : " sportsbook"}">
            <a class="sharp-market-price${leftBest ? " best" : ""}" href="${escapeHtml(row.deepLink || "#")}" ${row.deepLink ? 'target="_blank" rel="noopener noreferrer"' : 'aria-disabled="true"'}><strong>${escapeHtml(odds(row.americanOdds))}</strong><small>${row.availableLiquidity == null ? "" : `Liq ${money(row.availableLiquidity)}`}</small></a>
            <span class="sharp-market-book sharp-market-book--${providerKey(row)}">${logo(row, String(row.providerName || "?").slice(0, 2))}</span>
            <a class="sharp-market-price${rightBest ? " best" : ""}" href="${escapeHtml(row.deepLink || "#")}" ${row.deepLink ? 'target="_blank" rel="noopener noreferrer"' : 'aria-disabled="true"'}><strong>${escapeHtml(odds(row.oppositeAmericanOdds))}</strong><small>${row.oppositeAvailableLiquidity == null ? "" : `Liq ${money(row.oppositeAvailableLiquidity)}`}</small></a>
          </div>`;
        }).join("")}
      </div>`;
  }

  function comparisonRows(signal) {
    const rows = signal.comparisonLines || [];
    if (!rows.length) return `<div class="sharp-awaiting-lines"><i class="ph ph-hourglass-medium"></i><span>Exact-line comparisons refresh every 60 seconds while Play is active.</span></div>`;
    const best = Math.max(...rows.map(row => Number(row.americanOdds) || -99999));
    return rows.map(row => `
      <a class="sharp-execution-book${Number(row.americanOdds) === best ? " best" : ""}" href="${escapeHtml(row.deepLink || "#")}" ${row.deepLink ? 'target="_blank" rel="noopener noreferrer"' : 'aria-disabled="true"'}>
        <span class="sharp-execution-brand">${logo(row, String(row.providerName || "?").slice(0, 2))}</span>
        <span class="sharp-execution-copy"><strong>${escapeHtml(row.providerName)}</strong><small>${row.availableLiquidity == null ? "Exact market" : `${money(row.availableLiquidity)} available`}</small></span>
        <span class="sharp-execution-price"><strong>${escapeHtml(odds(row.americanOdds))}</strong><small>${Number(row.americanOdds) === best ? "Best line" : "Live line"}</small></span>
      </a>`).join("");
  }

  function historyChart(signal) {
    const history = signal.history || [];
    if (history.length < 2) return `<div class="sharp-chart-warmup"><i class="ph ph-chart-line-up"></i><strong>Building price history</strong><span>Two or more live snapshots are required.</span></div>`;
    const values = history.map(row => Number(row.americanOdds) || 0);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const points = values.map((value, index) => {
      const x = history.length === 1 ? 0 : (index / (history.length - 1)) * 100;
      const y = max === min ? 50 : 88 - ((value - min) / (max - min)) * 68;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    return `<svg class="sharp-flow-chart" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="ProphetX price history"><polyline points="${points}"></polyline></svg>`;
  }

  function detail(signal) {
    const sides = marketSides(signal);
    const quote = primaryQuote(signal);
    const recBet = Math.max(20, Math.round(Number(signal.confidence || 0) / 4) * 5);
    return `
      <button class="sharp-mobile-close" id="sharp-detail-close" type="button" aria-label="Close market detail"><i class="ph ph-x"></i></button>
      <header class="sharp-detail-head"><strong class="sharp-detail-liquidity">${escapeHtml(money(signal.liquidity))}</strong><div><span>${escapeHtml(signal.league)} · ${escapeHtml(signal.sport)}</span><h2>${escapeHtml(signal.event)}</h2><em>${escapeHtml(signal.market?.name)}</em></div><div class="sharp-detail-time"><b>${escapeHtml(timeLabel(signal.startsAt))}</b><span class="sharp-detail-icons"><i class="ph ph-table"></i><i class="ph ph-calendar-blank"></i><i class="ph ph-chart-line-up"></i><i class="ph ph-eye-slash"></i></span></div></header>
      <section class="sharp-recommendation">
        <span class="sharp-book-icon">${logo(quote, "SB")}</span>
        <div class="sharp-rec-copy"><strong>${escapeHtml(sides.selected)}</strong></div>
        <div class="sharp-rec-stake"><strong>${money(recBet, false)}</strong><span>Rec Bet</span></div>
        <div class="sharp-rec-price"><strong>${escapeHtml(quote ? odds(quote.americanOdds) : "—")}</strong><span>${escapeHtml(quote?.providerName || "No sportsbook line")}</span></div>
        ${quote ? `<a class="sharp-game-button" href="${escapeHtml(quote.deepLink || "#")}" ${quote.deepLink ? 'target="_blank" rel="noopener noreferrer"' : 'aria-disabled="true"'}>BET <i class="ph ph-arrow-up-right"></i></a>` : `<span class="sharp-game-button unavailable">WAIT</span>`}
        <button class="sharp-add-button" type="button" aria-label="Add selection"><i class="ph ph-plus"></i></button>
      </section>
      <section class="sharp-flow-summary">
        <span class="sharp-flow-primary-logo">${logo(signal)}</span><strong>${escapeHtml(sides.opposite)}</strong><span><b>${escapeHtml(odds(signal.americanOdds))}</b><small>Avg</small></span><span><b>${escapeHtml(money(signal.liquidity))}</b><small>Liquidity</small></span><i class="ph ph-question"></i>
      </section>
      <section class="sharp-flow-depth">
        ${flowRows(signal)}
      </section>
      <section class="sharp-detail-depth-pair">
        ${depthStrip(signal)}
      </section>
      <section class="sharp-market-comparison">
        ${twoSidedComparison(signal)}
      </section>
    `;
  }

  function matches(signal) {
    const haystack = `${signal.event} ${signal.selection} ${signal.league} ${signal.market?.name}`.toLowerCase();
    const detected = Math.abs(Number(signal.pressure)) >= 0.01;
    return (!state.sport || signal.league === state.sport || signal.sport === state.sport)
      && (!state.search || haystack.includes(state.search))
      && Number(signal.liquidity || 0) >= state.filters.minimumLiquidity
      && (!state.filters.flow || (state.filters.flow === "detected") === detected)
      && (!state.filters.marketType || signal.market?.kind === state.filters.marketType);
  }

  function render() {
    const payload = state.payload || {};
    const running = payload.running === true;
    const prophetxConfigured = payload.provider?.configured === true;
    const comparisonsConfigured = payload.comparisonProvider?.configured === true;
    state.visible = state.signals.filter(matches).sort((left, right) => {
      const leftLiquidity = combinedDepthLiquidity(left) ?? -1;
      const rightLiquidity = combinedDepthLiquidity(right) ?? -1;
      return state.sortDescending ? rightLiquidity - leftLiquidity : leftLiquidity - rightLiquidity;
    });
    if (!state.visible.some(row => row.id === state.selectedId)) state.selectedId = state.visible[0]?.id || null;
    const previewOnly = payload.previewOnly === true;
    const placeholderMode = payload.placeholderMode === true;
    const feedToggle = $("sharp-feed-toggle");
    feedToggle.innerHTML = `<i class="ph ${running ? "ph-pause" : "ph-play"}"></i>`;
    feedToggle.classList.toggle("active", running);
    feedToggle.setAttribute("aria-pressed", String(running));
    feedToggle.setAttribute("aria-label", running ? "Pause feed" : "Play feed");
    feedToggle.disabled = previewOnly || state.controlling || (!running && !prophetxConfigured);
    feedToggle.title = previewOnly
      ? "Visual preview does not start provider requests"
      : running
        ? "Pause the local read-only collector"
        : prophetxConfigured
          ? "Start the local read-only collector"
          : "Add ProphetX sandbox credentials to .env.local first";
    $("sharp-sort").setAttribute("aria-pressed", String(!state.sortDescending));
    $("sharp-sort").title = state.sortDescending ? "Combined liquidity: high to low" : "Combined liquidity: low to high";
    $("sharp-detail-toggle").setAttribute("aria-pressed", String(state.detailVisible));
    document.querySelector(".sharp-workspace")?.classList.toggle("detail-hidden", !state.detailVisible);
    const activeFilterCount = Number(state.filters.minimumLiquidity > 0) + Number(Boolean(state.filters.flow)) + Number(Boolean(state.filters.marketType));
    $("sharp-filter-count").textContent = String(activeFilterCount);
    $("sharp-filter-open").classList.toggle("has-filters", activeFilterCount > 0);
    $("sharp-mode-badge").classList.toggle("live", running);
    $("sharp-mode-badge").innerHTML = previewOnly
      ? `<i class="ph ph-eye"></i> Visual preview`
      : placeholderMode
        ? `<i class="ph ph-eye"></i> Sample trades`
      : running ? `<i class="ph ph-waveform"></i> Live local feed` : `<i class="ph ph-pause"></i> Paused`;
    $("sharp-feed-notice").classList.toggle("live", running);
    $("sharp-feed-title").textContent = previewOnly
      ? "Five visual preview plays - no provider requests"
      : placeholderMode
        ? `${state.visible.length} visual placeholder trades - no sample is executable`
      : running
      ? "Local collector active"
      : prophetxConfigured
        ? "Feed paused - zero new requests"
        : "ProphetX credentials required - zero new requests";
    $("sharp-feed-copy").textContent = previewOnly
      ? "Synthetic layout fixtures only. Tracking, Discord, provider credits, and model data are disabled."
      : placeholderMode
        ? running
          ? "Sample cards remain visible while the live collector looks for exact markets. They are clearly labeled and never enter tracking."
          : prophetxConfigured
            ? "Sample cards are shown while the feed is empty. Press Play to replace them with real markets as they arrive."
            : "Sample cards are shown for layout review. Connect ProphetX to replace them with real markets."
      : running
      ? `ProphetX refreshes every ${payload.pollSeconds || 1}s; other-book comparisons every ${payload.comparisonSeconds || 60}s.`
      : prophetxConfigured
        ? `Press Play to start ProphetX${comparisonsConfigured ? " and sportsbook comparisons" : "; add THE_ODDS_API_KEY for other-book comparisons"}.`
        : "Add PROPHETX_ACCESS_KEY and PROPHETX_SECRET_KEY to .env.local, then restart this local preview.";
    $("sharp-feed-state").innerHTML = `<i></i> ${previewOnly ? "Preview" : placeholderMode ? "Samples" : running ? "Collecting" : "Paused"}`;
    $("sharp-result-label").textContent = previewOnly
      ? `${state.visible.length} preview play${state.visible.length === 1 ? "" : "s"}`
      : placeholderMode
        ? `${state.visible.length} placeholder trade${state.visible.length === 1 ? "" : "s"}`
      : running ? `${state.visible.length} monitored market${state.visible.length === 1 ? "" : "s"}` : "Collector paused";
    $("sharp-last-updated").textContent = placeholderMode ? "Visual samples only" : payload.lastError || ageLabel(payload.lastSnapshotAt);
    const liquidity = state.visible.reduce((sum, row) => sum + Number(row.liquidity || 0), 0);
    const flows = state.visible.filter(row => Math.abs(Number(row.pressure)) >= 0.01).length;
    $("sharp-summary-signals").textContent = String(state.visible.length);
    $("sharp-summary-liquidity").textContent = money(liquidity);
    $("sharp-summary-flow").textContent = String(flows);
    $("sharp-summary-cycles").textContent = String(payload.cycles || 0);
    $("sharp-summary-signals-note").textContent = placeholderMode ? "Clearly labeled sample markets" : "Real ProphetX markets";
    $("sharp-summary-liquidity-note").textContent = placeholderMode ? "Sample quoted depth" : "Quoted, not confirmed wagers";
    $("sharp-summary-flow-note").textContent = placeholderMode ? "Sample inferred pressure" : "Snapshot-inferred pressure";
    const requests = payload.provider?.metrics?.requests || 0;
    $("sharp-summary-requests").textContent = running ? `${requests} ProphetX requests this process` : "No requests while paused";
    $("sharp-signal-list").innerHTML = state.visible.length
      ? state.visible.map(signalCard).join("")
      : `<div class="sharp-empty-state"><div><i class="ph ${running ? "ph-radar" : prophetxConfigured ? "ph-pause-circle" : "ph-key"}"></i><strong>${running ? "Waiting for exact ProphetX markets" : prophetxConfigured ? "Sharp Money is paused" : "Connect ProphetX to begin"}</strong><span>${payload.lastError || (running ? "The first authenticated snapshot may take a few seconds." : prophetxConfigured ? "Start the local feed when you want to inspect real markets." : "Credentials stay local and the integration remains read-only.")}</span></div></div>`;
    const selected = state.visible.find(row => row.id === state.selectedId);
    $("sharp-detail-panel").innerHTML = selected
      ? detail(selected)
      : `<div class="sharp-detail-loading"><i class="ph ph-waveform"></i><strong>No market selected</strong><span>${running ? "Waiting for ProphetX market data." : "Play the feed, then select a market."}</span></div>`;
  }

  async function load() {
    try {
      const endpoint = state.preview ? "/api/sharp-money/live?preview=1" : "/api/sharp-money/live";
      const response = await fetch(endpoint, { cache: "no-store", credentials: "same-origin" });
      if (!response.ok) throw new Error(`Sharp Money returned ${response.status}`);
      state.payload = await response.json();
      const liveSignals = Array.isArray(state.payload.signals) ? state.payload.signals : [];
      if (!state.preview && liveSignals.length === 0) {
        if (state.placeholderSignals.length === 0) {
          const placeholderResponse = await fetch("/api/sharp-money/live?preview=1", {
            cache: "no-store",
            credentials: "same-origin",
          });
          if (!placeholderResponse.ok) throw new Error(`Sharp Money placeholders returned ${placeholderResponse.status}`);
          const placeholderPayload = await placeholderResponse.json();
          state.placeholderSignals = Array.isArray(placeholderPayload.signals) ? placeholderPayload.signals : [];
        }
        state.payload.placeholderMode = true;
        state.signals = state.placeholderSignals;
      } else {
        state.signals = liveSignals;
      }
      render();
    } catch {
      $("sharp-last-updated").textContent = "Local collector unavailable";
    }
  }

  async function control(action) {
    if (state.controlling) return;
    state.controlling = true;
    render();
    try {
      const response = await fetch("/api/sharp-money/control", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || payload.error || "Control failed");
      state.payload = { ...state.payload, ...payload };
      if (window.showToast) window.showToast(payload.message);
      await load();
    } catch (error) {
      if (window.showToast) window.showToast(error.message);
      else window.alert(error.message);
    } finally {
      state.controlling = false;
      render();
    }
  }

  function openFilters(open) {
    $("sharp-filter-drawer").hidden = !open;
    $("sharp-filter-backdrop").hidden = !open;
    document.body.style.overflow = open ? "hidden" : "";
  }

  function readFilters() {
    state.filters.minimumLiquidity = Number($("sharp-liquidity-filter").value) || 0;
    state.filters.flow = $("sharp-flow-filter").value;
    state.filters.marketType = $("sharp-market-filter").value;
    render();
  }

  function bind() {
    $("sharp-feed-toggle").addEventListener("click", () => control(state.payload?.running ? "pause" : "play"));
    $("sharp-sort").addEventListener("click", () => {
      state.sortDescending = !state.sortDescending;
      render();
    });
    $("sharp-detail-toggle").addEventListener("click", () => {
      state.detailVisible = !state.detailVisible;
      render();
    });
    $("sharp-search").addEventListener("input", event => { state.search = event.target.value.trim().toLowerCase(); render(); });
    $("sharp-signal-list").addEventListener("click", event => {
      const card = event.target.closest("[data-sharp-signal]");
      if (!card) return;
      state.selectedId = card.dataset.sharpSignal;
      state.detailVisible = true;
      render();
      $("sharp-detail-panel").classList.add("mobile-open");
      document.body.classList.add("sharp-detail-open");
    });
    $("sharp-signal-list").addEventListener("keydown", event => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const card = event.target.closest("[data-sharp-signal]");
      if (!card) return;
      event.preventDefault();
      card.click();
    });
    $("sharp-detail-panel").addEventListener("click", event => {
      if (!event.target.closest("#sharp-detail-close")) return;
      $("sharp-detail-panel").classList.remove("mobile-open");
      document.body.classList.remove("sharp-detail-open");
    });
    document.querySelectorAll("[data-sharp-sport]").forEach(button => button.addEventListener("click", () => {
      state.sport = button.dataset.sharpSport;
      document.querySelectorAll("[data-sharp-sport]").forEach(item => item.classList.toggle("active", item === button));
      render();
    }));
    $("sharp-filter-open").addEventListener("click", () => openFilters(true));
    $("sharp-refresh")?.addEventListener("click", load);
    $("sharp-alerts")?.addEventListener("click", () => window.showToast?.("No new Sharp Money alerts"));
    $("sharp-more")?.addEventListener("click", () => window.showToast?.("Additional Sharp Money controls are coming soon"));
    $("sharp-filter-close").addEventListener("click", () => openFilters(false));
    $("sharp-filter-backdrop").addEventListener("click", () => openFilters(false));
    $("sharp-filter-apply").addEventListener("click", () => { readFilters(); openFilters(false); });
    $("sharp-filter-reset").addEventListener("click", () => {
      $("sharp-liquidity-filter").value = "0";
      $("sharp-liquidity-value").textContent = "$0";
      $("sharp-flow-filter").value = "";
      $("sharp-market-filter").value = "";
      readFilters();
    });
    $("sharp-liquidity-filter").addEventListener("input", event => { $("sharp-liquidity-value").textContent = money(event.target.value, false); });
    document.addEventListener("keydown", event => {
      if (event.key !== "Escape") return;
      openFilters(false);
      $("sharp-detail-panel").classList.remove("mobile-open");
      document.body.classList.remove("sharp-detail-open");
    });
  }

  if (document.body.dataset.page === "sharp-money") {
    bind();
    load();
    if (!state.preview) window.setInterval(load, 2000);
  }
})();
