from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


STRATEGY_ID = "SPECIALIST_WEIGHTED_MULTI_SPORT_V5"
STRATEGY_VERSION = "specialist-weighted-multi-sport-v5"
SIZING_MODE = "VALIDATED_SPECIALIST_UNITS"
TRACKER_ENTRY_WINDOW_MINUTES = 30
POSITION_THRESHOLD_TOLERANCE_UNITS = 0.01
MINIMUM_TENNIS_ENTRY_PRICE = 0.35
MAXIMUM_OPPOSING_EXPOSURE_RATIO = 0.10

BAGWELL = "0x9c76cdb43fb46454da005fbc82047a64a18ec926"
LILYBAEUM = "0x01c78f8873c0c86d6b6b92ff627e3802237ee995"
DABOSSHOGG = "0x6157d529ae129fe08f22a27ed42e741d2eaa9fb4"
FORMAL_CUPCAKE = "0xb8c842bc049bf208f73354c7b037b811d741d8a4"
BREAK_THE_BANK = "0xf0318c32136c2db7fec88b84869aee6a1106c80c"
PORTLY_DERIVATION = "0x8a3ab8120807bd64a3de48695110e390fa2ceb9a"
EVHUNTER = "0x8ce7eb8a3ad1d6907b24368865c8487a68fb3150"

