from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable


# Canonical SportsGameOdds bookmaker identifiers from the user's All Lines
# package.  Keep these identifiers separate from display labels: the API
# silently omits a bookmaker when an unsupported alias is sent.
SPORTS_GAME_ODDS_BOOKMAKERS: dict[str, dict[str, str]] = {
    "bet365": {"name": "Bet365", "type": "sportsbook"},
    "circa": {"name": "Circa", "type": "sportsbook"},
    "fanatics": {"name": "Fanatics", "type": "sportsbook"},
    "pinnacle": {"name": "Pinnacle", "type": "sportsbook"},
    "prizepicks": {"name": "PrizePicks", "type": "dfs"},
    "fanduel": {"name": "FanDuel", "type": "sportsbook"},
    "draftkings": {"name": "DraftKings", "type": "sportsbook"},
    "betmgm": {"name": "BetMGM", "type": "sportsbook"},
    "caesars": {"name": "Caesars", "type": "sportsbook"},
    "espnbet": {"name": "ESPN BET", "type": "sportsbook"},
    "bovada": {"name": "Bovada", "type": "sportsbook"},
    "unibet": {"name": "Unibet", "type": "sportsbook"},
    "pointsbet": {"name": "PointsBet", "type": "sportsbook"},
    "williamhill": {"name": "William Hill", "type": "sportsbook"},
    "1xbet": {"name": "1xBet", "type": "sportsbook"},
    "888sport": {"name": "888 Sport", "type": "sportsbook"},
    "ballybet": {"name": "Bally Bet", "type": "sportsbook"},
    "barstool": {"name": "Barstool", "type": "sportsbook"},
    "betvictor": {"name": "Bet Victor", "type": "sportsbook"},
    "betanysports": {"name": "BetAnySports", "type": "sportsbook"},
    "betclic": {"name": "BetClic", "type": "sportsbook"},
    "betonline": {"name": "BetOnline", "type": "sportsbook"},
    "betparx": {"name": "BetPARX", "type": "sportsbook"},
    "betrivers": {"name": "BetRivers", "type": "sportsbook"},
    "betus": {"name": "BetUS", "type": "sportsbook"},
    "betfairexchange": {"name": "Betfair Exchange", "type": "exchange"},
    "betfairsportsbook": {"name": "Betfair Sportsbook", "type": "sportsbook"},
    "betfred": {"name": "Betfred", "type": "sportsbook"},
    "betrsportsbook": {"name": "Betr Sportsbook", "type": "sportsbook"},
    "betsafe": {"name": "Betsafe", "type": "sportsbook"},
    "betsson": {"name": "Betsson", "type": "sportsbook"},
    "betway": {"name": "Betway", "type": "sportsbook"},
    "bluebet": {"name": "BlueBet", "type": "sportsbook"},
    "bodog": {"name": "Bodog", "type": "sportsbook"},
    "bookmakereu": {"name": "Bookmaker.eu", "type": "sportsbook"},
    "boombet": {"name": "BoomBet", "type": "sportsbook"},
    "boylesports": {"name": "BoyleSports", "type": "sportsbook"},
    "casumo": {"name": "Casumo", "type": "sportsbook"},
    "coolbet": {"name": "Coolbet", "type": "sportsbook"},
    "coral": {"name": "Coral", "type": "sportsbook"},
    "everygame": {"name": "Everygame", "type": "sportsbook"},
    "foxbet": {"name": "FOX Bet", "type": "sportsbook"},
    "fliff": {"name": "Fliff", "type": "sportsbook"},
    "fourwinds": {"name": "FourWinds", "type": "sportsbook"},
    "gtbets": {"name": "GTbets", "type": "sportsbook"},
    "grosvenor": {"name": "Grosvenor", "type": "sportsbook"},
    "hardrockbet": {"name": "Hard Rock Bet", "type": "sportsbook"},
    "hotstreak": {"name": "HotStreak", "type": "dfs"},
    "kalshi": {"name": "Kalshi", "type": "exchange"},
    "ladbrokes": {"name": "Ladbrokes", "type": "sportsbook"},
    "leovegas": {"name": "LeoVegas", "type": "sportsbook"},
    "livescorebet": {"name": "LiveScore Bet", "type": "sportsbook"},
    "lowvig": {"name": "LowVig", "type": "sportsbook"},
    "marathonbet": {"name": "Marathon Bet", "type": "sportsbook"},
    "matchbook": {"name": "Matchbook", "type": "exchange"},
    "mrgreen": {"name": "Mr Green", "type": "sportsbook"},
    "mybookie": {"name": "MyBookie", "type": "sportsbook"},
    "neds": {"name": "Neds", "type": "sportsbook"},
    "nordicbet": {"name": "NordicBet", "type": "sportsbook"},
    "northstarbets": {"name": "NorthStar Bets", "type": "sportsbook"},
    "novig": {"name": "Novig", "type": "exchange"},
    "paddypower": {"name": "Paddy Power", "type": "sportsbook"},
    "parlayplay": {"name": "ParlayPlay", "type": "dfs"},
    "polymarket": {"name": "Polymarket", "type": "exchange"},
    "playup": {"name": "PlayUp", "type": "sportsbook"},
    "primesports": {"name": "Prime Sports", "type": "sportsbook"},
    "prophetexchange": {"name": "Prophet Exchange", "type": "sportsbook"},
    "si": {"name": "SI Sportsbook", "type": "sportsbook"},
    "skybet": {"name": "Sky Bet", "type": "sportsbook"},
    "sleeper": {"name": "Sleeper", "type": "dfs"},
    "sportsbet": {"name": "SportsBet", "type": "sportsbook"},
    "sportsbetting_ag": {"name": "SportsBetting.ag", "type": "sportsbook"},
    "sporttrade": {"name": "Sporttrade", "type": "exchange"},
    "stake": {"name": "Stake", "type": "sportsbook"},
    "superbook": {"name": "Superbook", "type": "sportsbook"},
    "suprabets": {"name": "Suprabets", "type": "sportsbook"},
    "tab": {"name": "TAB", "type": "sportsbook"},
    "tabtouch": {"name": "TABtouch", "type": "sportsbook"},
    "tipico": {"name": "Tipico", "type": "sportsbook"},
    "topsport": {"name": "TopSport", "type": "sportsbook"},
    "underdog": {"name": "Underdog", "type": "dfs"},
    "virginbet": {"name": "Virgin Bet", "type": "sportsbook"},
    "windcreek": {"name": "Wind Creek (Betfred PA)", "type": "sportsbook"},
    "wynnbet": {"name": "WynnBet", "type": "sportsbook"},
    "thescorebet": {"name": "theScore Bet", "type": "sportsbook"},
}

