from __future__ import annotations

import logging
from pathlib import Path

from .loaders import load_credentials, load_inventory, load_profiles
from .reporting import build_report, publish
from .runner import collect, plan


def run_monitor(
    *,
    inventory_file: Path,
    config_dir: Path,
    output_root: Path,
    template_dir: Path,
    apply: bool,
    credentials_file: Path | None,
    max_devices: int,
    max_workers: int,
    logger: logging.Logger,
) -> Path:
    logger.info("Loading inventory: %s", inventory_file)
    devices = load_inventory(inventory_file, max_devices)
    profiles = load_profiles(config_dir)
    for device in devices:
        logger.info(
            "Row %s: prepared %s (%s)", device.row_number, device.target, device.device_type
        )
    if apply:
        if credentials_file is None:
            raise ValueError("--credentials-file is required with --apply.")
        credentials = load_credentials(credentials_file)
        logger.info("Apply confirmed; collecting live point-in-time health data")
        results = collect(devices, profiles, credentials, max(1, max_workers), logger)
        mode = "apply"
    else:
        logger.info("Dry-run mode; no SSH connections will be made")
        results = plan(devices, profiles)
        mode = "dry-run"
    report = build_report(mode, len(devices), results)
    output = publish(report, output_root, template_dir)
    logger.info("Completed report published to %s", output)
    return output
