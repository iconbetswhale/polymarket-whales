from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Iterable

from the_odds_api_provider import KNOWN_SPORTSBOOKS as THE_ODDS_API_BOOKS
from sports_game_odds import (
    SPORTS_GAME_ODDS_DEFAULT_EXECUTION_BOOKS,
    SPORTS_GAME_ODDS_DEFAULT_SOURCE_WEIGHTS,
    SPORTS_GAME_ODDS_EXCHANGE_BOOKS,
    SPORTS_GAME_ODDS_LOGOS,
)


DEFAULT_SOURCE_WEIGHTS = dict(SPORTS_GAME_ODDS_DEFAULT_SOURCE_WEIGHTS)

DEVIG_METHODS = ("power", "additive", "multiplicative", "shin")

DEFAULT_EXECUTION_BOOKS = SPORTS_GAME_ODDS_DEFAULT_EXECUTION_BOOKS

MAIN_MARKETS = ("h2h", "spreads", "totals")
ALTERNATE_MARKETS = ("alternate_spreads", "alternate_totals")
PLAYER_PROP_MARKETS = {
    "baseball_mlb": (
        "batter_hits",
        "batter_total_bases",
        "batter_home_runs",
        "batter_first_home_run",
        "batter_rbis",
        "batter_runs_scored",
        "batter_hits_runs_rbis",
        "batter_runs_rbis",
        "batter_singles",
        "batter_doubles",
        "batter_triples",
        "batter_walks",
        "batter_strikeouts",
        "batter_stolen_bases",
        "pitcher_strikeouts",
        "pitcher_hits_allowed",
        "pitcher_walks",
        "pitcher_earned_runs",
        "pitcher_outs",
        "pitcher_pitches_thrown",
        "pitcher_record_a_win",
    ),
    "basketball_wnba": (
        "player_points",
        "player_points_q1",
        "player_rebounds",
        "player_rebounds_q1",
        "player_assists",
        "player_assists_q1",
        "player_threes",
        "player_blocks",
        "player_steals",
        "player_blocks_steals",
        "player_turnovers",
        "player_points_rebounds_assists",
        "player_points_rebounds",
        "player_points_assists",
        "player_rebounds_assists",
        "player_field_goals",
        "player_field_goals_attempted",
        "player_frees_made",
        "player_frees_attempts",
        "player_first_basket",
        "player_double_double",
        "player_triple_double",
    ),
}
PLAYER_PROP_MARKETS["basketball_nba"] = PLAYER_PROP_MARKETS["basketball_wnba"]

EXCHANGE_BOOKS = set(SPORTS_GAME_ODDS_EXCHANGE_BOOKS)
DEFAULT_EXECUTION_PRIORITY = {
    book_key: index for index, book_key in enumerate(DEFAULT_EXECUTION_BOOKS)
}
DEFAULT_FEE_BPS = {book: 0.0 for book in DEFAULT_EXECUTION_BOOKS}
MIN_AMERICAN_ODDS = -5000
MAX_AMERICAN_ODDS = 5000


def american_to_probability(odds: int | float) -> float:
    value = float(odds)
    if value > 0:
        return 100.0 / (value + 100.0)
    if value < 0:
        return -value / (-value + 100.0)
    return 0.5


def american_to_decimal(odds: int | float) -> float:
    value = float(odds)
    return 1.0 + (value / 100.0 if value > 0 else 100.0 / -value)


def probability_to_american(probability: float) -> int:
    value = min(0.9999, max(0.0001, float(probability)))
    if value >= 0.5:
        return int(round(-100.0 * value / (1.0 - value)))
    return int(round(100.0 * (1.0 - value) / value))


