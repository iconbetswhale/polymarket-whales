const historyState = {
  page: 1,
  perPage: 50,
  loading: false,
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function formatMoney(value) {
  return Number(value || 0).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
}

function formatDate(value) {
  if (!value) return "n/a";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function eventLabel(eventType) {
  const labels = {
    new_entry: "New Entry",
    size_increase: "Increased",
    size_decrease: "Decreased",
    full_exit: "Exit",
    price_change: "Price Change",
    avg_price_change: "Avg Price",
    current_value_change: "Value Change",
    unrealized_pnl_change: "P&L Change",
  };
  return labels[eventType] || eventType || "Event";
}

async function fetchHistory() {
  if (historyState.loading) return;
  historyState.loading = true;
  document.body.classList.add("loading");
  try {
    const response = await fetch(`/api/history?page=${historyState.page}&per_page=${historyState.perPage}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    renderHistory(payload);
  } finally {
    historyState.loading = false;
    document.body.classList.remove("loading");
  }
}

function renderHistory(payload) {
  const rows = payload.data || [];
  const tbody = document.querySelector("#history-table tbody");
  tbody.innerHTML = rows.length
    ? rows.map((trade) => `
      <tr>
        <td>${escapeHtml(formatDate(trade.detected_at))}</td>
        <td><span class="event-badge">${escapeHtml(eventLabel(trade.event_type))}</span></td>
        <td>${escapeHtml(trade.wallet_label)}</td>
        <td class="market-cell"><span class="market-title" title="${escapeHtml(trade.market_title)}">${escapeHtml(trade.market_title)}</span></td>
        <td>${escapeHtml(trade.outcome)}</td>
        <td>${escapeHtml(trade.category)}</td>
        <td>${formatMoney(trade.current_value)}</td>
      </tr>
    `).join("")
    : '<tr><td class="empty-row" colspan="7">No position history recorded yet.</td></tr>';

  document.getElementById("history-count").textContent = `${payload.total || 0} total events`;
  document.getElementById("history-page-label").textContent = `Page ${payload.page || 1}`;
  document.getElementById("history-prev").disabled = !payload.has_prev;
  document.getElementById("history-next").disabled = !payload.has_next;
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("history-refresh").addEventListener("click", fetchHistory);
  document.getElementById("history-prev").addEventListener("click", () => {
    historyState.page = Math.max(1, historyState.page - 1);
    fetchHistory();
  });
  document.getElementById("history-next").addEventListener("click", () => {
    historyState.page += 1;
    fetchHistory();
  });
  fetchHistory();
});
