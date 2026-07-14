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
    top_categories: tuple[str, ...]
    top_category_ids: tuple[str, ...]
    primary_top_category_id: str | None
    top_category_source: str | None
    top_category_verified_at: str | None
    bettor_type: str | None
    selectivity: str | None
    selectivity_score: float | None
    hold_tendency: str | None
    copyability: str | None
    execution_style: str | None
    general_strategy: str | None
    minimum_position_units: float | None
    actionable_position_units: float | None


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
        top_category_ids = canonical_category_ids(configured_top_categories)
        primary_top_category_ids = canonical_category_ids(
            [configured_primary_category]
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
                top_categories=tuple(configured_top_categories),
                top_category_ids=top_category_ids,
                primary_top_category_id=(
                    primary_top_category_ids[0] if primary_top_category_ids else None
                ),
                top_category_source=top_category_source,
                top_category_verified_at=_parse_optional_text(
                    item.get("top_category_verified_at")
                    or item.get("topCategoryVerifiedAt")
                ),
                bettor_type=_parse_optional_text(item.get("bettor_type")),
                selectivity=_parse_optional_text(item.get("selectivity")),
                selectivity_score=_parse_optional_positive_float(
                    item.get("selectivity_score"), "selectivity_score"
                ),
                hold_tendency=_parse_optional_text(item.get("hold_tendency")),
                copyability=_parse_optional_text(item.get("copyability")),
                execution_style=_parse_optional_text(item.get("execution_style")),
                general_strategy=_parse_optional_text(item.get("general_strategy")),
                minimum_position_units=minimum_position_units,
                actionable_position_units=actionable_position_units,
            )
        )

    valid_wallets = list(wallets)
    enabled_wallets = [wallet for wallet in wallets if wallet.enabled]
    return WalletLoadResult(wallets, valid_wallets, enabled_wallets, invalid_entries, file_errors, raw_entries)
