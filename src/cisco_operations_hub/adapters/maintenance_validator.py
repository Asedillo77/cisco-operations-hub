from __future__ import annotations

import json
import logging
import sys
from argparse import Namespace
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..contracts import RunResult, ToolDescription, ToolField, ValidationResult
from ..inventory_files import prepare_tabular_inventory
from .command_runner import LIVE_CONFIRMATION, _bounded_int, _optional_path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAINTENANCE_ROOT = PROJECT_ROOT / "baseline" / "cisco-network-maintenance-validator"
MAINTENANCE_SRC = MAINTENANCE_ROOT / "src"


def _load_preserved_modules() -> tuple[Any, Any, Any, Any]:
    source = str(MAINTENANCE_SRC)
    if source not in sys.path:
        sys.path.insert(0, source)
    from network_prepost_check import cli, credentials, inventory, report_builder

    return cli, credentials, inventory, report_builder


class MaintenanceValidatorAdapter:
    def describe(self) -> ToolDescription:
        return ToolDescription(
            tool_id="maintenance-validator",
            name="Maintenance Validator",
            summary="Capture and compare read-only pre-check and post-check device state.",
            safety=(
                "Dry-run validates the scope and commands without connecting. Live collection "
                "requires credentials and exact confirmation."
            ),
            available=True,
            fields=(
                ToolField(
                    "operation",
                    "Workflow",
                    "select",
                    True,
                    default="mock",
                    options=(
                        ("mock", "Offline sample comparison"),
                        ("precheck", "Collect pre-check baseline"),
                        ("postcheck", "Collect post-check and compare"),
                    ),
                ),
                ToolField(
                    "inventory_file",
                    "Inventory CSV, XLSX, or JSON",
                    "path",
                    False,
                    "For pre-check or post-check, provide an inventory or one manual host.",
                    picker="file",
                    extensions=(("Device inventories", "*.csv *.xlsx *.json"),),
                ),
                ToolField("hostname", "Manual hostname or IP", "text", False),
                ToolField(
                    "device_type",
                    "Device type",
                    "select",
                    True,
                    default="auto",
                    options=(
                        ("auto", "Auto-detect"),
                        ("switch", "Catalyst switch"),
                        ("edge_router", "Catalyst SD-WAN edge router"),
                    ),
                ),
                ToolField(
                    "commands_file",
                    "Custom command configuration",
                    "path",
                    False,
                    "Optional JSON command profile. Defaults to the preserved profile.",
                    picker="file",
                    extensions=(("Command configuration", "*.json"),),
                ),
                ToolField(
                    "baseline_file",
                    "Pre-check baseline file",
                    "path",
                    False,
                    (
                        "Optional for a single-device post-check; otherwise the latest saved "
                        "baseline is used."
                    ),
                    picker="file",
                    extensions=(("Parsed pre-check output", "*.json"),),
                ),
                ToolField(
                    "credentials_file",
                    "Device credentials",
                    "path",
                    False,
                    "Required only for live pre-check or post-check collection.",
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
                ToolField(
                    "max_workers",
                    "Concurrent workers",
                    "number",
                    True,
                    default=3,
                ),
                ToolField(
                    "max_devices",
                    "Maximum devices",
                    "number",
                    True,
                    "Safety ceiling for an inventory run.",
                    default=20,
                ),
                ToolField(
                    "delay_minutes",
                    "Post-check stabilisation minutes",
                    "number",
                    True,
                    (
                        "Recorded in the comparison report; the browser workflow does not "
                        "pause automatically."
                    ),
                    default=50,
                ),
            ),
        )

    def validate(self, values: dict[str, Any]) -> ValidationResult:
        operation = _operation(values)
        if operation == "mock":
            return ValidationResult(
                True,
                "Validated the preserved offline pre-check/post-check comparison sample.",
                {
                    "workflow": "offline sample comparison",
                    "devices": 1,
                    "connections": 0,
                    "reports": "HTML, JSON, and text",
                },
            )
        args = _build_args(values, operation)
        targets = _load_targets(values, args)
        max_devices = _bounded_int(values, "max_devices", default=20, minimum=1, maximum=200)
        if len(targets) > max_devices:
            raise ValueError(
                f"Inventory has {len(targets)} devices, above the Maximum devices limit "
                f"of {max_devices}."
            )
        workers = _bounded_int(values, "max_workers", default=3, minimum=1, maximum=20)
        delay = _bounded_int(values, "delay_minutes", default=50, minimum=0, maximum=1440)
        cli, _credentials, _inventory, _report_builder = _load_preserved_modules()
        plans = [cli.build_target_plan(args, target) for target in targets]
        commands_by_device = {
            plan["target"].connection_target: plan["config"]["commands"] for plan in plans
        }
        if operation == "postcheck" and args.baseline_file and len(targets) != 1:
            raise ValueError("A specific baseline file can only be used with one manual host.")
        details = {
            "workflow": operation,
            "devices": len(targets),
            "planned_commands": sum(len(item) for item in commands_by_device.values()),
            "concurrent_workers": workers,
            "estimated_batches": (len(targets) + workers - 1) // workers,
            "stabilisation_minutes": delay if operation == "postcheck" else "not applicable",
            "commands_by_device": commands_by_device,
        }
        return ValidationResult(
            True,
            f"Validated {operation} for {len(targets)} device(s) and "
            f"{details['planned_commands']} planned command(s).",
            details,
        )

    def run(self, values: dict[str, Any], *, apply: bool) -> RunResult:
        validation = self.validate(values)
        operation = _operation(values)
        output_root = Path(str(values.get("output_root") or "outputs")).expanduser().resolve()
        logger, stream = _memory_logger(bool(values.get("debug", False)))
        cli, credentials_module, _inventory, _report_builder = _load_preserved_modules()
        if operation == "mock":
            before = set(output_root.glob("*_POST_*")) if output_root.exists() else set()
            args = Namespace(
                output_root=output_root,
                template_file=MAINTENANCE_ROOT / "reports" / "prepost_report.html.j2",
            )
            cli.run_mock_report(args, logger)
            created = sorted(set(output_root.glob("*_POST_*")) - before)
            run_dir = created[-1] if created else output_root
            return RunResult(
                "success",
                "Completed the offline sample comparison and rendered its reports.",
                run_dir,
                _logs(stream),
            )
        args = _build_args(values, operation)
        targets = _load_targets(values, args)
        if not apply:
            run_dir = _write_plan_report(output_root, validation)
            return RunResult(
                "success",
                f"{validation.summary} Created a dry-run plan; no device connection was made.",
                run_dir,
                _logs(stream),
            )
        if str(values.get("confirmation", "")) != LIVE_CONFIRMATION:
            raise ValueError(f"Live collection requires this confirmation: {LIVE_CONFIRMATION}")
        credentials_file = _optional_path(values, "credentials_file")
        if credentials_file is None:
            raise ValueError("Device credentials are required for live collection.")
        credentials = credentials_module.load_local_credentials(credentials_file)
        plans = [cli.build_target_plan(args, target) for target in targets]
        worker = cli.run_precheck_plan if operation == "precheck" else cli.run_postcheck_plan
        results = cli.run_plans_in_parallel(
            plans,
            args.max_workers,
            lambda plan: worker(plan, args, credentials, logger),
        )
        failed = [item for item in results if item["status"] != "success"]
        status = "partial" if failed else "success"
        message = (
            f"Completed {operation}. Successful: {len(results) - len(failed)}; "
            f"failed: {len(failed)}."
        )
        return RunResult(status, message, output_root, _logs(stream))


def _operation(values: dict[str, Any]) -> str:
    operation = str(values.get("operation", "mock")).strip().lower()
    if operation not in {"mock", "precheck", "postcheck"}:
        raise ValueError("Workflow must be offline sample, pre-check, or post-check.")
    return operation


def _build_args(values: dict[str, Any], operation: str) -> Namespace:
    return Namespace(
        command=operation,
        hostname=str(values.get("hostname", "")).strip() or None,
        inventory_file=_optional_path(values, "inventory_file"),
        device_type=str(values.get("device_type", "auto")),
        commands_file=_optional_path(values, "commands_file"),
        baseline_file=_optional_path(values, "baseline_file"),
        output_root=Path(str(values.get("output_root") or "outputs")).expanduser().resolve(),
        template_file=MAINTENANCE_ROOT / "reports" / "prepost_report.html.j2",
        max_workers=_bounded_int(values, "max_workers", default=3, minimum=1, maximum=20),
        max_devices=_bounded_int(values, "max_devices", default=20, minimum=1, maximum=200),
        delay_minutes=_bounded_int(values, "delay_minutes", default=50, minimum=0, maximum=1440),
        wait=False,
        apply=False,
    )


def _load_targets(values: dict[str, Any], args: Namespace) -> list[Any]:
    _cli, _credentials, inventory, _report_builder = _load_preserved_modules()
    if args.inventory_file and args.hostname:
        raise ValueError("Provide an inventory or a manual hostname, not both.")
    if args.inventory_file:
        if args.inventory_file.suffix.lower() == ".xlsx":
            with prepare_tabular_inventory(args.inventory_file) as prepared:
                targets = inventory.load_inventory(prepared)
        else:
            targets = inventory.load_inventory(args.inventory_file)
    elif args.hostname:
        device_type = args.device_type if args.device_type != "auto" else None
        targets = [
            inventory.DeviceTarget(
                connection_target=args.hostname,
                device_type=device_type,
                commands_file=args.commands_file,
            )
        ]
    else:
        raise ValueError("Provide an inventory or a manual hostname for this workflow.")
    return targets


def _write_plan_report(output_root: Path, validation: ValidationResult) -> Path:
    run_dir = output_root / f"maintenance_plan_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dry_run": True,
        "summary": validation.summary,
        "details": validation.details,
    }
    environment = Environment(
        loader=FileSystemLoader(PROJECT_ROOT / "templates"),
        autoescape=select_autoescape(default=True),
    )
    html = environment.get_template("maintenance_plan.html.j2").render(report=payload)
    (run_dir / "maintenance_plan.html").write_text(html, encoding="utf-8")
    (run_dir / "maintenance_plan.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return run_dir


def _memory_logger(debug: bool) -> tuple[logging.Logger, StringIO]:
    stream = StringIO()
    logger = logging.getLogger(f"cisco_operations_hub.maintenance.{id(stream)}")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger, stream


def _logs(stream: StringIO) -> tuple[str, ...]:
    return tuple(line for line in stream.getvalue().splitlines() if line)
