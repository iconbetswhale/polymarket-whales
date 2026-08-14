from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from market_quotes import NormalizedMarketQuote


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def meaningful_quote_hash(quote: NormalizedMarketQuote) -> str:
    """Hash only provider facts whose change is analytically meaningful."""
    payload = {
        "provider": quote.provider,
        "provider_selection_id": quote.provider_selection_id,
        "american_odds": quote.american_odds,
        "decimal_odds": round(quote.decimal_odds, 10),
        "implied_probability": round(quote.implied_probability, 10),
        "available_liquidity": quote.available_liquidity,
        "market_limit": quote.market_limit,
        "mapping_confidence": quote.mapping_confidence,
        "settlement_rule_key": quote.settlement_rule_key,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _snapshot_hash(meaningful_hash: str, received_at: str, checkpoint: bool) -> str:
    # Include observation time for both changes and checkpoints. A market may
    # legitimately return to a previously observed price; that reversal is a
    # new historical observation and must not collide with its earlier state.
    raw = f"{meaningful_hash}|{received_at}|{'checkpoint' if checkpoint else 'change'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _row_value(row: Any, key: str, index: int) -> Any:
    """Read sqlite tuples/Rows and psycopg dict rows without coupling stores."""
    if row is None:
        return None
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return row[index]


def record_quotes(
    conn: Any,
    quotes: Iterable[NormalizedMarketQuote],
    *,
    dialect: str,
    checkpoint_seconds: int = 900,
) -> dict[str, int]:
    placeholder = "%s" if dialect == "postgres" else "?"
    received = changed = checkpoints = 0
    for quote in quotes:
        received += 1
        payload = quote.to_dict()
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        meaningful_hash = meaningful_quote_hash(quote)
        current = conn.execute(
            f"SELECT meaningful_hash, received_timestamp FROM normalized_market_quotes "
            f"WHERE provider = {placeholder} AND provider_selection_id = {placeholder}",
            (quote.provider, quote.provider_selection_id),
        ).fetchone()
        prior_hash = _row_value(current, "meaningful_hash", 0)
        # The current-quote row is refreshed on every observation, including
        # unchanged ones.  Checkpoint cadence must therefore be measured from
        # the last persisted history row, not from the last poll.
        last_snapshot = conn.execute(
            f"SELECT received_timestamp FROM normalized_market_quote_history "
            f"WHERE provider = {placeholder} AND provider_selection_id = {placeholder} "
            f"ORDER BY received_timestamp DESC LIMIT 1",
            (quote.provider, quote.provider_selection_id),
        ).fetchone()
        prior_time = _parse_time(_row_value(last_snapshot, "received_timestamp", 0))
        elapsed = (
            (quote.received_timestamp - prior_time).total_seconds()
            if prior_time is not None
            else None
        )
        material_change = prior_hash != meaningful_hash
        checkpoint = bool(
            not material_change
            and elapsed is not None
            and checkpoint_seconds > 0
            and elapsed >= checkpoint_seconds
        )
        if material_change or checkpoint:
            received_at = quote.received_timestamp.isoformat()
            values = (
                _snapshot_hash(meaningful_hash, received_at, checkpoint),
                meaningful_hash,
                quote.provider,
                quote.provider_event_id,
                quote.provider_market_id,
                quote.provider_selection_id,
                quote.event_id,
                quote.market_id,
                quote.selection_id,
                quote.sport,
                quote.league,
                quote.event_name,
                quote.home_team,
                quote.away_team,
                quote.start_time.isoformat(),
                quote.market_type,
                quote.market_family,
                quote.period,
                quote.is_alternate,
                quote.line,
                quote.selection,
                quote.side,
                quote.american_odds,
                quote.decimal_odds,
                quote.implied_probability,
                quote.quote_timestamp.isoformat(),
                received_at,
                quote.available_liquidity,
                quote.market_limit,
                quote.mapping_confidence,
                quote.settlement_rule_key,
                checkpoint,
                serialized,
            )
            columns = (
                "snapshot_hash, meaningful_hash, provider, provider_event_id, provider_market_id, "
                "provider_selection_id, event_id, market_id, selection_id, sport, league, "
                "event_name, home_team, away_team, start_time, market_type, market_family, "
                "period, is_alternate, line, selection, side, american_odds, "
                "decimal_odds, implied_probability, quote_timestamp, received_timestamp, "
                "available_liquidity, market_limit, mapping_confidence, settlement_rule_key, "
                "checkpoint_only, quote_json"
            )
            marks = ", ".join([placeholder] * len(values))
            conflict = "ON CONFLICT(snapshot_hash) DO NOTHING" if dialect == "postgres" else ""
            verb = "INSERT" if dialect == "postgres" else "INSERT OR IGNORE"
            conn.execute(
                f"{verb} INTO normalized_market_quote_history({columns}) VALUES ({marks}) {conflict}",
                values,
            )
            changed += int(material_change)
            checkpoints += int(checkpoint)

        current_values = (
            quote.provider,
            quote.provider_selection_id,
            quote.event_id,
            quote.market_id,
            quote.selection_id,
            quote.quote_timestamp.isoformat(),
            quote.received_timestamp.isoformat(),
            meaningful_hash,
            serialized,
        )
        if dialect == "postgres":
            conn.execute(
                """
                INSERT INTO normalized_market_quotes(
                    provider, provider_selection_id, event_id, market_id, selection_id,
                    quote_timestamp, received_timestamp, meaningful_hash, quote_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(provider, provider_selection_id) DO UPDATE SET
                    event_id=excluded.event_id, market_id=excluded.market_id,
                    selection_id=excluded.selection_id, quote_timestamp=excluded.quote_timestamp,
                    received_timestamp=excluded.received_timestamp,
                    meaningful_hash=excluded.meaningful_hash, quote_json=excluded.quote_json
                """,
                current_values,
            )
        else:
            conn.execute(
                """
                INSERT INTO normalized_market_quotes(
                    provider, provider_selection_id, event_id, market_id, selection_id,
                    quote_timestamp, received_timestamp, meaningful_hash, quote_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, provider_selection_id) DO UPDATE SET
                    event_id=excluded.event_id, market_id=excluded.market_id,
                    selection_id=excluded.selection_id, quote_timestamp=excluded.quote_timestamp,
                    received_timestamp=excluded.received_timestamp,
                    meaningful_hash=excluded.meaningful_hash, quote_json=excluded.quote_json
                """,
                current_values,
            )
    return {"quotes_received": received, "material_snapshots": changed, "checkpoints": checkpoints}


def list_history(
    conn: Any,
    *,
    dialect: str,
    provider: str | None = None,
    event_id: str | None = None,
    market_id: str | None = None,
    selection_id: str | None = None,
    limit: int = 500,
) -> list[dict]:
    placeholder = "%s" if dialect == "postgres" else "?"
    clauses: list[str] = []
    params: list[object] = []
    for column, value in (
        ("provider", provider), ("event_id", event_id),
        ("market_id", market_id), ("selection_id", selection_id),
    ):
        if value:
            clauses.append(f"{column} = {placeholder}")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(int(limit), 5000)))
    rows = conn.execute(
        f"SELECT quote_json, checkpoint_only FROM normalized_market_quote_history "
        f"{where} ORDER BY received_timestamp DESC LIMIT {placeholder}",
        tuple(params),
    ).fetchall()
    result = []
    for row in rows:
        item = json.loads(_row_value(row, "quote_json", 0) or "{}")
        item["checkpoint_only"] = bool(_row_value(row, "checkpoint_only", 1))
        result.append(item)
    return result