def devig_probabilities(
    probabilities: list[float], method: str = "power"
) -> list[float]:
    """Remove market margin with one of the supported de-vig methods."""
    if not probabilities:
        return []
    values = [float(value) for value in probabilities]
    if any(
        not math.isfinite(value) or value <= 0.0 or value >= 1.0
        for value in values
    ):
        raise ValueError("De-vig probabilities must be finite values between 0 and 1.")
    total = sum(values)
    if total <= 0:
        return []
    method = str(method or "power").strip().lower()
    if method not in DEVIG_METHODS:
        raise ValueError(
            f"Unsupported de-vig method: {method}. "
            f"Choose one of {', '.join(DEVIG_METHODS)}."
        )
    if method == "additive":
        excess = (total - 1.0) / len(values)
        adjusted = [max(0.0001, value - excess) for value in values]
    elif method == "power":
        low, high = 0.000001, 100.0
        for _ in range(80):
            midpoint = (low + high) / 2.0
            powered = sum(value**midpoint for value in values)
            if powered > 1.0:
                low = midpoint
            else:
                high = midpoint
        adjusted = [value ** ((low + high) / 2.0) for value in values]
    elif method == "shin":
        # Shin and Additive have an exact closed-form equivalence for
        # two-outcome markets. Using it also avoids an unnecessary iterative
        # solve for the most common sportsbook market shape.
        if len(values) == 2:
            excess = (total - 1.0) / 2.0
            adjusted = [max(0.0001, value - excess) for value in values]
        elif total <= 1.0:
            # A non-positive overround has no valid insider-trading parameter
            # in Shin's standard z in [0, 1) model. Normalize it safely rather
            # than inventing a negative insider share.
            adjusted = list(values)
        else:
            def shin_probabilities(z_value: float) -> list[float]:
                denominator = 2.0 * (1.0 - z_value)
                return [
                    (
                        math.sqrt(
                            z_value * z_value
                            + 4.0
                            * (1.0 - z_value)
                            * value
                            * value
                            / total
                        )
                        - z_value
                    )
                    / denominator
                    for value in values
                ]

            low, high = 0.0, 1.0 - 1e-12
            for _ in range(80):
                midpoint = (low + high) / 2.0
                if sum(shin_probabilities(midpoint)) > 1.0:
                    low = midpoint
                else:
                    high = midpoint
            adjusted = shin_probabilities((low + high) / 2.0)
    else:
        # Multiplicative de-vig: scale every raw implied probability by the
        # same factor so the resulting market sums to 100%.
        adjusted = list(values)
    normalized = sum(adjusted)
    return [value / normalized for value in adjusted]


def _devig(probabilities: list[float], method: str) -> list[float]:
    """Backward-compatible internal alias for the public calculation helper."""
    return devig_probabilities(probabilities, method)


def _group_key(market_key: str, outcome: dict) -> tuple:
    description = str(outcome.get("description") or "").strip()
    point = outcome.get("point")
    if market_key in {"spreads", "alternate_spreads"}:
        try:
            line = abs(float(point))
        except (TypeError, ValueError):
            line = None
        return (market_key, line)
    if market_key in {"totals", "alternate_totals"}:
        return (market_key, point)
    if description:
        return (market_key, description.casefold(), point)
    return (market_key,)


def _selection_key(outcome: dict) -> tuple:
    return (
        str(outcome.get("name") or "").strip().casefold(),
        str(outcome.get("description") or "").strip().casefold(),
        outcome.get("point"),
    )


def _market_label(market_key: str) -> str:
    labels = {
        "h2h": "Moneyline",
        "spreads": "Spread",
        "totals": "Game Total",
        "alternate_spreads": "Alt Spread",
        "alternate_totals": "Alt Total",
        "batter_hits": "Hits",
        "batter_total_bases": "Total Bases",
        "batter_home_runs": "Home Runs",
        "batter_first_home_run": "First Home Run",
        "batter_rbis": "RBIs",
        "batter_runs_scored": "Runs",
        "batter_hits_runs_rbis": "Hits + Runs + RBIs",
        "batter_runs_rbis": "Runs + RBIs",
        "batter_singles": "Singles",
        "batter_doubles": "Doubles",
        "batter_triples": "Triples",
        "batter_walks": "Batter Walks",
        "batter_strikeouts": "Batter Strikeouts",
        "batter_stolen_bases": "Stolen Bases",
        "pitcher_strikeouts": "Pitcher Strikeouts",
        "pitcher_hits_allowed": "Hits Allowed",
        "pitcher_walks": "Pitcher Walks",
        "pitcher_earned_runs": "Earned Runs",
        "pitcher_outs": "Pitcher Outs",
        "pitcher_pitches_thrown": "Pitches Thrown",
        "pitcher_record_a_win": "Pitcher Win",
        "player_points": "Points",
        "player_points_q1": "1Q Points",
        "player_rebounds": "Rebounds",
        "player_rebounds_q1": "1Q Rebounds",
        "player_assists": "Assists",
        "player_assists_q1": "1Q Assists",
        "player_threes": "3-Pointers",
        "player_blocks": "Blocks",
        "player_steals": "Steals",
        "player_blocks_steals": "Blocks + Steals",
        "player_turnovers": "Turnovers",
        "player_points_rebounds_assists": "Pts + Reb + Ast",
        "player_points_rebounds": "Points + Rebounds",
        "player_points_assists": "Points + Assists",
        "player_rebounds_assists": "Rebounds + Assists",
        "player_field_goals": "Field Goals Made",
        "player_field_goals_attempted": "Field Goals Attempted",
        "player_frees_made": "Free Throws Made",
        "player_frees_attempts": "Free Throws Attempted",
        "player_first_basket": "First Basket",
        "player_double_double": "Double-Double",
        "player_triple_double": "Triple-Double",
    }
    return labels.get(market_key, market_key.replace("_", " ").title())


