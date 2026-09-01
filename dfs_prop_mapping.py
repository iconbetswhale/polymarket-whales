from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from typing import Iterable


MARKET_ALIASES = {
    "player_three_pointers": "player_threes",
    "player_three_pointers_made": "player_threes",
    "player_3_pointers": "player_threes",
    "player_free_throws_made": "player_frees_made",
    "player_free_throws_attempted": "player_frees_attempts",
    "pitcher_walks_allowed": "pitcher_walks",
    "pitcher_outs_recorded": "pitcher_outs",
}

PERIOD_MARKETS = {
    "player_points_q1": ("player_points", "first_quarter"),
    "player_points_1q": ("player_points", "first_quarter"),
    "player_first_quarter_points": ("player_points", "first_quarter"),
    "player_rebounds_q1": ("player_rebounds", "first_quarter"),
    "player_rebounds_1q": ("player_rebounds", "first_quarter"),
    "player_first_quarter_rebounds": ("player_rebounds", "first_quarter"),
    "player_assists_q1": ("player_assists", "first_quarter"),
    "player_assists_1q": ("player_assists", "first_quarter"),
    "player_first_quarter_assists": ("player_assists", "first_quarter"),
}

PLAYER_ID_FIELDS = (
    "player_id",
    "playerId",
    "athlete_id",
    "athleteId",
    "participant_id",
    "participantId",
    "entity_id",
    "entityId",
    "entity_name_std",
    "entityNameStd",
)

SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})
NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def _slug(value: object) -> str:
    return NON_ALPHANUMERIC.sub("-", str(value or "").casefold()).strip("-")


def _compact(value: object) -> str:
    return " ".join(str(value or "").split())


def normalized_player_name(value: object) -> str:
    raw = _compact(value)
    if not raw:
        return ""
    if "," in raw:
        last, first = (part.strip() for part in raw.split(",", 1))
        if first and last:
            raw = f"{first} {last}"
    ascii_name = unicodedata.normalize("NFKD", raw).encode(
        "ascii", "ignore"
    ).decode("ascii")
    parts = NON_ALPHANUMERIC.sub(" ", ascii_name.casefold()).split()
    leading_initials = 0
    for part in parts[:-1]:
        if len(part) != 1:
            break
        leading_initials += 1
    if leading_initials > 1:
        parts = ["".join(parts[:leading_initials]), *parts[leading_initials:]]
    return " ".join(parts)


def canonical_prop_market(market_key: object) -> tuple[str, str]:
    raw = _slug(market_key).replace("-", "_")
    if raw in PERIOD_MARKETS:
        return PERIOD_MARKETS[raw]
    return MARKET_ALIASES.get(raw, raw), "full_game"


def _player_id(record: dict) -> str:
    for source in (record.get("market") or {}, *(record.get("outcomes") or [])):
        if not isinstance(source, dict):
            continue
        for key in PLAYER_ID_FIELDS:
            value = _compact(source.get(key))
            if value:
                return value.casefold()
    return ""


def _tokens(name: str) -> tuple[str, ...]:
    return tuple(part for part in name.split() if part)


def _without_suffix(name: str) -> str:
    parts = list(_tokens(name))
    if parts and parts[-1] in SUFFIXES:
        parts.pop()
    return " ".join(parts)


def _is_abbreviated(name: str) -> bool:
    parts = _tokens(name)
    return bool(parts) and len(parts[0]) == 1


def _initial_last_match(alias: str, candidate: str) -> bool:
    alias_parts = _tokens(_without_suffix(alias))
    candidate_parts = _tokens(_without_suffix(candidate))
    if len(alias_parts) < 2 or len(candidate_parts) < 2:
        return False
    if len(alias_parts[0]) != 1 or candidate_parts[0][0] != alias_parts[0]:
        return False
    tail = alias_parts[1:]
    return len(candidate_parts) > len(tail) and candidate_parts[-len(tail) :] == tail


def _preferred_display(records: list[dict], target_name: str) -> str:
    candidates = [
        _compact(record.get("player"))
        for record in records
        if normalized_player_name(record.get("player")) == target_name
        or _without_suffix(normalized_player_name(record.get("player")))
        == _without_suffix(target_name)
    ]
    if not candidates:
        return " ".join(part.title() for part in target_name.split())
    return min(
        candidates,
        key=lambda name: (
            _is_abbreviated(normalized_player_name(name)),
            "," in name,
            -len(_tokens(normalized_player_name(name))),
            -len(name),
            name.casefold(),
        ),
    )


def _optional_bool(source: dict, *keys: str) -> bool | None:
    for key in keys:
        if key not in source:
            continue
        value = source.get(key)
        if isinstance(value, bool):
            return value
        normalized = str(value or "").strip().casefold()
        if normalized in {"true", "1", "yes", "included"}:
            return True
        if normalized in {"false", "0", "no", "excluded"}:
            return False
    return None


