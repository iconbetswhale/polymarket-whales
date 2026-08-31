(() => {
  "use strict";

  const sharpBookCatalog = (() => {
    try {
      const entries = JSON.parse(document.getElementById("sharp-book-catalog")?.textContent || "[]");
      return Array.isArray(entries) ? entries : [];
    } catch (_) {
      return [];
    }
  })();
  const sharpBookKeys = new Set(sharpBookCatalog.map(book => book.key));
  const sharpBookFilterStorageKey = "iconlabs-sharp-sportsbook-filter-v1";
  let initialSharpSportsbooks = new Set(sharpBookKeys);
  try {
    const saved = JSON.parse(localStorage.getItem(sharpBookFilterStorageKey) || "null");
    if (Array.isArray(saved)) {
      const valid = saved.filter(key => sharpBookKeys.has(key));
      if (valid.length) initialSharpSportsbooks = new Set(valid);
    }
  } catch (_) {}

  const state = {
    payload: null,
    signals: [],
    visible: [],
    selectedId: null,
    sport: "",
    search: "",
    controlling: false,
    filters: { minimumLiquidity: 0, flow: "", marketType: "", sportsbooks: initialSharpSportsbooks },
    filterDraftSportsbooks: new Set(initialSharpSportsbooks),
    sortDescending: true,
    detailVisible: true,
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
    if (value == null || value === "") return "N/A";
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
    "pinnacle", "circa", "circasports", "lowvig", "betonline",
  ]);
  const DEPTH_PROVIDER_ORDER = ["novig", "prophetx"];
  const EXCHANGE_DESTINATIONS = Object.freeze({
    novig: "https://novig.com/",
    prophetx: "https://www.prophetx.co/lobby/",
  });
  const TEAM_LOGO_KEYS = {
    mlb: {
      "Arizona Diamondbacks": "ari", "Atlanta Braves": "atl", "Baltimore Orioles": "bal",
      "Boston Red Sox": "bos", "Chicago Cubs": "chc", "Chicago White Sox": "chw",
      "Cincinnati Reds": "cin", "Cleveland Guardians": "cle", "Colorado Rockies": "col",
      "Detroit Tigers": "det", "Houston Astros": "hou", "Kansas City Royals": "kc",
      "Los Angeles Angels": "laa", "Los Angeles Dodgers": "lad", "Miami Marlins": "mia",
      "Milwaukee Brewers": "mil", "Minnesota Twins": "min", "New York Mets": "nym",
      "New York Yankees": "nyy", "Oakland Athletics": "oak", "Philadelphia Phillies": "phi",
      "Pittsburgh Pirates": "pit", "San Diego Padres": "sd", "Seattle Mariners": "sea",
      "San Francisco Giants": "sf", "St. Louis Cardinals": "stl", "Tampa Bay Rays": "tb",
      "Texas Rangers": "tex", "Toronto Blue Jays": "tor", "Washington Nationals": "wsh",
    },
    wnba: {
      "Atlanta Dream": "atl", "Chicago Sky": "chi", "Connecticut Sun": "connecticut",
      "Dallas Wings": "dal", "Golden State Valkyries": "gs", "Indiana Fever": "ind",
      "Los Angeles Sparks": "la", "Las Vegas Aces": "lv", "Minnesota Lynx": "min",
      "New York Liberty": "ny", "Phoenix Mercury": "phx", "Seattle Storm": "sea",
      "Washington Mystics": "wsh",
    },
  };

  function providerKey(row) {
    const raw = row?.providerKey || row?.providerName || row?.provider || "";
    const normalized = String(raw).toLowerCase().replace(/[^a-z0-9]/g, "");
    return normalized === "fourcx" ? "4cx" : normalized;
  }

  const sharpBookAliases = Object.freeze({
    betr: "betrsportsbook",
    hardrock: "hardrockbet",
    prophetx: "prophetexchange",
    sportsbettingag: "sportsbetting_ag",
    thescore: "thescorebet",
    betrpicks: "betr_picks",
    dkpick6: "pick6",
    draftkingspick6: "pick6",
  });
  const sharpBookByCompactKey = new Map(
    sharpBookCatalog.map(book => [String(book.key).toLowerCase().replace(/[^a-z0-9]/g, ""), book.key])
  );

  function providerCatalogKey(row) {
    const raw = String(row?.providerKey || row?.providerName || row?.provider || "")
      .trim().toLowerCase().replace(/^(oddsengine__|oddsapi__)/, "");
    const compact = raw.replace(/[^a-z0-9]/g, "");
    const alias = sharpBookAliases[raw] || sharpBookAliases[compact];
    if (alias && sharpBookKeys.has(alias)) return alias;
    if (sharpBookKeys.has(raw)) return raw;
    return sharpBookByCompactKey.get(compact) || raw;
  }

  function sportsbookFilterActive() {
    return state.filters.sportsbooks.size !== sharpBookKeys.size;
  }

  function selectedComparisonLines(signal) {
    const rows = Array.isArray(signal.comparisonLines) ? signal.comparisonLines : [];
    if (!sportsbookFilterActive()) return rows;
    return rows.filter(row => state.filters.sportsbooks.has(providerCatalogKey(row)));
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

  function decimalOdds(value) {
    const price = Number(value);
    if (!Number.isFinite(price) || (price > -100 && price < 100)) return null;
    return price > 0 ? 1 + price / 100 : 1 + 100 / Math.abs(price);
  }

  function isCrossedRetailQuote(signal, quote) {
    const retailDecimal = decimalOdds(quote?.americanOdds);
    if (retailDecimal == null) return false;
    return depthQuotes(signal).some(({ row }) => {
      const sharpDecimal = decimalOdds(row?.oppositeAmericanOdds);
      const liquidity = Number(row?.oppositeAvailableLiquidity);
      return sharpDecimal != null && Number.isFinite(liquidity) && liquidity > 0
        && (1 / retailDecimal) + (1 / sharpDecimal) < 1;
    });
  }

  function primaryQuote(signal) {
    const rows = selectedComparisonLines(signal);
    return bestQuote(rows.filter(row => !isMarketIntelligenceProvider(row)));
  }

  function depthQuotes(signal) {
    const rows = Array.isArray(signal.comparisonLines) ? signal.comparisonLines : [];
    const byProvider = new Map(rows.map(row => [providerKey(row), row]));
    const quotes = DEPTH_PROVIDER_ORDER.map(key => ({ key, row: byProvider.get(key) || null }));
    const best = bestQuote(quotes.map(item => item.row).filter(Boolean));
    return quotes.map(item => ({ ...item, isBest: item.row === best }));
  }

  function safeHttpsUrl(value) {
    try {
      const url = new URL(String(value || ""));
      return url.protocol === "https:" ? url.href : "";
    } catch (_) {
      return "";
    }
  }

  function exchangeAction(key, row) {
    const label = key === "novig" ? "NoVIG" : "ProphetX";
    const exactUrl = safeHttpsUrl(row?.deepLink);
    const destination = exactUrl || EXCHANGE_DESTINATIONS[key];
    const exactMarket = Boolean(
      exactUrl
      && row?.matchingConfidence === "Exact"
      && row?.linkScope !== "provider"
    );
    const title = exactMarket
      ? `Open the exact ${label} market`
      : `Open ${label} to find this market and inspect liquidity`;
    return `<a class="sharp-depth-bet${exactMarket ? " exact" : " provider"}" href="${escapeHtml(destination)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}">BET <i class="ph ph-arrow-up-right"></i></a>`;
  }

  function combinedCrossedLiquidity(signal) {
    if (signal?.crossedLiquidity != null) {
      const explicit = Number(signal.crossedLiquidity);
      if (Number.isFinite(explicit) && explicit >= 0) return explicit;
    }
    if (signal?.depthAvailable === false) return null;
    const values = depthQuotes(signal)
      .map(item => item.row?.oppositeAvailableLiquidity)
      .filter(value => value != null)
      .map(value => Number(value))
      .filter(value => Number.isFinite(value) && value >= 0);
    return values.length ? values.reduce((total, value) => total + value, 0) : null;
  }

  function signalHeadline(signal) {
    return liquidityMoney(combinedCrossedLiquidity(signal));
  }

  function signalHeadlineLabel(signal) {
    return "Net Sharp Liquidity";
  }

  function signalCoverageLabel(signal) {
    if (signal.depthAvailable === false) return "Liquidity unavailable";
    const sources = Object.keys(signal.liquiditySources || {});
    return sources.length ? `${sources.length} sharp exchange${sources.length === 1 ? "" : "s"}` : "NoVIG + ProphetX";
  }

  function depthProviderUnavailableLabel(key) {
    const diagnostics = state.payload?.sourceDiagnostics?.[key] || {};
    const status = String(diagnostics.health || diagnostics.status || "").toLowerCase();
    if (status === "unauthorized") return "Login needs reconnect";
    if (status.includes("connection")) return "Connection unavailable";
    return "Exact quote unavailable";
  }

  function sportsbookAction(quote, fallbackOdds) {
    if (!quote) {
      return `<span class="sharp-sportsbook-action unavailable"><small>Sportsbook</small><b>Awaiting line</b></span>`;
    }
    return `<a class="sharp-sportsbook-action" href="${escapeHtml(quote.deepLink || "#")}" ${quote.deepLink ? 'target="_blank" rel="noopener noreferrer"' : 'aria-disabled="true"'}>${logo(quote, String(quote.providerName || "?").slice(0, 2))}<span><small>${escapeHtml(quote.providerName || "Sportsbook")}</small><b>${escapeHtml(odds(quote.americanOdds ?? fallbackOdds))}</b></span></a>`;
  }

  function eventTeams(signal) {
    const eventParts = String(signal.event || "").split(/\s+vs\.?\s+/i).map(value => value.trim()).filter(Boolean);
    return {
      away: signal.awayTeam && !/^(over|under)\b/i.test(signal.awayTeam) ? signal.awayTeam : eventParts[0],
      home: signal.homeTeam || eventParts[1],
    };
  }

  function teamLogoUrl(signal, team) {
    const league = String(signal.league || signal.sport || "").toLowerCase();
    const key = TEAM_LOGO_KEYS[league]?.[team];
    return key ? `/static/assets/teams/${league}/${key}.png` : "";
  }

  function teamLogos(signal) {
    const teams = eventTeams(signal);
    const logos = [teams.away, teams.home].map(team => {
      const url = teamLogoUrl(signal, team);
      return url ? `<span class="sharp-card-team-logo" title="${escapeHtml(team)}"><img src="${escapeHtml(url)}" alt="${escapeHtml(team)} logo" loading="lazy"></span>` : "";
    }).filter(Boolean);
    return logos.length ? `<div class="sharp-card-team-logos" aria-label="Teams">${logos.join("")}</div>` : "";
  }

  function depthSummary(signal) {
    const quotes = depthQuotes(signal);
    const best = bestQuote(quotes.map(item => item.row).filter(Boolean));
    return `<div class="sharp-card-depth-summary" aria-label="NoVIG and ProphetX liquidity intelligence">
      <div class="sharp-card-depth-sources">
      ${quotes.map(({ key, row }) => {
        const label = key === "novig" ? "NoVIG" : "ProphetX";
        const secondary = !row
          ? depthProviderUnavailableLabel(key)
          : signal.depthAvailable === false
            ? `${odds(row.americanOdds)} exact quote`
            : row.availableLiquidity == null ? "Liquidity unavailable" : `${money(row.availableLiquidity)} at ${odds(row.americanOdds)}`;
        return `<div class="sharp-depth-chip${row ? "" : " unavailable"}">
          <span class="sharp-depth-chip-logo">${logo(row, key === "novig" ? "N" : "PX")}</span>
          <span class="sharp-depth-chip-copy"><strong>${label}</strong><small>${escapeHtml(secondary)}</small></span>
          ${exchangeAction(key, row)}
        </div>`;
      }).join("")}
      </div>
      <div class="sharp-card-best-price"><small>Best sharp price</small><strong>${escapeHtml(best ? odds(best.americanOdds) : "—")}</strong></div>
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
          <strong title="Selected-side liquidity minus opposing-side liquidity across NoVIG and ProphetX">${escapeHtml(signalHeadline(signal))}</strong>
          <small>${escapeHtml(signalHeadlineLabel(signal))}</small>
          <span>${escapeHtml(signalCoverageLabel(signal))}</span>
        </div>
        <div class="sharp-card-body">
          <div class="sharp-card-event">
            ${teamLogos(signal)}
            <strong>${escapeHtml(signal.event)}</strong>
            <em>${escapeHtml(signal.market?.name)}</em>
            <time>${escapeHtml(timeLabel(signal.startsAt))}</time>
            <b>${escapeHtml(sides.selected)}</b>
          </div>
          <div class="sharp-card-execution">
            <div class="sharp-card-action-row">
              <span class="sharp-card-rec-bet"><b>${money(recBet, false)}</b><small>Rec Bet</small></span>
              ${sportsbookAction(quote, signal.americanOdds)}
              ${quote ? `<a class="sharp-card-bet" href="${escapeHtml(quote.deepLink || "#")}" ${quote.deepLink ? 'target="_blank" rel="noopener noreferrer"' : 'aria-disabled="true"'}>BET <i class="ph ph-arrow-up-right"></i></a>` : ""}
              <button class="sharp-card-add" type="button" aria-label="Add ${escapeHtml(sides.selected)}"><i class="ph ph-plus"></i></button>
            </div>
            ${depthSummary(signal)}
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
    if (signal.depthAvailable === false) {
      return `<div class="sharp-awaiting-lines">Live price-consensus mode. Exact two-sided prices are available below.</div>`;
    }
    const rows = depthQuotes(signal).map(item => item.row).filter(row => row?.availableLiquidity != null);
    const max = Math.max(...rows.map(row => Number(row.availableLiquidity) || 0), 1);
    return rows.map(row => {
      const price = `<strong>${escapeHtml(odds(row.americanOdds))}</strong>`;
      const priceAction = row.deepLink
        ? `<a class="sharp-flow-bet-link" href="${escapeHtml(row.deepLink)}" target="_blank" rel="noopener noreferrer" aria-label="Open ${escapeHtml(row.providerName || "exchange")} ${escapeHtml(odds(row.americanOdds))} in a new tab">${price}<i class="ph ph-arrow-square-out" aria-hidden="true"></i></a>`
        : price;
      return `<div class="sharp-flow-depth-row">
        <span class="sharp-flow-book">${logo(row, String(row.providerName || "?").slice(0, 2))}<b>${escapeHtml(row.providerName || "Market")}</b></span>
        ${priceAction}
        <span class="sharp-flow-bar"><i style="--flow-width:${Math.max(4, (Number(row.availableLiquidity || 0) / max) * 100).toFixed(1)}%"></i></span>
        <small>${escapeHtml(money(row.availableLiquidity))}</small>
      </div>`;
    }).join("") || `<div class="sharp-awaiting-lines">Awaiting quoted depth</div>`;
  }

  function twoSidedComparison(signal) {
    const sides = marketSides(signal);
    const rows = [...selectedComparisonLines(signal)].sort((a, b) => {
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
            <a class="sharp-market-price${rightBest ? " best" : ""}" href="${escapeHtml(row.oppositeDeepLink || row.deepLink || "#")}" ${row.oppositeDeepLink || row.deepLink ? 'target="_blank" rel="noopener noreferrer"' : 'aria-disabled="true"'}><strong>${escapeHtml(odds(row.oppositeAmericanOdds))}</strong><small>${row.oppositeAvailableLiquidity == null ? "" : `Liq ${money(row.oppositeAvailableLiquidity)}`}</small></a>
          </div>`;
        }).join("")}
      </div>`;
  }

  function comparisonRows(signal) {
    const rows = selectedComparisonLines(signal);
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
    const league = String(signal.league || "").trim();
    const sport = String(signal.sport || "").trim();
    const competition = league && sport && league.toLowerCase() === sport.toLowerCase()
      ? league
      : [league, sport].filter(Boolean).join(" · ");
    return `
      <button class="sharp-mobile-close" id="sharp-detail-close" type="button" aria-label="Close market detail"><i class="ph ph-x"></i></button>
      <section class="sharp-detail-overview">
        <header class="sharp-detail-head"><div class="sharp-detail-money"><strong class="sharp-detail-liquidity">${escapeHtml(signalHeadline(signal))}</strong><small>${escapeHtml(signalHeadlineLabel(signal))}</small></div><div><span>${escapeHtml(competition)}</span><h2>${escapeHtml(signal.event)}</h2><em>${escapeHtml(signal.market?.name)}</em></div><div class="sharp-detail-time"><b>${escapeHtml(timeLabel(signal.startsAt))}</b><span class="sharp-detail-icons"><i class="ph ph-table"></i><i class="ph ph-calendar-blank"></i><i class="ph ph-chart-line-up"></i><i class="ph ph-eye-slash"></i></span></div></header>
        <section class="sharp-recommendation">
          <div class="sharp-rec-copy"><strong>${escapeHtml(sides.selected)}</strong></div>
          <div class="sharp-rec-stake"><strong>${money(recBet, false)}</strong><span>Rec Bet</span></div>
          <div class="sharp-rec-book">${sportsbookAction(quote, signal.americanOdds)}</div>
          ${quote ? `<a class="sharp-game-button" href="${escapeHtml(quote.deepLink || "#")}" ${quote.deepLink ? 'target="_blank" rel="noopener noreferrer"' : 'aria-disabled="true"'}>BET <i class="ph ph-arrow-up-right"></i></a>` : `<span class="sharp-game-button unavailable">WAIT</span>`}
          <button class="sharp-add-button" type="button" aria-label="Add selection"><i class="ph ph-plus"></i></button>
        </section>
      </section>
      <section class="sharp-liquidity-panel">
        <header><strong>${escapeHtml(sides.selected)}</strong><span>Sharp Odds</span><span>Liquidity</span></header>
        <div class="sharp-flow-depth">${flowRows(signal)}</div>
      </section>
      <section class="sharp-market-comparison">
        ${twoSidedComparison(signal)}
      </section>
    `;
  }

  function matches(signal) {
    const haystack = `${signal.event} ${signal.selection} ${signal.league} ${signal.market?.name}`.toLowerCase();
    const crossedLiquidity = combinedCrossedLiquidity(signal);
    const detected = crossedLiquidity != null && crossedLiquidity > 0;
    const marketFilterKind = signal.market?.isAlternative
      ? "alternate"
      : signal.market?.kind;
    return (!state.sport || signal.league === state.sport || signal.sport === state.sport)
      && (!state.search || haystack.includes(state.search))
      && Number(crossedLiquidity || 0) >= state.filters.minimumLiquidity
      && (!state.filters.flow || (state.filters.flow === "detected") === detected)
      && (!state.filters.marketType || marketFilterKind === state.filters.marketType)
      && (!sportsbookFilterActive() || selectedComparisonLines(signal).length > 0);
  }

  function render() {
    const payload = state.payload || {};
    const running = payload.running === true;
    const sourceConfigured = payload.provider?.configured === true;
    const automatic = payload.automatic === true;
    const quoteConsensus = payload.signalMode === "quote_consensus";
    const directOrderBook = payload.signalMode === "direct_order_book";
    const advancedOrderBookEnabled = payload.advancedOrderBookEnabled === true;
    const standardOddsEngine = payload.provider?.provider === "odds_engine" && !advancedOrderBookEnabled;
    const directDepthName = Array.isArray(payload.depthProviders) && payload.depthProviders.length
      ? payload.depthProviders.join(" + ")
      : "NoVIG + ProphetX";
    const sourceName = directOrderBook
      ? `direct ${directDepthName}`
      : payload.provider?.provider === "odds_engine"
      ? quoteConsensus || standardOddsEngine ? "OddsEngine sharp consensus" : "OddsEngine NoVIG + ProphetX order books"
      : "ProphetX";
    const providerError = String(payload.lastError || "").trim();
    const accessBlocked = Boolean(providerError && state.signals.length === 0);
    const advancedPlanRequired = accessBlocked
      && advancedOrderBookEnabled
      && /advanced plan|plan required|http 403/i.test(providerError);
    const comparisonsConfigured = payload.comparisonProvider?.configured === true;
    state.visible = state.signals.filter(matches).sort((left, right) => {
      const leftLiquidity = combinedCrossedLiquidity(left) ?? -1;
      const rightLiquidity = combinedCrossedLiquidity(right) ?? -1;
      return state.sortDescending ? rightLiquidity - leftLiquidity : leftLiquidity - rightLiquidity;
    });
    if (!state.visible.some(row => row.id === state.selectedId)) state.selectedId = state.visible[0]?.id || null;
    const feedToggle = $("sharp-feed-toggle");
    feedToggle.innerHTML = `<i class="ph ${running ? "ph-pause" : "ph-play"}"></i><span>${running ? "Pause feed" : "Play feed"}</span>`;
    feedToggle.classList.toggle("active", running);
    feedToggle.setAttribute("aria-pressed", String(running));
    feedToggle.setAttribute("aria-label", running ? "Pause feed" : "Play feed");
    feedToggle.disabled = automatic || state.controlling || (!running && !sourceConfigured);
    feedToggle.title = running
        ? "Pause the local read-only collector"
        : automatic
          ? `${quoteConsensus || standardOddsEngine ? "OddsEngine price-consensus" : "OddsEngine order-book"} refresh is automatic`
          : sourceConfigured
          ? "Start the local read-only collector"
          : "Add an OddsEngine Advanced or ProphetX credential first";
    $("sharp-sort").setAttribute("aria-pressed", String(!state.sortDescending));
    $("sharp-sort").title = state.sortDescending ? "Combined liquidity: high to low" : "Combined liquidity: low to high";
    $("sharp-sort").querySelector("span").textContent = state.sortDescending ? "Highest liquidity first" : "Lowest liquidity first";
    $("sharp-detail-toggle").setAttribute("aria-pressed", String(state.detailVisible));
    $("sharp-detail-toggle").querySelector("span").textContent = state.detailVisible ? "Hide market details" : "Show market details";
    document.querySelector(".sharp-workspace")?.classList.toggle("detail-hidden", !state.detailVisible);
    const activeFilterCount = Number(state.filters.minimumLiquidity > 0) + Number(Boolean(state.filters.flow)) + Number(Boolean(state.filters.marketType)) + Number(sportsbookFilterActive());
    $("sharp-filter-count").textContent = String(activeFilterCount);
    $("sharp-filter-open").classList.toggle("has-filters", activeFilterCount > 0);
    $("sharp-mode-badge").classList.toggle("live", running && !accessBlocked);
    $("sharp-mode-badge").innerHTML = accessBlocked
      ? `<i class="ph ph-warning-circle"></i> Provider blocked`
      : running ? `<i class="ph ph-waveform"></i> ${quoteConsensus ? "Live price movement" : automatic ? "Live order books" : "Live local feed"}` : `<i class="ph ph-pause"></i> Paused`;
    $("sharp-feed-notice").classList.toggle("live", running && !accessBlocked);
    $("sharp-feed-title").textContent = accessBlocked
      ? advancedPlanRequired ? "OddsEngine Advanced access required" : standardOddsEngine ? "OddsEngine price feed temporarily unavailable" : "Order-book provider unavailable"
      : running
      ? `${sourceName} active`
      : sourceConfigured
        ? "Feed paused - zero new requests"
        : "Order-book credentials required - zero new requests";
    $("sharp-feed-copy").textContent = accessBlocked
      ? providerError
      : running
      ? quoteConsensus
        ? `${sourceName} refreshes every ${payload.refreshSeconds || 30}s from exact two-sided REST prices and sharp-consensus movement.`
        : `${sourceName} refreshes every ${payload.refreshSeconds || payload.pollSeconds || 30}s${automatic ? " with full two-sided depth." : `; other-book comparisons every ${payload.comparisonSeconds || 60}s.`}`
      : sourceConfigured
        ? `Press Play to start ProphetX${comparisonsConfigured ? " and sportsbook comparisons" : "; add an odds feed for other-book comparisons"}.`
        : "Add ODDSENGINE_API_KEY or direct ProphetX credentials, then restart.";
    $("sharp-feed-state").innerHTML = `<i></i> ${accessBlocked ? "Action required" : running ? "Collecting" : "Paused"}`;
    $("sharp-result-label").textContent = accessBlocked ? "Feed unavailable" : running ? `${state.visible.length} monitored market${state.visible.length === 1 ? "" : "s"}` : "Collector paused";
    $("sharp-last-updated").textContent = payload.lastError || ageLabel(payload.lastSnapshotAt);
    const liquidity = state.visible.reduce((sum, row) => sum + Number(combinedCrossedLiquidity(row) || 0), 0);
    const flows = state.visible.filter(row => Number(combinedCrossedLiquidity(row) || 0) > 0).length;
    $("sharp-summary-signals").textContent = String(state.visible.length);
    $("sharp-summary-liquidity").textContent = money(liquidity);
    $("sharp-summary-flow").textContent = String(flows);
    $("sharp-summary-cycles").textContent = String(payload.cycles || 0);
    $("sharp-summary-signals-note").textContent = quoteConsensus ? "Exact two-sided markets" : `Real ${sourceName} markets`;
    $("sharp-summary-liquidity-note").textContent = quoteConsensus ? "Order-book depth unavailable" : "Selected minus opposing liquidity";
    $("sharp-summary-flow-note").textContent = quoteConsensus ? "Awaiting exact liquidity" : "Directional liquidity signals";
    const requests = payload.provider?.metrics?.requests || 0;
    $("sharp-summary-requests").textContent = running ? `${requests} ${sourceName} requests this process` : "No requests while paused";
    $("sharp-signal-list").innerHTML = state.visible.length
      ? state.visible.map(signalCard).join("")
      : `<div class="sharp-empty-state"><div><i class="ph ${accessBlocked ? "ph-warning-circle" : running ? "ph-radar" : sourceConfigured ? "ph-pause-circle" : "ph-key"}"></i><strong>${accessBlocked ? advancedPlanRequired ? "Upgrade OddsEngine to Advanced" : standardOddsEngine ? "Price feed temporarily unavailable" : "Order-book feed unavailable" : running ? quoteConsensus ? "Exact liquidity unavailable" : `Waiting for exact ${sourceName} markets` : sourceConfigured ? "Sharp Money is paused" : "Connect a Sharp Money source"}</strong><span>${providerError || (running ? quoteConsensus ? "Exact prices are connected, but no direct NoVIG or ProphetX order-book match is available in this response." : "The first authenticated snapshot may take a few seconds." : sourceConfigured ? "Start the local feed when you want to inspect real markets." : "Credentials remain server-side and the integration is read-only.")}</span></div></div>`;
    const selected = state.visible.find(row => row.id === state.selectedId);
    $("sharp-detail-panel").innerHTML = selected
      ? detail(selected)
      : `<div class="sharp-detail-loading"><i class="ph ${accessBlocked ? "ph-warning-circle" : "ph-waveform"}"></i><strong>${accessBlocked ? advancedPlanRequired ? "Order-book access blocked" : standardOddsEngine ? "Price feed temporarily unavailable" : "Order-book feed unavailable" : quoteConsensus ? "Exact liquidity unavailable" : "No market selected"}</strong><span>${accessBlocked ? providerError : running ? quoteConsensus ? "Waiting for direct NoVIG or ProphetX order-book depth." : `Waiting for ${sourceName} market data.` : "Play the feed, then select a market."}</span></div>`;
  }

  async function load() {
    try {
      const response = await fetch("/api/sharp-money/live", { cache: "default", credentials: "same-origin" });
      if (!response.ok) throw new Error(`Sharp Money returned ${response.status}`);
      state.payload = await response.json();
      state.signals = Array.isArray(state.payload.signals) ? state.payload.signals : [];
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

  function renderSharpSportsbookFilter(query = "") {
    const list = $("sharp-sportsbook-list");
    if (!list) return;
    const needle = query.trim().toLowerCase();
    const books = sharpBookCatalog.filter(book => !needle || `${book.name} ${book.key} ${book.type}`.toLowerCase().includes(needle));
    list.innerHTML = books.map(book => `
      <label class="sharp-sportsbook-option">
        <input type="checkbox" value="${escapeHtml(book.key)}" ${state.filterDraftSportsbooks.has(book.key) ? "checked" : ""}>
        <span class="sharp-sportsbook-option-logo">${logo(book, String(book.name || "?").slice(0, 2))}</span>
        <span><strong>${escapeHtml(book.name)}</strong><small>${escapeHtml(book.type === "dfs" ? "DFS pick'em" : book.type === "exchange" ? "Exchange" : "Sportsbook")}</small></span>
      </label>`).join("");
    const count = $("sharp-sportsbook-count");
    if (count) count.textContent = `${state.filterDraftSportsbooks.size}/${sharpBookCatalog.length} selected`;
  }

  function openFilters(open) {
    if (open) {
      state.filterDraftSportsbooks = new Set(state.filters.sportsbooks);
      const search = $("sharp-sportsbook-search");
      if (search) search.value = "";
      renderSharpSportsbookFilter();
    }
    $("sharp-filter-drawer").hidden = !open;
    $("sharp-filter-backdrop").hidden = !open;
    document.body.style.overflow = open ? "hidden" : "";
  }

  function readFilters() {
    if (!state.filterDraftSportsbooks.size) {
      window.showToast?.("Select at least one sportsbook");
      return false;
    }
    state.filters.minimumLiquidity = Number($("sharp-liquidity-filter").value) || 0;
    state.filters.flow = $("sharp-flow-filter").value;
    state.filters.marketType = $("sharp-market-filter").value;
    state.filters.sportsbooks = new Set(state.filterDraftSportsbooks);
    localStorage.setItem(sharpBookFilterStorageKey, JSON.stringify([...state.filters.sportsbooks]));
    render();
    return true;
  }

  function bind() {
    const moreMenu = $("sharp-more-menu");
    const closeMoreMenu = () => {
      moreMenu.hidden = true;
      $("sharp-more").setAttribute("aria-expanded", "false");
    };
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
      if (event.target.closest(".sharp-card-add")) {
        event.stopPropagation();
        window.showToast?.("Selection added to your Sharp Money shortlist");
        return;
      }
      if (event.target.closest("a")) return;
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
    $("sharp-more")?.addEventListener("click", event => {
      event.stopPropagation();
      moreMenu.hidden = !moreMenu.hidden;
      $("sharp-more").setAttribute("aria-expanded", String(!moreMenu.hidden));
    });
    moreMenu.addEventListener("click", event => event.stopPropagation());
    document.addEventListener("click", closeMoreMenu);
    $("sharp-filter-close").addEventListener("click", () => openFilters(false));
    $("sharp-filter-backdrop").addEventListener("click", () => openFilters(false));
    $("sharp-filter-apply").addEventListener("click", () => { if (readFilters()) openFilters(false); });
    $("sharp-filter-reset").addEventListener("click", () => {
      $("sharp-liquidity-filter").value = "0";
      $("sharp-liquidity-value").textContent = "$0";
      $("sharp-flow-filter").value = "";
      $("sharp-market-filter").value = "";
      state.filterDraftSportsbooks = new Set(sharpBookKeys);
      const sportsbookSearch = $("sharp-sportsbook-search");
      if (sportsbookSearch) sportsbookSearch.value = "";
      renderSharpSportsbookFilter();
      readFilters();
    });
    $("sharp-sportsbooks-all")?.addEventListener("click", () => {
      state.filterDraftSportsbooks = new Set(sharpBookKeys);
      renderSharpSportsbookFilter($("sharp-sportsbook-search")?.value || "");
    });
    $("sharp-sportsbooks-none")?.addEventListener("click", () => {
      state.filterDraftSportsbooks.clear();
      renderSharpSportsbookFilter($("sharp-sportsbook-search")?.value || "");
    });
    $("sharp-sportsbook-search")?.addEventListener("input", event => renderSharpSportsbookFilter(event.target.value));
    $("sharp-sportsbook-list")?.addEventListener("change", event => {
      const input = event.target.closest('input[type="checkbox"]');
      if (!input) return;
      if (input.checked) state.filterDraftSportsbooks.add(input.value);
      else state.filterDraftSportsbooks.delete(input.value);
      const count = $("sharp-sportsbook-count");
      if (count) count.textContent = `${state.filterDraftSportsbooks.size}/${sharpBookCatalog.length} selected`;
    });
    $("sharp-liquidity-filter").addEventListener("input", event => { $("sharp-liquidity-value").textContent = money(event.target.value, false); });
    document.addEventListener("keydown", event => {
      if (event.key !== "Escape") return;
      closeMoreMenu();
      openFilters(false);
      $("sharp-detail-panel").classList.remove("mobile-open");
      document.body.classList.remove("sharp-detail-open");
    });
  }

  if (document.body.dataset.page === "sharp-money") {
    bind();
    load();
    window.setInterval(load, 30000);
  }
})();