SPORTS_GAME_ODDS_LOGOS = {
    "bet365": "/static/assets/sportsbooks/bet365.png",
    "circa": "/static/assets/dfs-books/circa.png",
    "fanatics": "/static/assets/sportsbooks/fanatics.png",
    "pinnacle": "/static/assets/providers/pinnacle.png",
    "prizepicks": "/static/assets/dfs-books/prizepicks.png",
    "fanduel": "/static/assets/sportsbooks/fanduel.png",
    "draftkings": "/static/assets/sportsbooks/draftkings.png",
    "betmgm": "/static/assets/sportsbooks/betmgm.png",
    "caesars": "/static/assets/sportsbooks/caesars.png",
    "espnbet": "/static/assets/sportsbooks/espn-bet.png",
    "bovada": "/static/assets/sportsbooks/bovada.png",
    "unibet": "/static/assets/sportsbooks/catalog/unibet.jpg",
    "pointsbet": "/static/assets/sportsbooks/catalog/pointsbet.jpg",
    "williamhill": "/static/assets/sportsbooks/catalog/williamhill.jpg",
    "1xbet": "/static/assets/sportsbooks/catalog/1xbet.jpg",
    "888sport": "/static/assets/sportsbooks/catalog/888sport.jpg",
    "ballybet": "/static/assets/sportsbooks/catalog/ballybet.jpg",
    "barstool": "/static/assets/sportsbooks/catalog/barstool.jpg",
    "betvictor": "/static/assets/sportsbooks/catalog/betvictor.jpg",
    "betanysports": "/static/assets/sportsbooks/catalog/betanysports.jpg",
    "betclic": "/static/assets/sportsbooks/catalog/betclic.png",
    "betonline": "/static/assets/sportsbooks/betonline.png",
    "betparx": "/static/assets/sportsbooks/catalog/betparx.jpg",
    "betrivers": "/static/assets/sportsbooks/betrivers.png",
    "betus": "/static/assets/sportsbooks/catalog/betus.jpg",
    "betfairexchange": "/static/assets/sportsbooks/catalog/betfairexchange.png",
    "betfairsportsbook": "/static/assets/sportsbooks/catalog/betfairsportsbook.jpg",
    "betfred": "/static/assets/sportsbooks/catalog/betfred.jpg",
    "betrsportsbook": "/static/assets/dfs-books/betr.png",
    "betsafe": "/static/assets/sportsbooks/catalog/betsafe.jpg",
    "betsson": "/static/assets/sportsbooks/catalog/betsson.jpg",
    "betway": "/static/assets/sportsbooks/catalog/betway.jpg",
    "bluebet": "/static/assets/sportsbooks/catalog/bluebet.jpg",
    "bodog": "/static/assets/sportsbooks/catalog/bodog.jpg",
    "bookmakereu": "/static/assets/sportsbooks/catalog/bookmakereu.jpg",
    "boombet": "/static/assets/sportsbooks/catalog/boombet.jpg",
    "boylesports": "/static/assets/sportsbooks/catalog/boylesports.png",
    "casumo": "/static/assets/sportsbooks/catalog/casumo.jpg",
    "coolbet": "/static/assets/sportsbooks/catalog/coolbet.jpg",
    "coral": "/static/assets/sportsbooks/catalog/coral.jpg",
    "everygame": "/static/assets/sportsbooks/catalog/everygame.jpg",
    "foxbet": "/static/assets/sportsbooks/catalog/foxbet.jpg",
    "fliff": "/static/assets/sportsbooks/fliff.png",
    "fourwinds": "/static/assets/sportsbooks/catalog/fourwinds.jpg",
    "gtbets": "/static/assets/sportsbooks/catalog/gtbets.png",
    "grosvenor": "/static/assets/sportsbooks/catalog/grosvenor.png",
    "hardrockbet": "/static/assets/sportsbooks/hard-rock-bet.png?v=hard-rock-purple-20260815",
    "hotstreak": "/static/assets/sportsbooks/catalog/hotstreak.jpg",
    "kalshi": "/static/assets/providers/kalshi.png",
    "ladbrokes": "/static/assets/sportsbooks/catalog/ladbrokes.jpg",
    "leovegas": "/static/assets/sportsbooks/catalog/leovegas.jpg",
    "livescorebet": "/static/assets/sportsbooks/catalog/livescorebet.png",
    "lowvig": "/static/assets/sportsbooks/catalog/lowvig.jpeg",
    "marathonbet": "/static/assets/sportsbooks/catalog/marathonbet.png",
    "matchbook": "/static/assets/sportsbooks/catalog/matchbook.png",
    "mrgreen": "/static/assets/sportsbooks/catalog/mrgreen.jpg",
    "mybookie": "/static/assets/sportsbooks/catalog/mybookie.jpg",
    "neds": "/static/assets/sportsbooks/catalog/neds.jpg",
    "nordicbet": "/static/assets/sportsbooks/catalog/nordicbet.png",
    "northstarbets": "/static/assets/sportsbooks/catalog/northstarbets.jpg",
    "novig": "/static/assets/providers/novig.png",
    "paddypower": "/static/assets/sportsbooks/catalog/paddypower.jpg",
    "parlayplay": "/static/assets/dfs-books/parlay-play.png",
    "polymarket": "/static/assets/sportsbooks/polymarket.png",
    "playup": "/static/assets/sportsbooks/catalog/playup.jpg",
    "primesports": "/static/assets/sportsbooks/catalog/primesports.png",
    "prophetexchange": "/static/assets/providers/prophetx.ico",
    "si": "/static/assets/sportsbooks/catalog/si.ico",
    "skybet": "/static/assets/sportsbooks/catalog/skybet.jpg",
    "sleeper": "/static/assets/dfs-books/sleeper.png",
    "sportsbet": "/static/assets/sportsbooks/catalog/sportsbet.jpg",
    "sportsbetting_ag": "/static/assets/sportsbooks/catalog/sportsbetting_ag.jpg",
    "sporttrade": "/static/assets/sportsbooks/catalog/sporttrade.jpg",
    "stake": "/static/assets/sportsbooks/catalog/stake.jpg",
    "superbook": "/static/assets/sportsbooks/catalog/superbook.jpg",
    "suprabets": "/static/assets/sportsbooks/catalog/suprabets.jpg",
    "tab": "/static/assets/sportsbooks/catalog/tab.jpg",
    "tabtouch": "/static/assets/sportsbooks/catalog/tabtouch.jpg",
    "tipico": "/static/assets/sportsbooks/catalog/tipico.jpg",
    "topsport": "/static/assets/sportsbooks/catalog/topsport.png",
    "thescorebet": "/static/assets/sportsbooks/thescore-bet.jpg",
    "underdog": "/static/assets/dfs-books/underdog.png",
    "virginbet": "/static/assets/sportsbooks/catalog/virginbet.png",
    "windcreek": "/static/assets/sportsbooks/catalog/windcreek.jpg",
    "wynnbet": "/static/assets/sportsbooks/catalog/wynnbet.jpg",
}

