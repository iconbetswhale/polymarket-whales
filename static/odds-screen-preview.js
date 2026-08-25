(function buildOddsScreenPreview() {
  "use strict";

  const providers = [
    { key: "polymarket", name: "Polymarket", logoUrl: "/static/assets/sportsbooks/polymarket.png", source: "preview" },
    { key: "kalshi", name: "Kalshi", logoUrl: "/static/assets/providers/kalshi.png", source: "preview" },
    { key: "4cx", name: "4CX", logoUrl: "/static/assets/providers/4cx.png", source: "preview" },
    { key: "oddsapi__novig", name: "NoVIG", logoUrl: "/static/assets/providers/novig.png", source: "preview" },
  ];

  const participantLogos = {
    "Atlanta Braves": "https://a.espncdn.com/i/teamlogos/mlb/500/atl.png",
    "Milwaukee Brewers": "https://a.espncdn.com/i/teamlogos/mlb/500/mil.png",
    "St. Louis Cardinals": "https://a.espncdn.com/i/teamlogos/mlb/500/stl.png",
    "Philadelphia Phillies": "https://a.espncdn.com/i/teamlogos/mlb/500/phi.png",
    "Toronto Blue Jays": "https://a.espncdn.com/i/teamlogos/mlb/500/tor.png",
    "New York Yankees": "https://a.espncdn.com/i/teamlogos/mlb/500/nyy.png",
    "Washington Nationals": "https://a.espncdn.com/i/teamlogos/mlb/500/wsh.png",
    "Miami Marlins": "https://a.espncdn.com/i/teamlogos/mlb/500/mia.png",
    "San Francisco Giants": "https://a.espncdn.com/i/teamlogos/mlb/500/sf.png",
    "Boston Red Sox": "https://a.espncdn.com/i/teamlogos/mlb/500/bos.png",
    "Tampa Bay Rays": "https://a.espncdn.com/i/teamlogos/mlb/500/tb.png",
    "Baltimore Orioles": "https://a.espncdn.com/i/teamlogos/mlb/500/bal.png",
    "Los Angeles Dodgers": "https://a.espncdn.com/i/teamlogos/mlb/500/lad.png",
    "Chicago Cubs": "https://a.espncdn.com/i/teamlogos/mlb/500/chc.png",
    "New York Mets": "https://a.espncdn.com/i/teamlogos/mlb/500/nym.png",
    "Seattle Mariners": "https://a.espncdn.com/i/teamlogos/mlb/500/sea.png",
    "Houston Astros": "https://a.espncdn.com/i/teamlogos/mlb/500/hou.png",
    "Texas Rangers": "https://a.espncdn.com/i/teamlogos/mlb/500/tex.png",
    "Cleveland Guardians": "https://a.espncdn.com/i/teamlogos/mlb/500/cle.png",
    "Detroit Tigers": "https://a.espncdn.com/i/teamlogos/mlb/500/det.png",
    "Cincinnati Reds": "https://a.espncdn.com/i/teamlogos/mlb/500/cin.png",
    "Pittsburgh Pirates": "https://a.espncdn.com/i/teamlogos/mlb/500/pit.png",
    "San Diego Padres": "https://a.espncdn.com/i/teamlogos/mlb/500/sd.png",
    "Minnesota Twins": "https://a.espncdn.com/i/teamlogos/mlb/500/min.png",
  };

  const matchups = [
    ["braves-brewers", "Atlanta Braves", "Milwaukee Brewers", [133, -134], 8.5, "Ronald Acuña Jr."],
    ["cardinals-phillies", "St. Louis Cardinals", "Philadelphia Phillies", [233, -239], 8.0, "Bryce Harper"],
    ["blue-jays-yankees", "Toronto Blue Jays", "New York Yankees", [187, -190], 8.5, "Aaron Judge"],
    ["nationals-marlins", "Washington Nationals", "Miami Marlins", [140, -138], 7.5, "James Wood"],
    ["giants-red-sox", "San Francisco Giants", "Boston Red Sox", [163, -166], 9.0, "Rafael Devers"],
    ["rays-orioles", "Tampa Bay Rays", "Baltimore Orioles", [118, -118], 8.0, "Gunnar Henderson"],
    ["dodgers-cubs", "Los Angeles Dodgers", "Chicago Cubs", [-146, 132], 9.5, "Shohei Ohtani"],
    ["mets-mariners", "New York Mets", "Seattle Mariners", [-122, 108], 7.5, "Francisco Lindor"],
    ["astros-rangers", "Houston Astros", "Texas Rangers", [115, -129], 8.5, "Corey Seager"],
    ["guardians-tigers", "Cleveland Guardians", "Detroit Tigers", [104, -116], 7.0, "José Ramírez"],
    ["reds-pirates", "Cincinnati Reds", "Pittsburgh Pirates", [-108, -102], 9.0, "Elly De La Cruz"],
    ["padres-twins", "San Diego Padres", "Minnesota Twins", [-132, 119], 8.0, "Fernando Tatis Jr."],
  ];

  function impliedProbability(americanOdds) {
    const value = americanOdds > 0
      ? 100 / (americanOdds + 100)
      : Math.abs(americanOdds) / (Math.abs(americanOdds) + 100);
    return Math.round(value * 10000) / 10000;
  }

  function displayOdds(americanOdds) {
    return americanOdds > 0 ? `+${americanOdds}` : String(americanOdds);
  }

  function executionOptions(baseOdds, liquidity, seed) {
    const adjustments = [2, 0, -2, 4];
    return providers.map((provider, index) => {
      const americanOdds = baseOdds + adjustments[(index + seed) % adjustments.length];
      const probability = impliedProbability(americanOdds);
      return {
        providerName: provider.name,
        providerKey: provider.key,
        logoUrl: provider.logoUrl,
        displayOdds: displayOdds(americanOdds),
        americanOdds,
        contractPrice: probability,
        bestExecutablePrice: probability,
        availableLiquidity: liquidity + (index * 1300) + (seed * 240),
        deepLink: "",
        isAvailable: true,
        matchingConfidence: "Exact",
        marketStatus: "OPEN",
        quoteFreshness: "fresh",
        quoteAgeSeconds: 8 + index,
        isStale: false,
      };
    });
  }

  function marketRows({
    eventId,
    eventTitle,
    startsAt,
    kind,
    marketTitle,
    outcomes,
    odds,
    liquidity,
    line = null,
    playerName = "",
    seed = 0,
  }) {
    const lineKey = line === null ? "main" : JSON.stringify(line).replaceAll(".", "-");
    const marketId = `${eventId}-${kind}-${lineKey}`;
    const participants = eventTitle.split(" vs ").map(value => value.trim());
    const timestamp = startsAt.toISOString();
    const scheduleDate = timestamp.slice(0, 10);

    return outcomes.map((outcome, index) => {
      const rowLine = Array.isArray(line) ? line[index] : line;
      const logos = {};
      [...participants, ...outcomes].forEach(participant => {
        if (participantLogos[participant]) logos[participant] = participantLogos[participant];
      });
      const row = {
        id: `${marketId}-${index + 1}`,
        event_id: eventId,
        event_title: eventTitle,
        market_id: marketId,
        condition_id: marketId,
        market_title: marketTitle,
        sports_market_type: marketTitle,
        market_line: rowLine,
        outcome,
        event_date_et: timestamp,
        event_start_time: timestamp,
        resolution_time: timestamp,
        schedule_date_et: scheduleDate,
        category: "Baseball",
        canonical_sport_id: "BASEBALL",
        league: "MLB",
        canonical_league_id: "MLB",
        is_sports: true,
        previewOnly: true,
        participant_logos: logos,
        card: { recommended_amount: 0 },
        recommendation: { recommended_amount: 0 },
        executionOptions: executionOptions(odds[index], liquidity + (index * 1700), seed + index),
      };
      if (playerName) row.player_name = playerName;
      return row;
    });
  }

  const base = new Date();
  base.setUTCSeconds(0, 0);
  const rows = [];

  matchups.forEach(([slug, away, home, moneylineOdds, totalLine, playerName], eventIndex) => {
    const eventId = `preview-${slug}`;
    const eventTitle = `${away} vs ${home}`;
    const startsAt = new Date(base.getTime() + ((2 + eventIndex) * 60 * 60 * 1000) + ((eventIndex % 3) * 10 * 60 * 1000));
    const common = { eventId, eventTitle, startsAt };
    const spreadLine = moneylineOdds[0] > 0 ? [1.5, -1.5] : [-1.5, 1.5];
    const alternateSpreadLine = spreadLine[0] > 0 ? [2.5, -2.5] : [-2.5, 2.5];

    rows.push(
      ...marketRows({ ...common, kind: "moneyline", marketTitle: "Moneyline", outcomes: [away, home], odds: moneylineOdds, liquidity: 12600 + (eventIndex * 2200), seed: eventIndex }),
      ...marketRows({ ...common, kind: "spread", marketTitle: "Run Line / Spread", outcomes: [away, home], odds: [-108 - (eventIndex % 3), -112 + (eventIndex % 3)], liquidity: 9800 + (eventIndex * 1800), line: spreadLine, seed: eventIndex + 2 }),
      ...marketRows({ ...common, kind: "alternate-spread", marketTitle: "Alternate Spread", outcomes: [away, home], odds: [-104 - (eventIndex % 4), -116 + (eventIndex % 4)], liquidity: 9100 + (eventIndex * 1500), line: alternateSpreadLine, seed: eventIndex + 3 }),
      ...marketRows({ ...common, kind: "game-total", marketTitle: "Game Total", outcomes: ["Over", "Under"], odds: [-105 - (eventIndex % 4), -115 + (eventIndex % 4)], liquidity: 8400 + (eventIndex * 1400), line: totalLine, seed: eventIndex + 4 }),
      ...marketRows({ ...common, kind: "alternate-total", marketTitle: "Alternate Total", outcomes: ["Over", "Under"], odds: [-102 - (eventIndex % 5), -118 + (eventIndex % 5)], liquidity: 7600 + (eventIndex * 1200), line: totalLine + 1, seed: eventIndex + 5 }),
      ...marketRows({ ...common, kind: "player-hits", marketTitle: "Player Hits", outcomes: ["Over", "Under"], odds: [104 + (eventIndex % 5), -124 + (eventIndex % 5)], liquidity: 6800 + (eventIndex * 1000), line: 1.5, playerName, seed: eventIndex + 6 }),
    );
  });

  window.ICONLABS_ODDS_SCREEN_PREVIEW_DATA = {
    data: rows,
    providers,
    filters: { sport: "", league: "", market: "" },
    paused: false,
    previewOnly: true,
    fabricatedData: true,
    trackerWritesEnabled: false,
    providerRequestsEnabled: false,
    message: "Temporary visual fixtures only.",
  };
})();
