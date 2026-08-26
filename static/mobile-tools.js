(() => {
  "use strict";

  const mobileViewport = window.matchMedia("(max-width: 760px)");
  const nextFrame = (callback) => window.requestAnimationFrame(() => window.requestAnimationFrame(callback));

  function setupInlineDisclosure(config) {
    const feed = document.querySelector(config.feed);
    const detail = document.querySelector(config.detail);
    if (!feed || !detail) return;

    const home = detail.parentNode;
    const anchor = document.createComment(`${config.name}-mobile-detail-home`);
    home.insertBefore(anchor, detail);
    let userOpened = false;
    let activeId = "";
    let mounting = false;

    const cardId = (card) => String(
      card?.getAttribute(config.idAttribute)
      || card?.dataset.tradeId
      || (config.trigger ? card?.querySelector(config.trigger)?.getAttribute("data-trade-view") : "")
      || ""
    );
    const selectedCard = () => {
      if (activeId) {
        const exact = [...feed.querySelectorAll(config.card)].find((card) => cardId(card) === activeId);
        if (exact) return exact;
      }
      return feed.querySelector(config.selectedCard);
    };

    function clearPresentation() {
      feed.querySelectorAll(`${config.card}.mobile-expanded`).forEach((card) => {
        card.classList.remove("mobile-expanded");
        card.setAttribute("aria-expanded", "false");
      });
      detail.classList.remove("mobile-inline-detail", "mobile-open");
      (config.bodyClasses || []).forEach((className) => document.body.classList.remove(className));
      const overlay = config.overlay ? document.querySelector(config.overlay) : null;
      if (overlay) overlay.hidden = true;
    }

    function restoreHome() {
      if (anchor.parentNode && detail.parentNode !== anchor.parentNode) {
        anchor.parentNode.insertBefore(detail, anchor.nextSibling);
      }
      detail.classList.remove("mobile-inline-detail", "mobile-open");
    }

    function hideMobileHomeDetail() {
      if (!mobileViewport.matches || userOpened) return;
      restoreHome();
      clearPresentation();
      detail.setAttribute("aria-hidden", "true");
      detail.setAttribute("inert", "");
      detail.removeAttribute("role");
      detail.removeAttribute("aria-modal");
    }

    function mount() {
      if (mounting) return;
      mounting = true;
      try {
        if (!mobileViewport.matches) {
          restoreHome();
          clearPresentation();
          detail.removeAttribute("aria-hidden");
          detail.removeAttribute("inert");
          return;
        }
        if (!userOpened) {
          hideMobileHomeDetail();
          return;
        }
        const card = selectedCard();
        if (!card) {
          restoreHome();
          clearPresentation();
          detail.setAttribute("aria-hidden", "true");
          detail.setAttribute("inert", "");
          return;
        }
        clearPresentation();
        activeId = cardId(card) || activeId;
        card.classList.add("mobile-expanded");
        card.setAttribute("aria-expanded", "true");
        const trigger = config.trigger ? card.querySelector(config.trigger) : null;
        if (trigger && !trigger.querySelector(".mobile-card-caret")) {
          const caret = document.createElement("i");
          caret.className = "ph ph-caret-down mobile-card-caret";
          caret.setAttribute("aria-hidden", "true");
          trigger.append(caret);
        }
        detail.classList.add("mobile-inline-detail");
        detail.classList.remove("mobile-open");
        detail.removeAttribute("inert");
        detail.setAttribute("aria-hidden", "false");
        detail.setAttribute("role", "region");
        detail.removeAttribute("aria-modal");
        card.insertAdjacentElement("afterend", detail);
      } finally {
        mounting = false;
      }
    }

    function queueMount() {
      window.queueMicrotask(() => nextFrame(mount));
    }

    document.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof Element) || detail.contains(target)) return;
      const card = target.closest(config.card);
      if (!card || !feed.contains(card)) return;
      if (config.trigger && !target.closest(config.trigger)) return;
      if (!config.trigger) {
        const interactive = target.closest("a, button, input, select, textarea, summary");
        if (interactive && interactive !== card) return;
      }

      const clickedId = cardId(card);
      if (userOpened && activeId === clickedId && card.classList.contains("mobile-expanded")) {
        event.preventDefault();
        event.stopImmediatePropagation();
        userOpened = false;
        activeId = "";
        restoreHome();
        hideMobileHomeDetail();
        return;
      }

      restoreHome();
      userOpened = true;
      activeId = clickedId;
      queueMount();
    }, true);

    detail.addEventListener("click", (event) => {
      if (!event.target.closest(config.close)) return;
      userOpened = false;
      activeId = "";
      window.queueMicrotask(() => {
        restoreHome();
        hideMobileHomeDetail();
      });
    }, true);

    const overlay = config.overlay ? document.querySelector(config.overlay) : null;
    overlay?.addEventListener("click", () => {
      userOpened = false;
      activeId = "";
      queueMount();
    }, true);

    const feedObserver = new MutationObserver(() => {
      if (!detail.isConnected) restoreHome();
      if (userOpened) queueMount();
      else hideMobileHomeDetail();
    });
    feedObserver.observe(feed, { childList: true });

    const detailObserver = new MutationObserver(() => {
      if (userOpened) queueMount();
      else hideMobileHomeDetail();
    });
    detailObserver.observe(detail, { childList: true });

    const onViewportChange = () => {
      if (mobileViewport.matches) {
        if (userOpened) mount();
        else hideMobileHomeDetail();
      } else {
        restoreHome();
        clearPresentation();
        detail.removeAttribute("aria-hidden");
        detail.removeAttribute("inert");
        detail.removeAttribute("role");
      }
    };
    mobileViewport.addEventListener?.("change", onViewportChange);
    onViewportChange();
  }

  function cellLabel(cell, index) {
    const header = document.querySelectorAll("#dfs-head-row th")[index];
    const image = header?.querySelector("img");
    return String(image?.alt || image?.title || header?.textContent || `Column ${index + 1}`).trim();
  }

  function appendCellContent(target, source) {
    const wrapper = document.createElement("span");
    wrapper.className = "dfs-mobile-cell-value";
    [...source.childNodes].forEach((node) => wrapper.append(node.cloneNode(true)));
    if (!wrapper.textContent.trim() && !wrapper.querySelector("img")) wrapper.textContent = "—";
    target.append(wrapper);
  }

  function setupDfsCards() {
    const tableShell = document.querySelector(".dfs-table-shell");
    const table = tableShell?.querySelector(".dfs-table");
    const body = document.getElementById("dfs-body");
    if (!tableShell || !table || !body) return;

    const list = document.createElement("div");
    list.className = "dfs-mobile-list";
    list.id = "dfs-mobile-list";
    list.setAttribute("aria-live", "polite");
    table.insertAdjacentElement("afterend", list);

    function renderCards() {
      const openKey = list.querySelector("details[open]")?.dataset.rowKey || "";
      const rows = [...body.querySelectorAll("tr")];
      const fragment = document.createDocumentFragment();
      rows.forEach((row, rowIndex) => {
        const cells = [...row.children];
        if (cells.length < 6) return;
        const player = cells[0].querySelector("strong")?.textContent?.trim() || "Player";
        const matchup = cells[0].querySelector("small")?.textContent?.trim() || "";
        const timing = cells[0].querySelector("em")?.textContent?.trim() || "";
        const side = cells[1].textContent.trim();
        const stat = cells[2].textContent.trim();
        const line = cells[3].textContent.trim() || "—";
        const hit = cells[4].textContent.trim() || "—";
        const key = `${player}|${side}|${stat}|${line}`;

        const details = document.createElement("details");
        details.className = "dfs-mobile-player";
        details.dataset.rowKey = key;
        if (openKey === key) details.open = true;

        const summary = document.createElement("summary");
        const mark = document.createElement("span");
        mark.className = "dfs-mobile-app-mark";
        const activeLogo = document.querySelector("#dfs-line-head img")?.cloneNode(true);
        if (activeLogo) mark.append(activeLogo);
        else {
          const icon = document.createElement("i");
          icon.className = "ph ph-user";
          icon.setAttribute("aria-hidden", "true");
          mark.append(icon);
        }

        const copy = document.createElement("span");
        copy.className = "dfs-mobile-player-copy";
        const title = document.createElement("strong");
        title.textContent = player;
        const pick = document.createElement("span");
        pick.textContent = `${side} ${line} · ${stat}`;
        const meta = document.createElement("small");
        meta.textContent = [matchup, timing].filter(Boolean).join(" · ");
        copy.append(title, pick, meta);

        const score = document.createElement("span");
        score.className = "dfs-mobile-hit";
        const scoreValue = document.createElement("strong");
        scoreValue.textContent = hit;
        const scoreLabel = document.createElement("small");
        scoreLabel.textContent = "to hit";
        score.append(scoreValue, scoreLabel);

        const caret = document.createElement("i");
        caret.className = "ph ph-caret-down";
        caret.setAttribute("aria-hidden", "true");
        summary.append(mark, copy, score, caret);

        const detail = document.createElement("div");
        detail.className = "dfs-mobile-player-detail";
        const highlights = document.createElement("div");
        highlights.className = "dfs-mobile-highlights";
        [["App line", 3], ["Chance to hit", 4], ["IconLabs fair odds", 5]].forEach(([label, index]) => {
          const item = document.createElement("div");
          const itemLabel = document.createElement("span");
          itemLabel.textContent = label;
          item.append(itemLabel);
          appendCellContent(item, cells[index]);
          highlights.append(item);
        });

        const comparisonTitle = document.createElement("h3");
        comparisonTitle.textContent = "All book comparisons";
        const comparison = document.createElement("div");
        comparison.className = "dfs-mobile-comparisons";
        cells.slice(6).forEach((cell, offset) => {
          const item = document.createElement("div");
          const label = document.createElement("span");
          label.textContent = cellLabel(cell, offset + 6);
          item.append(label);
          appendCellContent(item, cell);
          comparison.append(item);
        });
        detail.append(highlights, comparisonTitle, comparison);
        details.append(summary, detail);
        details.addEventListener("toggle", () => {
          if (!details.open) return;
          list.querySelectorAll("details[open]").forEach((other) => {
            if (other !== details) other.open = false;
          });
        });
        fragment.append(details);
      });
      list.replaceChildren(fragment);
      list.hidden = rows.length === 0;
    }

    new MutationObserver(renderCards).observe(body, { childList: true });
    document.querySelectorAll("[data-dfs-book]").forEach((button) => button.addEventListener("click", () => nextFrame(renderCards)));
    renderCards();
  }

  function setupNavigationState() {
    const links = document.getElementById("primary-links");
    if (!links) return;
    const sync = () => document.body.classList.toggle("mobile-menu-open", links.classList.contains("open") && mobileViewport.matches);
    new MutationObserver(sync).observe(links, { attributes: true, attributeFilter: ["class"] });
    mobileViewport.addEventListener?.("change", sync);
    sync();
  }

  document.addEventListener("DOMContentLoaded", () => {
    setupNavigationState();
    setupDfsCards();

    [
      { name: "trades", feed: "#trade-list", detail: "#trade-detail", card: ".trade-card", selectedCard: ".trade-card.selected", idAttribute: "data-trade-id", trigger: ".trade-event-action", close: "[data-mobile-detail-close]", overlay: "#mobile-trade-detail-backdrop", bodyClasses: ["mobile-trade-detail-open"] },
      { name: "positive-ev", feed: "#ev-feed", detail: "#ev-detail", card: ".ev-opportunity", selectedCard: ".ev-opportunity.active", idAttribute: "data-id", trigger: "[data-open]", close: ".ev-detail-close", overlay: "#ev-mobile-scrim" },
      { name: "arbitrage", feed: "#arb-feed", detail: "#arb-detail", card: ".arb-opportunity", selectedCard: ".arb-opportunity.active", idAttribute: "data-arb-id", close: "[data-arb-close-detail]", overlay: "#arb-mobile-scrim" },
      { name: "middles", feed: "#mid-feed", detail: "#mid-detail", card: ".mid-opportunity-card", selectedCard: ".mid-opportunity-card.selected", idAttribute: "data-mid-id", close: "[data-mid-mobile-close]", overlay: "#mid-mobile-backdrop", bodyClasses: ["mid-detail-open"] },
      { name: "low-hold", feed: "#lh-feed", detail: "#lh-detail", card: ".arb-opportunity", selectedCard: ".arb-opportunity.active", idAttribute: "data-lh-id", close: "[data-lh-close-detail]", overlay: "#lh-mobile-scrim" },
      { name: "sharp-money", feed: "#sharp-signal-list", detail: "#sharp-detail-panel", card: ".sharp-signal-card", selectedCard: ".sharp-signal-card.selected", idAttribute: "data-sharp-signal", close: "#sharp-detail-close", bodyClasses: ["sharp-detail-open"] },
    ].forEach(setupInlineDisclosure);
  });
})();
