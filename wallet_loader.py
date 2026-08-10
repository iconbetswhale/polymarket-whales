from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from classification import canonical_category_ids

WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


@dataclass(frozen=True)
class WalletEntry:
    address: str
    display_address: str
    label: str
    enabled: bool
    base_unit: float | None
    notes: str
    top_category: str | None
    top_category_display: str | None
    top_categories: tuple[str, ...]
    sub_top_categories: tuple[str, ...]
    top_category_ids: tuple[str, ...]
    sub_top_category_ids: tuple[str, ...]
    primary_top_category_id: str | None
    top_category_source: str | None
    top_category_verified_at: str | None
    bettor_type: str | None
    trader_type: str | None
    selectivity: str | None
    selectivity_code: str | None
    selectivity_score: float | None
    hold_tendency: str | None
    hold_profile: str | None
    copyability: str | None
    copyability_code: str | None
    execution_style: str | None
    execution_style_code: str | None
    general_strategy: str | None
    minimum_position_units: float | None
    actionable_position_units: float | None
    typical_execution_tranche_dollars: float | None
    minimum_actionable_exposure_dollars: float | None
    requires_fill_aggregation: bool
    hedge_detection_required: bool
    event_portfolio_netting_required: bool
    registry_status: str
    supporting_sharp_eligible: bool
    lead_sharp_eligible: bool
    standard_originator_eligible: bool
    research_candidate_originator_eligible: bool
    supporting_weight: float
    provisional_unit: bool
    minimum_meaningful_originator_position_usd: float | None
    historical_fill_backfill: bool
    category_signal_roles: dict[str, dict[str, Any]]
    wallet_forensics: dict[str, Any]


@dataclass(frozen=True)
class WalletError:
    index: int
    field: str
    value: Any
    message: str


@dataclass(frozen=True)
class WalletLoadResult:
    wallets: list[WalletEntry]
    valid_wallets: list[WalletEntry]
    enabled_wallets: list[WalletEntry]
    invalid_entries: list[WalletError]
    file_errors: list[str]
    raw_entries: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "wallets": [asdict(wallet) for wallet in self.wallets],
            "valid_wallets": [asdict(wallet) for wallet in self.valid_wallets],
            "enabled_wallets": [asdict(wallet) for wallet in self.enabled_wallets],
            "invalid_entries": [asdict(error) for error in self.invalid_entries],
            "file_errors": self.file_errors,
            "raw_entries": self.raw_entries,
        }


def normalize_wallet_address(address: str) -> str:
    if not isinstance(address, str):
        raise ValueError("Wallet address must be a string")
    normalized = address.strip().lower()
    if not WALLET_RE.fullmatch(normalized):
        raise ValueError("Wallet addresses must start with 0x and contain exactly 40 hexadecimal characters")
    return normalized


def _parse_base_unit(value: Any) -> float | None:
    if value in ("", None):
        return None
    parsed = float(value)
    if parsed <= 0:
        raise ValueError("base_unit must be greater than zero when provided")
    return parsed


def _parse_optional_text(value: Any) -> str | None:
    if value in ("", None):
        return None
    return str(value).strip() or None


def _parse_optional_text_list(value: Any) -> tuple[str, ...]:
    if value in ("", None):
        return ()
    values = value if isinstance(value, (list, tuple, set)) else [value]
    parsed: list[str] = []
    for item in values:
        text = _parse_optional_text(item)
        if text and text not in parsed:
            parsed.append(text)
    return tuple(parsed)


def _parse_optional_positive_float(value: Any, field: str) -> float | None:
    if value in ("", None):
        return None
    parsed = float(value)
    if parsed <= 0:
        raise ValueError(f"{field} must be greater than zero when provided")
    return parsed


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("must be a boolean")