def _book_logo(book_key: str, book: dict) -> str:
    if book_key in SPORTS_GAME_ODDS_LOGOS:
        return SPORTS_GAME_ODDS_LOGOS[book_key]
    known = THE_ODDS_API_BOOKS.get(book_key)
    if known and known[1]:
        return known[1]
    return str(book.get("logo") or book.get("logo_url") or "")


def _parse_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _quote_age_seconds(value: object, now: datetime) -> float | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _valid_american(value: object) -> bool:
    try:
        odds = float(value)
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(odds)
        and odds != 0
        and MIN_AMERICAN_ODDS <= odds <= MAX_AMERICAN_ODDS
    )


def _weighted_median(rows: list[tuple[float, float, str]]) -> float:
    ordered = sorted(rows, key=lambda row: row[0])
    halfway = sum(row[1] for row in ordered) / 2.0
    cumulative = 0.0
    for value, weight, _book in ordered:
        cumulative += weight
        if cumulative >= halfway:
            return value
    return ordered[-1][0]


def _fair_consensus(
    rows: list[tuple[float, float, str]],
    *,
    min_source_books: int,
    max_source_dispersion: float,
    configured_weight: float,
) -> dict | None:
    unique = {book for _probability, _weight, book in rows}
    if len(unique) < min_source_books:
        return None
    center = _weighted_median(rows)
    clipped = [
        row for row in rows if abs(row[0] - center) <= max_source_dispersion
    ]
    if len({row[2] for row in clipped}) < min_source_books:
        return None
    total_weight = sum(row[1] for row in clipped)
    if total_weight <= 0:
        return None
    weighted_mean = sum(row[0] * row[1] for row in clipped) / total_weight
    # Blend the efficient weighted mean with the outlier-resistant center.
    fair_probability = (weighted_mean * 0.7) + (center * 0.3)
    values = [row[0] for row in clipped]
    dispersion = max(values) - min(values) if len(values) > 1 else 0.0
    coverage_ratio = min(1.0, total_weight / max(1.0, configured_weight))
    confidence = min(1.0, len(values) / 5.0)
    confidence *= max(0.0, 1.0 - dispersion / max_source_dispersion)
    confidence *= min(1.0, coverage_ratio / 0.6)
    return {
        "fairProbability": fair_probability,
        "sourceRows": clipped,
        "sourceCount": len(values),
        "sourceDispersion": dispersion,
        "sourceCoverage": total_weight,
        "sourceCoverageRatio": coverage_ratio,
        "fairConfidence": confidence,
    }


def _effective_decimal(american_odds: float, fee_bps: float) -> float:
    decimal = american_to_decimal(american_odds)
    fee_rate = min(0.25, max(0.0, float(fee_bps)) / 10000.0)
    return 1.0 + ((decimal - 1.0) * (1.0 - fee_rate))


def _selection_label(market_key: str, outcome: dict) -> str:
    name = str(outcome.get("name") or "")
    description = str(outcome.get("description") or "")
    point = outcome.get("point")
    label = description or name
    if name.casefold() in {"over", "under"}:
        return f"{description + ' ' if description else ''}{name} {point}".strip()
    if name.casefold() in {"yes", "no"} and description:
        return f"{description} — {name}"
    if point is not None and market_key != "h2h":
        try:
            return f"{name} {float(point):+g}"
        except (TypeError, ValueError):
            return f"{name} {point}"
    return label


