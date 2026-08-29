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
  const optionalComparisonBooks = (() => {
    try {
      const catalog = JSON.parse(document.querySelector('#dfs-comparison-book-catalog')?.textContent || '[]');
      return Array.isArray(catalog)
        ? catalog.filter(book=>book && book.key && book.name)
        : [];
    } catch (_) { return []; }
  })();
  const requiredComparisonBookKeys = new Set(comparisonBooks.map(book=>book.key));
  const optionalComparisonBookMap = new Map(optionalComparisonBooks.map(book=>[book.key,book]));
  const allowedComparisonBookKeys = new Set([...requiredComparisonBookKeys,...optionalComparisonBookMap.keys()]);
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
  let rowsByBook = {};
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
  const sportSelect = document.querySelector('#dfs-sport');
  const teamSelect = document.querySelector('#dfs-team');
  const statSelect = document.querySelector('#dfs-stat');
  const dateSelect = document.querySelector('#dfs-date');
  const customDateRange = document.querySelector('#dfs-custom-date-range');
  const customDateStart = document.querySelector('#dfs-date-from');
  const customDateEnd = document.querySelector('#dfs-date-to');
  const customDateError = document.querySelector('#dfs-date-error');
  const devigDialog = document.querySelector('#dfs-devig-dialog');
  const parlayGuideDialog = document.querySelector('#dfs-parlay-guide-dialog');
  const parlayConfig = document.querySelector('#dfs-parlay-config');
  const comparisonBookOpen = document.querySelector('#dfs-add-book-open');
  const comparisonBookPicker = document.querySelector('#dfs-add-book-picker');
  const comparisonBookSearch = document.querySelector('#dfs-add-book-search');
  const comparisonBookList = document.querySelector('#dfs-add-book-list');
  const comparisonBookEmpty = document.querySelector('#dfs-add-book-empty');
  const iconAlgoTooltipTrigger = document.querySelector('.dfs-algo-tooltip');
  const iconAlgoTooltipPopover = document.querySelector('#dfs-iconalgo-tooltip');
  const defaultWeights = {fanduel:30, novig:20, prophetx:15, draftkings:10, pinnacle:10, circa:7, kalshi:5, polymarket:3};
  const zeroWeights = Object.fromEntries(Object.keys(defaultWeights).map(key => [key,0]));
  const detailBookDefaults = ['fanduel','novig','prophetx','draftkings','pinnacle','circa','caesars','hard-rock','fliff','betonline','bovada','kalshi','polymarket','sleeper','parlay-play','propbuilder'];
  const detailBookSet = new Set(detailBookDefaults);
  const detailBookNames = {'hard-rock':'Hard Rock','parlay-play':'ParlayPlay',propbuilder:'PropBuilder',betonline:'BetOnline',caesars:'Caesars',fliff:'Fliff',bovada:'Bovada'};
  // Equivalent per-leg prices come from each fixed or guaranteed base payout
  // schedule. DraftKings can add extra peer-to-peer winnings above its base.
  const parlayTypes = {
    PrizePicks: [
      {id:'6-flex',label:'6 Pick Flex',odds:-118,payout:'25x / 2x / 0.4x'},
      {id:'5-flex',label:'5 Pick Flex',odds:-119,payout:'10x / 2x / 0.4x'},
      {id:'6-power',label:'6 Pick Power',odds:-121,payout:'37.5x'},
      {id:'3-power',label:'3 Pick Power',odds:-122,payout:'6x'},
      {id:'4-flex',label:'4 Pick Flex',odds:-122,payout:'6x / 1.5x'},
      {id:'5-power',label:'5 Pick Power',odds:-122,payout:'20x'},
      {id:'4-power',label:'4 Pick Power',odds:-128,payout:'10x'},
      {id:'2-power',label:'2 Pick Power',odds:-137,payout:'3x'},
      {id:'3-flex',label:'3 Pick Flex',odds:-137,payout:'3x / 1x'},
      {id:'2-flex',label:'2 Pick Flex',odds:-162,payout:'2x / 0.5x'},
    ],
    Underdog: [
      {id:'2-standard',label:'2 Pick Standard',odds:-115,payout:'3.5x'},
      {id:'3-standard',label:'3 Pick Standard',odds:-115,payout:'6.5x'},
      {id:'4-standard',label:'4 Pick Standard',odds:-116,payout:'12x'},
      {id:'6-flex',label:'6 Pick Flex',odds:-117,payout:'25x / 2.6x / 0.25x'},
      {id:'5-flex',label:'5 Pick Flex',odds:-121,payout:'10x / 2.5x'},
      {id:'4-flex',label:'4 Pick Flex',odds:-122,payout:'6x / 1.5x'},
      {id:'5-standard',label:'5 Pick Standard',odds:-122,payout:'20x'},
      {id:'8-standard',label:'8 Pick Standard',odds:-122,payout:'120x'},
      {id:'7-standard',label:'7 Pick Standard',odds:-123,payout:'65x'},
      {id:'8-flex',label:'8 Pick Flex',odds:-123,payout:'80x / 3x / 1x'},
      {id:'3-flex',label:'3 Pick Flex',odds:-124,payout:'3.25x / 1.09x'},
      {id:'6-standard',label:'6 Pick Standard',odds:-124,payout:'35x'},
      {id:'7-flex',label:'7 Pick Flex',odds:-124,payout:'40x / 2.75x / 0.5x'},
    ],
    'DK Pick6': [
      {id:'3-pick',label:'3 Pick',odds:-122,payout:'6x base + extra winnings'},
      {id:'5-pick',label:'5 Pick',odds:-122,payout:'20x base + extra winnings'},
      {id:'6-pick',label:'6 Pick',odds:-124,payout:'35x base + extra winnings'},
      {id:'4-pick',label:'4 Pick',odds:-128,payout:'10x base + extra winnings'},
      {id:'2-pick',label:'2 Pick',odds:-137,payout:'3x base + extra winnings'},
    ],
    Betr: [
      {id:'8-flex',label:'8 Pick Flex',odds:-118,payout:'50x / 2x / 1.5x / 1.25x'},
      {id:'10-flex',label:'10 Pick Flex',odds:-118,payout:'200x / 2x / 1.5x / 1.25x / 1x'},
      {id:'5-flex',label:'5 Pick Flex',odds:-119,payout:'10x / 2x / 0.4x'},
      {id:'6-flex',label:'6 Pick Flex',odds:-120,payout:'20x / 1.5x / 1x'},
      {id:'4-flex',label:'4 Pick Flex',odds:-122,payout:'6x / 1.5x'},
      {id:'5-perfect',label:'5 Pick Perfect',odds:-122,payout:'20x'},
      {id:'7-flex',label:'7 Pick Flex',odds:-124,payout:'35x / 2x / 1.25x'},
      {id:'9-flex',label:'9 Pick Flex',odds:-124,payout:'100x / 2x / 1.5x / 1.25x'},
      {id:'4-perfect',label:'4 Pick Perfect',odds:-128,payout:'10x'},
      {id:'8-perfect',label:'8 Pick Perfect',odds:-128,payout:'100x'},
      {id:'6-perfect',label:'6 Pick Perfect',odds:-131,payout:'30x'},
      {id:'7-perfect',label:'7 Pick Perfect',odds:-134,payout:'50x'},
      {id:'2-perfect',label:'2 Pick Perfect',odds:-137,payout:'3x'},
      {id:'3-flex',label:'3 Pick Flex',odds:-137,payout:'3x / 1x'},
      {id:'3-perfect',label:'3 Pick Perfect',odds:-141,payout:'5x'},
    ],
    Dabble: [
      {id:'6-hedge',label:'6 Pick Hedge',odds:-122,payout:'25x / 1.5x / 0.4x'},
      {id:'5-all-in',label:'5 Pick All-In',odds:-122,payout:'20x'},
      {id:'3-all-in',label:'3 Pick All-In',odds:-122,payout:'6x'},
      {id:'7-hedge',label:'7 Pick Hedge',odds:-124,payout:'35x / 2.5x / 1x'},
      {id:'6-all-in',label:'6 Pick All-In',odds:-124,payout:'35x'},
      {id:'5-hedge',label:'5 Pick Hedge',odds:-126,payout:'10x / 1.5x / 0.4x'},
      {id:'8-hedge',label:'8 Pick Hedge',odds:-126,payout:'50x / 5x / 1.5x'},
      {id:'7-all-in',label:'7 Pick All-In',odds:-126,payout:'60x'},
      {id:'10-hedge',label:'10 Pick Hedge',odds:-128,payout:'75x / 15x / 4x / 0.4x'},
      {id:'12-hedge',label:'12 Pick Hedge',odds:-128,payout:'250x / 40x / 7.5x / 1x'},
      {id:'9-hedge',label:'9 Pick Hedge',odds:-128,payout:'50x / 10x / 2x / 0.4x'},
      {id:'4-all-in',label:'4 Pick All-In',odds:-128,payout:'10x'},
      {id:'8-all-in',label:'8 Pick All-In',odds:-128,payout:'100x'},
      {id:'12-all-in',label:'12 Pick All-In',odds:-128,payout:'1000x'},
      {id:'9-all-in',label:'9 Pick All-In',odds:-129,payout:'175x'},
      {id:'11-hedge',label:'11 Pick Hedge',odds:-130,payout:'125x / 20x / 5x / 1x'},
      {id:'10-all-in',label:'10 Pick All-In',odds:-130,payout:'300x'},
      {id:'11-all-in',label:'11 Pick All-In',odds:-132,payout:'500x'},
      {id:'4-hedge',label:'4 Pick Hedge',odds:-132,payout:'5x / 1.5x'},
      {id:'3-hedge',label:'3 Pick Hedge',odds:-135,payout:'2.5x / 1.25x'},
      {id:'2-all-in',label:'2 Pick All-In',odds:-137,payout:'3x'},
    ],
  };
  const dfsComparisonKeys = new Set([...Object.values(selectedBookKeys),'sleeper']);
  let activeBook = 'PrizePicks';
  let parlaySelections = loadParlaySelections();
  let compareOrder = loadCompareOrder();
  let accountOrderSyncEnabled = false;
  let accountOrderSaveQueue = Promise.resolve();
  let savedWeights = loadWeights();
  let draftWeights = {...savedWeights};
  let savedPresets = loadPresets();
  let activePreset = weightsMatch(savedWeights,defaultWeights) ? 'iconlabs' : presetForWeights(savedWeights);
  let expandedRowId = '';
  const esc = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const easternDateFormatter = new Intl.DateTimeFormat('en-US', {timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'});

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

  function bestParlayProfile(book) {
    const profiles = parlayTypes[book] || [];
    return profiles.reduce((best,profile) => {
      if (!best) return profile;
      const probability = americanOddsToProbability(profile.odds);
      const bestProbability = americanOddsToProbability(best.odds);
      return probability !== null && (bestProbability === null || probability < bestProbability) ? profile : best;
    },null);
  }

  function loadParlaySelections() {
    let stored = {};
    try { stored = JSON.parse(localStorage.getItem('dfsParlaySelectionsV1') || '{}') || {}; }
    catch (_) { stored = {}; }
    return Object.fromEntries(Object.keys(parlayTypes).map(book => {
      const profiles = parlayTypes[book];
      const storedId = String(stored[book] || '');
      const selected = profiles.find(profile => profile.id === storedId) || bestParlayProfile(book);
      return [book,selected?.id || ''];
    }));
  }

  function selectedParlayProfile(book=activeBook) {
    const profiles = parlayTypes[book] || [];
    return profiles.find(profile => profile.id === parlaySelections[book]) || bestParlayProfile(book);
  }

  function formatAmericanOdds(odds) {
    const value = Number(odds);
    if (!Number.isFinite(value)) return '—';
    return value > 0 ? `+${Math.round(value)}` : String(Math.round(value));
  }

  function parlayMaxPayout(profile) {
    const match = String(profile?.payout || '').match(/\d+(?:\.\d+)?x/i);
    return match?.[0] || 'Reference';
  }

  function parlayOptionLabel(profile) {
    const label = String(profile?.label || '').replace(/\s*·\s*reference$/i,'');
    return `${label}: ${formatAmericanOdds(profile?.odds)} (${parlayMaxPayout(profile)})`;
  }

  function parlayOddsTitle(book=activeBook) {
    const profile = selectedParlayProfile(book);
    return profile ? `${book} ${profile.label} equivalent odds · ${profile.payout}` : `${book} equivalent odds`;
  }

  function updateParlaySummaries() {
    document.querySelectorAll('[data-dfs-book]').forEach(button => {
      const profile = selectedParlayProfile(button.dataset.dfsBook);
      const summary = button.querySelector('[data-dfs-parlay-summary]');
      if (summary && profile) summary.textContent = `${profile.label} · ${formatAmericanOdds(profile.odds)}`;
    });
  }

  function syncParlayPicker() {
    const profiles = parlayTypes[activeBook] || [];
    const selected = selectedParlayProfile(activeBook);
    parlayConfig.replaceChildren(...profiles.map(profile => {
      const option = document.createElement('button');
      option.type = 'button';
      option.dataset.parlayId = profile.id;
      option.setAttribute('role','option');
      option.setAttribute('aria-selected',String(profile.id === selected?.id));
      option.textContent = parlayOptionLabel(profile);
      return option;
    }));
    parlayConfig.setAttribute('aria-label',`${activeBook} parlay type`);
    updateParlaySummaries();
  }

  function positionParlayPicker(button) {
    if (!button) return;
    const buttonRect = button.getBoundingClientRect();
    const accent = getComputedStyle(button).getPropertyValue('--dfs-book-accent').trim();
    parlayConfig.style.left = `${Math.round(buttonRect.left)}px`;
    parlayConfig.style.top = `${Math.round(buttonRect.bottom+2)}px`;
    parlayConfig.style.width = `${Math.round(buttonRect.width)}px`;
    parlayConfig.style.setProperty('--parlay-picker-accent',accent || 'var(--il-brand)');
  }

  function setParlayPickerOpen(open,button=document.querySelector(`[data-dfs-book="${CSS.escape(activeBook)}"]`)) {
    if (open) positionParlayPicker(button);
    parlayConfig.hidden = !open;
    document.querySelectorAll('[data-dfs-book]').forEach(item => {
      item.setAttribute('aria-expanded',String(open && item===button));
    });
    if (!open) return;
    parlayConfig.querySelector('[aria-selected="true"]')?.focus({preventScroll:true});
  }

  function positionOpenParlayPicker() {
    if (parlayConfig.hidden) return;
    positionParlayPicker(
      document.querySelector(`[data-dfs-book="${CSS.escape(activeBook)}"]`)
    );
  }

  function loadCompareOrder() {
    const defaults = comparisonBooks.map(book => book.key);
    try {
      const stored = JSON.parse(localStorage.getItem('dfsCompareBookOrder') || 'null');
      return validCompareOrder(stored) ? stored : defaults;
    } catch (_) { return defaults; }
  }

  function validCompareOrder(order) {
    const defaults = comparisonBooks.map(book => book.key);
    return Array.isArray(order)
      && order.length >= defaults.length
      && new Set(order).size === order.length
      && defaults.every(key => order.includes(key))
      && order.every(key => allowedComparisonBookKeys.has(key));
  }

  function detailBookOrder() {
    const ordered = compareOrder.filter(key => detailBookSet.has(key) || optionalComparisonBookMap.has(key));
    return [...ordered,...detailBookDefaults.filter(key => !ordered.includes(key))];
  }

  function persistCompareOrder() {
    localStorage.setItem('dfsCompareBookOrder',JSON.stringify(compareOrder));
    if (!accountOrderSyncEnabled) return Promise.resolve();
    const body = JSON.stringify({compareBookOrder:[...compareOrder]});
    accountOrderSaveQueue = accountOrderSaveQueue
      .catch(()=>{})
      .then(()=>fetch('/api/dfs/preferences',{
        method:'PUT',
        headers:{'Content-Type':'application/json','Accept':'application/json'},
        body,
      }))
      .catch(()=>{});
    return accountOrderSaveQueue;
  }

  async function syncCompareOrderFromAccount() {
    try {
      const response = await fetch('/api/dfs/preferences',{headers:{Accept:'application/json'},cache:'no-store'});
      if (!response.ok) return;
      const payload = await response.json();
      accountOrderSyncEnabled = Boolean(payload.data?.accountAuthenticated);
      const remoteOrder = payload.data?.compareBookOrder;
      if (validCompareOrder(remoteOrder)) {
        compareOrder = [...remoteOrder];
        localStorage.setItem('dfsCompareBookOrder',JSON.stringify(compareOrder));
        reorderHeaders();
        render();
      } else if (accountOrderSyncEnabled) {
        persistCompareOrder();
      }
    } catch (_) {}
  }

  function weightsMatch(a,b) { return Object.keys(defaultWeights).every(key => Number(a[key])===Number(b[key])); }

  function updateAlgoPresentation() {
    const customWeights = !weightsMatch(savedWeights,defaultWeights);
    const accessibleLabel = customWeights
      ? 'Your Odds using custom Devig Settings'
      : 'IconLabs Algo Odds active';
    const tooltipLabel = customWeights
      ? 'Your Odds · custom Devig weights'
      : 'IconLabs Algo Odds · private model active';
    const head = document.querySelector('#dfs-algo-odds-head');
    head.setAttribute('aria-label',accessibleLabel);
    head.dataset.model = customWeights ? 'custom' : 'iconlabs';
    iconAlgoTooltipTrigger.setAttribute('aria-label',accessibleLabel);
    iconAlgoTooltipPopover.textContent = tooltipLabel;
  }

  function updateDevigSummary() {
    const usingIconLabs = weightsMatch(savedWeights,defaultWeights);
    document.querySelector('#dfs-devig-summary').textContent=usingIconLabs
      ? 'IconLabs Algo · 100%'
      : 'Custom DVIG · 100%';
  }

  function renderPresets() {
    const algoPreset = document.querySelector('#dfs-algo-preset');
    algoPreset.classList.toggle('active',activePreset==='iconlabs');
    algoPreset.setAttribute('aria-pressed',String(activePreset==='iconlabs'));
    algoPreset.querySelector('small').textContent = activePreset==='iconlabs' ? 'Private model · On' : 'Private model · Off';
    document.querySelector('#dfs-saved-presets').innerHTML=savedPresets.map((preset,index)=>`<button class="dfs-saved-preset ${activePreset===`custom-${index}`?'active':''}" type="button" data-preset-index="${index}">${esc(preset.name)}</button>`).join('');
    document.querySelector('#dfs-devig-delete').hidden=!/^custom-\d+$/.test(activePreset);
  }

  function weightedDevigConsensus(row,targetLine) {
    if (!Number.isFinite(Number(targetLine))) return null;
    const lineKey = String(Number(targetLine));
    const sources = row.devigSourcesByLine?.[lineKey];
    if (!sources || typeof sources !== 'object') return null;
    let weightedProbability = 0;
    let effectiveWeightTotal = 0;
    let sourceCount = 0;
    Object.keys(defaultWeights).forEach(key => {
      const source = sources[key];
      const probability = Number(Array.isArray(source) ? source[0] : source?.probability);
      const freshness = Number(Array.isArray(source) ? source[1] : source?.freshnessFactor);
      const configuredWeight = Number(savedWeights[key] || 0);
      const effectiveWeight = configuredWeight * freshness;
      if (!(probability > 0 && probability < 1) || !(effectiveWeight > 0)) return;
      weightedProbability += probability * effectiveWeight;
      effectiveWeightTotal += effectiveWeight;
      sourceCount += 1;
    });
    if (!(effectiveWeightTotal > 0)) return null;
    return {
      probability: Math.round(weightedProbability / effectiveWeightTotal * 10000) / 100,
      sourceCount,
    };
  }

  function fairProbability(row,targetLine) {
    const consensus = weightedDevigConsensus(row,targetLine);
    if (consensus) return consensus.probability;
    if (!Number.isFinite(Number(targetLine))) return null;
    const lineKey = String(Number(targetLine));
    const liveValue = row.hitByLine?.[lineKey] ?? row.hit;
    return Number.isFinite(Number(liveValue)) ? Number(liveValue) : null;
  }

  function fairSourceCount(row,targetLine) {
    const consensus = weightedDevigConsensus(row,targetLine);
    if (consensus) return consensus.sourceCount;
    const lineKey = String(Number(targetLine));
    return Number(row.exactSourcesByLine?.[lineKey] ?? row.sourceCount ?? 0);
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

  function rowMarketKey(row) {
    const id = String(row?.id || '');
    if (/::(?:over|under)$/i.test(id)) return id.replace(/::(?:over|under)$/i,'');
    return [row?.player,row?.match,row?.sport,row?.stat].map(value=>String(value||'')).join('::');
  }

  function detailPair(row) {
    const marketKey = rowMarketKey(row);
    const pair = {over:null,under:null};
    rows.forEach(candidate => {
      if (rowMarketKey(candidate) !== marketKey) return;
      const side = String(candidate.side || '').toLowerCase();
      if (side === 'over' || side === 'under') pair[side] = candidate;
    });
    return pair;
  }

  function bookName(key) {
    return comparisonBooks.find(book=>book.key===key)?.name || optionalComparisonBookMap.get(key)?.name || detailBookNames[key] || key;
  }

  function bookLogo(key) {
    const existing = document.querySelector(`[data-book-key="${key}"] img`)?.src;
    if (existing) return existing;
    const optionalLogo = optionalComparisonBookMap.get(key)?.logoUrl;
    if (optionalLogo) return new URL(optionalLogo,window.location.href).href;
    const sample = document.querySelector('[data-book-key="fanduel"] img')?.src;
    if (!sample) return '';
    try {
      const url = new URL(sample,window.location.href);
      url.pathname = url.pathname.replace(/fanduel\.png$/,`${key}.png`);
      return url.href;
    } catch (_) { return ''; }
  }

  function marketSnapshot(row,key) {
    if (!row) return {display:'—',american:null,line:null};
    const oddsByKey = row.oddsByBook || Object.fromEntries(sourceOddsKeys.map((item,index)=>[item,row.odds?.[index] ?? '—']));
    const market = oddsByKey[key];
    const structured = market !== null && typeof market === 'object';
    const display = structured ? (market.odds ?? market.displayOdds ?? market.americanOdds ?? '—') : (market ?? '—');
    const rawAmerican = structured ? (market.americanOdds ?? market.american_odds ?? market.odds) : market;
    const cents = String(display).trim().match(/^([0-9]+(?:\.[0-9]+)?)¢$/);
    let american = Number(rawAmerican);
    if (!Number.isFinite(american) && cents) {
      const probability = Number(cents[1]) / 100;
      american = Number(fairAmericanOdds(probability * 100));
    }
    return {
      display: display === null || display === undefined || display === '' ? '—' : String(display),
      american: Number.isFinite(american) ? american : null,
      line: structured && Number.isFinite(Number(market.line)) ? Number(market.line) : null,
    };
  }

  function centsAmericanLabel(display,americanOdds) {
    const isCentsPrice = /^([0-9]+(?:\.[0-9]+)?)¢$/.test(String(display).trim());
    const american = Number(americanOdds);
    return isCentsPrice && Number.isFinite(american) ? `(${formatAmericanOdds(american)})` : '';
  }

  function sideSummary(row) {
    const snapshots = detailBookOrder().map(key=>marketSnapshot(row,key));
    const americanOdds = snapshots.map(item=>item.american).filter(Number.isFinite);
    const best = americanOdds.length ? Math.max(...americanOdds) : null;
    const probabilities = americanOdds.map(americanOddsToProbability).filter(Number.isFinite);
    const average = probabilities.length
      ? fairAmericanOdds(probabilities.reduce((sum,value)=>sum+value,0) / probabilities.length * 100)
      : '—';
    return {snapshots,best,bestDisplay:best===null?'—':`${best>0?'+':''}${Math.round(best)}`,average};
  }

  function renderOddsDetail(row,activeLine) {
    const pair = detailPair(row);
    const over = sideSummary(pair.over);
    const under = sideSummary(pair.under);
    const orderedBooks = detailBookOrder();
    const headerCells = orderedBooks.map(key=>{
      const logo = bookLogo(key);
      return `<div class="dfs-detail-book-head">${logo?`<img src="${esc(logo)}" alt="">`:''}<span>${esc(bookName(key))}</span></div>`;
    }).join('');
    const sideLane = (label,sideRow,summary) => {
      const line = selectedDfsLine(sideRow || row) ?? activeLine;
      const bookCells = orderedBooks.map((key,index)=>{
        const snapshot = summary.snapshots[index];
        const isBest = snapshot.american !== null && summary.best !== null && Math.abs(snapshot.american-summary.best)<0.01;
        const alternate = snapshot.line !== null && Number(snapshot.line)!==Number(line) ? `Line ${snapshot.line}` : '';
        const centsAmerican = centsAmericanLabel(snapshot.display,snapshot.american);
        return `<div class="dfs-detail-price${isBest?' best':''}${snapshot.display==='—'?' muted':''}"><strong>${esc(snapshot.display)}</strong>${centsAmerican?`<small class="cents-american">${esc(centsAmerican)}</small>`:''}${alternate?`<small>${esc(alternate)}</small>`:''}</div>`;
      }).join('');
      return `<div class="dfs-detail-side"><b>${label} ${esc(line)}</b></div><div class="dfs-detail-metric best"><strong>${esc(summary.bestDisplay)}</strong></div><div class="dfs-detail-metric"><strong>${esc(summary.average)}</strong></div>${bookCells}`;
    };
    const colspan = 6 + compareOrder.filter(key=>key!==selectedBookKeys[activeBook]).length;
    return `<tr class="dfs-odds-detail-row"><td colspan="${colspan}"><section class="dfs-odds-detail" aria-label="${esc(row.player)} ${esc(activeLine)} ${esc(row.stat)} over and under odds"><div class="dfs-odds-detail-grid" style="--dfs-detail-book-count:${orderedBooks.length}"><div class="dfs-detail-title"><strong>${esc(row.player)} ${esc(activeLine)} ${esc(row.stat)}</strong></div><div class="dfs-detail-summary-head">Best odds</div><div class="dfs-detail-summary-head">Avg odds</div>${headerCells}${sideLane('Over',pair.over,over)}${sideLane('Under',pair.under,under)}</div></section></td></tr>`;
  }

  function updateStats() {
    const current = statSelect.value;
    const sport = sportSelect.value;
    const options = sport ? marketTypes[sport] : allMarkets;
    statSelect.innerHTML = '<option value="">All stats</option>' + options.map(stat => `<option>${esc(stat)}</option>`).join('');
    statSelect.value = options.includes(current) ? current : '';
  }

  function rowTeams(row) {
    const explicitTeams = [row.awayTeam,row.homeTeam]
      .map(team => String(team || '').trim())
      .filter(Boolean);
    if (explicitTeams.length) return [...new Set(explicitTeams)];
    return String(row.match || '')
      .split(/\s+vs\.?\s+/i)
      .map(team => team.trim())
      .filter(team => team && !/^(away|home)$/i.test(team));
  }

  function updateTeams() {
    const current = teamSelect.value;
    const sport = sportSelect.value;
    const teams = [...new Set(
      rows.filter(row => !sport || row.sport === sport).flatMap(rowTeams)
    )].sort((left,right) => left.localeCompare(right));
    teamSelect.innerHTML = '<option value="">All teams</option>'
      + teams.map(team => `<option value="${esc(team)}">${esc(team)}</option>`).join('');
    teamSelect.value = teams.includes(current) ? current : '';
  }

  function easternDateKey(date = new Date()) {
    const parts = Object.fromEntries(
      easternDateFormatter.formatToParts(date)
        .filter(part => part.type !== 'literal')
        .map(part => [part.type,part.value])
    );
    return `${parts.year}-${parts.month}-${parts.day}`;
  }

  function shiftDateKey(dateKey,days) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(dateKey))) return '';
    const [year,month,day] = String(dateKey).split('-').map(Number);
    const shifted = new Date(Date.UTC(year,month-1,day+days,12));
    return shifted.toISOString().slice(0,10);
  }

  function resetCustomDateRange() {
    const today = easternDateKey();
    customDateStart.value = today;
    customDateEnd.value = shiftDateKey(today,6);
  }

  function syncCustomDateRange() {
    const active = dateSelect.value === 'custom';
    customDateRange.hidden = !active;
    customDateEnd.min = customDateStart.value || '';
    const incomplete = active && (!customDateStart.value || !customDateEnd.value);
    const reversed = active && !incomplete && customDateStart.value > customDateEnd.value;
    const message = incomplete
      ? 'Choose both a start and end date.'
      : reversed
        ? 'End date must be on or after the start date.'
        : '';
    customDateError.textContent = message;
    customDateError.hidden = !message;
    customDateStart.setAttribute('aria-invalid',String(Boolean(message)));
    customDateEnd.setAttribute('aria-invalid',String(Boolean(message)));
  }

  function selectedDateRange() {
    const today = easternDateKey();
    if (dateSelect.value === 'today') return {start:today,end:today};
    if (dateSelect.value === 'tomorrow') {
      const tomorrow = shiftDateKey(today,1);
      return {start:tomorrow,end:tomorrow};
    }
    if (dateSelect.value === 'next_7_days') {
      return {start:today,end:shiftDateKey(today,6)};
    }
    if (dateSelect.value === 'custom'
      && customDateStart.value
      && customDateEnd.value
      && customDateStart.value <= customDateEnd.value) {
      return {start:customDateStart.value,end:customDateEnd.value};
    }
    return null;
  }

  function rowEventDateKey(row,dateRange) {
    const exactDate = String(row.eventDate || '');
    if (/^\d{4}-\d{2}-\d{2}$/.test(exactDate)) return exactDate;
    if (row.date === 'today') return dateRange?.today || easternDateKey();
    if (row.date === 'tomorrow') return shiftDateKey(dateRange?.today || easternDateKey(),1);
    return null;
  }

  function matchesDateRange(row,dateRange) {
    if (!dateRange) return false;
    const eventDate = rowEventDateKey(row,dateRange);
    return eventDate !== null && eventDate >= dateRange.start && eventDate <= dateRange.end;
  }

  function reorderHeaders() {
    const row = document.querySelector('#dfs-head-row');
    const selectedKey = selectedBookKeys[activeBook];
    syncOptionalComparisonHeaders();
    compareOrder.forEach(key => {
      const header = row.querySelector(`[data-book-key="${key}"]`);
      if (!header) return;
      header.hidden = key === selectedKey;
      row.appendChild(header);
    });
  }

  function createOptionalComparisonHeader(book) {
    const header = document.createElement('th');
    header.className = 'compare-book is-optional';
    header.dataset.bookKey = book.key;
    header.dataset.optionalComparisonBook = 'true';
    header.draggable = true;
    const logo = book.logoUrl
      ? `<img src="${esc(book.logoUrl)}" alt="${esc(book.name)}" title="${esc(book.name)}">`
      : '';
    header.innerHTML = `${logo}<i class="ph ph-dots-six dfs-column-drag" aria-hidden="true"></i><button class="dfs-remove-comparison-book" type="button" data-remove-comparison-book="${esc(book.key)}" aria-label="Remove ${esc(book.name)} comparison column" title="Remove ${esc(book.name)}"><i class="ph ph-x" aria-hidden="true"></i></button>`;
    return header;
  }

  function syncOptionalComparisonHeaders() {
    const row = document.querySelector('#dfs-head-row');
    row.querySelectorAll('[data-optional-comparison-book="true"]').forEach(header => {
      if (!compareOrder.includes(header.dataset.bookKey)) header.remove();
    });
    compareOrder.forEach(key => {
      const book = optionalComparisonBookMap.get(key);
      if (!book || row.querySelector(`[data-book-key="${key}"]`)) return;
      row.appendChild(createOptionalComparisonHeader(book));
    });
  }

  function renderComparisonBookPicker() {
    const query = comparisonBookSearch.value.trim().toLowerCase();
    const matches = optionalComparisonBooks.filter(book =>
      !query || `${book.name} ${book.key}`.toLowerCase().includes(query)
    );
    comparisonBookList.replaceChildren(...matches.map(book => {
      const added = compareOrder.includes(book.key);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'dfs-add-book-option';
      button.dataset.comparisonBookKey = book.key;
      button.setAttribute('aria-pressed',String(added));
      button.setAttribute('aria-label',`${added?'Remove':'Add'} ${book.name} comparison column`);
      const logo = book.logoUrl ? `<img src="${esc(book.logoUrl)}" alt="">` : '<span></span>';
      button.innerHTML = `${logo}<span>${esc(book.name)}</span><i class="ph ${added?'ph-check':'ph-plus'}" aria-hidden="true"></i>`;
      return button;
    }));
    comparisonBookEmpty.hidden = matches.length > 0;
  }

  function positionComparisonBookPicker() {
    if (comparisonBookPicker.hidden) return;
    const triggerRect = comparisonBookOpen.getBoundingClientRect();
    const edge = 12;
    const gap = 8;
    const width = Math.min(340,window.innerWidth-edge*2);
    comparisonBookPicker.style.width = `${Math.round(width)}px`;
    comparisonBookPicker.style.left = `${Math.round(Math.min(
      window.innerWidth-width-edge,
      Math.max(edge,triggerRect.right-width)
    ))}px`;
    comparisonBookPicker.style.top = `${Math.round(triggerRect.bottom+gap)}px`;
    const pickerHeight = comparisonBookPicker.getBoundingClientRect().height;
    const belowTop = triggerRect.bottom+gap;
    const aboveTop = triggerRect.top-gap-pickerHeight;
    const top = belowTop+pickerHeight <= window.innerHeight-edge
      ? belowTop
      : aboveTop >= edge
        ? aboveTop
        : Math.max(edge,window.innerHeight-edge-pickerHeight);
    comparisonBookPicker.style.top = `${Math.round(top)}px`;
  }

  function setComparisonBookPickerOpen(open) {
    comparisonBookPicker.hidden = !open;
    comparisonBookOpen.setAttribute('aria-expanded',String(open));
    if (!open) return;
    renderComparisonBookPicker();
    positionComparisonBookPicker();
    requestAnimationFrame(()=>comparisonBookSearch.focus({preventScroll:true}));
  }

  function toggleOptionalComparisonBook(key) {
    if (!optionalComparisonBookMap.has(key)) return;
    compareOrder = compareOrder.includes(key)
      ? compareOrder.filter(item=>item!==key)
      : [...compareOrder,key];
    persistCompareOrder();
    reorderHeaders();
    renderComparisonBookPicker();
    render();
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

  function applyLivePayload(payload) {
    const payloadBoards = payload?.dataByBook;
    if (payloadBoards && typeof payloadBoards === 'object') {
      rowsByBook = Object.fromEntries(
        Object.entries(payloadBoards).filter(([,bookRows]) => Array.isArray(bookRows))
      );
    }
    rows = rowsByBook[selectedBookKeys[activeBook]]
      ?? (Array.isArray(payload?.data) ? payload.data : []);
    updateTeams();
  }

  function render() {
    updateAlgoPresentation();
    const activeParlay = selectedParlayProfile();
    const activeParlayOdds = formatAmericanOdds(activeParlay?.odds);
    const sport = sportSelect.value;
    const team = teamSelect.value;
    const dateRange = selectedDateRange();
    if (dateRange) dateRange.today = easternDateKey();
    const stat = statSelect.value;
    const side = document.querySelector('#dfs-side').value;
    const search = document.querySelector('#dfs-search').value.trim().toLowerCase();
    const visible = rows
      .filter(r => selectedDfsLine(r) !== null && matchesDateRange(r,dateRange) && (!sport || r.sport === sport) && (!team || rowTeams(r).includes(team)) && (!stat || r.stat === stat) && (!side || r.side === side) && (!search || `${r.player} ${r.match}`.toLowerCase().includes(search)))
      .sort(compareByHitRate);
    body.innerHTML = visible.map(r => {
      const activeLine = selectedDfsLine(r);
      const fairHitRate = fairProbability(r,activeLine);
      const requiredProbability = americanOddsToProbability(activeParlay?.odds);
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
        const snapshot = marketSnapshot(r,key);
        const centsAmerican = centsAmericanLabel(price,snapshot.american);
        const classes = ['book-cell',unavailable?'muted':'',alternateLine===null?'':'has-alternate',centsAmerican?'has-cents-american':''].filter(Boolean).join(' ');
        return `<td class="${classes}" data-book-cell="${key}">${unavailable?'—':`<strong>${esc(price)}</strong>${centsAmerican?`<small class="cents-american">${esc(centsAmerican)}</small>`:''}${alternateLine===null?'':`<small class="alternate-line">${esc(alternateLine)}</small>`}`}</td>`;
      }).join('');
      const oddsSource = weightsMatch(savedWeights,defaultWeights) ? 'IconLabs Algo Odds' : 'Your Odds from custom Devig weights';
      const hitDisplay = fairHitRate === null ? '—' : `${fairHitRate.toFixed(1)}%`;
      const exactSources = fairSourceCount(r,activeLine);
      const hitTitle = fairHitRate === null ? 'No fresh exact-line source matches the current Devig allocation' : `${fairHitRate.toFixed(1)}% fair hit rate from ${exactSources} exact source${exactSources===1?'':'s'} · ${requiredPercent} required for ${activeBook} ${activeParlay?.label || ''} ${activeParlayOdds} · ${edgeLabel}`;
      const fairOdds = fairHitRate === null ? '—' : fairAmericanOdds(fairHitRate);
      const selectedAppOdds = activeParlayOdds;
      const selectedOddsTitle = parlayOddsTitle();
      const expanded = expandedRowId === String(r.id || '');
      const primaryRow = `<tr class="dfs-prop-row${expanded?' expanded':''}" data-row-id="${esc(r.id)}" tabindex="0" role="button" aria-expanded="${expanded}" title="Show Over and Under odds for ${esc(r.player)}"><td class="player-col"><div class="dfs-player"><span><strong>${esc(r.player)}</strong><small>${esc(r.match)}</small><em>${esc(r.sport)} · ${esc(r.time)}</em></span><i class="ph ph-caret-down dfs-row-expand-icon" aria-hidden="true"></i></div></td><td><b class="dfs-side ${r.side.toLowerCase()}">${r.side}</b></td><td><span class="dfs-stat"><strong class="dfs-stat-number">${esc(activeLine)}</strong><span class="dfs-stat-label">${esc(r.stat)}</span></span></td><td class="selected-line" title="${esc(selectedOddsTitle)}"><strong>${esc(selectedAppOdds)}</strong></td><td><span class="hit-rate ${hitRateBand}" title="${esc(hitTitle)}"><strong>${hitDisplay}</strong></span></td><td class="algo-odds-cell" title="${esc(oddsSource)}"><strong>${fairOdds}</strong></td>${cells}</tr>`;
      return primaryRow + (expanded ? renderOddsDetail(r,activeLine) : '');
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
    const params = new URLSearchParams({weights:JSON.stringify(savedWeights),schema:'instant-devig-v2'});
    const url = `/api/dfs/lines?${params}`;
    const cacheKey = pagePayloadCacheKey('dfs',params.toString());
    const signature = params.toString();
    if (activeLoad?.signature === signature) return activeLoad.promise;
    activeLoad?.controller.abort();
    if (!hasLoadedRows && !rows.length) {
      const cached = readPagePayloadCache(cacheKey,5*60*1000);
      if (cached) {
        applyLivePayload(cached);
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
        applyLivePayload(payload);
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

  function selectedDevigTotal() { return activePreset === 'iconlabs' ? 100 : devigTotal(); }

  function presetForWeights(weights) {
    const index = savedPresets.findIndex(preset=>weightsMatch(weights,preset.weights));
    return index >= 0 ? `custom-${index}` : '';
  }

  function syncDevigControls() {
    const total = selectedDevigTotal();
    const iconLabsSelected = activePreset === 'iconlabs';
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
    message.textContent = iconLabsSelected
      ? 'IconLabs private model is on. Move any slider to start a custom DVIG.'
      : total === 100
        ? 'Custom DVIG is ready to apply'
        : `${100-total}% left to allocate`;
    message.classList.toggle('ready',total===100);
    document.querySelector('#dfs-devig-apply').disabled = total !== 100;
    document.querySelector('#dfs-devig-apply').textContent = iconLabsSelected ? 'Use IconLabs Algo Odds' : 'Apply custom DVIG';
    document.querySelector('#dfs-devig-save-open').disabled = iconLabsSelected;
    const impact = document.querySelector('#dfs-devig-impact');
    impact.classList.toggle('algo-active',iconLabsSelected);
    document.querySelector('#dfs-devig-impact-icon').className = `ph ${iconLabsSelected?'ph-shield-check':'ph-warning'}`;
    document.querySelector('#dfs-devig-impact-title').textContent = iconLabsSelected
      ? 'IconLabs Algo Odds is selected.'
      : 'You’re building Your Odds.';
    document.querySelector('#dfs-devig-impact-copy').textContent = iconLabsSelected
      ? 'The internal book allocation stays private. Custom sliders remain at 0% until you move one.'
      : 'Your custom weights replace the IconLabs model for Chance to Hit and fair odds.';
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
    if (changed) setParlayPickerOpen(false);
    document.querySelectorAll('[data-dfs-book]').forEach(item => {
      item.classList.toggle('active',item===button);
      item.setAttribute('aria-selected',String(item===button));
    });
    activeBook = button.dataset.dfsBook;
    if (changed) expandedRowId = '';
    syncParlayPicker();
    const lineHead = document.querySelector('#dfs-line-head');
    const logo = button.querySelector('img').cloneNode();
    const selectedOddsTitle = parlayOddsTitle();
    logo.alt = activeBook;
    logo.title = selectedOddsTitle;
    lineHead.replaceChildren(logo);
    lineHead.setAttribute('aria-label',selectedOddsTitle);
    const selectedRows = rowsByBook[selectedBookKeys[activeBook]];
    if (Array.isArray(selectedRows)) rows = selectedRows;
    updateTeams();
    reorderHeaders();
    render();
    if (changed && !Array.isArray(selectedRows)) loadLiveRows();
  }

  document.querySelectorAll('[data-dfs-book]').forEach(btn => btn.addEventListener('click', () => {
    if (activeBook !== btn.dataset.dfsBook) {
      setActiveBook(btn);
      return;
    }
    setParlayPickerOpen(parlayConfig.hidden,btn);
  }));
  parlayConfig.addEventListener('click', event => {
    const option = event.target.closest('[data-parlay-id]');
    if (!option) return;
    const profiles = parlayTypes[activeBook] || [];
    if (!profiles.some(profile => profile.id === option.dataset.parlayId)) return;
    parlaySelections[activeBook] = option.dataset.parlayId;
    localStorage.setItem('dfsParlaySelectionsV1',JSON.stringify(parlaySelections));
    syncParlayPicker();
    setParlayPickerOpen(false);
    const activeButton = document.querySelector(`[data-dfs-book="${CSS.escape(activeBook)}"]`);
    const lineHead = document.querySelector('#dfs-line-head');
    const selectedOddsTitle = parlayOddsTitle();
    const logo = activeButton?.querySelector('img')?.cloneNode();
    if (logo) {
      logo.alt = activeBook;
      logo.title = selectedOddsTitle;
      lineHead.replaceChildren(logo);
    }
    lineHead.setAttribute('aria-label',selectedOddsTitle);
    render();
  });
  parlayConfig.addEventListener('keydown', event => {
    if (!['ArrowDown','ArrowUp','Home','End'].includes(event.key)) return;
    const options = [...parlayConfig.querySelectorAll('[data-parlay-id]')];
    const currentIndex = Math.max(0,options.indexOf(document.activeElement));
    const nextIndex = event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? options.length-1
        : (currentIndex + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
    event.preventDefault();
    options[nextIndex]?.focus();
  });
  document.addEventListener('click', event => {
    if (!parlayConfig.hidden && !event.target.closest('#dfs-parlay-config,[data-dfs-book]')) {
      setParlayPickerOpen(false);
    }
    if (!comparisonBookPicker.hidden && !event.target.closest('.dfs-add-book')) {
      setComparisonBookPickerOpen(false);
    }
  });
  body.addEventListener('click', event => {
    const row = event.target.closest('.dfs-prop-row');
    if (!row) return;
    expandedRowId = expandedRowId === row.dataset.rowId ? '' : row.dataset.rowId;
    render();
  });
  body.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const row = event.target.closest('.dfs-prop-row');
    if (!row) return;
    event.preventDefault();
    expandedRowId = expandedRowId === row.dataset.rowId ? '' : row.dataset.rowId;
    render();
    body.querySelector(`[data-row-id="${CSS.escape(expandedRowId || row.dataset.rowId)}"]`)?.focus();
  });
  enableDrag(document.querySelector('#dfs-head-row'), '.compare-book', () => { compareOrder=[...document.querySelectorAll('.compare-book')].map(cell=>cell.dataset.bookKey); persistCompareOrder(); reorderHeaders(); render(); });
  comparisonBookOpen.addEventListener('click', () => setComparisonBookPickerOpen(comparisonBookPicker.hidden));
  document.querySelector('#dfs-add-book-close').addEventListener('click', () => setComparisonBookPickerOpen(false));
  comparisonBookSearch.addEventListener('input',renderComparisonBookPicker);
  comparisonBookList.addEventListener('click', event => {
    const option = event.target.closest('[data-comparison-book-key]');
    if (!option) return;
    toggleOptionalComparisonBook(option.dataset.comparisonBookKey);
  });
  document.querySelector('#dfs-head-row').addEventListener('click', event => {
    const remove = event.target.closest('[data-remove-comparison-book]');
    if (!remove) return;
    event.stopPropagation();
    toggleOptionalComparisonBook(remove.dataset.removeComparisonBook);
  });
  sportSelect.addEventListener('change', () => { updateStats(); updateTeams(); render(); });
  ['dfs-team','dfs-stat','dfs-side'].forEach(id => document.querySelector(`#${id}`).addEventListener('change', render));
  dateSelect.addEventListener('change', () => { syncCustomDateRange(); render(); });
  [customDateStart,customDateEnd].forEach(input => input.addEventListener('input', () => { syncCustomDateRange(); render(); }));
  document.querySelector('#dfs-search').addEventListener('input', render);
  document.querySelector('#dfs-reset').addEventListener('click', () => { document.querySelectorAll('.dfs-filter-bar select').forEach(el=>el.value=''); dateSelect.value='next_7_days'; document.querySelector('#dfs-search').value=''; resetCustomDateRange(); syncCustomDateRange(); updateStats(); updateTeams(); render(); });
  document.querySelector('#dfs-live').addEventListener('click', () => setLiveRefresh(true));
  document.querySelector('#dfs-pause').addEventListener('click', () => setLiveRefresh(false));
  document.querySelector('#dfs-refresh').addEventListener('click', () => loadLiveRows());
  document.querySelectorAll('[data-devig-key]').forEach(input => input.addEventListener('input', event => updateDevigWeight(event.target.dataset.devigKey,event.target.value)));
  document.querySelectorAll('[data-devig-number]').forEach(input => input.addEventListener('input', event => updateDevigWeight(event.target.dataset.devigNumber,event.target.value)));
  document.querySelector('#dfs-devig-open').addEventListener('click', () => { const usingIconLabs=weightsMatch(savedWeights,defaultWeights); draftWeights=usingIconLabs?{...zeroWeights}:{...savedWeights}; activePreset=usingIconLabs?'iconlabs':presetForWeights(savedWeights); document.querySelector('#dfs-devig-save-popover').hidden=true; document.querySelector('#dfs-devig-save-error').textContent=''; renderPresets(); syncDevigControls(); devigDialog.showModal(); requestAnimationFrame(()=>{document.querySelector('.dfs-devig-presets').scrollTo(0,0);document.querySelector('.dfs-devig-list').scrollTo(0,0);}); });
  document.querySelector('#dfs-devig-close').addEventListener('click', () => devigDialog.close());
  document.querySelector('#dfs-devig-cancel').addEventListener('click', () => devigDialog.close());
  document.querySelector('#dfs-devig-reset').addEventListener('click', () => { draftWeights={...zeroWeights}; activePreset=''; renderPresets(); syncDevigControls(); });
  document.querySelector('#dfs-algo-preset').addEventListener('click', () => { draftWeights={...zeroWeights}; activePreset='iconlabs'; renderPresets(); syncDevigControls(); });
  document.querySelector('#dfs-saved-presets').addEventListener('click', event => { const button=event.target.closest('[data-preset-index]'); if(!button)return; const index=Number(button.dataset.presetIndex); draftWeights={...savedPresets[index].weights}; activePreset=`custom-${index}`; renderPresets(); syncDevigControls(); requestAnimationFrame(()=>document.querySelector('#dfs-devig-delete').scrollIntoView({block:'nearest',inline:'nearest'})); });
  document.querySelector('#dfs-devig-save-open').addEventListener('click', () => { if(activePreset==='iconlabs')return; const popover=document.querySelector('#dfs-devig-save-popover'); popover.hidden=false; const error=document.querySelector('#dfs-devig-save-error'); error.textContent=devigTotal()===100?'':'Allocate exactly 100% before saving.'; const input=document.querySelector('#dfs-devig-filter-name'); input.value=''; requestAnimationFrame(()=>{popover.scrollIntoView({block:'nearest',inline:'nearest'});input.focus();}); });
  document.querySelector('#dfs-devig-save-confirm').addEventListener('click', () => { const input=document.querySelector('#dfs-devig-filter-name'); const error=document.querySelector('#dfs-devig-save-error'); const name=input.value.trim(); if(activePreset==='iconlabs'){error.textContent='Move a slider to create a custom DVIG first.';return;} if(!name){error.textContent='Enter a name for this filter.';return;} if(devigTotal()!==100){error.textContent='Allocate exactly 100% before saving.';return;} const duplicateName=savedPresets.find(preset=>weightsMatch(draftWeights,preset.weights))?.name; if(duplicateName){error.textContent=`This allocation is already saved as ${duplicateName}.`;return;} savedPresets.push({name,weights:{...draftWeights}}); localStorage.setItem('dfsDevigPresets',JSON.stringify(savedPresets)); activePreset=`custom-${savedPresets.length-1}`; document.querySelector('#dfs-devig-save-popover').hidden=true; renderPresets(); requestAnimationFrame(()=>document.querySelector('#dfs-devig-delete').scrollIntoView({block:'nearest',inline:'nearest'})); });
  document.querySelector('#dfs-devig-delete').addEventListener('click', () => { const match=activePreset.match(/^custom-(\d+)$/); if(!match)return; savedPresets.splice(Number(match[1]),1); localStorage.setItem('dfsDevigPresets',JSON.stringify(savedPresets)); activePreset=''; renderPresets(); });
  document.querySelector('#dfs-devig-filter-name').addEventListener('input',()=>document.querySelector('#dfs-devig-save-error').textContent='');
  document.querySelector('#dfs-devig-filter-name').addEventListener('keydown', event => { if(event.key==='Enter'){event.preventDefault();document.querySelector('#dfs-devig-save-confirm').click();} if(event.key==='Escape')document.querySelector('#dfs-devig-save-popover').hidden=true; });
  document.querySelector('#dfs-devig-form').addEventListener('submit', event => {
    event.preventDefault();
    if(selectedDevigTotal()!==100)return;
    savedWeights=activePreset==='iconlabs'?{...defaultWeights}:{...draftWeights};
    localStorage.setItem('dfsDevigWeightsV2',JSON.stringify(savedWeights));
    activePreset=weightsMatch(savedWeights,defaultWeights)?'iconlabs':presetForWeights(savedWeights);
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
    if (event.key === 'Escape' && !parlayConfig.hidden) setParlayPickerOpen(false);
    if (event.key === 'Escape' && !comparisonBookPicker.hidden) {
      setComparisonBookPickerOpen(false);
      comparisonBookOpen.focus();
    }
  });
  iconAlgoTooltipTrigger.addEventListener('pointerenter', showIconAlgoTooltip);
  iconAlgoTooltipTrigger.addEventListener('pointerleave', hideIconAlgoTooltip);
  iconAlgoTooltipTrigger.addEventListener('focus', showIconAlgoTooltip);
  iconAlgoTooltipTrigger.addEventListener('blur', hideIconAlgoTooltip);
  window.addEventListener('resize', () => {
    hideIconAlgoTooltip();
    positionOpenParlayPicker();
    positionComparisonBookPicker();
  });
  document.querySelector('.dfs-book-row').addEventListener('scroll',positionOpenParlayPicker);
  window.addEventListener('scroll',() => {
    positionOpenParlayPicker();
    positionComparisonBookPicker();
  },{capture:true,passive:true});
  document.querySelector('.dfs-table-shell').addEventListener('scroll', hideIconAlgoTooltip);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) clearAutoRefresh();
    else if (liveRefreshEnabled) loadLiveRows();
  });
  updateStats();
  updateTeams();
  resetCustomDateRange();
  syncCustomDateRange();
  reorderHeaders();
  updateDevigSummary();
  renderPresets();
  syncDevigControls();
  syncRefreshControls();
  syncParlayPicker();
  render();
  syncCompareOrderFromAccount();
  loadLiveRows();
})();

