from __future__ import annotations

import logging
from pathlib import Path

from .commands import load_commands, parse_command_text
from .credentials import load_credentials, validate_credentials
from .inventory import load_inventory
from .reporting import build_report, write_reports
from .runner import execute_inventory, plan_results


def run_job(
    *,
    inventory_file: Path,
    output_root: Path,
    template_dir: Path,
    apply: bool,
    max_devices: int,
    max_workers: int,
    logger: logging.Logger,
    result_handling: str = "complete",
    commands_file: Path | None = None,
    commands_text: str = "",
    credentials_file: Path | None = None,
    credentials: dict[str, str | int] | None = None,
) -> Path:
    logger.info("Loading and validating inventory: %s", inventory_file)
    devices = load_inventory(inventory_file, max_devices=max_devices)
    commands = load_commands(commands_file) if commands_file else parse_command_text(commands_text)
    logger.info("Validated %s devices and %s unique commands", len(devices), len(commands))

    if apply:
        auth = (
            load_credentials(credentials_file)
            if credentials_file
            else validate_credentials(credentials or {})
        )
        logger.info("Apply mode confirmed; starting SSH execution")
        results = execute_inventory(devices, commands, auth, max_workers, logger)
        mode = "apply"
    else:
        logger.info("Dry-run mode; no SSH connections will be made")
        results = plan_results(devices, commands)
        mode = "dry-run"

    report = build_report(
        mode,
        len(devices),
        len(commands),
        results,
        result_handling=result_handling,
    )
    run_dir = write_reports(report, output_root, template_dir)
    logger.info("Reports created: %s", run_dir)
    return run_dir
