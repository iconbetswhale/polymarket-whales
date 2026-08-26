"""Isolated visual-preview fixtures for the Positive EV product.

These rows are intentionally never sourced from, or written to, production data.
They exist only behind an explicit ``preview=1`` request so the UI can be reviewed
without consuming provider credits or creating trackable recommendations.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from ev_optimizer import (
    DEVIG_METHODS,
    american_to_decimal,
    american_to_probability,
    devig_probabilities,
    probability_to_american,
)


_LOGOS = {
    "novig": "https://novig.us/favicon.ico",
    "prophetx": "/static/assets/providers/prophetx.ico",
    "fourcx": "/static/assets/providers/4cx.png",
    "pinnacle": "https://www.pinnacle.com/favicon.ico",
    "circa": "https://www.circasports.com/favicon.ico",
    "bookmakereu": "https://www.bookmaker.eu/favicon.ico",
    "betfairexchange": "https://www.betfair.com/favicon.ico",
    "betonlineag": "/static/assets/sportsbooks/betonline.png",
    "kalshi": "/static/assets/providers/kalshi.png",
    "polymarket": "https://polymarket.com/icons/favicon-32x32.png",
    "fanduel": "https://sportsbook.fanduel.com/favicon.ico",
    "draftkings": "https://sportsbook.draftkings.com/favicon.ico",
}

_NAMES = {
    "novig": "NoVIG",
    "prophetx": "ProphetX",
    "fourcx": "4CX",
    "pinnacle": "Pinnacle",
    "circa": "Circa",
    "bookmakereu": "Bookmaker.eu",
    "betfairexchange": "Betfair Exchange",
    "betonlineag": "BetOnline",
    "kalshi": "Kalshi",
    "polymarket": "Polymarket",
    "fanduel": "FanDuel",
    "draftkings": "DraftKings",
}

_MARKET_KEYS = {
    "Moneyline": "h2h",
    "Spread": "spreads",
    "Game Total": "totals",
    "Player Total Bases": "batter_total_bases",
    "Player Rebounds": "player_rebounds",
}


def _quote(book: str, odds: int, fair_probability: float, liquidity: float | None) -> dict:
    decimal = american_to_decimal(odds)
    ev_percent = (fair_probability * decimal - 1.0) * 100.0
    return {
        "bookKey": book,
        "bookName": _NAMES[book],
        "logoUrl": _LOGOS[book],
        "americanOdds": odds,
        "topPriceAmericanOdds": odds,
        "topPrice": round(american_to_probability(odds), 8),
        "topPriceLiquidity": liquidity,
        "marketLimit": None,
        "depthVwapPrice": None,
        "depthExecutableAmount": None,
        "depthLevelsUsed": None,
        "effectiveAmerican": odds,
        "effectiveDecimal": round(decimal, 6),
        "evPercent": round(ev_percent, 2),
        "executionStatus": "executable",
        "quoteAgeSeconds": 2,
        "deepLink": "#",
    }


def temporary_ev_preview_rows(
    now: datetime | None = None,
    *,
    devig_method: str = "power",
    bankroll: float = 10_000.0,
) -> list[dict]:
    """Return synthetic, non-actionable opportunities for visual QA only."""

    devig_method = str(devig_method or "power").strip().lower()
    if devig_method not in DEVIG_METHODS:
        raise ValueError(f"Unsupported de-vig method: {devig_method}.")
    bankroll = min(10_000_000.0, max(1.0, float(bankroll)))
    bankroll_scale = bankroll / 10_000.0
    anchor = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    fixtures = (
        (
            "1", "baseball_mlb", "MLB", "New York Mets vs Philadelphia Phillies",
            "Moneyline", "Philadelphia Phillies", "New York Mets",
            5.62, "novig", 118, 84.0, 420,
        ),
        (
            "2", "basketball_wnba", "WNBA",
            "Las Vegas Aces vs New York Liberty",
            "Spread", "New York Liberty -3.5", "Las Vegas Aces +3.5",
            4.18, "prophetx", 108, 72.0, 310,
        ),
        (
            "3", "baseball_mlb", "MLB", "Chicago Cubs vs Milwaukee Brewers",
            "Game Total", "Under 8.5", "Over 8.5",
            3.41, "fourcx", 105, 58.0, 205,
        ),
        (
            "4", "tennis_atp", "ATP", "Taylor Fritz vs Ben Shelton",
            "Moneyline", "Taylor Fritz", "Ben Shelton",
            2.76, "novig", -158, 46.0, 690,
        ),
        (
            "5", "basketball_wnba", "WNBA",
            "Seattle Storm vs Phoenix Mercury",
            "Game Total", "Over 162.5", "Under 162.5",
            1.93, "prophetx", 102, 34.0, 180,
        ),
        (
            "6", "americanfootball_nfl", "NFL",
            "Buffalo Bills vs Baltimore Ravens",
            "Moneyline", "Buffalo Bills", "Baltimore Ravens",
            1.74, "novig", 115, 31.0, 240,
        ),
        (
            "7", "basketball_wnba", "WNBA",
            "Connecticut Sun vs Indiana Fever",
            "Player Rebounds", "Alyssa Thomas · Over 8.5", "Alyssa Thomas · Under 8.5",
            1.52, "prophetx", 106, 28.0, 155,
        ),
        (
            "8", "baseball_mlb", "MLB",
            "Baltimore Orioles vs Toronto Blue Jays",
            "Player Total Bases", "Vladimir Guerrero Jr. · Over 1.5", "Vladimir Guerrero Jr. · Under 1.5",
            1.31, "fourcx", 120, 26.0, 190,
        ),
        (
            "9", "tennis_atp", "ATP",
            "Jannik Sinner vs Carlos Alcaraz",
            "Moneyline", "Jannik Sinner", "Carlos Alcaraz",
            1.08, "novig", 105, 24.0, 275,
        ),
        (
            "10", "baseball_mlb", "MLB",
            "Los Angeles Dodgers vs San Diego Padres",
            "Game Total", "Under 8.5", "Over 8.5",
            0.92, "prophetx", 102, 22.0, 165,
        ),
    )
    books = (
        "novig", "prophetx", "fourcx", "pinnacle", "betonlineag",
        "kalshi", "polymarket", "fanduel", "draftkings",
    )
    rows: list[dict] = []
    for index, fixture in enumerate(fixtures, start=1):
        (
            preview_key, sport, league, event, market, selection,
            opposing_selection, target_ev, best_book, best_odds, stake, liquidity,
        ) = fixture
        power_fair = (1.0 + target_ev / 100.0) / american_to_decimal(best_odds)
        source_specs = (
            ("pinnacle", 35.0, 0.0010),
            ("circa", 28.0, -0.0015),
            ("bookmakereu", 28.0, 0.0005),
            ("betfairexchange", 7.0, -0.0005),
            ("fanduel", 2.0, 0.0020),
        )
        weighted_adjustment = sum(
            weight * adjustment for _, weight, adjustment in source_specs
        ) / sum(weight for _, weight, _ in source_specs)
        sharp_sources: list[dict] = []
        fair = 0.0
        for position, (book, weight, adjustment) in enumerate(source_specs):
            # Build an internally coherent synthetic two-way market whose Power
            # de-vig result matches the long-standing preview fair price. This
            # keeps the default preview stable while the other methods genuinely
            # recalculate each source from the same raw implied probabilities.
            power_target = max(
                0.01,
                min(0.99, power_fair + adjustment - weighted_adjustment),
            )
            selected_raw = min(0.995, power_target + 0.012 + position * 0.0005)
            power_exponent = math.log(power_target) / math.log(selected_raw)
            opposing_raw = (1.0 - power_target) ** (1.0 / power_exponent)
            source_fair = devig_probabilities(
                [selected_raw, opposing_raw], devig_method
            )[0]
            fair += source_fair * weight / 100.0
            sharp_sources.append(
                {
                    "bookKey": book,
                    "bookName": _NAMES[book],
                    "logoUrl": _LOGOS[book],
                    "americanOdds": probability_to_american(selected_raw),
                    "lastUpdated": anchor.isoformat(),
                    "quoteAgeSeconds": 3 + position * 2,
                    "weight": weight,
                    "fairProbability": round(source_fair, 8),
                }
            )
        decimal_odds = american_to_decimal(best_odds)
        ev = round((fair * decimal_odds - 1.0) * 100.0, 2)
        price_profit = decimal_odds - 1.0
        default_full_kelly = max(
            0.0,
            (power_fair * price_profit - (1.0 - power_fair)) / price_profit,
        )
        method_full_kelly = max(
            0.0,
            (fair * price_profit - (1.0 - fair)) / price_profit,
        )
        base_adjusted_stake = (
            round(stake * method_full_kelly / default_full_kelly, 2)
            if default_full_kelly > 0.0
            else stake
        )
        theoretical_stake = round(base_adjusted_stake * 1.32 * bankroll_scale, 2)
        adjusted_stake = round(
            min(float(liquidity), base_adjusted_stake * bankroll_scale),
            2,
        )
        # Odds in secondary rows are illustrative comparisons, not provider claims.
        quotes = [
            _quote(
                book,
                best_odds if book == best_book else best_odds - 3 - position,
                fair,
                liquidity if book == best_book else None,
            )
            for position, book in enumerate(books)
        ]
        quotes.sort(key=lambda item: item["americanOdds"], reverse=True)
        opposing_base = probability_to_american(
            1.0 - american_to_probability(best_odds)
        )
        opposing_quotes = [
            _quote(
                book,
                opposing_base - 1 - position,
                1.0 - fair,
                round(liquidity * 0.8, 2) if book == best_book else None,
            )
            for position, book in enumerate(books)
        ]
        opposing_quotes.sort(key=lambda item: item["americanOdds"], reverse=True)
        best = next(item for item in quotes if item["bookKey"] == best_book)
        best["evPercent"] = ev
        rows.append(
            {
                "id": f"positive-ev-preview-{preview_key}",
                "eventId": f"preview-event-{preview_key}",
                "sportKey": sport,
                "league": league,
                "eventTitle": event,
                "commenceTime": (anchor + timedelta(hours=index + 1)).isoformat(),
                "marketKey": _MARKET_KEYS[market],
                "marketLabel": market,
                "selection": selection,
                "evPercent": ev,
                "fairProbability": fair,
                "fairAmerican": probability_to_american(fair),
                "fairConfidence": 0.82 - index * 0.025,
                "sourceCount": 5,
                "sourceDispersion": 0.018 + index * 0.002,
                "sourceCoverage": 100.0,
                "sourceCoverageRatio": 1.0,
                "sourceBooks": sharp_sources,
                "bestQuote": best,
                "quotes": quotes,
                "marketSides": [
                    {"selection": selection, "quotes": quotes},
                    {"selection": opposing_selection, "quotes": opposing_quotes},
                ],
                "executionStatus": "executable",
                "portfolioStatus": "qualified",
                "theoreticalStake": theoretical_stake,
                "recommendedStake": adjusted_stake,
                "kellyFraction": round(adjusted_stake / bankroll, 6),
                "fullKellyFraction": round(
                    adjusted_stake / (bankroll * 0.25),
                    6,
                ),
                "warnings": ["Preview only — not a live wager or recommendation."],
                "previewOnly": True,
                "calculatedAt": anchor.isoformat(),
                "calculationVersion": "ev-visual-preview-v2-devig",
                "devigMethod": devig_method,
            }
        )
    return rows
