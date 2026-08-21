from __future__ import annotations

import logging
import sys
from io import StringIO
from pathlib import Path
from typing import Any

from ..contracts import RunResult, ToolDescription, ToolField, ValidationResult
from ..inventory_files import prepare_tabular_inventory
from .command_runner import LIVE_CONFIRMATION, _bounded_int, _optional_path, _required_path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HEALTH_MONITOR_ROOT = PROJECT_ROOT / "baseline" / "daily_network_health_monitor"
HEALTH_MONITOR_SRC = HEALTH_MONITOR_ROOT / "src"


def _load_preserved_modules() -> tuple[Any, Any]:
    source = str(HEALTH_MONITOR_SRC)
    if source not in sys.path:
        sys.path.insert(0, source)
    from daily_network_health_monitor import loaders, service

    return loaders, service


class HealthMonitorAdapter:
    def describe(self) -> ToolDescription:
        return ToolDescription(
            tool_id="health-monitor",
            name="Daily Health Monitor",
            summary="Collect and classify point-in-time switch and edge-router health evidence.",
            safety="Dry-run lists every planned command without connecting to a device.",
            available=True,
            fields=(
                ToolField(
                    "inventory_file",
                    "Inventory CSV or XLSX",
                    "path",
                    True,
                    picker="file",
                    extensions=(("Inventory files", "*.csv *.xlsx"),),
                ),
                ToolField(
                    "config_dir",
                    "Command profile folder",
                    "path",
                    True,
                    default=str(HEALTH_MONITOR_ROOT / "configs"),
                    picker="folder",
                ),
                ToolField(
                    "credentials_file",
                    "Credentials file",
                    "path",
                    False,
                    "Required only for live collection.",
                    apply_only=True,
                    picker="file",
                    extensions=(("Credential text files", "*.txt"),),
                ),
                ToolField(
                    "output_root",
                    "Output folder",
                    "path",
                    True,
                    default="outputs",
                    picker="folder",
                ),
                ToolField("max_devices", "Maximum devices", "number", True, default=50),
                ToolField("max_workers", "Concurrent workers", "number", True, default=3),
            ),
        )

    def validate(self, values: dict[str, Any]) -> ValidationResult:
        loaders, _service = _load_preserved_modules()
        max_devices = _bounded_int(values, "max_devices", default=50, minimum=1, maximum=500)
        with prepare_tabular_inventory(_required_path(values, "inventory_file")) as inventory_file:
            devices = loaders.load_inventory(inventory_file, max_devices)
        profiles = loaders.load_profiles(_required_path(values, "config_dir"))
        command_counts = {
            device_type: len(profile.commands) for device_type, profile in profiles.items()
        }
        planned_checks = sum(len(profiles[device.device_type].commands) for device in devices)
        return ValidationResult(
            True,
            f"Validated {len(devices)} enabled device(s) and {planned_checks} planned check(s).",
            {
                "devices": len(devices),
                "planned_checks": planned_checks,
                "commands_by_device_type": command_counts,
                "mode": "dry-run until live collection is explicitly confirmed",
            },
        )

    def run(self, values: dict[str, Any], *, apply: bool) -> RunResult:
        _loaders, service = _load_preserved_modules()
        validation = self.validate(values)
        credentials_file = _optional_path(values, "credentials_file")
        if apply:
            if str(values.get("confirmation", "")) != LIVE_CONFIRMATION:
                raise ValueError(f"Live collection requires this confirmation: {LIVE_CONFIRMATION}")
            if credentials_file is None:
                raise ValueError("A credentials file is required for live collection.")

        logger, stream = _memory_logger(bool(values.get("debug", False)))
        with prepare_tabular_inventory(_required_path(values, "inventory_file")) as inventory_file:
            run_dir = service.run_monitor(
                inventory_file=inventory_file,
                config_dir=_required_path(values, "config_dir"),
                output_root=Path(str(values.get("output_root") or "outputs"))
                .expanduser()
                .resolve(),
                template_dir=HEALTH_MONITOR_ROOT / "templates",
                apply=apply,
                credentials_file=credentials_file,
                max_devices=_bounded_int(values, "max_devices", default=50, minimum=1, maximum=500),
                max_workers=_bounded_int(values, "max_workers", default=3, minimum=1, maximum=20),
                logger=logger,
            )
        logs = tuple(line for line in stream.getvalue().splitlines() if line)
        mode = "live collection" if apply else "dry-run"
        return RunResult("success", f"{validation.summary} Completed {mode}.", run_dir, logs)


def _memory_logger(debug: bool) -> tuple[logging.Logger, StringIO]:
    stream = StringIO()
    logger = logging.getLogger(f"cisco_operations_hub.health_monitor.{id(stream)}")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger, stream
