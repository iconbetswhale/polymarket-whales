(() => {
  const serverConfig = (() => {
    try { return JSON.parse(document.getElementById("ev-config")?.textContent || "{}"); }
    catch { return {}; }
  })();
  const catalog = Array.isArray(serverConfig.books) ? serverConfig.books : [];
  const devigCatalog = Array.isArray(serverConfig.devigBooks) ? serverConfig.devigBooks : [];
  const catalogVersion = Number(serverConfig.catalogVersion || 1);
  const marketGroups = {
    main: ["h2h", "spreads", "totals"],
    props: [
      "batter_hits", "batter_total_bases", "batter_home_runs", "batter_rbis",
      "batter_runs_scored", "pitcher_strikeouts", "pitcher_hits_allowed",
      "player_points", "player_rebounds", "player_assists", "player_threes",
      "player_points_rebounds_assists"
    ],
    alternate: ["alternate_spreads", "alternate_totals"]
  };
  const validMarketKeys = new Set(Object.values(marketGroups).flat());
  const validDevigMethods = new Set(["power", "additive", "multiplicative", "shin"]);
  const requiredBookCatalog = [...catalog].sort((left, right) => String(left.name || left.key).localeCompare(String(right.name || right.key)));
  const validRequiredBookKeys = new Set(requiredBookCatalog.map(book => book.key));
  const defaults = {
    group: "custom",
    markets: [...marketGroups.main],
    sports: ["baseball_mlb", "basketball_wnba"],
    books: catalog.filter(book => book.defaultExecution).map(book => book.key),
    minEv: 1,
    kelly: .25,
    minSources: 3,
    requiredBooks: [],
    devigMethod: "power",
    weights: Object.fromEntries(devigCatalog.map(book => [book.key, Number(book.weight || 0)])),
    catalogVersion
  };
  const bookNames = Object.fromEntries(catalog.map(book => [book.key, book.name]));
  const bookLogos = Object.fromEntries(catalog.map(book => [book.key, book.logoUrl || ""]));
  const trackedStorageKey = "iconlabs-ev-tracked-opportunities";
  const hiddenStorageKey = "iconlabs-ev-hidden-opportunities";
  let settings = {...defaults, weights:{...defaults.weights}, books:[...defaults.books], requiredBooks:[...defaults.requiredBooks], sports:[...defaults.sports], markets:[...defaults.markets]};
  try {
    const saved = JSON.parse(localStorage.getItem("iconlabs-ev-settings") || "{}");
    const {books, weights, markets, requiredBooks, catalogVersion: savedVersion, bankroll, maxQuoteAge, maxDispersion, maxStakePct, maxEventPct, ...rest} = saved;
    settings = {...settings, ...rest};
    if (!validDevigMethods.has(settings.devigMethod)) settings.devigMethod = defaults.devigMethod;
    settings.requiredBooks = Array.isArray(requiredBooks) ? [...new Set(requiredBooks.filter(key => validRequiredBookKeys.has(key)))] : [...defaults.requiredBooks];
    const legacyMarkets = saved.group && marketGroups[saved.group] ? marketGroups[saved.group] : defaults.markets;
    const savedMarkets = Array.isArray(markets) ? markets.filter(key => validMarketKeys.has(key)) : legacyMarkets;
    settings.markets = savedMarkets.length ? [...new Set(savedMarkets)] : [...defaults.markets];
    settings.group = "custom";
    if (Number(savedVersion) === catalogVersion) {
      settings.books = Array.isArray(books) ? books.filter(key => key in bookNames) : [...defaults.books];
      settings.weights = Object.fromEntries(devigCatalog.map(book => [book.key, Number(weights?.[book.key] ?? defaults.weights[book.key])]));
    }
  } catch {}
  let trackedIds = new Set();
  try {
    const savedTrackedIds = JSON.parse(localStorage.getItem(trackedStorageKey) || "[]");
    if (Array.isArray(savedTrackedIds)) trackedIds = new Set(savedTrackedIds.map(String));
  } catch {}
  let hiddenIds = new Set();
  try {
    const savedHiddenIds = JSON.parse(localStorage.getItem(hiddenStorageKey) || "[]");
    if (Array.isArray(savedHiddenIds)) hiddenIds = new Set(savedHiddenIds.map(String));
  } catch {}
  let rows = [], selectedId = "", paused = false, timer = null, feedView = "active";
  let trackerRowId = "", trackerSelectedTags = [], trackerOptions = null;
  let trackerConfirmation = {duplicate:false, conflict:false};
  let lastDetailTrigger = null, lastFilterTrigger = null;
  const previewOnly = Boolean(serverConfig.previewOnly);
  const $ = id => document.getElementById(id);
  const feed = $("ev-feed"), detail = $("ev-detail"), dialog = $("ev-filter-dialog"), scrim = $("ev-mobile-scrim");
  const trackerDialog = $("ev-tracker-dialog");
  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const weightsMatch = (left, right) => devigCatalog.every(book => Number(left?.[book.key] || 0) === Number(right?.[book.key] || 0));
  function updateAlgoSummary() {
    const isDefault = settings.devigMethod === defaults.devigMethod && weightsMatch(settings.weights, defaults.weights);
    $("ev-algo-summary").textContent = `${settings.devigMethod.charAt(0).toUpperCase()}${settings.devigMethod.slice(1)} · ${isDefault ? "IconLabs mix" : "custom mix"}`;
  }
  const teamBranding = Object.freeze({
    arizonadiamondbacks: {short:"Diamondbacks", logo:"/static/assets/teams/mlb/ari.png"},
    atlantabraves: {short:"Braves", logo:"/static/assets/teams/mlb/atl.png"},
    baltimoreorioles: {short:"Orioles", logo:"/static/assets/teams/mlb/bal.png"},
    bostonredsox: {short:"Red Sox", logo:"/static/assets/teams/mlb/bos.png"},
    chicagocubs: {short:"Cubs", logo:"/static/assets/teams/mlb/chc.png"},
    chicagowhitesox: {short:"White Sox", logo:"/static/assets/teams/mlb/chw.png"},
    cincinnatireds: {short:"Reds", logo:"/static/assets/teams/mlb/cin.png"},
    clevelandguardians: {short:"Guardians", logo:"/static/assets/teams/mlb/cle.png"},
    coloradorockies: {short:"Rockies", logo:"/static/assets/teams/mlb/col.png"},
    detroittigers: {short:"Tigers", logo:"/static/assets/teams/mlb/det.png"},
    houstonastros: {short:"Astros", logo:"/static/assets/teams/mlb/hou.png"},
    kansascityroyals: {short:"Royals", logo:"/static/assets/teams/mlb/kc.png"},
    losangelesangels: {short:"Angels", logo:"/static/assets/teams/mlb/laa.png"},
    losangelesdodgers: {short:"Dodgers", logo:"/static/assets/teams/mlb/lad.png"},
    miamimarlins: {short:"Marlins", logo:"/static/assets/teams/mlb/mia.png"},
    milwaukeebrewers: {short:"Brewers", logo:"/static/assets/teams/mlb/mil.png"},
    minnesotatwins: {short:"Twins", logo:"/static/assets/teams/mlb/min.png"},
    newyorkmets: {short:"Mets", logo:"/static/assets/teams/mlb/nym.png"},
    newyorkyankees: {short:"Yankees", logo:"/static/assets/teams/mlb/nyy.png"},
    athletics: {short:"Athletics", logo:"/static/assets/teams/mlb/oak.png"},
    oaklandathletics: {short:"Athletics", logo:"/static/assets/teams/mlb/oak.png"},
    philadelphiaphillies: {short:"Phillies", logo:"/static/assets/teams/mlb/phi.png"},
    pittsburghpirates: {short:"Pirates", logo:"/static/assets/teams/mlb/pit.png"},
    sandiegopadres: {short:"Padres", logo:"/static/assets/teams/mlb/sd.png"},
    sanfranciscogiants: {short:"Giants", logo:"/static/assets/teams/mlb/sf.png"},
    seattlemariners: {short:"Mariners", logo:"/static/assets/teams/mlb/sea.png"},
    stlouiscardinals: {short:"Cardinals", logo:"/static/assets/teams/mlb/stl.png"},
    tampabayrays: {short:"Rays", logo:"/static/assets/teams/mlb/tb.png"},
    texasrangers: {short:"Rangers", logo:"/static/assets/teams/mlb/tex.png"},
    torontobluejays: {short:"Blue Jays", logo:"/static/assets/teams/mlb/tor.png"},
    washingtonnationals: {short:"Nationals", logo:"/static/assets/teams/mlb/wsh.png"},
    atlantadream: {short:"Dream", logo:"/static/assets/teams/wnba/atl.png"},
    chicagosky: {short:"Sky", logo:"/static/assets/teams/wnba/chi.png"},
    connecticutsun: {short:"Sun", logo:"/static/assets/teams/wnba/connecticut.png"},
    dallaswings: {short:"Wings", logo:"/static/assets/teams/wnba/dal.png"},
    goldenstatevalkyries: {short:"Valkyries", logo:"/static/assets/teams/wnba/gs.png"},
    indianafever: {short:"Fever", logo:"/static/assets/teams/wnba/ind.png"},
    lasvegasaces: {short:"Aces", logo:"/static/assets/teams/wnba/lv.png"},
    losangelessparks: {short:"Sparks", logo:"/static/assets/teams/wnba/la.png"},
    minnesotalynx: {short:"Lynx", logo:"/static/assets/teams/wnba/min.png"},
    newyorkliberty: {short:"Liberty", logo:"/static/assets/teams/wnba/ny.png"},
    phoenixmercury: {short:"Mercury", logo:"/static/assets/teams/wnba/phx.png"},
    seattlestorm: {short:"Storm", logo:"/static/assets/teams/wnba/sea.png"},
    washingtonmystics: {short:"Mystics", logo:"/static/assets/teams/wnba/wsh.png"},
  });
  const canonicalTeam = value => String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
  const teamBrand = value => teamBranding[canonicalTeam(value)] || null;
  const matchup = row => {
    const label = String(row?.eventTitle ?? "").trim();
    const sides = label.match(/^(.*?)\s+vs\.?\s+(.*)$/i);
    if (!sides) return esc(label);
    const first = teamBrand(sides[1]), second = teamBrand(sides[2]);
    if (first?.logo && second?.logo) {
      return `<span class="ev-matchup-inline"><img class="ev-team-logo" src="${esc(first.logo)}" alt="" aria-hidden="true" decoding="async"><span class="ev-team-name">${esc(first.short)}</span><span class="ev-matchup-vs">vs</span><span class="ev-team-name">${esc(second.short)}</span><img class="ev-team-logo" src="${esc(second.logo)}" alt="" aria-hidden="true" decoding="async"></span>`;
    }
    return `<span class="ev-matchup-line">${esc(`${sides[1]} vs`)}</span><span class="ev-matchup-line">${esc(sides[2])}</span>`;
  };
  const sportIcon = row => {
    const sport = `${row?.sportKey || ""} ${row?.league || ""}`.toLowerCase();
    if (/baseball|mlb/.test(sport)) return "ph-baseball";
    if (/basketball|nba|wnba|ncaab/.test(sport)) return "ph-basketball";
    if (/tennis|atp|wta/.test(sport)) return "ph-tennis-ball";
    if (/football|nfl|ncaaf/.test(sport)) return "ph-football";
    if (/hockey|nhl/.test(sport)) return "ph-hockey";
    if (/soccer|epl|mls/.test(sport)) return "ph-soccer-ball";
    if (/golf|pga/.test(sport)) return "ph-golf";
    return "ph-trophy";
  };
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
  const leagueLogo = row => {
    const canonical = value => String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
    const league = canonical(row?.league);
    const sport = canonical(row?.sportKey);
    return leagueLogos[league] || leagueLogos[sport] || "";
  };
  const leagueWatermark = row => {
    const source = leagueLogo(row);
    return source ? `<img class="ev-league-watermark" src="${esc(source)}" alt="" aria-hidden="true">` : "";
  };
  const fullSelection = row => {
    const label = String(row?.line ?? row?.selection ?? "").trim();
    if (!/^(over|under)\b/i.test(label)) return label;
    const context = `${row?.marketLabel || ""} ${row?.marketKey || ""}`.toLowerCase();
    const league = `${row?.league || ""} ${row?.sportKey || ""}`.toLowerCase();
    const statUnits = [
      [/strikeouts?/, "Strikeouts"], [/rebounds?/, "Rebounds"],
      [/assists?/, "Assists"], [/three pointers?|threes?/, "Three-Pointers"],
      [/shots? on goal/, "Shots on Goal"], [/saves?/, "Saves"],
      [/player points?/, "Points"], [/hits?/, "Hits"], [/walks?/, "Walks"],
    ];
    let unit = statUnits.find(([pattern]) => pattern.test(context))?.[1] || "";
    if (!unit && /game total|totals?/.test(context)) {
      if (/mlb|baseball/.test(league)) unit = "Runs";
      else if (/nba|wnba|ncaab|basketball|nfl|ncaaf|football/.test(league)) unit = "Points";
      else if (/nhl|hockey|soccer/.test(league)) unit = "Goals";
      else if (/tennis|atp|wta/.test(league)) unit = "Games";
    }
    if (!unit || label.toLowerCase().includes(unit.toLowerCase())) return label;
    return `${label} ${unit}`;
  };
  const detailSelection = row => {
    const selection = fullSelection(row);
    const market = String(row?.marketLabel || "").trim();
    if (!market) return selection;
    if (!/^moneyline$/i.test(market)) return selection;
    return /\bML$/i.test(selection) ? selection : `${selection} ML`;
  };
  const marketSideSelection = (row, value) => {
    const selection = String(value || "").trim();
    const market = String(row?.marketLabel || "").trim();
    if (!/^player\b/i.test(market)) return selection;
    const outcome = selection.match(/\b(over|under)\s*([+-]?\d+(?:\.\d+)?)\b(?:\s+(.*))?$/i);
    if (!outcome) return selection;
    const stat = String(outcome[3] || market.replace(/^player\s*/i, "")).trim();
    const side = /^over$/i.test(outcome[1]) ? "O" : "U";
    return `${side}${outcome[2]}${stat ? ` ${stat}` : ""}`;
  };
  const money = value => `$${Number(value || 0).toLocaleString(undefined,{maximumFractionDigits:2})}`;
  const profitMoney = value => `$${Number(value || 0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
  const odds = value => `${Number(value) > 0 ? "+" : ""}${Number(value || 0)}`;
  const evPercent = value => `${Number(value) > 0 ? "+" : ""}${Number(value || 0).toFixed(2)}%`;
  const americanProfit = (stake, americanOdds) => {
    const amount = Math.max(0, Number(stake || 0));
    const price = Number(americanOdds || 0);
    if (!Number.isFinite(price) || price === 0) return 0;
    return price > 0 ? amount * price / 100 : amount * 100 / Math.abs(price);
  };
  const quotePayout = (stake, quote = {}) => {
    const amount = Math.max(0, Number(stake || 0));
    return amount + americanProfit(amount, quote.topPriceAmericanOdds ?? quote.americanOdds);
  };
  const time = value => { const date = new Date(value); return Number.isNaN(date.valueOf()) ? "" : date.toLocaleTimeString([],{hour:"numeric",minute:"2-digit"}); };
  const img = (url, name) => {
    const label = bookNames[name] || name || "Sportsbook";
    const source = bookLogos[name] || url || "";
    return source
      ? `<span class="ev-book-mark il-provider-logo"><img class="ev-book-logo" src="${esc(source)}" alt="${esc(label)} logo"><span class="ev-book-fallback" aria-hidden="true">${esc(label.slice(0, 1))}</span></span>`
      : `<span class="ev-book-mark il-provider-logo fallback" aria-label="${esc(label)}"><span class="ev-book-fallback" aria-hidden="true">${esc(label.slice(0, 1))}</span></span>`;
  };
  const statusLabel = row => row.portfolioStatus !== "qualified" ? "Suppressed" : row.executionStatus === "executable" ? "Executable" : "Verify liquidity";
  const chartPath = points => points.map((point, index) => `${index ? "L" : "M"}${point[0].toFixed(1)} ${point[1].toFixed(1)}`).join(" ");
  const stableSeed = value => [...String(value || "")].reduce((total, character) => total + character.charCodeAt(0), 0);

  function trackerSelectOptions(select, values, selectedValue = "", emptyLabel = null) {
    if (!select) return;
    const normalized = [...new Set((values || []).map(value => String(value || "").trim()).filter(Boolean))];
    const options = emptyLabel === null ? [] : [`<option value="">${esc(emptyLabel)}</option>`];
    options.push(...normalized.map(value => `<option value="${esc(value)}">${esc(value)}</option>`));
    select.innerHTML = options.join("");
    if (selectedValue && normalized.includes(selectedValue)) select.value = selectedValue;
  }

  function renderTrackerTags() {
    const selected = $("ev-tracker-selected-tags");
    const count = $("ev-tracker-tag-count");
    const existing = $("ev-tracker-existing-tag");
    if (!selected || !count || !existing) return;
    count.textContent = `${trackerSelectedTags.length} selected`;
    selected.innerHTML = trackerSelectedTags.length
      ? trackerSelectedTags.map(tag => `<button type="button" data-ev-remove-tag="${esc(tag)}" title="Remove ${esc(tag)}"><span>#${esc(tag)}</span><i class="ph ph-x" aria-hidden="true"></i></button>`).join("")
      : "<span>No tags selected</span>";
    const available = (trackerOptions?.tags || []).filter(tag => !trackerSelectedTags.some(selectedTag => selectedTag.toLowerCase() === String(tag).toLowerCase()));
    trackerSelectOptions(existing, available, "", "Select an existing tag");
  }

  function addTrackerTag(rawTag) {
    const tag = String(rawTag || "").trim().replace(/^#+/, "").replace(/\s+/g, " ");
    if (!tag || trackerSelectedTags.some(item => item.toLowerCase() === tag.toLowerCase())) return;
    if (tag.length > 32) { $("ev-tracker-error").textContent = "Tags must be 32 characters or fewer."; return; }
    if (trackerSelectedTags.length >= 8) { $("ev-tracker-error").textContent = "Choose no more than 8 tags per bet."; return; }
    trackerSelectedTags.push(tag);
    $("ev-tracker-error").textContent = "";
    renderTrackerTags();
  }

  async function loadTrackerOptions(preferredBook) {
    if (!trackerOptions) {
      try {
        const response = await fetch("/api/personal-tracker/options", {headers:{"Accept":"application/json"}});
        const payload = await response.json();
        if (response.ok) trackerOptions = payload.data || {};
      } catch {}
    }
    const catalogBooks = catalog.map(book => book.name).filter(Boolean);
    const savedBook = localStorage.getItem("iconbets-personal-sportsbook") || "";
    const selectedBook = preferredBook || savedBook || catalogBooks[0] || "Other";
    const choices = [selectedBook, ...(trackerOptions?.sportsbook_choices || []), ...catalogBooks];
    trackerSelectOptions($("ev-tracker-sportsbook"), choices, selectedBook);
    renderTrackerTags();
  }

  function updateTrackerTotal() {
    const price = Number($("ev-tracker-odds")?.value || 0);
    const stake = Math.max(0, Number($("ev-tracker-stake")?.value || 0));
    const fees = Math.max(0, Number($("ev-tracker-fees")?.value || 0));
    const toWin = americanProfit(stake, price);
    $("ev-tracker-total").innerHTML = `<span>Bet cost</span><strong>${profitMoney(stake)}</strong><small>To win ${profitMoney(toWin)} · Total payout ${profitMoney(stake + toWin)} · Total paid ${profitMoney(stake + fees)}</small>`;
  }

  function closeTracker() {
    if (trackerDialog?.open) trackerDialog.close();
    trackerRowId = "";
    trackerConfirmation = {duplicate:false, conflict:false};
  }

  function openTracker(row) {
    if (!trackerDialog || !row) return;
    const quote = row.bestQuote || {};
    const currentOdds = Number(quote.topPriceAmericanOdds ?? quote.americanOdds ?? 0);
    trackerRowId = String(row.id);
    trackerSelectedTags = [];
    trackerConfirmation = {duplicate:false, conflict:false};
    $("ev-tracker-summary").innerHTML = `
      <div><span>Event</span><strong>${esc(row.eventTitle)}</strong></div>
      <div><span>Selection</span><strong>${esc(row.selection)}</strong></div>
      <div><span>Recommendation</span><strong>${profitMoney(row.recommendedStake)}</strong></div>
      <div><span>Current odds</span><strong>${odds(currentOdds)}</strong></div>`;
    $("ev-tracker-odds").value = currentOdds || "";
    $("ev-tracker-stake").value = Number(row.recommendedStake || 0).toFixed(2);
    $("ev-tracker-fees").value = "0";
    $("ev-tracker-error").textContent = "";
    $("ev-tracker-exposure").hidden = true;
    $("ev-tracker-exposure").innerHTML = "";
    $("ev-tracker-submit").innerHTML = '<i class="ph ph-check" aria-hidden="true"></i>Track bet';
    $("ev-tracker-hide-submit").innerHTML = '<i class="ph ph-eye-slash" aria-hidden="true"></i>Track and Hide';
    loadTrackerOptions(quote.bookName || bookNames[quote.bookKey] || quote.bookKey);
    updateTrackerTotal();
    trackerDialog.showModal();
  }

  async function saveTrackedBet(event) {
    event.preventDefault();
    const row = rows.find(item => String(item.id) === trackerRowId);
    if (!row) return;
    const quote = row.bestQuote || {};
    const hideAfterSave = event.submitter?.id === "ev-tracker-hide-submit";
    const activeSubmit = event.submitter || $("ev-tracker-submit");
    const submitButtons = [...$("ev-tracker-form").querySelectorAll('button[type="submit"]')];
    submitButtons.forEach(button => { button.disabled = true; });
    $("ev-tracker-error").textContent = "";
    try {
      const response = await fetch("/api/positive-ev/personal-bets", {
        method: "POST",
        headers: {"Accept":"application/json", "Content-Type":"application/json"},
        body: JSON.stringify({
          source_id: row.id,
          event_title: row.eventTitle,
          market_title: row.marketLabel,
          selection: row.selection,
          event_start_time: row.commenceTime,
          sport_key: row.sportKey,
          league: row.league,
          market_key: row.marketKey,
          market_line: quote.point ?? row.line ?? null,
          canonical_event_id: row.eventId,
          american_odds: Number($("ev-tracker-odds").value),
          stake: Number($("ev-tracker-stake").value),
          fees: Number($("ev-tracker-fees").value || 0),
          sportsbook: $("ev-tracker-sportsbook").value,
          sportsbook_logo: quote.logoUrl || bookLogos[quote.bookKey] || "",
          market_url: /^https:\/\//.test(String(quote.deepLink || "")) ? quote.deepLink : "",
          ev_percent: row.evPercent,
          tags: trackerSelectedTags,
          hide_after_track: hideAfterSave,
          confirm_duplicate: trackerConfirmation.duplicate,
          confirm_conflict: trackerConfirmation.conflict,
        }),
      });
      const payload = await response.json();
      if (response.status === 409 && payload.confirmationRequired) {
        trackerConfirmation[payload.confirmationRequired] = true;
        const exposure = $("ev-tracker-exposure");
        exposure.hidden = false;
        exposure.className = `personal-exposure-notice ${payload.confirmationRequired === "conflict" ? "danger" : "caution"}`;
        exposure.innerHTML = `<i class="ph ph-warning" aria-hidden="true"></i><span><strong>${payload.confirmationRequired === "conflict" ? "Conflicting personal bet" : "Already tracked"}</strong>${esc(payload.error)}</span>`;
        activeSubmit.innerHTML = `<i class="ph ph-check" aria-hidden="true"></i>${hideAfterSave ? "Confirm and hide" : payload.confirmationRequired === "conflict" ? "Confirm opposing bet" : "Track another bet"}`;
        return;
      }
      if (!response.ok) throw new Error(payload.error || "Unable to track bet.");
      const id = String(row.id);
      trackedIds.add(id);
      localStorage.setItem(trackedStorageKey, JSON.stringify([...trackedIds]));
      localStorage.setItem("iconbets-personal-sportsbook", $("ev-tracker-sportsbook").value);
      closeTracker();
      if (hideAfterSave) hideOpportunity(id);
      else renderFeed();
    } catch (error) {
      $("ev-tracker-error").textContent = error.message;
    } finally {
      submitButtons.forEach(button => { button.disabled = false; });
    }
  }

  function hideOpportunity(id) {
    hiddenIds.add(String(id));
    localStorage.setItem(hiddenStorageKey, JSON.stringify([...hiddenIds]));
    const shown = visibleRows();
    if (String(selectedId) === String(id)) {
      if (shown.length) select(shown[0].id);
      else { selectedId = ""; renderFeed(); showDetailPlaceholder(); }
      return;
    }
    renderFeed();
  }

  function restoreOpportunity(id) {
    hiddenIds.delete(String(id));
    localStorage.setItem(hiddenStorageKey, JSON.stringify([...hiddenIds]));
    const shown = visibleRows();
    if (String(selectedId) === String(id)) {
      if (shown.length) select(shown[0].id);
      else { selectedId = ""; renderFeed(); showDetailPlaceholder(); }
      return;
    }
    renderFeed();
  }

  function marketTrendVisual(row) {
    const best = row.bestQuote || {};
    const currentOdds = Number(best.topPriceAmericanOdds ?? best.americanOdds ?? row.fairAmerican ?? 100);
    const fairOdds = Number(row.fairAmerican ?? currentOdds);
    const seed = stableSeed(row.id);
    const width = 520, height = 250, left = 46, right = 28, top = 34, bottom = 38;
    const count = 9;
    const series = [
      { key: "pinnacle", name: "Pinnacle", color: "#ff4fa0", end: fairOdds - 2, pattern: [12, 8, 5, 7, 2, 1, 3, 0, 0] },
      { key: "bookmaker", name: "BookMaker", color: "#f3c324", end: fairOdds + 1, pattern: [-8, -5, -5, -2, 1, -1, 2, 1, 0] },
      { key: "circa", name: "Circa", color: "#8b5cff", end: fairOdds - 5, pattern: [7, 4, 4, 1, 2, 0, 0, 0, 0] },
      { key: "selected", name: best.bookName || bookNames[best.bookKey] || "Selected book", color: "#19c6e8", end: currentOdds, pattern: [-15, -10, -4, -7, -1, 2, -2, 0, 0] }
    ];
    const allOdds = series.flatMap(item => item.pattern.map((delta, index) => item.end + delta + ((seed + index) % 3 - 1)));
    const minOdds = Math.min(...allOdds) - 8;
    const maxOdds = Math.max(...allOdds) + 8;
    const x = index => left + (index / (count - 1)) * (width - left - right);
    const y = value => top + ((maxOdds - value) / Math.max(1, maxOdds - minOdds)) * (height - top - bottom);
    const paths = series.map(item => {
      const points = item.pattern.map((delta, index) => [x(index), y(item.end + delta + ((seed + index) % 3 - 1))]);
      return `<g data-series="${item.key}"><path class="ev-trend-line" d="${chartPath(points)}" stroke="${item.color}"></path>${points.map(point=>`<circle cx="${point[0].toFixed(1)}" cy="${point[1].toFixed(1)}" r="2.5" fill="${item.color}"></circle>`).join("")}</g>`;
    }).join("");
    const limitValues = [350, 450, 700, 900, 1200, 1450, 1850, 2300, 2800];
    const limitY = value => top + ((3000 - value) / 3000) * (height - top - bottom);
    const limitPoints = limitValues.map((value,index)=>[x(index),limitY(value)]);
    const grid = [0,.25,.5,.75,1].map(ratio=>{
      const gridY=top+ratio*(height-top-bottom);
      const label=Math.round(maxOdds-ratio*(maxOdds-minOdds));
      return `<line x1="${left}" y1="${gridY}" x2="${width-right}" y2="${gridY}" class="ev-trend-grid"></line><text x="4" y="${gridY+4}" class="ev-trend-axis">${odds(label)}</text>`;
    }).join("");
    const historySeries = [
      { key: "history-pinnacle", name: "Pinnacle", color: "#ff4fa0", values: [fairOdds + 9, fairOdds + 2, fairOdds + 7, fairOdds - 1, fairOdds + 3, fairOdds + 3, fairOdds - 2, fairOdds - 2, fairOdds - 10] },
      { key: "history-bookmaker", name: "BookMaker", color: "#f3c324", values: [fairOdds + 13, fairOdds + 13, fairOdds + 5, fairOdds + 5, fairOdds + 5, fairOdds + 1, fairOdds + 1, fairOdds + 1, fairOdds - 3] },
      { key: "history-circa", name: "Circa", color: "#8b5cff", values: [fairOdds + 12, fairOdds + 12, fairOdds - 4, fairOdds + 4, fairOdds + 4, fairOdds + 4, fairOdds + 4, fairOdds + 1, fairOdds - 12] }
    ];
    const historyValues = historySeries.flatMap(item => item.values);
    const historyMin = Math.min(...historyValues) - 7;
    const historyMax = Math.max(...historyValues) + 7;
    const historyY = value => top + ((historyMax - value) / Math.max(1, historyMax - historyMin)) * (height - top - bottom);
    const historyPaths = historySeries.map(item => {
      const points = item.values.map((value, index) => [x(index), historyY(value)]);
      return `<g data-series="${item.key}"><path class="ev-trend-line ev-history-line" d="${chartPath(points)}" stroke="${item.color}"></path>${points.map(point=>`<circle cx="${point[0].toFixed(1)}" cy="${point[1].toFixed(1)}" r="2.4" fill="${item.color}"></circle>`).join("")}</g>`;
    }).join("");
    const historyGrid = [0,.25,.5,.75,1].map(ratio=>{
      const gridY=top+ratio*(height-top-bottom);
      const label=Math.round(historyMax-ratio*(historyMax-historyMin));
      return `<line x1="${left}" y1="${gridY}" x2="${width-right}" y2="${gridY}" class="ev-trend-grid"></line><text x="4" y="${gridY+4}" class="ev-trend-axis">${odds(label)}</text>`;
    }).join("");
    const legendButton = item => `<button type="button" class="ev-trend-legend-toggle" data-series-toggle="${item.key}" aria-pressed="true" style="--legend:${item.color}">${esc(item.name)}</button>`;
    return `<div class="ev-trend-chart il-chart-container" aria-label="Visual preview of market trend and line history charts">
      <div class="ev-trend-chart-head"><div class="ev-chart-tabs" role="tablist" aria-label="Chart view"><button type="button" class="active" role="tab" aria-selected="true" data-chart-tab="trend">Market Trend</button><button type="button" role="tab" aria-selected="false" data-chart-tab="history">Line History</button></div></div>
      <div class="ev-chart-view active" data-chart-view="trend">
        <div class="ev-trend-chart-title"><strong>${esc(row.selection)}</strong><span>${esc(row.eventTitle)}</span></div>
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Preview trend lines for selected book, Pinnacle, BookMaker, Circa, and Pinnacle limits">
          ${grid}<text x="${width-right-2}" y="${top+4}" text-anchor="end" class="ev-trend-limit-label">$3k</text><text x="${width-right-2}" y="${height-bottom+4}" text-anchor="end" class="ev-trend-limit-label">$0</text>
          ${paths}<g data-series="limits"><path class="ev-trend-limit" d="${chartPath(limitPoints)}"></path>${limitPoints.map(point=>`<circle cx="${point[0].toFixed(1)}" cy="${point[1].toFixed(1)}" r="2.4" fill="#f4f5f8"></circle>`).join("")}</g>
          <text x="${left}" y="${height-10}" class="ev-trend-axis">Open</text><text x="${width/2}" y="${height-10}" text-anchor="middle" class="ev-trend-axis">1h</text><text x="${width-right}" y="${height-10}" text-anchor="end" class="ev-trend-axis">Now</text>
        </svg>
        <div class="ev-trend-legend">${series.map(legendButton).join("")}${legendButton({key:"limits",name:"Pinnacle limits",color:"#f4f5f8"})}</div>
        <p class="ev-trend-preview-note"><i class="ph ph-eye"></i> Visual preview only. Historical movement and limits are collecting; current EV, FV, price, and stake use the selected opportunity.</p>
      </div>
      <div class="ev-chart-view" data-chart-view="history" hidden>
        <div class="ev-history-heading"><strong>${esc(row.marketLabel)} Line History</strong><span>${esc(row.eventTitle)}</span></div>
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Preview line history for Pinnacle, BookMaker, and Circa">
          ${historyGrid}${historyPaths}
          <text x="${left}" y="${height-10}" class="ev-trend-axis">Open</text><text x="${left+(width-left-right)/3}" y="${height-10}" text-anchor="middle" class="ev-trend-axis">12 AM</text><text x="${left+2*(width-left-right)/3}" y="${height-10}" text-anchor="middle" class="ev-trend-axis">6 AM</text><text x="${width-right}" y="${height-10}" text-anchor="end" class="ev-trend-axis ev-current-axis">Current</text>
        </svg>
        <div class="ev-trend-legend">${historySeries.map(legendButton).join("")}</div>
        <p class="ev-trend-preview-note"><i class="ph ph-eye"></i> Visual preview only. Historical book lines will populate here when the line-history feed is connected.</p>
      </div>
    </div>`;
  }

  function bindTrendControls() {
    const activateChartTab = button => {
      const mode = button.dataset.chartTab;
      detail.querySelectorAll("[data-chart-tab]").forEach(tab => {
        const active = tab.dataset.chartTab === mode;
        tab.classList.toggle("active", active);
        tab.setAttribute("aria-selected", String(active));
        tab.tabIndex = active ? 0 : -1;
      });
      detail.querySelectorAll("[data-chart-view]").forEach(view => {
        const active = view.dataset.chartView === mode;
        view.hidden = !active;
        view.classList.toggle("active", active);
      });
    };
    detail.querySelectorAll("[data-chart-tab]").forEach(button => {
      button.addEventListener("click", () => activateChartTab(button));
      button.addEventListener("keydown", event => {
        if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        event.preventDefault();
        const tabs = [...detail.querySelectorAll("[data-chart-tab]")];
        const offset = event.key === "ArrowRight" ? 1 : -1;
        const next = tabs[(tabs.indexOf(button) + offset + tabs.length) % tabs.length];
        activateChartTab(next);
        next.focus();
      });
    });
    detail.querySelectorAll("[data-series-toggle]").forEach(button => button.addEventListener("click", () => {
      const visible = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", String(visible));
      button.classList.toggle("off", !visible);
      const view = button.closest("[data-chart-view]");
      view?.querySelectorAll(`[data-series="${button.dataset.seriesToggle}"]`).forEach(series => series.classList.toggle("series-hidden", !visible));
    }));
  }

  function marketOddsVisual(row) {
    const suppliedSides = (row.marketSides || []).filter(side => side?.selection && side?.quotes?.length);
    const sides = suppliedSides.length >= 2
      ? suppliedSides.slice(0, 2)
      : [{selection: row.selection, quotes: row.quotes || []}];
    const sideMaps = sides.map(side => new Map(side.quotes.map(quote => [quote.bookKey, quote])));
    const sideLabels = sides.map(side => marketSideSelection(row, side.selection));
    const bookKeys = [...new Set(sides.flatMap(side => side.quotes.map(quote => quote.bookKey)))];
    if (!bookKeys.length) return "";
    const priceOf = quote => Number(quote?.topPriceAmericanOdds ?? quote?.americanOdds ?? -10000);
    bookKeys.sort((left, right) => priceOf(sideMaps[0].get(right)) - priceOf(sideMaps[0].get(left)));
    const bestBySide = sideMaps.map(sideMap => Math.max(...[...sideMap.values()].map(priceOf)));
    const detailText = quote => quote?.topPriceLiquidity != null
      ? `Liq ${money(quote.topPriceLiquidity)}`
      : quote?.marketLimit != null
        ? `Limit ${money(quote.marketLimit)}`
        : "";
    const priceCell = (quote, sideIndex) => {
      if (!quote) return `<span class="ev-compare-price unavailable" aria-label="No price available">—</span>`;
      const quoteOdds = priceOf(quote);
      const best = quoteOdds === bestBySide[sideIndex];
      const content = `<small>${esc(detailText(quote))}</small><strong>${odds(quoteOdds)}</strong><i class="ph ph-arrow-up-right"></i>`;
      return quote.deepLink && quote.deepLink !== "#"
        ? `<a class="ev-compare-price ${best ? "best" : ""}" href="${esc(quote.deepLink)}" target="_blank" rel="noopener" aria-label="Open ${esc(quote.bookName || bookNames[quote.bookKey] || quote.bookKey)} ${esc(sides[sideIndex].selection)} at ${odds(quoteOdds)}">${content}</a>`
        : `<span class="ev-compare-price ${best ? "best" : ""}">${content}</span>`;
    };
    const rowsHtml = bookKeys.map(bookKey => {
      const left = sideMaps[0].get(bookKey);
      const right = sideMaps[1]?.get(bookKey);
      const representative = left || right || {};
      const label = representative.bookName || bookNames[bookKey] || bookKey;
      return `<div class="ev-market-compare-row">
        ${priceCell(left, 0)}
        <span class="ev-market-book-center" title="${esc(label)}" aria-label="${esc(label)}">${img(representative.logoUrl, bookKey)}</span>
        ${sides.length > 1 ? priceCell(right, 1) : ""}
      </div>`;
    }).join("");
    return `<section class="ev-market-odds ev-market-comparison il-detail-section">
      <header><h3>MARKET ODDS</h3></header>
      <div class="ev-market-compare-head"><strong>${esc(sideLabels[0])}</strong><i class="ph ph-arrows-down-up" aria-hidden="true"></i>${sides.length > 1 ? `<strong>${esc(sideLabels[1])}</strong>` : ""}</div>
      <div class="ev-market-compare-rows">${rowsHtml}</div>
    </section>`;
  }

  function quoteAgeLabel(source) {
    const age = Number(source?.quoteAgeSeconds);
    if (Number.isFinite(age)) return age < 60 ? `${Math.round(age)}s old` : `${Math.round(age / 60)}m old`;
    return source?.lastUpdated ? `Updated ${time(source.lastUpdated)}` : "Timestamp unavailable";
  }

  function sharpBooksVisual(row) {
    const sources = (row.sourceBooks || []).filter(source => Number.isFinite(Number(source.americanOdds)));
    if (!sources.length) return "";
    return `<details class="ev-section ev-detail-accordion ev-sharp-prices il-detail-section">
      <summary><h3>SHARP ODDS USED FOR FAIR VALUE</h3><span>${sources.length} source${sources.length === 1 ? "" : "s"}</span><i class="ph ph-caret-down" aria-hidden="true"></i></summary>
      <div class="ev-sharp-price-list">${sources.map(source => `<div class="ev-sharp-price-row">
        <span class="ev-sharp-book">${img(source.logoUrl, source.bookKey)}<span><strong>${esc(source.bookName || bookNames[source.bookKey] || source.bookKey)}</strong><small>${esc(quoteAgeLabel(source))} · Configured ${Number(source.weight || 0)}%</small></span></span>
        <span class="ev-sharp-novig"><small>No-vig probability</small><b>${(Number(source.fairProbability || 0) * 100).toFixed(2)}%</b></span>
        <strong class="ev-sharp-odds">${odds(source.americanOdds)}</strong>
      </div>`).join("")}</div>
    </details>`;
  }

  function evExplanationVisual(row) {
    const best = row.bestQuote || {};
    const fairProbability = Number(row.fairProbability || 0);
    const effectiveDecimal = Number(best.effectiveDecimal || 0);
    const breakEvenProbability = effectiveDecimal > 1 ? 1 / effectiveDecimal : 0;
    const executionOdds = best.topPriceAmericanOdds ?? best.americanOdds;
    const book = best.bookName || bookNames[best.bookKey] || best.bookKey || "the selected sportsbook";
    return `<details class="ev-section ev-detail-accordion ev-value-explanation il-detail-section">
      <summary><h3>WHY IS THIS +EV?</h3><span>At ${esc(book)} ${odds(executionOdds)}</span><i class="ph ph-caret-down" aria-hidden="true"></i></summary>
      <div class="ev-value-copy">
        <p><strong>${evPercent(row.evPercent)} EV</strong> is the estimated long-run return at the displayed odds. A $100 wager has approximately <b>${money(Number(row.evPercent || 0))}</b> in theoretical expected profit—not guaranteed profit.</p>
        <p>The weighted de-vig blend prices this outcome at <b>${(fairProbability * 100).toFixed(2)}%</b> (${odds(row.fairAmerican)} fair odds), while the offered price requires <b>${(breakEvenProbability * 100).toFixed(2)}%</b> to break even after applicable fees.</p>
        <div class="ev-value-formula"><span>EV</span><code>(${(fairProbability * 100).toFixed(2)}% × ${effectiveDecimal.toFixed(3)}) − 1</code><strong>${evPercent(row.evPercent)}</strong></div>
      </div>
    </details>`;
  }

  function renderFilters() {
    document.querySelectorAll("[data-market-key]").forEach(input => input.checked = settings.markets.includes(input.dataset.marketKey));
    document.querySelectorAll('input[name="sports"]').forEach(input => input.checked = settings.sports.includes(input.value));
    document.querySelectorAll('input[name="devig-method"]').forEach(input => input.checked = input.value === settings.devigMethod);
    [["ev-min-ev","minEv"],["ev-kelly","kelly"],["ev-min-sources","minSources"]].forEach(([id,key]) => { if ($(id)) $(id).value = settings[key]; });
    $("ev-execution-books").innerHTML = Object.keys(bookNames).map(key => `<label><input type="checkbox" value="${key}" aria-label="${esc(bookNames[key])}" ${settings.books.includes(key)?"checked":""}><span class="ev-book-option">${img(bookLogos[key],key)}<span class="ev-book-name">${esc(bookNames[key])}</span></span></label>`).join("");
    $("ev-weight-list").innerHTML = devigCatalog.map(book => `<div class="ev-weight-row"><span class="ev-weight-book">${img(book.logoUrl || bookLogos[book.key], book.key)}<label for="weight-${book.key}">${esc(book.name || bookNames[book.key] || book.key)}</label></span><span class="ev-weight-input"><input id="weight-${book.key}" data-weight="${book.key}" type="number" min="0" max="100" step=".5" value="${Number(settings.weights[book.key] || 0)}"><b>%</b></span></div>`).join("");
    $("ev-required-books-list").innerHTML = requiredBookCatalog.map(book => `<label><span>${img(book.logoUrl || bookLogos[book.key], book.key)}</span><strong>${esc(book.name || bookNames[book.key] || book.key)}</strong><input type="checkbox" data-required-book="${esc(book.key)}" aria-label="Require ${esc(book.name || book.key)}" ${settings.requiredBooks.includes(book.key)?"checked":""}></label>`).join("");
    updateRequiredBooksSummary();
    updateFilterValidity();
  }
  function updateRequiredBooksSummary(){
    const selected = [...document.querySelectorAll("[data-required-book]:checked")].map(input => input.dataset.requiredBook);
    const summary = selected.length === 0
      ? "Any book"
      : selected.length === 1
        ? `${bookNames[selected[0]] || selected[0]} required`
        : `${selected.length} books required`;
    $("ev-required-books-summary").textContent = summary;
  }
  function updateWeightTotal(){
    const inputs = [...document.querySelectorAll("[data-weight]")];
    const values = inputs.map(input => Number(input.value));
    const total = values.reduce((sum, value) => sum + (Number.isFinite(value) ? value : 0), 0);
    const validValues = values.every(value => Number.isFinite(value) && value >= 0 && value <= 100);
    const valid = validValues && Math.abs(total - 100) < .000001;
    $("ev-weight-total").textContent = `${Number(total.toFixed(2))}%`;
    $("ev-weight-total").closest(".ev-weight-total").classList.toggle("invalid", !valid);
    $("ev-weight-error").textContent = valid ? "" : validValues ? "Allocate exactly 100% across the five sources." : "Every source must be between 0% and 100%.";
    return valid;
  }
  function updateMarketSummary(){
    const activeSports = new Set([...document.querySelectorAll('input[name="sports"]:checked')].map(input => input.value));
    const inputs = [...document.querySelectorAll("[data-market-key]")];
    inputs.forEach(input => {
      input.disabled = Boolean(input.dataset.marketSport && !activeSports.has(input.dataset.marketSport));
      input.closest("label")?.classList.toggle("disabled", input.disabled);
    });
    Object.entries(marketGroups).forEach(([group, keys]) => {
      const groupInputs = inputs.filter(input => keys.includes(input.dataset.marketKey) && !input.disabled);
      const selected = groupInputs.filter(input => input.checked).length;
      const counter = document.querySelector(`[data-market-group-count="${group}"]`);
      const toggle = document.querySelector(`[data-market-group-toggle="${group}"]`);
      if (counter) counter.textContent = `${selected}/${groupInputs.length}`;
      if (toggle) {
        toggle.checked = selected > 0;
        toggle.indeterminate = false;
        toggle.disabled = groupInputs.length === 0;
        toggle.closest("label")?.classList.toggle("disabled", toggle.disabled);
      }
    });
    const selectedCount = inputs.filter(input => input.checked && !input.disabled).length;
    $("ev-market-count").textContent = `${selectedCount} selected`;
    $("ev-market-error").textContent = selectedCount ? "" : "Select at least one market.";
    return selectedCount > 0;
  }
  function updateFilterValidity(){
    const weightValid = updateWeightTotal();
    const marketValid = updateMarketSummary();
    const valid = weightValid && marketValid;
    $("ev-apply").disabled = !valid;
    return valid;
  }
  function query() {
    const params = new URLSearchParams({group:"custom",markets:settings.markets.join(","),sports:settings.sports.join(","),books:settings.books.join(","),min_ev:settings.minEv,kelly:settings.kelly,min_sources:settings.minSources,required_books:settings.requiredBooks.join(","),devig_method:settings.devigMethod,weights:JSON.stringify(settings.weights)});
    if (previewOnly) {
      params.set("preview", "1");
      params.delete("markets");
      params.delete("sports");
    }
    return `/api/positive-ev?${params}`;
  }
  function renderDiagnostics(diagnostics = {}, history = {}) {
    const reasons = diagnostics.rejectionReasons || {};
    const topReason = Object.entries(reasons).sort((a,b)=>b[1]-a[1])[0];
    const bookClv = history.averageRespectiveBookClvPoints == null ? "collecting" : `${Number(history.averageRespectiveBookClvPoints) >= 0 ? "+" : ""}${Number(history.averageRespectiveBookClvPoints).toFixed(2)} pts`;
    const compositeClv = history.averageCompositeClvPoints == null ? "collecting" : `${Number(history.averageCompositeClvPoints) >= 0 ? "+" : ""}${Number(history.averageCompositeClvPoints).toFixed(2)} pts`;
    $("ev-credit-banner").innerHTML = `<i class="ph ph-shield-check" aria-hidden="true"></i><span><strong>${Number(diagnostics.qualified || 0)} executable</strong> · ${Number(diagnostics.watchOnly || 0)} watch-only · ${Number(diagnostics.rejected || 0)} rejected${topReason ? ` · most common: ${esc(topReason[0].replaceAll("_"," "))}` : ""}</span><span class="ev-history-stat">Tracked ${Number(history.opportunities || 0)} · book CLV ${bookClv} · composite ${compositeClv}</span><button class="button ghost compact" id="ev-adjust-filters" type="button">Adjust filters</button>`;
    $("ev-adjust-filters").addEventListener("click", openFilters);
  }
  async function load(force=false) {
    if (paused && !force) return;
    feed.setAttribute("aria-busy", "true");
    feed.innerHTML = `<div class="ev-loading il-state il-state-loading"><span></span><p>Validating exact markets and executable prices...</p></div>`;
    try {
      const response = await fetch(query(), {headers:{"Accept":"application/json"}});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Unable to load feed");
      if (payload.paused) {
        rows = [];
        selectedId = "";
        dismissDetail();
        clearTimeout(timer);
        timer = null;
        $("ev-count").textContent = "0";
        $("ev-updated").textContent = "Optimizer paused";
        $("ev-feed-label").textContent = "Credit-safe pause";
        $("ev-pause").setAttribute("aria-pressed", "true");
        $("ev-pause").innerHTML = '<i class="ph ph-play"></i>';
        $("ev-credit-banner").innerHTML = `<i class="ph ph-shield-check" aria-hidden="true"></i><span><strong>EV optimizer paused</strong> · No paid odds requests or refreshes are running.</span>`;
        feed.innerHTML = `<div class="ev-empty il-state il-state-empty"><i class="ph ph-pause-circle" aria-hidden="true"></i><p>${esc(payload.message || "Positive EV scanning is paused.")}</p></div>`;
        feed.setAttribute("aria-busy", "false");
        return;
      }
      rows = payload.data || [];
      $("ev-count").textContent = rows.length;
      $("ev-updated").textContent = `Updated ${new Date().toLocaleTimeString([],{hour:"numeric",minute:"2-digit",second:"2-digit"})}`;
      let history = {};
      if (!payload.previewOnly) {
        try { history = (await (await fetch("/api/positive-ev/history?limit=100")).json()).summary || {}; } catch {}
        renderDiagnostics(payload.diagnostics || {}, history);
      } else {
        const previewCount = Number(payload.total || payload.data?.length || 0);
        $("ev-credit-banner").innerHTML = `<i class="ph ph-eye" aria-hidden="true"></i><span><strong>${previewCount} temporary preview plays</strong> · Visual fixtures only · tracking requires confirmation and saves only to your personal trackers.</span>`;
      }
      const currentViewRows = visibleRows();
      const nextSelectedId = currentViewRows.some(row=>row.id===selectedId) ? selectedId : currentViewRows[0]?.id;
      if (nextSelectedId) select(nextSelectedId);
      else { selectedId = ""; renderFeed(); showDetailPlaceholder(); }
      feed.setAttribute("aria-busy", "false");
      clearTimeout(timer);
      if (!payload.previewOnly && Number(payload.refreshSeconds) > 0) timer = setTimeout(load, Number(payload.refreshSeconds) * 1000);
    } catch (error) {
      feed.innerHTML = `<div class="ev-empty il-state il-state-error"><i class="ph ph-warning-circle" aria-hidden="true"></i><p>${esc(error.message)}</p></div>`;
      feed.setAttribute("aria-busy", "false");
    }
  }
  function visibleRows() {
    const search = $("ev-search").value.trim().toLowerCase();
    return rows.filter(row => {
      const isHidden = hiddenIds.has(String(row.id));
      const matchesView = feedView === "hidden" ? isHidden : !isHidden;
      return matchesView && (!search || `${row.eventTitle} ${row.selection} ${row.marketLabel} ${row.league}`.toLowerCase().includes(search));
    });
  }
  function updateHiddenMenu() {
    const hiddenCount = rows.filter(row => hiddenIds.has(String(row.id))).length;
    $("ev-hidden-count").textContent = hiddenCount;
    $("ev-visible-count").textContent = Math.max(0, rows.length - hiddenCount);
    document.querySelectorAll("[data-feed-view]").forEach(button => button.setAttribute("aria-current", String(button.dataset.feedView === feedView)));
    $("ev-hidden-menu-toggle").setAttribute("aria-pressed", String(feedView === "hidden"));
    $("ev-feed-label").textContent = feedView === "hidden" ? "Manually hidden bets" : paused ? "Refresh paused" : "Live market scan";
  }
  function closeHiddenMenu(restoreFocus = false) {
    const menu = $("ev-hidden-menu");
    menu.hidden = true;
    $("ev-hidden-menu-toggle").setAttribute("aria-expanded", "false");
    if (restoreFocus) $("ev-hidden-menu-toggle").focus();
  }
  function setFeedView(nextView) {
    feedView = nextView === "hidden" ? "hidden" : "active";
    closeHiddenMenu();
    const shown = visibleRows();
    if (shown.length) select(shown[0].id);
    else { selectedId = ""; renderFeed(); showDetailPlaceholder(); }
  }
  function renderFeed() {
    const shown = visibleRows();
    updateHiddenMenu();
    $("ev-count").textContent = shown.length;
    if (!shown.length) {
      const emptyIcon = feedView === "hidden" ? "ph-eye-slash" : "ph-shield-check";
      const emptyCopy = feedView === "hidden" ? "No hidden bets yet. Use Track and Hide on a bet to save it here." : "No opportunity passed every validation gate. That is safer than displaying a false edge.";
      feed.innerHTML = `<div class="ev-empty il-state il-state-empty"><i class="ph ${emptyIcon}" aria-hidden="true"></i><p>${emptyCopy}</p></div>`;
      return;
    }
    feed.innerHTML = shown.map(row => {
      const quote=row.bestQuote||{}, state = row.executionStatus === "executable" && row.portfolioStatus === "qualified" ? "executable" : "watch";
      const tracked = trackedIds.has(String(row.id));
      const totalPayout = quotePayout(row.recommendedStake, quote);
      const scoreAction = feedView === "hidden"
        ? `<button class="ev-track-button button ghost compact" type="button" data-restore="${esc(row.id)}" aria-label="Restore ${esc(row.selection)} to visible bets"><i class="ph ph-eye" aria-hidden="true"></i>Restore</button>`
        : `<button class="ev-track-button button ghost compact ${tracked?"tracked":""}" type="button" data-track="${esc(row.id)}" aria-pressed="${tracked}" aria-label="${tracked?"Track another bet on":"Track"} ${esc(row.selection)}"><i class="ph ${tracked?"ph-check":"ph-crosshair"}" aria-hidden="true"></i>${tracked?"Tracked":"Track"}</button>`;
      return `<article class="ev-opportunity ${row.id===selectedId?"active":""} ${state}" data-id="${esc(row.id)}">
        <button class="ev-card-open" type="button" data-open="${esc(row.id)}" aria-label="Open ${esc(row.selection)} at ${odds(quote.topPriceAmericanOdds??quote.americanOdds)}, ${evPercent(row.evPercent)} EV" aria-pressed="${row.id===selectedId}"></button>
        <div class="ev-score il-confidence-display"><span class="ev-score-values"><strong>${evPercent(row.evPercent)}</strong><small>Algo odds ${odds(row.fairAmerican)}</small></span>${scoreAction}</div>
        <div class="ev-event"><time>${esc(time(row.commenceTime))}</time><strong class="ev-matchup" aria-label="${esc(row.eventTitle)}">${matchup(row)}</strong></div>
        <div class="ev-pick">${leagueWatermark(row)}<small><i class="ph ${sportIcon(row)}" aria-hidden="true"></i>${esc(row.league)}</small><strong>${esc(row.marketLabel)}</strong></div>
        <div class="ev-execution"><div class="ev-selection">${esc(fullSelection(row))}</div><div class="ev-bet-metrics"><span class="ev-bet-metric"><small>Rec Bet</small><strong>${money(row.recommendedStake)}</strong></span><span class="ev-bet-metric ev-to-win"><small>Total payout</small><strong>${profitMoney(totalPayout)}</strong></span></div><a class="ev-best-button il-executable-quote ${state}" href="${esc(quote.deepLink||"#")}" target="_blank" rel="noopener" aria-label="Open ${esc(quote.bookName||quote.bookKey)} at ${odds(quote.topPriceAmericanOdds??quote.americanOdds)}">${img(quote.logoUrl,quote.bookKey)}<span>${odds(quote.topPriceAmericanOdds??quote.americanOdds)}<i class="ph ph-arrow-up-right" aria-hidden="true"></i></span></a></div>
      </article>`;
    }).join("");
    feed.querySelectorAll("[data-open]").forEach(button => button.addEventListener("click", () => {
      lastDetailTrigger = button;
      select(button.dataset.open);
    }));
    feed.querySelectorAll("[data-track]").forEach(button => button.addEventListener("click", event => {
      event.stopPropagation();
      const id = String(button.dataset.track || "");
      if (!id) return;
      openTracker(rows.find(row => String(row.id) === id));
    }));
    feed.querySelectorAll("[data-restore]").forEach(button => button.addEventListener("click", event => {
      event.stopPropagation();
      restoreOpportunity(button.dataset.restore);
    }));
  }
  function showDetailPlaceholder() {
    const isHiddenView = feedView === "hidden";
    detail.innerHTML = `<div class="ev-detail-empty il-state il-state-empty">
      <i class="ph ${isHiddenView ? "ph-eye-slash" : "ph-chart-line-up"}" aria-hidden="true"></i>
      <h2>${isHiddenView ? "No hidden bet selected" : "Select an opportunity"}</h2>
      <p>${isHiddenView ? "Hidden bets will appear here after you use Track and Hide." : "Inspect the fair price, EV calculation, best execution, liquidity, and the full market."}</p>
    </div>`;
    dismissDetail();
  }
  function select(id) {
    selectedId=id; const row=rows.find(item=>item.id===id); if(!row)return;
    renderFeed(); const best=row.bestQuote||{};
    detail.innerHTML = `<article class="ev-detail-card ev-trend-detail"><div class="ev-detail-head"><strong>${evPercent(row.evPercent)}</strong><div><h2>${esc(row.eventTitle)}</h2><time class="ev-detail-start" datetime="${esc(row.commenceTime)}">${esc(time(row.commenceTime))}</time></div><button class="ev-detail-close icon-button" type="button" aria-label="Close detail"><i class="ph ph-x" aria-hidden="true"></i></button></div>
      <div class="ev-detail-pick ev-trend-pick"><strong>${esc(detailSelection(row))} <span>${odds(best.topPriceAmericanOdds??best.americanOdds)}</span></strong><div class="ev-detail-stake">${money(row.recommendedStake)}</div></div>
      ${row.warnings.length ? `<div class="ev-warning-list">${row.warnings.map(warning=>`<span><i class="ph ph-warning"></i>${esc(warning)}</span>`).join("")}</div>` : ""}
      ${marketOddsVisual(row)}
      <section class="ev-section ev-market-trend il-detail-section"><header><h3>MARKET TREND</h3></header><div class="ev-trend-metrics il-metric-group">
        <span class="il-metric positive"><small>EV</small><b>${evPercent(row.evPercent)}</b></span>
        <span class="il-metric"><small>FV</small><b>${odds(row.fairAmerican)}</b></span>
        <span class="il-metric"><small>1H</small><b>--</b></span>
        <span class="il-metric"><small>OPEN</small><b>--</b></span>
      </div>${marketTrendVisual(row)}</section>
      ${evExplanationVisual(row)}${sharpBooksVisual(row)}
    </article>`;
    bindTrendControls();
    detail.querySelector(".ev-detail-close").addEventListener("click", closeDetail);
    detail.classList.add("open");
    detail.closest(".ev-workspace")?.classList.add("detail-open");
    detail.removeAttribute("inert");
    detail.setAttribute("aria-hidden", "false");
    if (matchMedia("(max-width:980px)").matches) {
      scrim.hidden=false;
      detail.setAttribute("role", "dialog");
      detail.setAttribute("aria-modal", "true");
      requestAnimationFrame(() => detail.querySelector(".ev-detail-close")?.focus());
    } else {
      detail.removeAttribute("role");
      detail.removeAttribute("aria-modal");
    }
  }
  function dismissDetail(restoreFocus=false){
    detail.classList.remove("open");
    detail.closest(".ev-workspace")?.classList.remove("detail-open");
    scrim.hidden=true;
    if (matchMedia("(max-width:980px)").matches) {
      detail.setAttribute("aria-hidden", "true");
      detail.setAttribute("inert", "");
      detail.removeAttribute("role");
      detail.removeAttribute("aria-modal");
      if (restoreFocus) requestAnimationFrame(() => {
        const trigger = lastDetailTrigger?.isConnected
          ? lastDetailTrigger
          : feed.querySelector(`[data-open="${CSS.escape(String(selectedId))}"]`);
        trigger?.focus();
      });
    }
  }
  function closeDetail(){
    if (matchMedia("(min-width:981px)").matches && rows.length) {
      if (!detail.classList.contains("open")) select(rows.some(row=>row.id===selectedId) ? selectedId : rows[0].id);
      return;
    }
    dismissDetail(true);
  }
  function syncSearchSelection(){
    const shown = visibleRows();
    if (shown.length && !shown.some(row=>row.id===selectedId)) select(shown[0].id);
    else renderFeed();
  }
  function openFilters(event){
    lastFilterTrigger = event?.currentTarget || document.activeElement;
    renderFilters();
    dialog.showModal();
    requestAnimationFrame(() => $("ev-filter-close")?.focus());
  }
  function activateFilterPanel(panel) {
    dialog.querySelectorAll("[data-panel], [data-filter-panel]").forEach(item => item.classList.remove("active"));
    dialog.querySelector(`[data-panel="${panel}"]`)?.classList.add("active");
    dialog.querySelector(`[data-filter-panel="${panel}"]`)?.classList.add("active");
  }
  function openAlgoSettings(event) {
    lastFilterTrigger = event?.currentTarget || document.activeElement;
    renderFilters();
    activateFilterPanel("devig");
    dialog.showModal();
    requestAnimationFrame(() => $("ev-algo-defaults")?.focus());
  }
  function applyFilters(){
    if (!updateFilterValidity()) return;
    settings.group="custom";
    settings.markets=[...document.querySelectorAll("[data-market-key]:checked:not(:disabled)")].map(input=>input.dataset.marketKey);
    settings.sports=[...document.querySelectorAll('input[name="sports"]:checked')].map(i=>i.value);
    settings.books=[...$("ev-execution-books").querySelectorAll("input:checked")].map(i=>i.value);
    settings.requiredBooks=[...document.querySelectorAll("[data-required-book]:checked")].map(i=>i.dataset.requiredBook);
    settings.devigMethod=document.querySelector('input[name="devig-method"]:checked')?.value || defaults.devigMethod;
    [["ev-min-ev","minEv"],["ev-kelly","kelly"],["ev-min-sources","minSources"]].forEach(([id,key]) => settings[key]=Number($(id).value || defaults[key]));
    settings.weights=Object.fromEntries([...document.querySelectorAll("[data-weight]")].map(i=>[i.dataset.weight,Number(i.value||0)]));
    settings.catalogVersion = catalogVersion;
    localStorage.setItem("iconlabs-ev-settings",JSON.stringify(settings));updateAlgoSummary();dialog.close();load(true);
  }
  updateAlgoSummary();
  $("ev-filter-open").addEventListener("click",openFilters);$("ev-algo-open").addEventListener("click",openAlgoSettings);$("ev-adjust-filters").addEventListener("click",openFilters);$("ev-filter-close").addEventListener("click",()=>dialog.close());$("ev-apply").addEventListener("click",applyFilters);
  $("ev-algo-defaults").addEventListener("click",()=>{document.querySelector('input[name="devig-method"][value="power"]').checked=true;document.querySelectorAll("[data-weight]").forEach(input=>{input.value=String(defaults.weights[input.dataset.weight]||0);});updateFilterValidity();});
  $("ev-reset").addEventListener("click",()=>{settings={...defaults,weights:{...defaults.weights},books:[...defaults.books],requiredBooks:[...defaults.requiredBooks],sports:[...defaults.sports],markets:[...defaults.markets]};renderFilters();});
  $("ev-required-books-clear").addEventListener("click",()=>{document.querySelectorAll("[data-required-book]").forEach(input=>input.checked=false);updateRequiredBooksSummary();});
  $("ev-refresh").addEventListener("click",()=>load(true));$("ev-search").addEventListener("input",syncSearchSelection);scrim.addEventListener("click",closeDetail);
  $("ev-hidden-menu-toggle").addEventListener("click", event => {
    event.stopPropagation();
    const menu = $("ev-hidden-menu");
    menu.hidden = !menu.hidden;
    $("ev-hidden-menu-toggle").setAttribute("aria-expanded", String(!menu.hidden));
    if (!menu.hidden) requestAnimationFrame(() => menu.querySelector('[aria-current="true"]')?.focus());
  });
  $("ev-hidden-menu").addEventListener("click", event => {
    const option = event.target.closest("[data-feed-view]");
    if (option) setFeedView(option.dataset.feedView);
  });
  document.addEventListener("click", event => { if (!event.target.closest(".ev-hidden-menu-wrap")) closeHiddenMenu(); });
  document.addEventListener("keydown", event => { if (event.key === "Escape" && !$("ev-hidden-menu").hidden) { event.preventDefault(); closeHiddenMenu(true); } });
  $("ev-pause").addEventListener("click",()=>{paused=!paused;$("ev-pause").setAttribute("aria-pressed",String(paused));$("ev-pause").innerHTML=`<i class="ph ph-${paused?"play":"pause"}"></i>`;updateHiddenMenu();if(!paused)load(true);});
  dialog.querySelectorAll("[data-panel]").forEach(button=>button.addEventListener("click",()=>activateFilterPanel(button.dataset.panel)));
  dialog.addEventListener("input",event=>{
    if(event.target.matches("[data-market-group-toggle]")){
      const keys = marketGroups[event.target.dataset.marketGroupToggle] || [];
      document.querySelectorAll("[data-market-key]").forEach(input=>{
        if(keys.includes(input.dataset.marketKey) && !input.disabled) input.checked=event.target.checked;
      });
      updateFilterValidity();
      return;
    }
    if(event.target.matches("[data-required-book]"))updateRequiredBooksSummary();
    if(event.target.matches("[data-weight], [data-market-key], input[name=\"sports\"]"))updateFilterValidity();
  });
  dialog.addEventListener("click",event=>{
    if(event.target.closest(".ev-market-group-toggle")){
      event.stopPropagation();
    }
    // Keep dismissal explicit through the close button or Escape. Chromium can
    // retarget clicks inside a scrolled native dialog to the dialog itself,
    // which previously closed the filter while users toggled sportsbook cards.
  });
  dialog.addEventListener("keydown",event=>{if(event.key==="Escape"){event.preventDefault();dialog.close();}});
  dialog.addEventListener("close",()=>{if(lastFilterTrigger?.isConnected)requestAnimationFrame(()=>lastFilterTrigger.focus());});
  detail.addEventListener("keydown",event=>{
    if(!matchMedia("(max-width:980px)").matches||!detail.classList.contains("open"))return;
    if(event.key==="Escape"){
      event.preventDefault();
      dismissDetail(true);
      return;
    }
    if(event.key!=="Tab")return;
    const focusable=[...detail.querySelectorAll('button:not([disabled]),a[href],[tabindex]:not([tabindex="-1"])')].filter(element=>!element.hidden&&element.getClientRects().length);
    if(!focusable.length)return;
    const first=focusable[0],last=focusable[focusable.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  });
  $("ev-tracker-close")?.addEventListener("click", closeTracker);
  $("ev-tracker-dismiss")?.addEventListener("click", closeTracker);
  $("ev-tracker-form")?.addEventListener("submit", saveTrackedBet);
  trackerDialog?.addEventListener("click", event => { if (event.target === trackerDialog) closeTracker(); });
  trackerDialog?.addEventListener("keydown", event => { if (event.key === "Escape") { event.preventDefault(); closeTracker(); } });
  trackerDialog?.addEventListener("input", event => {
    if (event.target.matches("#ev-tracker-odds, #ev-tracker-stake, #ev-tracker-fees")) updateTrackerTotal();
  });
  $("ev-tracker-add-tag")?.addEventListener("click", () => {
    addTrackerTag($("ev-tracker-new-tag").value);
    $("ev-tracker-new-tag").value = "";
  });
  $("ev-tracker-existing-tag")?.addEventListener("change", event => { addTrackerTag(event.target.value); event.target.value = ""; });
  $("ev-tracker-selected-tags")?.addEventListener("click", event => {
    const button = event.target.closest("[data-ev-remove-tag]");
    if (!button) return;
    trackerSelectedTags = trackerSelectedTags.filter(tag => tag !== button.dataset.evRemoveTag);
    renderTrackerTags();
  });
  document.addEventListener("error",event=>{if(event.target.matches(".ev-book-logo")){event.target.hidden=true;event.target.parentElement.classList.add("fallback");}},true);
  renderFilters(); load(true);
})();