def _apply_portfolio_limits(
    candidates: list[dict],
    *,
    bankroll: float,
    max_event_exposure_pct: float,
) -> None:
    event_used: dict[str, float] = defaultdict(float)
    market_winner: dict[tuple[str, str, str], str] = {}
    for row in sorted(candidates, key=lambda item: item["evPercent"], reverse=True):
        exact_market = json.dumps(row.get("marketGroup"), sort_keys=True, default=str)
        conflict_key = (row["eventId"], row["marketKey"], exact_market)
        winner = market_winner.get(conflict_key)
        if winner and winner != row["selection"]:
            row["portfolioStatus"] = "conflict_suppressed"
            row["warnings"].append("A stronger opposing selection already uses this market.")
            row["recommendedStake"] = 0.0
            continue
        market_winner[conflict_key] = row["selection"]
        event_cap = bankroll * max_event_exposure_pct
        room = max(0.0, event_cap - event_used[row["eventId"]])
        constrained = min(float(row["recommendedStake"]), room)
        if constrained + 0.01 < float(row["recommendedStake"]):
            row["warnings"].append("Stake reduced by the per-event exposure cap.")
        row["recommendedStake"] = round(constrained, 2)
        event_used[row["eventId"]] += constrained
        if constrained <= 0:
            row["portfolioStatus"] = "event_cap_reached"


