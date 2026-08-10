from __future__ import annotations

import math
from statistics import mean
from typing import Any, Iterable


STRATEGY_ID = "MLB_WEIGHTED_DIRECTIONAL_V1"
STRATEGY_VERSION = "mlb-weighted-directional-v1"
SIZING_MODE = "WEIGHTED_DIRECTIONAL_CONVICTION_UNITS"
TRACKER_ENTRY_WINDOW_MINUTES = 30
POSITION_THRESHOLD_TOLERANCE_UNITS = 0.01

FORMAL_CUPCAKE = "0xb8c842bc049bf208f73354c7b037b811d741d8a4"
SOARIN = "0x84dbb7103982e3617704a2ed7d5b39691952aeeb"
PHONE_SCULPTOR = "0xf1528f12e645462c344799b62b1b421a6a4c64aa"
SPORTSMASTER = "0x32ed517a571c01b6e9adecf61ba81ca48ff2f960"
ONE_WIN_STREAK = "0xbca08c1bc204a34f2fddbe47b438b9bd42ac9705"
OX4F2 = "0x4f29e103339919c4baaea2a60195cf1c8bb27a7e"
FERRARI = "0xfe787d2da716d60e8acff57fb87eb13cd4d10319"

CONVICTION_TIERS: tuple[tuple[float, float], ...] = (
    (10.0, 1.55),
    (5.0, 1.40),
    (2.5, 1.25),
    (1.5, 1.10),
    (0.0, 1.00),
)

# These are strategy roles, not labels shown on the wallet page. Only the two
# primaries may originate an MLB play; every other wallet modifies that signal.
SHARPS: dict[str, dict[str, Any]] = {
    FORMAL_CUPCAKE: {
        "label": "Formal-Cupcake", "role": "PRIMARY", "copy_weight": 1.00,
        "minimum_units": 1.00,
    },
    PHONE_SCULPTOR: {
        "label": "phonesculptor", "role": "PRIMARY", "copy_weight": 0.85,
        "minimum_units": 0.50,
    },
    SOARIN: {
        "label": "Soarin22", "role": "CONDITIONAL", "copy_weight": 0.40,
        "minimum_units": 0.50,
    },
    SPORTSMASTER: {
        "label": "sportmaster777", "role": "CONFIRMER", "copy_weight": 0.25,
        "minimum_units": 0.25,
    },
    ONE_WIN_STREAK: {
        "label": "1winstreak", "role": "CONFIRMER", "copy_weight": 0.25,
        "minimum_units": 1.00,
    },
    OX4F2: {
        "label": "0x4f2", "role": "CONFIRMER", "copy_weight": 0.15,
        "minimum_units": 0.20,
    },
    FERRARI: {
        "label": "ferrariChampions2026", "role": "CONFIRMER", "copy_weight": 0.10,
        "minimum_units": 0.20,
    },
}


def normalize_address(value: Any) -> str:
    return str(value or "").strip().lower()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", " ").replace("-", " ")


def is_strategy_wallet(value: Any) -> bool:
    return normalize_address(value) in SHARPS


def strategy_role(value: Any) -> str | None:
    return SHARPS.get(normalize_address(value), {}).get("role")


def copy_weight(wallet_address: Any) -> float:
    return float(SHARPS.get(normalize_address(wallet_address), {}).get("copy_weight", 0.0))


def minimum_units(wallet_address: Any) -> float:
    return float(SHARPS.get(normalize_address(wallet_address), {}).get("minimum_units", 999.0))


def conviction_multiplier(relative_units: Any) -> float:
    units = max(0.0, _number(relative_units))
    for threshold, multiplier in CONVICTION_TIERS:
        if units >= threshold:
            return multiplier
    return 1.0


def _relative_unit_map(values: dict[Any, Any] | None) -> dict[str, float]:
    return {
        normalize_address(address): max(0.0, _number(units))
        for address, units in (values or {}).items()
        if is_strategy_wallet(address)
    }


def _eligible_addresses(
    wallet_addresses: Iterable[Any], relative_units: dict[str, float]
) -> list[str]:
    return sorted(
        address
        for address in {normalize_address(value) for value in wallet_addresses}
        if is_strategy_wallet(address)
        and relative_units.get(address, 1.0) + POSITION_THRESHOLD_TOLERANCE_UNITS
        >= minimum_units(address)
    )


