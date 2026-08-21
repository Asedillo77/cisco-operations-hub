"""Standalone inventory loading with a future Nautobot adapter boundary."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Any

from .models import DeviceTarget

SITE_TYPE_ALIASES = {
    "mobile_unit": "dmu",
    "portable_unit": "dmt",
    "dual_edge_hub": "processing_centre",
    "data_centre": "datacentre",
    "branch": "donor_centre",
}
TRANSPORT_ALIASES = {"satellite": "starlink"}


def _normalise_host(value: str) -> str:
    host = value.strip()
    if not host:
        raise ValueError("Device host cannot be empty.")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_")
        if any(character not in allowed for character in host):
            raise ValueError(f"Invalid device hostname: {host}") from None
        return host


def target_from_mapping(data: dict[str, Any]) -> DeviceTarget:
    """Validate and normalise one inventory row."""
    node_id = data.get("solarwinds_node_id")
    raw_vrfs = data.get("service_vrfs", ["10"])
    if isinstance(raw_vrfs, str):
        raw_vrfs = [value.strip() for value in raw_vrfs.split(",") if value.strip()]
    if not isinstance(raw_vrfs, list) or not all(str(value).strip() for value in raw_vrfs):
        raise ValueError("service_vrfs must be a list of VRF names or a comma-separated string.")
    transport = str(data.get("transport") or "unknown").strip().casefold()
    site_type = str(data.get("site_type") or "other").strip().casefold()
    return DeviceTarget(
        name=str(data.get("name") or data.get("host") or "").strip(),
        host=_normalise_host(str(data.get("host") or "")),
        site=str(data.get("site") or "Ad hoc").strip(),
        platform=str(data.get("platform") or "cisco_xe").strip(),
        transport=TRANSPORT_ALIASES.get(transport, transport),
        site_type=SITE_TYPE_ALIASES.get(site_type, site_type),
        solarwinds_node_id=int(node_id) if node_id not in (None, "") else None,
        solarwinds_name=str(data.get("solarwinds_name") or "").strip() or None,
        solarwinds_ip=(
            _normalise_host(str(data["solarwinds_ip"])) if data.get("solarwinds_ip") not in (None, "") else None
        ),
        edge_role=str(data.get("edge_role") or "single").strip().casefold(),
        service_vrfs=tuple(str(value).strip() for value in raw_vrfs),
    )


def load_inventory(path: Path) -> list[DeviceTarget]:
    """Load devices from a JSON document containing a devices list."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("devices") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("Inventory JSON must be a list or contain a 'devices' list.")
    targets = [target_from_mapping(row) for row in rows if isinstance(row, dict)]
    if not targets:
        raise ValueError("Inventory does not contain any valid device rows.")
    return targets


def sites_from_inventory(targets: list[DeviceTarget]) -> list[str]:
    """Return unique site names in alphabetical order."""
    return sorted({target.site for target in targets}, key=str.casefold)


def devices_for_site(targets: list[DeviceTarget], site: str) -> list[DeviceTarget]:
    """Return devices belonging to one selected site."""
    return [target for target in targets if target.site == site]