SPORTS_GAME_ODDS_DFS_BOOKS = frozenset(
    key
    for key, metadata in SPORTS_GAME_ODDS_BOOKMAKERS.items()
    if metadata["type"] == "dfs"
)
SPORTS_GAME_ODDS_EXCHANGE_BOOKS = frozenset(
    key
    for key, metadata in SPORTS_GAME_ODDS_BOOKMAKERS.items()
    if metadata["type"] == "exchange"
)

# DFS entries generally require multi-pick entries and therefore are not
# mathematically interchangeable with an independently executable single bet.
# They remain visible in the catalog, but are not fair-price sources or selected
# as execution venues until a payout-structure adapter exists.
SPORTS_GAME_ODDS_DEFAULT_EXECUTION_BOOKS = tuple(
    key
    for key in SPORTS_GAME_ODDS_BOOKMAKERS
    if key not in SPORTS_GAME_ODDS_DFS_BOOKS
)

# These are the only books users may blend into the fair probability for now.
# Every other subscribed book remains available for price comparison and
# execution, but cannot silently influence the de-vig consensus.
POSITIVE_EV_DEVIG_BOOKS = (
    "pinnacle",
    "circa",
    "bookmakereu",
    "fanduel",
    "betfairexchange",
)
SPORTS_GAME_ODDS_DEFAULT_SOURCE_WEIGHTS = {
    "pinnacle": 35.0,
    "circa": 28.0,
    "bookmakereu": 28.0,
    "fanduel": 2.0,
    "betfairexchange": 7.0,
}

