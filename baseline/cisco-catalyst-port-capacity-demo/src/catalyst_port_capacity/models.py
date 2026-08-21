"""Shared models for collection, classification, and reporting."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

OBSERVATION_THRESHOLD_DAYS = 60


@dataclass(slots=True)
class DeviceSummary:
    """Normalized information for one switch or switch stack."""

    name: str
    management_ip: str
    device_id: str
    uptime: str
    uptime_days: int | None
    confidence: str
    collection_status: str = "success"
    message: str = "Collection completed."
    cli_validation_status: str = "not_requested"
    cli_validation_message: str = "CLI validation was not requested."

    def to_dict(self) -> dict[str, Any]:
        """Return a report-friendly dictionary."""
        return asdict(self)


@dataclass(slots=True)
class PortResult:
    """Normalized evidence and decision for one physical switchport."""

    device_name: str
    management_ip: str
    port_name: str
    description: str
    mac_address: str
    admin_status: str
    operational_status: str
    last_input: str
    last_output: str
    days_unused: int | None
    observed_unused_days: int | None
    confidence: str
    usage_flag: str
    status: str
    message: str
    cli_verified: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a report-friendly dictionary."""
        return asdict(self)


@dataclass(slots=True)
class AuditReport:
    """Complete report shared by HTML, JSON, and CSV output."""

    generated_at: str
    timezone: str
    dry_run: bool
    cli_validation: bool
    devices: list[DeviceSummary]
    ports: list[PortResult]
    messages: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Return the public report schema."""
        return {
            "generated_at": self.generated_at,
            "timezone": self.timezone,
            "dry_run": self.dry_run,
            "cli_validation": self.cli_validation,
            "observation_threshold_days": OBSERVATION_THRESHOLD_DAYS,
            "counts": {
                "devices": len(self.devices),
                "ports": len(self.ports),
                "active": sum(port.usage_flag == "ACTIVE" for port in self.ports),
                "potentially_unused": sum(port.usage_flag.startswith("UNUSED") for port in self.ports),
                "review": sum(port.usage_flag == "REVIEW" for port in self.ports),
                "failed_devices": sum(device.collection_status == "failed" for device in self.devices),
            },
            "messages": self.messages,
            "devices": [device.to_dict() for device in self.devices],
            "ports": [port.to_dict() for port in self.ports],
        }