def build_ev_board(
    events: Iterable[dict],
    *,
    source_weights: dict[str, float] | None = None,
    execution_books: Iterable[str] = DEFAULT_EXECUTION_BOOKS,
    required_books: Iterable[str] = (),
    devig_method: str = "power",
    min_ev: float = 0.0,
    bankroll: float = 10000.0,
    kelly_fraction: float = 0.25,
    min_source_books: int = 3,
    max_quote_age_seconds: int = 180,
    max_source_age_seconds: int = 600,
    max_source_dispersion: float = 0.12,
    max_stake_pct: float = 0.02,
    max_event_exposure_pct: float = 0.05,
    fee_bps: dict[str, float] | None = None,
) -> dict:
    devig_method = str(devig_method or "power").strip().lower()
    if devig_method not in DEVIG_METHODS:
        raise ValueError(
            f"Unsupported de-vig method: {devig_method}. "
            f"Choose one of {', '.join(DEVIG_METHODS)}."
        )
    weights = {
        str(key).lower(): max(0.0, float(value))
        for key, value in (source_weights or DEFAULT_SOURCE_WEIGHTS).items()
    }
    targets = {str(key).lower() for key in execution_books}
    required_targets = {
        str(key).strip().lower() for key in required_books if str(key).strip()
    }
    fees = {**DEFAULT_FEE_BPS, **(fee_bps or {})}
    candidates: list[dict] = []
    rejected: Counter[str] = Counter()
    now = datetime.now(timezone.utc)

    for event in events:
        event_id = str(event.get("id") or "")
        commence = str(event.get("commence_time") or "")
        commence_at = _parse_time(commence)
        if commence_at is None:
            rejected["invalid_commence_time"] += 1
            continue
        if commence_at <= now:
            rejected["event_already_started"] += 1
            continue
        away = str(event.get("away_team") or "")
        home = str(event.get("home_team") or "")
        sport_key = str(event.get("sport_key") or "")
        league = str(event.get("sport_title") or sport_key)
        books_by_group: dict[tuple, dict[str, dict]] = defaultdict(dict)

        for book in event.get("bookmakers") or []:
            book_key = str(book.get("key") or "").lower()
            for market in book.get("markets") or []:
                market_key = str(market.get("key") or "").lower()
                grouped_outcomes: dict[tuple, list[dict]] = defaultdict(list)
                for outcome in market.get("outcomes") or []:
                    if outcome.get("price") is not None:
                        grouped_outcomes[_group_key(market_key, outcome)].append(outcome)
                for group, outcomes in grouped_outcomes.items():
                    if len(outcomes) < 2:
                        rejected["incomplete_market"] += 1
                        continue
                    if not all(_valid_american(outcome.get("price")) for outcome in outcomes):
                        rejected["invalid_odds"] += 1
                        continue
                    raw_probs = [american_to_probability(outcome["price"]) for outcome in outcomes]
                    hold = sum(raw_probs)
                    if not 0.85 <= hold <= 1.25:
                        rejected["abnormal_market_hold"] += 1
                        continue
                    updated = market.get("last_update") or book.get("last_update")
                    age = _quote_age_seconds(updated, now)
                    books_by_group[(market_key, group)][book_key] = {
                        "book": book,
                        "market": market,
                        "outcomes": outcomes,
                        "age": age,
                        "hold": hold,
                    }

        for (market_key, group), book_map in books_by_group.items():
            fair_by_selection: dict[tuple, list[tuple[float, float, str]]] = defaultdict(list)
            quotes_by_selection: dict[tuple, list[dict]] = defaultdict(list)
            labels: dict[tuple, dict] = {}
            for book_key, payload in book_map.items():
                outcomes = payload["outcomes"]
                no_vig = _devig(
                    [american_to_probability(outcome["price"]) for outcome in outcomes],
                    devig_method,
                )
                book = payload["book"]
                market = payload["market"]
                age = payload["age"]
                for outcome, fair_probability in zip(outcomes, no_vig):
                    selection = _selection_key(outcome)
                    labels[selection] = outcome
                    source_weight = weights.get(book_key, 0.0)
                    if source_weight > 0 and (age is None or age <= max_source_age_seconds):
                        fair_by_selection[selection].append(
                            (fair_probability, source_weight, book_key)
                        )
                    market_limit = outcome.get("bet_limit")
                    top_price_liquidity = outcome.get("liquidity")
                    try:
                        market_limit = float(market_limit) if market_limit is not None else None
                    except (TypeError, ValueError):
                        market_limit = None
                    try:
                        top_price_liquidity = (
                            float(top_price_liquidity)
                            if top_price_liquidity is not None
                            else None
                        )
                    except (TypeError, ValueError):
                        top_price_liquidity = None
                    top_american = int(round(float(outcome["price"])))
                    top_probability = american_to_probability(top_american)
                    quotes_by_selection[selection].append(
                        {
                            "bookKey": book_key,
                            "bookName": str(book.get("title") or book_key),
                            "logoUrl": _book_logo(book_key, book),
                            # Compatibility keys remain, but are explicitly the
                            # current top-of-book quote and never a depth VWAP.
                            "americanOdds": top_american,
                            "top_price": round(top_probability, 10),
                            "topPrice": round(top_probability, 10),
                            "top_price_american_odds": top_american,
                            "topPriceAmericanOdds": top_american,
                            "top_price_liquidity": top_price_liquidity,
                            "topPriceLiquidity": top_price_liquidity,
                            "market_limit": market_limit,
                            "marketLimit": market_limit,
                            "depth_vwap_price": outcome.get("depth_vwap_price"),
                            "depthVwapPrice": outcome.get("depth_vwap_price"),
                            "depth_executable_amount": outcome.get("depth_executable_amount"),
                            "depthExecutableAmount": outcome.get("depth_executable_amount"),
                            "depth_levels_used": outcome.get("depth_levels_used"),
                            "depthLevelsUsed": outcome.get("depth_levels_used"),
                            "point": outcome.get("point"),
                            "lastUpdated": str(
                                market.get("last_update") or book.get("last_update") or ""
                            ),
                            "quoteAgeSeconds": round(age, 1) if age is not None else None,
                            "deepLink": str(
                                outcome.get("link") or market.get("link") or book.get("link") or ""
                            ),
                            "liquidity": top_price_liquidity,
                            "marketHold": round(payload["hold"], 6),
                        }
                    )

            for selection, source_rows in fair_by_selection.items():
                fresh_selection_quotes = [
                    quote
                    for quote in quotes_by_selection.get(selection, [])
                    if (
                        quote["quoteAgeSeconds"] is None
                        or quote["quoteAgeSeconds"] <= max_quote_age_seconds
                    )
                ]
                available_books = {
                    quote["bookKey"] for quote in fresh_selection_quotes
                }
                if not required_targets.issubset(available_books):
                    rejected["missing_required_books"] += 1
                    continue
                quotes = [
                    quote
                    for quote in fresh_selection_quotes
                    if quote["bookKey"] in targets
                ]
                if not quotes:
                    rejected["no_fresh_execution_quote"] += 1
                    continue

                evaluated_quotes: list[tuple[dict, dict]] = []
                for quote in quotes:
                    leave_one_out = [row for row in source_rows if row[2] != quote["bookKey"]]
                    configured_weight = sum(
                        weights.get(book, 0.0)
                        for book in book_map
                        if book != quote["bookKey"]
                    )
                    consensus = _fair_consensus(
                        leave_one_out,
                        min_source_books=min_source_books,
                        max_source_dispersion=max_source_dispersion,
                        configured_weight=configured_weight,
                    )
                    if consensus is None:
                        continue
                    effective_decimal = _effective_decimal(
                        quote["topPriceAmericanOdds"], fees.get(quote["bookKey"], 0.0)
                    )
                    ev = consensus["fairProbability"] * effective_decimal - 1.0
                    execution_status = "executable"
                    execution_capacity = (
                        quote["topPriceLiquidity"]
                        if quote["topPriceLiquidity"] is not None
                        else quote["marketLimit"]
                    )
                    if quote["bookKey"] in EXCHANGE_BOOKS and execution_capacity is None:
                        execution_status = "liquidity_unknown"
                    elif execution_capacity is not None and execution_capacity <= 0:
                        execution_status = "unavailable"
                    enriched = {
                        **quote,
                        "feeBps": float(fees.get(quote["bookKey"], 0.0)),
                        "effectiveDecimal": round(effective_decimal, 6),
                        "effectiveAmerican": probability_to_american(1.0 / effective_decimal),
                        "evPercent": round(ev * 100.0, 4),
                        "executionStatus": execution_status,
                        "fairProbability": round(consensus["fairProbability"], 8),
                        "executionCapacity": execution_capacity,
                    }
                    evaluated_quotes.append((enriched, consensus))

                if not evaluated_quotes:
                    rejected["insufficient_independent_sources"] += 1
                    continue
                evaluated_quotes.sort(
                    key=lambda item: (
                        item[0]["executionStatus"] == "executable",
                        item[0]["evPercent"],
                        -DEFAULT_EXECUTION_PRIORITY.get(item[0]["bookKey"], 99),
                    ),
                    reverse=True,
                )
                best, consensus = evaluated_quotes[0]
                ev = float(best["evPercent"]) / 100.0
                if ev * 100.0 < float(min_ev):
                    rejected["below_minimum_ev"] += 1
                    continue

                fair_probability = consensus["fairProbability"]
                decimal_odds = best["effectiveDecimal"]
                full_kelly = max(
                    0.0,
                    (
                        fair_probability * (decimal_odds - 1.0)
                        - (1.0 - fair_probability)
                    )
                    / max(0.0001, decimal_odds - 1.0),
                )
                confidence_multiplier = max(0.0, min(1.0, consensus["fairConfidence"]))
                theoretical_stake = bankroll * full_kelly * kelly_fraction
                confidence_stake = theoretical_stake * confidence_multiplier
                per_bet_cap = bankroll * max_stake_pct
                recommended_stake = min(confidence_stake, per_bet_cap)
                warnings: list[str] = []
                execution_capacity = best.get("executionCapacity")
                if execution_capacity is not None:
                    if recommended_stake > execution_capacity:
                        qualifier = (
                            "top-price liquidity"
                            if best.get("topPriceLiquidity") is not None
                            else "reported market limit"
                        )
                        warnings.append(f"Stake reduced to the {qualifier}.")
                    recommended_stake = min(recommended_stake, execution_capacity)
                if best["executionStatus"] == "liquidity_unknown":
                    warnings.append("Verify exchange depth before placing this stake.")
                if best["quoteAgeSeconds"] is None:
                    warnings.append("The provider did not supply a quote timestamp.")
                if fair_probability < 0.40:
                    longshot_cap = bankroll * min(max_stake_pct, 0.0125)
                    if recommended_stake > longshot_cap:
                        warnings.append("Longshot variance cap reduced the Kelly stake.")
                    recommended_stake = min(recommended_stake, longshot_cap)

                outcome = labels[selection]
                selected_quotes_by_book = {
                    quote["bookKey"]: quote
                    for quote in quotes_by_selection.get(selection, [])
                }
                source_books = [
                    {
                        "bookKey": row[2],
                        "bookName": selected_quotes_by_book.get(row[2], {}).get(
                            "bookName", row[2]
                        ),
                        "logoUrl": selected_quotes_by_book.get(row[2], {}).get(
                            "logoUrl", ""
                        ),
                        "americanOdds": selected_quotes_by_book.get(row[2], {}).get(
                            "topPriceAmericanOdds"
                        ),
                        "lastUpdated": selected_quotes_by_book.get(row[2], {}).get(
                            "lastUpdated", ""
                        ),
                        "quoteAgeSeconds": selected_quotes_by_book.get(row[2], {}).get(
                            "quoteAgeSeconds"
                        ),
                        "weight": row[1],
                        "fairProbability": round(row[0], 8),
                    }
                    for row in consensus["sourceRows"]
                ]
                source_books.sort(
                    key=lambda source: (
                        float(source["weight"]),
                        str(source["bookKey"]),
                    ),
                    reverse=True,
                )
                ordered_market_selections = [selection] + [
                    item for item in labels if item != selection
                ]
                market_sides = []
                for market_selection in ordered_market_selections:
                    side_quotes = [
                        quote
                        for quote in quotes_by_selection.get(market_selection, [])
                        if (
                            quote["quoteAgeSeconds"] is None
                            or quote["quoteAgeSeconds"] <= max_quote_age_seconds
                        )
                    ]
                    side_quotes.sort(
                        key=lambda quote: quote["topPriceAmericanOdds"],
                        reverse=True,
                    )
                    market_sides.append(
                        {
                            "selection": _selection_label(
                                market_key, labels[market_selection]
                            ),
                            "quotes": side_quotes,
                        }
                    )
                candidate_id = (
                    f"ev::{event_id}::{market_key}::"
                    f"{hashlib.sha256(json.dumps(selection, default=str).encode()).hexdigest()[:16]}"
                )
                candidates.append(
                    {
                        "id": candidate_id,
                        "eventId": event_id,
                        "sportKey": sport_key,
                        "league": league,
                        "eventTitle": f"{away} vs {home}",
                        "homeTeam": home,
                        "awayTeam": away,
                        "commenceTime": commence,
                        "marketKey": market_key,
                        "marketGroup": group,
                        "marketLabel": _market_label(market_key),
                        "selection": _selection_label(market_key, outcome),
                        "evPercent": round(ev * 100.0, 2),
                        "fairProbability": round(fair_probability, 6),
                        "fairAmerican": probability_to_american(fair_probability),
                        "fairConfidence": round(confidence_multiplier, 4),
                        "sourceCount": consensus["sourceCount"],
                        "sourceDispersion": round(consensus["sourceDispersion"], 6),
                        "sourceCoverage": round(consensus["sourceCoverage"], 2),
                        "sourceCoverageRatio": round(consensus["sourceCoverageRatio"], 4),
                        "sourceBooks": source_books,
                        "bestQuote": best,
                        "quotes": [item[0] for item in evaluated_quotes],
                        "marketSides": market_sides,
                        "executionStatus": best["executionStatus"],
                        "portfolioStatus": "qualified",
                        "theoreticalStake": round(theoretical_stake, 2),
                        "recommendedStake": round(max(0.0, recommended_stake), 2),
                        "kellyFraction": round(full_kelly * kelly_fraction, 6),
                        "fullKellyFraction": round(full_kelly, 6),
                        "warnings": warnings,
                        "calculatedAt": now.isoformat(),
                        "calculationVersion": "ev-optimizer-v3-top-of-book",
                        "devigMethod": devig_method,
                        "requiredBooks": sorted(required_targets),
                    }
                )

    _apply_portfolio_limits(
        candidates,
        bankroll=bankroll,
        max_event_exposure_pct=max_event_exposure_pct,
    )
    candidates.sort(
        key=lambda row: (
            row["portfolioStatus"] == "qualified",
            row["executionStatus"] == "executable",
            row["evPercent"],
        ),
        reverse=True,
    )
    return {
        "data": candidates,
        "diagnostics": {
            "eventsScanned": len(list(events)) if isinstance(events, list) else None,
            "qualified": sum(
                1
                for row in candidates
                if row["portfolioStatus"] == "qualified"
                and row["executionStatus"] == "executable"
            ),
            "watchOnly": sum(
                1
                for row in candidates
                if row["executionStatus"] != "executable"
                or row["portfolioStatus"] != "qualified"
            ),
            "rejected": sum(rejected.values()),
            "rejectionReasons": dict(sorted(rejected.items())),
            "calculationVersion": "ev-optimizer-v3-top-of-book",
            "devigMethod": devig_method,
            "requiredBooks": sorted(required_targets),
        },
    }


def build_ev_candidates(events: Iterable[dict], **kwargs) -> list[dict]:
    """Compatibility wrapper for callers that only need candidate rows."""
    return build_ev_board(events, **kwargs)["data"]
