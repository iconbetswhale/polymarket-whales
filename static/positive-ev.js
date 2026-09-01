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
      "batter_first_home_run", "batter_runs_scored", "batter_hits_runs_rbis",
      "batter_runs_rbis",
      "batter_singles", "batter_doubles", "batter_triples", "batter_walks",
      "batter_strikeouts", "batter_stolen_bases", "pitcher_strikeouts",
      "pitcher_hits_allowed", "pitcher_walks", "pitcher_earned_runs",
      "pitcher_outs", "pitcher_pitches_thrown", "pitcher_record_a_win",
      "player_points", "player_points_q1", "player_rebounds",
      "player_rebounds_q1", "player_assists", "player_assists_q1",
      "player_threes", "player_blocks", "player_steals", "player_blocks_steals",
      "player_turnovers", "player_points_rebounds_assists",
      "player_points_rebounds", "player_points_assists", "player_rebounds_assists",
      "player_field_goals", "player_field_goals_attempted", "player_frees_made",
      "player_frees_attempts",
      "player_first_basket", "player_double_double", "player_triple_double"
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
    sports: Array.isArray(serverConfig.sports) && serverConfig.sports.length
      ? serverConfig.sports.map(sport => sport.key).filter(Boolean)
      : ["baseball_mlb", "basketball_nba", "basketball_wnba"],
    books: catalog.filter(book => book.defaultExecution).map(book => book.key),
    minEv: 1,
    kelly: .25,
    minSources: 3,
    requiredBooks: [],
    devigMethod: "power",
    weights: Object.fromEntries(devigCatalog.map(book => [book.key, Number(book.weight || 0)])),
    catalogVersion,
    settingsVersion: 4
  };
  const bookNames = Object.fromEntries(catalog.map(book => [book.key, book.name]));
  const bookLogos = Object.fromEntries(catalog.map(book => [book.key, book.logoUrl || ""]));
  const trackedStorageKey = "iconlabs-ev-tracked-opportunities";
  const hiddenStorageKey = "iconlabs-ev-hidden-opportunities";
  let settings = {...defaults, weights:{...defaults.weights}, books:[...defaults.books], requiredBooks:[...defaults.requiredBooks], sports:[...defaults.sports], markets:[...defaults.markets]};
  try {
    const saved = JSON.parse(localStorage.getItem("iconlabs-ev-settings") || "{}");
    const {books, weights, markets, requiredBooks, catalogVersion: savedVersion, bankroll, maxQuoteAge, maxDispersion, maxStakePct, maxEventPct, ...rest} = saved;
    const migrated = {...rest};
    if (Number(saved.settingsVersion) !== defaults.settingsVersion) {
      delete migrated.minSources;
      delete migrated.sports;
    }
    settings = {...settings, ...migrated};
    if (!validDevigMethods.has(settings.devigMethod)) settings.devigMethod = defaults.devigMethod;
    settings.minSources = Math.max(3, Math.min(5, Number(settings.minSources || defaults.minSources)));
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
  let rows = [], selectedId = "", paused = false, timer = null, feedView = "active", retryCount = 0;
  let lineHistoryRequestId = 0;
  let lineHistoryMetricMode = "auto";
  let bankrollConfig = {amount:10000, unitPercentage:.01, settingsVersion:null, dirty:false, savePending:false};
  let trackerRowId = "", trackerSelectedTags = [], trackerOptions = null;
  let trackerConfirmation = {duplicate:false, conflict:false};
  let lastDetailTrigger = null, lastFilterTrigger = null;
  const $ = id => document.getElementById(id);
  const feed = $("ev-feed"), detail = $("ev-detail"), dialog = $("ev-filter-dialog"), scrim = $("ev-mobile-scrim");
  const trackerDialog = $("ev-tracker-dialog");
  const mobileInfo = $("ev-mobile-info"), mobileInfoViewport = matchMedia("(max-width:760px)");
  const syncMobileInfo = () => {
    if (!mobileInfo) return;
    mobileInfo.open = !mobileInfoViewport.matches;
    mobileInfo.dataset.mobileReady = "true";
  };
  mobileInfoViewport.addEventListener?.("change", syncMobileInfo);
  syncMobileInfo();
  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
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
  const sameValues = (left, right) => JSON.stringify([...left].sort()) === JSON.stringify([...right].sort());
  async function requestJson(url, options={}) {
    const response = await fetch(url, {...options,headers:{"Accept":"application/json","Content-Type":"application/json",...(options.headers||{})}});
    const payload = await response.json().catch(()=>({}));
    if (!response.ok) {
      const error = new Error(payload.error || payload.message || `Request failed (${response.status})`);
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  }
  function updateToolbarFilterCount() {
    const changed = [
      !sameValues(settings.markets, defaults.markets),
      !sameValues(settings.sports, defaults.sports),
      !sameValues(settings.books, defaults.books),
      settings.requiredBooks.length > 0,
      settings.devigMethod !== defaults.devigMethod || JSON.stringify(settings.weights) !== JSON.stringify(defaults.weights),
      Number(settings.minEv) !== Number(defaults.minEv) || Number(settings.kelly) !== Number(defaults.kelly) || Number(settings.minSources) !== Number(defaults.minSources),
    ].filter(Boolean).length;
    const badge = $("ev-active-filter-count");
    badge.textContent = String(changed);
    badge.setAttribute("aria-label", `${changed} customized filter group${changed === 1 ? "" : "s"}`);
  }
  function setToolbarPopover(buttonId, panelId, expanded) {
    const button = $(buttonId), panel = $(panelId);
    if (!button || !panel) return;
    panel.hidden = !expanded;
    button.setAttribute("aria-expanded", String(expanded));
  }
  function applyBankrollSettings(accountSettings, {forceInput=false}={}) {
    const amount = Number(accountSettings?.trades_to_play_bankroll ?? accountSettings?.starting_bankroll ?? bankrollConfig.amount);
    const unitPercentage = Number(accountSettings?.unit_percentage ?? bankrollConfig.unitPercentage);
    if (Number.isFinite(amount) && amount > 0) bankrollConfig.amount = amount;
    if (Number.isFinite(unitPercentage) && unitPercentage > 0) bankrollConfig.unitPercentage = unitPercentage;
    bankrollConfig.settingsVersion = accountSettings?.settings_version ?? bankrollConfig.settingsVersion;
    const input = $("ev-bankroll-input"), button = $("ev-save-bankroll"), state = $("ev-bankroll-save-state");
    input.disabled = false;
    input.closest(".ev-money-input")?.classList.remove("is-loading");
    if (forceInput || !bankrollConfig.dirty) input.value = bankrollConfig.amount.toFixed(2);
    button.disabled = false;
    $("ev-bankroll-toolbar-value").textContent = money(bankrollConfig.amount);
    const unitAmount = bankrollConfig.amount * bankrollConfig.unitPercentage;
    $("ev-unit-value").textContent = money(unitAmount);
    $("ev-unit-toolbar-value").textContent = money(unitAmount);
    if (state && !bankrollConfig.dirty) {
      state.textContent = accountSettings?.sizing_bankroll_configured
        ? accountSettings?.account_authenticated ? "Saved to your account" : "Saved to this browser — sign in to sync"
        : "Configured default — save to make permanent";
      state.dataset.state = accountSettings?.sizing_bankroll_configured ? "saved" : "default";
    }
  }
  async function loadBankrollSettings() {
    try {
      const payload = await requestJson("/api/user-settings");
      applyBankrollSettings(payload.data, {forceInput:true});
    } catch (error) {
      applyBankrollSettings({trades_to_play_bankroll:bankrollConfig.amount,unit_percentage:bankrollConfig.unitPercentage}, {forceInput:true});
      $("ev-bankroll-save-state").textContent = `Could not load saved bankroll: ${error.message}`;
      $("ev-bankroll-save-state").dataset.state = "error";
    }
  }
  async function saveBankroll() {
    const amount = Number($("ev-bankroll-input").value), state = $("ev-bankroll-save-state"), button = $("ev-save-bankroll");
    if (!(amount > 0)) {
      state.textContent = "Enter an amount greater than zero";
      state.dataset.state = "error";
      return;
    }
    if (bankrollConfig.savePending) return;
    bankrollConfig.savePending = true;
    button.disabled = true;
    state.textContent = "Saving…";
    state.dataset.state = "saving";
    try {
      const payload = await requestJson("/api/user-settings", {method:"PUT",body:JSON.stringify({trades_to_play_bankroll:amount,expected_version:bankrollConfig.settingsVersion})});
      bankrollConfig.dirty = false;
      applyBankrollSettings(payload.data, {forceInput:true});
      state.textContent = "Saved";
      state.dataset.state = "saved";
      await load(true);
    } catch (error) {
      if (error.status === 409 && error.payload?.data) {
        bankrollConfig.dirty = false;
        applyBankrollSettings(error.payload.data, {forceInput:true});
      }
      state.textContent = `Save failed: ${error.message}`;
      state.dataset.state = "error";
    } finally {
      bankrollConfig.savePending = false;
      button.disabled = false;
    }
  }
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
  const statusLabel = row => {
    if (row.portfolioStatus !== "qualified") return "Suppressed";
    return ({
      executable:"Executable", liquidity_unknown:"Verify liquidity", limit_unknown:"Verify limit",
      eligibility_unknown:"Verify eligibility", account_ineligible:"Account ineligible",
      settlement_unverified:"Verify settlement", unavailable:"Unavailable",
    })[row.executionStatus] || "Watch only";
  };
  const executionAction = (row, quote, state) => state === "executable" && quote.deepLink
    ? `<a class="ev-best-button il-executable-quote executable" href="${esc(quote.deepLink)}" target="_blank" rel="noopener" aria-label="Open ${esc(quote.bookName||quote.bookKey)} at ${odds(quote.topPriceAmericanOdds??quote.americanOdds)}">${img(quote.logoUrl,quote.bookKey)}<span>${odds(quote.topPriceAmericanOdds??quote.americanOdds)}<i class="ph ph-arrow-up-right" aria-hidden="true"></i></span></a>`
    : `<span class="ev-best-button il-executable-quote watch" role="status" aria-label="${esc(statusLabel(row))}. Execution disabled.">${img(quote.logoUrl,quote.bookKey)}<span>${odds(quote.topPriceAmericanOdds??quote.americanOdds)}<small>${esc(statusLabel(row))}</small></span></span>`;
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

  function liveHistoryBookKeys(row) {
    const sharpBooks = ["pinnacle", "circa", "bookmakereu"];
    return [...new Set([row.bestQuote?.bookKey, ...sharpBooks].filter(Boolean))];
  }

  function marketTrendVisual(row) {
    const identity = row.lineHistoryIdentity || {};
    if (!identity.eventId || !identity.marketId || !identity.selectionId) {
      return `<div class="ev-trend-chart il-chart-container"><div class="ev-chart-live-state il-state il-state-empty"><i class="ph ph-database"></i><strong>Line history is starting</strong><span>This play will chart after its first normalized bookmaker snapshot.</span></div></div>`;
    }
    return `<div class="ev-trend-chart il-chart-container" id="ev-live-line-history" aria-live="polite" aria-busy="true">
      <div class="ev-chart-live-state il-state il-state-loading"><span></span><strong>Loading real line movement</strong><small>Reading timestamped odds from the selected market books…</small></div>
    </div>`;
  }

  const liveChartColors = ["#a65cff", "#20d6a2", "#36a7ff", "#ff4fa0", "#f3c324", "#ff8b3d", "#77e1ff", "#d6d9e0"];
  const liveChartBookColors = Object.freeze({
    pinnacle: "#ff4fa0",
    circa: "#20d6a2",
    bookmakereu: "#f3c324",
    fanduel: "#36a7ff",
    hardrockbet: "#8b5cff",
    draftkings: "#53d337",
    betmgm: "#3f78ff",
    caesars: "#f0c34a",
    bet365: "#16a05d",
    fanatics: "#ff5a4f",
  });

  const finiteOrNull = value => {
    const number = Number(value);
    return value == null || value === "" || !Number.isFinite(number) ? null : number;
  };

  function liveChartColor(bookKey, index = 0) {
    const key = String(bookKey || "").toLowerCase();
    return liveChartBookColors[key] || liveChartColors[(stableSeed(key) + index) % liveChartColors.length];
  }

  function prepareLiveHistorySeries(row, rawSeries) {
    const order = liveHistoryBookKeys(row);
    const selectedBook = String(row.bestQuote?.bookKey || "").toLowerCase();
    return [...(rawSeries || [])].map((series, index) => ({
      ...series,
      color: liveChartColor(series.bookKey, index),
      isSelected: String(series.bookKey || "").toLowerCase() === selectedBook,
    })).sort((left, right) => {
      const leftIndex = order.indexOf(left.bookKey);
      const rightIndex = order.indexOf(right.bookKey);
      return (leftIndex < 0 ? order.length : leftIndex) - (rightIndex < 0 ? order.length : rightIndex);
    });
  }

  function liveHistorySeries(rawSeries, mode) {
    // Keep only timestamped provider observations: no synthetic points.
    const normalized = (rawSeries || []).map((series, index) => ({
      ...series,
      key: `live-${String(series.bookKey || index).replace(/[^a-z0-9_-]/gi, "-")}`,
      color: series.color || liveChartColor(series.bookKey, index),
      points: (series.points || []).map(point => ({
        timestamp: Date.parse(point.timestamp),
        americanOdds: Number(point.americanOdds),
        line: finiteOrNull(point.line),
        marketLimit: finiteOrNull(point.marketLimit),
      })).filter(point => Number.isFinite(point.timestamp) && Number.isFinite(point.americanOdds))
        .sort((left, right) => left.timestamp - right.timestamp),
    })).filter(series => series.points.length);
    if (!normalized.length) return [];
    if (mode !== "trend") return normalized;
    const latest = Math.max(...normalized.flatMap(series => series.points.map(point => point.timestamp)));
    const cutoff = latest - 6 * 60 * 60 * 1000;
    return normalized.map(series => {
      const recent = series.points.filter(point => point.timestamp >= cutoff);
      return { ...series, points: recent.length >= 2 ? recent : series.points.slice(-12) };
    });
  }

  const liveHistoryMetric = (rawSeries, preferred = "auto") => {
    const points = (rawSeries || []).flatMap(series => series.points || []);
    const hasLine = points.some(point => finiteOrNull(point.line) != null);
    const hasLimit = points.some(point => finiteOrNull(point.marketLimit) != null);
    if (preferred === "line" && hasLine) return "line";
    if (preferred === "marketLimit" && hasLimit) return "marketLimit";
    if (preferred === "americanOdds") return "americanOdds";
    const distinctLines = new Set(points.map(point => finiteOrNull(point.line)).filter(value => value != null));
    return hasLine && distinctLines.size > 1 ? "line" : "americanOdds";
  };
  const liveHistoryValue = (point, metric) => metric === "line"
    ? point.line
    : metric === "marketLimit"
      ? point.marketLimit
      : point.americanOdds;
  const liveHistoryHasMovement = rawSeries => new Set(
    (rawSeries || []).flatMap(series => (series.points || []).map(point => point.timestamp))
  ).size > 1;
  const lineValue = value => {
    const number = Number(value);
    if (!Number.isFinite(number)) return "--";
    const formatted = Number.isInteger(number) ? String(number) : number.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
    return formatted;
  };
  const historyValueLabel = (value, metric) => metric === "line"
    ? lineValue(value)
    : metric === "marketLimit"
      ? compactDollars(value)
      : odds(value);
  const compactDollars = value => {
    const number = Number(value || 0);
    if (number >= 1000) return `$${(number / 1000).toFixed(number >= 10000 ? 0 : 1).replace(/\.0$/, "")}k`;
    return `$${Math.round(number)}`;
  };
  const chartStepPath = points => points.length
    ? points.slice(1).reduce((path, point, index) => `${path} H${point[0].toFixed(1)} V${point[1].toFixed(1)}`, `M${points[0][0].toFixed(1)} ${points[0][1].toFixed(1)}`)
    : "";

  function liveHistorySvg(rawSeries, mode, preferredMetric = "auto") {
    const series = liveHistorySeries(rawSeries, mode);
    const metric = liveHistoryMetric(series, preferredMetric);
    const points = series.flatMap(item => item.points).filter(point => Number.isFinite(liveHistoryValue(point, metric)));
    if (!points.length) return "";
    const axisTime = timestamp => new Intl.DateTimeFormat("en-US", {hour:"numeric", minute:"2-digit"}).format(new Date(timestamp));
    if (!liveHistoryHasMovement(series)) {
      return `<div class="ev-trend-snapshot" role="status"><span>Current snapshot</span><strong>${esc(axisTime(points[0].timestamp))}</strong><small>The next real line, price, limit, or checkpoint update will start the graph.</small></div>`;
    }
    const width = 520, height = 220, left = 48, right = 54, top = 20, bottom = 36;
    const minTime = Math.min(...points.map(point => point.timestamp));
    const maxTime = Math.max(...points.map(point => point.timestamp));
    const values = points.map(point => liveHistoryValue(point, metric));
    const rawMin = Math.min(...values), rawMax = Math.max(...values);
    const valuePadding = metric === "line"
      ? Math.max(.5, (rawMax - rawMin) * .15)
      : metric === "marketLimit"
        ? Math.max(100, (rawMax - rawMin) * .12)
        : Math.max(6, (rawMax - rawMin) * .12);
    const minValue = rawMin - valuePadding;
    const maxValue = rawMax + valuePadding;
    const timeSpan = Math.max(1, maxTime - minTime);
    const valueSpan = Math.max(.01, maxValue - minValue);
    const x = timestamp => left + ((timestamp - minTime) / timeSpan) * (width - left - right);
    const y = value => top + ((maxValue - value) / valueSpan) * (height - top - bottom);
    const grid = [0, .25, .5, .75, 1].map(ratio => {
      const gridY = top + ratio * (height - top - bottom);
      const value = maxValue - ratio * valueSpan;
      const label = metric === "line" ? Math.round(value * 2) / 2 : Math.round(value);
      return `<line x1="${left}" y1="${gridY}" x2="${width-right}" y2="${gridY}" class="ev-trend-grid"></line><text x="4" y="${gridY+4}" class="ev-trend-axis">${historyValueLabel(label, metric)}</text>`;
    }).join("");
    const paths = series.map(item => {
      const plotted = item.points.filter(point => Number.isFinite(liveHistoryValue(point, metric))).map(point => [x(point.timestamp), y(liveHistoryValue(point, metric)), point]);
      const path = plotted.length > 1
        ? `<path class="ev-trend-line ev-history-line ${item.isSelected ? "is-selected" : ""}" d="${chartStepPath(plotted)}" stroke="${item.color}"></path>`
        : "";
      return `<g data-series="${esc(item.key)}">${path}${plotted.map(point => `<circle cx="${point[0].toFixed(1)}" cy="${point[1].toFixed(1)}" r="${item.isSelected ? "3.4" : "2.8"}" fill="${item.color}"><title>${esc(item.bookName || item.bookKey)} ${historyValueLabel(liveHistoryValue(point[2], metric), metric)} at ${esc(new Date(point[2].timestamp).toLocaleString())}</title></circle>`).join("")}</g>`;
    }).join("");
    const pinnacle = series.find(item => String(item.bookKey).toLowerCase() === "pinnacle");
    const limitPoints = (pinnacle?.points || []).filter(point => Number.isFinite(point.marketLimit));
    const maxLimit = limitPoints.length ? Math.max(100, ...limitPoints.map(point => point.marketLimit)) * 1.1 : 0;
    const limitY = value => top + ((maxLimit - value) / maxLimit) * (height - top - bottom);
    const plottedLimits = limitPoints.map(point => [x(point.timestamp), limitY(point.marketLimit), point]);
    const limitPath = metric !== "marketLimit" && plottedLimits.length > 1
      ? `<g data-series="live-pinnacle-limit"><path class="ev-trend-limit" stroke-dasharray="8 6" d="${chartStepPath(plottedLimits)}"></path>${plottedLimits.map(point => `<circle class="ev-trend-limit-point" cx="${point[0].toFixed(1)}" cy="${point[1].toFixed(1)}" r="3"><title>Pinnacle limit ${compactDollars(point[2].marketLimit)} at ${esc(new Date(point[2].timestamp).toLocaleString())}</title></circle>`).join("")}</g>`
      : "";
    const limitAxis = metric !== "marketLimit" && plottedLimits.length > 1
      ? `<text x="${width-2}" y="${top+4}" text-anchor="end" class="ev-trend-limit-label">${compactDollars(maxLimit)}</text><text x="${width-2}" y="${height-bottom+4}" text-anchor="end" class="ev-trend-limit-label">$0</text>`
      : "";
    const metricLabel = metric === "line" ? "line" : metric === "marketLimit" ? "limit" : "price";
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Real timestamped sportsbook ${metricLabel} history">${grid}${limitAxis}${paths}${limitPath}<text x="${left}" y="${height-10}" class="ev-trend-axis">${esc(axisTime(minTime))}</text><text x="${width-right}" y="${height-10}" text-anchor="end" class="ev-trend-axis ev-current-axis">${esc(axisTime(maxTime))}</text></svg>`;
  }

  function liveHistoryLegend(rawSeries, mode, preferredMetric = "auto") {
    const series = liveHistorySeries(rawSeries, mode);
    const metric = liveHistoryMetric(series, preferredMetric);
    const books = series.map(item => {
      const latest = item.points[item.points.length - 1];
      const value = liveHistoryValue(latest, metric);
      const summary = metric === "line"
        ? `${historyValueLabel(value, metric)} · ${odds(latest.americanOdds)}`
        : odds(latest.americanOdds);
      return `<button type="button" class="ev-trend-legend-toggle ${item.isSelected ? "is-selected" : ""}" data-series-toggle="${esc(item.key)}" aria-pressed="true" style="--legend:${item.color}"><span>${esc(item.bookName || bookNames[item.bookKey] || item.bookKey)}${item.isSelected ? " <small>Compared</small>" : ""}</span><b>${summary}</b></button>`;
    }).join("");
    const pinnacle = series.find(item => String(item.bookKey).toLowerCase() === "pinnacle");
    const latestLimit = [...(pinnacle?.points || [])].reverse().find(point => Number.isFinite(point.marketLimit));
    const limitPointCount = (pinnacle?.points || []).filter(point => Number.isFinite(point.marketLimit)).length;
    const limit = latestLimit
      ? `<button type="button" class="ev-trend-legend-toggle is-limit ${limitPointCount < 2 ? "is-snapshot" : ""}" ${limitPointCount > 1 ? 'data-series-toggle="live-pinnacle-limit" aria-pressed="true"' : 'disabled aria-disabled="true"'}><span>Pinnacle limit</span><b>${compactDollars(latestLimit.marketLimit)}</b></button>`
      : `<button type="button" class="ev-trend-legend-toggle is-limit is-snapshot" disabled aria-disabled="true"><span>Pinnacle limit</span><b>Unavailable</b></button>`;
    return books + limit;
  }

  function updateTrendMetrics(rawSeries, preferredMetric = "auto") {
    const series = liveHistorySeries(rawSeries, "history");
    const metric = liveHistoryMetric(series, preferredMetric);
    const primary = series.find(item => item.isSelected) || series.find(item => item.bookKey === "pinnacle") || series[0];
    if (!primary?.points?.length) return;
    const open = primary.points[0];
    const latestTime = primary.points[primary.points.length - 1].timestamp;
    const oneHourCutoff = latestTime - 60 * 60 * 1000;
    const oneHour = [...primary.points].reverse().find(point => point.timestamp <= oneHourCutoff) || open;
    const openMetric = detail.querySelector('[data-trend-metric="open"]');
    const hourMetric = detail.querySelector('[data-trend-metric="1h"]');
    if (openMetric) openMetric.textContent = historyValueLabel(liveHistoryValue(open, metric), metric);
    if (hourMetric) hourMetric.textContent = historyValueLabel(liveHistoryValue(oneHour, metric), metric);
  }

  function renderLiveLineHistory(row, payload, viewState = {}) {
    const container = $("ev-live-line-history");
    if (!container || String(selectedId) !== String(row.id)) return;
    const series = prepareLiveHistorySeries(row, payload.series || []);
    const observationCount = Number(payload.observationCount || 0);
    if (!observationCount) {
      container.setAttribute("aria-busy", "false");
      container.innerHTML = `<div class="ev-chart-live-state il-state il-state-empty"><i class="ph ph-chart-line-up"></i><strong>Collecting real bookmaker history</strong><span>The current live quote is recorded now; the chart appears as timestamped book prices accumulate.</span></div>`;
      return;
    }
    const metric = liveHistoryMetric(series, lineHistoryMetricMode);
    const trendSvg = liveHistorySvg(series, "trend", metric);
    const historySvg = liveHistorySvg(series, "history", metric);
    const singleSnapshot = !liveHistoryHasMovement(series);
    const availableKinds = new Set(payload.valueKindsAvailable || []);
    const metricControls = [
      ["line", "Line", availableKinds.has("line")],
      ["americanOdds", "Price", availableKinds.has("american_odds")],
      ["marketLimit", "Limit", availableKinds.has("market_limit")],
    ].map(([key, label, available]) => `<button type="button" data-history-metric="${key}" aria-pressed="${metric === key}" class="${metric === key ? "active" : ""}" ${available ? "" : 'disabled aria-disabled="true"'}>${label}</button>`).join("");
    const metricCopy = metric === "line" ? "Live line movement" : metric === "marketLimit" ? "Reported Pinnacle limit history" : "Live price movement";
    container.setAttribute("aria-busy", "false");
    container.innerHTML = `<div class="ev-trend-chart-head"><div class="ev-chart-tabs" role="tablist" aria-label="Live line chart view"><button type="button" class="active" role="tab" aria-selected="true" data-chart-tab="trend">Market Trend</button><button type="button" role="tab" aria-selected="false" data-chart-tab="history">Line History</button></div><div class="ev-chart-tabs ev-chart-metric-tabs" role="group" aria-label="Chart metric">${metricControls}</div></div>
      <div class="ev-chart-view active" data-chart-view="trend"><div class="ev-trend-chart-title"><strong>${esc(row.selection)}</strong><span>${metricCopy} from the selected book, Pinnacle, Circa, and Bookmaker</span></div>${trendSvg}<div class="ev-trend-legend">${liveHistoryLegend(series, "trend", metric)}</div><p class="ev-trend-live-note"><i class="ph ph-broadcast"></i>${singleSnapshot ? "First real snapshots recorded. Movement appears after the next line, price, limit, or checkpoint update." : "Real provider timestamps. A missing Pinnacle limit is labeled unavailable, never inferred."}</p></div>
      <div class="ev-chart-view" data-chart-view="history" hidden><div class="ev-history-heading"><strong>${esc(row.marketLabel)} History</strong><span>${esc(row.eventTitle)}</span></div>${historySvg}<div class="ev-trend-legend">${liveHistoryLegend(series, "history", metric)}</div><p class="ev-trend-live-note"><i class="ph ph-database"></i>${observationCount} stored bookmaker observation${observationCount === 1 ? "" : "s"}; first seen is not represented as a sportsbook opening line.</p></div>`;
    updateTrendMetrics(series, metric);
    bindTrendControls(viewState, row, payload);
    if (Number.isFinite(viewState.scrollTop)) requestAnimationFrame(() => { detail.scrollTop = viewState.scrollTop; });
  }

  async function loadLiveLineHistory(row, viewState = {}) {
    if (!row.lineHistoryIdentity?.eventId || !row.lineHistoryIdentity?.marketId || !row.lineHistoryIdentity?.selectionId) return;
    const requestId = ++lineHistoryRequestId;
    const identity = row.lineHistoryIdentity;
    const books = liveHistoryBookKeys(row);
    const params = new URLSearchParams({
      event_id: identity.eventId,
      market_id: identity.marketId,
      selection_id: identity.selectionId,
      books: books.join(","),
      limit: "1000",
    });
    if (identity.providerEventId) params.set("provider_event_id", identity.providerEventId);
    if (identity.providerSelectionId) params.set("provider_selection_id", identity.providerSelectionId);
    if (identity.providerSeriesId) params.set("provider_series_id", identity.providerSeriesId);
    if (identity.marketType && identity.marketFamily && identity.period && identity.selection && typeof identity.isAlternate === "boolean") {
      params.set("market_type", identity.marketType);
      params.set("market_family", identity.marketFamily);
      params.set("period", identity.period);
      params.set("selection", identity.selection);
      params.set("side", identity.side || "");
      params.set("is_alternate", String(identity.isAlternate));
    }
    try {
      const response = await fetch(`/api/positive-ev/line-history?${params}`, {headers:{"Accept":"application/json"}});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Line history unavailable");
      if (requestId !== lineHistoryRequestId) return;
      renderLiveLineHistory(row, payload, viewState);
    } catch (error) {
      const container = $("ev-live-line-history");
      if (requestId !== lineHistoryRequestId || !container || String(selectedId) !== String(row.id)) return;
      container.setAttribute("aria-busy", "false");
      container.innerHTML = `<div class="ev-chart-live-state il-state il-state-error"><i class="ph ph-warning-circle"></i><strong>Live history temporarily unavailable</strong><span>${esc(error.message)}</span></div>`;
    }
  }

  function bindTrendControls(viewState = {}, row = null, payload = null) {
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
    detail.querySelectorAll("[data-series-toggle]:not(:disabled)").forEach(button => button.addEventListener("click", () => {
      const visible = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", String(visible));
      button.classList.toggle("off", !visible);
      const view = button.closest("[data-chart-view]");
      view?.querySelectorAll(`[data-series="${button.dataset.seriesToggle}"]`).forEach(series => series.classList.toggle("series-hidden", !visible));
    }));
    detail.querySelectorAll("[data-history-metric]:not(:disabled)").forEach(button => button.addEventListener("click", () => {
      lineHistoryMetricMode = button.dataset.historyMetric || "auto";
      const activeTab = detail.querySelector('[data-chart-tab][aria-selected="true"]')?.dataset.chartTab || "trend";
      if (row && payload) renderLiveLineHistory(row, payload, {scrollTop: detail.scrollTop, chartMode: activeTab});
    }));
    const preferredTab = detail.querySelector(`[data-chart-tab="${CSS.escape(viewState.chartMode || "trend")}"]`);
    if (preferredTab) activateChartTab(preferredTab);
    const hiddenSeries = new Set(viewState.hiddenSeries || []);
    detail.querySelectorAll("[data-series-toggle]").forEach(button => {
      if (!hiddenSeries.has(button.dataset.seriesToggle)) return;
      button.setAttribute("aria-pressed", "false");
      button.classList.add("off");
      button.closest("[data-chart-view]")?.querySelectorAll(`[data-series="${button.dataset.seriesToggle}"]`).forEach(series => series.classList.add("series-hidden"));
    });
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
    bookKeys.sort((left, right) => {
      const order = window.IconLabsLineShopOrder;
      const leftRank = order?.rank(left,bookKeys) ?? Number.MAX_SAFE_INTEGER;
      const rightRank = order?.rank(right,bookKeys) ?? Number.MAX_SAFE_INTEGER;
      return leftRank-rightRank || priceOf(sideMaps[0].get(right))-priceOf(sideMaps[0].get(left));
    });
    const bestBySide = sideMaps.map(sideMap => Math.max(...[...sideMap.values()].map(priceOf)));
    const priceCell = (quote, sideIndex) => {
      if (!quote) return `<span class="ev-compare-price unavailable" aria-label="No price available">—</span>`;
      const quoteOdds = priceOf(quote);
      const best = quoteOdds === bestBySide[sideIndex];
      const content = `<strong>${odds(quoteOdds)}</strong><i class="ph ph-arrow-up-right" aria-hidden="true"></i>`;
      return quote.deepLink && quote.deepLink !== "#"
        ? `<a class="ev-compare-price ${best ? "best" : ""}" href="${esc(quote.deepLink)}" target="_blank" rel="noopener" aria-label="Open ${esc(quote.bookName || bookNames[quote.bookKey] || quote.bookKey)} ${esc(sides[sideIndex].selection)} at ${odds(quoteOdds)}">${content}</a>`
        : `<span class="ev-compare-price ${best ? "best" : ""}">${content}</span>`;
    };
    const rowsHtml = bookKeys.map(bookKey => {
      const left = sideMaps[0].get(bookKey);
      const right = sideMaps[1]?.get(bookKey);
      const representative = left || right || {};
      const label = representative.bookName || bookNames[bookKey] || bookKey;
      return `<div class="ev-market-compare-row" draggable="true" data-line-shop-book="${esc(bookKey)}" title="Drag ${esc(label)} to reorder line shopping">
        ${priceCell(left, 0)}
        <span class="ev-market-book-center" title="${esc(label)}" aria-label="${esc(label)}">${img(representative.logoUrl, bookKey)}<span>${esc(label)}</span></span>
        ${sides.length > 1 ? priceCell(right, 1) : ""}
      </div>`;
    }).join("");
    const collapsedBookCount = 5;
    const canExpand = bookKeys.length > collapsedBookCount;
    return `<section class="ev-market-odds ev-market-comparison il-detail-section" data-market-book-count="${bookKeys.length}">
      <header><h3>MARKET ODDS</h3></header>
      <div class="ev-market-compare-head"><span>Sportsbook</span><strong>${esc(sideLabels[0])}</strong>${sides.length > 1 ? `<strong>${esc(sideLabels[1])}</strong>` : ""}</div>
      <div class="ev-market-compare-rows" id="ev-market-compare-rows">${rowsHtml}</div>
      ${canExpand ? `<button class="ev-market-odds-toggle" type="button" aria-expanded="false" aria-controls="ev-market-compare-rows"><span>Show all ${bookKeys.length} books</span><i class="ph ph-caret-down" aria-hidden="true"></i></button>` : ""}
    </section>`;
  }

  function setMarketOddsExpanded(section, expanded) {
    if (!section) return;
    const button = section.querySelector(".ev-market-odds-toggle");
    if (!button) return;
    const bookCount = Number(section.dataset.marketBookCount || 0);
    section.classList.toggle("is-expanded", expanded);
    button.setAttribute("aria-expanded", String(expanded));
    button.querySelector("span").textContent = expanded ? "Show top 5 books" : `Show all ${bookCount} books`;
    button.querySelector("i").className = `ph ph-caret-${expanded ? "up" : "down"}`;
  }

  function bindMarketOddsControls(expanded = false) {
    const section = detail.querySelector(".ev-market-comparison");
    if (!section) return;
    setMarketOddsExpanded(section, expanded);
    section.querySelector(".ev-market-odds-toggle")?.addEventListener("click", () => {
      setMarketOddsExpanded(section, !section.classList.contains("is-expanded"));
    });
    let draggedBook = "";
    section.addEventListener("dragstart", event => {
      const row = event.target.closest("[data-line-shop-book]");
      if (!row) return;
      draggedBook = row.dataset.lineShopBook;
      row.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain",draggedBook);
    });
    section.addEventListener("dragover", event => {
      const target = event.target.closest("[data-line-shop-book]");
      if (!draggedBook || !target || target.dataset.lineShopBook===draggedBook) return;
      event.preventDefault();
    });
    section.addEventListener("drop", event => {
      const target = event.target.closest("[data-line-shop-book]");
      if (!target || !draggedBook || target.dataset.lineShopBook===draggedBook) return;
      event.preventDefault();
      const order = [...section.querySelectorAll("[data-line-shop-book]")].map(item=>item.dataset.lineShopBook);
      const sourceIndex = order.indexOf(draggedBook);
      const targetIndex = order.indexOf(target.dataset.lineShopBook);
      if (sourceIndex < 0 || targetIndex < 0) return;
      order.splice(sourceIndex,1);
      order.splice(targetIndex,0,draggedBook);
      window.IconLabsLineShopOrder?.save(order);
      const selected = rows.find(item=>String(item.id)===String(selectedId));
      const markup = selected ? marketOddsVisual(selected) : "";
      if (markup) {
        const wasExpanded = section.classList.contains("is-expanded");
        const template = document.createElement("template");
        template.innerHTML = markup.trim();
        section.replaceWith(template.content.firstElementChild);
        bindMarketOddsControls(wasExpanded);
      }
    });
    section.addEventListener("dragend", () => {
      draggedBook = "";
      section.querySelectorAll("[data-line-shop-book].dragging").forEach(item=>item.classList.remove("dragging"));
    });
  }

  function captureDetailViewState() {
    return {
      scrollTop: detail.scrollTop,
      chartMode: detail.querySelector("[data-chart-tab].active")?.dataset.chartTab || "trend",
      hiddenSeries: [...detail.querySelectorAll('[data-series-toggle][aria-pressed="false"]')].map(button => button.dataset.seriesToggle),
      marketOddsExpanded: detail.querySelector(".ev-market-comparison")?.classList.contains("is-expanded") || false,
      marketDepthExpanded: detail.querySelector(".ev-full-market-button")?.getAttribute("aria-expanded") === "true",
    };
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
    $("ev-weight-list").innerHTML = devigCatalog.map(book => `<div class="ev-weight-row"><label for="weight-${book.key}">${esc(book.name || bookNames[book.key] || book.key)}</label><span class="ev-weight-input"><input id="weight-${book.key}" data-weight="${book.key}" type="number" min="0" max="100" step=".5" value="${Number(settings.weights[book.key] || 0)}"><b>%</b></span></div>`).join("");
    $("ev-required-books-list").innerHTML = requiredBookCatalog.map(book => `<label><span>${img(book.logoUrl || bookLogos[book.key], book.key)}</span><strong>${esc(book.name || bookNames[book.key] || book.key)}</strong><input type="checkbox" data-required-book="${esc(book.key)}" aria-label="Require ${esc(book.name || book.key)}" ${settings.requiredBooks.includes(book.key)?"checked":""}></label>`).join("");
    updateRequiredBooksSummary();
    updateFilterValidity();
    updateToolbarFilterCount();
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
      const supportedSports = String(input.dataset.marketSports || input.dataset.marketSport || "")
        .split(",").map(value => value.trim()).filter(Boolean);
      input.disabled = supportedSports.length > 0 && !supportedSports.some(sport => activeSports.has(sport));
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
    const params = new URLSearchParams({group:"custom",markets:settings.markets.join(","),sports:settings.sports.join(","),books:settings.books.join(","),min_ev:settings.minEv,kelly:settings.kelly,min_sources:settings.minSources,required_books:settings.requiredBooks.join(","),devig_method:settings.devigMethod,weights:JSON.stringify(settings.weights),bankroll:bankrollConfig.amount});
    return `/api/positive-ev/live?${params}`;
  }
  function renderDiagnostics(diagnostics = {}, history = {}) {
    const reasons = diagnostics.rejectionReasons || {};
    const topReason = Object.entries(reasons).sort((a,b)=>b[1]-a[1])[0];
    const bookClv = history.averageRespectiveBookClvPoints == null ? "collecting" : `${Number(history.averageRespectiveBookClvPoints) >= 0 ? "+" : ""}${Number(history.averageRespectiveBookClvPoints).toFixed(2)} pts`;
    const compositeClv = history.averageCompositeClvPoints == null ? "collecting" : `${Number(history.averageCompositeClvPoints) >= 0 ? "+" : ""}${Number(history.averageCompositeClvPoints).toFixed(2)} pts`;
    $("ev-credit-banner").innerHTML = `<i class="ph ph-shield-check" aria-hidden="true"></i><span><strong>${Number(diagnostics.qualified || 0)} executable</strong> · ${Number(diagnostics.watchOnly || 0)} watch-only · ${Number(diagnostics.rejected || 0)} rejected${topReason ? ` · most common: ${esc(topReason[0].replaceAll("_"," "))}` : ""}</span><span class="ev-history-stat">Tracked ${Number(history.opportunities || 0)} · book CLV ${bookClv} · composite ${compositeClv}</span><button class="button ghost compact" id="ev-adjust-filters" type="button">Adjust filters</button>`;
    $("ev-mobile-credit-summary-copy").innerHTML = `<strong>${Number(diagnostics.qualified || 0)} executable</strong> · ${Number(diagnostics.watchOnly || 0)} watch-only · ${Number(diagnostics.rejected || 0)} rejected`;
    $("ev-adjust-filters").addEventListener("click", openFilters);
  }
  async function load(force=false) {
    if (paused && !force) return;
    const url = query();
    const cacheKey = pagePayloadCacheKey("positive-ev", url.replace("/positive-ev/live", "/positive-ev"));
    let showedCached = false;
    if (!rows.length) {
      const cached = readPagePayloadCache(cacheKey, 5 * 60 * 1000);
      if (cached && !cached.paused) {
        rows = Array.isArray(cached.data) ? cached.data : [];
        $("ev-count").textContent = rows.length;
        $("ev-updated").textContent = "Showing recent scan · updating live";
        renderDiagnostics(cached.diagnostics || {}, {});
        const cachedRows = visibleRows();
        if (cachedRows[0]) select(cachedRows[0].id);
        else renderFeed();
        showedCached = true;
      }
    }
    feed.setAttribute("aria-busy", "true");
    if (!showedCached && !rows.length) feed.innerHTML = `<div class="ev-loading il-state il-state-loading"><span></span><p>Validating exact markets and executable prices...</p></div>`;
    try {
      const response = await fetch(url, {headers:{"Accept":"application/json"}});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Unable to load feed");
      if (payload.degraded && rows.length && !(payload.data || []).length) {
        retryCount += 1;
        $("ev-updated").textContent = "Recent scan shown · live feed reconnecting";
        $("ev-feed-label").textContent = "Live feed reconnecting";
        feed.setAttribute("aria-busy", "false");
        clearTimeout(timer);
        timer = setTimeout(() => load(), Math.max(3000, Number(payload.refreshSeconds || 5) * 1000));
        return;
      }
      writePagePayloadCache(cacheKey, payload);
      retryCount = 0;
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
        updateMoreMenu();
        $("ev-credit-banner").innerHTML = `<i class="ph ph-shield-check" aria-hidden="true"></i><span><strong>EV optimizer paused</strong> · No paid odds requests or refreshes are running.</span>`;
        $("ev-mobile-credit-summary-copy").innerHTML = `<strong>Optimizer paused</strong> · refreshes are off`;
        feed.innerHTML = `<div class="ev-empty il-state il-state-empty"><i class="ph ph-pause-circle" aria-hidden="true"></i><p>${esc(payload.message || "Positive EV scanning is paused.")}</p></div>`;
        $("ev-feed-footer").textContent = "Showing 0 of 0 markets";
        feed.setAttribute("aria-busy", "false");
        return;
      }
      rows = payload.data || [];
      $("ev-count").textContent = rows.length;
      $("ev-updated").textContent = payload.degraded
        ? "Recent verified odds · live feed reconnecting"
        : `Updated ${new Date().toLocaleTimeString([],{hour:"numeric",minute:"2-digit",second:"2-digit"})}`;
      $("ev-feed-label").textContent = payload.degraded ? "Live feed reconnecting" : "Live market scan";
      let history = {};
      try { history = (await (await fetch("/api/positive-ev/history?limit=100")).json()).summary || {}; } catch {}
      renderDiagnostics(payload.diagnostics || {}, history);
      const currentViewRows = visibleRows();
      const nextSelectedId = currentViewRows.some(row=>row.id===selectedId) ? selectedId : currentViewRows[0]?.id;
      if (nextSelectedId && String(nextSelectedId) === String(selectedId) && detail.classList.contains("open")) {
        refreshSelectedDetail(currentViewRows.find(row => String(row.id) === String(nextSelectedId)));
      } else if (nextSelectedId) select(nextSelectedId);
      else { selectedId = ""; renderFeed(); showDetailPlaceholder(); }
      feed.setAttribute("aria-busy", "false");
      clearTimeout(timer);
      if (Number(payload.refreshSeconds) > 0) timer = setTimeout(load, Number(payload.refreshSeconds) * 1000);
    } catch (error) {
      if (rows.length) {
        $("ev-updated").textContent = "Recent scan shown · live refresh delayed";
      } else {
        feed.innerHTML = `<div class="ev-empty il-state il-state-error"><i class="ph ph-warning-circle" aria-hidden="true"></i><p>${esc(error.message)}</p></div>`;
      }
      feed.setAttribute("aria-busy", "false");
      clearTimeout(timer);
      retryCount += 1;
      timer = setTimeout(() => load(), Math.min(30000, 3000 * (2 ** (retryCount - 1))));
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
    $("ev-feed-label").textContent = feedView === "hidden" ? "Manually hidden bets" : paused ? "Refresh paused" : "Live market scan";
    updateMoreMenu();
  }
  function closeHiddenMenu(restoreFocus = false) {
    const menu = $("ev-more-menu");
    menu.hidden = true;
    $("ev-more-menu-toggle").setAttribute("aria-expanded", "false");
    if (restoreFocus) $("ev-more-menu-toggle").focus();
  }
  function updateMoreMenu() {
    const button = $("ev-pause"), icon = button.querySelector("i"), status = button.querySelector("small");
    button.setAttribute("aria-pressed", String(paused));
    button.setAttribute("aria-label", paused ? "Resume automatic refresh" : "Pause automatic refresh");
    icon.className = `ph ph-${paused ? "play" : "pause"}`;
    status.textContent = paused ? "Paused" : "Active";
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
    $("ev-feed-footer").textContent = `Showing ${shown.length} of ${rows.length} markets`;
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
        <div class="ev-score il-confidence-display"><strong>${evPercent(row.evPercent)}</strong>${scoreAction}</div>
        <div class="ev-event"><span class="ev-event-meta"><time>${esc(time(row.commenceTime))}</time><span><i class="ph ${sportIcon(row)}" aria-hidden="true"></i>${esc(row.league)}</span></span><strong class="ev-matchup" aria-label="${esc(row.eventTitle)}">${matchup(row)}</strong><small>${esc(row.marketLabel)}</small></div>
        <div class="ev-pick">${leagueWatermark(row)}<small>Best Bet</small><strong>${esc(detailSelection(row))}</strong></div>
        <div class="ev-execution"><div class="ev-selection">${esc(detailSelection(row))}</div><div class="ev-bet-metrics"><span class="ev-bet-metric"><small>Rec Bet</small><strong>${money(row.recommendedStake)}</strong></span><span class="ev-bet-metric ev-to-win"><small>Total payout</small><strong>${profitMoney(totalPayout)}</strong></span></div>${executionAction(row, quote, state)}</div>
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
    detail.classList.remove("line-history-visible", "market-depth-open");
    detail.innerHTML = `<div class="ev-detail-empty il-state il-state-empty">
      <i class="ph ${isHiddenView ? "ph-eye-slash" : "ph-chart-line-up"}" aria-hidden="true"></i>
      <h2>${isHiddenView ? "No hidden bet selected" : "Select an opportunity"}</h2>
      <p>${isHiddenView ? "Hidden bets will appear here after you use Track and Hide." : "Inspect the fair price, EV calculation, best execution, liquidity, and the full market."}</p>
    </div>`;
    dismissDetail();
  }

  function setFullMarketDepthExpanded(expanded) {
    const button = detail.querySelector(".ev-full-market-button");
    const content = detail.querySelector(".ev-full-market-depth");
    if (!button || !content) return;
    button.setAttribute("aria-expanded", String(expanded));
    button.querySelector("span").textContent = expanded ? "Collapse market depth" : "View full market depth";
    button.querySelector("i").className = `ph ph-arrow-${expanded ? "up" : "right"}`;
    content.hidden = !expanded;
    detail.classList.toggle("market-depth-open", expanded);
  }

  function refreshSelectedDetail(row) {
    if (!row || String(row.id) !== String(selectedId)) return;
    const viewState = captureDetailViewState();
    const best = row.bestQuote || {};
    renderFeed();
    const setText = (selector, value) => {
      const node = detail.querySelector(selector);
      if (node) node.textContent = value;
    };
    setText("[data-detail-ev]", evPercent(row.evPercent));
    setText("[data-detail-event]", row.eventTitle);
    setText("[data-detail-start]", time(row.commenceTime));
    const start = detail.querySelector("[data-detail-start]");
    if (start) start.setAttribute("datetime", row.commenceTime || "");
    setText("[data-detail-selection]", detailSelection(row));
    setText("[data-detail-odds]", odds(best.topPriceAmericanOdds ?? best.americanOdds));
    setText("[data-detail-stake]", money(row.recommendedStake));
    setText('[data-trend-metric="ev"]', evPercent(row.evPercent));
    setText('[data-trend-metric="fv"]', odds(row.fairAmerican));

    const currentMarketOdds = detail.querySelector(".ev-market-comparison");
    const marketOddsMarkup = marketOddsVisual(row);
    if (currentMarketOdds && marketOddsMarkup) {
      const template = document.createElement("template");
      template.innerHTML = marketOddsMarkup.trim();
      currentMarketOdds.replaceWith(template.content.firstElementChild);
      bindMarketOddsControls(viewState.marketOddsExpanded);
    }
    const fullDepth = detail.querySelector(".ev-full-market-depth");
    if (fullDepth && viewState.marketDepthExpanded) {
      fullDepth.innerHTML = `${evExplanationVisual(row)}${sharpBooksVisual(row)}`;
      setFullMarketDepthExpanded(true);
    }
    loadLiveLineHistory(row, viewState);
  }

  function select(id) {
    selectedId=id; const row=rows.find(item=>item.id===id); if(!row)return;
    detail.classList.remove("market-depth-open");
    renderFeed(); const best=row.bestQuote||{};
    detail.innerHTML = `<article class="ev-detail-card ev-trend-detail"><div class="ev-detail-head"><strong data-detail-ev>${evPercent(row.evPercent)}</strong><div><h2 data-detail-event>${esc(row.eventTitle)}</h2><time class="ev-detail-start" data-detail-start datetime="${esc(row.commenceTime)}">${esc(time(row.commenceTime))}</time></div><button class="ev-detail-close icon-button" type="button" aria-label="Close detail"><i class="ph ph-x" aria-hidden="true"></i></button></div>
      <div class="ev-detail-pick ev-trend-pick"><strong><span class="ev-detail-selection" data-detail-selection>${esc(detailSelection(row))}</span> <span class="ev-detail-odds" data-detail-odds>${odds(best.topPriceAmericanOdds??best.americanOdds)}</span></strong><div class="ev-detail-stake" data-detail-stake>${money(row.recommendedStake)}</div></div>
      ${row.warnings.length ? `<div class="ev-warning-list">${row.warnings.map(warning=>`<span><i class="ph ph-warning"></i>${esc(warning)}</span>`).join("")}</div>` : ""}
      ${marketOddsVisual(row)}
      <section class="ev-section ev-market-trend il-detail-section"><header><h3>LINE MOVEMENT</h3></header><div class="ev-trend-metrics il-metric-group">
        <span class="il-metric positive"><small>EV</small><b data-trend-metric="ev">${evPercent(row.evPercent)}</b></span>
        <span class="il-metric"><small>FV</small><b data-trend-metric="fv">${odds(row.fairAmerican)}</b></span>
        <span class="il-metric"><small>1H</small><b data-trend-metric="1h">--</b></span>
        <span class="il-metric"><small>FIRST SEEN</small><b data-trend-metric="open">--</b></span>
      </div>${marketTrendVisual(row)}</section>
      <button class="ev-full-market-button" type="button" aria-expanded="false"><span>View full market depth</span><i class="ph ph-arrow-right" aria-hidden="true"></i></button>
      <div class="ev-full-market-depth" hidden>${evExplanationVisual(row)}${sharpBooksVisual(row)}</div>
    </article>`;
    bindTrendControls();
    bindMarketOddsControls();
    loadLiveLineHistory(row);
    detail.querySelector(".ev-detail-close").addEventListener("click", closeDetail);
    detail.querySelector(".ev-full-market-button")?.addEventListener("click", event => setFullMarketDepthExpanded(event.currentTarget.getAttribute("aria-expanded") !== "true"));
    detail.classList.add("open", "line-history-visible");
    detail.closest(".ev-workspace")?.classList.add("detail-open");
    detail.removeAttribute("inert");
    detail.setAttribute("aria-hidden", "false");
    detail.scrollTop = 0;
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
    lineHistoryRequestId += 1;
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
  function applyFilters(){
    if (!updateFilterValidity()) return;
    settings.group="custom";
    settings.markets=[...document.querySelectorAll("[data-market-key]:checked:not(:disabled)")].map(input=>input.dataset.marketKey);
    settings.sports=[...document.querySelectorAll('input[name="sports"]:checked')].map(i=>i.value);
    settings.books=[...$("ev-execution-books").querySelectorAll("input:checked")].map(i=>i.value);
    settings.requiredBooks=[...document.querySelectorAll("[data-required-book]:checked")].map(i=>i.dataset.requiredBook);
    settings.devigMethod=document.querySelector('input[name="devig-method"]:checked')?.value || defaults.devigMethod;
    [["ev-min-ev","minEv"],["ev-kelly","kelly"],["ev-min-sources","minSources"]].forEach(([id,key]) => settings[key]=Number($(id).value || defaults[key]));
    settings.minSources = Math.max(3, Math.min(5, settings.minSources));
    settings.weights=Object.fromEntries([...document.querySelectorAll("[data-weight]")].map(i=>[i.dataset.weight,Number(i.value||0)]));
    settings.catalogVersion = catalogVersion;
    localStorage.setItem("iconlabs-ev-settings",JSON.stringify(settings));updateToolbarFilterCount();dialog.close();load(true);
  }
  $("ev-filter-open").addEventListener("click",openFilters);$("ev-adjust-filters").addEventListener("click",openFilters);$("ev-filter-close").addEventListener("click",()=>dialog.close());$("ev-apply").addEventListener("click",applyFilters);
  $("ev-reset").addEventListener("click",()=>{settings={...defaults,weights:{...defaults.weights},books:[...defaults.books],requiredBooks:[...defaults.requiredBooks],sports:[...defaults.sports],markets:[...defaults.markets]};renderFilters();});
  $("ev-required-books-clear").addEventListener("click",()=>{document.querySelectorAll("[data-required-book]").forEach(input=>input.checked=false);updateRequiredBooksSummary();});
  $("ev-refresh").addEventListener("click",()=>{closeHiddenMenu();load(true);});$("ev-search").addEventListener("input",syncSearchSelection);scrim.addEventListener("click",closeDetail);
  $("ev-more-menu-toggle").addEventListener("click", event => {
    event.stopPropagation();
    setToolbarPopover("ev-bankroll-popover-button", "ev-bankroll-popover", false);
    const menu = $("ev-more-menu");
    menu.hidden = !menu.hidden;
    $("ev-more-menu-toggle").setAttribute("aria-expanded", String(!menu.hidden));
    if (!menu.hidden) requestAnimationFrame(() => menu.querySelector('[aria-current="true"]')?.focus());
  });
  $("ev-more-menu").addEventListener("click", event => {
    const option = event.target.closest("[data-feed-view]");
    if (option) setFeedView(option.dataset.feedView);
  });
  $("ev-bankroll-popover-button").addEventListener("click", event => {
    event.stopPropagation();
    closeHiddenMenu();
    const panel = $("ev-bankroll-popover");
    setToolbarPopover("ev-bankroll-popover-button", "ev-bankroll-popover", panel.hidden);
  });
  $("ev-save-bankroll").addEventListener("click", saveBankroll);
  $("ev-bankroll-input").addEventListener("input",()=>{
    bankrollConfig.dirty = true;
    $("ev-bankroll-save-state").textContent = "Unsaved changes";
    $("ev-bankroll-save-state").dataset.state = "unsaved";
  });
  $("ev-bankroll-input").addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();saveBankroll();}});
  document.addEventListener("click", event => {
    if (!event.target.closest(".ev-more-menu-wrap")) closeHiddenMenu();
    if (!event.target.closest(".ev-toolbar-popover-shell")) setToolbarPopover("ev-bankroll-popover-button", "ev-bankroll-popover", false);
  });
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    if (!$("ev-more-menu").hidden) { event.preventDefault(); closeHiddenMenu(true); }
    if (!$("ev-bankroll-popover").hidden) { event.preventDefault(); setToolbarPopover("ev-bankroll-popover-button", "ev-bankroll-popover", false); $("ev-bankroll-popover-button").focus(); }
  });
  $("ev-pause").addEventListener("click",()=>{paused=!paused;closeHiddenMenu();updateHiddenMenu();if(!paused)load(true);});
  dialog.querySelectorAll("[data-panel]").forEach(button=>button.addEventListener("click",()=>{dialog.querySelectorAll("[data-panel], [data-filter-panel]").forEach(item=>item.classList.remove("active"));button.classList.add("active");dialog.querySelector(`[data-filter-panel="${button.dataset.panel}"]`).classList.add("active");}));
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
  window.addEventListener("iconlabs:line-shop-order",()=>{
    const selected=rows.find(item=>String(item.id)===String(selectedId));
    const section=detail.querySelector(".ev-market-comparison");
    if(!selected||!section)return;
    const expanded=section.classList.contains("is-expanded");
    const template=document.createElement("template");
    template.innerHTML=marketOddsVisual(selected).trim();
    section.replaceWith(template.content.firstElementChild);
    bindMarketOddsControls(expanded);
  });
  renderFilters();
  loadBankrollSettings().finally(()=>load(true));
})();
