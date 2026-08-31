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

  function appendCellContent(target, source) {
    const wrapper = document.createElement("span");
    wrapper.className = "dfs-mobile-cell-value";
    [...source.childNodes].forEach((node) => wrapper.append(node.cloneNode(true)));
    if (!wrapper.textContent.trim() && !wrapper.querySelector("img")) wrapper.textContent = "—";
    target.append(wrapper);
  }

  function readDfsMobileDetail(row) {
    try {
      return JSON.parse(decodeURIComponent(row?.dataset.mobileDetail || ""));
    } catch (_) {
      return null;
    }
  }

  function appendDfsLogoValue(target, image, source, accessibleLabel) {
    target.classList.add("dfs-mobile-logo-value");
    target.setAttribute("aria-label", accessibleLabel);
    const logo = image?.cloneNode(true);
    if (logo) {
      logo.alt = "";
      logo.setAttribute("aria-hidden", "true");
      target.append(logo);
    }
    appendCellContent(target, source);
  }

  function appendDfsComparisonSide(target, label, snapshot) {
    const side = document.createElement("span");
    side.className = "dfs-mobile-comparison-side";
    const sideLabel = document.createElement("small");
    sideLabel.textContent = label;
    const value = document.createElement("strong");
    value.textContent = snapshot?.display || "—";
    side.append(sideLabel, value);
    if (snapshot?.secondary) {
      const secondary = document.createElement("em");
      secondary.textContent = snapshot.secondary;
      side.append(secondary);
    }
    target.append(side);
  }

  function dfsComparisonMeta(key) {
    const header = [...document.querySelectorAll("#dfs-head-row [data-book-key]")]
      .find((cell) => cell.dataset.bookKey === key);
    const image = header?.querySelector("img");
    return {
      name: String(image?.alt || image?.title || key || "Sportsbook").trim(),
      logo: image?.src || "",
    };
  }

  function setupDfsFilters() {
    const toggle = document.getElementById("dfs-mobile-filter-toggle");
    const summary = document.getElementById("dfs-mobile-filter-summary");
    const bar = document.getElementById("dfs-filter-bar");
    const deck = document.querySelector(".dfs-control-deck");
    if (!toggle || !summary || !bar || !deck) return;

    const controls = [...bar.querySelectorAll("select, input")];
    const syncSummary = () => {
      const active = controls.filter((control) => {
        const value = String(control.value || "").trim();
        if (!value) return false;
        if (control.id === "dfs-date" && value === "next_7_days") return false;
        return true;
      }).length;
      summary.textContent = active ? `${active} active` : "All plays";
    };
    const setOpen = (open) => {
      const expanded = Boolean(open && mobileViewport.matches);
      toggle.setAttribute("aria-expanded", String(expanded));
      bar.classList.toggle("mobile-open", expanded);
      deck.classList.toggle("mobile-filters-open", expanded);
    };

    toggle.addEventListener("click", () => setOpen(toggle.getAttribute("aria-expanded") !== "true"));
    controls.forEach((control) => {
      control.addEventListener("change", syncSummary);
      control.addEventListener("input", syncSummary);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        setOpen(false);
        toggle.focus();
      }
    });
    mobileViewport.addEventListener?.("change", () => setOpen(false));
    syncSummary();
    setOpen(false);
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
        const statNumber = cells[2].querySelector(".dfs-stat-number")?.textContent?.trim() || "";
        const statLabel = cells[2].querySelector(".dfs-stat-label")?.textContent?.trim() || "";
        const stat = [statNumber, statLabel].filter(Boolean).join(" ") || cells[2].textContent.trim();
        const line = cells[3].textContent.trim() || "—";
        const hit = cells[4].textContent.trim() || "—";
        const hitRate = cells[4].querySelector(".hit-rate");
        const hitRateBand = ["positive-edge", "near-threshold", "negative-edge", "below-threshold"]
          .find((band) => hitRate?.classList.contains(band)) || "below-threshold";
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
        score.className = `dfs-mobile-hit ${hitRateBand}`;
        const scoreValue = document.createElement("strong");
        scoreValue.textContent = hit;
        const scoreLabel = document.createElement("small");
        scoreLabel.textContent = "to hit";
        score.append(scoreValue, scoreLabel);

        const caret = document.createElement("i");
        caret.className = "ph ph-caret-down";
        caret.setAttribute("aria-hidden", "true");
        summary.append(mark, copy, score, caret);

        const mobileDetail = readDfsMobileDetail(row);
        const detail = document.createElement("div");
        detail.className = "dfs-mobile-player-detail";
        const highlights = document.createElement("div");
        highlights.className = "dfs-mobile-highlights";
        const appValue = document.createElement("div");
        appendDfsLogoValue(
          appValue,
          document.querySelector("#dfs-line-head img"),
          cells[3],
          `Selected app odds ${cells[3].textContent.trim() || "unavailable"}`,
        );
        const chanceValue = document.createElement("div");
        chanceValue.className = "dfs-mobile-hit-value";
        const chanceLabel = document.createElement("small");
        chanceLabel.textContent = "Hit";
        chanceValue.append(chanceLabel);
        appendCellContent(chanceValue, cells[4]);
        const algoValue = document.createElement("div");
        appendDfsLogoValue(
          algoValue,
          document.querySelector("#dfs-algo-odds-head img"),
          cells[5],
          `IconLabs fair odds ${cells[5].textContent.trim() || "unavailable"}`,
        );
        highlights.append(appValue, chanceValue, algoValue);

        const comparisonTitle = document.createElement("h3");
        const comparisonTitleText = document.createElement("span");
        comparisonTitleText.textContent = "All book comparisons";
        const comparisonLegend = document.createElement("small");
        comparisonLegend.textContent = "O  Over   ·   U  Under";
        comparisonTitle.append(comparisonTitleText, comparisonLegend);
        const comparison = document.createElement("div");
        comparison.className = "dfs-mobile-comparisons";
        (mobileDetail?.books || []).forEach((bookKey) => {
          const book = dfsComparisonMeta(bookKey);
          const item = document.createElement("div");
          item.className = "dfs-mobile-comparison";
          item.title = book.name || "Sportsbook";
          item.setAttribute(
            "aria-label",
            `${book.name || "Sportsbook"}: Over ${mobileDetail.over?.books?.[bookKey]?.display || "unavailable"}, Under ${mobileDetail.under?.books?.[bookKey]?.display || "unavailable"}`,
          );
          const logo = document.createElement("span");
          logo.className = "dfs-mobile-comparison-logo";
          if (book.logo) {
            const image = document.createElement("img");
            image.src = book.logo;
            image.alt = book.name || "";
            image.title = book.name || "";
            logo.append(image);
          }
          const prices = document.createElement("span");
          prices.className = "dfs-mobile-comparison-prices";
          appendDfsComparisonSide(prices, "O", mobileDetail.over?.books?.[bookKey]);
          appendDfsComparisonSide(prices, "U", mobileDetail.under?.books?.[bookKey]);
          item.append(logo, prices);
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

  function setupDfsAppPicker() {
    const select = document.getElementById("dfs-mobile-book-select");
    const books = [...document.querySelectorAll("[data-dfs-book]")];
    if (!select || !books.length) return;

    const syncOptions = () => {
      const activeBook = books.find((book) => book.classList.contains("active"))?.dataset.dfsBook || "";
      [...select.options].forEach((option) => {
        option.hidden = Boolean(option.value) && option.value === activeBook;
      });
      select.value = "";
    };

    select.addEventListener("change", () => {
      const nextBook = books.find((book) => book.dataset.dfsBook === select.value);
      nextBook?.click();
      syncOptions();
    });
    books.forEach((book) => book.addEventListener("click", syncOptions));
    syncOptions();
  }

  function setupSampleTradeDisclosures() {
    const samples = document.getElementById("mobile-trade-samples");
    if (!samples) return;
    samples.addEventListener("toggle", (event) => {
      const details = event.target;
      if (!(details instanceof HTMLDetailsElement) || !details.open) return;
      samples.querySelectorAll("details[open]").forEach((other) => {
        if (other !== details) other.open = false;
      });
    }, true);
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
    setupDfsFilters();
    setupDfsCards();
    setupDfsAppPicker();
    setupSampleTradeDisclosures();

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