def _confirmer_signal(addresses: Iterable[str], relative: dict[str, float]) -> float:
    return sum(
        copy_weight(address) * min(2.0, math.sqrt(max(0.0, relative.get(address, 0.0))))
        for address in addresses
        if strategy_role(address) == "CONFIRMER"
    )


def evaluate_matchup(
    wallet_addresses: Iterable[Any],
    relative_units_by_wallet: dict[Any, Any] | None = None,
    opposing_wallet_addresses: Iterable[Any] | None = None,
    opposing_relative_units_by_wallet: dict[Any, Any] | None = None,
) -> dict[str, Any]:
    agreeing_relative = _relative_unit_map(relative_units_by_wallet)
    opposing_relative = _relative_unit_map(opposing_relative_units_by_wallet)
    agreeing = _eligible_addresses(wallet_addresses, agreeing_relative)
    opposing = _eligible_addresses(opposing_wallet_addresses or [], opposing_relative)
    primaries = [address for address in agreeing if strategy_role(address) == "PRIMARY"]
    opposing_primaries = [address for address in opposing if strategy_role(address) == "PRIMARY"]
    confirming_weight = _confirmer_signal(agreeing, agreeing_relative)
    opposing_weight = _confirmer_signal(opposing, opposing_relative)

    reason = None
    if not primaries:
        reason = "MLB_WEIGHTED_REQUIRES_PRIMARY"
    elif opposing_primaries:
        reason = "MLB_WEIGHTED_PRIMARY_CONFLICT"
    elif SOARIN in opposing and opposing_relative.get(SOARIN, 0.0) >= 1.0:
        reason = "MLB_WEIGHTED_SOARIN_STRONG_VETO"
    elif opposing_weight > confirming_weight + 0.50:
        reason = "MLB_WEIGHTED_CONFIRMERS_OPPOSE"

    return {
        "qualified": reason is None,
        "reason": reason or "QUALIFIED_MLB_WEIGHTED_DIRECTIONAL",
        "agreeing_wallet_ids": agreeing,
        "opposing_wallet_ids": opposing,
        "primary_wallet_ids": primaries,
        "opposing_primary_wallet_ids": opposing_primaries,
        "conditional_wallet_ids": [a for a in agreeing if strategy_role(a) == "CONDITIONAL"],
        "confirmer_wallet_ids": [a for a in agreeing if strategy_role(a) == "CONFIRMER"],
        "confirming_portfolio_weight": round(confirming_weight, 8),
        "opposing_portfolio_weight": round(opposing_weight, 8),
        "agreeing_relative_units": agreeing_relative,
        "opposing_relative_units": opposing_relative,
    }


def recommendation_units(
    wallet_addresses: Iterable[Any],
    relative_units_by_wallet: dict[Any, Any] | None = None,
    opposing_wallet_addresses: Iterable[Any] | None = None,
    opposing_relative_units_by_wallet: dict[Any, Any] | None = None,
) -> dict[str, Any]:
    matchup = evaluate_matchup(
        wallet_addresses,
        relative_units_by_wallet,
        opposing_wallet_addresses,
        opposing_relative_units_by_wallet,
    )
    agreeing = matchup["agreeing_wallet_ids"]
    primaries = matchup["primary_wallet_ids"]
    relative = matchup["agreeing_relative_units"]
    adjusted_primary_weights = {
        address: copy_weight(address) * conviction_multiplier(relative.get(address, 1.0))
        for address in primaries
    }
    consensus = 1.0
    if len(primaries) >= 2:
        consensus += 0.25
    if SOARIN in agreeing:
        consensus += 0.15
    if SOARIN in matchup["opposing_wallet_ids"]:
        consensus -= 0.15
    portfolio_multiplier = max(
        0.50,
        1.0
        + 0.12 * matchup["confirming_portfolio_weight"]
        - 0.15 * matchup["opposing_portfolio_weight"],
    )
    consensus *= portfolio_multiplier
    raw_units = mean(adjusted_primary_weights.values()) * consensus if primaries else 0.0
    units = min(3.0, max(0.25, raw_units)) if matchup["qualified"] else 0.0
    return {
        **matchup,
        "units": round(units, 8),
        "sizing_mode": SIZING_MODE,
        "agreeing_count": len(agreeing),
        "average_copy_weight": round(mean(copy_weight(a) for a in primaries), 8) if primaries else 0.0,
        "average_adjusted_copy_weight": round(mean(adjusted_primary_weights.values()), 8) if primaries else 0.0,
        "consensus_multiplier": round(consensus, 8),
        "portfolio_multiplier": round(portfolio_multiplier, 8),
        "conviction_multipliers": {
            address: conviction_multiplier(relative.get(address, 1.0)) for address in primaries
        },
        "relative_units_by_wallet": {address: round(relative.get(address, 0.0), 8) for address in agreeing},
        "wallet_addresses": agreeing,
    }