TENNIS_SHARPS = {
    BAGWELL: {"label": "Bagwell306", "base_unit_usd": 875.0},
    LILYBAEUM: {"label": "Lilybaeum", "base_unit_usd": 575.0},
    DABOSSHOGG: {"label": "DaBossHogg", "base_unit_usd": 5050.0},
    EVHUNTER: {"label": "EVhunter69", "base_unit_usd": 575.0},
}
WNBA_SPREAD_SHARPS = {
    FORMAL_CUPCAKE: {"label": "Formal-Cupcake", "base_unit_usd": 1300.0}
}
SOCCER_ML_SHARPS = {
    BREAK_THE_BANK: {"label": "BreakTheBank", "base_unit_usd": 116150.0}
}
NBA_SHARPS = {
    PORTLY_DERIVATION: {"label": "Portly-Derivation", "base_unit_usd": 10200.0}
}
MMA_SHARPS = {
    PORTLY_DERIVATION: {"label": "Portly-Derivation", "base_unit_usd": 8400.0}
}
SHARPS = {
    **TENNIS_SHARPS,
    **WNBA_SPREAD_SHARPS,
    **SOCCER_ML_SHARPS,
    **NBA_SHARPS,
    **MMA_SHARPS,
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


def _event_key(position: dict[str, Any]) -> str:
    return str(
        position.get("event_slug")
        or position.get("event_id")
        or position.get("event_title")
        or ""
    ).strip().lower()


def _market_volume(position: dict[str, Any]) -> float:
    return max(
        _number(position.get("market_volume")),
        _number(position.get("volume")),
        _number(position.get("liquidity")),
    )


def _category_text(position: dict[str, Any]) -> str:
    return " ".join(
        _text(position.get(field))
        for field in (
            "canonical_league_id",
            "canonical_category_id",
            "league",
            "category",
        )
    )


def _market_text(position: dict[str, Any]) -> str:
    return " ".join(
        _text(position.get(field))
        for field in ("sports_market_type", "market_slug", "market_title")
    )


def _relative_units(position: dict[str, Any]) -> float:
    return max(
        0.0,
        _number(
            position.get("signal_units")
            if position.get("signal_units") is not None
            else position.get("estimated_units")
        ),
    )


def _is_clean_directional(position: dict[str, Any]) -> bool:
    ratio = _number(position.get("opposing_exposure_ratio"), 0.0)
    status = str(
        position.get("two_sided_status")
        or position.get("wallet_hedge_status")
        or "CLEAN_DIRECTIONAL"
    ).upper()
    return (
        ratio < MAXIMUM_OPPOSING_EXPOSURE_RATIO
        and status
        in {
            "CLEAN_DIRECTIONAL",
            "DIRECTIONAL_AFTER_MARKET_NETTING",
            "UNHEDGED",
        }
    )


def _meets_one_unit(position: dict[str, Any]) -> bool:
    return _relative_units(position) + POSITION_THRESHOLD_TOLERANCE_UNITS >= 1.0


def _tennis_family(position: dict[str, Any]) -> str | None:
    text = _market_text(position)
    if any(
        token in text
        for token in (
            "first set",
            "set 1",
            "set-1",
            "game handicap",
            "first game",
        )
    ):
        return None
    event_slug = str(position.get("event_slug") or "").strip().lower()
    market_slug = str(position.get("market_slug") or "").strip().lower()
    if event_slug and market_slug and event_slug == market_slug:
        return "moneyline"
    if any(token in text for token in ("moneyline", "money line", "winner")):
        return "moneyline"
    if any(token in text for token in ("tennis set handicap", "set handicap", "spread")):
        return "spread"
    if any(token in text for token in ("tennis match totals", "match total", "total")):
        return "total"
    return None


def _select_main_markets(
    rows: Iterable[dict[str, Any]], family_getter: Any
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        family = family_getter(row)
        if not family:
            continue
        condition = str(
            row.get("condition_id")
            or row.get("market_slug")
            or row.get("market_title")
            or ""
        ).strip().lower()
        grouped[(_event_key(row), family)][condition].append(row)
    selected: list[dict[str, Any]] = []
    for conditions in grouped.values():
        chosen = max(
            conditions.values(),
            key=lambda group: max((_market_volume(row) for row in group), default=0.0),
        )
        selected.extend(chosen)
    return selected


def _wnba_spread_family(position: dict[str, Any]) -> str | None:
    text = _market_text(position)
    if "spread" not in text:
        return None
    if any(
        token in text
        for token in (
            "first half",
            "second half",
            "1st half",
            "2nd half",
            "quarter",
        )
    ):
        return None
    return "spread"


def _soccer_moneyline_family(position: dict[str, Any]) -> str | None:
    text = _market_text(position)
    if any(
        token in text
        for token in (
            "spread",
            "handicap",
            "total",
            "o/u",
            "exact score",
            "both teams",
            "first half",
            "second half",
        )
    ):
        return None
    event_slug = str(position.get("event_slug") or "").strip().lower()
    market_slug = str(position.get("market_slug") or "").strip().lower()
    if event_slug and market_slug and event_slug == market_slug:
        return "moneyline"
    if any(token in text for token in ("moneyline", "money line", "winner", " win on ", " draw")):
        return "moneyline"
    return None


def _nba_main_family(position: dict[str, Any]) -> str | None:
    text = _market_text(position)
    if any(
        token in text
        for token in (
            "first half",
            "second half",
            "1st half",
            "2nd half",
            "quarter",
            "team total",
            "player",
        )
    ):
        return None
    if "spread" in text or "handicap" in text:
        return "spread"
    if any(token in text for token in ("total", "o/u", "over/under")):
        return None
    event_slug = str(position.get("event_slug") or "").strip().lower()
    market_slug = str(position.get("market_slug") or "").strip().lower()
    if event_slug and market_slug and event_slug == market_slug:
        return "moneyline"
    if any(token in text for token in ("moneyline", "money line", "winner")):
        return "moneyline"
    return None


def _mma_moneyline_family(position: dict[str, Any]) -> str | None:
    text = _market_text(position)
    if any(
        token in text
        for token in (
            "method",
            "round",
            "decision",
            "knockout",
            "submission",
            "go the distance",
            "total",
            "spread",
        )
    ):
        return None
    event_slug = str(position.get("event_slug") or "").strip().lower()
    market_slug = str(position.get("market_slug") or "").strip().lower()
    if event_slug and market_slug and event_slug == market_slug:
        return "moneyline"
    if any(token in text for token in ("moneyline", "money line", "winner", "fight winner")):
        return "moneyline"
    return None


def specialist_strategy_positions(
    positions: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return only validated sport-and-market specialist signals."""
    tennis: list[dict[str, Any]] = []
    wnba: list[dict[str, Any]] = []
    soccer: list[dict[str, Any]] = []
    nba: list[dict[str, Any]] = []
    mma: list[dict[str, Any]] = []
    for position in positions:
        address = normalize_address(position.get("wallet_address"))
        category = _category_text(position)
        if not _is_clean_directional(position) or not _meets_one_unit(position):
            continue
        if address in TENNIS_SHARPS and "tennis" in category:
            entry = _number(
                position.get("executable_ask_price")
                if position.get("executable_ask_price") is not None
                else position.get("current_price")
            )
            if entry >= MINIMUM_TENNIS_ENTRY_PRICE:
                tennis.append(position)
            continue
        if address in WNBA_SPREAD_SHARPS and "wnba" in category:
            wnba.append(position)
            continue
        if address in SOCCER_ML_SHARPS and "soccer" in category:
            soccer.append(position)
            continue
        if address in NBA_SHARPS and "nba" in category:
            nba.append(position)
            continue
        if address in MMA_SHARPS and any(token in category for token in ("mma", "ufc")):
            mma.append(position)
    return [
        *_select_main_markets(tennis, _tennis_family),
        *_select_main_markets(wnba, _wnba_spread_family),
        *_select_main_markets(soccer, _soccer_moneyline_family),
        *_select_main_markets(nba, _nba_main_family),
        *_select_main_markets(mma, _mma_moneyline_family),
    ]


def recommendation_units(
    wallet_addresses: Iterable[Any],
    relative_units_by_wallet: dict[Any, Any] | None,
    category: Any,
    market_type: Any = None,
) -> dict[str, Any]:
    addresses = sorted(
        {
            normalize_address(address)
            for address in wallet_addresses
            if normalize_address(address) in SHARPS
        }
    )
    relative = {
        normalize_address(address): max(0.0, _number(units))
        for address, units in (relative_units_by_wallet or {}).items()
    }
    category_text = _text(category)
    market_text = _text(market_type)
    if "tennis" in category_text:
        eligible = [address for address in addresses if address in TENNIS_SHARPS]
        legacy = [address for address in eligible if address != EVHUNTER]
        if len(legacy) >= 3:
            units = 3.0
        elif len(legacy) == 2:
            units = 2.0
        elif legacy == [BAGWELL]:
            units = 1.0
        elif legacy == [LILYBAEUM]:
            units = 0.75
        elif legacy == [DABOSSHOGG]:
            units = 1.0
        else:
            units = 0.0
        if EVHUNTER in eligible:
            units += 0.5
        rule = (
            "Bagwell 1.00u; Lilybaeum 0.75u; DaBossHogg 1.00u; "
            "EVhunter69 0.50u; 2.00u two-core-sharp agreement; "
            "3.00u three-core-sharp agreement; "
            "direct conflicts skipped"
        )
    elif "wnba" in category_text and addresses == [FORMAL_CUPCAKE]:
        observed = relative.get(FORMAL_CUPCAKE, 1.0)
        units = min(1.25, max(1.0, observed))
        rule = "Mirror Formal-Cupcake relative stake from 1.00u to 1.25u"
    elif "soccer" in category_text and addresses == [BREAK_THE_BANK]:
        observed = relative.get(BREAK_THE_BANK, 1.0)
        units = min(1.0, max(0.5, 0.5 * observed))
        rule = "BreakTheBank large clean soccer ML: 0.50u at 1x wallet unit, scaled to 1.00u"
    elif "nba" in category_text and addresses == [PORTLY_DERIVATION]:
        if "spread" in market_text or "handicap" in market_text:
            units = 1.0
            rule = "Portly-Derivation validated NBA main spread: 1.00u"
        else:
            units = 0.75
            rule = "Portly-Derivation NBA moneyline: 0.75u pending a larger market sample"
    elif any(token in category_text for token in ("mma", "ufc")) and addresses == [PORTLY_DERIVATION]:
        units = 1.0
        rule = "Portly-Derivation validated UFC/MMA fight moneyline: 1.00u"
    else:
        units = 0.0
        rule = "No eligible specialist sizing rule"
    return {
        "units": round(units, 8),
        "sizing_mode": SIZING_MODE,
        "agreeing_count": len(addresses),
        "relative_units_by_wallet": {
            address: round(relative.get(address, 1.0), 8) for address in addresses
        },
        "wallet_addresses": addresses,
        "rule": rule,
    }


def confidence_score(
    wallet_addresses: Iterable[Any], category: Any, market_type: Any = None
) -> tuple[int, dict[str, Any]]:
    addresses = sorted(
        {
            normalize_address(address)
            for address in wallet_addresses
            if normalize_address(address) in SHARPS
        }
    )
    category_text = _text(category)
    market_text = _text(market_type)
    if "tennis" in category_text:
        eligible = [address for address in addresses if address in TENNIS_SHARPS]
        legacy_count = len([address for address in eligible if address != EVHUNTER])
        has_evhunter = EVHUNTER in eligible
        if legacy_count >= 3:
            score, band = 99, "Three-tennis-sharp agreement"
        elif legacy_count == 2:
            score, band = 97, "Two-tennis-sharp agreement"
        elif legacy_count == 1 and has_evhunter:
            score, band = 94, "Validated tennis sharp plus EVhunter69 confirmation"
        elif addresses == [BAGWELL]:
            score, band = 90, "Bagwell validated tennis sharp"
        elif addresses == [LILYBAEUM]:
            score, band = 84, "Lilybaeum weighted tennis sharp"
        elif addresses == [DABOSSHOGG]:
            score, band = 88, "DaBossHogg validated tennis sharp"
        elif addresses == [EVHUNTER]:
            score, band = 82, "EVhunter69 half-weight tennis originator"
        else:
            score, band = 0, "No validated tennis signal"
    elif "wnba" in category_text and addresses == [FORMAL_CUPCAKE]:
        score = 90
        band = "Formal-Cupcake WNBA full-game spread"
    elif "soccer" in category_text and addresses == [BREAK_THE_BANK]:
        score = 84
        band = "BreakTheBank large clean soccer moneyline"
    elif "nba" in category_text and addresses == [PORTLY_DERIVATION]:
        if "spread" in market_text or "handicap" in market_text:
            score, band = 92, "Portly-Derivation validated NBA main spread"
        else:
            score, band = 87, "Portly-Derivation NBA moneyline"
    elif any(token in category_text for token in ("mma", "ufc")) and addresses == [PORTLY_DERIVATION]:
        score, band = 91, "Portly-Derivation validated UFC/MMA moneyline"
    else:
        score = 0
        band = "No validated specialist signal"
    return score, {
        "architecture": "specialist_weighted_multi_sport_v5",
        "consensus_band": band,
        "raw_sharp_count": len(addresses),
        "wallet_addresses": addresses,
        "stake_independent": True,
        "explanation": (
            "Confidence reflects the validated sport and market-specific copy rule. "
            "Sizing is fixed from the historical simulation rather than inferred from confidence."
        ),
    }
