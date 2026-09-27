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
  const compactDesktopDetail = window.matchMedia("(max-width: 1600px) and (min-width: 981px)");
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
    filters: { minimumCrossedEdgePercent: 0, flow: "", marketType: "", sportsbooks: initialSharpSportsbooks },
    filterDraftSportsbooks: new Set(initialSharpSportsbooks),
    sortDescending: true,
    detailVisible: true,
    previewExpandedId: null,
    previewListView: "live",
    refreshPaused: false,
  };
  const $ = id => document.getElementById(id);
  const previewTrackedStorageKey = "iconlabs-sharp-money-preview-tracked-v1";
  const previewHiddenStorageKey = "iconlabs-sharp-money-preview-hidden-v1";
  const previewBankrollStorageKey = "iconlabs-sharp-money-preview-bankroll-v1";
  let previewBankroll = 10000;
  try {
    const savedBankroll = Number(localStorage.getItem(previewBankrollStorageKey));
    if (Number.isFinite(savedBankroll) && savedBankroll > 0) previewBankroll = savedBankroll;
  } catch (_) {}
  let previewHiddenIds = new Set();
  try {
    const hidden = JSON.parse(localStorage.getItem(previewHiddenStorageKey) || "[]");
    if (Array.isArray(hidden)) previewHiddenIds = new Set(hidden.map(String));
  } catch (_) {}
  let previewTrackerDialog = null;
  let previewTrackerSignalId = "";
  let previewTrackerTags = [];
  let previewTrackerTrigger = null;
  let previewTrackerOptions = null;
  let previewTrackerConfirmation = { duplicate: false, conflict: false };

  function previewTrackedBets() {
    try {
      const bets = JSON.parse(localStorage.getItem(previewTrackedStorageKey) || "[]");
      return Array.isArray(bets) ? bets.filter(bet => bet && typeof bet === "object") : [];
    } catch (_) {
      return [];
    }
  }

  function savePreviewHiddenIds() {
    try {
      localStorage.setItem(previewHiddenStorageKey, JSON.stringify([...previewHiddenIds]));
    } catch (_) {}
  }

  function hidePreviewSignal(signalId) {
    previewHiddenIds.add(String(signalId));
    savePreviewHiddenIds();
    if (String(state.previewExpandedId) === String(signalId)) state.previewExpandedId = "";
    render();
  }

  function restorePreviewSignal(signalId) {
    previewHiddenIds.delete(String(signalId));
    savePreviewHiddenIds();
    if (String(state.previewExpandedId) === String(signalId)) state.previewExpandedId = "";
    render();
    window.showToast?.("Play restored to Live");
  }

  function setPreviewListView(nextView) {
    state.previewListView = nextView === "hidden" ? "hidden" : "live";
    state.previewExpandedId = "";
    render();
  }

  function previewBankrollMoney(value) {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
  }

  function updatePreviewBankroll() {
    const unit = previewBankroll * .01;
    if ($("sharp-bankroll-toolbar-value")) $("sharp-bankroll-toolbar-value").textContent = previewBankrollMoney(previewBankroll);
    if ($("sharp-unit-toolbar-value")) $("sharp-unit-toolbar-value").textContent = previewBankrollMoney(unit);
    if ($("sharp-unit-value")) $("sharp-unit-value").textContent = previewBankrollMoney(unit);
    if ($("sharp-bankroll-input")) $("sharp-bankroll-input").value = previewBankroll.toFixed(2);
  }

  function setPreviewBankrollPopover(open) {
    const panel = $("sharp-bankroll-popover");
    const button = $("sharp-bankroll-popover-button");
    if (!panel || !button) return;
    panel.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
  }

  function savePreviewBankroll() {
    const amount = Number($('sharp-bankroll-input')?.value);
    const saveState = $("sharp-bankroll-save-state");
    if (!Number.isFinite(amount) || amount <= 0) {
      if (saveState) saveState.textContent = "Enter a bankroll greater than zero";
      return;
    }
    previewBankroll = amount;
    try { localStorage.setItem(previewBankrollStorageKey, String(amount)); } catch (_) {}
    updatePreviewBankroll();
    if (saveState) saveState.textContent = "Saved in this browser";
    setPreviewBankrollPopover(false);
    window.showToast?.("Sharp Money bankroll updated");
  }

  function previewTrackerMoney(value) {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
  }

  function renderPreviewTrackerTags() {
    const selected = $("sharp-preview-tracker-selected-tags");
    const existing = $("sharp-preview-tracker-existing-tag");
    if (!selected || !existing) return;
    $("sharp-preview-tracker-tag-count").textContent = `${previewTrackerTags.length} selected`;
    selected.innerHTML = previewTrackerTags.length
      ? previewTrackerTags.map(tag => `<button type="button" data-preview-remove-tag="${escapeHtml(tag)}" title="Remove ${escapeHtml(tag)}"><span>#${escapeHtml(tag)}</span><i class="ph ph-x" aria-hidden="true"></i></button>`).join("")
      : "<span>No tags selected</span>";
    const available = [...new Set([
      ...(previewTrackerOptions?.tags || []),
      ...previewTrackedBets().flatMap(bet => Array.isArray(bet.tags) ? bet.tags : []),
    ])]
      .filter(tag => typeof tag === "string" && !previewTrackerTags.some(selectedTag => selectedTag.toLowerCase() === tag.toLowerCase()));
    existing.innerHTML = `<option value="">Select an existing tag</option>${available.map(tag => `<option value="${escapeHtml(tag)}">${escapeHtml(tag)}</option>`).join("")}`;
  }

  async function loadPreviewTrackerOptions(preferredBook) {
    if (!previewTrackerOptions && state.payload?.previewOnly !== true) {
      try {
        const response = await fetch("/api/personal-tracker/options", { headers: { Accept: "application/json" } });
        const payload = await response.json();
        if (response.ok) previewTrackerOptions = payload.data || {};
      } catch (_) {}
    }
    const savedBook = localStorage.getItem("iconbets-personal-sportsbook") || "";
    const selectedBook = preferredBook || savedBook || "Sportsbook";
    const books = [...new Set([
      selectedBook,
      ...(previewTrackerOptions?.sportsbook_choices || []),
      ...sharpBookCatalog.filter(book => book.type !== "exchange").map(book => book.name).filter(Boolean),
    ])];
    $("sharp-preview-tracker-sportsbook").innerHTML = books.map(book => `<option value="${escapeHtml(book)}">${escapeHtml(book)}</option>`).join("");
    $("sharp-preview-tracker-sportsbook").value = selectedBook;
    renderPreviewTrackerTags();
  }

  function addPreviewTrackerTag(rawTag) {
    const tag = String(rawTag || "").trim().replace(/^#+/, "").replace(/\s+/g, " ");
    if (!tag || previewTrackerTags.some(item => item.toLowerCase() === tag.toLowerCase())) return;
    const error = $("sharp-preview-tracker-error");
    if (tag.length > 32) { error.textContent = "Tags must be 32 characters or fewer."; return; }
    if (previewTrackerTags.length >= 8) { error.textContent = "Choose no more than 8 tags per bet."; return; }
    previewTrackerTags.push(tag);
    error.textContent = "";
    renderPreviewTrackerTags();
  }

  function updatePreviewTrackerTotal() {
    const price = Number($("sharp-preview-tracker-odds").value);
    const stake = Number($("sharp-preview-tracker-stake").value);
    const fees = Number($("sharp-preview-tracker-fees").value || 0);
    const valid = isUsableAmericanOdds(price) && Number.isFinite(stake) && stake > 0 && Number.isFinite(fees) && fees >= 0;
    const toWin = valid ? (price > 0 ? stake * price / 100 : stake * 100 / Math.abs(price)) : 0;
    $("sharp-preview-tracker-total").innerHTML = `<span>Bet cost</span><strong>${previewTrackerMoney(valid ? stake : 0)}</strong><small>To win ${previewTrackerMoney(toWin)} · Total payout ${previewTrackerMoney((valid ? stake : 0) + toWin)} · Total paid ${previewTrackerMoney(valid ? stake + fees : 0)}</small>`;
  }

  function ensurePreviewTrackerDialog() {
    if (previewTrackerDialog) return previewTrackerDialog;
    const dialog = document.createElement("dialog");
    dialog.className = "tracker-dialog sharp-preview-tracker-dialog";
    dialog.id = "sharp-preview-tracker-dialog";
    dialog.setAttribute("aria-labelledby", "sharp-preview-tracker-title");
    dialog.innerHTML = `<div class="tracker-dialog-shell">
      <button class="icon-button tracker-dialog-close" id="sharp-preview-tracker-close" type="button" aria-label="Close bet tracker"><i class="ph ph-x" aria-hidden="true"></i></button>
      <p class="eyebrow">PERSONAL TRACKER</p>
      <h2 id="sharp-preview-tracker-title">Track a sportsbook bet</h2>
      <div class="tracker-dialog-summary" id="sharp-preview-tracker-summary"></div>
      <form id="sharp-preview-tracker-form">
        <div class="personal-tracking-meta">
          <label>Sportsbook<select id="sharp-preview-tracker-sportsbook" required></select></label>
          <div class="personal-tag-builder">
            <div class="personal-tag-heading"><span>Tags <small>Optional, up to 8</small></span><span id="sharp-preview-tracker-tag-count">0 selected</span></div>
            <div class="personal-tag-controls">
              <select id="sharp-preview-tracker-existing-tag" aria-label="Select an existing bet tag"><option value="">Select an existing tag</option></select>
              <input id="sharp-preview-tracker-new-tag" type="text" maxlength="32" placeholder="Create a new tag" aria-label="Create a new bet tag">
              <button class="button ghost compact" id="sharp-preview-tracker-add-tag" type="button"><i class="ph ph-plus" aria-hidden="true"></i>Add</button>
            </div>
            <div class="personal-selected-tags" id="sharp-preview-tracker-selected-tags" aria-live="polite"><span>No tags selected</span></div>
          </div>
        </div>
        <div class="personal-purchase-fields">
          <label>Entry odds <input id="sharp-preview-tracker-odds" type="number" step="1" inputmode="numeric" required></label>
          <label>Stake <span class="input-with-suffix money"><span>$</span><input id="sharp-preview-tracker-stake" type="number" min="0.01" step="0.01" inputmode="decimal" required></span></label>
          <label>Fees <span class="input-with-suffix money"><span>$</span><input id="sharp-preview-tracker-fees" type="number" min="0" step="0.01" inputmode="decimal" value="0"></span></label>
        </div>
        <div class="personal-purchase-total" id="sharp-preview-tracker-total"><span>Bet cost</span><strong>$0.00</strong></div>
        <p class="tracker-admin-error" id="sharp-preview-tracker-error" role="alert" aria-live="polite"></p>
        <p class="tracker-dialog-note" id="sharp-preview-tracker-note"></p>
        <div class="tracker-dialog-actions"><button class="button ghost" id="sharp-preview-tracker-dismiss" type="button">Cancel</button><button class="button primary" id="sharp-preview-tracker-submit" type="submit"><i class="ph ph-check" aria-hidden="true"></i>Track bet</button><button class="button primary sharp-preview-track-hide" id="sharp-preview-tracker-hide-submit" type="submit"><i class="ph ph-eye-slash" aria-hidden="true"></i>Track and Hide</button></div>
      </form>
    </div>`;
    document.body.appendChild(dialog);
    const close = () => dialog.close();
    $("sharp-preview-tracker-close").addEventListener("click", close);
    $("sharp-preview-tracker-dismiss").addEventListener("click", close);
    dialog.addEventListener("click", event => { if (event.target === dialog) close(); });
    dialog.addEventListener("close", () => {
      previewTrackerSignalId = "";
      previewTrackerConfirmation = { duplicate: false, conflict: false };
      previewTrackerTrigger?.focus();
      previewTrackerTrigger = null;
    });
    dialog.addEventListener("input", event => {
      if (event.target.matches("#sharp-preview-tracker-odds, #sharp-preview-tracker-stake, #sharp-preview-tracker-fees")) updatePreviewTrackerTotal();
    });
    $("sharp-preview-tracker-add-tag").addEventListener("click", () => {
      addPreviewTrackerTag($("sharp-preview-tracker-new-tag").value);
      $("sharp-preview-tracker-new-tag").value = "";
    });
    $("sharp-preview-tracker-new-tag").addEventListener("keydown", event => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      addPreviewTrackerTag(event.target.value);
      event.target.value = "";
    });
    $("sharp-preview-tracker-existing-tag").addEventListener("change", event => {
      addPreviewTrackerTag(event.target.value);
      event.target.value = "";
    });
    $("sharp-preview-tracker-selected-tags").addEventListener("click", event => {
      const button = event.target.closest("[data-preview-remove-tag]");
      if (!button) return;
      previewTrackerTags = previewTrackerTags.filter(tag => tag !== button.dataset.previewRemoveTag);
      renderPreviewTrackerTags();
    });
    $("sharp-preview-tracker-form").addEventListener("submit", async event => {
      event.preventDefault();
      const hideAfterSave = event.submitter?.id === "sharp-preview-tracker-hide-submit";
      const activeSubmit = event.submitter || $("sharp-preview-tracker-submit");
      const submitButtons = [...$("sharp-preview-tracker-form").querySelectorAll('button[type="submit"]')];
      const signal = state.signals.find(row => String(row.id) === previewTrackerSignalId);
      const quote = signal && primaryQuote(signal);
      const price = Number($("sharp-preview-tracker-odds").value);
      const stake = Number($("sharp-preview-tracker-stake").value);
      const fees = Number($("sharp-preview-tracker-fees").value || 0);
      const sportsbook = $("sharp-preview-tracker-sportsbook").value;
      const error = $("sharp-preview-tracker-error");
      if (!signal || !quote || !isUsableAmericanOdds(price) || !Number.isFinite(stake) || stake <= 0 || !Number.isFinite(fees) || fees < 0 || !sportsbook) {
        error.textContent = "Enter a sportsbook, valid American odds, a positive stake, and nonnegative fees.";
        return;
      }
      const bets = previewTrackedBets();
      const previous = bets.find(bet => bet.id === signal.id);
      const trackedBet = {
        id: signal.id, event: signal.event, market: signal.market?.name || "",
        marketKind: signal.market?.kind || "", selection: displaySelection(signal),
        sportsbook, americanOdds: price, amount: stake, fees,
        tags: [...previewTrackerTags], league: signal.league || signal.sport || "",
        startsAt: signal.startsAt || "", trackedAt: previous?.trackedAt || new Date().toISOString(),
      };
      if (state.payload?.previewOnly !== true) {
        submitButtons.forEach(button => { button.disabled = true; });
        error.textContent = "";
        try {
          const response = await fetch("/api/sharp-money/personal-bets", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/json" },
            body: JSON.stringify({
              source_id: signal.id,
              event_title: signal.event,
              market_title: signal.market?.name || "Sharp Money",
              selection: displaySelection(signal),
              event_start_time: signal.startsAt || "",
              sport_key: signal.sport || signal.league || "",
              league: signal.league || signal.sport || "Other",
              market_key: signal.market?.kind || signal.market?.name || "market",
              market_line: signal.market?.line ?? null,
              canonical_event_id: signal.eventId || signal.event_id || "",
              american_odds: price,
              stake,
              fees,
              sportsbook,
              sportsbook_logo: quote.logoUrl || "",
              market_url: /^https:\/\//.test(String(quote.deepLink || "")) ? quote.deepLink : "",
              tags: previewTrackerTags,
              hide_after_track: hideAfterSave,
              confirm_duplicate: previewTrackerConfirmation.duplicate,
              confirm_conflict: previewTrackerConfirmation.conflict,
            }),
          });
          const payload = await response.json();
          if (response.status === 409 && payload.confirmationRequired) {
            previewTrackerConfirmation[payload.confirmationRequired] = true;
            error.textContent = payload.error || "Confirm this tracked bet and submit again.";
            activeSubmit.innerHTML = `<i class="ph ph-check" aria-hidden="true"></i>${hideAfterSave ? "Confirm and hide" : "Confirm bet"}`;
            return;
          }
          if (!response.ok) throw new Error(payload.error || "Unable to track bet.");
          localStorage.setItem("iconbets-personal-sportsbook", sportsbook);
          localStorage.setItem(previewTrackedStorageKey, JSON.stringify([trackedBet, ...bets.filter(bet => bet.id !== signal.id)]));
          dialog.close();
          if (hideAfterSave) {
            hidePreviewSignal(signal.id);
            window.showToast?.("Tracked and moved to Hidden");
          } else {
            window.location.assign(payload.destinations?.betTracker || "/tracker?view=personal&section=bets");
          }
        } catch (requestError) {
          error.textContent = requestError.message;
        } finally {
          submitButtons.forEach(button => { button.disabled = false; });
        }
        return;
      }
      try {
        localStorage.setItem(previewTrackedStorageKey, JSON.stringify([trackedBet, ...bets.filter(bet => bet.id !== signal.id)]));
      } catch (_) {
        error.textContent = "Could not save this sample play in this browser.";
        return;
      }
      dialog.close();
      if (hideAfterSave) {
        hidePreviewSignal(signal.id);
        window.showToast?.("Tracked and moved to Hidden");
      } else {
        window.location.assign("/tracker?preview=1&view=model&section=bets");
      }
    });
    previewTrackerDialog = dialog;
    return dialog;
  }

  function openPreviewTracker(signal, trigger) {
    const quote = primaryQuote(signal);
    if (!quote || !isUsableAmericanOdds(quote.americanOdds)) return;
    const dialog = ensurePreviewTrackerDialog();
    const saved = previewTrackedBets().find(bet => bet.id === signal.id);
    const recBet = Math.max(20, Math.round(Number(signal.confidence || 0) / 4) * 5);
    previewTrackerSignalId = String(signal.id);
    previewTrackerTags = Array.isArray(saved?.tags) ? saved.tags.filter(tag => typeof tag === "string") : [];
    previewTrackerConfirmation = { duplicate: false, conflict: false };
    previewTrackerTrigger = trigger;
    $("sharp-preview-tracker-summary").innerHTML = `
      <div><span>Event</span><strong>${escapeHtml(signal.event)}</strong></div>
      <div><span>Selection</span><strong>${escapeHtml(displaySelection(signal))}</strong></div>
      <div><span>Recommendation</span><strong>${previewTrackerMoney(recBet)}</strong></div>
      <div><span>Current odds</span><strong>${escapeHtml(odds(quote.americanOdds))}</strong></div>`;
    const preferredBook = saved?.sportsbook || quote.providerName || "Sportsbook";
    loadPreviewTrackerOptions(preferredBook);
    $("sharp-preview-tracker-odds").value = saved?.americanOdds ?? quote.americanOdds;
    $("sharp-preview-tracker-stake").value = Number(saved?.amount ?? recBet).toFixed(2);
    $("sharp-preview-tracker-fees").value = Number(saved?.fees || 0).toFixed(2);
    $("sharp-preview-tracker-new-tag").value = "";
    $("sharp-preview-tracker-error").textContent = "";
    $("sharp-preview-tracker-note").textContent = state.payload?.previewOnly
      ? "Fictional sample data. Track bet saves it to the local Bet Tracker preview. Track and Hide also moves the play to Hidden. No wager is placed."
      : "Track bet saves this play to your Personal Bet Tracker. Track and Hide also moves it to Hidden. No wager is placed automatically.";
    $("sharp-preview-tracker-submit").innerHTML = `<i class="ph ph-check" aria-hidden="true"></i>${saved ? "Update bet" : "Track bet"}`;
    $("sharp-preview-tracker-hide-submit").innerHTML = `<i class="ph ph-eye-slash" aria-hidden="true"></i>${saved ? "Update and Hide" : "Track and Hide"}`;
    renderPreviewTrackerTags();
    updatePreviewTrackerTotal();
    dialog.showModal();
  }

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
    return window.IconLabsOdds.fromAmerican(value);
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
      prophetx: "/static/assets/sportsbooks/prophetx.png",
    };
    const catalog = sharpBookCatalog.find(book => book.key === providerCatalogKey(row));
    const url = localLogos[providerKey(row)] || catalog?.logoUrl || row?.logoUrl || row?.providerLogo;
    return url
      ? `<img src="${escapeHtml(url)}" alt="" loading="lazy" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><span hidden>${escapeHtml(fallback)}</span>`
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

  function displaySelection(signal) {
    const selected = String(marketSides(signal).selected || "Selection").trim();
    const marketName = String(signal.market?.name || "").trim();
    const marketKind = String(signal.market?.kind || "").toLowerCase();
    if (marketKind === "moneyline" && !/moneyline/i.test(selected)) {
      return `${selected} Moneyline`;
    }
    if (!/^(over|under)\s+[+-]?\d/i.test(selected)) return selected;
    let unit = "";
    if (marketKind.includes("player")) {
      unit = marketName.replace(/^(alternate\s+)?player\s+/i, "").trim();
      if (/^(prop|alternate)$/i.test(unit)) unit = "";
    } else if (marketKind.includes("total") || /total/i.test(marketName)) {
      const competition = `${signal.league || ""} ${signal.sport || ""}`.toLowerCase();
      if (/mlb|baseball/.test(competition)) unit = "Runs";
      else if (/nba|wnba|basketball|nfl|football/.test(competition)) unit = "Points";
      else if (/nhl|hockey/.test(competition)) unit = "Goals";
      else if (/tennis/.test(competition)) unit = "Games";
    }
    return unit && !selected.toLowerCase().includes(unit.toLowerCase())
      ? `${selected} ${unit}`
      : selected;
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
  // Reuse-licensed Wikimedia Commons portraits for the fictional local sample feed.
  // Only map verified players; other tennis names retain the generic icon.
  const PREVIEW_TENNIS_PORTRAITS = Object.freeze({
    "Jannik Sinner": {
      url: "https://upload.wikimedia.org/wikipedia/commons/thumb/9/97/Jannik_Sinner_%282024_US_Open%29_04_%28cropped%29.jpg/120px-Jannik_Sinner_%282024_US_Open%29_04_%28cropped%29.jpg",
      source: "https://commons.wikimedia.org/wiki/File:Jannik_Sinner_(2024_US_Open)_04_(cropped).jpg",
      author: "Hameltion (Commons crop by Babu)",
    },
    "Frances Tiafoe": {
      url: "https://upload.wikimedia.org/wikipedia/commons/thumb/4/49/Frances_Tiafoe_%282024_DC_Open%29_01_%28cropped%29.jpg/120px-Frances_Tiafoe_%282024_DC_Open%29_01_%28cropped%29.jpg",
      source: "https://commons.wikimedia.org/wiki/File:Frances_Tiafoe_(2024_DC_Open)_01_(cropped).jpg",
      author: "Hameltion",
    },
  });
  const PREVIEW_PORTRAIT_LICENSE = "https://creativecommons.org/licenses/by-sa/4.0/";

  function providerKey(row) {
    const raw = row?.providerKey || row?.key || row?.providerName || row?.provider || "";
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
    const usable = rows.filter(isUsableQuote);
    if (!sportsbookFilterActive()) return usable;
    return usable.filter(row => state.filters.sportsbooks.has(providerCatalogKey(row)));
  }

  function isMarketIntelligenceProvider(row) {
    return MARKET_INTELLIGENCE_PROVIDERS.has(providerKey(row));
  }

  function bestQuote(rows) {
    return (rows || []).reduce((best, row) => {
      const price = Number(row?.americanOdds);
      return isUsableAmericanOdds(price) && (!best || price > Number(best.americanOdds)) ? row : best;
    }, null);
  }

  const MAX_ACTIONABLE_ABS_AMERICAN_ODDS = 10000;

  function isUsableAmericanOdds(value) {
    const price = Number(value);
    return Number.isFinite(price)
      && Math.abs(price) >= 100
      && Math.abs(price) <= MAX_ACTIONABLE_ABS_AMERICAN_ODDS;
  }

  function isUsableQuote(row) {
    if (!isUsableAmericanOdds(row?.americanOdds)) return false;
    return row?.oppositeAmericanOdds == null || isUsableAmericanOdds(row.oppositeAmericanOdds);
  }

  function decimalOdds(value) {
    const price = Number(value);
    if (!isUsableAmericanOdds(price)) return null;
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

  function crossedPriceGapPercent(signal) {
    const retail = primaryQuote(signal);
    const retailDecimal = decimalOdds(retail?.americanOdds);
    if (retailDecimal == null) return 0;
    return depthQuotes(signal).reduce((best, {row}) => {
      const sharpOppositeDecimal = decimalOdds(row?.oppositeAmericanOdds);
      const liquidity = Number(row?.oppositeAvailableLiquidity);
      if (sharpOppositeDecimal == null || !Number.isFinite(liquidity) || liquidity <= 0) return best;
      const gap = Math.max(0, (1 - (1 / retailDecimal) - (1 / sharpOppositeDecimal)) * 100);
      return Math.max(best,gap);
    },0);
  }

  function primaryQuotes(signal) {
    const rows = selectedComparisonLines(signal);
    const sportsbookRows = rows.filter(row => !isMarketIntelligenceProvider(row));
    const best = bestQuote(sportsbookRows);
    if (!best) return [];
    const bestPrice = Number(best.americanOdds);
    return sportsbookRows.filter(row => Number(row.americanOdds) === bestPrice);
  }

  function primaryQuote(signal) {
    return primaryQuotes(signal)[0] || null;
  }

  function depthQuotes(signal) {
    const rows = Array.isArray(signal.comparisonLines) ? signal.comparisonLines : [];
    const byProvider = new Map(rows.filter(isUsableQuote).map(row => [providerKey(row), row]));
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
    if (state.payload?.previewOnly) {
      return `<span class="sharp-depth-bet provider" aria-disabled="true" title="Sample data — betting unavailable">DEMO <i class="ph ph-lock"></i></span>`;
    }
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
    if (!quote) return "";
    if (state.payload?.previewOnly) {
      return `<span class="sharp-sportsbook-action" aria-disabled="true" title="Sample price — betting unavailable">${logo(quote, String(quote.providerName || "?").slice(0, 2))}<span><small>${escapeHtml(quote.providerName || "Sportsbook")}</small><b>${escapeHtml(odds(quote.americanOdds ?? fallbackOdds))}</b></span></span>`;
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

  function eventTeamCards(signal) {
    const teams = eventTeams(signal);
    const cards = [teams.away, teams.home].map(team => {
      const url = teamLogoUrl(signal, team);
      return `<span class="sharp-card-team">
        ${url ? `<span class="sharp-card-team-logo"><img src="${escapeHtml(url)}" alt="${escapeHtml(team)} logo" loading="lazy"></span>` : ""}
        <strong>${escapeHtml(team || "Team")}</strong>
      </span>`;
    });
    return `<div class="sharp-card-teams" aria-label="${escapeHtml(signal.event)}">
      ${cards[0]}<span class="sharp-card-versus">vs</span>${cards[1]}
    </div>`;
  }

  function depthSummary(signal) {
    const quotes = depthQuotes(signal);
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
          <span class="sharp-depth-chip-logo">${logo(row || {providerKey:key}, key === "novig" ? "N" : "PX")}</span>
          <span class="sharp-depth-chip-copy"><strong>${label}</strong><small>${escapeHtml(secondary)}</small></span>
          ${exchangeAction(key, row)}
        </div>`;
      }).join("")}
      </div>
    </div>`;
  }

  function signalCard(signal) {
    const selection = displaySelection(signal);
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
        </div>
        <div class="sharp-card-body">
          <div class="sharp-card-event">
            ${eventTeamCards(signal)}
            <strong class="sharp-card-featured-selection">${escapeHtml(selection)}</strong>
            <div class="sharp-card-market-meta"><em>${escapeHtml(signal.market?.name)}</em><time>${escapeHtml(timeLabel(signal.startsAt))}</time></div>
          </div>
          <div class="sharp-card-execution">
            <div class="sharp-card-action-row">
              <span class="sharp-card-rec-bet"><span class="sharp-card-rec-stake"><b>${money(recBet, false)}</b><small>Rec Bet</small></span><strong class="sharp-card-rec-selection">${escapeHtml(selection)}</strong></span>
              ${sportsbookAction(quote, signal.americanOdds)}
              ${quote ? state.payload?.previewOnly ? `<span class="sharp-card-bet" aria-disabled="true">DEMO <i class="ph ph-lock"></i></span>` : `<a class="sharp-card-bet" href="${escapeHtml(quote.deepLink || "#")}" ${quote.deepLink ? 'target="_blank" rel="noopener noreferrer"' : 'aria-disabled="true"'}>BET <i class="ph ph-arrow-up-right"></i></a>` : ""}
              <button class="sharp-card-add" type="button" aria-label="Add ${escapeHtml(selection)}"><i class="ph ph-plus"></i></button>
            </div>
            ${depthSummary(signal)}
          </div>
        </div>
      </article>`;
  }

  function previewProvider(row, fallback) {
    const name = row?.providerName || fallback;
    return `<span class="sharp-ledger-provider-logo">${logo(row, fallback.slice(0, 2))}</span><span>${escapeHtml(name)}</span>`;
  }

  function previewSportsbookLine(quotes) {
    if (!quotes.length) return '<span class="sharp-ledger-book">No sportsbook<b>—</b></span>';
    const providers = quotes.map(row => `<span class="sharp-ledger-book-provider">${previewProvider(row, "Sportsbook")}</span>`)
      .join('<span class="sharp-ledger-book-separator" aria-hidden="true">/</span>');
    return `<span class="sharp-ledger-book${quotes.length > 1 ? " tied" : ""}">${providers}<b>${escapeHtml(odds(quotes[0].americanOdds))}</b></span>`;
  }

  function previewDepth(signal) {
    return depthQuotes(signal).filter(({ row }) => row && Number(row.oppositeAvailableLiquidity) > 0)
      .sort((left, right) => Number(right.row.oppositeAvailableLiquidity) - Number(left.row.oppositeAvailableLiquidity));
  }

  function previewExpandedDetail(signal) {
    const selected = displaySelection(signal);
    const opposite = marketSides(signal).opposite;
    const quotes = primaryQuotes(signal);
    const depth = previewDepth(signal);
    const maxDepth = Math.max(1, ...depth.map(({ row }) => Number(row.oppositeAvailableLiquidity)));
    const recBet = Math.max(20, Math.round(Number(signal.confidence || 0) / 4) * 5);
    const columns = [selected, opposite];
    const lines = [...quotes, ...depth.map(item => item.row)].filter(Boolean);
    return `<div class="sharp-ledger-detail" id="sharp-ledger-detail-${escapeHtml(signal.id)}">
      <section class="sharp-ledger-depth-panel">
        <h3>Bet &amp; Opposite-Side Liquidity</h3>
        <p>Follow the sharp on <strong>${escapeHtml(selected)}</strong> at the softer sportsbook. The exchange depth below is available on <strong>${escapeHtml(opposite)}</strong>.</p>
        <div class="sharp-ledger-depth-head"><span>Source</span><span>Side</span><span>Odds</span><span>Amount</span></div>
        ${quotes.map(quote => `<div class="sharp-ledger-depth-item sportsbook"><span>${previewProvider(quote, "Sportsbook")}</span><span class="sharp-ledger-purple">${escapeHtml(selected)}</span><strong>${escapeHtml(odds(quote.americanOdds))}</strong><strong>${money(recBet, false)} <small>REC BET</small></strong></div>`).join("")}
        ${depth.map(({ key, row }) => `<div class="sharp-ledger-depth-item exchange"><span>${previewProvider(row, key === "novig" ? "NoVIG" : "ProphetX")}</span><span>${escapeHtml(opposite)}</span><strong>${escapeHtml(odds(row.oppositeAmericanOdds))}</strong><strong>${escapeHtml(liquidityMoney(row.oppositeAvailableLiquidity))}</strong><i style="--depth-width:${Math.max(8, Math.round(Number(row.oppositeAvailableLiquidity) / maxDepth * 100))}%"></i></div>`).join("")}
        <div class="sharp-ledger-depth-note"><i class="ph ph-info"></i><span>Exchange liquidity is on the opposite side of the recommended bet. It does not guarantee a fill.</span></div>
      </section>
      <section class="sharp-ledger-odds-panel">
        <div class="sharp-ledger-odds-title"><div><h3>Two-Sided Odds</h3><p>Compare both sides at each book</p></div></div>
        <div class="sharp-ledger-odds-head"><span>Provider</span>${columns.map(side => `<span>${escapeHtml(side)}</span>`).join("")}</div>
        ${lines.map(row => {
          const values = [row.americanOdds, row.oppositeAmericanOdds];
          return `<div class="sharp-ledger-odds-item"><span>${previewProvider(row, "Book")}</span>${values.map((value, index) => `<strong class="${index === 0 ? "sharp-ledger-purple" : ""}">${value == null ? "—" : escapeHtml(odds(value))}</strong>`).join("")}</div>`;
        }).join("")}
      </section>
    </div>`;
  }

  function previewSignalCard(signal) {
    const selected = displaySelection(signal);
    const opposite = marketSides(signal).opposite;
    const quotes = primaryQuotes(signal);
    const quote = quotes[0] || null;
    const depth = previewDepth(signal);
    const expanded = signal.id === state.previewExpandedId;
    const recBet = Math.max(20, Math.round(Number(signal.confidence || 0) / 4) * 5);
    const tracked = previewTrackedBets().some(bet => bet.id === signal.id);
    const hiddenView = state.previewListView === "hidden";
    const teams = eventTeams(signal);
    const teamLines = [teams.away, teams.home].map(team => {
      const tennisPlayer = /tennis|atp/i.test(String(signal.league || signal.sport || ""));
      const portrait = tennisPlayer ? PREVIEW_TENNIS_PORTRAITS[team] : null;
      const url = portrait ? portrait.url : teamLogoUrl(signal, team);
      return `<span class="sharp-ledger-team"><span class="sharp-ledger-team-mark${tennisPlayer ? " tennis-player" : ""}${team === "Jannik Sinner" ? " sinner-portrait" : ""}"${portrait ? ` title="Photo by ${escapeHtml(portrait.author)}, CC BY-SA 4.0"` : ""}>${tennisPlayer ? '<i class="ph ph-user-focus" aria-hidden="true"></i>' : ""}${url ? `<img src="${escapeHtml(url)}" alt="" loading="lazy" onerror="this.hidden=true">` : ""}</span><strong>${escapeHtml(team || "Team")}</strong></span>`;
    });
    const sample = state.payload?.previewOnly === true;
    return `<article class="sharp-ledger-card${expanded ? " expanded" : ""}" data-sharp-signal="${escapeHtml(signal.id)}" tabindex="0" aria-expanded="${expanded}" aria-controls="sharp-ledger-detail-${escapeHtml(signal.id)}">
      <div class="sharp-ledger-grid">
        <div class="sharp-ledger-matchup" aria-label="${escapeHtml(signal.event)}">${teamLines[0]}<span class="sharp-ledger-vs">vs</span>${teamLines[1]}<small>${escapeHtml(signal.league || signal.sport)} · ${escapeHtml(signal.market?.name)}</small></div>
        <div class="sharp-ledger-market"><strong>${escapeHtml(selected)}</strong><small>${escapeHtml(signal.market?.name)}</small></div>
        <time class="sharp-ledger-start">${escapeHtml(timeLabel(signal.startsAt))}<small>ET</small></time>
        <strong class="sharp-ledger-net">${escapeHtml(signalHeadline(signal))}</strong>
        <div class="sharp-ledger-execution">
          <div class="sharp-ledger-play-line"><span class="sharp-ledger-side"><small><i class="ph ph-arrow-up-right"></i> PLAY THIS SIDE</small><strong>${escapeHtml(selected)}</strong></span><div class="sharp-ledger-books">${previewSportsbookLine(quotes)}</div><span class="sharp-ledger-rec"><small>REC BET</small><b>${money(recBet, false)}</b></span>${hiddenView ? `<button class="sharp-ledger-sample-action restore" type="button" data-preview-restore="${escapeHtml(signal.id)}" title="Restore this play to Live">Restore <i class="ph ph-eye"></i></button>` : `<button class="sharp-ledger-sample-action" type="button" data-preview-track="${escapeHtml(signal.id)}" aria-pressed="${tracked}" title="${tracked ? "Review, update, or hide this tracked bet" : `Review, track, or hide this ${sample ? "fictional " : ""}play`}">Track/Hide <i class="ph ${tracked ? "ph-check" : "ph-plus"}"></i></button>`}</div>
          <div class="sharp-ledger-opposite-line"><span class="sharp-ledger-side"><small><i class="ph ph-arrow-down-left"></i> OPPOSITE SIDE · LIQUIDITY</small><strong>${escapeHtml(opposite)}</strong></span><div class="sharp-ledger-exchanges">${depth.map(({ key, row }) => `<span class="sharp-ledger-exchange">${previewProvider(row, key === "novig" ? "NoVIG" : "ProphetX")}<b>${escapeHtml(odds(row.oppositeAmericanOdds))}</b><strong>${escapeHtml(liquidityMoney(row.oppositeAvailableLiquidity))}</strong></span>`).join("")}</div></div>
        </div>
        <button class="sharp-ledger-expand" type="button" aria-label="${expanded ? "Collapse" : "Expand"} ${escapeHtml(signal.event)} details"><i class="ph ${expanded ? "ph-caret-up" : "ph-caret-down"}"></i></button>
      </div>
      ${expanded ? previewExpandedDetail(signal) : ""}
    </article>`;
  }

  function previewViewTabs() {
    const { liveCount, hiddenCount } = previewViewCounts();
    return `<button type="button" class="${state.previewListView === "live" ? "active" : ""}" data-preview-list-view="live" role="tab" aria-selected="${state.previewListView === "live"}"><i class="ph ph-broadcast"></i>Live <span>${liveCount}</span></button><button type="button" class="${state.previewListView === "hidden" ? "active" : ""}" data-preview-list-view="hidden" role="tab" aria-selected="${state.previewListView === "hidden"}"><i class="ph ph-eye-slash"></i>Hidden <span>${hiddenCount}</span></button>`;
  }

  function previewViewCounts() {
    const matchingSignals = state.signals.filter(matches);
    const hiddenCount = matchingSignals.filter(signal => previewHiddenIds.has(String(signal.id))).length;
    return { liveCount: matchingSignals.length - hiddenCount, hiddenCount };
  }

  function previewLedger() {
    const visiblePortraits = [...new Set(state.visible.flatMap(signal => {
      if (!/tennis|atp/i.test(String(signal.league || signal.sport || ""))) return [];
      const teams = eventTeams(signal);
      return [teams.away, teams.home].filter(team => PREVIEW_TENNIS_PORTRAITS[team]);
    }))];
    const portraitCredits = visiblePortraits.length
      ? `<p class="sharp-ledger-photo-credits">Tennis photos: ${visiblePortraits.map(team => `<a href="${escapeHtml(PREVIEW_TENNIS_PORTRAITS[team].source)}" target="_blank" rel="noopener noreferrer">${escapeHtml(team)}</a> by ${escapeHtml(PREVIEW_TENNIS_PORTRAITS[team].author)}`).join(" · ")} · <a href="${PREVIEW_PORTRAIT_LICENSE}" target="_blank" rel="noopener noreferrer">CC BY-SA 4.0</a> · displayed as circular crops. Photos do not imply player endorsement.</p>`
      : "";
    return `<div class="sharp-ledger-head"><span>Matchup</span><span>Market / Selection</span><span>Start (ET)</span><span>Net Sharp $</span><span>Sportsbook Bet / Opposite Exchange Liquidity</span><span></span></div>
      ${state.visible.length ? state.visible.map(previewSignalCard).join("") : `<div class="sharp-ledger-empty">${state.previewListView === "hidden" ? "No hidden plays yet. Use Track/Hide and choose Track and Hide to move a play here." : "No sample plays match these filters."}</div>`}${portraitCredits}`;
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
    const selectedRows = selectedComparisonLines(signal);
    const providerKeys = selectedRows.map(providerCatalogKey);
    const rows = [...selectedRows].sort((a, b) => {
      const order = window.IconLabsLineShopOrder;
      const aRank = order?.rank(providerCatalogKey(a), providerKeys) ?? Number.MAX_SAFE_INTEGER;
      const bRank = order?.rank(providerCatalogKey(b), providerKeys) ?? Number.MAX_SAFE_INTEGER;
      if (aRank !== bRank) return aRank-bRank;
      const aIntel = isMarketIntelligenceProvider(a) ? 1 : 0;
      const bIntel = isMarketIntelligenceProvider(b) ? 1 : 0;
      return aIntel-bIntel;
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
          return `<div class="sharp-market-table-row${isMarketIntelligenceProvider(row) ? " intelligence" : " sportsbook"}" draggable="true" tabindex="0" role="group" data-line-shop-book="${escapeHtml(providerCatalogKey(row))}" aria-label="${escapeHtml(row.providerName || providerCatalogKey(row))} line. Press Alt plus left or right arrow to reorder." title="Drag to reorder, or press Alt + Left/Right">
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
    const history = (signal.history || []).filter(row => isUsableAmericanOdds(row.americanOdds));
    if (history.length < 2) return `<div class="sharp-chart-warmup"><i class="ph ph-chart-line-up"></i><strong>Building price history</strong><span>Two or more live snapshots are required.</span></div>`;
    const values = history.map(row => Number(row.americanOdds) || 0);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const points = values.map((value, index) => {
      const x = history.length === 1 ? 0 : (index / (history.length - 1)) * 100;
      const y = max === min ? 50 : 88 - ((value - min) / (max - min)) * 68;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    return `<svg class="sharp-flow-chart" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="Sharp exchange price history"><polyline points="${points}"></polyline></svg>`;
  }

  function detail(signal) {
    const sides = marketSides(signal);
    const selection = displaySelection(signal);
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
          <div class="sharp-rec-copy"><strong>${escapeHtml(selection)}</strong></div>
          <div class="sharp-rec-stake"><strong>${money(recBet, false)}</strong><span>Rec Bet</span></div>
          <div class="sharp-rec-book">${sportsbookAction(quote, signal.americanOdds)}</div>
          ${quote ? state.payload?.previewOnly ? `<span class="sharp-game-button unavailable" aria-disabled="true">DEMO <i class="ph ph-lock"></i></span>` : `<a class="sharp-game-button" href="${escapeHtml(quote.deepLink || "#")}" ${quote.deepLink ? 'target="_blank" rel="noopener noreferrer"' : 'aria-disabled="true"'}>BET <i class="ph ph-arrow-up-right"></i></a>` : `<span class="sharp-game-button unavailable">WAIT</span>`}
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
    const retailQuote = primaryQuote(signal);
    const rawDirectDepth = signal.depthAvailable === true
      && (signal.comparisonLines || []).some(row => DEPTH_PROVIDER_ORDER.includes(providerKey(row)));
    const hasDirectDepth = signal.depthAvailable === true
      && depthQuotes(signal).some(({row}) => row && Number(row.availableLiquidity) > 0);
    return (!rawDirectDepth || hasDirectDepth)
      && Boolean(retailQuote || hasDirectDepth)
      && (!state.sport || signal.league === state.sport || signal.sport === state.sport)
      && (!state.search || haystack.includes(state.search))
      && crossedPriceGapPercent(signal) >= state.filters.minimumCrossedEdgePercent
      && (!state.filters.flow || (state.filters.flow === "detected") === detected)
      && (!state.filters.marketType || marketFilterKind === state.filters.marketType)
      && (!sportsbookFilterActive() || selectedComparisonLines(signal).length > 0);
  }

  function render() {
    const payload = state.payload || {};
    const preview = payload.previewOnly === true;
    document.body.classList.add("sharp-preview-active");
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
    state.visible = state.signals.filter(matches).filter(signal => {
      const hidden = previewHiddenIds.has(String(signal.id));
      return state.previewListView === "hidden" ? hidden : !hidden;
    }).sort((left, right) => {
      const leftLiquidity = combinedCrossedLiquidity(left) ?? -1;
      const rightLiquidity = combinedCrossedLiquidity(right) ?? -1;
      return state.sortDescending ? rightLiquidity - leftLiquidity : leftLiquidity - rightLiquidity;
    });
    if (!state.visible.some(row => row.id === state.selectedId)) state.selectedId = state.visible[0]?.id || null;
    if (state.previewExpandedId !== "" && !state.visible.some(row => row.id === state.previewExpandedId)) {
      state.previewExpandedId = state.visible[0]?.id || null;
    }
    const previewViewTabsHost = $("sharp-preview-view-tabs");
    if (previewViewTabsHost) {
      previewViewTabsHost.hidden = false;
      previewViewTabsHost.innerHTML = previewViewTabs();
    }
    const previewCounts = previewViewCounts();
    if ($("sharp-menu-visible-count")) $("sharp-menu-visible-count").textContent = String(previewCounts.liveCount);
    if ($("sharp-menu-hidden-count")) $("sharp-menu-hidden-count").textContent = String(previewCounts.hiddenCount);
    document.querySelectorAll("#sharp-more-menu [data-preview-list-view]").forEach(button => {
      button.setAttribute("aria-current", String(button.dataset.previewListView === state.previewListView));
    });
    const refreshToggle = $("sharp-menu-pause");
    if (refreshToggle) {
      refreshToggle.setAttribute("aria-pressed", String(state.refreshPaused));
      refreshToggle.setAttribute("aria-label", state.refreshPaused ? "Resume automatic refresh" : "Pause automatic refresh");
      refreshToggle.querySelector("i").className = `ph ph-${state.refreshPaused ? "play" : "pause"}`;
      refreshToggle.querySelector("small").textContent = state.refreshPaused ? "Paused" : "Active";
    }
    const feedToggle = $("sharp-feed-toggle");
    if (feedToggle) {
      feedToggle.innerHTML = `<i class="ph ${running ? "ph-pause" : "ph-play"}"></i><span>${running ? "Pause feed" : "Play feed"}</span>`;
      feedToggle.classList.toggle("active", running);
      feedToggle.setAttribute("aria-pressed", String(running));
      feedToggle.setAttribute("aria-label", running ? "Pause feed" : "Play feed");
      feedToggle.disabled = preview || automatic || state.controlling || (!running && !sourceConfigured);
      feedToggle.title = running
        ? "Pause the local read-only collector"
        : automatic
          ? `${quoteConsensus || standardOddsEngine ? "OddsEngine price-consensus" : "OddsEngine order-book"} refresh is automatic`
          : sourceConfigured
          ? "Start the local read-only collector"
          : "Add an OddsEngine Advanced or ProphetX credential first";
    }
    const sortButton = $("sharp-sort");
    if (sortButton) {
      sortButton.setAttribute("aria-pressed", String(!state.sortDescending));
      sortButton.title = state.sortDescending ? "Combined liquidity: high to low" : "Combined liquidity: low to high";
      sortButton.querySelector("span").textContent = state.sortDescending ? "Highest liquidity first" : "Lowest liquidity first";
    }
    const detailToggle = $("sharp-detail-toggle");
    if (detailToggle) {
      detailToggle.setAttribute("aria-pressed", String(state.detailVisible));
      detailToggle.querySelector("span").textContent = state.detailVisible ? "Hide market details" : "Show market details";
    }
    document.querySelector(".sharp-workspace")?.classList.toggle("detail-hidden", !state.detailVisible);
    const activeFilterCount = Number(Boolean(state.sport)) + Number(state.filters.minimumCrossedEdgePercent > 0) + Number(Boolean(state.filters.flow)) + Number(Boolean(state.filters.marketType)) + Number(sportsbookFilterActive());
    $("sharp-filter-count").textContent = String(activeFilterCount);
    $("sharp-filter-count").setAttribute("aria-label", `${activeFilterCount} customized filter group${activeFilterCount === 1 ? "" : "s"}`);
    $("sharp-filter-open").classList.toggle("has-filters", activeFilterCount > 0);
    $("sharp-mode-badge").classList.toggle("live", running && !accessBlocked);
    $("sharp-mode-badge").innerHTML = preview
      ? `<i class="ph ph-flask"></i> Sample data`
      : accessBlocked
      ? `<i class="ph ph-warning-circle"></i> Provider blocked`
      : running ? `<i class="ph ph-waveform"></i> ${quoteConsensus ? "Live price movement" : automatic ? "Live order books" : "Live local feed"}` : `<i class="ph ph-pause"></i> Paused`;
    $("sharp-feed-notice").classList.toggle("live", running && !accessBlocked);
    $("sharp-feed-title").textContent = preview
      ? "Local Sharp Money preview — simulated plays"
      : accessBlocked
      ? advancedPlanRequired ? "OddsEngine Advanced access required" : standardOddsEngine ? "OddsEngine price feed temporarily unavailable" : "Order-book provider unavailable"
      : running
      ? `${sourceName} active`
      : sourceConfigured
        ? "Feed paused - zero new requests"
        : "Order-book credentials required - zero new requests";
    $("sharp-feed-copy").textContent = preview
      ? "All markets, prices and liquidity below are fictional examples. No live provider requests or betting actions are enabled."
      : accessBlocked
      ? providerError
      : running
      ? quoteConsensus
        ? `${sourceName} refreshes every ${payload.refreshSeconds || 30}s from exact two-sided REST prices and sharp-consensus movement.`
        : `${sourceName} refreshes every ${payload.refreshSeconds || payload.pollSeconds || 30}s${automatic ? " with full two-sided depth." : `; other-book comparisons every ${payload.comparisonSeconds || 60}s.`}`
      : sourceConfigured
        ? `Press Play to start ProphetX${comparisonsConfigured ? " and sportsbook comparisons" : "; add an odds feed for other-book comparisons"}.`
        : "Add ODDSENGINE_API_KEY or direct ProphetX credentials, then restart.";
    $("sharp-feed-state").innerHTML = `<i></i> ${preview ? "Preview" : accessBlocked ? "Action required" : running ? "Collecting" : "Paused"}`;
    $("sharp-result-label").textContent = preview ? `${state.visible.length} sample market${state.visible.length === 1 ? "" : "s"}` : accessBlocked ? "Feed unavailable" : running ? `${state.visible.length} monitored market${state.visible.length === 1 ? "" : "s"}` : "Collector paused";
    $("sharp-last-updated").textContent = preview ? "Fictional example data" : payload.lastError
      ? state.visible.length ? `Live source active · ${payload.lastError}` : payload.lastError
      : ageLabel(payload.lastSnapshotAt);
    const liquidity = state.visible.reduce((sum, row) => sum + Number(combinedCrossedLiquidity(row) || 0), 0);
    const flows = state.visible.filter(row => Number(combinedCrossedLiquidity(row) || 0) > 0).length;
    $("sharp-summary-signals").textContent = String(state.visible.length);
    $("sharp-summary-liquidity").textContent = money(liquidity);
    $("sharp-summary-flow").textContent = String(flows);
    $("sharp-summary-cycles").textContent = String(payload.cycles || 0);
    $("sharp-summary-signals-note").textContent = preview ? "Simulated markets" : quoteConsensus ? "Exact two-sided markets" : `Real ${sourceName} markets`;
    $("sharp-summary-liquidity-note").textContent = preview ? "Simulated liquidity" : quoteConsensus ? "Order-book depth unavailable" : "Selected minus opposing liquidity";
    $("sharp-summary-flow-note").textContent = preview ? "Sample signals" : quoteConsensus ? "Awaiting exact liquidity" : "Directional liquidity signals";
    const requests = payload.provider?.metrics?.requests || 0;
    $("sharp-summary-requests").textContent = preview ? "No live requests" : running ? `${requests} ${sourceName} requests this process` : "No requests while paused";
    $("sharp-signal-list").innerHTML = state.visible.length || preview
      ? previewLedger()
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
      $("sharp-last-updated").textContent = state.visible.length
        ? "Live cards retained · refresh temporarily unavailable"
        : "Live feed unavailable";
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
    const filterDialog = $("sharp-filter-dialog");
    if (!filterDialog) return;
    if (open) {
      state.filterDraftSportsbooks = new Set(state.filters.sportsbooks);
      $("sharp-sport-filter").value = state.sport;
      const search = $("sharp-sportsbook-search");
      if (search) search.value = "";
      renderSharpSportsbookFilter();
      if (!filterDialog.open) filterDialog.showModal();
      requestAnimationFrame(() => $("sharp-filter-close")?.focus());
      return;
    }
    if (filterDialog.open) filterDialog.close();
  }

  function readFilters() {
    if (!state.filterDraftSportsbooks.size) {
      window.showToast?.("Select at least one sportsbook");
      return false;
    }
    state.sport = $("sharp-sport-filter").value;
    state.filters.minimumCrossedEdgePercent = Number($("sharp-liquidity-filter").value) || 0;
    state.filters.flow = $("sharp-flow-filter").value;
    state.filters.marketType = $("sharp-market-filter").value;
    state.filters.sportsbooks = new Set(state.filterDraftSportsbooks);
    localStorage.setItem(sharpBookFilterStorageKey, JSON.stringify([...state.filters.sportsbooks]));
    render();
    return true;
  }

  function bind() {
    const moreMenu = $("sharp-more-menu");
    document.querySelector(".sharp-money-page")?.addEventListener("click", event => {
      if (!state.payload?.previewOnly || !event.target.closest("a")) return;
      event.preventDefault();
      event.stopPropagation();
      window.showToast?.("Betting links are disabled in this sample preview");
    }, true);
    let draggedLineShopBook = "";
    const closeMoreMenu = () => {
      moreMenu.hidden = true;
      $("sharp-more").setAttribute("aria-expanded", "false");
    };
    $("sharp-feed-toggle")?.addEventListener("click", () => control(state.payload?.running ? "pause" : "play"));
    $("sharp-sort")?.addEventListener("click", () => {
      state.sortDescending = !state.sortDescending;
      render();
    });
    $("sharp-detail-toggle")?.addEventListener("click", () => {
      state.detailVisible = !state.detailVisible;
      render();
    });
    $("sharp-search").addEventListener("input", event => { state.search = event.target.value.trim().toLowerCase(); render(); });
    $("sharp-preview-view-tabs")?.addEventListener("click", event => {
      const listView = event.target.closest("[data-preview-list-view]");
      if (!listView) return;
      setPreviewListView(listView.dataset.previewListView);
    });
    $("sharp-signal-list").addEventListener("click", event => {
      const restoreButton = event.target.closest("[data-preview-restore]");
      if (restoreButton) {
        restorePreviewSignal(restoreButton.dataset.previewRestore);
        return;
      }
      const trackButton = event.target.closest("[data-preview-track]");
      if (trackButton) {
        const signal = state.signals.find(row => String(row.id) === String(trackButton.dataset.previewTrack));
        if (signal) openPreviewTracker(signal, trackButton);
        return;
      }
      const ledgerCard = event.target.closest(".sharp-ledger-grid")?.closest("[data-sharp-signal]");
      if (ledgerCard) {
        state.previewExpandedId = state.previewExpandedId === ledgerCard.dataset.sharpSignal ? "" : ledgerCard.dataset.sharpSignal;
        render();
        return;
      }
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
      $("sharp-detail-panel").classList.toggle("desktop-overlay-open", compactDesktopDetail.matches);
      document.body.classList.add("sharp-detail-open");
      document.body.classList.toggle("sharp-desktop-detail-open", compactDesktopDetail.matches);
    });
    $("sharp-signal-list").addEventListener("keydown", event => {
      if (event.key !== "Enter" && event.key !== " ") return;
      if (event.target.closest("button")) return;
      const card = event.target.closest("[data-sharp-signal]");
      if (!card) return;
      event.preventDefault();
      state.previewExpandedId = state.previewExpandedId === card.dataset.sharpSignal ? "" : card.dataset.sharpSignal;
      render();
    });
    $("sharp-detail-panel").addEventListener("click", event => {
      if (!event.target.closest("#sharp-detail-close")) return;
      $("sharp-detail-panel").classList.remove("mobile-open", "desktop-overlay-open");
      document.body.classList.remove("sharp-detail-open", "sharp-desktop-detail-open");
    });
    $("sharp-detail-panel").addEventListener("dragstart", event => {
      const row = event.target.closest("[data-line-shop-book]");
      if (!row) return;
      draggedLineShopBook = row.dataset.lineShopBook;
      row.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain",draggedLineShopBook);
    });
    $("sharp-detail-panel").addEventListener("dragover", event => {
      const target = event.target.closest("[data-line-shop-book]");
      if (!draggedLineShopBook || !target || target.dataset.lineShopBook === draggedLineShopBook) return;
      event.preventDefault();
    });
    $("sharp-detail-panel").addEventListener("drop", event => {
      const target = event.target.closest("[data-line-shop-book]");
      if (!target || !draggedLineShopBook || target.dataset.lineShopBook === draggedLineShopBook) return;
      event.preventDefault();
      const order = [...$("sharp-detail-panel").querySelectorAll("[data-line-shop-book]")]
        .map(row => row.dataset.lineShopBook);
      const sourceIndex = order.indexOf(draggedLineShopBook);
      const targetIndex = order.indexOf(target.dataset.lineShopBook);
      if (sourceIndex < 0 || targetIndex < 0) return;
      order.splice(sourceIndex,1);
      order.splice(targetIndex,0,draggedLineShopBook);
      window.IconLabsLineShopOrder?.save(order);
      draggedLineShopBook = "";
      render();
    });
    $("sharp-detail-panel").addEventListener("dragend", () => {
      draggedLineShopBook = "";
      $("sharp-detail-panel").querySelectorAll("[data-line-shop-book].dragging").forEach(row=>row.classList.remove("dragging"));
    });
    $("sharp-detail-panel").addEventListener("keydown", event => {
      if (!event.altKey || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      const row = event.target.closest("[data-line-shop-book]");
      if (!row) return;
      const order = [...$("sharp-detail-panel").querySelectorAll("[data-line-shop-book]")]
        .map(item => item.dataset.lineShopBook);
      const index = order.indexOf(row.dataset.lineShopBook);
      const targetIndex = index + (event.key === "ArrowLeft" ? -1 : 1);
      if (index < 0 || targetIndex < 0 || targetIndex >= order.length) return;
      event.preventDefault();
      [order[index], order[targetIndex]] = [order[targetIndex], order[index]];
      const focusedKey = row.dataset.lineShopBook;
      window.IconLabsLineShopOrder?.save(order);
      render();
      requestAnimationFrame(() => $("sharp-detail-panel").querySelector(`[data-line-shop-book="${CSS.escape(focusedKey)}"]`)?.focus());
    });
    $("sharp-filter-open").addEventListener("click", () => openFilters(true));
    $("sharp-more")?.addEventListener("click", event => {
      event.stopPropagation();
      setPreviewBankrollPopover(false);
      moreMenu.hidden = !moreMenu.hidden;
      $("sharp-more").setAttribute("aria-expanded", String(!moreMenu.hidden));
      if (!moreMenu.hidden) requestAnimationFrame(() => moreMenu.querySelector('[aria-current="true"]')?.focus());
    });
    $("sharp-menu-refresh")?.addEventListener("click", () => { closeMoreMenu(); load(); });
    $("sharp-menu-pause")?.addEventListener("click", () => {
      state.refreshPaused = !state.refreshPaused;
      closeMoreMenu();
      render();
      if (!state.refreshPaused) load();
    });
    moreMenu.addEventListener("click", event => {
      event.stopPropagation();
      const listView = event.target.closest("[data-preview-list-view]");
      if (!listView) return;
      closeMoreMenu();
      setPreviewListView(listView.dataset.previewListView);
    });
    $("sharp-bankroll-popover-button")?.addEventListener("click", event => {
      event.stopPropagation();
      closeMoreMenu();
      setPreviewBankrollPopover($("sharp-bankroll-popover").hidden);
    });
    $("sharp-save-bankroll")?.addEventListener("click", savePreviewBankroll);
    $("sharp-bankroll-input")?.addEventListener("input", () => {
      $("sharp-bankroll-save-state").textContent = "Unsaved changes";
    });
    $("sharp-bankroll-input")?.addEventListener("keydown", event => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      savePreviewBankroll();
    });
    document.addEventListener("click", event => {
      if (!event.target.closest(".sharp-more-shell")) closeMoreMenu();
      if (!event.target.closest(".sharp-bankroll-popover-shell")) setPreviewBankrollPopover(false);
    });
    $("sharp-filter-close").addEventListener("click", () => openFilters(false));
    $("sharp-filter-apply").addEventListener("click", () => { if (readFilters()) openFilters(false); });
    $("sharp-filter-reset").addEventListener("click", () => {
      $("sharp-sport-filter").value = "";
      $("sharp-liquidity-filter").value = "0";
      $("sharp-liquidity-value").textContent = "0%";
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
    $("sharp-liquidity-filter").addEventListener("input", event => { $("sharp-liquidity-value").textContent = `${Number(event.target.value).toFixed(Number(event.target.value)%1?1:0)}%`; });
    $("sharp-filter-dialog")?.querySelectorAll("[data-sharp-filter-panel]").forEach(button => button.addEventListener("click", () => {
      $("sharp-filter-dialog").querySelectorAll("[data-sharp-filter-panel], [data-sharp-filter-content]").forEach(item => item.classList.remove("active"));
      button.classList.add("active");
      $("sharp-filter-dialog").querySelector(`[data-sharp-filter-content="${button.dataset.sharpFilterPanel}"]`)?.classList.add("active");
    }));
    document.addEventListener("keydown", event => {
      if (event.key !== "Escape") return;
      closeMoreMenu();
      setPreviewBankrollPopover(false);
      openFilters(false);
      $("sharp-detail-panel").classList.remove("mobile-open", "desktop-overlay-open");
      document.body.classList.remove("sharp-detail-open", "sharp-desktop-detail-open");
    });
    compactDesktopDetail.addEventListener?.("change", () => {
      $("sharp-detail-panel").classList.remove("desktop-overlay-open");
      document.body.classList.remove("sharp-desktop-detail-open");
    });
    window.addEventListener("iconlabs:line-shop-order",render);
    window.addEventListener(window.IconLabsOdds.EVENT,render);
    updatePreviewBankroll();
  }

  if (document.body.dataset.page === "sharp-money") {
    bind();
    load();
    window.setInterval(() => { if (!state.refreshPaused) load(); }, 30000);
  }
})();
