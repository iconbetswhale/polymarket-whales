"""Isolated visual-preview fixtures for the Positive EV product.

These rows are intentionally never sourced from, or written to, production data.
They exist only behind an explicit ``preview=1`` request so the UI can be reviewed
without consuming provider credits or creating trackable recommendations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ev_optimizer import (
    american_to_decimal,
    american_to_probability,
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


def temporary_ev_preview_rows(now: datetime | None = None) -> list[dict]:
    """Return synthetic, non-actionable opportunities for visual QA only."""

    anchor = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    fixtures = (
        (
            "1", "baseball_mlb", "MLB", "New York Mets vs Philadelphia Phillies",
            "Moneyline", "Philadelphia Phillies", "New York Mets",
            5.62, "novig", 118, 84.0, 420,
        ),
        (
            "ohtani-total-bases", "baseball_mlb", "MLB",
            "Los Angeles Dodgers vs Colorado Rockies",
            "Player Total Bases", "Shohei Ohtani Over 1.5 Total Bases",
            "Shohei Ohtani Under 1.5 Total Bases",
            4.72, "fanduel", 115, 63.0, 275,
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
            "wilson-rebounds", "basketball_wnba", "WNBA",
            "Las Vegas Aces vs New York Liberty",
            "Player Rebounds", "A'ja Wilson Over 10.5 Rebounds",
            "A'ja Wilson Under 10.5 Rebounds",
            2.34, "draftkings", -105, 41.0, 240,
        ),
        (
            "5", "basketball_wnba", "WNBA",
            "Seattle Storm vs Phoenix Mercury",
            "Game Total", "Over 162.5", "Under 162.5",
            1.93, "prophetx", 102, 34.0, 180,
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
            opposing_selection, ev, best_book, best_odds, stake, liquidity,
        ) = fixture
        fair = (1.0 + ev / 100.0) / american_to_decimal(best_odds)
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
        sharp_sources = [
            {
                "bookKey": book,
                "bookName": _NAMES[book],
                "logoUrl": _LOGOS[book],
                "americanOdds": best_odds - adjustment,
                "lastUpdated": anchor.isoformat(),
                "quoteAgeSeconds": 3 + position * 2,
                "weight": weight,
                "fairProbability": round(
                    max(0.01, min(0.99, fair + probability_adjustment)), 8
                ),
            }
            for position, (
                book,
                weight,
                adjustment,
                probability_adjustment,
            ) in enumerate(
                (
                    ("pinnacle", 35.0, 9, 0.0010),
                    ("circa", 28.0, 11, -0.0015),
                    ("bookmakereu", 28.0, 10, 0.0005),
                    ("betfairexchange", 7.0, 8, -0.0005),
                    ("fanduel", 2.0, 6, 0.0020),
                )
            )
        ]
        # Preserve the intentionally chosen headline EV while keeping quote audit
        # values internally coherent enough for the existing visual components.
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
                "theoreticalStake": round(stake * 1.32, 2),
                "recommendedStake": stake,
                "kellyFraction": round(stake / 10000.0, 6),
                "fullKellyFraction": round(stake / 2500.0, 6),
                "warnings": ["Preview only — not a live wager or recommendation."],
                "previewOnly": True,
                "calculatedAt": anchor.isoformat(),
                "calculationVersion": "ev-visual-preview-v1",
            }
        )
    return rows
