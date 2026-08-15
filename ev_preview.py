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
    "betonlineag": "BetOnline",
    "kalshi": "Kalshi",
    "polymarket": "Polymarket",
    "fanduel": "FanDuel",
    "draftkings": "DraftKings",
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
    """Return five synthetic, non-actionable opportunities for visual QA only."""

    anchor = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    fixtures = (
        (
            "baseball_mlb", "MLB", "New York Mets vs Philadelphia Phillies",
            "Moneyline", "Philadelphia Phillies", "New York Mets",
            5.62, "novig", 118, 84.0, 420,
        ),
        (
            "basketball_wnba", "WNBA", "Las Vegas Aces vs New York Liberty",
            "Spread", "New York Liberty -3.5", "Las Vegas Aces +3.5",
            4.18, "prophetx", 108, 72.0, 310,
        ),
        (
            "baseball_mlb", "MLB", "Chicago Cubs vs Milwaukee Brewers",
            "Game Total", "Under 8.5", "Over 8.5",
            3.41, "fourcx", 105, 58.0, 205,
        ),
        (
            "tennis_atp", "ATP", "Taylor Fritz vs Ben Shelton", "Moneyline",
            "Taylor Fritz", "Ben Shelton", 2.76, "novig", -158, 46.0, 690,
        ),
        (
            "basketball_wnba", "WNBA", "Seattle Storm vs Phoenix Mercury",
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
            sport, league, event, market, selection, opposing_selection, ev, best_book,
            best_odds, stake, liquidity,
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
        # Preserve the intentionally chosen headline EV while keeping quote audit
        # values internally coherent enough for the existing visual components.
        best["evPercent"] = ev
        rows.append(
            {
                "id": f"positive-ev-preview-{index}",
                "eventId": f"preview-event-{index}",
                "sportKey": sport,
                "league": league,
                "eventTitle": event,
                "commenceTime": (anchor + timedelta(hours=index + 1)).isoformat(),
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
                "sourceBooks": [],
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
