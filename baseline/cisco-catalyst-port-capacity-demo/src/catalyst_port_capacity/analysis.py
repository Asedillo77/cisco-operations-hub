"""Port normalization and capacity assessment logic."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import OBSERVATION_THRESHOLD_DAYS, DeviceSummary, PortResult
from .switch_cli import compact_interface_name, reportable_switchport

REPORT_TIMEZONE = "Australia/Sydney"
PREFIX_ORDER = {"fa": 0, "gi": 1, "tw": 2, "te": 3, "fo": 4, "eth": 5}


def parse_timestamp(value: Any) -> datetime | None:
    """Parse Catalyst epoch or ISO timestamps as UTC datetimes."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        if text.replace(".", "", 1).isdigit():
            timestamp = float(text)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=UTC)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (OSError, OverflowError, ValueError):
        return None


def report_timezone() -> tzinfo:
    """Return the report timezone used by the v7 Nautobot implementation."""
    try:
        return ZoneInfo(REPORT_TIMEZONE)
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone().tzinfo or UTC


def display_timestamp(value: Any) -> str:
    """Format a Catalyst timestamp in the report timezone."""
    parsed = parse_timestamp(value)
    if parsed is None:
        return "" if value in (None, "") else str(value)
    return parsed.astimezone(report_timezone()).strftime("%Y-%m-%d %H:%M:%S %Z")


def first_value(data: dict[str, Any], keys: Iterable[str]) -> str:
    """Return the first non-empty mapping value for the supplied aliases."""
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def uptime_days(value: Any) -> int | None:
    """Convert Catalyst uptime seconds into non-negative whole days."""
    try:
        seconds = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return max(0, seconds // 86_400)


def natural_port_key(name: str) -> tuple[int, int, int, int, str]:
    """Sort by stack member, module, port, then interface type."""
    compact = compact_interface_name(name)
    prefix = next((item for item in PREFIX_ORDER if compact.startswith(item)), "")
    path = compact[len(prefix) :].split("/") if prefix else []
    if len(path) != 3 or not all(item.isdigit() for item in path):
        return (99, 999, 999, 999, name.lower())
    member, module, port = (int(item) for item in path)
    return (member, module, port, PREFIX_ORDER.get(prefix, 98), name.lower())


def assess_device(device: dict[str, Any]) -> DeviceSummary:
    """Hydrate the v7 device-level uptime and confidence values."""
    days = uptime_days(device.get("uptimeSeconds"))
    confidence = (
        "HIGH" if days is not None and days >= OBSERVATION_THRESHOLD_DAYS else "LOW" if days is not None else "UNKNOWN"
    )
    return DeviceSummary(
        device_id=str(device.get("id", "")),
        name=str(device.get("hostname") or device.get("name") or "Unknown device"),
        management_ip=str(device.get("managementIpAddress") or "Not available"),
        uptime=str(device.get("upTime") or "N/A"),
        uptime_days=days,
        confidence=confidence,
    )


def assess_interface(
    device: DeviceSummary,
    interface: dict[str, Any],
    generated_at: datetime,
) -> PortResult | None:
    """Normalize and classify one DNAC interface using v7 behavior."""
    port_name = first_value(interface, ("portName", "interfaceName", "name", "ifName"))
    if not reportable_switchport(port_name):
        return None

    admin = first_value(interface, ("adminStatus", "adminState"))
    operational = first_value(interface, ("status", "operStatus", "ifOperStatus"))
    last_input_raw = first_value(interface, ("lastIncomingPacketTime", "lastInput", "lastInputTime"))
    last_output_raw = first_value(interface, ("lastOutgoingPacketTime", "lastOutput", "lastOutputTime"))
    activity = [stamp for value in (last_input_raw, last_output_raw) if (stamp := parse_timestamp(value))]
    days_unused = max(0, (generated_at.astimezone(UTC) - max(activity)).days) if activity else None
    observed = (
        min(days_unused, device.uptime_days) if days_unused is not None and device.uptime_days is not None else None
    )

    status_text = f"{admin} {operational}".lower()
    if any(value in status_text for value in ("down", "notconnect", "disabled")):
        flag = "UNUSED_DOWN"
        reason = "Port is operationally down or disabled."
    elif operational.lower() in {"up", "connected"}:
        flag = "ACTIVE"
        reason = "Port is operationally active."
    else:
        flag = "REVIEW"
        reason = "Port state requires manual review."

    return PortResult(
        device_name=device.name,
        management_ip=device.management_ip,
        port_name=port_name,
        description=first_value(interface, ("description", "interfaceDescription")),
        mac_address=first_value(interface, ("macAddress", "interfaceMacAddress")),
        admin_status=admin,
        operational_status=operational,
        last_input=display_timestamp(last_input_raw),
        last_output=display_timestamp(last_output_raw),
        days_unused=days_unused,
        observed_unused_days=observed,
        confidence=device.confidence,
        usage_flag=flag,
        status="success",
        message=reason,
    )
