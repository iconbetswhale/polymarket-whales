from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from dfs_probability_engine import (
    DfsProbabilityEngine,
    ICONLABS_DFS_WEIGHTS,
    american_to_probability,
)
from sports_game_odds import SPORTS_GAME_ODDS_BOOKMAKERS


DFS_EXTRA_BOOKMAKERS = {
    "pick6": {"name": "DraftKings Pick6", "type": "dfs"},
    "betr_picks": {"name": "Betr Picks", "type": "dfs"},
    "dabble": {"name": "Dabble", "type": "dfs"},
}
EASTERN = ZoneInfo("America/New_York")


DFS_BOOK_KEY_BY_PROVIDER = {
    "prizepicks": "prizepicks",
    "underdog": "underdog",
    "pick6": "dk-pick6",
    "betr_picks": "betr",
    "dabble": "dabble",
    "sleeper": "sleeper",
}
DFS_BOOK_KEYS = frozenset(DFS_BOOK_KEY_BY_PROVIDER.values())
DFS_OPTIMIZER_BOOK_KEYS = (
    "prizepicks",
    "underdog",
    "dk-pick6",
    "betr",
    "dabble",
)

# Two sharp, independent exact-line sources can qualify; otherwise require
# three sources before a probability becomes an executable Fantasy signal.
DFS_SHARP_MODEL_SOURCES = frozenset(
    {"pinnacle", "circa", "bookmakereu", "novig", "prophetx"}
)

MODEL_PROVIDER_ALIASES = {
    "prophetexchange": "prophetx",
}

DISPLAY_PROVIDER_ALIASES = {
    "hardrockbet": "hard-rock",
    "parlayplay": "parlay-play",
    "prophetexchange": "prophetx",
}

STAT_TITLES = {
    "batter_hits": "Hits",
    "batter_total_bases": "Total Bases",
    "batter_home_runs": "Home Runs",
    "batter_rbis": "RBIs",
    "batter_runs_scored": "Runs",
    "batter_hits_runs_rbis": "Hits + Runs + RBIs",
    "batter_runs_rbis": "Runs + RBIs",
    "batter_singles": "Singles",
    "batter_doubles": "Doubles",
    "batter_triples": "Triples",
    "batter_walks": "Walks",
    "batter_strikeouts": "Strikeouts",
    "batter_stolen_bases": "Stolen Bases",
    "pitcher_strikeouts": "Strikeouts",
    "pitcher_hits_allowed": "Hits Allowed",
    "pitcher_walks": "Walks Allowed",
    "pitcher_earned_runs": "Earned Runs",
    "pitcher_outs": "Pitching Outs",
    "pitcher_pitches_thrown": "Pitches Thrown",
    "player_points": "Points",
    "player_points_q1": "1Q Points",
    "player_rebounds": "Rebounds",
    "player_rebounds_q1": "1Q Rebounds",
    "player_assists": "Assists",
    "player_assists_q1": "1Q Assists",
    "player_threes": "3-Pointers Made",
    "player_blocks": "Blocks",
    "player_steals": "Steals",
    "player_blocks_steals": "Blocks + Steals",
    "player_turnovers": "Turnovers",
    "player_points_rebounds_assists": "Points + Rebounds + Assists",
    "player_points_rebounds": "Points + Rebounds",
    "player_points_assists": "Points + Assists",
    "player_rebounds_assists": "Rebounds + Assists",
    "player_field_goals": "Field Goals Made",
    "player_field_goals_attempted": "Field Goals Attempted",
    "player_frees_made": "Free Throws Made",
    "player_frees_attempts": "Free Throws Attempted",
}


def _point(outcome: dict) -> float | None:
    try:
        return float(outcome.get("point"))
    except (TypeError, ValueError):
        return None


def _price(outcome: dict) -> int | None:
    try:
        price = int(round(float(outcome.get("price"))))
    except (TypeError, ValueError):
        return None
    return price if price != 0 else None


