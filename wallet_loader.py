from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


@dataclass(frozen=True)
class WalletEntry:
    address: str
    label: str
    enabled: bool
    base_unit: float | None
    notes: str


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

        label = str(item.get("label") or f"Wallet {index + 1}").strip()
        notes = str(item.get("notes") or "")
        enabled = bool(item.get("enabled", True))
        wallets.append(
            WalletEntry(
                address=address,
                label=label,
                enabled=enabled,
                base_unit=base_unit,
                notes=notes,
            )
        )

    valid_wallets = list(wallets)
    enabled_wallets = [wallet for wallet in wallets if wallet.enabled]
    return WalletLoadResult(wallets, valid_wallets, enabled_wallets, invalid_entries, file_errors, raw_entries)
