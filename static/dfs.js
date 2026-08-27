(() => {
  const comparisonBooks = [
    {key:'fanduel', name:'FanDuel'}, {key:'novig', name:'NoVIG'},
    {key:'prophetx', name:'ProphetX'}, {key:'draftkings', name:'DraftKings'},
    {key:'pinnacle', name:'Pinnacle'}, {key:'circa', name:'Circa'},
    {key:'kalshi', name:'Kalshi'}, {key:'polymarket', name:'Polymarket'},
    {key:'prizepicks', name:'PrizePicks'}, {key:'underdog', name:'Underdog'},
    {key:'dk-pick6', name:'DK Pick6'}, {key:'betr', name:'Betr'},
    {key:'dabble', name:'Dabble'}, {key:'sleeper', name:'Sleeper'}
  ];
  const sourceOddsKeys = ['novig','prophetx','fanduel','draftkings','kalshi','polymarket','caesars','hard-rock','fliff','sleeper','betonline','pinnacle','parlay-play','propbuilder','bovada'];
  const selectedBookKeys = {'PrizePicks':'prizepicks','Underdog':'underdog','DK Pick6':'dk-pick6','Betr':'betr','Dabble':'dabble'};
  const marketTypes = {
    MLB: ['Bases','Earned Runs','Fantasy Score','Hits','Hits + Runs + RBIs','Home Runs','Pitching Outs','Runs','RBIs','Singles','Stolen Bases','Strikeouts','Total Bases','Walks'],
    WNBA: ['3-Pointers Made','Assists','Blocks','Fantasy Score','Points','Points + Assists','Points + Rebounds','Points + Rebounds + Assists','Rebounds','Steals','Turnovers'],
    NFL: ['Anytime Touchdowns','Completions','Fantasy Score','Interceptions','Passing Touchdowns','Passing Yards','Receptions','Receiving Yards','Rushing Attempts','Rushing Yards','Tackles + Assists'],
    NBA: ['3-Pointers Made','Assists','Blocks','Fantasy Score','Points','Points + Assists','Points + Rebounds','Points + Rebounds + Assists','Rebounds','Steals','Turnovers'],
    NHL: ['Assists','Blocked Shots','Fantasy Score','Goals','Goalie Saves','Points','Shots on Goal']
  };
  const allMarkets = [...new Set(Object.values(marketTypes).flat())].sort((a,b) => a.localeCompare(b));
  let rows = [];
  let hasLoadedRows = false;
  let loadFailed = false;
  let liveRefreshEnabled = true;
  let refreshDelayMs = 15000;
  let refreshTimer = null;
  let activeLoad = null;
  const body = document.querySelector('#dfs-body');
  const loadingState = document.querySelector('#dfs-loading');
  const emptyState = document.querySelector('#dfs-empty');
  const errorState = document.querySelector('#dfs-error');
  const statSelect = document.querySelector('#dfs-stat');
  const devigDialog = document.querySelector('#dfs-devig-dialog');
  const parlayGuideDialog = document.querySelector('#dfs-parlay-guide-dialog');
  const iconAlgoTooltipTrigger = document.querySelector('.dfs-algo-tooltip');
  const iconAlgoTooltipPopover = document.querySelector('#dfs-iconalgo-tooltip');
  const defaultWeights = {fanduel:30, novig:20, prophetx:15, draftkings:10, pinnacle:10, circa:7, kalshi:5, polymarket:3};
  const zeroWeights = Object.fromEntries(Object.keys(defaultWeights).map(key => [key,0]));
  const bestSlipOdds = {'PrizePicks':'-119','Underdog':'-107','DK Pick6':'-122','Betr':'-118','Dabble':'-122'};
  const dfsComparisonKeys = new Set([...Object.values(selectedBookKeys),'sleeper']);
  let activeBook = 'PrizePicks';
  let compareOrder = loadCompareOrder();
  let savedWeights = loadWeights();
  let draftWeights = {...savedWeights};
  let savedPresets = loadPresets();
  let activePreset = weightsMatch(savedWeights,defaultWeights) ? 'iconlabs' : '';
  const esc = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

  function loadWeights() {
    try {
      const stored = JSON.parse(localStorage.getItem('dfsDevigWeightsV2') || 'null');
      const validKeys = stored && Object.keys(defaultWeights).every(key => Number.isFinite(Number(stored[key])));
      const total = validKeys ? Object.values(defaultWeights).reduce((sum,_,index) => sum + Number(stored[Object.keys(defaultWeights)[index]]),0) : 0;
      return validKeys && total === 100 ? Object.fromEntries(Object.keys(defaultWeights).map(key => [key,Number(stored[key])])) : {...defaultWeights};
    } catch (_) { return {...defaultWeights}; }
  }

  function loadPresets() {
    try { const stored=JSON.parse(localStorage.getItem('dfsDevigPresets')||'[]'); return Array.isArray(stored) ? stored.filter(item=>item&&item.name&&item.weights) : []; }
    catch (_) { return []; }
  }

  function loadCompareOrder() {
    const defaults = comparisonBooks.map(book => book.key);
    try {
      const stored = JSON.parse(localStorage.getItem('dfsCompareBookOrder') || 'null');
      return Array.isArray(stored) && stored.length === defaults.length && defaults.every(key => stored.includes(key)) ? stored : defaults;
    } catch (_) { return defaults; }
  }

  function weightsMatch(a,b) { return Object.keys(defaultWeights).every(key => Number(a[key])===Number(b[key])); }

  function updateAlgoPresentation() {
    const customWeights = !weightsMatch(savedWeights,defaultWeights);
    const accessibleLabel = customWeights
      ? 'Your Odds using custom Devig Settings'
      : 'IconLabs Algo Odds using default weights';
    const tooltipLabel = customWeights
      ? 'Your Odds · custom Devig weights'
      : 'IconLabs Algo Odds · default weights';
    const head = document.querySelector('#dfs-algo-odds-head');
    head.setAttribute('aria-label',accessibleLabel);
    head.dataset.model = customWeights ? 'custom' : 'iconlabs';
    iconAlgoTooltipTrigger.setAttribute('aria-label',accessibleLabel);
    iconAlgoTooltipPopover.textContent = tooltipLabel;
  }

  function updateDevigSummary() {
    const total = Object.values(savedWeights).reduce((sum,value)=>sum+Number(value||0),0);
    document.querySelector('#dfs-devig-summary').textContent=`8 sharp books · ${total}%`;
  }

  function renderPresets() {
    document.querySelector('#dfs-algo-preset').classList.toggle('active',activePreset==='iconlabs');
    document.querySelector('#dfs-saved-presets').innerHTML=savedPresets.map((preset,index)=>`<button class="dfs-saved-preset ${activePreset===`custom-${index}`?'active':''}" type="button" data-preset-index="${index}">${esc(preset.name)}</button>`).join('');
    document.querySelector('#dfs-devig-delete').hidden=!/^custom-\d+$/.test(activePreset);
  }

  function fairProbability(row,targetLine) {
    if (!Number.isFinite(Number(targetLine))) return null;
    const lineKey = String(Number(targetLine));
    const exactSources = Number(row.exactSourcesByLine?.[lineKey] ?? row.sourceCount ?? 0);
    const reliability = Number(row.reliabilityByLine?.[lineKey] ?? row.reliability ?? 0);
    if (exactSources < 2 || !Number.isFinite(reliability) || reliability < 0.08) return null;
    const liveValue = row.hitByLine?.[lineKey] ?? row.hit;
    return Number.isFinite(Number(liveValue)) ? Number(liveValue) : null;
  }

  function fairAmericanOdds(probabilityPercent) {
    const probability = Number(probabilityPercent) / 100;
    if (!(probability > 0 && probability < 1)) return '—';
    if (Math.abs(probability - 0.5) < 1e-9) return '+100';
    const odds = probability > 0.5 ? -100 * probability / (1-probability) : 100 * (1-probability) / probability;
    const rounded = Math.round(odds);
    return rounded > 0 ? `+${rounded}` : String(rounded);
  }

  function americanOddsToProbability(odds) {
    const value = Number(odds);
    if (!Number.isFinite(value) || value === 0) return null;
    return value > 0 ? 100/(value+100) : Math.abs(value)/(Math.abs(value)+100);
  }

  function updateStats() {
    const current = statSelect.value;
    const sport = document.querySelector('#dfs-sport').value;
    const options = sport ? marketTypes[sport] : allMarkets;
    statSelect.innerHTML = '<option value="">All stats</option>' + options.map(stat => `<option>${esc(stat)}</option>`).join('');
    statSelect.value = options.includes(current) ? current : '';
  }

  function reorderHeaders() {
    const row = document.querySelector('#dfs-head-row');
    const selectedKey = selectedBookKeys[activeBook];
    compareOrder.forEach(key => {
      const header = row.querySelector(`[data-book-key="${key}"]`);
      header.hidden = key === selectedKey;
      row.appendChild(header);
    });
  }

  function selectedDfsLine(row) {
    const value = row.dfsLines?.[selectedBookKeys[activeBook]];
    if (value === null || value === undefined || value === '') return null;
    return Number.isFinite(Number(value)) ? Number(value) : null;
  }

  function displayedHitRate(row) {
    const activeLine = selectedDfsLine(row);
    return fairProbability(row,activeLine);
  }

  function compareByHitRate(a,b) {
    const aHit = displayedHitRate(a);
    const bHit = displayedHitRate(b);
    if (aHit === null && bHit !== null) return 1;
    if (aHit !== null && bHit === null) return -1;
    if (aHit !== null && bHit !== null && bHit !== aHit) return bHit-aHit;
    return String(a.player||'').localeCompare(String(b.player||''))
      || String(a.stat||'').localeCompare(String(b.stat||''))
      || String(a.side||'').localeCompare(String(b.side||''));
  }

  function render() {
    updateAlgoPresentation();
    const sport = document.querySelector('#dfs-sport').value;
    const date = document.querySelector('#dfs-date').value;
    const stat = statSelect.value;
    const side = document.querySelector('#dfs-side').value;
    const search = document.querySelector('#dfs-search').value.trim().toLowerCase();
    const visible = rows
      .filter(r => selectedDfsLine(r) !== null && (!sport || r.sport === sport) && (!date || date === 'this_week' || r.date === date) && (!stat || r.stat === stat) && (!side || r.side === side) && (!search || `${r.player} ${r.match}`.toLowerCase().includes(search)))
      .sort(compareByHitRate);
    body.innerHTML = visible.map(r => {
      const activeLine = selectedDfsLine(r);
      const fairHitRate = fairProbability(r,activeLine);
      const requiredProbability = americanOddsToProbability(bestSlipOdds[activeBook]);
      const probabilityEdgePoints = requiredProbability === null || fairHitRate === null ? null : fairHitRate - requiredProbability*100;
      const hitRateBand = probabilityEdgePoints === null
        ? 'below-threshold'
        : probabilityEdgePoints > 0
          ? 'positive-edge'
          : probabilityEdgePoints >= -2
            ? 'near-threshold'
            : 'negative-edge';
      const requiredPercent = requiredProbability === null ? '—' : `${(requiredProbability*100).toFixed(2)}%`;
      const edgeLabel = probabilityEdgePoints === null ? 'edge unavailable' : `${probabilityEdgePoints >= 0 ? '+' : ''}${probabilityEdgePoints.toFixed(2)} pp edge`;
      const oddsByKey = r.oddsByBook || Object.fromEntries(sourceOddsKeys.map((key,index) => [key,r.odds?.[index] ?? '—']));
      const cells = compareOrder.filter(key => key !== selectedBookKeys[activeBook]).map(key => {
        if (dfsComparisonKeys.has(key)) {
          const comparisonLine = r.dfsLines?.[key] ?? null;
          if (comparisonLine === null) return `<td class="book-cell dfs-market-cell muted" data-book-cell="${key}"><strong>—</strong></td>`;
          return `<td class="book-cell dfs-market-cell" data-book-cell="${key}"><strong>${esc(comparisonLine)}</strong></td>`;
        }
        const market = oddsByKey[key];
        const isStructuredMarket = market !== null && typeof market === 'object';
        const price = isStructuredMarket ? (market.odds ?? market.displayOdds ?? market.americanOdds) : market;
        const unavailable = price === null || price === undefined || price === '' || price === '—';
        const alternateLine = isStructuredMarket
          && Number.isFinite(Number(market.line))
          && Number(market.line) !== Number(activeLine)
          ? market.line
          : null;
        const classes = ['book-cell',unavailable?'muted':'',alternateLine===null?'':'has-alternate'].filter(Boolean).join(' ');
        return `<td class="${classes}" data-book-cell="${key}">${unavailable?'—':`<strong>${esc(price)}</strong>${alternateLine===null?'':`<small class="alternate-line">${esc(alternateLine)}</small>`}`}</td>`;
      }).join('');
      const oddsSource = weightsMatch(savedWeights,defaultWeights) ? 'IconLabs Algo Odds' : 'Your Odds from custom Devig weights';
      const hitDisplay = fairHitRate === null ? '—' : `${fairHitRate.toFixed(1)}%`;
      const exactSources = Number(r.exactSourcesByLine?.[String(Number(activeLine))] ?? r.sourceCount ?? 0);
      const hitTitle = fairHitRate === null ? 'Requires at least two reliable exact-line sportsbook sources' : `${fairHitRate.toFixed(1)}% fair hit rate from ${exactSources} exact sources · ${requiredPercent} required for ${activeBook} ${bestSlipOdds[activeBook]} · ${edgeLabel}`;
      const fairOdds = fairHitRate === null ? '—' : fairAmericanOdds(fairHitRate);
      const statDisplay = `${activeLine} ${r.stat}`;
      const selectedAppOdds = bestSlipOdds[activeBook] ?? '—';
      const selectedOddsTitle = `${activeBook} best available equivalent odds`;
      return `<tr><td class="player-col"><div class="dfs-player"><span><strong>${esc(r.player)}</strong><small>${esc(r.match)}</small><em>${esc(r.sport)} · ${esc(r.time)}</em></span></div></td><td><b class="dfs-side ${r.side.toLowerCase()}">${r.side}</b></td><td><strong class="dfs-stat">${esc(statDisplay)}</strong></td><td class="selected-line" title="${esc(selectedOddsTitle)}"><strong>${esc(selectedAppOdds)}</strong></td><td><span class="hit-rate ${hitRateBand}" title="${esc(hitTitle)}"><strong>${hitDisplay}</strong></span></td><td class="algo-odds-cell" title="${esc(oddsSource)}"><strong>${fairOdds}</strong></td>${cells}</tr>`;
    }).join('');
    loadingState.hidden = hasLoadedRows || loadFailed;
    errorState.hidden = !loadFailed || rows.length > 0;
    emptyState.hidden = !hasLoadedRows || loadFailed || visible.length > 0;
  }

  function clearAutoRefresh() {
    window.clearTimeout(refreshTimer);
    refreshTimer = null;
  }

  function scheduleAutoRefresh() {
    clearAutoRefresh();
    if (!liveRefreshEnabled || document.hidden) return;
    refreshTimer = window.setTimeout(loadLiveRows,refreshDelayMs);
  }

  function syncRefreshControls() {
    const liveButton = document.querySelector('#dfs-live');
    const pauseButton = document.querySelector('#dfs-pause');
    liveButton.classList.toggle('active',liveRefreshEnabled);
    pauseButton.classList.toggle('active',!liveRefreshEnabled);
    liveButton.setAttribute('aria-pressed',String(liveRefreshEnabled));
    pauseButton.setAttribute('aria-pressed',String(!liveRefreshEnabled));
  }

  function setLiveRefresh(enabled) {
    const wasLive = liveRefreshEnabled;
    liveRefreshEnabled = enabled;
    syncRefreshControls();
    clearAutoRefresh();
    if (!enabled) {
      if (wasLive) activeLoad?.controller.abort();
      return;
    }
    loadLiveRows();
  }

  async function loadLiveRows() {
    clearAutoRefresh();
    const button = document.querySelector('#dfs-refresh');
    const params = new URLSearchParams({weights:JSON.stringify(savedWeights),book:selectedBookKeys[activeBook]});
    const url = `/api/dfs/lines?${params}`;
    const cacheKey = pagePayloadCacheKey('dfs',params.toString());
    const signature = params.toString();
    if (activeLoad?.signature === signature) return activeLoad.promise;
    activeLoad?.controller.abort();
    if (!hasLoadedRows && !rows.length) {
      const cached = readPagePayloadCache(cacheKey,5*60*1000);
      if (cached) {
        rows = Array.isArray(cached.data) ? cached.data : [];
        hasLoadedRows = true;
        loadFailed = false;
        render();
      }
    }
    button?.classList.add('spinning');
    if (button) button.disabled = true;
    const controller = new AbortController();
    const promise = (async () => {
      try {
        const response = await fetch(url, {headers:{Accept:'application/json'}, cache:'no-store', signal:controller.signal});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || 'DFS odds unavailable');
        rows = Array.isArray(payload.data) ? payload.data : [];
        hasLoadedRows = true;
        loadFailed = false;
        const serverDelay = Number(payload.refreshSeconds)*1000;
        if (Number.isFinite(serverDelay)) refreshDelayMs = Math.max(5000,serverDelay);
        writePagePayloadCache(cacheKey,payload);
      } catch (error) {
        if (error.name === 'AbortError') return;
        hasLoadedRows = true;
        loadFailed = rows.length === 0;
      } finally {
        if (activeLoad?.promise !== promise) return;
        activeLoad = null;
        button?.classList.remove('spinning');
        if (button) button.disabled = false;
        render();
        scheduleAutoRefresh();
      }
    })();
    activeLoad = {signature,controller,promise};
    return promise;
  }

  function enableDrag(container, itemSelector, onDrop) {
    let dragged = null;
    container.addEventListener('dragstart', event => { dragged=event.target.closest(itemSelector); if(!dragged)return; dragged.classList.add('dragging'); event.dataTransfer.effectAllowed='move'; });
    container.addEventListener('dragend', () => { if(dragged)dragged.classList.remove('dragging'); dragged=null; });
    container.addEventListener('dragover', event => { const target=event.target.closest(itemSelector); if(!dragged || !target || target===dragged)return; event.preventDefault(); const box=target.getBoundingClientRect(); container.insertBefore(dragged, event.clientX < box.left + box.width/2 ? target : target.nextSibling); });
    container.addEventListener('drop', event => { if(!dragged)return; event.preventDefault(); onDrop(); });
  }

  function devigTotal() { return Object.values(draftWeights).reduce((sum,value) => sum + Number(value || 0),0); }

  function syncDevigControls() {
    const total = devigTotal();
    Object.keys(defaultWeights).forEach(key => {
      const range = document.querySelector(`[data-devig-key="${key}"]`);
      const number = document.querySelector(`[data-devig-number="${key}"]`);
      range.max = '100';
      number.max = '100';
      range.value = String(draftWeights[key]);
      number.value = String(draftWeights[key]);
    });
    document.querySelector('#dfs-devig-total').textContent = `${total}%`;
    document.querySelector('#dfs-devig-progress').style.width = `${Math.min(total,100)}%`;
    const message = document.querySelector('#dfs-devig-message');
    message.textContent = total === 100 ? 'Ready to replace IconLabs odds with Your Odds' : `${100-total}% left to allocate`;
    message.classList.toggle('ready',total===100);
    document.querySelector('#dfs-devig-apply').disabled = total !== 100;
  }

  function updateDevigWeight(key,rawValue) {
    const nextValue = Math.max(0,Math.min(100,Math.round(Number(rawValue)||0)));
    const otherTotal = Object.entries(draftWeights).reduce((sum,[item,value]) => item===key ? sum : sum + Number(value),0);
    draftWeights[key] = Math.min(nextValue,100-otherTotal);
    activePreset='';
    renderPresets();
    syncDevigControls();
  }

  function showIconAlgoTooltip() {
    iconAlgoTooltipPopover.hidden = false;
    const triggerRect = iconAlgoTooltipTrigger.getBoundingClientRect();
    const tooltipRect = iconAlgoTooltipPopover.getBoundingClientRect();
    const edge = 8;
    const gap = 8;
    const left = Math.min(
      window.innerWidth - tooltipRect.width - edge,
      Math.max(edge, triggerRect.left + (triggerRect.width - tooltipRect.width) / 2)
    );
    const above = triggerRect.top - tooltipRect.height - gap;
    const top = above >= edge ? above : triggerRect.bottom + gap;
    iconAlgoTooltipPopover.style.left = `${Math.round(left)}px`;
    iconAlgoTooltipPopover.style.top = `${Math.round(top)}px`;
  }

  function hideIconAlgoTooltip() {
    iconAlgoTooltipPopover.hidden = true;
  }

  function setActiveBook(button) {
    if (!button || !selectedBookKeys[button.dataset.dfsBook]) return;
    const changed = activeBook !== button.dataset.dfsBook;
    document.querySelectorAll('[data-dfs-book]').forEach(item => {
      item.classList.toggle('active',item===button);
      item.setAttribute('aria-selected',String(item===button));
    });
    activeBook = button.dataset.dfsBook;
    const lineHead = document.querySelector('#dfs-line-head');
    const logo = button.querySelector('img').cloneNode();
    const selectedOddsTitle = `${activeBook} best available equivalent odds`;
    logo.alt = activeBook;
    logo.title = selectedOddsTitle;
    lineHead.replaceChildren(logo);
    lineHead.setAttribute('aria-label',selectedOddsTitle);
    reorderHeaders();
    render();
    if (changed) loadLiveRows();
  }

  document.querySelectorAll('[data-dfs-book]').forEach(btn => btn.addEventListener('click', () => setActiveBook(btn)));
  enableDrag(document.querySelector('.dfs-book-row'), '.dfs-book', () => {});
  enableDrag(document.querySelector('#dfs-head-row'), '.compare-book', () => { compareOrder=[...document.querySelectorAll('.compare-book')].map(cell=>cell.dataset.bookKey); localStorage.setItem('dfsCompareBookOrder',JSON.stringify(compareOrder)); reorderHeaders(); render(); });
  document.querySelector('#dfs-sport').addEventListener('change', () => { updateStats(); render(); });
  ['dfs-date','dfs-stat','dfs-side'].forEach(id => document.querySelector(`#${id}`).addEventListener('change', render));
  document.querySelector('#dfs-search').addEventListener('input', render);
  document.querySelector('#dfs-reset').addEventListener('click', () => { document.querySelectorAll('.dfs-filter-bar select').forEach(el=>el.value=''); document.querySelector('#dfs-search').value=''; updateStats(); render(); });
  document.querySelector('#dfs-live').addEventListener('click', () => setLiveRefresh(true));
  document.querySelector('#dfs-pause').addEventListener('click', () => setLiveRefresh(false));
  document.querySelector('#dfs-refresh').addEventListener('click', () => loadLiveRows());
  document.querySelectorAll('[data-devig-key]').forEach(input => input.addEventListener('input', event => updateDevigWeight(event.target.dataset.devigKey,event.target.value)));
  document.querySelectorAll('[data-devig-number]').forEach(input => input.addEventListener('input', event => updateDevigWeight(event.target.dataset.devigNumber,event.target.value)));
  document.querySelector('#dfs-devig-open').addEventListener('click', () => { draftWeights={...zeroWeights}; activePreset=''; document.querySelector('#dfs-devig-save-popover').hidden=true; document.querySelector('#dfs-devig-save-error').textContent=''; renderPresets(); syncDevigControls(); devigDialog.showModal(); requestAnimationFrame(()=>{document.querySelector('.dfs-devig-presets').scrollTo(0,0);document.querySelector('.dfs-devig-list').scrollTo(0,0);}); });
  document.querySelector('#dfs-devig-close').addEventListener('click', () => devigDialog.close());
  document.querySelector('#dfs-devig-cancel').addEventListener('click', () => { savedWeights={...defaultWeights}; draftWeights={...defaultWeights}; activePreset='iconlabs'; localStorage.setItem('dfsDevigWeightsV2',JSON.stringify(savedWeights)); updateDevigSummary(); renderPresets(); syncDevigControls(); render(); devigDialog.close(); });
  document.querySelector('#dfs-devig-reset').addEventListener('click', () => { draftWeights={...zeroWeights}; activePreset=''; renderPresets(); syncDevigControls(); });
  document.querySelector('#dfs-algo-preset').addEventListener('click', () => { draftWeights={...defaultWeights}; activePreset='iconlabs'; renderPresets(); syncDevigControls(); });
  document.querySelector('#dfs-saved-presets').addEventListener('click', event => { const button=event.target.closest('[data-preset-index]'); if(!button)return; const index=Number(button.dataset.presetIndex); draftWeights={...savedPresets[index].weights}; activePreset=`custom-${index}`; renderPresets(); syncDevigControls(); requestAnimationFrame(()=>document.querySelector('#dfs-devig-delete').scrollIntoView({block:'nearest',inline:'nearest'})); });
  document.querySelector('#dfs-devig-save-open').addEventListener('click', () => { const popover=document.querySelector('#dfs-devig-save-popover'); popover.hidden=false; const error=document.querySelector('#dfs-devig-save-error'); error.textContent=devigTotal()===100?'':'Allocate exactly 100% before saving.'; const input=document.querySelector('#dfs-devig-filter-name'); input.value=''; requestAnimationFrame(()=>{popover.scrollIntoView({block:'nearest',inline:'nearest'});input.focus();}); });
  document.querySelector('#dfs-devig-save-confirm').addEventListener('click', () => { const input=document.querySelector('#dfs-devig-filter-name'); const error=document.querySelector('#dfs-devig-save-error'); const name=input.value.trim(); if(!name){error.textContent='Enter a name for this filter.';return;} if(devigTotal()!==100){error.textContent='Allocate exactly 100% before saving.';return;} const duplicateName=weightsMatch(draftWeights,defaultWeights)?'IconLabs Algo Odds':savedPresets.find(preset=>weightsMatch(draftWeights,preset.weights))?.name; if(duplicateName){error.textContent=`This allocation is already saved as ${duplicateName}.`;return;} savedPresets.push({name,weights:{...draftWeights}}); localStorage.setItem('dfsDevigPresets',JSON.stringify(savedPresets)); activePreset=`custom-${savedPresets.length-1}`; document.querySelector('#dfs-devig-save-popover').hidden=true; renderPresets(); requestAnimationFrame(()=>document.querySelector('#dfs-devig-delete').scrollIntoView({block:'nearest',inline:'nearest'})); });
  document.querySelector('#dfs-devig-delete').addEventListener('click', () => { const match=activePreset.match(/^custom-(\d+)$/); if(!match)return; savedPresets.splice(Number(match[1]),1); localStorage.setItem('dfsDevigPresets',JSON.stringify(savedPresets)); activePreset=''; renderPresets(); });
  document.querySelector('#dfs-devig-filter-name').addEventListener('input',()=>document.querySelector('#dfs-devig-save-error').textContent='');
  document.querySelector('#dfs-devig-filter-name').addEventListener('keydown', event => { if(event.key==='Enter'){event.preventDefault();document.querySelector('#dfs-devig-save-confirm').click();} if(event.key==='Escape')document.querySelector('#dfs-devig-save-popover').hidden=true; });
  document.querySelector('#dfs-devig-form').addEventListener('submit', event => {
    event.preventDefault();
    if(devigTotal()!==100)return;
    savedWeights={...draftWeights};
    localStorage.setItem('dfsDevigWeightsV2',JSON.stringify(savedWeights));
    updateDevigSummary();
    render();
    devigDialog.close();
    loadLiveRows();
  });
  document.querySelector('#dfs-parlay-guide-open').addEventListener('click', () => parlayGuideDialog.showModal());
  document.querySelector('#dfs-parlay-guide-close').addEventListener('click', () => parlayGuideDialog.close());
  parlayGuideDialog.addEventListener('click', event => {
    if (event.target === parlayGuideDialog) parlayGuideDialog.close();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && parlayGuideDialog.open) parlayGuideDialog.close();
  });
  iconAlgoTooltipTrigger.addEventListener('pointerenter', showIconAlgoTooltip);
  iconAlgoTooltipTrigger.addEventListener('pointerleave', hideIconAlgoTooltip);
  iconAlgoTooltipTrigger.addEventListener('focus', showIconAlgoTooltip);
  iconAlgoTooltipTrigger.addEventListener('blur', hideIconAlgoTooltip);
  window.addEventListener('resize', hideIconAlgoTooltip);
  document.querySelector('.dfs-table-shell').addEventListener('scroll', hideIconAlgoTooltip);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) clearAutoRefresh();
    else if (liveRefreshEnabled) loadLiveRows();
  });
  updateStats();
  reorderHeaders();
  updateDevigSummary();
  renderPresets();
  syncDevigControls();
  syncRefreshControls();
  render();
  loadLiveRows();
})();

