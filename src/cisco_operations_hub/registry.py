from __future__ import annotations

from .adapters.command_runner import CommandRunnerAdapter
from .adapters.connectivity_evidence import ConnectivityEvidenceAdapter
from .adapters.health_monitor import HealthMonitorAdapter
from .adapters.maintenance_validator import MaintenanceValidatorAdapter
from .adapters.port_capacity import PortCapacityAdapter
from .contracts import ToolAdapter


def build_registry() -> dict[str, ToolAdapter]:
    adapters: tuple[ToolAdapter, ...] = (
        CommandRunnerAdapter(),
        HealthMonitorAdapter(),
        PortCapacityAdapter(),
        ConnectivityEvidenceAdapter(),
        MaintenanceValidatorAdapter(),
    )
    return {adapter.describe().tool_id: adapter for adapter in adapters}
