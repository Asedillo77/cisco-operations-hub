from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class DeviceTarget:
    hostname: str
    ip_address: str
    device_type: str
    row_number: int
    enabled: bool = True

    @property
    def connection_target(self) -> str:
        return self.ip_address or self.hostname


@dataclass
class CommandResult:
    inventory_row: int
    hostname: str
    ip_address: str
    detected_hostname: str
    device_type: str
    command_number: int
    command: str
    status: str
    started_at: str
    finished_at: str
    duration_seconds: float
    message: str
    output: str = ""
    result_summary: str = ""
    extracted_fields: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunReport:
    run_id: str
    mode: str
    generated_at: str
    requested_devices: int
    requested_commands: int
    result_handling: str = "complete"
    results: list[CommandResult] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts = {"success": 0, "failed": 0, "skipped": 0, "planned": 0}
        for result in self.results:
            counts[result.status] = counts.get(result.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "generated_at": self.generated_at,
            "requested_devices": self.requested_devices,
            "requested_commands": self.requested_commands,
            "result_handling": self.result_handling,
            "counts": self.counts,
            "validation_errors": self.validation_errors,
            "results": [result.to_dict() for result in self.results],
        }