def confidence_score(
    wallet_addresses: Iterable[Any],
    relative_units_by_wallet: dict[Any, Any] | None = None,
    opposing_wallet_addresses: Iterable[Any] | None = None,
    opposing_relative_units_by_wallet: dict[Any, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    sizing = recommendation_units(
        wallet_addresses,
        relative_units_by_wallet,
        opposing_wallet_addresses,
        opposing_relative_units_by_wallet,
    )
    primaries = sizing["primary_wallet_ids"]
    if not sizing["qualified"]:
        score, band = 0, sizing["reason"]
    elif len(primaries) >= 2:
        score, band = 96, "Two-primary agreement"
    elif primaries == [FORMAL_CUPCAKE]:
        score, band = 91, "Formal-Cupcake primary"
    else:
        score, band = 87, "PhoneSculptor primary"
    if score:
        if SOARIN in sizing["agreeing_wallet_ids"]:
            score += 2
        score += min(2, int(sizing["confirming_portfolio_weight"] / 0.25))
        if SOARIN in sizing["opposing_wallet_ids"]:
            score -= 2
        score -= min(3, int(sizing["opposing_portfolio_weight"] / 0.25))
        score = max(1, min(99, score))
    return score, {
        "architecture": "mlb_weighted_directional_v1",
        "consensus_band": band,
        "raw_sharp_count": len(sizing["agreeing_wallet_ids"]),
        "primary_wallet_ids": primaries,
        "conditional_wallet_ids": sizing["conditional_wallet_ids"],
        "confirmer_wallet_ids": sizing["confirmer_wallet_ids"],
        "opposing_wallet_ids": sizing["opposing_wallet_ids"],
        "confirming_portfolio_weight": sizing["confirming_portfolio_weight"],
        "opposing_portfolio_weight": sizing["opposing_portfolio_weight"],
        "stake_independent": False,
        "explanation": "Confidence follows primary quality, agreement, Soarin direction, and netted confirmer balance. Stake is calculated separately from primary conviction.",
    }


def strategy_wallet_positions(positions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for position in positions:
        address = normalize_address(position.get("wallet_address"))
        if not is_strategy_wallet(address):
            continue
        minimum = minimum_units(address)
        selected.append({
            **position,
            "minimum_position_units": minimum,
            "actionable_position_units": minimum,
        })
    return selected


def main_mlb_strategy_positions(positions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select full-game MLB moneylines only, matching the weighted simulation."""
    accepted: list[dict[str, Any]] = []
    for position in strategy_wallet_positions(positions):
        category = " ".join(
            _text(position.get(field))
            for field in ("canonical_league_id", "canonical_category_id", "league", "category")
        )
        if "mlb" not in category and "baseball" not in category:
            continue
        market_text = " ".join(
            _text(position.get(field))
            for field in ("sports_market_type", "market_slug", "market_title")
        )
        if any(token in market_text for token in ("first five", "first 5", " f5 ", "inning", "spread", "run line", "total", "o/u")):
            continue
        event_slug = str(position.get("event_slug") or "").strip().lower()
        market_slug = str(position.get("market_slug") or "").strip().lower()
        if (event_slug and market_slug and event_slug == market_slug) or any(
            token in market_text for token in ("moneyline", "money line", " h2h ", "winner")
        ):
            accepted.append(position)
    return accepted
