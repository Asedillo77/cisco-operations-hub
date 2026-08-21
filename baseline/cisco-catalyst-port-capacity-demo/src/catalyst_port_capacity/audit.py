"""Audit orchestration shared by live and mock execution."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

from .analysis import assess_device, assess_interface, natural_port_key, report_timezone
from .switch_cli import collect_cli_port_inventory, compact_interface_name, reportable_switchport
from .config import Credentials
from .models import AuditReport, DeviceSummary

LOGGER = logging.getLogger(__name__)


class InventoryClient(Protocol):
    """Minimum client interface required by the audit."""

    def authenticate(self) -> None: ...
    def find_device(self, target: str) -> dict: ...
    def get_interfaces(self, device_id: str) -> list[dict]: ...


def run_audit(
    client: InventoryClient,
    targets: list[str],
    *,
    dry_run: bool,
    cli_credentials: Credentials | None = None,
) -> AuditReport:
    """Collect and normalize physical switchport evidence."""
    generated_at = datetime.now(UTC)
    devices = []
    ports = []
    messages = []
    client.authenticate()
    for target in targets:
        LOGGER.info("Resolving target %s", target)
        device = None
        try:
            device = assess_device(client.find_device(target))
            if dry_run:
                devices.append(device)
                messages.append(f"Validated target {device.name}; interface collection was not requested.")
                continue
            interfaces = client.get_interfaces(device.device_id)
            rows = []
            for interface in interfaces:
                name = str(
                    interface.get("portName")
                    or interface.get("interfaceName")
                    or interface.get("name")
                    or interface.get("ifName")
                    or ""
                )
                LOGGER.debug("Processing %s %s", device.name, name)
                row = assess_interface(device, interface, generated_at)
                if row is not None:
                    rows.append(row)
            if cli_credentials is not None:
                cli_inventory = collect_cli_port_inventory(
                    device.management_ip,
                    username=cli_credentials.ssh_username,
                    password=cli_credentials.ssh_password,
                    secret=cli_credentials.ssh_secret,
                    device_type=cli_credentials.ssh_device_type,
                )
                original_count = len(rows)
                rows = [
                    row
                    for row in rows
                    if compact_interface_name(row.port_name) in cli_inventory.ports
                    and reportable_switchport(row.port_name, cli_inventory.ready_switches)
                ]
                for row in rows:
                    row.cli_verified = True
                device.cli_validation_status = "success"
                device.cli_validation_message = (
                    f"Validated {len(rows)} of {original_count} DNAC physical port(s) using live CLI."
                )
                messages.append(
                    f"CLI correlation retained {len(rows)} of {original_count} DNAC row(s) for {device.name}."
                )
            ports.extend(rows)
            devices.append(device)
        except Exception as exc:  # One target must not hide results from the others.
            LOGGER.exception("Collection failed for %s", target)
            if device is None:
                device = DeviceSummary(
                    name=target,
                    management_ip=target,
                    device_id="",
                    uptime="Not available",
                    uptime_days=None,
                    confidence="LOW",
                    collection_status="failed",
                )
            device.collection_status = "failed"
            device.message = str(exc)
            if cli_credentials is not None:
                device.cli_validation_status = "failed"
                device.cli_validation_message = str(exc)
            devices.append(device)
    ports.sort(key=lambda row: (row.device_name.lower(), natural_port_key(row.port_name)))
    return AuditReport(
        generated_at=generated_at.astimezone(report_timezone()).strftime("%Y-%m-%d %H:%M:%S %Z"),
        timezone="Australia/Sydney",
        dry_run=dry_run,
        cli_validation=cli_credentials is not None,
        devices=devices,
        ports=ports,
        messages=messages,
    )
