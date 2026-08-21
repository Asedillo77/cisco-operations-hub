"""Read-only command profiles for initial troubleshooting scenarios."""

from __future__ import annotations

from dataclasses import dataclass

from .models import CommandResult, DeviceTarget


@dataclass(frozen=True, slots=True)
class CommandCheck:
    """One command and its interpretation category."""

    check_id: str
    label: str
    command: str


BASE_PROFILE = (
    CommandCheck("device_uptime", "Device uptime", "show version | include uptime"),
    CommandCheck("interface_state", "Interface state", "show ip interface brief"),
    CommandCheck("default_route", "Default route", "show ip route"),
    CommandCheck("transport_descriptions", "Transport descriptions", "show interfaces description"),
    CommandCheck(
        "tunnel_topology",
        "Tunnel topology",
        "show running-config | section ^interface Tunnel",
    ),
)

CELLULAR_PROFILE = (
    CommandCheck("cellular_radio", "Cellular radio measurements", "show cellular 0/2/0 radio"),
    CommandCheck("cellular_network", "Cellular network registration", "show cellular 0/2/0 network"),
)


def initial_checks() -> list[CommandCheck]:
    """Return checks that are safe and relevant before the active transport is known."""
    return list(BASE_PROFILE)


def dry_run_checks(target: DeviceTarget) -> list[CommandCheck]:
    """Return deterministic planned commands without requiring live interface evidence."""
    checks = initial_checks()
    if target.is_cellular or target.site_type.casefold() == "dmt":
        checks.extend(CELLULAR_PROFILE)
    return checks


def cellular_collection_required(target: DeviceTarget, results: list[CommandResult]) -> bool:
    """Decide whether cellular commands are relevant after interface collection."""
    site_type = target.site_type.casefold()
    if site_type == "processing_centre" or target.transport.casefold() in {"fixed", "starlink"}:
        return False
    if site_type == "dmt" or target.is_cellular:
        return True
    interface_result = next((result for result in results if result.check_id == "interface_state"), None)
    if interface_result is None:
        return False
    observed_transport = interface_result.evidence.get("observed_transport")
    if site_type == "dmu":
        return observed_transport != "starlink"
    if site_type in {"datacentre", "donor_centre", "warehouse"}:
        return observed_transport == "cellular_failover"
    return observed_transport == "cellular"
