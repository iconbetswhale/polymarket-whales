(() => {
  const defaults = {
    group: "main",
    sports: ["baseball_mlb", "basketball_wnba"],
    books: ["novig", "prophetx", "fourcx", "kalshi", "polymarket", "pinnacle", "betonlineag", "fanduel", "draftkings"],
    devig: "power",
    minEv: 1,
    bankroll: 10000,
    kelly: .25,
    minSources: 3,
    maxQuoteAge: 180,
    maxDispersion: 12,
    maxStakePct: 2,
    maxEventPct: 5,
    weights: {pinnacle:40,betonlineag:20,novig:10,prophetx:10,fourcx:8,kalshi:7,polymarket:5,fanduel:5,draftkings:5}
  };
  const bookNames = {pinnacle:"Pinnacle",betonlineag:"BetOnline",novig:"Novig",prophetx:"ProphetX",fourcx:"4CX",kalshi:"Kalshi",polymarket:"Polymarket",fanduel:"FanDuel",draftkings:"DraftKings"};
  const bookLogos = {novig:"/static/assets/providers/novig.png",prophetx:"/static/assets/providers/prophetx.ico",kalshi:"/static/assets/providers/kalshi.png",polymarket:"https://polymarket.com/icons/favicon-32x32.png",pinnacle:"/static/assets/providers/pinnacle.png",betonlineag:"/static/assets/sportsbooks/betonline.png",fanduel:"https://sportsbook.fanduel.com/favicon.ico",draftkings:"https://sportsbook.draftkings.com/favicon.ico",fourcx:"/static/assets/providers/4cx.png"};
  let settings = {...defaults, weights:{...defaults.weights}, books:[...defaults.books], sports:[...defaults.sports]};
  try { settings = {...settings, ...JSON.parse(localStorage.getItem("iconlabs-ev-settings") || "{}")}; } catch {}
  let rows = [], selectedId = "", paused = false, timer = null;
  // The optimizer is credit-safe for now, so the public board intentionally
  // renders the isolated five-row visual feed instead of starting paid scans.
  const previewOnly = true;
  const $ = id => document.getElementById(id);
  const feed = $("ev-feed"), detail = $("ev-detail"), dialog = $("ev-filter-dialog"), scrim = $("ev-mobile-scrim");
  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const money = value => `$${Number(value || 0).toLocaleString(undefined,{maximumFractionDigits:2})}`;
  const odds = value => `${Number(value) > 0 ? "+" : ""}${Number(value || 0)}`;
  const time = value => { const date = new Date(value); return Number.isNaN(date.valueOf()) ? "" : date.toLocaleTimeString([],{hour:"numeric",minute:"2-digit"}); };
  const img = (url, name) => {
    const label = bookNames[name] || name || "Sportsbook";
    const source = bookLogos[name] || url || "";
    return source
      ? `<span class="ev-book-mark"><img class="ev-book-logo" src="${esc(source)}" alt="${esc(label)} logo"><span class="ev-book-fallback" aria-hidden="true">${esc(label.slice(0, 1))}</span></span>`
      : `<span class="ev-book-mark fallback" aria-label="${esc(label)}"><span class="ev-book-fallback" aria-hidden="true">${esc(label.slice(0, 1))}</span></span>`;
  };
  const statusLabel = row => row.portfolioStatus !== "qualified" ? "Suppressed" : row.executionStatus === "executable" ? "Executable" : "Verify liquidity";
  const chartPath = points => points.map((point, index) => `${index ? "L" : "M"}${point[0].toFixed(1)} ${point[1].toFixed(1)}`).join(" ");
  const stableSeed = value => [...String(value || "")].reduce((total, character) => total + character.charCodeAt(0), 0);

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
      return `<path class="ev-trend-line" d="${chartPath(points)}" stroke="${item.color}"></path>${points.map(point=>`<circle cx="${point[0].toFixed(1)}" cy="${point[1].toFixed(1)}" r="2.5" fill="${item.color}"></circle>`).join("")}`;
    }).join("");
    const limitValues = [350, 450, 700, 900, 1200, 1450, 1850, 2300, 2800];
    const limitY = value => top + ((3000 - value) / 3000) * (height - top - bottom);
    const limitPoints = limitValues.map((value,index)=>[x(index),limitY(value)]);
    const grid = [0,.25,.5,.75,1].map(ratio=>{
      const gridY=top+ratio*(height-top-bottom);
      const label=Math.round(maxOdds-ratio*(maxOdds-minOdds));
      return `<line x1="${left}" y1="${gridY}" x2="${width-right}" y2="${gridY}" class="ev-trend-grid"></line><text x="4" y="${gridY+4}" class="ev-trend-axis">${odds(label)}</text>`;
    }).join("");
    return `<div class="ev-trend-chart" aria-label="Visual preview of the requested market trend chart">
      <div class="ev-trend-chart-title"><strong>${esc(row.selection)}</strong><span>${esc(row.eventTitle)}</span></div>
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Preview trend lines for selected book, Pinnacle, BookMaker, Circa, and Pinnacle limits">
        ${grid}<text x="${width-right-2}" y="${top+4}" text-anchor="end" class="ev-trend-limit-label">$3k</text><text x="${width-right-2}" y="${height-bottom+4}" text-anchor="end" class="ev-trend-limit-label">$0</text>
        ${paths}<path class="ev-trend-limit" d="${chartPath(limitPoints)}"></path>${limitPoints.map(point=>`<circle cx="${point[0].toFixed(1)}" cy="${point[1].toFixed(1)}" r="2.4" fill="#f4f5f8"></circle>`).join("")}
        <text x="${left}" y="${height-10}" class="ev-trend-axis">Open</text><text x="${width/2}" y="${height-10}" text-anchor="middle" class="ev-trend-axis">1h</text><text x="${width-right}" y="${height-10}" text-anchor="end" class="ev-trend-axis">Now</text>
      </svg>
      <div class="ev-trend-legend">${series.map(item=>`<span style="--legend:${item.color}">${esc(item.name)}</span>`).join("")}<span style="--legend:#f4f5f8">Pinnacle limits</span></div>
      <p class="ev-trend-preview-note"><i class="ph ph-eye"></i> Visual preview only. Historical movement and limits are collecting; current EV, FV, price, and stake use the selected opportunity.</p>
    </div>`;
  }

  function marketOddsVisual(row) {
    const quotes = [...(row.quotes || [])].sort((left, right) =>
      Number(right.topPriceAmericanOdds ?? right.americanOdds ?? -10000) - Number(left.topPriceAmericanOdds ?? left.americanOdds ?? -10000)
    );
    if (!quotes.length) return "";
    const bestOdds = quotes[0].topPriceAmericanOdds ?? quotes[0].americanOdds;
    const quoteRow = (quote, index) => {
      const quoteOdds = quote.topPriceAmericanOdds ?? quote.americanOdds;
      const detailText = quote.topPriceLiquidity != null
        ? `${money(quote.topPriceLiquidity)} available`
        : quote.marketLimit != null
          ? `${money(quote.marketLimit)} limit`
          : quote.executionStatus === "executable"
            ? "Executable"
            : String(quote.executionStatus || "Price available").replaceAll("_", " ");
      const content = `<span class="ev-market-rank">${index + 1}</span>${img(quote.logoUrl, quote.bookKey)}<span class="ev-market-book"><strong>${esc(quote.bookName || bookNames[quote.bookKey] || quote.bookKey)}</strong><small>${esc(detailText)}</small></span><span class="ev-market-price"><strong>${odds(quoteOdds)}</strong><small>${Number(quote.evPercent) >= 0 ? "+" : ""}${Number(quote.evPercent || 0).toFixed(2)}% EV</small></span>${Number(quoteOdds) === Number(bestOdds) ? '<em>BEST</em>' : ""}`;
      return quote.deepLink && quote.deepLink !== "#"
        ? `<a class="ev-market-quote ${index === 0 ? "best" : ""}" href="${esc(quote.deepLink)}" target="_blank" rel="noopener">${content}<i class="ph ph-arrow-up-right"></i></a>`
        : `<div class="ev-market-quote ${index === 0 ? "best" : ""}">${content}</div>`;
    };
    return `<section class="ev-market-odds"><header><div><h3>MARKET ODDS</h3><span>${quotes.length} available books</span></div><div class="ev-market-best"><small>BEST PRICING</small><strong>${odds(bestOdds)}</strong></div></header><div class="ev-market-side"><span>${esc(row.selection)}</span><small>Ranked by available price</small></div><div class="ev-market-quotes">${quotes.map(quoteRow).join("")}</div></section>`;
  }

  function renderFilters() {
    document.querySelectorAll('input[name="marketGroup"]').forEach(input => input.checked = input.value === settings.group);
    document.querySelectorAll('input[name="sports"]').forEach(input => input.checked = settings.sports.includes(input.value));
    document.querySelectorAll('input[name="devig"]').forEach(input => input.checked = input.value === settings.devig);
    [["ev-min-ev","minEv"],["ev-bankroll","bankroll"],["ev-kelly","kelly"],["ev-min-sources","minSources"],["ev-max-quote-age","maxQuoteAge"],["ev-max-dispersion","maxDispersion"],["ev-max-stake-pct","maxStakePct"],["ev-max-event-pct","maxEventPct"]].forEach(([id,key]) => { if ($(id)) $(id).value = settings[key]; });
    $("ev-execution-books").innerHTML = Object.keys(bookNames).map(key => `<label><input type="checkbox" value="${key}" ${settings.books.includes(key)?"checked":""}><span>${img(bookLogos[key],key)}${bookNames[key]}</span></label>`).join("");
    $("ev-weight-list").innerHTML = Object.entries(settings.weights).map(([key,value]) => `<div class="ev-weight-row"><label for="weight-${key}">${esc(bookNames[key] || key)}</label><input id="weight-${key}" data-weight="${key}" type="number" min="0" max="100" step="1" value="${Number(value)}"></div>`).join("");
    updateWeightTotal();
  }
  function updateWeightTotal(){ $("ev-weight-total").textContent = `${[...document.querySelectorAll("[data-weight]")].reduce((sum,input)=>sum+Number(input.value||0),0)}%`; }
  function query() {
    const params = new URLSearchParams({group:settings.group,sports:settings.sports.join(","),books:settings.books.join(","),devig:settings.devig,min_ev:settings.minEv,bankroll:settings.bankroll,kelly:settings.kelly,min_sources:settings.minSources,max_quote_age:settings.maxQuoteAge,max_dispersion:settings.maxDispersion,max_stake_pct:settings.maxStakePct,max_event_pct:settings.maxEventPct,weights:JSON.stringify(settings.weights)});
    if (previewOnly) params.set("preview", "1");
    return `/api/positive-ev?${params}`;
  }
  function renderDiagnostics(diagnostics = {}, history = {}) {
    const reasons = diagnostics.rejectionReasons || {};
    const topReason = Object.entries(reasons).sort((a,b)=>b[1]-a[1])[0];
    const bookClv = history.averageRespectiveBookClvPoints == null ? "collecting" : `${Number(history.averageRespectiveBookClvPoints) >= 0 ? "+" : ""}${Number(history.averageRespectiveBookClvPoints).toFixed(2)} pts`;
    const compositeClv = history.averageCompositeClvPoints == null ? "collecting" : `${Number(history.averageCompositeClvPoints) >= 0 ? "+" : ""}${Number(history.averageCompositeClvPoints).toFixed(2)} pts`;
    $("ev-credit-banner").innerHTML = `<i class="ph ph-shield-check"></i><span><strong>${Number(diagnostics.qualified || 0)} executable</strong> · ${Number(diagnostics.watchOnly || 0)} watch-only · ${Number(diagnostics.rejected || 0)} rejected${topReason ? ` · most common: ${esc(topReason[0].replaceAll("_"," "))}` : ""}</span><span class="ev-history-stat">Tracked ${Number(history.opportunities || 0)} · book CLV ${bookClv} · composite ${compositeClv}</span><button id="ev-adjust-filters" type="button">Adjust filters</button>`;
    $("ev-adjust-filters").addEventListener("click", openFilters);
  }
  async function load(force=false) {
    if (paused && !force) return;
    feed.innerHTML = `<div class="ev-loading"><span></span><p>Validating exact markets and executable prices...</p></div>`;
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
        $("ev-credit-banner").innerHTML = `<i class="ph ph-shield-check"></i><span><strong>EV optimizer paused</strong> · No paid odds requests or refreshes are running.</span>`;
        feed.innerHTML = `<div class="ev-empty"><i class="ph ph-pause-circle"></i><p>${esc(payload.message || "Positive EV scanning is paused.")}</p></div>`;
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
        $("ev-credit-banner").innerHTML = `<i class="ph ph-eye"></i><span><strong>5 temporary preview plays</strong> · Visual fixtures only · never tracked, signaled, or sent to a sportsbook.</span>`;
      }
      const nextSelectedId = rows.some(row=>row.id===selectedId) ? selectedId : rows[0]?.id;
      if (nextSelectedId) select(nextSelectedId);
      else { selectedId = ""; renderFeed(); dismissDetail(); }
      clearTimeout(timer);
      if (!payload.previewOnly && Number(payload.refreshSeconds) > 0) timer = setTimeout(load, Number(payload.refreshSeconds) * 1000);
    } catch (error) {
      feed.innerHTML = `<div class="ev-empty"><i class="ph ph-warning-circle"></i><p>${esc(error.message)}</p></div>`;
    }
  }
  function visibleRows() {
    const search = $("ev-search").value.trim().toLowerCase();
    return rows.filter(row => !search || `${row.eventTitle} ${row.selection} ${row.marketLabel} ${row.league}`.toLowerCase().includes(search));
  }
  function renderFeed() {
    const shown = visibleRows();
    if (!shown.length) { feed.innerHTML = `<div class="ev-empty"><i class="ph ph-shield-check"></i><p>No opportunity passed every validation gate. That is safer than displaying a false edge.</p></div>`; return; }
    feed.innerHTML = shown.map(row => {
      const quote=row.bestQuote||{}, state = row.executionStatus === "executable" && row.portfolioStatus === "qualified" ? "executable" : "watch";
      return `<button class="ev-opportunity ${row.id===selectedId?"active":""} ${state}" type="button" data-id="${esc(row.id)}" aria-pressed="${row.id===selectedId}">
        <div class="ev-score"><strong>${Number(row.evPercent).toFixed(2)}%</strong></div>
        <div class="ev-event"><time>${esc(time(row.commenceTime))}</time><strong>${esc(row.eventTitle)}</strong></div>
        <div class="ev-pick"><small><i class="ph ph-globe-hemisphere-west"></i>${esc(row.league)}</small><strong>${esc(row.selection)}</strong><em>${esc(row.marketLabel)}</em></div>
        <div class="ev-execution"><div class="ev-selection">${esc(row.line ?? row.selection)}</div><div class="ev-stake"><strong>${money(row.recommendedStake)}</strong></div><a class="ev-best-button ${state}" href="${esc(quote.deepLink||"#")}" target="_blank" rel="noopener" aria-label="Open ${esc(quote.bookName||quote.bookKey)} at ${odds(quote.topPriceAmericanOdds??quote.americanOdds)}">${img(quote.logoUrl,quote.bookKey)}<span>${odds(quote.topPriceAmericanOdds??quote.americanOdds)}<i class="ph ph-arrow-up-right"></i></span></a></div>
      </button>`;
    }).join("");
    feed.querySelectorAll(".ev-opportunity").forEach(button => button.addEventListener("click", event => { if(event.target.closest("a")) return; select(button.dataset.id); }));
  }
  function select(id) {
    selectedId=id; const row=rows.find(item=>item.id===id); if(!row)return;
    renderFeed(); const best=row.bestQuote||{};
    detail.innerHTML = `<article class="ev-detail-card ev-trend-detail"><div class="ev-detail-head"><strong>${Number(row.evPercent).toFixed(2)}%</strong><div><h2>${esc(row.eventTitle)}</h2></div><button class="ev-detail-close" type="button" aria-label="Close detail"><i class="ph ph-x"></i></button></div>
      <div class="ev-detail-pick ev-trend-pick"><strong>${esc(row.selection)} <span>${odds(best.topPriceAmericanOdds??best.americanOdds)}</span></strong><div class="ev-detail-stake">${money(row.recommendedStake)}</div></div>
      ${row.warnings.length ? `<div class="ev-warning-list">${row.warnings.map(warning=>`<span><i class="ph ph-warning"></i>${esc(warning)}</span>`).join("")}</div>` : ""}
      <section class="ev-section ev-market-trend"><header><h3>MARKET TREND</h3><span>Current values + preview history</span></header><div class="ev-trend-metrics">
        <span><small>EV</small><b>${Number(row.evPercent).toFixed(2)}%</b></span>
        <span><small>FV</small><b>${odds(row.fairAmerican)}</b></span>
        <span><small>1H</small><b>--</b></span>
        <span><small>OPEN</small><b>--</b></span>
      </div>${marketTrendVisual(row)}${marketOddsVisual(row)}</section>
    </article>`;
    detail.querySelector(".ev-detail-close").addEventListener("click", closeDetail);
    detail.classList.add("open");
    detail.closest(".ev-workspace")?.classList.add("detail-open");
    $("ev-detail-toggle")?.setAttribute("aria-pressed", "true");
    if (matchMedia("(max-width:900px)").matches) scrim.hidden=false;
  }
  function dismissDetail(){detail.classList.remove("open");detail.closest(".ev-workspace")?.classList.remove("detail-open");scrim.hidden=true;$("ev-detail-toggle")?.setAttribute("aria-pressed", "false");}
  function closeDetail(){
    if (matchMedia("(min-width:901px)").matches && rows.length) {
      if (!detail.classList.contains("open")) select(rows.some(row=>row.id===selectedId) ? selectedId : rows[0].id);
      return;
    }
    dismissDetail();
  }
  function syncSearchSelection(){
    const shown = visibleRows();
    if (shown.length && !shown.some(row=>row.id===selectedId)) select(shown[0].id);
    else renderFeed();
  }
  function openFilters(){renderFilters();dialog.showModal();}
  function applyFilters(){
    settings.group=document.querySelector('input[name="marketGroup"]:checked').value;
    settings.sports=[...document.querySelectorAll('input[name="sports"]:checked')].map(i=>i.value);
    settings.books=[...$("ev-execution-books").querySelectorAll("input:checked")].map(i=>i.value);
    settings.devig=document.querySelector('input[name="devig"]:checked').value;
    [["ev-min-ev","minEv"],["ev-bankroll","bankroll"],["ev-kelly","kelly"],["ev-min-sources","minSources"],["ev-max-quote-age","maxQuoteAge"],["ev-max-dispersion","maxDispersion"],["ev-max-stake-pct","maxStakePct"],["ev-max-event-pct","maxEventPct"]].forEach(([id,key]) => settings[key]=Number($(id).value || defaults[key]));
    settings.weights=Object.fromEntries([...document.querySelectorAll("[data-weight]")].map(i=>[i.dataset.weight,Number(i.value||0)]));
    localStorage.setItem("iconlabs-ev-settings",JSON.stringify(settings));dialog.close();load(true);
  }
  $("ev-filter-open").addEventListener("click",openFilters);$("ev-adjust-filters").addEventListener("click",openFilters);$("ev-filter-close").addEventListener("click",()=>dialog.close());$("ev-apply").addEventListener("click",applyFilters);
  $("ev-detail-toggle")?.addEventListener("click",()=>{ if(detail.classList.contains("open")) closeDetail(); else if(selectedId) select(selectedId); });
  $("ev-reset").addEventListener("click",()=>{settings={...defaults,weights:{...defaults.weights},books:[...defaults.books],sports:[...defaults.sports]};renderFilters();});
  $("ev-refresh").addEventListener("click",()=>load(true));$("ev-search").addEventListener("input",syncSearchSelection);scrim.addEventListener("click",closeDetail);
  $("ev-pause").addEventListener("click",()=>{paused=!paused;$("ev-pause").setAttribute("aria-pressed",String(paused));$("ev-pause").innerHTML=`<i class="ph ph-${paused?"play":"pause"}"></i>`;$("ev-feed-label").textContent=paused?"Refresh paused":"Validated market scan";if(!paused)load(true);});
  dialog.querySelectorAll("[data-panel]").forEach(button=>button.addEventListener("click",()=>{dialog.querySelectorAll("[data-panel], [data-filter-panel]").forEach(item=>item.classList.remove("active"));button.classList.add("active");dialog.querySelector(`[data-filter-panel="${button.dataset.panel}"]`).classList.add("active");}));
  dialog.addEventListener("input",event=>{if(event.target.matches("[data-weight]"))updateWeightTotal();});
  dialog.addEventListener("click",event=>{if(event.target===dialog)dialog.close();});
  dialog.addEventListener("keydown",event=>{if(event.key==="Escape"){event.preventDefault();dialog.close();}});
  document.addEventListener("error",event=>{if(event.target.matches(".ev-book-logo")){event.target.hidden=true;event.target.parentElement.classList.add("fallback");}},true);
  renderFilters(); load(true);
})();
