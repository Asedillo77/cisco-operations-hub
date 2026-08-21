from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Device:
    hostname: str
    ip_address: str
    device_type: str
    row_number: int

    @property
    def target(self) -> str:
        return self.ip_address or self.hostname


@dataclass(frozen=True)
class Profile:
    device_type: str
    netmiko_device_type: str
    commands: tuple[str, ...]
    thresholds: dict[str, float] = field(default_factory=dict)
    vrf: str = "2"


@dataclass
class Result:
    hostname: str
    ip_address: str
    device_type: str
    inventory_row: int
    command_number: int
    command: str
    collection_status: str
    health_status: str
    message: str
    output: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Report:
    run_id: str
    mode: str
    generated_at: str
    overall_status: str
    requested_devices: int
    results: list[Result]

    @property
    def counts(self) -> dict[str, int]:
        counts = {
            "healthy": 0,
            "informational": 0,
            "warning": 0,
            "critical": 0,
            "unknown": 0,
            "failed": 0,
            "planned": 0,
        }
        for result in self.results:
            counts[result.health_status] = counts.get(result.health_status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "generated_at": self.generated_at,
            "overall_status": self.overall_status,
            "requested_devices": self.requested_devices,
            "counts": self.counts,
            "results": [result.to_dict() for result in self.results],
        }