SPORT_KEY_TO_LEAGUE_ID = {
    "baseball_mlb": "MLB",
    "basketball_nba": "NBA",
    "basketball_wnba": "WNBA",
}
LEAGUE_ID_TO_SPORT_KEY = {
    league_id: sport_key for sport_key, league_id in SPORT_KEY_TO_LEAGUE_ID.items()
}

MAIN_ODD_IDS = (
    "points-home-game-ml-home",
    "points-home-game-sp-home",
    "points-all-game-ou-over",
)
PROP_MARKET_SPECS_BY_LEAGUE = {
    "MLB": {
        "batter_hits": ("batting_hits", "game", "ou", "over"),
        "batter_total_bases": ("batting_totalBases", "game", "ou", "over"),
        "batter_home_runs": ("batting_homeRuns", "game", "ou", "over"),
        "batter_first_home_run": ("batting_firstHomeRun", "game", "yn", "yes"),
        "batter_rbis": ("batting_RBI", "game", "ou", "over"),
        "batter_runs_scored": ("points", "game", "ou", "over"),
        "batter_hits_runs_rbis": ("batting_hits+runs+rbi", "game", "ou", "over"),
        "batter_runs_rbis": ("batting_runs+rbi", "game", "ou", "over"),
        "batter_singles": ("batting_singles", "game", "ou", "over"),
        "batter_doubles": ("batting_doubles", "game", "ou", "over"),
        "batter_triples": ("batting_triples", "game", "ou", "over"),
        "batter_walks": ("batting_basesOnBalls", "game", "ou", "over"),
        "batter_strikeouts": ("batting_strikeouts", "game", "ou", "over"),
        "batter_stolen_bases": ("batting_stolenBases", "game", "ou", "over"),
        "pitcher_strikeouts": ("pitching_strikeouts", "game", "ou", "over"),
        "pitcher_hits_allowed": ("pitching_hits", "game", "ou", "over"),
        "pitcher_walks": ("pitching_basesOnBalls", "game", "ou", "over"),
        "pitcher_earned_runs": ("pitching_earnedRuns", "game", "ou", "over"),
        "pitcher_outs": ("pitching_outs", "game", "ou", "over"),
        "pitcher_pitches_thrown": ("pitching_pitchesThrown", "game", "ou", "over"),
        "pitcher_record_a_win": ("pitching_win", "game", "yn", "yes"),
    },
    "WNBA": {
        "player_points": ("points", "game", "ou", "over"),
        "player_points_q1": ("points", "1q", "ou", "over"),
        "player_rebounds": ("rebounds", "game", "ou", "over"),
        "player_rebounds_q1": ("rebounds", "1q", "ou", "over"),
        "player_assists": ("assists", "game", "ou", "over"),
        "player_assists_q1": ("assists", "1q", "ou", "over"),
        "player_threes": ("threePointersMade", "game", "ou", "over"),
        "player_blocks": ("blocks", "game", "ou", "over"),
        "player_steals": ("steals", "game", "ou", "over"),
        "player_blocks_steals": ("blocks+steals", "game", "ou", "over"),
        "player_turnovers": ("turnovers", "game", "ou", "over"),
        "player_points_rebounds_assists": ("points+rebounds+assists", "game", "ou", "over"),
        "player_points_rebounds": ("points+rebounds", "game", "ou", "over"),
        "player_points_assists": ("points+assists", "game", "ou", "over"),
        "player_rebounds_assists": ("rebounds+assists", "game", "ou", "over"),
        "player_field_goals": ("fieldGoalsMade", "game", "ou", "over"),
        "player_field_goals_attempted": ("fieldGoalsAttempted", "game", "ou", "over"),
        "player_frees_made": ("freeThrowsMade", "game", "ou", "over"),
        "player_frees_attempts": ("freeThrowsAttempted", "game", "ou", "over"),
        "player_first_basket": ("firstBasket", "game", "yn", "yes"),
        "player_double_double": ("doubleDouble", "game", "yn", "yes"),
        "player_triple_double": ("tripleDouble", "game", "yn", "yes"),
    },
}
PROP_MARKET_SPECS_BY_LEAGUE["NBA"] = dict(PROP_MARKET_SPECS_BY_LEAGUE["WNBA"])
PROP_MARKET_LOOKUP_BY_LEAGUE = {
    league_id: {
        (stat_id.casefold(), period_id.casefold(), bet_type_id.casefold()): market_key
        for market_key, (stat_id, period_id, bet_type_id, _side_id) in specs.items()
    }
    for league_id, specs in PROP_MARKET_SPECS_BY_LEAGUE.items()
}


