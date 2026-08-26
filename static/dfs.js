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
  const baseRows = [
    {player:'Aaron Judge', match:'Yankees vs Red Sox', sport:'MLB', date:'today', time:'Today · 7:05 PM', side:'Over', stat:'Hits + Runs + RBIs', line:2.5, dfsLines:{underdog:3.5}, hit:63.8, discrepancy:true, odds:['-176','-165','-145','-152','—','-160','-148','-150','-142','-112','-155','-168','—','—','-150']},
    {player:'Paul Skenes', match:'Pirates at Cubs', sport:'MLB', date:'today', time:'Today · 2:20 PM', side:'Over', stat:'Strikeouts', line:6.5, dfsLines:{'dk-pick6':5.5}, hit:60.4, odds:[{odds:'-185',line:5.5},'-148','-137','-142','-129','-151','-135','-140','-132',{odds:'-118',line:6.0},'-145','-158','-120','—','-138']},
    {player:'A’ja Wilson', match:'Aces vs Mercury', sport:'WNBA', date:'today', time:'Today · 9:30 PM', side:'Over', stat:'Points', line:25.5, hit:58.9, odds:['-143','-138','-124','-130','-120','-141','-128','-126','-121','-115','-133','-146','—',{odds:'-108',line:25.0},'-127']},
    {player:'Caitlin Clark', match:'Fever at Liberty', sport:'WNBA', date:'tomorrow', time:'Tomorrow · 8:00 PM', side:'Under', stat:'Points', line:21.5, hit:57.6, odds:['-136','-133','-120','-125','-116','-132','-124','-122','-118',{odds:'-115',line:22.5},'-128','-140','-120','—','-121']},
    {player:'Josh Allen', match:'Bills vs Ravens', sport:'NFL', date:'tomorrow', time:'Tomorrow · 7:20 PM', side:'Over', stat:'Passing Yards', line:265.5, hit:56.8, odds:['-131','-128','-115','-120','-112','-127','-119','-118','-114',{odds:'-112',line:264.5},'-123','-134','—',{odds:'-110',line:266.5},'-116']},
    {player:'Breanna Stewart', match:'Liberty vs Fever', sport:'WNBA', date:'tomorrow', time:'Tomorrow · 8:00 PM', side:'Over', stat:'Rebounds', line:8.5, hit:53.4, discrepancy:false, odds:['-126','-124','-112','-116','-108','-123','-114','-115','-110','-115','-118','-129','—','—','-113']},
    {player:'Shohei Ohtani', match:'Dodgers at Padres', sport:'MLB', date:'today', time:'Today · 10:10 PM', side:'Under', stat:'Hits + Runs + RBIs', line:3.5, hit:54.9, odds:['-121','-118','-108','-112','-104','-120','-109','-111','-105','-110','-115','-124','—','-108','-110']},
    {player:'Nikola Jokic', match:'Nuggets vs Suns', sport:'NBA', date:'tomorrow', time:'Tomorrow · 9:00 PM', side:'Over', stat:'Rebounds', line:11.5, hit:50.8, discrepancy:false, odds:['-115','-112','-102','-106','+100','-114','-104','-105','+101',{odds:'-112',line:11.0},'-108','-118','-110','—','-103']}
  ];
  const previewOddsFor = seed => sourceOddsKeys.map((_, index) => {
    if ((seed + index) % 17 === 0) return '—';
    const price = -104 - ((seed * 7 + index * 5) % 57);
    return index === 1 && seed % 4 === 0 ? {odds:String(price), line:null} : String(price);
  });
  const supplementalPreviewRows = [
    {player:'Juan Soto', match:'Mets vs Nationals', sport:'MLB', date:'today', time:'Today · 7:10 PM', side:'Over', stat:'Home Runs', line:0.5, hit:62.1},
    {player:'Mookie Betts', match:'Dodgers at Padres', sport:'MLB', date:'today', time:'Today · 10:10 PM', side:'Over', stat:'Total Bases', line:1.5, hit:61.3},
    {player:'Bobby Witt Jr.', match:'Royals vs Athletics', sport:'MLB', date:'today', time:'Today · 8:10 PM', side:'Over', stat:'Stolen Bases', line:0.5, hit:59.7},
    {player:'Tarik Skubal', match:'Tigers at Guardians', sport:'MLB', date:'today', time:'Today · 6:40 PM', side:'Over', stat:'Strikeouts', line:7.5, hit:60.8},
    {player:'Gunnar Henderson', match:'Orioles vs Rays', sport:'MLB', date:'tomorrow', time:'Tomorrow · 7:05 PM', side:'Over', stat:'Hits + Runs + RBIs', line:2.5, hit:58.6},
    {player:'José Ramírez', match:'Guardians vs Tigers', sport:'MLB', date:'today', time:'Today · 6:40 PM', side:'Over', stat:'Total Bases', line:1.5, hit:57.9},
    {player:'Sabrina Ionescu', match:'Liberty vs Fever', sport:'WNBA', date:'tomorrow', time:'Tomorrow · 8:00 PM', side:'Over', stat:'3-Pointers Made', line:2.5, hit:60.2},
    {player:'Napheesa Collier', match:'Lynx at Storm', sport:'WNBA', date:'today', time:'Today · 10:00 PM', side:'Over', stat:'Rebounds', line:9.5, hit:59.4},
    {player:'Kelsey Plum', match:'Sparks vs Aces', sport:'WNBA', date:'today', time:'Today · 9:30 PM', side:'Over', stat:'Assists', line:4.5, hit:56.9},
    {player:'Angel Reese', match:'Sky at Sun', sport:'WNBA', date:'tomorrow', time:'Tomorrow · 7:00 PM', side:'Over', stat:'Rebounds', line:11.5, hit:55.8},
    {player:'Lamar Jackson', match:'Ravens at Bills', sport:'NFL', date:'tomorrow', time:'Tomorrow · 7:20 PM', side:'Over', stat:'Passing Yards', line:248.5, hit:60.6},
    {player:'Saquon Barkley', match:'Eagles vs Cowboys', sport:'NFL', date:'today', time:'Today · 8:20 PM', side:'Over', stat:'Rushing Yards', line:82.5, hit:58.8},
    {player:'Justin Jefferson', match:'Vikings at Packers', sport:'NFL', date:'tomorrow', time:'Tomorrow · 4:25 PM', side:'Over', stat:'Receiving Yards', line:88.5, hit:57.4},
    {player:'CeeDee Lamb', match:'Cowboys at Eagles', sport:'NFL', date:'today', time:'Today · 8:20 PM', side:'Over', stat:'Receptions', line:6.5, hit:56.7},
    {player:'Patrick Mahomes', match:'Chiefs vs Broncos', sport:'NFL', date:'tomorrow', time:'Tomorrow · 8:15 PM', side:'Over', stat:'Passing Touchdowns', line:2.5, hit:55.6},
    {player:'Jalen Brunson', match:'Knicks vs Celtics', sport:'NBA', date:'tomorrow', time:'Tomorrow · 7:30 PM', side:'Over', stat:'Points', line:28.5, hit:59.1},
    {player:'Shai Gilgeous-Alexander', match:'Thunder at Rockets', sport:'NBA', date:'today', time:'Today · 8:00 PM', side:'Over', stat:'Points', line:31.5, hit:58.3},
    {player:'Anthony Edwards', match:'Timberwolves vs Nuggets', sport:'NBA', date:'tomorrow', time:'Tomorrow · 9:00 PM', side:'Over', stat:'3-Pointers Made', line:3.5, hit:56.2},
    {player:'Victor Wembanyama', match:'Spurs at Mavericks', sport:'NBA', date:'today', time:'Today · 8:30 PM', side:'Over', stat:'Blocks', line:3.5, hit:54.7},
    {player:'Connor McDavid', match:'Oilers vs Flames', sport:'NHL', date:'tomorrow', time:'Tomorrow · 9:00 PM', side:'Over', stat:'Points', line:1.5, hit:61.6},
    {player:'Auston Matthews', match:'Maple Leafs at Canadiens', sport:'NHL', date:'today', time:'Today · 7:00 PM', side:'Over', stat:'Shots on Goal', line:4.5, hit:57.1},
    {player:'Igor Shesterkin', match:'Rangers vs Devils', sport:'NHL', date:'tomorrow', time:'Tomorrow · 7:30 PM', side:'Over', stat:'Goalie Saves', line:27.5, hit:55.2}
  ].map((row, index) => ({...row, discrepancy:true, odds:previewOddsFor(index + baseRows.length)}));
  const isPreview = document.querySelector('.dfs-page')?.dataset.dfsPreview === 'true';
  let rows = isPreview ? [...baseRows, ...supplementalPreviewRows] : [];
  const body = document.querySelector('#dfs-body');
  const statSelect = document.querySelector('#dfs-stat');
  const devigDialog = document.querySelector('#dfs-devig-dialog');
  const parlayGuideDialog = document.querySelector('#dfs-parlay-guide-dialog');
  const iconAlgoTooltipTrigger = document.querySelector('.dfs-algo-tooltip');
  const iconAlgoTooltipPopover = document.querySelector('#dfs-iconalgo-tooltip');
  const defaultWeights = {fanduel:30, novig:20, prophetx:15, draftkings:10, pinnacle:10, circa:7, kalshi:5, polymarket:3};
  const zeroWeights = Object.fromEntries(Object.keys(defaultWeights).map(key => [key,0]));
  const sharpOffsets = {fanduel:-0.7, novig:1.3, pinnacle:0.8, prophetx:0.4, kalshi:-0.2, polymarket:0.6, draftkings:-0.5, circa:0.1};
  const bestSlipOdds = {'PrizePicks':'-119','Underdog':'-107','DK Pick6':'-122','Betr':'-118','Dabble':'-122'};
  const bestSlipOddsByKey = Object.fromEntries(Object.entries(selectedBookKeys).map(([book,key]) => [key,bestSlipOdds[book]]));
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
    if (!isPreview) {
      if (!Number.isFinite(Number(targetLine))) return null;
      const lineKey = Number.isFinite(Number(targetLine)) ? String(Number(targetLine)) : '';
      const liveValue = row.hitByLine?.[lineKey] ?? row.hit;
      return Number.isFinite(Number(liveValue)) ? Number(liveValue) : null;
    }
    const adjustment = Object.entries(savedWeights).reduce((sum,[key,weight]) => sum + sharpOffsets[key] * (weight/100),0);
    return Math.max(1,Math.min(99,row.hit + adjustment));
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

  function render() {
    updateAlgoPresentation();
    const sport = document.querySelector('#dfs-sport').value;
    const date = document.querySelector('#dfs-date').value;
    const stat = statSelect.value;
    const side = document.querySelector('#dfs-side').value;
    const search = document.querySelector('#dfs-search').value.trim().toLowerCase();
    const visible = rows.filter(r => (!sport || r.sport === sport) && (!date || date === 'this_week' || r.date === date) && (!stat || r.stat === stat) && (!side || r.side === side) && (!search || `${r.player} ${r.match}`.toLowerCase().includes(search)));
    body.innerHTML = visible.map(r => {
      const activeLine = r.dfsLines?.[selectedBookKeys[activeBook]] ?? (isPreview ? r.line : null);
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
      if (isPreview) oddsByKey.circa = oddsByKey.betonline;
      if (isPreview) Object.keys(bestSlipOddsByKey).forEach(key => { oddsByKey[key] = bestSlipOddsByKey[key]; });
      const cells = compareOrder.filter(key => key !== selectedBookKeys[activeBook]).map(key => {
        if (dfsComparisonKeys.has(key)) {
          const comparisonLine = r.dfsLines?.[key] ?? (isPreview ? r.line : null);
          if (comparisonLine === null) return `<td class="book-cell dfs-market-cell muted" data-book-cell="${key}"><strong>—</strong></td>`;
          const differs = Number(comparisonLine) !== Number(activeLine);
          const display = isPreview && !differs ? (bestSlipOddsByKey[key] || comparisonLine) : comparisonLine;
          return `<td class="book-cell dfs-market-cell" data-book-cell="${key}"><strong>${esc(display)}</strong></td>`;
        }
        const market = oddsByKey[key];
        const unavailable = market === '—';
        const price = typeof market === 'object' ? market.odds : market;
        const alternateLine = typeof market === 'object' && Number(market.line) !== Number(activeLine) ? market.line : null;
        const classes = ['book-cell',unavailable?'muted':'',alternateLine===null?'':'has-alternate'].filter(Boolean).join(' ');
        return `<td class="${classes}" data-book-cell="${key}">${unavailable?'—':`<strong>${esc(price)}</strong>${alternateLine===null?'':`<small class="alternate-line">${esc(alternateLine)}</small>`}`}</td>`;
      }).join('');
      const oddsSource = weightsMatch(savedWeights,defaultWeights) ? 'IconLabs Algo Odds' : 'Your Odds from custom Devig weights';
      const hitDisplay = fairHitRate === null ? '—' : `${fairHitRate.toFixed(1)}%`;
      const hitTitle = fairHitRate === null ? 'Insufficient exact-line sportsbook sources' : `${fairHitRate.toFixed(1)}% fair hit rate · ${requiredPercent} required for ${activeBook} ${bestSlipOdds[activeBook]} · ${edgeLabel}`;
      const fairOdds = fairHitRate === null ? '—' : fairAmericanOdds(fairHitRate);
      const lineDisplay = activeLine === null ? '—' : activeLine;
      return `<tr><td class="player-col"><div class="dfs-player"><span><strong>${esc(r.player)}</strong><small>${esc(r.match)}</small><em>${esc(r.sport)} · ${esc(r.time)}</em></span></div></td><td><b class="dfs-side ${r.side.toLowerCase()}">${r.side}</b></td><td><strong class="dfs-stat">${esc(r.stat)}</strong></td><td class="selected-line"><strong>${esc(lineDisplay)}</strong></td><td><span class="hit-rate ${hitRateBand}" title="${esc(hitTitle)}"><strong>${hitDisplay}</strong></span></td><td class="algo-odds-cell" title="${esc(oddsSource)}"><strong>${fairOdds}</strong></td>${cells}</tr>`;
    }).join('');
    document.querySelector('#dfs-empty').hidden = visible.length > 0;
  }

  async function loadLiveRows() {
    if (isPreview) return;
    const button = document.querySelector('#dfs-refresh');
    const live = document.querySelector('#dfs-live');
    button?.classList.add('spinning');
    if (button) button.disabled = true;
    try {
      const response = await fetch('/api/dfs/lines', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({weights:savedWeights}),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'DFS odds unavailable');
      rows = Array.isArray(payload.data) ? payload.data : [];
      if (live) live.lastChild.textContent = ` ${rows.length} live props · updated just now`;
      render();
    } catch (_error) {
      if (live) live.lastChild.textContent = ' Live odds temporarily unavailable';
      rows = [];
      render();
    } finally {
      button?.classList.remove('spinning');
      if (button) button.disabled = false;
    }
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

  document.querySelectorAll('[data-dfs-book]').forEach(btn => btn.addEventListener('click', () => { document.querySelectorAll('[data-dfs-book]').forEach(item => { item.classList.toggle('active', item===btn); item.setAttribute('aria-selected', String(item===btn)); }); activeBook=btn.dataset.dfsBook; const lineHead=document.querySelector('#dfs-line-head'); const logo=btn.querySelector('img').cloneNode(); logo.alt=activeBook; logo.title=`${activeBook} line`; lineHead.replaceChildren(logo); lineHead.setAttribute('aria-label',`${activeBook} line`); reorderHeaders(); render(); }));
  enableDrag(document.querySelector('.dfs-book-row'), '.dfs-book', () => {});
  enableDrag(document.querySelector('#dfs-head-row'), '.compare-book', () => { compareOrder=[...document.querySelectorAll('.compare-book')].map(cell=>cell.dataset.bookKey); localStorage.setItem('dfsCompareBookOrder',JSON.stringify(compareOrder)); reorderHeaders(); render(); });
  document.querySelector('#dfs-sport').addEventListener('change', () => { updateStats(); render(); });
  ['dfs-date','dfs-stat','dfs-side'].forEach(id => document.querySelector(`#${id}`).addEventListener('change', render));
  document.querySelector('#dfs-search').addEventListener('input', render);
  document.querySelector('#dfs-reset').addEventListener('click', () => { document.querySelectorAll('.dfs-filter-bar select').forEach(el=>el.value=''); document.querySelector('#dfs-search').value=''; updateStats(); render(); });
  document.querySelector('#dfs-refresh').addEventListener('click', event => {
    if (!isPreview) return loadLiveRows();
    const button = event.currentTarget;
    button.classList.add('spinning');
    button.disabled = true;
    window.setTimeout(() => {
      button.classList.remove('spinning');
      button.disabled = false;
      const live = document.querySelector('#dfs-live');
      if (live) live.lastChild.textContent = ' Preview refreshed just now';
    },700);
  });
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
    if (!isPreview) loadLiveRows();
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
  updateStats();
  reorderHeaders();
  updateDevigSummary();
  renderPresets();
  syncDevigControls();
  render();
  if (!isPreview) {
    loadLiveRows();
    window.setInterval(() => { if (!document.hidden) loadLiveRows(); },60000);
  }
})();