def _parse_category_signal_roles(value: Any) -> dict[str, dict[str, Any]]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValueError("category_signal_roles must be an object")
    allowed_roles = {
        "ORIGINATOR",
        "CONDITIONAL_ORIGINATOR",
        "CONFIRMER",
        "RESEARCH",
    }
    allowed_consensus_roles = {
        "DIRECTIONAL_CORE",
        "NETTED_CONFIRMER",
        "RESEARCH",
    }
    parsed: dict[str, dict[str, Any]] = {}
    for category, raw_policy in value.items():
        category_ids = canonical_category_ids([category])
        if not category_ids:
            raise ValueError(f"Unknown category_signal_roles category: {category}")
        if not isinstance(raw_policy, dict):
            raise ValueError("Each category signal role must be an object")
        role = str(raw_policy.get("role") or "CONFIRMER").strip().upper()
        if role not in allowed_roles:
            raise ValueError(f"Unsupported category signal role: {role}")
        consensus_role = str(
            raw_policy.get("consensus_role") or ""
        ).strip().upper() or None
        if consensus_role not in allowed_consensus_roles | {None}:
            raise ValueError(
                f"Unsupported category consensus role: {consensus_role}"
            )
        quality_weight = float(raw_policy.get("quality_weight", 0.5))
        if not 0 <= quality_weight <= 1:
            raise ValueError("quality_weight must be between zero and one")
        minimum_units = float(raw_policy.get("minimum_originator_units", 0.5))
        if minimum_units < 0:
            raise ValueError("minimum_originator_units cannot be negative")
        unit_baseline = raw_policy.get("unit_baseline_usd")
        if unit_baseline is not None:
            unit_baseline = float(unit_baseline)
            if unit_baseline <= 0:
                raise ValueError("unit_baseline_usd must be greater than zero")
        parsed[category_ids[0]] = {
            "role": role,
            **({"consensus_role": consensus_role} if consensus_role else {}),
            "quality_weight": quality_weight,
            "minimum_originator_units": minimum_units,
            "unit_baseline_usd": unit_baseline,
            "requires_clean_directional": _parse_bool(
                raw_policy.get("requires_clean_directional"), False
            ),
            "source": str(
                raw_policy.get("source") or "provisional_category_review"
            ).strip(),
        }
    return parsed


