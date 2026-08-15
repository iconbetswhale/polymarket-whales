(() => {
  const state = {
    scope: "signal",
    source: "all",
    window: "7d",
    display: localStorage.getItem("iconlabs-lab-display") || "dollars",
    log: "graded",
    data: null,
  };

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");

  function amount(value, signed = true) {
    const number = Number(value || 0);
    if (state.display === "units") {
      const units = number / 100;
      return `${signed && units > 0 ? "+" : ""}${units.toFixed(1)} u`;
    }
    const absolute = Math.abs(number);
    const digits = absolute >= 1000 ? 0 : 2;
    return `${number < 0 ? "-" : signed && number > 0 ? "+" : ""}$${absolute.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })}`;
  }

  function odds(value) {
    const number = Number(value || 0);
    return number > 0 ? `+${number}` : String(number);
  }

  function rowIcon(item, fallback) {
    if (item.logo) return `<img src="${escapeHtml(item.logo)}" alt="" loading="lazy">`;
    return `<span class="lab-rank-icon"><i class="ph ${fallback}" aria-hidden="true"></i></span>`;
  }

  function renderRanking(target, rows, icon) {
    const root = $(target);
    const visible = (rows || []).slice(0, 12);
    if (!visible.length) {
      root.innerHTML = `<div class="lab-empty"><i class="ph ph-hourglass"></i><strong>No graded plays yet</strong><span>Rankings appear after verified results.</span></div>`;
      return;
    }
    root.innerHTML = visible.map((item) => `
      <div class="lab-rank-row">
        ${rowIcon(item, icon)}
        <div class="lab-rank-copy"><strong>${escapeHtml(item.name)}</strong><small>${item.wins}-${item.losses}</small></div>
        <span class="lab-rank-profit ${Number(item.profit) < 0 ? "loss" : ""}">${amount(item.profit)}</span>
      </div>`).join("");
  }

  function betCard(row, open) {
    const pnl = Number(row.profit_loss || 0);
    const source = row.source === "positive_ev" ? "+EV" : "Sharp";
    const resultLabel = open ? amount(-Number(row.stake || 100), false) : amount(pnl);
    const time = new Date(row.commence_time || row.created_at);
    const details = Number.isNaN(time.getTime()) ? row.event_title : `${row.event_title} · ${time.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`;
    return `
      <article class="lab-bet-card">
        <div class="lab-bet-pnl"><strong class="${!open && pnl < 0 ? "loss" : ""}">${resultLabel}</strong><span>${open ? "1.0 u risk" : row.result || "graded"}</span></div>
        <div class="lab-bet-main"><strong><span class="lab-source-pill">${source}</span>${escapeHtml(row.selection)}</strong><p>${escapeHtml(row.market_label)}</p><small>${escapeHtml(details)}</small></div>
        <div class="lab-bet-book">${row.sportsbook_logo ? `<img src="${escapeHtml(row.sportsbook_logo)}" alt="">` : `<span class="lab-rank-icon"><i class="ph ph-buildings"></i></span>`}<div><span>${escapeHtml(row.sportsbook_name)}</span><strong>${odds(row.entry_american_odds)}</strong></div></div>
        ${open && state.scope === "signal" ? `<button class="lab-track-button" type="button" data-personal-bet="${escapeHtml(row.bet_id)}"><i class="ph ph-check"></i> I took this bet</button>` : ""}
      </article>`;
  }

  function renderLog() {
    const open = state.log === "open";
    const rows = open ? state.data.openBets : state.data.lastGraded;
    $("#lab-log-caption").textContent = open ? `${rows.length} active signals` : "Last 5 graded";
    if (!rows.length) {
      $("#lab-bet-log").innerHTML = `<div class="lab-empty"><i class="ph ${open ? "ph-radar" : "ph-check-circle"}"></i><strong>${open ? "No open plays" : "No graded plays yet"}</strong><span>${state.scope === "personal" ? "Use I took this bet on an open signal to start your personal LabTracker." : "Verified plays will appear here automatically."}</span></div>`;
      return;
    }
    $("#lab-bet-log").innerHTML = rows.map((row) => betCard(row, open)).join("");
    $$('[data-personal-bet]').forEach((button) => button.addEventListener("click", () => takeBet(button)));
  }

  function drawChart() {
    const canvas = $("#lab-chart");
    const points = state.data.curve || [];
    $("#lab-chart-empty").hidden = points.length > 0;
    $("#lab-chart-total").textContent = amount(state.data.summary.profit);
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    canvas.width = Math.max(1, Math.floor(width * ratio));
    canvas.height = Math.max(1, Math.floor(height * ratio));
    const ctx = canvas.getContext("2d");
    ctx.scale(ratio, ratio);
    ctx.clearRect(0, 0, width, height);
    if (!points.length) return;
    const values = [0, ...points.map((point) => Number(point.profit || 0))];
    let min = Math.min(...values), max = Math.max(...values);
    if (min === max) { min -= 100; max += 100; }
    const pad = { left: 38, right: 10, top: 14, bottom: 26 };
    const chartWidth = width - pad.left - pad.right;
    const chartHeight = height - pad.top - pad.bottom;
    const x = (index) => pad.left + chartWidth * (index / Math.max(1, values.length - 1));
    const y = (value) => pad.top + chartHeight * (1 - (value - min) / (max - min));
    ctx.font = "10px DM Sans";
    ctx.strokeStyle = "rgba(114,132,153,.18)";
    ctx.fillStyle = "#718095";
    ctx.lineWidth = 1;
    for (let index = 0; index < 4; index += 1) {
      const value = min + (max - min) * (index / 3);
      const lineY = y(value);
      ctx.beginPath(); ctx.moveTo(pad.left, lineY); ctx.lineTo(width - pad.right, lineY); ctx.stroke();
      ctx.fillText(state.display === "units" ? `${(value / 100).toFixed(1)}u` : `$${Math.round(value)}`, 0, lineY + 3);
    }
    const gradient = ctx.createLinearGradient(0, pad.top, 0, height - pad.bottom);
    gradient.addColorStop(0, "rgba(22,214,160,.28)");
    gradient.addColorStop(1, "rgba(22,214,160,0)");
    ctx.beginPath();
    values.forEach((value, index) => index ? ctx.lineTo(x(index), y(value)) : ctx.moveTo(x(index), y(value)));
    ctx.lineTo(x(values.length - 1), height - pad.bottom); ctx.lineTo(x(0), height - pad.bottom); ctx.closePath();
    ctx.fillStyle = gradient; ctx.fill();
    ctx.beginPath();
    values.forEach((value, index) => index ? ctx.lineTo(x(index), y(value)) : ctx.moveTo(x(index), y(value)));
    ctx.strokeStyle = "#16d6a0"; ctx.lineWidth = 2; ctx.stroke();
    ctx.fillStyle = "#16d6a0"; ctx.beginPath(); ctx.arc(x(values.length - 1), y(values.at(-1)), 4, 0, Math.PI * 2); ctx.fill();
  }

  function render() {
    const summary = state.data.summary;
    $("#lab-profit-label").textContent = state.display === "units" ? "Units" : "Profit";
    $("#lab-profit").textContent = amount(summary.profit);
    $("#lab-roi").textContent = `${Number(summary.roi).toFixed(1)}%`;
    $("#lab-record").textContent = `${summary.wins}-${summary.losses}${summary.pushes ? `-${summary.pushes}` : ""}`;
    $("#lab-win-rate").textContent = `${Number(summary.winRate).toFixed(1)}%`;
    $("#lab-stake-caption").textContent = state.display === "units" ? "1 u = $100" : "$100 flat bets";
    renderRanking("#lab-sportsbooks", state.data.sportsbooks, "ph-buildings");
    renderRanking("#lab-leagues", state.data.leagues, "ph-trophy");
    renderRanking("#lab-markets", state.data.markets, "ph-chart-line-up");
    renderLog();
    drawChart();
  }

  async function load() {
    const params = new URLSearchParams({ scope: state.scope, window: state.window });
    if (state.source !== "all") params.set("source", state.source);
    try {
      const response = await fetch(`/api/lab-tracker?${params}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`Request failed (${response.status})`);
      state.data = (await response.json()).data;
      render();
    } catch (error) {
      $("#lab-bet-log").innerHTML = `<div class="lab-empty"><i class="ph ph-warning-circle"></i><strong>LabTracker is unavailable</strong><span>${escapeHtml(error.message)}</span></div>`;
    }
  }

  async function takeBet(button) {
    button.disabled = true;
    button.textContent = "Saving...";
    const response = await fetch("/api/lab-tracker/personal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ betId: button.dataset.personalBet }),
    });
    if (!response.ok) {
      button.disabled = false;
      button.textContent = "Try again";
      return;
    }
    button.textContent = "Added to My Bets";
  }

  $$('[data-lab-source]').forEach((button) => button.addEventListener("click", () => {
    state.scope = "signal"; state.source = button.dataset.labSource;
    $$('.lab-tabs button').forEach((item) => item.classList.toggle("active", item === button));
    load();
  }));
  $('[data-lab-scope="personal"]').addEventListener("click", (event) => {
    state.scope = "personal"; state.source = "all";
    $$('.lab-tabs button').forEach((item) => item.classList.toggle("active", item === event.currentTarget));
    load();
  });
  $$('[data-lab-display]').forEach((button) => button.addEventListener("click", () => {
    state.display = button.dataset.labDisplay;
    localStorage.setItem("iconlabs-lab-display", state.display);
    $$('[data-lab-display]').forEach((item) => item.classList.toggle("active", item === button));
    if (state.data) render();
  }));
  $$('[data-lab-window]').forEach((button) => button.addEventListener("click", () => {
    state.window = button.dataset.labWindow;
    $$('[data-lab-window]').forEach((item) => item.classList.toggle("active", item === button));
    load();
  }));
  $$('[data-lab-log]').forEach((button) => button.addEventListener("click", () => {
    state.log = button.dataset.labLog;
    $$('[data-lab-log]').forEach((item) => item.classList.toggle("active", item === button));
    if (state.data) renderLog();
  }));
  $$('[data-lab-display]').forEach((button) => button.classList.toggle("active", button.dataset.labDisplay === state.display));
  window.addEventListener("resize", () => state.data && drawChart());
  load();
})();
