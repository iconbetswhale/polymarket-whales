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
    preview: new URLSearchParams(window.location.search).get("preview") === "1",
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
    const url = row?.logoUrl || row?.providerLogo;
    return url
      ? `<img src="${escapeHtml(url)}" alt="" loading="lazy">`
      : `<span>${escapeHtml(fallback)}</span>`;
  }

  function signalCard(signal) {
    const detected = Math.abs(Number(signal.pressure)) >= 0.01;
    return `
      <article class="sharp-signal-card${signal.id === state.selectedId ? " selected" : ""}" data-sharp-signal="${escapeHtml(signal.id)}" tabindex="0">
        <div class="sharp-signal-money">
          <strong>${escapeHtml(money(signal.liquidity))}</strong>
          <span>ProphetX depth</span>
          <small class="${detected ? "flow-hot" : ""}"><i class="ph ph-waveform"></i>${detected ? "Flow detected" : "Monitoring"}</small>
        </div>
        <div class="sharp-signal-content">
          <div class="sharp-signal-meta">
            <div>
              <div class="sharp-signal-overline"><span>${escapeHtml(signal.league)} · ${escapeHtml(signal.market?.name)}${signal.previewOnly ? '<b class="sharp-preview-tag">Visual preview</b>' : ""}</span><time>${escapeHtml(timeLabel(signal.startsAt))} ET</time></div>
              <strong>${escapeHtml(signal.event)}</strong>
              <div class="sharp-signal-subrow"><em>${escapeHtml(signal.selection)}</em><div class="sharp-signal-badges"><span class="${detected ? "edge" : ""}">${escapeHtml(signal.pressureLabel)}</span><span>${escapeHtml(signal.confidence)} confidence</span></div></div>
            </div>
          </div>
          <div class="sharp-market-mini">
            <div><span>Inferred pressure side</span><strong>${escapeHtml(signal.selection)}</strong><small>Read-only · no orders</small></div>
            <div class="sharp-rec-bet"><span>ProphetX price</span><strong>${escapeHtml(odds(signal.americanOdds))}</strong><small>${escapeHtml(money(signal.liquidity))} quoted</small></div>
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
    const detected = Math.abs(Number(signal.pressure)) >= 0.01;
    return `
      <button class="sharp-mobile-close" id="sharp-detail-close" type="button" aria-label="Close market detail"><i class="ph ph-x"></i></button>
      <header class="sharp-detail-head"><div>
        <div class="sharp-detail-eyebrow"><span>${escapeHtml(signal.league)} · ${escapeHtml(signal.market?.name)}</span><div><b>${detected ? "Flow detected" : "Monitoring"}</b><b>Read only</b></div></div>
        <h2>${escapeHtml(signal.event)}</h2><strong>${escapeHtml(signal.selection)}</strong>
      </div><div class="sharp-detail-time"><b>${escapeHtml(timeLabel(signal.startsAt))} ET</b><small>ProphetX sandbox</small></div></header>
      <section class="sharp-recommendation">
        <span class="sharp-book-icon">${logo(signal)}</span>
        <div class="sharp-rec-copy"><span>Inferred pressure side</span><strong>${escapeHtml(signal.selection)}</strong></div>
        <div class="sharp-rec-price"><span>ProphetX quote</span><strong>${escapeHtml(odds(signal.americanOdds))}</strong></div>
        <div class="sharp-rec-stake"><span>Quoted depth</span><strong>${escapeHtml(money(signal.liquidity))}</strong></div>
        <span class="sharp-readonly-pill"><i class="ph ph-eye"></i> Read only</span>
      </section>
      <section class="sharp-metric-strip">
        <div><span>Price move</span><strong class="${Number(signal.probabilityDelta) > 0 ? "positive" : ""}">${escapeHtml(pct(signal.probabilityDelta, true))}</strong></div>
        <div><span>Depth change</span><strong>${escapeHtml(money(signal.liquidityDelta, false))}</strong></div>
        <div><span>Total market depth</span><strong>${escapeHtml(money(signal.totalLiquidity))}</strong></div>
        <div><span>Flow confidence</span><strong>${escapeHtml(signal.confidence)}</strong></div>
      </section>
      <section class="sharp-panel-section">
        <header class="sharp-section-head"><span><i class="ph ph-chart-line-up"></i> ProphetX price movement</span><small>Rolling local session</small></header>
        <div class="sharp-history-chart">${historyChart(signal)}</div>
      </section>
      <section class="sharp-panel-section">
        <header class="sharp-section-head"><span><i class="ph ph-stack"></i> ProphetX quoted depth</span><small>Posted liquidity, not confirmed handle</small></header>
        <div class="sharp-depth-chart">${outcomeRows(signal)}</div>
      </section>
      <section class="sharp-execution-section">
        <header><div><span>Exact-line market comparison</span><strong>Other books</strong></div><small>Odds API refreshes only while playing</small></header>
        <div class="sharp-execution-books">${comparisonRows(signal)}</div>
      </section>
      <section class="sharp-inference-note"><i class="ph ph-info"></i><p><strong>What “sharp flow” means here:</strong> price changes plus disappearing quoted depth can indicate aggressive pressure. Until ProphetX sends an explicit trade event, this remains an inference—not a claim about a known bettor.</p></section>`;
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
    state.visible = state.signals.filter(matches);
    if (!state.visible.some(row => row.id === state.selectedId)) state.selectedId = state.visible[0]?.id || null;
    const previewOnly = payload.previewOnly === true;
    $("sharp-play").classList.toggle("active", running);
    $("sharp-pause").classList.toggle("active", !running);
    $("sharp-play").disabled = previewOnly || state.controlling || !prophetxConfigured;
    $("sharp-play").title = prophetxConfigured
      ? "Start the local read-only collector"
      : "Add ProphetX sandbox credentials to .env.local first";
    $("sharp-pause").disabled = previewOnly || state.controlling;
    $("sharp-mode-badge").classList.toggle("live", running);
    $("sharp-mode-badge").innerHTML = previewOnly
      ? `<i class="ph ph-eye"></i> Visual preview`
      : running ? `<i class="ph ph-waveform"></i> Live local feed` : `<i class="ph ph-pause"></i> Paused`;
    $("sharp-feed-notice").classList.toggle("live", running);
    $("sharp-feed-title").textContent = previewOnly
      ? "Five visual preview plays - no provider requests"
      : running
      ? "Local collector active"
      : prophetxConfigured
        ? "Feed paused - zero new requests"
        : "ProphetX credentials required - zero new requests";
    $("sharp-feed-copy").textContent = previewOnly
      ? "Synthetic layout fixtures only. Tracking, Discord, provider credits, and model data are disabled."
      : running
      ? `ProphetX refreshes every ${payload.pollSeconds || 1}s; other-book comparisons every ${payload.comparisonSeconds || 60}s.`
      : prophetxConfigured
        ? `Press Play to start ProphetX${comparisonsConfigured ? " and sportsbook comparisons" : "; add THE_ODDS_API_KEY for other-book comparisons"}.`
        : "Add PROPHETX_ACCESS_KEY and PROPHETX_SECRET_KEY to .env.local, then restart this local preview.";
    $("sharp-feed-state").innerHTML = `<i></i> ${previewOnly ? "Preview" : running ? "Collecting" : "Paused"}`;
    $("sharp-result-label").textContent = previewOnly
      ? `${state.visible.length} preview play${state.visible.length === 1 ? "" : "s"}`
      : running ? `${state.visible.length} monitored market${state.visible.length === 1 ? "" : "s"}` : "Collector paused";
    $("sharp-last-updated").textContent = payload.lastError || ageLabel(payload.lastSnapshotAt);
    const liquidity = state.visible.reduce((sum, row) => sum + Number(row.liquidity || 0), 0);
    const flows = state.visible.filter(row => Math.abs(Number(row.pressure)) >= 0.01).length;
    $("sharp-summary-signals").textContent = String(state.visible.length);
    $("sharp-summary-liquidity").textContent = money(liquidity);
    $("sharp-summary-flow").textContent = String(flows);
    $("sharp-summary-cycles").textContent = String(payload.cycles || 0);
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
    $("sharp-play").addEventListener("click", () => control("play"));
    $("sharp-pause").addEventListener("click", () => control("pause"));
    $("sharp-search").addEventListener("input", event => { state.search = event.target.value.trim().toLowerCase(); render(); });
    $("sharp-signal-list").addEventListener("click", event => {
      const card = event.target.closest("[data-sharp-signal]");
      if (!card) return;
      state.selectedId = card.dataset.sharpSignal;
      render();
      $("sharp-detail-panel").classList.add("mobile-open");
      document.body.classList.add("sharp-detail-open");
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
