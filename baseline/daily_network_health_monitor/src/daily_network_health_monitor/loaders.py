from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import Device, Profile

DEVICE_TYPES = {"switch", "edge_router"}


def load_inventory(path: Path, max_devices: int) -> list[Device]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    devices: list[Device] = []
    errors: list[str] = []
    for row_number, row in enumerate(rows, start=2):
        if not any((value or "").strip() for value in row.values()):
            continue
        if (row.get("enabled") or "true").strip().lower() in {"false", "no", "0"}:
            continue
        hostname = (row.get("hostname") or "").strip()
        ip_address = (row.get("ip_address") or "").strip()
        device_type = (row.get("device_type") or "").strip().lower()
        if not hostname and not ip_address:
            errors.append(f"Row {row_number}: hostname or ip_address is required.")
        elif device_type not in DEVICE_TYPES:
            errors.append(f"Row {row_number}: unsupported device_type '{device_type}'.")
        else:
            devices.append(Device(hostname, ip_address, device_type, row_number))
    if errors:
        raise ValueError("\n".join(errors))
    if not devices:
        raise ValueError("Inventory contains no enabled devices.")
    if len(devices) > max_devices:
        raise ValueError(f"Inventory has {len(devices)} devices; limit is {max_devices}.")
    return devices


def load_profiles(config_dir: Path) -> dict[str, Profile]:
    profiles: dict[str, Profile] = {}
    for path in sorted(config_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        device_type = str(data.get("device_type", "")).strip()
        raw_commands = data.get("commands", [])
        if (
            device_type not in DEVICE_TYPES
            or not isinstance(raw_commands, list)
            or not raw_commands
        ):
            raise ValueError(f"Invalid command profile: {path}")
        vrf = str(data.get("vrf", "2"))
        commands = tuple(str(command).format(vrf=vrf) for command in raw_commands)
        profiles[device_type] = Profile(
            device_type=device_type,
            netmiko_device_type=str(data.get("netmiko_device_type", "cisco_ios")),
            commands=commands,
            thresholds={key: float(value) for key, value in data.get("thresholds", {}).items()},
            vrf=vrf,
        )
    missing = DEVICE_TYPES - profiles.keys()
    if missing:
        raise ValueError(f"Missing profiles for: {', '.join(sorted(missing))}")
    return profiles


def load_credentials(path: Path) -> dict[str, str | int]:
    values: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise ValueError(f"Credentials line {line_number} must use key=value format.")
        key, value = stripped.split("=", 1)
        values[key.strip().lower()] = value.strip()
    if not values.get("username") or not values.get("password"):
        raise ValueError("Credentials require username and password.")
    return {
        "username": values["username"],
        "password": values["password"],
        "secret": values.get("secret", ""),
        "port": int(values.get("port", "22")),
        "timeout": int(values.get("timeout", "30")),
    }