def sports_game_odds_request_params(
    sport_keys: Iterable[str], market_keys: Iterable[str]
) -> dict[str, object] | None:
    leagues = tuple(
        dict.fromkeys(
            league_id
            for sport_key in sport_keys
            if (league_id := SPORT_KEY_TO_LEAGUE_ID.get(str(sport_key).strip()))
        )
    )
    requested = {str(key).strip().lower() for key in market_keys if str(key).strip()}
    if not leagues or not requested:
        return None

    alternate_requested = bool(
        requested & {"alternate_spreads", "alternate_totals"}
    )
    prop_specs = {
        spec
        for league_id in leagues
        for market_key, spec in PROP_MARKET_SPECS_BY_LEAGUE.get(league_id, {}).items()
        if market_key in requested
    }
    odd_ids: list[str] = []
    if requested & {"h2h", "spreads", "totals", "alternate_spreads", "alternate_totals"}:
        odd_ids.extend(MAIN_ODD_IDS)
    odd_ids.extend(
        f"{stat_id}-PLAYER_ID-{period_id}-{bet_type_id}-{side_id}"
        for stat_id, period_id, bet_type_id, side_id in sorted(prop_specs)
    )

    params: dict[str, object] = {
        "leagueID": ",".join(leagues),
        "oddsAvailable": "true",
        "started": "false",
        "includeOpposingOdds": "true",
        "includeAltLines": "true" if alternate_requested else "false",
        "limit": 100,
    }
    if odd_ids:
        params["oddID"] = ",".join(dict.fromkeys(odd_ids))
    return params