def settlement_rule_key(record: dict) -> str:
    market = record.get("market") or {}
    explicit = next(
        (
            _compact(market.get(key))
            for key in (
                "settlement_rule_key",
                "settlementRuleKey",
                "rules_key",
                "rulesKey",
            )
            if _compact(market.get(key))
        ),
        "",
    )
    if explicit:
        return f"explicit:{_slug(explicit)}"
    overtime = _optional_bool(
        market,
        "includes_overtime",
        "includesOvertime",
        "overtime_included",
        "overtimeIncluded",
    )
    overtime_rule = (
        "overtime_included"
        if overtime is True
        else "regulation_only"
        if overtime is False
        else "provider_standard"
    )
    push_rule = _slug(
        market.get("push_rule")
        or market.get("pushRule")
        or market.get("tie_rule")
        or market.get("tieRule")
        or "provider-standard"
    )
    return ":".join(
        (
            _slug(record.get("sport_key") or record.get("sport")),
            str(record.get("canonical_stat_key") or ""),
            str(record.get("period") or "full_game"),
            overtime_rule,
            push_rule,
        )
    )


def _stable_prop_id(*parts: object) -> str:
    payload = json.dumps(parts, ensure_ascii=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"prop_{digest}"


def resolve_prop_records(records: Iterable[dict]) -> list[dict]:
    """Resolve provider prop labels without ever guessing ambiguous players."""

    prepared: list[dict] = []
    for source in records:
        record = dict(source)
        stat_key, period = canonical_prop_market(record.get("market_key"))
        record["canonical_stat_key"] = stat_key
        record["period"] = period
        record["normalized_player_name"] = normalized_player_name(
            record.get("player")
        )
        record["provider_player_id"] = _player_id(record)
        prepared.append(record)

    scopes: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, record in enumerate(prepared):
        scopes[
            (
                str(record.get("event_id") or ""),
                str(record.get("canonical_stat_key") or ""),
                str(record.get("period") or ""),
            )
        ].append(index)

    for indexes in scopes.values():
        scope_records = [prepared[index] for index in indexes]
        names = {
            record["normalized_player_name"]
            for record in scope_records
            if record["normalized_player_name"]
        }
        full_names = {name for name in names if not _is_abbreviated(name)}
        suffix_clusters: dict[str, set[str]] = defaultdict(set)
        for name in full_names:
            suffix_clusters[_without_suffix(name)].add(name)
        ids: dict[str, set[str]] = defaultdict(set)
        for record in scope_records:
            if record["provider_player_id"] and record["normalized_player_name"]:
                ids[record["provider_player_id"]].add(
                    record["normalized_player_name"]
                )

        for index in indexes:
            record = prepared[index]
            name = record["normalized_player_name"]
            target = name
            confidence = "EXACT"
            reasons = ["EXACT_NORMALIZED_NAME"]
            provider_id = record["provider_player_id"]

            if not name:
                confidence = "AMBIGUOUS"
                reasons = ["PLAYER_NAME_MISSING"]
            elif provider_id and len(ids.get(provider_id, ())) > 1:
                id_names = ids[provider_id]
                target = min(
                    id_names,
                    key=lambda candidate: (
                        _is_abbreviated(candidate),
                        -len(_tokens(candidate)),
                        -len(candidate),
                    ),
                )
                reasons = ["PROVIDER_PLAYER_ID_MATCH"]
            elif _is_abbreviated(name):
                matches = {
                    candidate
                    for candidate in full_names
                    if _initial_last_match(name, candidate)
                }
                if len(matches) == 1:
                    target = next(iter(matches))
                    reasons = ["UNIQUE_INITIAL_LAST_ALIAS"]
                elif len(matches) > 1:
                    confidence = "AMBIGUOUS"
                    reasons = ["AMBIGUOUS_INITIAL_LAST_ALIAS"]
            else:
                cluster = suffix_clusters.get(_without_suffix(name), set())
                suffix_variants = {
                    _tokens(candidate)[-1]
                    for candidate in cluster
                    if _tokens(candidate)
                    and _tokens(candidate)[-1] in SUFFIXES
                }
                if len(cluster) == 2 and len(suffix_variants) == 1:
                    target = max(cluster, key=lambda candidate: len(candidate))
                    reasons = ["UNIQUE_SUFFIX_ALIAS"]

            canonical_display = _preferred_display(scope_records, target)
            rule_key = settlement_rule_key(record)
            player_key = target or f"missing-{index}"
            canonical_id = _stable_prop_id(
                record.get("event_id"),
                record.get("canonical_stat_key"),
                record.get("period"),
                player_key,
                rule_key,
            )
            record.update(
                {
                    "canonical_player_key": player_key,
                    "canonical_player_name": canonical_display,
                    "mapping_confidence": confidence,
                    "mapping_reason_codes": reasons,
                    "settlement_rule_key": rule_key,
                    "canonical_prop_id": canonical_id,
                    "group_key": (
                        str(record.get("event_id") or ""),
                        str(record.get("canonical_stat_key") or ""),
                        str(record.get("period") or ""),
                        player_key,
                        rule_key,
                    ),
                }
            )
    return prepared
