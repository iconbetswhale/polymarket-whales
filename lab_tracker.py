from __future__ import annotations

import hashlib
import json
import math
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator


LAB_TRACKER_GLOBAL_USER_ID = "iconlabs-labtracker-global"
LAB_TRACKER_STAKE = 100.0
LAB_TRACKER_QUALIFICATION_SECONDS = 5.0
LAB_TRACKER_SOURCES = frozenset(
    {"positive_ev", "sharp_money", "prediction_traders"}
)
PREDICTION_TRADER_PROVIDERS = {
    "novig": {
        "name": "NoVIG",
        "logo": "/static/assets/sportsbooks/novig.png",
        "aliases": ("novig",),
    },
    "prophetx": {
        "name": "ProphetX",
        "logo": "/static/assets/sportsbooks/prophetx.png",
        "aliases": ("prophetx",),
    },
    "polymarket": {
        "name": "Polymarket",
        "logo": "/static/assets/sportsbooks/polymarket.png",
        "aliases": ("polymarket",),
    },
    "kalshi": {
        "name": "Kalshi",
        "logo": "/static/assets/sportsbooks/kalshi.png",
        "aliases": ("kalshi",),
    },
    "4cx": {
        "name": "4CX",
        "logo": "/static/assets/providers/4cx.png",
        "aliases": ("4cx", "fourcx"),
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def _number(value: object, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _canonical(value: object) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def _american_profit(stake: float, odds: int) -> float:
    return stake * (odds / 100.0 if odds > 0 else 100.0 / abs(odds))


def _identity(*parts: object) -> str:
    digest = hashlib.sha256("|".join(str(part or "") for part in parts).encode()).hexdigest()
    return f"lab-{digest[:32]}"


def _provider_key(*values: object) -> str | None:
    for value in values:
        token = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
        if not token:
            continue
        for key, provider in PREDICTION_TRADER_PROVIDERS.items():
            if any(
                token == alias or token.endswith(alias)
                for alias in provider["aliases"]
            ):
                return key
    return None


def _probability_from_american(odds: int) -> float | None:
    if odds == 0:
        return None
    return (
        100.0 / (odds + 100.0)
        if odds > 0
        else abs(odds) / (abs(odds) + 100.0)
    )


def _american_from_probability(probability: float) -> int:
    if probability < 0.5:
        return int(round(100.0 * (1.0 - probability) / probability))
    return -int(round(100.0 * probability / (1.0 - probability)))


def _entry_terms(snapshot: dict) -> tuple[float | None, int | None]:
    display = str(snapshot.get("provider_display_odds") or "").strip().lower()
    displayed_american: int | None = None
    displayed_probability: float | None = None
    if display.endswith("c") or display.endswith("¢"):
        displayed_probability = (_number(display[:-1]) or 0) / 100.0
    elif re.fullmatch(r"[+-]?\d+", display):
        displayed_american = int(display)
        displayed_probability = _probability_from_american(displayed_american)

    probability = next(
        (
            value
            for value in (
                _number(snapshot.get("provider_entry_price")),
                _number(snapshot.get("effective_entry_price")),
                _number(snapshot.get("current_executable_entry_price")),
                displayed_probability,
            )
            if value is not None and 0 < value < 1
        ),
        None,
    )
    if probability is None:
        return None, displayed_american
    return probability, displayed_american or _american_from_probability(probability)


def _settlement_terms(
    status: object, entry_probability: float, stake: float
) -> tuple[str, str | None, float | None]:
    normalized = str(status or "unresolved").lower()
    if normalized == "won":
        return "graded", "won", stake * ((1.0 / entry_probability) - 1.0)
    if normalized == "lost":
        return "graded", "lost", -stake
    if normalized in {"push", "void", "canceled"}:
        return "graded", "push", 0.0
    return "pending", None, None


DEMO_SPORTSBOOKS = (
    ("betmgm", "BetMGM", "/static/assets/sportsbooks/betmgm.png"),
    ("draftkings", "DraftKings", "/static/assets/sportsbooks/draftkings.png"),
    ("fanduel", "FanDuel", "/static/assets/sportsbooks/fanduel.png"),
    ("caesars", "Caesars", "/static/assets/sportsbooks/caesars.png"),
    ("hard-rock-bet", "Hard Rock Bet", "/static/assets/sportsbooks/hard-rock-bet.png"),
    ("fanatics", "Fanatics", "/static/assets/sportsbooks/fanatics.png"),
    ("betrivers", "BetRivers", "/static/assets/sportsbooks/betrivers.png"),
    ("bet365", "bet365", "/static/assets/sportsbooks/bet365.png"),
    ("espn-bet", "ESPN BET", "/static/assets/sportsbooks/espn-bet.png"),
    ("thescore-bet", "theScore Bet", "/static/assets/sportsbooks/thescore-bet.jpg"),
    ("bovada", "Bovada", "/static/assets/sportsbooks/bovada.png"),
    ("betonline", "BetOnline", "/static/assets/sportsbooks/betonline.png"),
    ("fliff", "Fliff", "/static/assets/sportsbooks/fliff.png"),
    ("rebet", "Rebet", "/static/assets/sportsbooks/rebet.png"),
    ("polymarket", "Polymarket", "/static/assets/sportsbooks/polymarket.png"),
    ("novig", "NoVIG", "/static/assets/sportsbooks/novig.png"),
    ("prophetx", "ProphetX", "/static/assets/sportsbooks/prophetx.png"),
    ("kalshi", "Kalshi", "/static/assets/sportsbooks/kalshi.png"),
    ("4cx", "4CX", "/static/assets/providers/4cx.png"),
)

DEMO_PREDICTION_SPORTSBOOKS = tuple(
    (key, provider["name"], provider["logo"])
    for key, provider in PREDICTION_TRADER_PROVIDERS.items()
)

DEMO_MARKETS = (
    ("h2h", "Moneyline", "MLB", "Boston Red Sox vs New York Yankees", "New York Yankees"),
    ("spreads", "Spread", "NBA", "Boston Celtics vs New York Knicks", "Boston Celtics -4.5"),
    ("totals", "Game Total", "NFL", "Baltimore Ravens vs Buffalo Bills", "Under 47.5"),
    ("team_totals", "Team Total", "NBA", "Miami Heat vs Orlando Magic", "Miami Heat Over 108.5"),
    ("player_points", "Player Points", "NBA", "Oklahoma City Thunder vs Denver Nuggets", "Shai Gilgeous-Alexander Over 31.5"),
    ("player_rebounds", "Player Rebounds", "NBA", "Los Angeles Lakers vs Golden State Warriors", "LeBron James Over 7.5"),
    ("player_assists", "Player Assists", "NBA", "San Antonio Spurs vs Houston Rockets", "Victor Wembanyama Over 4.5"),
    ("player_pra", "Player PRA", "NBA", "Dallas Mavericks vs Minnesota Timberwolves", "Luka Doncic Over 46.5"),
    ("player_threes", "Player Made Threes", "WNBA", "New York Liberty vs Las Vegas Aces", "Sabrina Ionescu Over 3.5"),
    ("pitcher_strikeouts", "Pitcher Strikeouts", "MLB", "Seattle Mariners vs Houston Astros", "Logan Gilbert Over 6.5"),
    ("batter_hits", "Batter Hits", "MLB", "Philadelphia Phillies vs New York Mets", "Juan Soto Over 0.5"),
    ("total_bases", "Total Bases", "MLB", "Chicago Cubs vs Milwaukee Brewers", "Pete Crow-Armstrong Over 1.5"),
    ("first_five", "First Five Innings", "MLB", "Atlanta Braves vs Miami Marlins", "Atlanta Braves -0.5"),
    ("first_half_spread", "First Half Spread", "NCAAB", "Duke vs North Carolina", "Duke -1.5"),
    ("player_shots", "Player Shots on Goal", "NHL", "New York Rangers vs Boston Bruins", "Artemi Panarin Over 3.5"),
    ("soccer_h2h", "Three-way Moneyline", "MLS", "Inter Miami vs Atlanta United", "Inter Miami"),
    ("match_h2h", "Match Moneyline", "ATP", "Jannik Sinner vs Carlos Alcaraz", "Jannik Sinner"),
    ("match_totals", "Match Total Games", "WTA", "Aryna Sabalenka vs Coco Gauff", "Over 21.5"),
    ("college_spread", "College Football Spread", "NCAAF", "Ohio State vs Michigan", "Ohio State -6.5"),
)


def _market_category(row: dict) -> str:
    market_key = str(row.get("market_key") or "").lower()
    market_label = str(row.get("market_label") or "").lower()
    combined = re.sub(r"[^a-z0-9]+", " ", f"{market_key} {market_label}").strip()
    compact = combined.replace(" ", "")

    if "team total" in combined or "teamtotal" in compact:
        return "Team Total"
    if market_key.startswith(("player_", "pitcher_", "batter_")) or market_key == "total_bases" or any(
        term in combined
        for term in (
            "player prop",
            "player points",
            "player rebounds",
            "player assists",
            "player outs",
            "player hits",
            "player strikeouts",
            "player made",
        )
    ):
        return "Player Prop"
    if "first five" in combined or market_key == "first_five":
        return "First 5"
    if "spread" in combined or "handicap" in combined:
        return "Spread"
    if market_key in {"h2h", "ml", "moneyline", "match_h2h"} or "moneyline" in combined:
        return "Moneyline"
    if "total" in combined or market_key in {"totals", "match_totals"}:
        return "Total"
    if "to advance" in combined or "to qualify" in combined:
        return "To Advance"
    if "yes no" in combined or "prediction market" in combined:
        return "Yes / No"
    return "Other"


def _dashboard_from_rows(
    rows: list[dict], *, scope: str, source: str | None, window: str, demo_only: bool = False
) -> dict:
    now = _now()
    if source:
        rows = [row for row in rows if row.get("source") == source]
    cutoffs = {
        "yesterday": now - timedelta(days=1),
        "7d": now - timedelta(days=7),
        "30d": now - timedelta(days=30),
    }
    cutoff = cutoffs.get(window)
    if cutoff:
        rows = [
            row
            for row in rows
            if (_parse_time(row.get("created_at")) or now) >= cutoff
        ]
    graded = [row for row in rows if row.get("status") == "graded"]
    wins = sum(row.get("result") == "won" for row in graded)
    losses = sum(row.get("result") == "lost" for row in graded)
    pushes = sum(row.get("result") == "push" for row in graded)
    profit = round(sum(float(row.get("profit_loss") or 0) for row in graded), 2)
    risked = sum(
        float(row.get("stake") or 0)
        for row in graded
        if row.get("result") in {"won", "lost"}
    )

    def breakdown(
        key: str,
        name_key: str | None = None,
        logo_key: str | None = None,
        resolver=None,
    ) -> list[dict]:
        groups: dict[str, dict] = {}
        for row in graded:
            resolved_name = resolver(row) if resolver else None
            group_key = str(resolved_name or row.get(key) or "Other")
            item = groups.setdefault(
                group_key,
                {
                    "key": group_key,
                    "name": resolved_name or row.get(name_key or key) or group_key,
                    "logo": row.get(logo_key or "") or "",
                    "wins": 0,
                    "losses": 0,
                    "profit": 0.0,
                },
            )
            item["wins"] += int(row.get("result") == "won")
            item["losses"] += int(row.get("result") == "lost")
            item["profit"] += float(row.get("profit_loss") or 0)
        for item in groups.values():
            item["profit"] = round(item["profit"], 2)
        return sorted(groups.values(), key=lambda item: item["profit"], reverse=True)

    curve = []
    cumulative = 0.0
    for row in sorted(graded, key=lambda item: item.get("graded_at") or ""):
        cumulative += float(row.get("profit_loss") or 0)
        curve.append({"at": row.get("graded_at"), "profit": round(cumulative, 2)})
    return {
        "summary": {
            "profit": profit,
            "units": round(profit / LAB_TRACKER_STAKE, 2),
            "roi": round((profit / risked * 100) if risked else 0.0, 2),
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "winRate": round((wins / (wins + losses) * 100) if wins + losses else 0.0, 1),
            "tracked": len(rows),
            "open": sum(row.get("status") == "pending" for row in rows),
            "stake": LAB_TRACKER_STAKE,
        },
        "curve": curve,
        "sportsbooks": breakdown("sportsbook_key", "sportsbook_name", "sportsbook_logo"),
        "leagues": breakdown("league"),
        "markets": breakdown("market_key", "market_label", resolver=_market_category),
        "lastGraded": sorted(
            graded, key=lambda row: row.get("graded_at") or "", reverse=True
        )[:5],
        "openBets": sorted(
            (row for row in rows if row.get("status") == "pending"),
            key=lambda row: row.get("created_at") or "",
            reverse=True,
        )[:20],
        "scope": scope,
        "source": source or "all",
        "window": window,
        "unitValue": LAB_TRACKER_STAKE,
        "demoOnly": demo_only,
    }


def demo_dashboard(
    *,
    scope: str,
    source: str | None,
    window: str,
    prediction_records: Iterable[dict] | None = None,
) -> dict:
    """Return deterministic preview rows without touching tracker persistence."""
    now = _now()
    results = ("won", "won", "lost", "won", "push", "lost", "won")
    odds_cycle = (-110, 115, -105, 128, -120, 105, -115, 135)
    rows: list[dict] = []
    for index in range(54):
        row_source = ("positive_ev", "sharp_money")[index % 2]
        books = DEMO_SPORTSBOOKS
        book_key, book_name, book_logo = books[index % len(books)]
        market_key, market_label, league, event_title, selection = DEMO_MARKETS[index % len(DEMO_MARKETS)]
        result = results[index % len(results)]
        odds = odds_cycle[index % len(odds_cycle)]
        graded_at = now - timedelta(hours=(index * 2.55) + 2)
        pnl = 0.0
        if result == "won":
            pnl = _american_profit(LAB_TRACKER_STAKE, odds)
        elif result == "lost":
            pnl = -LAB_TRACKER_STAKE
        row = {
            "bet_id": f"demo-graded-{index + 1}",
            "source": row_source,
            "league": league,
            "event_title": event_title,
            "commence_time": (graded_at - timedelta(hours=3)).isoformat(),
            "market_key": market_key,
            "market_label": market_label,
            "selection": selection,
            "sportsbook_key": book_key,
            "sportsbook_name": book_name,
            "sportsbook_logo": book_logo,
            "entry_american_odds": odds,
            "stake": LAB_TRACKER_STAKE,
            "status": "graded",
            "result": result,
            "profit_loss": round(pnl, 2),
            "graded_at": graded_at.isoformat(),
            "created_at": (graded_at - timedelta(hours=5)).isoformat(),
            "demo_personal": index % 4 == 0,
        }
        rows.append(row)
    for index in range(8):
        row_source = ("positive_ev", "sharp_money")[index % 2]
        books = DEMO_SPORTSBOOKS
        book_key, book_name, book_logo = books[(index + 5) % len(books)]
        market_key, market_label, league, event_title, selection = DEMO_MARKETS[(index + 7) % len(DEMO_MARKETS)]
        created_at = now - timedelta(minutes=(index * 19) + 7)
        rows.append(
            {
                "bet_id": f"demo-open-{index + 1}",
                "source": row_source,
                "league": league,
                "event_title": event_title,
                "commence_time": (now + timedelta(hours=index + 2)).isoformat(),
                "market_key": market_key,
                "market_label": market_label,
                "selection": selection,
                "sportsbook_key": book_key,
                "sportsbook_name": book_name,
                "sportsbook_logo": book_logo,
                "entry_american_odds": odds_cycle[(index + 3) % len(odds_cycle)],
                "stake": LAB_TRACKER_STAKE,
                "status": "pending",
                "result": None,
                "profit_loss": None,
                "graded_at": None,
                "created_at": created_at.isoformat(),
                "demo_personal": index % 3 == 0,
            }
        )
    if scope == "personal":
        rows = [row for row in rows if row.get("demo_personal")]
    elif source in {None, "prediction_traders"} and prediction_records is not None:
        rows.extend(normalize_model_tracker_records(prediction_records))
    return _dashboard_from_rows(
        rows,
        scope=scope,
        source=source,
        window=window,
        demo_only=source != "prediction_traders",
    )


class LabTrackerStore:
    """Portable persistence for the global LabTracker and user-owned copies."""

    def __init__(self, tracker_database) -> None:
        self.database = tracker_database
        self.postgres = bool(getattr(tracker_database, "user_store", None))
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator:
        target = self.database.user_store if self.postgres else self.database
        with target.connection() as conn:
            yield conn

    def sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.postgres else statement

    def execute(self, conn, statement: str, params: tuple = ()):
        return conn.execute(self.sql(statement), params)

    def initialize(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS lab_tracker_candidates (
                candidate_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                qualified_at TEXT,
                snapshot_json TEXT NOT NULL
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_lab_candidates_source
            ON lab_tracker_candidates(source, source_id)
            """,
            """
            CREATE TABLE IF NOT EXISTS lab_tracker_bets (
                bet_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                tracker_scope TEXT NOT NULL,
                user_id TEXT NOT NULL,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                sport_key TEXT,
                league TEXT,
                event_id TEXT,
                event_title TEXT NOT NULL,
                home_team TEXT,
                away_team TEXT,
                commence_time TEXT,
                market_key TEXT NOT NULL,
                market_label TEXT NOT NULL,
                selection TEXT NOT NULL,
                market_line DOUBLE PRECISION,
                sportsbook_key TEXT NOT NULL,
                sportsbook_name TEXT NOT NULL,
                sportsbook_logo TEXT,
                entry_american_odds INTEGER NOT NULL,
                entry_decimal_odds DOUBLE PRECISION NOT NULL,
                ev_percent DOUBLE PRECISION,
                stake DOUBLE PRECISION NOT NULL,
                units DOUBLE PRECISION NOT NULL,
                status TEXT NOT NULL,
                result TEXT,
                profit_loss DOUBLE PRECISION,
                graded_at TEXT,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(tracker_scope, user_id, candidate_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_lab_bets_scope_time
            ON lab_tracker_bets(tracker_scope, user_id, created_at DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_lab_bets_status_start
            ON lab_tracker_bets(status, commence_time)
            """,
        )
        with self.connection() as conn:
            for statement in statements:
                self.execute(conn, statement)

    def observe(self, source: str, records: Iterable[dict], observed_at: datetime | None = None) -> dict:
        now = (observed_at or _now()).astimezone(timezone.utc)
        now_text = now.isoformat()
        qualified = 0
        observed = 0
        with self.connection() as conn:
            for record in records:
                source_id = str(record.get("source_id") or "").strip()
                if not source_id:
                    continue
                observed += 1
                candidate_id = _identity(source, source_id)
                existing = self.execute(
                    conn,
                    "SELECT * FROM lab_tracker_candidates WHERE candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
                snapshot_json = json.dumps(record, sort_keys=True, separators=(",", ":"))
                if existing is None:
                    self.execute(
                        conn,
                        """
                        INSERT INTO lab_tracker_candidates(
                            candidate_id, source, source_id, first_seen_at,
                            last_seen_at, qualified_at, snapshot_json
                        ) VALUES (?, ?, ?, ?, ?, NULL, ?)
                        """,
                        (candidate_id, source, source_id, now_text, now_text, snapshot_json),
                    )
                    continue
                row = dict(existing)
                qualified_at = row.get("qualified_at")
                first_seen = _parse_time(row.get("first_seen_at")) or now
                if qualified_at is None and (now - first_seen).total_seconds() >= LAB_TRACKER_QUALIFICATION_SECONDS:
                    qualified_at = now_text
                    qualified += self._insert_signal_bet(conn, candidate_id, source, record, now_text)
                self.execute(
                    conn,
                    """
                    UPDATE lab_tracker_candidates
                    SET last_seen_at = ?, qualified_at = ?, snapshot_json = ?
                    WHERE candidate_id = ?
                    """,
                    (now_text, qualified_at, snapshot_json, candidate_id),
                )
        return {"observed": observed, "qualified": qualified}

    def _insert_signal_bet(self, conn, candidate_id: str, source: str, record: dict, now_text: str) -> int:
        bet_id = _identity("signal", LAB_TRACKER_GLOBAL_USER_ID, candidate_id)
        cursor = self.execute(
            conn,
            """
            INSERT INTO lab_tracker_bets(
                bet_id, candidate_id, tracker_scope, user_id, source, source_id,
                sport_key, league, event_id, event_title, home_team, away_team,
                commence_time, market_key, market_label, selection, market_line,
                sportsbook_key, sportsbook_name, sportsbook_logo,
                entry_american_odds, entry_decimal_odds, ev_percent, stake, units,
                status, result, profit_loss, graded_at, snapshot_json, created_at, updated_at
            ) VALUES (
                ?, ?, 'signal', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, 1.0, 'pending', NULL, NULL, NULL, ?, ?, ?
            )
            ON CONFLICT(tracker_scope, user_id, candidate_id) DO NOTHING
            """,
            (
                bet_id, candidate_id, LAB_TRACKER_GLOBAL_USER_ID, source,
                record["source_id"], record.get("sport_key"), record.get("league"),
                record.get("event_id"), record["event_title"], record.get("home_team"),
                record.get("away_team"), record.get("commence_time"), record["market_key"],
                record["market_label"], record["selection"], record.get("market_line"),
                record["sportsbook_key"], record["sportsbook_name"],
                record.get("sportsbook_logo"), int(record["entry_american_odds"]),
                float(record["entry_decimal_odds"]), record.get("ev_percent"),
                LAB_TRACKER_STAKE, json.dumps(record, sort_keys=True, separators=(",", ":")),
                now_text, now_text,
            ),
        )
        return max(0, int(cursor.rowcount or 0))

    def add_personal(self, user_id: str, signal_bet_id: str) -> dict | None:
        now_text = _now().isoformat()
        with self.connection() as conn:
            source = self.execute(
                conn,
                "SELECT * FROM lab_tracker_bets WHERE bet_id = ? AND tracker_scope = 'signal'",
                (signal_bet_id,),
            ).fetchone()
            if source is None:
                return None
            row = dict(source)
            bet_id = _identity("personal", user_id, row["candidate_id"])
            self.execute(
                conn,
                """
                INSERT INTO lab_tracker_bets(
                    bet_id, candidate_id, tracker_scope, user_id, source, source_id,
                    sport_key, league, event_id, event_title, home_team, away_team,
                    commence_time, market_key, market_label, selection, market_line,
                    sportsbook_key, sportsbook_name, sportsbook_logo,
                    entry_american_odds, entry_decimal_odds, ev_percent, stake, units,
                    status, result, profit_loss, graded_at, snapshot_json, created_at, updated_at
                ) SELECT ?, candidate_id, 'personal', ?, source, source_id, sport_key,
                    league, event_id, event_title, home_team, away_team, commence_time,
                    market_key, market_label, selection, market_line, sportsbook_key,
                    sportsbook_name, sportsbook_logo, entry_american_odds,
                    entry_decimal_odds, ev_percent, stake, units, status, result,
                    profit_loss, graded_at, snapshot_json, ?, ?
                FROM lab_tracker_bets WHERE bet_id = ?
                ON CONFLICT(tracker_scope, user_id, candidate_id) DO NOTHING
                """,
                (bet_id, user_id, now_text, now_text, signal_bet_id),
            )
            created = self.execute(conn, "SELECT * FROM lab_tracker_bets WHERE bet_id = ?", (bet_id,)).fetchone()
        return dict(created) if created else None

    def pending(self) -> list[dict]:
        with self.connection() as conn:
            rows = self.execute(
                conn,
                "SELECT * FROM lab_tracker_bets WHERE status = 'pending' ORDER BY commence_time ASC",
            ).fetchall()
        return [dict(row) for row in rows]

    def settle(self, bet_id: str, result: str, profit_loss: float, graded_at: str) -> None:
        with self.connection() as conn:
            self.execute(
                conn,
                """
                UPDATE lab_tracker_bets SET status = 'graded', result = ?, profit_loss = ?,
                    graded_at = ?, updated_at = ? WHERE bet_id = ? AND status = 'pending'
                """,
                (result, profit_loss, graded_at, graded_at, bet_id),
            )

    def rows(self, scope: str, user_id: str, source: str | None = None) -> list[dict]:
        clauses = ["tracker_scope = ?", "user_id = ?"]
        params: list[object] = [scope, user_id]
        if source:
            clauses.append("source = ?")
            params.append(source)
        with self.connection() as conn:
            rows = self.execute(
                conn,
                f"SELECT * FROM lab_tracker_bets WHERE {' AND '.join(clauses)} ORDER BY created_at ASC",
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]


def normalize_positive_ev(rows: Iterable[dict]) -> list[dict]:
    records = []
    for row in rows:
        best = row.get("bestQuote") or {}
        odds = _number(best.get("topPriceAmericanOdds", best.get("americanOdds")))
        if not row.get("id") or odds in (None, 0):
            continue
        decimal = _number(best.get("effectiveDecimal"))
        if not decimal or decimal <= 1:
            decimal = 1 + (odds / 100 if odds > 0 else 100 / abs(odds))
        book_key = str(best.get("bookKey") or "unknown").lower()
        source_id = f"{row['id']}::{book_key}"
        records.append(
            {
                "source_id": source_id,
                "sport_key": row.get("sportKey"),
                "league": row.get("league"),
                "event_id": row.get("eventId"),
                "event_title": row.get("eventTitle") or "Unknown event",
                "home_team": row.get("homeTeam"),
                "away_team": row.get("awayTeam"),
                "commence_time": row.get("commenceTime"),
                "market_key": row.get("marketKey") or "unknown",
                "market_label": row.get("marketLabel") or "Market",
                "selection": row.get("selection") or "Selection",
                "market_line": best.get("point"),
                "sportsbook_key": book_key,
                "sportsbook_name": best.get("bookName") or book_key.title(),
                "sportsbook_logo": best.get("logoUrl") or "",
                "entry_american_odds": int(round(odds)),
                "entry_decimal_odds": float(decimal),
                "ev_percent": _number(row.get("evPercent")),
                "raw": row,
            }
        )
    return records


def normalize_sharp_money(rows: Iterable[dict]) -> list[dict]:
    league_sports = {
        "MLB": "baseball_mlb", "NBA": "basketball_nba", "WNBA": "basketball_wnba",
        "NFL": "americanfootball_nfl", "NCAAF": "americanfootball_ncaaf",
        "NCAAB": "basketball_ncaab", "NHL": "icehockey_nhl",
        "MLS": "soccer_usa_mls", "EPL": "soccer_epl",
    }
    records = []
    for row in rows:
        odds = _number(row.get("americanOdds"))
        market = row.get("market") or {}
        if not row.get("id") or odds in (None, 0):
            continue
        decimal = _number(row.get("decimalOdds"))
        if not decimal or decimal <= 1:
            decimal = 1 + (odds / 100 if odds > 0 else 100 / abs(odds))
        league = str(row.get("league") or "Other")
        kind = str(market.get("kind") or "unknown")
        records.append(
            {
                "source_id": str(row["id"]),
                "sport_key": league_sports.get(league.upper()),
                "league": league,
                "event_id": str(row["id"]).split(":")[1] if ":" in str(row["id"]) else None,
                "event_title": row.get("event") or "Unknown event",
                "home_team": row.get("homeTeam"),
                "away_team": row.get("awayTeam"),
                "commence_time": row.get("startsAt"),
                "market_key": {"moneyline": "h2h", "spread": "spreads", "game_total": "totals"}.get(kind, kind),
                "market_label": market.get("name") or kind.replace("_", " ").title(),
                "selection": row.get("selection") or "Selection",
                "market_line": market.get("line"),
                "sportsbook_key": str(row.get("providerKey") or "prophetx").lower(),
                "sportsbook_name": row.get("provider") or "ProphetX",
                "sportsbook_logo": row.get("providerLogo") or "",
                "entry_american_odds": int(round(odds)),
                "entry_decimal_odds": float(decimal),
                "ev_percent": None,
                "raw": row,
            }
        )
    return records


def normalize_model_tracker_records(rows: Iterable[dict]) -> list[dict]:
    records: list[dict] = []
    for row in rows:
        snapshot = row.get("snapshot") or {}
        provider_key = _provider_key(
            snapshot.get("provider_key"),
            snapshot.get("sportsbook"),
            snapshot.get("entry_price_source"),
        )
        if provider_key is None:
            continue
        probability, american_odds = _entry_terms(snapshot)
        if probability is None or american_odds is None:
            continue
        provider = PREDICTION_TRADER_PROVIDERS[provider_key]
        status, result, profit_loss = _settlement_terms(
            row.get("status"), probability, LAB_TRACKER_STAKE
        )
        source_id = str(
            row.get("dedupe_key") or snapshot.get("dedupe_key") or ""
        ).strip()
        if not source_id:
            continue
        records.append(
            {
                "bet_id": _identity("prediction_traders", source_id),
                "candidate_id": source_id,
                "tracker_scope": "signal",
                "user_id": LAB_TRACKER_GLOBAL_USER_ID,
                "source": "prediction_traders",
                "source_id": source_id,
                "sport_key": snapshot.get("canonical_sport_id")
                or snapshot.get("category"),
                "league": snapshot.get("league")
                or snapshot.get("canonical_league_id")
                or snapshot.get("category")
                or "Other",
                "event_id": snapshot.get("canonical_event_id"),
                "event_title": snapshot.get("event_title") or "Unknown event",
                "home_team": snapshot.get("home_team"),
                "away_team": snapshot.get("away_team"),
                "commence_time": snapshot.get("event_start_time"),
                "market_key": snapshot.get("sports_market_type")
                or snapshot.get("canonical_market_id")
                or "prediction_market",
                "market_label": snapshot.get("market_title") or "Prediction market",
                "selection": snapshot.get("recommended_side") or "Selection",
                "market_line": snapshot.get("market_line"),
                "sportsbook_key": provider_key,
                "sportsbook_name": provider["name"],
                "sportsbook_logo": provider["logo"],
                "entry_american_odds": american_odds,
                "entry_decimal_odds": 1.0 / probability,
                "ev_percent": (
                    (_number(snapshot.get("calculated_edge")) or 0.0) * 100.0
                    if snapshot.get("calculated_edge") is not None
                    else None
                ),
                "stake": LAB_TRACKER_STAKE,
                "units": 1.0,
                "status": status,
                "result": result,
                "profit_loss": (
                    round(profit_loss, 2) if profit_loss is not None else None
                ),
                "graded_at": row.get("settled_at") if status == "graded" else None,
                "snapshot_json": json.dumps(
                    snapshot, sort_keys=True, separators=(",", ":")
                ),
                "created_at": row.get("created_at")
                or snapshot.get("recommendation_timestamp")
                or _now().isoformat(),
                "updated_at": row.get("updated_at")
                or row.get("created_at")
                or _now().isoformat(),
            }
        )
    return records


def normalize_personal_fills(rows: Iterable[dict]) -> list[dict]:
    records: list[dict] = []
    for row in rows:
        probability = _number(row.get("entry_price"))
        if probability is None or not 0 < probability < 1:
            continue
        sportsbook_name = " ".join(
            str(row.get("sportsbook") or "Polymarket").split()
        )
        sportsbook_key = (
            re.sub(r"[^a-z0-9]+", "", sportsbook_name.lower()) or "other"
        )
        status = str(row.get("status") or "unresolved").lower()
        total_paid = float(
            _number(row.get("total_paid"), _number(row.get("position_cost"), 0.0)) or 0.0
        )
        shares = float(_number(row.get("shares"), 0.0) or 0.0)
        if status == "won":
            tracker_status, result, profit_loss = "graded", "won", shares - total_paid
        elif status == "lost":
            tracker_status, result, profit_loss = "graded", "lost", -total_paid
        elif status in {"push", "void", "canceled"}:
            tracker_status, result, profit_loss = "graded", "push", 0.0
        else:
            tracker_status, result, profit_loss = "pending", None, None
        source_id = str(row.get("fill_id") or "").strip()
        if not source_id:
            continue
        records.append(
            {
                "bet_id": _identity("personal_fill", source_id),
                "candidate_id": source_id,
                "tracker_scope": "personal",
                "user_id": row.get("user_id"),
                "source": "personal",
                "source_id": source_id,
                "sport_key": None,
                "league": "Other",
                "event_id": row.get("canonical_event_id"),
                "event_title": row.get("event_title") or "Manual bet",
                "home_team": None,
                "away_team": None,
                "commence_time": row.get("event_start_time"),
                "market_key": row.get("canonical_market_id") or "personal_market",
                "market_label": row.get("market_title") or "Market",
                "selection": row.get("selection") or "Selection",
                "market_line": row.get("market_line"),
                "sportsbook_key": sportsbook_key,
                "sportsbook_name": sportsbook_name,
                "sportsbook_logo": "",
                "entry_american_odds": _american_from_probability(probability),
                "entry_decimal_odds": 1.0 / probability,
                "ev_percent": None,
                "stake": total_paid,
                "units": total_paid / LAB_TRACKER_STAKE,
                "status": tracker_status,
                "result": result,
                "profit_loss": (
                    round(profit_loss, 2) if profit_loss is not None else None
                ),
                "graded_at": row.get("settled_at") if tracker_status == "graded" else None,
                "snapshot_json": "{}",
                "created_at": row.get("created_at") or _now().isoformat(),
                "updated_at": row.get("updated_at")
                or row.get("created_at")
                or _now().isoformat(),
            }
        )
    return records


def _merge_rows(*groups: Iterable[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for group in groups:
        for row in group:
            identity = row.get("bet_id") or _identity(
                row.get("source"), row.get("source_id")
            )
            merged[str(identity)] = row
    return sorted(merged.values(), key=lambda row: str(row.get("created_at") or ""))


def _score_map(event: dict) -> dict[str, float]:
    return {
        _canonical(score.get("name")): float(score.get("score"))
        for score in event.get("scores") or []
        if isinstance(score, dict) and _number(score.get("score")) is not None
    }


def _matching_score_event(bet: dict, events: Iterable[dict]) -> dict | None:
    event_id = str(bet.get("event_id") or "")
    for event in events:
        if event.get("completed") and event_id and str(event.get("id") or "") == event_id:
            return event
    # Positive EV rows carry the authoritative Odds API event id. Falling
    # back to team names could settle a doubleheader against the wrong game.
    if event_id and bet.get("source") == "positive_ev":
        return None
    home = _canonical(bet.get("home_team"))
    away = _canonical(bet.get("away_team"))
    start = _parse_time(bet.get("commence_time"))
    for event in events:
        if not event.get("completed"):
            continue
        if {_canonical(event.get("home_team")), _canonical(event.get("away_team"))} != {home, away}:
            continue
        event_start = _parse_time(event.get("commence_time"))
        if start and event_start and abs((start - event_start).total_seconds()) > 6 * 3600:
            continue
        return event
    return None


def grade_bet(bet: dict, score_event: dict) -> str | None:
    scores = _score_map(score_event)
    home_key = _canonical(bet.get("home_team"))
    away_key = _canonical(bet.get("away_team"))
    if home_key not in scores or away_key not in scores:
        return None
    home_score, away_score = scores[home_key], scores[away_key]
    selection = _canonical(bet.get("selection"))
    market = str(bet.get("market_key") or "").lower()
    if market == "h2h":
        if selection in {"draw", "tie"}:
            return "won" if home_score == away_score else "lost"
        selected_home = home_key and home_key in selection
        selected_away = away_key and away_key in selection
        if not selected_home and not selected_away:
            return None
        if home_score == away_score:
            return "push"
        return "won" if (selected_home and home_score > away_score) or (selected_away and away_score > home_score) else "lost"
    line = _number(bet.get("market_line"))
    if line is None:
        matches = re.findall(r"[-+]?\d+(?:\.\d+)?", str(bet.get("selection") or ""))
        line = float(matches[-1]) if matches else None
    if market in {"spreads", "alternate_spreads"} and line is not None:
        selected_home = home_key and home_key in selection
        selected_away = away_key and away_key in selection
        if not selected_home and not selected_away:
            return None
        margin = (home_score - away_score if selected_home else away_score - home_score) + line
        return "won" if margin > 0 else "lost" if margin < 0 else "push"
    if market in {"totals", "alternate_totals"} and line is not None:
        total = home_score + away_score
        if total == line:
            return "push"
        if selection.startswith("over"):
            return "won" if total > line else "lost"
        if selection.startswith("under"):
            return "won" if total < line else "lost"
    return None


class LabTrackerService:
    def __init__(
        self, tracker_database, model_tracker_user_id: str | None = None
    ) -> None:
        self.database = tracker_database
        self.model_tracker_user_id = model_tracker_user_id
        self.store = LabTrackerStore(tracker_database)

    def observe_positive_ev(self, rows: Iterable[dict], observed_at: datetime | None = None) -> dict:
        return self.store.observe("positive_ev", normalize_positive_ev(rows), observed_at)

    def observe_sharp_money(self, rows: Iterable[dict], observed_at: datetime | None = None) -> dict:
        return self.store.observe("sharp_money", normalize_sharp_money(rows), observed_at)

    def add_personal(self, user_id: str, signal_bet_id: str) -> dict | None:
        return self.store.add_personal(user_id, signal_bet_id)

    def settle(self, score_events: Iterable[dict]) -> dict:
        events = list(score_events)
        settled = 0
        graded_at = _now().isoformat()
        for bet in self.store.pending():
            event = _matching_score_event(bet, events)
            if event is None:
                continue
            result = grade_bet(bet, event)
            if result is None:
                continue
            stake = float(bet.get("stake") or LAB_TRACKER_STAKE)
            if result == "won":
                pnl = _american_profit(stake, int(bet["entry_american_odds"]))
            elif result == "lost":
                pnl = -stake
            else:
                pnl = 0.0
            self.store.settle(bet["bet_id"], result, round(pnl, 2), graded_at)
            settled += 1
        return {"settled": settled, "scoreEvents": len(events)}

    def dashboard(self, *, scope: str, user_id: str, source: str | None, window: str) -> dict:
        if scope == "personal":
            rows = _merge_rows(
                self.store.rows(scope, user_id),
                normalize_personal_fills(
                    self.database.get_personal_bet_fills(user_id)
                ),
            )
            source = None
        else:
            signal_rows = (
                []
                if source == "prediction_traders"
                else self.store.rows(scope, user_id, source)
            )
            prediction_rows = []
            if source in {None, "prediction_traders"} and self.model_tracker_user_id:
                prediction_rows = normalize_model_tracker_records(
                    self.database.get_tracker_records(self.model_tracker_user_id)
                )
            rows = _merge_rows(signal_rows, prediction_rows)
        return _dashboard_from_rows(
            rows, scope=scope, source=source, window=window, demo_only=False
        )