def _team_name(team: object) -> str:
    if not isinstance(team, dict):
        return ""
    names = team.get("names") or {}
    return str(
        (names.get("long") if isinstance(names, dict) else None)
        or team.get("name")
        or team.get("teamID")
        or ""
    ).strip()


def _player_names(event: dict) -> dict[str, str]:
    raw_players = event.get("players") or {}
    if isinstance(raw_players, dict):
        rows = raw_players.items()
    elif isinstance(raw_players, (list, tuple)):
        rows = ((None, player) for player in raw_players)
    else:
        rows = ()
    result: dict[str, str] = {}
    for fallback_id, player in rows:
        if not isinstance(player, dict):
            continue
        player_id = str(
            player.get("playerID") or player.get("id") or fallback_id or ""
        ).strip()
        names = player.get("names") or {}
        name = str(
            player.get("name")
            or (names.get("long") if isinstance(names, dict) else None)
            or " ".join(
                str(player.get(key) or "").strip()
                for key in ("firstName", "lastName")
            ).strip()
        ).strip()
        if player_id and name:
            result[player_id] = name
    return result


def _number(value: object) -> float | None:
    try:
        result = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return result


def _american_odds(value: object) -> int | None:
    parsed = _number(value)
    if parsed is None or parsed == 0 or not -5000 <= parsed <= 5000:
        return None
    return int(round(parsed))


def _timestamp(value: object) -> datetime | None:
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


def _market_key(
    odd: dict, *, is_alternative: bool, league_id: str
) -> str | None:
    period_id = str(odd.get("periodID") or "").lower()
    bet_type_id = str(odd.get("betTypeID") or "").lower()
    stat_id = str(odd.get("statID") or "")
    stat_entity_id = str(odd.get("statEntityID") or "").lower()
    if (
        period_id == "game"
        and stat_id == "points"
        and stat_entity_id in {"home", "away"}
    ):
        if bet_type_id == "ml" and not is_alternative:
            return "h2h"
        if bet_type_id == "sp":
            return "alternate_spreads" if is_alternative else "spreads"
    if (
        period_id == "game"
        and stat_id == "points"
        and stat_entity_id == "all"
        and bet_type_id == "ou"
    ):
        return "alternate_totals" if is_alternative else "totals"
    if not is_alternative and stat_entity_id not in {"", "all", "home", "away"}:
        return PROP_MARKET_LOOKUP_BY_LEAGUE.get(league_id, {}).get(
            (stat_id.casefold(), period_id, bet_type_id)
        )
    return None


