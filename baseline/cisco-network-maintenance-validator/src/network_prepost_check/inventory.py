from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DeviceTarget:
    connection_target: str
    device_type: str | None = None
    commands_file: Path | None = None
    row_number: int | None = None


def load_inventory(inventory_file: Path) -> list[DeviceTarget]:
    if not inventory_file.exists():
        raise FileNotFoundError(f"Inventory file was not found: {inventory_file}")

    suffix = inventory_file.suffix.lower()
    if suffix == ".csv":
        return load_csv_inventory(inventory_file)
    if suffix == ".json":
        return load_json_inventory(inventory_file)

    raise ValueError("Inventory file must be CSV or JSON.")


def load_csv_inventory(inventory_file: Path) -> list[DeviceTarget]:
    targets = []
    with inventory_file.open("r", encoding="utf-8-sig", newline="") as file_handle:
        reader = csv.DictReader(file_handle)
        if not reader.fieldnames:
            raise ValueError(f"Inventory CSV has no header row: {inventory_file}")

        for row_number, row in enumerate(reader, start=2):
            target = _target_from_mapping(row, row_number=row_number)
            if target:
                targets.append(target)

    if not targets:
        raise ValueError(f"Inventory CSV has no usable devices: {inventory_file}")
    return targets


def load_json_inventory(inventory_file: Path) -> list[DeviceTarget]:
    with inventory_file.open("r", encoding="utf-8") as file_handle:
        inventory_data = json.load(file_handle)

    devices = inventory_data.get("devices") if isinstance(inventory_data, dict) else inventory_data

    if not isinstance(devices, list):
        raise ValueError("Inventory JSON must be a list or an object with a devices list.")

    targets = []
    for index, item in enumerate(devices, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Inventory JSON device {index} must be an object.")
        target = _target_from_mapping(item, row_number=index)
        if target:
            targets.append(target)

    if not targets:
        raise ValueError(f"Inventory JSON has no usable devices: {inventory_file}")
    return targets


def _target_from_mapping(data: dict[str, Any], row_number: int) -> DeviceTarget | None:
    normalized = {str(key).strip().lower(): value for key, value in data.items()}
    connection_target = _first_value(
        normalized,
        "hostname",
        "host",
        "ip",
        "ip_address",
        "connection_target",
    )
    if not connection_target:
        return None

    device_type = _first_value(normalized, "device_type", "type")
    commands_file = _first_value(normalized, "commands_file", "command_file", "config_file")

    return DeviceTarget(
        connection_target=connection_target,
        device_type=device_type,
        commands_file=Path(commands_file) if commands_file else None,
        row_number=row_number,
    )


def _first_value(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None
