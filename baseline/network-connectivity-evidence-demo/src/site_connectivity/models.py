"""Shared data models for collection, evaluation, and reporting."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    """Normalised check states used throughout the report."""

    HEALTHY = "healthy"
    INFORMATIONAL = "informational"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"
    PLANNED = "planned"


@dataclass(slots=True)
class DeviceTarget:
    """Connection and inventory details for one edge router."""

    name: str
    host: str
    site: str = "Ad hoc"
    platform: str = "cisco_xe"
    transport: str = "unknown"
    site_type: str = "other"
    solarwinds_node_id: int | None = None
    solarwinds_name: str | None = None
    solarwinds_ip: str | None = None
    edge_role: str = "single"
    service_vrfs: tuple[str, ...] = ("10",)

    def __post_init__(self) -> None:
        """Canonicalise browser-friendly aliases to the established v7 inventory values."""
        site_type_aliases = {
            "mobile_unit": "dmu",
            "portable_unit": "dmt",
            "dual_edge_hub": "processing_centre",
            "data_centre": "datacentre",
            "branch": "donor_centre",
        }
        self.site_type = site_type_aliases.get(self.site_type.casefold(), self.site_type.casefold())
        self.transport = {"satellite": "starlink"}.get(self.transport.casefold(), self.transport.casefold())

    @property
    def is_cellular(self) -> bool:
        """Return whether inventory marks the device as cellular."""
        return self.transport.casefold() == "cellular"


@dataclass(slots=True)
class PingResult:
    """Parsed ICMP reachability evidence."""

    status: Status = Status.UNKNOWN
    transmitted: int | None = None
    received: int | None = None
    loss_percent: float | None = None
    loss_rating: str | None = None
    loss_explanation: str | None = None
    minimum_ms: float | None = None
    average_ms: float | None = None
    maximum_ms: float | None = None
    latency_rating: str | None = None
    latency_explanation: str | None = None
    message: str = "Ping was not run."
    raw_output: str = ""


@dataclass(slots=True)
class CommandResult:
    """Result of one read-only device command."""

    check_id: str
    command: str
    status: Status
    summary: str
    explanation: str
    recommended_action: str
    raw_output: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DeviceResult:
    """All evidence and conclusions for one device."""

    target: DeviceTarget
    status: Status
    summary: str
    ping: PingResult
    ssh_status: Status = Status.UNKNOWN
    ssh_message: str = "SSH was not attempted."
    checks: list[CommandResult] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return asdict(self)
