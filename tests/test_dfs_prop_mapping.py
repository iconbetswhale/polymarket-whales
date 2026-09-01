from __future__ import annotations

from dfs_prop_mapping import (
    canonical_prop_market,
    normalized_player_name,
    resolve_prop_records,
)


def _record(
    player: str,
    *,
    book_key: str,
    market_key: str = "player_points",
    player_id: str = "",
    market_metadata: dict | None = None,
) -> dict:
    outcome = {"description": player}
    if player_id:
        outcome["player_id"] = player_id
    return {
        "event_id": "nba-event-1",
        "sport_key": "basketball_nba",
        "sport": "NBA",
        "book_key": book_key,
        "market_key": market_key,
        "market": market_metadata or {},
        "outcomes": [outcome],
        "player": player,
    }


def test_normalized_player_name_handles_accents_punctuation_and_last_first() -> None:
    assert normalized_player_name("Dončić, Luka") == "luka doncic"
    assert normalized_player_name("  Jayson   Tatum  ") == "jayson tatum"
    assert normalized_player_name("D'Angelo Russell") == "d angelo russell"
    assert normalized_player_name("A.J. Brown") == "aj brown"


def test_canonical_prop_market_resolves_aliases_and_periods() -> None:
    assert canonical_prop_market("player_three_pointers_made") == (
        "player_threes",
        "full_game",
    )
    assert canonical_prop_market("player_points_1q") == (
        "player_points",
        "first_quarter",
    )


def test_unique_initial_last_alias_resolves_to_one_canonical_prop() -> None:
    resolved = resolve_prop_records(
        [
            _record("J. Tatum", book_key="prizepicks"),
            _record("Jayson Tatum", book_key="fanduel"),
            _record("Jayson Tatum", book_key="pinnacle"),
        ]
    )

    assert {record["canonical_player_key"] for record in resolved} == {
        "jayson tatum"
    }
    assert {record["canonical_player_name"] for record in resolved} == {
        "Jayson Tatum"
    }
    assert {record["canonical_prop_id"] for record in resolved} == {
        resolved[0]["canonical_prop_id"]
    }
    assert {record["mapping_confidence"] for record in resolved} == {"EXACT"}


def test_shared_initial_last_alias_is_ambiguous_and_never_guessed() -> None:
    resolved = resolve_prop_records(
        [
            _record("J. Smith", book_key="prizepicks"),
            _record("John Smith", book_key="fanduel"),
            _record("James Smith", book_key="pinnacle"),
        ]
    )
    alias = next(record for record in resolved if record["player"] == "J. Smith")

    assert alias["mapping_confidence"] == "AMBIGUOUS"
    assert alias["mapping_reason_codes"] == ["AMBIGUOUS_INITIAL_LAST_ALIAS"]
    assert alias["canonical_player_key"] == "j smith"


def test_provider_player_id_overrides_provider_name_formatting() -> None:
    resolved = resolve_prop_records(
        [
            _record(
                "J. Tatum",
                book_key="prizepicks",
                player_id="nba-1628369",
            ),
            _record(
                "Jayson Tatum",
                book_key="pinnacle",
                player_id="nba-1628369",
            ),
        ]
    )

    assert {record["canonical_player_key"] for record in resolved} == {
        "jayson tatum"
    }
    assert {record["mapping_confidence"] for record in resolved} == {"EXACT"}
    assert "PROVIDER_PLAYER_ID_MATCH" in resolved[0]["mapping_reason_codes"]


def test_settlement_rules_are_part_of_the_canonical_prop_identity() -> None:
    resolved = resolve_prop_records(
        [
            _record(
                "Jayson Tatum",
                book_key="prizepicks",
                market_metadata={"includes_overtime": True},
            ),
            _record(
                "Jayson Tatum",
                book_key="fanduel",
                market_metadata={"includes_overtime": False},
            ),
        ]
    )

    assert len({record["settlement_rule_key"] for record in resolved}) == 2
    assert len({record["canonical_prop_id"] for record in resolved}) == 2
    assert len({record["group_key"] for record in resolved}) == 2
