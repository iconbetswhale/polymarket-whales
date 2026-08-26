(() => {
  "use strict";

  const now = Date.now();
  const iso = (offsetHours) => new Date(now + offsetHours * 60 * 60 * 1000).toISOString();
  const eventTimeLabel = (timestamp) => new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(timestamp));
  const providerCatalog = [
    ["novig", "NoVIG", "/static/assets/sportsbooks/novig.png", "https://novig.com/"],
    ["4cx", "4CX", "/static/assets/providers/4cx.png", "https://4cx.com/"],
    ["kalshi", "Kalshi", "/static/assets/sportsbooks/kalshi.png", "https://kalshi.com/"],
    ["prophetx", "ProphetX", "/static/assets/sportsbooks/prophetx.png", "https://prophetx.com/"],
    ["polymarket", "Polymarket", "/static/assets/sportsbooks/polymarket.png", "https://polymarket.com/"],
  ];

  const tradeSpecs = [
    {
      score: 64, sharps: 2, category: "Basketball", league: "WNBA",
      event: "New York Liberty vs Las Vegas Aces", market: "Game Total",
      marketType: "game_total", selection: "Over 167.5", current: 0.455,
      sharp: 0.46, stake: 25, hit: 0.6268, sample: 620, volume: 3400,
    },
    {
      score: 58, sharps: 3, category: "Baseball", league: "MLB",
      event: "Cincinnati Reds vs St. Louis Cardinals", market: "Moneyline",
      marketType: "moneyline", selection: "Cincinnati Reds ML", current: 0.429,
      sharp: 0.419, stake: 20, hit: 0.5908, sample: 1010, volume: 4100,
    },
    {
      score: 56, sharps: 3, category: "Baseball", league: "MLB",
      event: "New York Yankees vs Boston Red Sox", market: "Moneyline",
      marketType: "moneyline", selection: "Yankees ML", current: 0.507,
      sharp: 0.489, stake: 15, hit: 0.6028, sample: 880, volume: 3700,
    },
    {
      score: 55, sharps: 2, category: "Soccer", league: "FIFA World Cup",
      event: "Spain vs France", market: "To Advance", marketType: "to_advance",
      selection: "Spain", current: 0.40, sharp: 0.389, stake: 10,
      hit: 0.6148, sample: 750, volume: 2950,
    },
    {
      score: 53, sharps: 2, category: "Hockey", league: "NHL",
      event: "New York Rangers vs Boston Bruins", market: "Moneyline",
      marketType: "moneyline", selection: "Rangers ML", current: 0.525,
      sharp: 0.51, stake: 10, hit: 0.6388, sample: 490, volume: 2600,
    },
    {
      score: 72, sharps: 3, category: "Basketball", league: "NBA",
      event: "Boston Celtics vs New York Knicks", market: "Spread -4.5",
      marketType: "spread", selection: "Boston Celtics -4.5", line: -4.5,
      current: 0.49, sharp: 0.475, stake: 30, hit: 0.618, sample: 845, volume: 5200,
    },
    {
      score: 69, sharps: 2, category: "Football", league: "NFL",
      event: "Buffalo Bills vs Miami Dolphins", market: "Spread +2.5",
      marketType: "spread", selection: "Buffalo Bills +2.5", line: 2.5,
      current: 0.515, sharp: 0.502, stake: 25, hit: 0.607, sample: 690, volume: 4650,
    },
    {
      score: 66, sharps: 3, category: "Baseball", league: "MLB",
      event: "Los Angeles Dodgers vs San Diego Padres", market: "Run Line -1.5",
      marketType: "spread", selection: "Los Angeles Dodgers -1.5", line: -1.5,
      current: 0.445, sharp: 0.432, stake: 20, hit: 0.596, sample: 925, volume: 4450,
    },
    {
      score: 61, sharps: 2, category: "Tennis", league: "ATP",
      event: "Taylor Fritz vs Ben Shelton", market: "Player Aces",
      marketType: "player_prop", selection: "Taylor Fritz Over 12.5 Aces",
      current: 0.47, sharp: 0.458, stake: 15, hit: 0.612, sample: 410, volume: 2850,
    },
    {
      score: 59, sharps: 2, category: "Soccer", league: "Premier League",
      event: "Arsenal vs Liverpool", market: "Both Teams To Score",
      marketType: "yes_no", selection: "Yes", current: 0.565,
      sharp: 0.552, stake: 15, hit: 0.584, sample: 780, volume: 3150,
    },
  ];

  const americanOdds = (probability) => {
    if (!(probability > 0 && probability < 1)) return null;
    return Math.round(probability >= 0.5
      ? (-100 * probability) / (1 - probability)
      : (100 * (1 - probability)) / probability);
  };

  const executionOptions = (tradeIndex, spec) => {
    const offsets = tradeIndex % 2 === 0
      ? [0, 0.008, 0.012, 0.016, 0.02]
      : [0.007, 0, 0.011, 0.015, 0.019];
    return providerCatalog.map(([providerKey, providerName, logoUrl, deepLink], index) => {
      const price = Math.min(0.95, Math.max(0.05, spec.current + offsets[index]));
      const nativeContract = ["kalshi", "polymarket"].includes(providerKey);
      return {
        providerKey,
        providerName,
        logoUrl,
        deepLink,
        directMarketUrl: deepLink,
        marketId: `preview-${providerKey}-${tradeIndex + 1}`,
        selectionId: `preview-${providerKey}-selection-${tradeIndex + 1}`,
        americanOdds: nativeContract ? null : americanOdds(price),
        contractPrice: price,
        bestExecutablePrice: price,
        displayOdds: nativeContract ? `${(price * 100).toFixed(1)}¢` : String(americanOdds(price)),
        estimatedFees: providerKey === "kalshi" ? 0.42 : 0,
        feeRate: 0,
        recommendedStake: spec.stake,
        availableLiquidity: 3800 - index * 425 + tradeIndex * 180,
        isAvailable: true,
        isExactMatch: true,
        isStale: false,
        marketStatus: "OPEN",
        matchingConfidence: "Exact",
        canFillRecommendedStake: true,
        quoteAgeSeconds: 4 + index * 5,
        quoteTimestamp: iso(-(4 + index * 5) / 3600),
        lastUpdated: iso(-(4 + index * 5) / 3600),
        tooltip: `${providerName} visual preview quote`,
      };
    });
  };

  const makeTrade = (spec, index) => {
    const start = iso(1.25 + index * 0.75);
    const slippage = (spec.current - spec.sharp) / spec.sharp;
    const shares = spec.stake / spec.current;
    const supporters = Array.from({ length: spec.sharps }, (_, sharpIndex) => ({
      wallet_address: `0xpreview${index + 1}${sharpIndex + 1}`,
      wallet_label: ["Bagwell306", "FerrariChampions2026", "Weflyhigh"][sharpIndex],
      wallet_profile_url: "https://polymarket.com/",
      amount: spec.volume - sharpIndex * 525,
      relative_units: 1.4 + sharpIndex * 0.4,
      is_lead_sharp: sharpIndex === 0,
      category_weight: sharpIndex === 0 ? 1 : 0.5,
      top_category_ids: [spec.category],
    }));
    const recommendation = {
      available: true,
      bankroll: 10000,
      baseline_probability: spec.current,
      current_top_ask_price: spec.current,
      current_user_entry_price: spec.current,
      effective_entry_price: spec.current,
      sharp_average_entry_price: spec.sharp,
      sharp_reference_entry_price: spec.sharp,
      price_slippage_fraction: slippage,
      unfavorable_slippage_pct: Math.max(slippage, 0),
      passes_slippage_rule: true,
      estimated_win_probability: Math.min(spec.current + 0.08, 0.92),
      calculated_edge: 0.08 - index * 0.006,
      evidence_score: 0.78 - index * 0.02,
      evidence_adjustment: 0.08,
      full_kelly_fraction: 0.008,
      half_kelly_fraction: 0.004,
      sharp_risk_cap: 0.01,
      final_recommended_fraction: spec.stake / 10000,
      recommended_amount: spec.stake,
      recommended_shares: shares,
      recommended_units: spec.stake / 100,
      slippage_cents: (spec.current - spec.sharp) * 100,
      execution_plan: {
        recommended_execution_method: "Best available exact market",
        execution_reason_code: "LOWEST_ALL_IN_PRICE",
        maximum_average_price: Math.min(spec.current + 0.025, 0.99),
        effective_price_for_executable_amount: spec.current,
        amount_executable_below_max: spec.stake,
        unfilled_amount: 0,
        quote_fresh: true,
        quote_age_seconds: 4,
        execution_explanation: "Preview data demonstrates the verified execution hierarchy without placing a wager.",
      },
    };
    const orderbook = {
      asks: [0, 0.004, 0.008, 0.013].map((offset, level) => ({
        price: (spec.current + offset).toFixed(3), size: String(1450 + level * 850),
      })),
      bids: [0.003, 0.007, 0.011, 0.016].map((offset, level) => ({
        price: (spec.current - offset).toFixed(3), size: String(1700 + level * 725),
      })),
      timestamp: iso(0), tick_size: "0.001", min_order_size: "5",
    };
    return {
      id: `preview-trade-${index + 1}`,
      canonical_market_key: `preview-market-${index + 1}`,
      canonical_category_id: spec.category.toLowerCase(),
      condition_id: `preview-condition-${index + 1}`,
      event_slug: `preview-event-${index + 1}`,
      event_title: spec.event,
      market_title: spec.market,
      outcome: spec.selection,
      category: spec.category,
      league: spec.league,
      sports_market_type: spec.marketType,
      market_line: spec.line ?? null,
      event_date_et: start,
      event_time_et: eventTimeLabel(start),
      resolution_time: iso(4.25 + index * 0.75),
      market_url: "https://polymarket.com/",
      clob_token_id: `preview-token-${index + 1}`,
      market_open: true,
      lifecycle_status: "open",
      average_entry_price: spec.sharp,
      sharp_reference_entry_price: spec.sharp,
      confidence_score: spec.score,
      score_breakdown: { consensus_band: "Verified Sharp agreement", category_composition: 0.75 },
      raw_sharp_count: spec.sharps,
      agreeing_wallet_count: spec.sharps,
      lead_sharp_count: 1,
      supporting_sharp_count: Math.max(spec.sharps - 1, 0),
      weighted_sharp_count: 1 + Math.max(spec.sharps - 1, 0) * 0.5,
      has_lead_sharp: true,
      weighted_amount_signal: 0.83,
      weighted_relative_size_signal: 0.77,
      combined_exposure_exact: supporters.reduce((total, item) => total + item.amount, 0),
      evidence_inputs: { adjusted_category_hit_rate: spec.hit },
      primary_trader: {
        ...supporters[0], top_category: spec.category, sample_size: spec.sample,
        adjusted_hit_rate: spec.hit,
      },
      supporting_wallets: supporters,
      search_blob: `${spec.category} ${spec.league} ${spec.event} ${spec.selection} ${spec.market}`.toLowerCase(),
      recommendation,
      card: {
        category_hit_rate: spec.hit,
        current_actionable_price: spec.current,
        event_time: start,
        recommended_amount: spec.stake,
        recommended_shares: shares,
        recommended_units: spec.stake / 100,
        relative_bet_size: 1.4,
        slippage_fraction: slippage,
        trader_average_entry_price: spec.sharp,
        trader_bet_amount: spec.volume,
      },
      executionOptions: executionOptions(index, spec),
      orderbook,
      orderbook_summary: {
        ask_levels: 4, bid_levels: 4,
        best_ask: spec.current.toFixed(3),
        best_bid: (spec.current - 0.003).toFixed(3),
        timestamp: iso(0),
      },
      tradeFeedEligible: true,
      modelTrackerEligible: true,
      passesSlippageRule: true,
      unfavorableSlippagePct: Math.max(slippage, 0) * 100,
      isHidden: false,
      isPinnedByCurrentUser: false,
      personalExposureSummary: {
        type: "none", title: null, message: null, personalEntryCount: 0,
        aggregate: { entryCount: 0, totalShares: 0, totalPositionCost: 0, totalFees: 0 },
      },
    };
  };

  const lineHistory = (latest, variation = 0) => Array.from({ length: 25 }, (_, index) => {
    const progress = index / 24;
    const wave = Math.sin(progress * Math.PI * 3) * 0.002;
    const startOffset = [0.019, -0.015, 0.012, -0.018, 0.016][variation % 5];
    const value = index === 24 ? latest : latest + startOffset * (1 - progress) + wave;
    return { t: now - (24 - index) * 15 * 60 * 1000, p: Math.min(0.98, Math.max(0.02, value)).toFixed(4) };
  });

  const openPositionSpecs = [
    ["open-1", "Polymarket", "Philadelphia Phillies vs New York Mets", "Moneyline", "Philadelphia Phillies", 0.46, 0.54, 120],
    ["open-2", "NoVIG", "New York Liberty vs Las Vegas Aces", "Spread -3.5", "New York Liberty -3.5", 0.52, 0.57, 85],
    ["open-3", "4CX", "Chicago Cubs vs Milwaukee Brewers", "Game Total 8.5", "Under 8.5 Runs", 0.44, 0.405, 140],
    ["open-4", "ProphetX", "Taylor Fritz vs Ben Shelton", "Moneyline", "Taylor Fritz", 0.61, 0.66, 70],
    ["open-5", "Kalshi", "Seattle Storm vs Phoenix Mercury", "Game Total 162.5", "Over 162.5", 0.48, 0.515, 100],
  ];

  const makeOpenPosition = ([id, provider, eventTitle, marketTitle, selection, entry, exit, shares], index) => {
    const grossPurchaseCost = entry * shares;
    const buyFees = 0.75 + index * 0.1;
    const totalPaid = grossPurchaseCost + buyFees;
    const currentMarketValue = exit * shares;
    const unrealizedPnl = currentMarketValue - totalPaid;
    return {
      positionId: `preview-position-${id}`,
      canonicalEventId: `preview-${id}-event`, canonicalMarketId: `preview-${id}-market`,
      marketLine: marketTitle, canonicalOutcomeId: `preview-${id}-outcome`,
      provider, eventTitle, marketTitle, selection, eventStartTime: iso(3 + index),
      marketUrl: "https://polymarket.com/", totalPurchasedShares: shares,
      soldShares: 0, remainingShares: shares, grossPurchaseCost, buyFees, totalPaid,
      remainingCostBasis: totalPaid, averageBuyEntry: entry, averageSellEntry: null,
      grossSaleProceeds: 0, sellFees: 0, netSaleProceeds: 0, settlementProceeds: 0,
      settlementPrice: null, refunds: 0, realizedPnl: 0, unrealizedPnl,
      totalPnl: unrealizedPnl, returnPct: unrealizedPnl / totalPaid, currentMarketValue,
      quote: {
        bestBid: exit + 0.003, effectiveSellPrice: exit, executableShares: shares,
        estimatedGrossProceeds: currentMarketValue, estimatedSellFee: 0,
        estimatedNetProceeds: currentMarketValue, unfilledShares: 0,
        quoteTimestamp: iso(0), expectedSlippagePct: 0.004, quoteFreshness: "live",
      },
      status: "unresolved", isClosed: false, closureMethod: null,
      closureTimestamp: null, result: null, fills: [], exits: [], executionMode: "tracker_only",
    };
  };

  const closedPositionSpecs = [
    ["closed-1", "Polymarket", "Los Angeles Dodgers vs San Diego Padres", "Moneyline", "Los Angeles Dodgers", 0.48, 0.68, 110, "sold"],
    ["closed-2", "NoVIG", "Boston Celtics vs New York Knicks", "Spread -4.5", "Boston Celtics -4.5", 0.53, 1, 90, "resolved"],
    ["closed-3", "4CX", "Arsenal vs Liverpool", "Game Total 2.5", "Over 2.5 Goals", 0.57, 0, 75, "resolved"],
    ["closed-4", "ProphetX", "Buffalo Bills vs Miami Dolphins", "Moneyline", "Buffalo Bills", 0.41, 0.55, 130, "sold"],
    ["closed-5", "Kalshi", "New York Rangers vs Boston Bruins", "Game Total 5.5", "Under 5.5", 0.49, 1, 80, "resolved"],
  ];

  const makeClosedPosition = ([id, provider, eventTitle, marketTitle, selection, entry, exit, shares, closureMethod], index) => {
    const grossPurchaseCost = entry * shares;
    const buyFees = 0.8;
    const totalPaid = grossPurchaseCost + buyFees;
    const grossSaleProceeds = exit * shares;
    const sellFees = closureMethod === "sold" ? 0.65 : 0;
    const netSaleProceeds = closureMethod === "sold" ? grossSaleProceeds - sellFees : 0;
    const settlementProceeds = closureMethod === "resolved" ? grossSaleProceeds : 0;
    const realizedPnl = netSaleProceeds + settlementProceeds - totalPaid;
    return {
      positionId: `preview-position-${id}`,
      canonicalEventId: `preview-${id}-event`, canonicalMarketId: `preview-${id}-market`,
      marketLine: marketTitle, canonicalOutcomeId: `preview-${id}-outcome`, provider,
      eventTitle, marketTitle, selection, eventStartTime: iso(-24 * (index + 1)),
      marketUrl: "https://polymarket.com/", totalPurchasedShares: shares,
      soldShares: closureMethod === "sold" ? shares : 0, remainingShares: 0,
      grossPurchaseCost, buyFees, totalPaid, remainingCostBasis: 0,
      averageBuyEntry: entry, averageSellEntry: closureMethod === "sold" ? exit : null,
      grossSaleProceeds: closureMethod === "sold" ? grossSaleProceeds : 0,
      sellFees, netSaleProceeds, settlementProceeds,
      settlementPrice: closureMethod === "resolved" ? exit : null,
      refunds: 0, realizedPnl, unrealizedPnl: null, totalPnl: realizedPnl,
      returnPct: realizedPnl / totalPaid, currentMarketValue: null, quote: {},
      status: "closed", isClosed: true, closureMethod,
      closureTimestamp: iso(-24 * index - 2), result: exit === 1 ? "Won" : exit === 0 ? "Lost" : "Sold",
      fills: [], exits: [], executionMode: "tracker_only",
    };
  };

  const trades = tradeSpecs.map(makeTrade);
  const openPositions = openPositionSpecs.map(makeOpenPosition);
  const closedPositions = closedPositionSpecs.map(makeClosedPosition);
  const priceHistory = Object.fromEntries([
    ...trades.map((trade, index) => [trade.clob_token_id, lineHistory(trade.card.current_actionable_price, index)]),
    ...openPositions.map((position, index) => [position.positionId, lineHistory(position.quote.effectiveSellPrice, index)]),
    ...closedPositions.map((position, index) => [position.positionId, lineHistory(position.averageSellEntry ?? position.settlementPrice ?? position.averageBuyEntry, index)]),
  ]);

  window.ICONLABS_TRADES_PREVIEW_DATA = Object.freeze({
    trades: {
      data: trades,
      officialTracked: [], liveRejectedTradeIds: [], hiddenCount: 0, whiteboardCount: 0,
      showHidden: false, fastMode: false, previewOnly: true,
      pagination: { page: 1, per_page: 100, total: trades.length, has_next: false, has_prev: false },
      status: {
        api_status: "ok", state: "ok", enabled_wallet_count: 9, position_count: 714,
        last_successful_refresh: new Date(now).toISOString(),
      },
      bankroll: {
        starting_bankroll: 10000, trades_to_play_bankroll: 10000,
        unit_percentage: 0.01, sizing_bankroll_configured: false,
        account_authenticated: false, settings_version: 1,
      },
    },
    openPositions,
    closedPositions,
    priceHistory,
    personalPnl: {
      period: "week", timezone: "America/New_York", realizedPnl: 126.3,
      todayPnl: 34.5, yesterdayPnl: -18.25,
      graph: [-12, 9, 31, 18, 62, 91, 126.3].map((profitLoss, index) => ({
        timestamp: new Date(now - (6 - index) * 24 * 60 * 60 * 1000).toISOString().slice(0, 10),
        profitLoss,
      })),
    },
  });
})();