def _outcome(
    *,
    market_key: str,
    odd: dict,
    snapshot: dict,
    home_name: str,
    away_name: str,
    player_names: dict[str, str],
    event_link: object,
    bookmaker_link: object,
) -> dict | None:
    american = _american_odds(snapshot.get("odds"))
    if american is None or snapshot.get("available") is not True:
        return None
    side_id = str(odd.get("sideID") or "").strip().lower()
    entity_id = str(odd.get("statEntityID") or "").strip()
    point = None
    description = ""
    if market_key in {"spreads", "alternate_spreads"}:
        point = _number(snapshot.get("spread"))
        name = (
            home_name
            if side_id == "home"
            else away_name if side_id == "away" else ""
        )
    elif market_key in {"totals", "alternate_totals"}:
        point = _number(snapshot.get("overUnder"))
        name = side_id.title()
    elif market_key == "h2h":
        name = (
            home_name
            if side_id == "home"
            else away_name if side_id == "away" else ""
        )
    else:
        if str(odd.get("betTypeID") or "").strip().lower() == "ou":
            point = _number(snapshot.get("overUnder"))
        name = side_id.title()
        description = player_names.get(entity_id) or str(
            odd.get("playerName") or ""
        ).strip()
        if not description:
            description = entity_id.replace("_", " ").title()
    if not name or (
        str(odd.get("betTypeID") or "").strip().lower() == "ou"
        and point is None
    ):
        return None
    result = {
        "name": name,
        "description": description,
        "price": american,
        "point": point,
        "last_update": str(snapshot.get("lastUpdatedAt") or "").strip(),
        "link": str(
            snapshot.get("deeplink") or bookmaker_link or event_link or ""
        ).strip(),
    }
    for source, target in (
        ("betLimit", "bet_limit"),
        ("maxBet", "bet_limit"),
        ("liquidity", "liquidity"),
    ):
        parsed = _number(snapshot.get(source))
        if parsed is not None:
            result[target] = parsed
    return result


def _group_key(market_key: str, outcome: dict) -> tuple:
    point = outcome.get("point")
    if market_key in {"spreads", "alternate_spreads"}:
        point = abs(float(point)) if point is not None else None
    if market_key.startswith(
        ("batter_", "pitcher_", "player_")
    ):
        return (market_key, str(outcome.get("description") or "").casefold(), point)
    return (market_key, point)


def _oldest_update(outcomes: Iterable[dict]) -> str:
    parsed = [
        (timestamp, str(outcome.get("last_update") or ""))
        for outcome in outcomes
        if (timestamp := _timestamp(outcome.get("last_update"))) is not None
    ]
    return min(
        parsed,
        default=(None, ""),
        key=lambda item: item[0]
        or datetime.max.replace(tzinfo=timezone.utc),
    )[1]


