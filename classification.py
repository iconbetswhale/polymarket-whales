from __future__ import annotations

from dataclasses import dataclass


SPORTS_CATEGORIES = {
    "MLB",
    "NBA",
    "WNBA",
    "NFL",
    "NHL",
    "College Basketball",
    "College Football",
    "Soccer",
    "Tennis",
    "Golf",
    "MMA",
    "Boxing",
    "Other Sports",
}


@dataclass(frozen=True)
class MarketClassification:
    category: str
    league: str
    is_sports: bool
    matched_on: list[str]


def _collect_tokens(position: dict, event: dict | None) -> list[str]:
    pieces: list[str] = []

    for value in (
        position.get("title"),
        position.get("slug"),
        position.get("eventSlug"),
        position.get("outcome"),
        position.get("marketTitle"),
        (event or {}).get("title"),
        (event or {}).get("slug"),
        (event or {}).get("description"),
        ((event or {}).get("series") or [{}])[0].get("slug") if (event or {}).get("series") else None,
        ((event or {}).get("series") or [{}])[0].get("title") if (event or {}).get("series") else None,
        ((event or {}).get("sport") or {}).get("sport"),
        ((event or {}).get("sport") or {}).get("resolution"),
        ((event or {}).get("eventMetadata") or {}).get("opticOddsGameId"),
        (((event or {}).get("markets") or [{}])[0].get("sportsMarketType") if (event or {}).get("markets") else None),
    ):
        if value:
            pieces.append(str(value).lower())

    for tag in (event or {}).get("tags", []):
        pieces.append(str(tag.get("label") or "").lower())
        pieces.append(str(tag.get("slug") or "").lower())

    for team in (event or {}).get("teams", []):
        pieces.append(str(team.get("league") or "").lower())
        pieces.append(str(team.get("name") or "").lower())
        pieces.append(str(team.get("abbreviation") or "").lower())

    return [piece for piece in pieces if piece]


def classify_market(position: dict, event: dict | None = None) -> MarketClassification:
    tokens = _collect_tokens(position, event)
    joined = " ".join(tokens)
    matched_on: list[str] = []

    def match(*needles: str) -> bool:
        found = [needle for needle in needles if needle in joined]
        if found:
            matched_on.extend(found)
            return True
        return False

    if match("politics", "election", "senate", "governor", "president", "white house", "congress"):
        return MarketClassification("Politics", "Politics", False, matched_on)
    if match("crypto", "bitcoin", "ethereum", "solana", "dogecoin", "token", "airdrop"):
        return MarketClassification("Crypto", "Crypto", False, matched_on)
    if match("movie", "box office", "oscars", "grammys", "emmys", "tv", "entertainment"):
        return MarketClassification("Entertainment", "Entertainment", False, matched_on)

    if match("mlb", "baseball", "world series"):
        return MarketClassification("MLB", "MLB", True, matched_on)
    if match("wnba"):
        return MarketClassification("WNBA", "WNBA", True, matched_on)
    if match("nba"):
        return MarketClassification("NBA", "NBA", True, matched_on)
    if match("nfl", "super bowl"):
        return MarketClassification("NFL", "NFL", True, matched_on)
    if match("nhl", "stanley cup", "hockey"):
        return MarketClassification("NHL", "NHL", True, matched_on)
    if match("ncaab", "college basketball", "march madness"):
        return MarketClassification("College Basketball", "College Basketball", True, matched_on)
    if match("ncaaf", "college football", "bowl game"):
        return MarketClassification("College Football", "College Football", True, matched_on)
    if match("soccer", "fifwc", "fifa", "uefa", "premier league", "champions league", "laliga", "serie a", "bundesliga", "ligue 1", "mls"):
        return MarketClassification("Soccer", "Soccer", True, matched_on)
    if match("tennis", "wimbledon", "atp", "wta", "us open", "french open", "australian open"):
        return MarketClassification("Tennis", "Tennis", True, matched_on)
    if match("golf", "pga", "masters", "ryder cup", "open championship"):
        return MarketClassification("Golf", "Golf", True, matched_on)
    if match("ufc", "mma", "bellator", "fight night"):
        return MarketClassification("MMA", "MMA", True, matched_on)
    if match("boxing", "heavyweight", "welterweight"):
        return MarketClassification("Boxing", "Boxing", True, matched_on)
    if match("sports", "game", "spread", "moneyline", "total", "over/under"):
        return MarketClassification("Other Sports", "Other Sports", True, matched_on)

    return MarketClassification("Other", "Other", False, matched_on)


def is_sports_category(category: str) -> bool:
    return category in SPORTS_CATEGORIES