def load_wallets(path: Path) -> WalletLoadResult:
    invalid_entries: list[WalletError] = []
    file_errors: list[str] = []
    wallets: list[WalletEntry] = []
    raw_entries: list[dict[str, Any]] = []

    if not path.exists():
        file_errors.append(f"{path} does not exist")
        return WalletLoadResult([], [], [], invalid_entries, file_errors, raw_entries)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        file_errors.append(f"Invalid JSON in {path}: {exc.msg} at line {exc.lineno} column {exc.colno}")
        return WalletLoadResult([], [], [], invalid_entries, file_errors, raw_entries)

    if not isinstance(payload, list):
        file_errors.append(f"{path} must contain a JSON array of wallet objects")
        return WalletLoadResult([], [], [], invalid_entries, file_errors, raw_entries)

    seen: set[str] = set()

    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            invalid_entries.append(WalletError(index=index, field="entry", value=item, message="Wallet entry must be an object"))
            continue

        raw_entries.append(item)
        address_value = item.get("address", "")
        try:
            address = normalize_wallet_address(address_value)
        except ValueError as exc:
            invalid_entries.append(WalletError(index=index, field="address", value=address_value, message=str(exc)))
            continue

        if address in seen:
            invalid_entries.append(WalletError(index=index, field="address", value=address_value, message="Duplicate wallet address"))
            continue

        seen.add(address)

        base_unit_value = item.get("base_unit")
        try:
            base_unit = _parse_base_unit(base_unit_value)
        except (TypeError, ValueError) as exc:
            invalid_entries.append(WalletError(index=index, field="base_unit", value=base_unit_value, message=str(exc)))
            continue

        minimum_position_units_value = item.get("minimum_position_units")
        try:
            minimum_position_units = _parse_optional_positive_float(
                minimum_position_units_value, "minimum_position_units"
            )
        except (TypeError, ValueError) as exc:
            invalid_entries.append(
                WalletError(
                    index=index,
                    field="minimum_position_units",
                    value=minimum_position_units_value,
                    message=str(exc),
                )
            )
            continue

        actionable_position_units_value = item.get("actionable_position_units")
        try:
            actionable_position_units = _parse_optional_positive_float(
                actionable_position_units_value, "actionable_position_units"
            )
        except (TypeError, ValueError) as exc:
            invalid_entries.append(
                WalletError(
                    index=index,
                    field="actionable_position_units",
                    value=actionable_position_units_value,
                    message=str(exc),
                )
            )
            continue

        optional_dollar_fields: dict[str, float | None] = {}
        invalid_optional_dollars = False
        for field in (
            "typical_execution_tranche_dollars",
            "minimum_actionable_exposure_dollars",
            "minimum_meaningful_originator_position_usd",
        ):
            value = item.get(field)
            try:
                optional_dollar_fields[field] = _parse_optional_positive_float(
                    value, field
                )
            except (TypeError, ValueError) as exc:
                invalid_entries.append(
                    WalletError(index=index, field=field, value=value, message=str(exc))
                )
                invalid_optional_dollars = True
                break
        if invalid_optional_dollars:
            continue

        boolean_fields: dict[str, bool] = {}
        invalid_boolean = False
        boolean_defaults = {
            "requires_fill_aggregation": False,
            "hedge_detection_required": False,
            "event_portfolio_netting_required": False,
            "supporting_sharp_eligible": True,
            "lead_sharp_eligible": True,
            "standard_originator_eligible": True,
            "research_candidate_originator_eligible": True,
            "provisional_unit": False,
            "historical_fill_backfill": False,
        }
        for field, default in boolean_defaults.items():
            value = item.get(field)
            try:
                boolean_fields[field] = _parse_bool(value, default)
            except ValueError as exc:
                invalid_entries.append(
                    WalletError(index=index, field=field, value=value, message=str(exc))
                )
                invalid_boolean = True
                break
        if invalid_boolean:
            continue

        supporting_weight_value = item.get("supporting_weight", 0.5)
        try:
            supporting_weight = float(supporting_weight_value)
            if not 0 < supporting_weight <= 1:
                raise ValueError("supporting_weight must be greater than zero and no more than one")
        except (TypeError, ValueError) as exc:
            invalid_entries.append(
                WalletError(
                    index=index,
                    field="supporting_weight",
                    value=supporting_weight_value,
                    message=str(exc),
                )
            )
            continue

        try:
            category_signal_roles = _parse_category_signal_roles(
                item.get("category_signal_roles")
            )
        except (TypeError, ValueError) as exc:
            invalid_entries.append(
                WalletError(
                    index=index,
                    field="category_signal_roles",
                    value=item.get("category_signal_roles"),
                    message=str(exc),
                )
            )
            continue
        wallet_forensics = item.get("wallet_forensics") or {}
        if not isinstance(wallet_forensics, dict):
            invalid_entries.append(
                WalletError(
                    index=index,
                    field="wallet_forensics",
                    value=wallet_forensics,
                    message="wallet_forensics must be an object",
                )
            )
            continue

        if (
            minimum_position_units is not None
            and actionable_position_units is not None
            and actionable_position_units < minimum_position_units
        ):
            invalid_entries.append(
                WalletError(
                    index=index,
                    field="actionable_position_units",
                    value=actionable_position_units_value,
                    message="actionable_position_units must be greater than or equal to minimum_position_units",
                )
            )
            continue

        label = str(item.get("label") or f"Wallet {index + 1}").strip()
        notes = str(item.get("notes") or "")
        enabled = bool(item.get("enabled", True))
        configured_top_categories = list(
            _parse_optional_text_list(
                item.get("top_categories") or item.get("topCategoryIds")
            )
        )
        configured_sub_top_categories = list(
            _parse_optional_text_list(
                item.get("sub_top_categories")
                or item.get("subTopCategories")
                or item.get("secondary_top_categories")
            )
        )
        configured_primary_category = _parse_optional_text(
            item.get("primary_top_category")
            or item.get("primaryTopCategoryId")
            or item.get("top_category")
        )
        if (
            configured_primary_category
            and configured_primary_category not in configured_top_categories
        ):
            configured_top_categories.insert(0, configured_primary_category)
        combined_top_categories = [
            *configured_top_categories,
            *(
                category
                for category in configured_sub_top_categories
                if category not in configured_top_categories
            ),
        ]
        top_category_ids = canonical_category_ids(combined_top_categories)
        primary_top_category_ids = canonical_category_ids(
            [configured_primary_category]
        )
        primary_top_category_id = (
            primary_top_category_ids[0] if primary_top_category_ids else None
        )
        sub_top_category_ids = canonical_category_ids(
            configured_sub_top_categories
        ) or tuple(
            category_id
            for category_id in top_category_ids
            if category_id != primary_top_category_id
        )
        top_category_source = _parse_optional_text(
            item.get("top_category_source") or item.get("topCategorySource")
        )
        if not top_category_source and top_category_ids:
            top_category_source = "manual_config"
        wallets.append(
            WalletEntry(
                address=address,
                display_address=str(address_value).strip() or address,
                label=label,
                enabled=enabled,
                base_unit=base_unit,
                notes=notes,
                top_category=configured_primary_category,
                top_category_display=_parse_optional_text(
                    item.get("top_category_display")
                ),
                top_categories=tuple(combined_top_categories),
                sub_top_categories=tuple(configured_sub_top_categories),
                top_category_ids=top_category_ids,
                sub_top_category_ids=sub_top_category_ids,
                primary_top_category_id=primary_top_category_id,
                top_category_source=top_category_source,
                top_category_verified_at=_parse_optional_text(
                    item.get("top_category_verified_at")
                    or item.get("topCategoryVerifiedAt")
                ),
                bettor_type=_parse_optional_text(item.get("bettor_type")),
                trader_type=_parse_optional_text(item.get("trader_type")),
                selectivity=_parse_optional_text(item.get("selectivity")),
                selectivity_code=_parse_optional_text(item.get("selectivity_code")),
                selectivity_score=_parse_optional_positive_float(
                    item.get("selectivity_score"), "selectivity_score"
                ),
                hold_tendency=_parse_optional_text(item.get("hold_tendency")),
                hold_profile=_parse_optional_text(item.get("hold_profile")),
                copyability=_parse_optional_text(item.get("copyability")),
                copyability_code=_parse_optional_text(item.get("copyability_code")),
                execution_style=_parse_optional_text(item.get("execution_style")),
                execution_style_code=_parse_optional_text(
                    item.get("execution_style_code")
                ),
                general_strategy=_parse_optional_text(item.get("general_strategy")),
                minimum_position_units=minimum_position_units,
                actionable_position_units=actionable_position_units,
                typical_execution_tranche_dollars=optional_dollar_fields[
                    "typical_execution_tranche_dollars"
                ],
                minimum_actionable_exposure_dollars=optional_dollar_fields[
                    "minimum_actionable_exposure_dollars"
                ],
                requires_fill_aggregation=boolean_fields[
                    "requires_fill_aggregation"
                ],
                hedge_detection_required=boolean_fields[
                    "hedge_detection_required"
                ],
                event_portfolio_netting_required=boolean_fields[
                    "event_portfolio_netting_required"
                ],
                registry_status=(
                    _parse_optional_text(item.get("registry_status")) or "ACTIVE"
                ).upper(),
                supporting_sharp_eligible=boolean_fields[
                    "supporting_sharp_eligible"
                ],
                lead_sharp_eligible=boolean_fields["lead_sharp_eligible"],
                standard_originator_eligible=boolean_fields[
                    "standard_originator_eligible"
                ],
                research_candidate_originator_eligible=boolean_fields[
                    "research_candidate_originator_eligible"
                ],
                supporting_weight=supporting_weight,
                provisional_unit=boolean_fields["provisional_unit"],
                minimum_meaningful_originator_position_usd=optional_dollar_fields[
                    "minimum_meaningful_originator_position_usd"
                ],
                historical_fill_backfill=boolean_fields[
                    "historical_fill_backfill"
                ],
                category_signal_roles=category_signal_roles,
                wallet_forensics=wallet_forensics,
            )
        )

    valid_wallets = list(wallets)
    enabled_wallets = [wallet for wallet in wallets if wallet.enabled]
    return WalletLoadResult(wallets, valid_wallets, enabled_wallets, invalid_entries, file_errors, raw_entries)