def normalize_sports_game_odds_ev_events(
    events: Iterable[dict], market_keys: Iterable[str]
) -> list[dict]:
    """Convert SportsGameOdds' byBookmaker tree into optimizer events.

    The optimizer consumes one complete, same-line market per bookmaker.  An
    incomplete side is deliberately retained only until the optimizer's
    structural validation rejects it; no opposing price is synthesized.
    """
    requested = {str(key).strip().lower() for key in market_keys if str(key).strip()}
    normalized_events: list[dict] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("eventID") or "").strip()
        league_id = str(event.get("leagueID") or "").strip().upper()
        sport_key = LEAGUE_ID_TO_SPORT_KEY.get(league_id)
        commence_time = str((event.get("status") or {}).get("startsAt") or "").strip()
        home_name = _team_name((event.get("teams") or {}).get("home"))
        away_name = _team_name((event.get("teams") or {}).get("away"))
        if not all((event_id, sport_key, commence_time, home_name, away_name)):
            continue
        players = _player_names(event)
        event_links = (event.get("links") or {}).get("bookmakers") or {}
        grouped: dict[tuple[str, str, tuple], dict[tuple, dict]] = defaultdict(dict)

        for _odd_id, odd in (event.get("odds") or {}).items():
            if not isinstance(odd, dict):
                continue
            for bookmaker_key, bookmaker_quote in (
                odd.get("byBookmaker") or {}
            ).items():
                bookmaker_key = str(bookmaker_key).strip().lower()
                if (
                    bookmaker_key not in SPORTS_GAME_ODDS_BOOKMAKERS
                    or not isinstance(bookmaker_quote, dict)
                ):
                    continue
                snapshots = [(bookmaker_quote, False)]
                snapshots.extend(
                    (snapshot, True)
                    for snapshot in bookmaker_quote.get("altLines") or ()
                    if isinstance(snapshot, dict)
                )
                for snapshot, is_alternative in snapshots:
                    market_key = _market_key(
                        odd, is_alternative=is_alternative, league_id=league_id
                    )
                    if market_key not in requested:
                        continue
                    outcome = _outcome(
                        market_key=market_key,
                        odd=odd,
                        snapshot=snapshot,
                        home_name=home_name,
                        away_name=away_name,
                        player_names=players,
                        event_link=event_links.get(bookmaker_key),
                        bookmaker_link=bookmaker_quote.get("deeplink"),
                    )
                    if outcome is None:
                        continue
                    group_key = _group_key(market_key, outcome)
                    selection_key = (
                        str(outcome.get("name") or "").casefold(),
                        str(outcome.get("description") or "").casefold(),
                        outcome.get("point"),
                    )
                    existing = grouped[(bookmaker_key, market_key, group_key)].get(
                        selection_key
                    )
                    if existing is None or (
                        _timestamp(outcome.get("last_update"))
                        or datetime.min.replace(tzinfo=timezone.utc)
                    ) > (
                        _timestamp(existing.get("last_update"))
                        or datetime.min.replace(tzinfo=timezone.utc)
                    ):
                        grouped[(bookmaker_key, market_key, group_key)][
                            selection_key
                        ] = outcome

        by_book: dict[str, list[dict]] = defaultdict(list)
        for (
            bookmaker_key,
            market_key,
            _group,
        ), outcomes_by_selection in grouped.items():
            outcomes = list(outcomes_by_selection.values())
            by_book[bookmaker_key].append(
                {
                    "key": market_key,
                    "last_update": _oldest_update(outcomes),
                    "outcomes": outcomes,
                }
            )
        bookmakers = [
            {
                "key": bookmaker_key,
                "title": SPORTS_GAME_ODDS_BOOKMAKERS[bookmaker_key]["name"],
                "logo": SPORTS_GAME_ODDS_LOGOS.get(bookmaker_key, ""),
                "link": str(event_links.get(bookmaker_key) or "").strip(),
                "markets": markets,
            }
            for bookmaker_key, markets in by_book.items()
            if markets
        ]
        if bookmakers:
            normalized_events.append(
                {
                    "id": event_id,
                    "sport_key": sport_key,
                    "sport_title": league_id,
                    "commence_time": commence_time,
                    "home_team": home_name,
                    "away_team": away_name,
                    "bookmakers": bookmakers,
                }
            )
    return normalized_events


def positive_ev_catalog_payload() -> dict:
    return {
        "catalogVersion": 3,
        "books": [
            {
                "key": key,
                "name": metadata["name"],
                "type": metadata["type"],
                "logoUrl": SPORTS_GAME_ODDS_LOGOS.get(key, ""),
                "defaultExecution": key in SPORTS_GAME_ODDS_DEFAULT_EXECUTION_BOOKS,
            }
            for key, metadata in SPORTS_GAME_ODDS_BOOKMAKERS.items()
        ],
        "devigBooks": [
            {
                "key": key,
                "name": SPORTS_GAME_ODDS_BOOKMAKERS[key]["name"],
                "logoUrl": SPORTS_GAME_ODDS_LOGOS.get(key, ""),
                "weight": SPORTS_GAME_ODDS_DEFAULT_SOURCE_WEIGHTS[key],
            }
            for key in POSITIVE_EV_DEVIG_BOOKS
        ],
        "previewOnly": False,
    }