def _nonnegative_number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _multiplier(outcome: dict) -> float | None:
    try:
        raw = str(outcome.get("multiplier") or "").strip().lower().rstrip("x")
        parsed = float(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _line_key(value: float) -> str:
    return f"{value:g}"


def _display_price(book_key: str, american_odds: int) -> str:
    """Use native-looking cents for prediction exchanges in the DFS grid."""
    if book_key in {"kalshi", "polymarket"}:
        probability = american_to_probability(american_odds)
        if probability is not None:
            cents = probability * 100.0
            return f"{cents:.0f}\u00a2" if cents >= 99.95 else f"{cents:.1f}\u00a2"
    return f"{american_odds:+d}"


def _date_label(start: datetime, now: datetime) -> str:
    local_start = start.astimezone(EASTERN)
    local_now = now.astimezone(EASTERN)
    if local_start.date() == local_now.date():
        return "today"
    if local_start.date() == (local_now + timedelta(days=1)).date():
        return "tomorrow"
    return "this_week"


def _time_label(start: datetime, now: datetime) -> str:
    label = _date_label(start, now)
    prefix = {"today": "Today", "tomorrow": "Tomorrow"}.get(
        label, start.astimezone(EASTERN).strftime("%a")
    )
    clock = start.astimezone(EASTERN).strftime("%I:%M %p").lstrip("0")
    return f"{prefix} · {clock}"


def _nearest_quote(quotes: list[dict], target_line: float) -> dict | None:
    if not quotes:
        return None
    return min(
        quotes,
        key=lambda quote: (
            abs(float(quote["line"]) - target_line),
            str(quote.get("quote_timestamp") or ""),
        ),
    )


def build_dfs_odds_board(
    events: Iterable[dict],
    *,
    weights: dict[str, float] | None = None,
    now: datetime | None = None,
    limit: int = 250,
    selected_dfs_book: str | None = None,
) -> list[dict]:
    """Build live DFS rows from normalized all-book prop markets."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    selected_book = str(selected_dfs_book or "").strip().lower() or None
    if selected_book is not None and selected_book not in DFS_BOOK_KEYS:
        raise ValueError("selected_dfs_book must be a supported DFS book")
    groups: dict[tuple[str, str, str], dict] = {}
    for event in events:
        event_id = str(event.get("id") or "").strip()
        start = _parse_time(event.get("commence_time"))
        if not event_id or start is None or start <= current:
            continue
        away_team = str(event.get("away_team") or "").strip()
        home_team = str(event.get("home_team") or "").strip()
        matchup = f"{away_team or 'Away'} vs {home_team or 'Home'}"
        sport = str(event.get("sport_title") or "").upper()
        for bookmaker in event.get("bookmakers") or []:
            book_key = str(bookmaker.get("key") or "").strip().lower()
            metadata = SPORTS_GAME_ODDS_BOOKMAKERS.get(
                book_key
            ) or DFS_EXTRA_BOOKMAKERS.get(book_key)
            if not metadata:
                continue
            for market in bookmaker.get("markets") or []:
                market_key = str(market.get("key") or "").strip().lower()
                if market_key not in STAT_TITLES:
                    continue
                outcomes = [
                    outcome
                    for outcome in market.get("outcomes") or []
                    if isinstance(outcome, dict)
                ]
                player = next(
                    (
                        str(outcome.get("description") or "").strip()
                        for outcome in outcomes
                        if str(outcome.get("description") or "").strip()
                    ),
                    "",
                )
                if not player:
                    continue
                by_line: dict[float, dict[str, dict]] = defaultdict(dict)
                for outcome in outcomes:
                    side = str(outcome.get("name") or "").strip().lower()
                    line = _point(outcome)
                    if side not in {"over", "under"} or line is None:
                        continue
                    by_line[line][side] = outcome
                group = groups.setdefault(
                    (event_id, market_key, player.casefold()),
                    {
                        "event_id": event_id,
                        "player": player,
                        "match": matchup,
                        "away_team": away_team,
                        "home_team": home_team,
                        "sport": sport,
                        "start": start,
                        "stat": STAT_TITLES[market_key],
                        "quotes": defaultdict(list),
                        "dfs_options": defaultdict(dict),
                    },
                )
                for line, sides in by_line.items():
                    quote = {
                        "provider": MODEL_PROVIDER_ALIASES.get(book_key, book_key),
                        "book_key": book_key,
                        "line": line,
                        "over_odds": _price(sides.get("over", {})),
                        "under_odds": _price(sides.get("under", {})),
                        "over_liquidity": _nonnegative_number(
                            sides.get("over", {}).get("liquidity")
                        ),
                        "under_liquidity": _nonnegative_number(
                            sides.get("under", {}).get("liquidity")
                        ),
                        "over_link": str(sides.get("over", {}).get("link") or ""),
                        "under_link": str(sides.get("under", {}).get("link") or ""),
                        "quote_timestamp": str(
                            market.get("last_update")
                            or bookmaker.get("last_update")
                            or current.isoformat()
                        ),
                    }
                    if metadata["type"] == "dfs":
                        ui_key = DFS_BOOK_KEY_BY_PROVIDER.get(book_key)
                        if ui_key:
                            option = group["dfs_options"][ui_key].setdefault(
                                line,
                                {
                                    "sides": set(),
                                    "is_alt": False,
                                    "standard_multiplier": True,
                                },
                            )
                            option["sides"].update(sides)
                            option["is_alt"] = bool(option["is_alt"]) or any(
                                bool(outcome.get("is_alt"))
                                or bool(outcome.get("is_boosted"))
                                or bool(outcome.get("is_promotional"))
                                for outcome in sides.values()
                            )
                            option["standard_multiplier"] = bool(
                                option["standard_multiplier"]
                            ) and all(
                                _multiplier(outcome) is None
                                or abs(float(_multiplier(outcome)) - 1.0) < 1e-9
                                for outcome in sides.values()
                            )
                    else:
                        group["quotes"][book_key].append(quote)

    engine_weights = weights or ICONLABS_DFS_WEIGHTS
    # A single source is useful for line shopping, but it is not independent
    # evidence for an executable fair-probability recommendation.
    minimum_sources = 2
    engine = DfsProbabilityEngine(
        engine_weights,
        devig_method="power",
        max_quote_age_seconds=90,
        freshness_half_life_seconds=90,
        minimum_sources=minimum_sources,
    )
    pair_capable_app_sports = {
        (ui_key, group["sport"])
        for group in groups.values()
        for ui_key, line_options in group["dfs_options"].items()
        if any(
            not option.get("is_alt")
            and option.get("standard_multiplier", True)
            and {"over", "under"}.issubset(option.get("sides") or set())
            for option in line_options.values()
        )
    }
    rows: list[dict] = []
    for group in groups.values():
        dfs_options = group["dfs_options"]
        if not dfs_options or (selected_book and selected_book not in dfs_options):
            continue
        dfs_lines: dict[str, float] = {}
        dfs_sides: dict[str, set[str]] = {}
        for ui_key, line_options in dfs_options.items():
            eligible_line_options = {
                line: option
                for line, option in line_options.items()
                if not option.get("is_alt")
                and option.get("standard_multiplier", True)
            }
            if (ui_key, group["sport"]) in pair_capable_app_sports:
                eligible_line_options = {
                    line: option
                    for line, option in line_options.items()
                    if {"over", "under"}.issubset(option.get("sides") or set())
                }
            if not eligible_line_options:
                continue
            primary_line, primary_option = min(
                eligible_line_options.items(),
                key=lambda item: (
                    bool(item[1].get("is_alt")),
                    float(item[0]),
                ),
            )
            dfs_lines[ui_key] = float(primary_line)
            dfs_sides[ui_key] = set(primary_option.get("sides") or ())
        if not dfs_lines or (selected_book and selected_book not in dfs_lines):
            continue
        display_book = selected_book or (
            "prizepicks" if "prizepicks" in dfs_lines else sorted(dfs_lines)[0]
        )
        selectable_sides = dfs_sides.get(display_book, set())
        target_lines = sorted(set(dfs_lines.values()))
        flat_quotes = [
            quote for book_quotes in group["quotes"].values() for quote in book_quotes
        ]
        for side in ("Over", "Under"):
            side_key = side.lower()
            if side_key not in selectable_sides:
                continue
            hit_by_line: dict[str, float | None] = {}
            fair_odds_by_line: dict[str, float | None] = {}
            reliability_by_line: dict[str, float] = {}
            exact_sources_by_line: dict[str, int] = {}
            devig_sources_by_line: dict[str, dict[str, list[float]]] = {}
            model_quality_by_line: dict[str, dict[str, str]] = {}
            model_status_by_line: dict[str, str] = {}
            model_evidence_by_line: dict[str, dict] = {}
            for target_line in target_lines:
                result = engine.calculate(
                    target_line=target_line,
                    side=side,
                    quotes=flat_quotes,
                    now=current,
                )
                key = _line_key(target_line)
                hit_by_line[key] = result.hit_rate_percent
                fair_odds_by_line[key] = result.fair_american_odds
                reliability_by_line[key] = result.reliability
                exact_sources_by_line[key] = result.source_count
                devig_sources_by_line[key] = {
                    str(contribution["provider"]): [
                        round(float(contribution["no_vig_probability"]), 8),
                        round(float(contribution["freshness_factor"]), 8),
                    ]
                    for contribution in result.contributions
                    if contribution.get("provider") in ICONLABS_DFS_WEIGHTS
                    and contribution.get("no_vig_probability") is not None
                    and contribution.get("exclusion_reason")
                    in {None, "PROVIDER_WEIGHT_NOT_CONFIGURED"}
                }
                model_quality_by_line[key] = {
                    str(contribution["provider"]): str(
                        contribution.get("exclusion_reason") or ""
                    )
                    for contribution in result.contributions
                    if contribution.get("exclusion_reason")
                    not in {None, "PROVIDER_WEIGHT_NOT_CONFIGURED"}
                }
                included_sources = {
                    str(contribution.get("provider") or "")
                    for contribution in result.contributions
                    if contribution.get("no_vig_probability") is not None
                    and contribution.get("exclusion_reason")
                    in {None, "PROVIDER_WEIGHT_NOT_CONFIGURED"}
                }
                two_sharp_sources = (
                    result.source_count >= 2
                    and included_sources
                    and included_sources.issubset(DFS_SHARP_MODEL_SOURCES)
                )
                qualified = result.source_count >= 3 or two_sharp_sources
                model_status_by_line[key] = (
                    result.status if qualified else "WATCH_ONLY"
                )
                model_evidence_by_line[key] = {
                    "qualified": qualified,
                    "sourceCount": result.source_count,
                    "sourceKeys": sorted(included_sources),
                    "rule": (
                        "THREE_INDEPENDENT_SOURCES"
                        if result.source_count >= 3
                        else "TWO_SHARP_SOURCES"
                        if two_sharp_sources
                        else "INSUFFICIENT_INDEPENDENT_EVIDENCE"
                    ),
                }

            primary_line = dfs_lines[display_book]
            side_dfs_lines = {
                book_key: line
                for book_key, line in dfs_lines.items()
                if side_key in dfs_sides.get(book_key, set())
            }
            odds_by_book: dict[str, object] = {}
            for book_key, book_quotes in group["quotes"].items():
                quote = _nearest_quote(book_quotes, primary_line)
                if quote is None:
                    continue
                price = quote[f"{side.lower()}_odds"]
                if price is None:
                    continue
                display_key = DISPLAY_PROVIDER_ALIASES.get(book_key, book_key)
                display_odds = _display_price(book_key, price)
                quote_line_key = _line_key(float(quote["line"]))
                quality_reason = model_quality_by_line.get(quote_line_key, {}).get(
                    MODEL_PROVIDER_ALIASES.get(book_key, book_key)
                )
                if float(quote["line"]) != float(primary_line):
                    quality_reason = "LINE_MISMATCH"
                odds_by_book[display_key] = {
                    "odds": display_odds,
                    "americanOdds": price,
                    "line": quote["line"],
                    "liquidity": quote.get(f"{side_key}_liquidity"),
                    "deepLink": quote.get(f"{side_key}_link") or "",
                    "modelExcluded": bool(quality_reason),
                    "modelExclusionReason": quality_reason or "",
                }
            primary_key = _line_key(primary_line)
            rows.append(
                {
                    "id": (
                        f"{group['event_id']}::{group['player']}::"
                        f"{group['stat']}::{side.lower()}"
                    ),
                    "eventId": group["event_id"],
                    "player": group["player"],
                    "match": group["match"],
                    "awayTeam": group["away_team"],
                    "homeTeam": group["home_team"],
                    "sport": group["sport"],
                    "date": _date_label(group["start"], current),
                    "eventDate": group["start"].astimezone(EASTERN).date().isoformat(),
                    "time": _time_label(group["start"], current),
                    "side": side,
                    "stat": group["stat"],
                    "line": primary_line,
                    "dfsLines": side_dfs_lines,
                    "hit": hit_by_line.get(primary_key),
                    "hitByLine": hit_by_line,
                    "fairOddsByLine": fair_odds_by_line,
                    "reliabilityByLine": reliability_by_line,
                    "exactSourcesByLine": exact_sources_by_line,
                    "minimumSourcesByLine": {
                        _line_key(line): minimum_sources for line in target_lines
                    },
                    "devigSourcesByLine": devig_sources_by_line,
                    "modelQualityByLine": model_quality_by_line,
                    "modelStatusByLine": model_status_by_line,
                    "modelEvidenceByLine": model_evidence_by_line,
                    "modelStatus": model_status_by_line.get(
                        primary_key, "UNAVAILABLE"
                    ),
                    "executionEligible": bool(
                        model_evidence_by_line.get(primary_key, {}).get(
                            "qualified"
                        )
                    ),
                    "reliability": reliability_by_line.get(primary_key, 0.0),
                    "oddsByBook": odds_by_book,
                    "sourceCount": exact_sources_by_line.get(primary_key, 0),
                    "availableQuoteCount": len(flat_quotes),
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            row["hit"] is None,
            -float(row.get("hit") or 0.0),
            -float(row.get("reliability") or 0.0),
            row["time"],
            row["player"],
            row["stat"],
            row["side"],
        ),
    )[: max(1, int(limit))]
