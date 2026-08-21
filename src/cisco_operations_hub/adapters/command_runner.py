from __future__ import annotations

import logging
import sys
from importlib.util import find_spec
from io import StringIO
from pathlib import Path
from typing import Any

from ..contracts import RunResult, ToolDescription, ToolField, ValidationResult

LIVE_CONFIRMATION = "RUN LIVE READ-ONLY COMMANDS"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMMAND_RUNNER_ROOT = PROJECT_ROOT / "baseline" / "cisco_command_runner"
COMMAND_RUNNER_SRC = COMMAND_RUNNER_ROOT / "src"


def _load_preserved_modules() -> tuple[Any, Any, Any]:
    source = str(COMMAND_RUNNER_SRC)
    if source not in sys.path:
        sys.path.insert(0, source)
    from cisco_command_runner import commands, inventory, service

    return commands, inventory, service


class CommandRunnerAdapter:
    def describe(self) -> ToolDescription:
        return ToolDescription(
            tool_id="command-runner",
            name="Operational Command Runner",
            summary="Validate and run approved show, ping, and traceroute commands.",
            safety="Dry-run is the default. Live collection requires credentials and confirmation.",
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
                    "commands_file",
                    "Commands TXT, CSV, or JSON",
                    "path",
                    False,
                    "Choose a command file or enter commands below, but not both.",
                    picker="file",
                    extensions=(("Command files", "*.txt *.csv *.json"),),
                ),
                ToolField(
                    "commands_text",
                    "Commands entered manually",
                    "textarea",
                    False,
                    "One approved operational command per line. Leave blank when using a file.",
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
                ToolField(
                    "result_handling",
                    "Result detail",
                    "select",
                    True,
                    default="complete",
                    options=(
                        ("complete", "Complete output"),
                        ("common_summary", "Common summary"),
                    ),
                ),
            ),
        )

    def validate(self, values: dict[str, Any]) -> ValidationResult:
        commands, inventory, _service = _load_preserved_modules()
        inventory_file = _required_path(values, "inventory_file")
        max_devices = _bounded_int(values, "max_devices", default=50, minimum=1, maximum=500)
        devices = inventory.load_inventory(inventory_file, max_devices=max_devices)
        commands_file = _optional_path(values, "commands_file")
        commands_text = str(values.get("commands_text", "")).strip()
        if commands_file and commands_text:
            raise ValueError("Choose a command file or enter commands manually, not both.")
        command_list = (
            commands.load_commands(commands_file)
            if commands_file
            else commands.parse_command_text(commands_text)
        )
        result_handling = str(values.get("result_handling", "complete"))
        if result_handling not in {"complete", "common_summary"}:
            raise ValueError("Result detail must be complete or common_summary.")
        return ValidationResult(
            True,
            f"Validated {len(devices)} enabled device(s) and {len(command_list)} command(s).",
            {
                "devices": len(devices),
                "commands": command_list,
                "mode": "dry-run until live collection is explicitly confirmed",
            },
        )

    def run(self, values: dict[str, Any], *, apply: bool) -> RunResult:
        _commands, _inventory, service = _load_preserved_modules()
        validation = self.validate(values)
        credentials_file = _optional_path(values, "credentials_file")
        if apply:
            if str(values.get("confirmation", "")) != LIVE_CONFIRMATION:
                raise ValueError(f"Live collection requires this confirmation: {LIVE_CONFIRMATION}")
            if credentials_file is None:
                raise ValueError("A credentials file is required for live collection.")
            _require_netmiko()

        output_root = Path(str(values.get("output_root") or "outputs")).expanduser().resolve()
        max_devices = _bounded_int(values, "max_devices", default=50, minimum=1, maximum=500)
        max_workers = _bounded_int(values, "max_workers", default=3, minimum=1, maximum=20)
        logger, stream = _memory_logger(bool(values.get("debug", False)))
        run_dir = service.run_job(
            inventory_file=_required_path(values, "inventory_file"),
            output_root=output_root,
            template_dir=COMMAND_RUNNER_ROOT / "templates",
            apply=apply,
            max_devices=max_devices,
            max_workers=max_workers,
            logger=logger,
            result_handling=str(values.get("result_handling", "complete")),
            commands_file=_optional_path(values, "commands_file"),
            commands_text=str(values.get("commands_text", "")),
            credentials_file=credentials_file,
        )
        logs = tuple(line for line in stream.getvalue().splitlines() if line)
        mode = "live collection" if apply else "dry-run"
        return RunResult("success", f"{validation.summary} Completed {mode}.", run_dir, logs)


def _require_netmiko() -> None:
    if find_spec("netmiko") is None:
        raise RuntimeError(
            "Live SSH support is not installed. From the project folder, run "
            "'uv sync' and restart Cisco Operations Hub."
        )


def _required_path(values: dict[str, Any], name: str) -> Path:
    value = str(values.get(name, "")).strip()
    if not value:
        raise ValueError(f"{name.replace('_', ' ').title()} is required.")
    return Path(value).expanduser().resolve()


def _optional_path(values: dict[str, Any], name: str) -> Path | None:
    value = str(values.get(name, "")).strip()
    return Path(value).expanduser().resolve() if value else None


def _bounded_int(
    values: dict[str, Any], name: str, *, default: int, minimum: int, maximum: int
) -> int:
    try:
        value = int(values.get(name, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name.replace('_', ' ').title()} must be a number.") from exc
    if not minimum <= value <= maximum:
        raise ValueError(
            f"{name.replace('_', ' ').title()} must be between {minimum} and {maximum}."
        )
    return value


def _memory_logger(debug: bool) -> tuple[logging.Logger, StringIO]:
    stream = StringIO()
    logger = logging.getLogger(f"cisco_operations_hub.command_runner.{id(stream)}")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger, stream
