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
  const bookLogos = {novig:"https://novig.us/favicon.ico",prophetx:"/static/assets/providers/prophetx.ico",kalshi:"/static/assets/providers/kalshi.png",polymarket:"https://polymarket.com/icons/favicon-32x32.png",pinnacle:"https://www.pinnacle.com/favicon.ico",betonlineag:"https://sports.betonline.ag/favicon.ico",fanduel:"https://sportsbook.fanduel.com/favicon.ico",draftkings:"https://sportsbook.draftkings.com/favicon.ico",fourcx:"/static/assets/providers/4cx.png"};
  let settings = {...defaults, weights:{...defaults.weights}, books:[...defaults.books], sports:[...defaults.sports]};
  try { settings = {...settings, ...JSON.parse(localStorage.getItem("iconlabs-ev-settings") || "{}")}; } catch {}
  let rows = [], selectedId = "", paused = false, timer = null;
  const previewOnly = new URLSearchParams(window.location.search).get("preview") === "1";
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
      renderFeed();
      if (selectedId && rows.some(row=>row.id===selectedId)) select(selectedId);
      clearTimeout(timer);
      if (!payload.previewOnly && Number(payload.refreshSeconds) > 0) timer = setTimeout(load, Number(payload.refreshSeconds) * 1000);
    } catch (error) {
      feed.innerHTML = `<div class="ev-empty"><i class="ph ph-warning-circle"></i><p>${esc(error.message)}</p></div>`;
    }
  }
  function renderFeed() {
    const search = $("ev-search").value.trim().toLowerCase();
    const shown = rows.filter(row => !search || `${row.eventTitle} ${row.selection} ${row.marketLabel} ${row.league}`.toLowerCase().includes(search));
    if (!shown.length) { feed.innerHTML = `<div class="ev-empty"><i class="ph ph-shield-check"></i><p>No opportunity passed every validation gate. That is safer than displaying a false edge.</p></div>`; return; }
    feed.innerHTML = shown.map(row => {
      const quote=row.bestQuote||{}, state = row.executionStatus === "executable" && row.portfolioStatus === "qualified" ? "executable" : "watch";
      return `<button class="ev-opportunity ${row.id===selectedId?"active":""} ${state}" type="button" data-id="${esc(row.id)}">
        <div class="ev-score"><strong>${Number(row.evPercent).toFixed(2)}%</strong><span>${Math.round(Number(row.fairProbability)*100)}% fair</span><em>${row.previewOnly ? "PREVIEW ONLY" : esc(statusLabel(row))}</em></div>
        <div class="ev-event"><time>${esc(time(row.commenceTime))}</time><strong>${esc(row.eventTitle)}</strong><small>${esc(row.league)} · ${Number(row.sourceCount)} sources</small></div>
        <div class="ev-pick"><small>${esc(row.marketLabel)}</small><strong>${esc(row.selection)}</strong><small>${(Number(row.fairConfidence)*100).toFixed(0)}% model confidence</small></div>
        <div class="ev-execution"><div class="ev-selection">${esc(row.selection)}<small>${esc(row.marketLabel)}</small></div><div class="ev-stake"><strong>${money(row.recommendedStake)}</strong><small>${row.executionStatus === "executable" ? "constrained stake" : `${money(row.theoreticalStake)} raw Kelly`}</small></div><a class="ev-best-button ${state}" href="${esc(quote.deepLink||"#")}" target="_blank" rel="noopener">${img(quote.logoUrl,quote.bookKey)}<span>${odds(quote.topPriceAmericanOdds??quote.americanOdds)}<small>${esc(quote.bookName||quote.bookKey)}</small></span></a></div>
      </button>`;
    }).join("");
    feed.querySelectorAll(".ev-opportunity").forEach(button => button.addEventListener("click", event => { if(event.target.closest("a")) return; select(button.dataset.id); }));
  }
  function select(id) {
    selectedId=id; const row=rows.find(item=>item.id===id); if(!row)return;
    renderFeed(); const best=row.bestQuote||{}, quoteEvs=row.quotes.map(q=>Math.abs(Number(q.evPercent || 0))), maxEv=Math.max(1,...quoteEvs);
    detail.innerHTML = `<article class="ev-detail-card"><div class="ev-detail-head"><strong>${Number(row.evPercent).toFixed(2)}%</strong><div><h2>${esc(row.eventTitle)}</h2><p>${esc(row.marketLabel)} · ${esc(time(row.commenceTime))} · ${esc(statusLabel(row))}</p></div><button class="ev-detail-close" type="button" aria-label="Close detail"><i class="ph ph-x"></i></button></div>
      <div class="ev-detail-pick"><div><small>CONSTRAINED RECOMMENDATION</small><strong>${esc(row.selection)}</strong></div><div class="ev-detail-stake">${money(row.recommendedStake)}</div></div>
      ${row.warnings.length ? `<div class="ev-warning-list">${row.warnings.map(warning=>`<span><i class="ph ph-warning"></i>${esc(warning)}</span>`).join("")}</div>` : ""}
      <section class="ev-section"><header><h3>FAIR-PRICE AUDIT</h3><span>${Number(row.sourceCount)} independent books</span></header><div class="ev-audit-grid"><span><small>Fair probability</small><b>${(Number(row.fairProbability)*100).toFixed(2)}%</b></span><span><small>Fair odds</small><b>${odds(row.fairAmerican)}</b></span><span><small>Confidence</small><b>${(Number(row.fairConfidence)*100).toFixed(0)}%</b></span><span><small>Source spread</small><b>${(Number(row.sourceDispersion)*100).toFixed(2)} pts</b></span></div></section>
      <section class="ev-section"><header><h3>MARKET ODDS</h3><span>Execution book excluded from its own fair price</span></header><div class="ev-analysis">${row.quotes.slice(0,9).map(q=>`<div class="ev-analysis-row ${q.bookKey===best.bookKey?"best":""}">${img(q.logoUrl,q.bookKey)}<div class="bar"><i style="width:${Math.max(3,Math.abs(Number(q.evPercent||0))/maxEv*100)}%"></i></div><b>${Number(q.evPercent)>=0?"+":""}${Number(q.evPercent).toFixed(2)}%</b></div>`).join("")}</div><div class="ev-quotes">${row.quotes.map(q=>`<a class="ev-quote ${q.bookKey===best.bookKey?"best":""}" href="${esc(q.deepLink||"#")}" target="_blank" rel="noopener">${img(q.logoUrl,q.bookKey)}<span><strong>${esc(q.bookName)}</strong><small>${q.topPriceLiquidity != null ? `${money(q.topPriceLiquidity)} at top price` : q.marketLimit != null ? `${money(q.marketLimit)} reported limit` : `${esc(q.executionStatus.replaceAll("_"," "))} · ${q.quoteAgeSeconds == null ? "age unknown" : `${Math.round(q.quoteAgeSeconds)}s old`}`}</small></span><b>${odds(q.topPriceAmericanOdds??q.americanOdds)} ↗</b></a>`).join("")}</div></section>
      <section class="ev-section"><header><h3>SIZING AUDIT</h3><span>${(Number(row.fullKellyFraction)*100).toFixed(2)}% full Kelly</span></header><div class="ev-formula">Raw fractional Kelly: <strong>${money(row.theoreticalStake)}</strong><br>After confidence, per-bet, event, variance, and liquidity constraints: <b>${money(row.recommendedStake)}</b><br>Effective line after configured costs: ${odds(best.effectiveAmerican)}. Calculation: (${(Number(row.fairProbability)*100).toFixed(2)}% × ${Number(best.effectiveDecimal).toFixed(3)}) − 1 = <b>+${Number(row.evPercent).toFixed(2)}%</b>.</div></section></article>`;
    detail.querySelector(".ev-detail-close").addEventListener("click", closeDetail);
    if (matchMedia("(max-width:900px)").matches){ detail.classList.add("open"); scrim.hidden=false; }
  }
  function closeDetail(){detail.classList.remove("open");scrim.hidden=true;}
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
  $("ev-reset").addEventListener("click",()=>{settings={...defaults,weights:{...defaults.weights},books:[...defaults.books],sports:[...defaults.sports]};renderFilters();});
  $("ev-refresh").addEventListener("click",()=>load(true));$("ev-search").addEventListener("input",renderFeed);scrim.addEventListener("click",closeDetail);
  $("ev-pause").addEventListener("click",()=>{paused=!paused;$("ev-pause").setAttribute("aria-pressed",String(paused));$("ev-pause").innerHTML=`<i class="ph ph-${paused?"play":"pause"}"></i>`;$("ev-feed-label").textContent=paused?"Refresh paused":"Validated market scan";if(!paused)load(true);});
  dialog.querySelectorAll("[data-panel]").forEach(button=>button.addEventListener("click",()=>{dialog.querySelectorAll("[data-panel], [data-filter-panel]").forEach(item=>item.classList.remove("active"));button.classList.add("active");dialog.querySelector(`[data-filter-panel="${button.dataset.panel}"]`).classList.add("active");}));
  dialog.addEventListener("input",event=>{if(event.target.matches("[data-weight]"))updateWeightTotal();});
  dialog.addEventListener("click",event=>{if(event.target===dialog)dialog.close();});
  dialog.addEventListener("keydown",event=>{if(event.key==="Escape"){event.preventDefault();dialog.close();}});
  document.addEventListener("error",event=>{if(event.target.matches(".ev-book-logo")){event.target.hidden=true;event.target.parentElement.classList.add("fallback");}},true);
  renderFilters(); load(true);
})();
