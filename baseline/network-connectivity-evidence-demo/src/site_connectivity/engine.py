"""Orchestrate safe site troubleshooting runs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from .collector import CollectionError, collect_commands
from .credentials import Credentials
from .evaluation import finalise_device
from .models import CommandResult, DeviceResult, DeviceTarget, PingResult, Status
from .profiles import dry_run_checks, initial_checks
from .reachability import run_ping

if TYPE_CHECKING:
    from .solarwinds import SolarWindsCollector


def investigate_device(
    target: DeviceTarget,
    credentials: Credentials | None,
    *,
    apply: bool = False,
    ping_count: int = 15,
    ping_timeout: int = 2,
    logger: logging.Logger,
    cancelled: Callable[[], bool] | None = None,
    solarwinds_collector: SolarWindsCollector | None = None,
    solarwinds_requested: bool = False,
) -> DeviceResult:
    """Run reachability and optionally live read-only SSH collection."""
    checks = dry_run_checks(target) if not apply else initial_checks()
    logger.info("Processing device %s (%s)", target.name, target.host)
    if not apply:
        planned = [
            CommandResult(
                check.check_id,
                check.command,
                Status.PLANNED,
                f"Planned check: {check.label}",
                "Dry-run mode does not contact the device.",
                "Run with live collection enabled after reviewing the command list.",
            )
            for check in checks
        ]
        if solarwinds_requested:
            planned.append(
                CommandResult(
                    "solarwinds_alerts",
                    "SolarWinds active alerts API",
                    Status.PLANNED,
                    "Planned check: SolarWinds active alerts",
                    "Dry-run mode does not contact SolarWinds.",
                    "Run live collection after reviewing the optional API settings.",
                )
            )
        return DeviceResult(
            target,
            Status.PLANNED,
            "Dry run completed; no ping or SSH connection was made.",
            PingResult(status=Status.PLANNED, message="Ping is planned for a live run."),
            Status.PLANNED,
            "SSH commands are planned for a live run.",
            planned,
        )

    ping = run_ping(target.host, ping_count, ping_timeout)
    result = DeviceResult(target, Status.UNKNOWN, "Collection is incomplete.", ping)
    if cancelled and cancelled():
        result.summary = "Collection was cancelled after the reachability check."
        return result
    if credentials is None:
        result.ssh_message = "Credentials were not supplied, so SSH was not attempted."
    else:
        try:
            result.ssh_status, result.ssh_message, result.checks = collect_commands(
                target, credentials, checks, logger, cancelled
            )
        except CollectionError as exc:
            result.ssh_status = Status.DOWN
            result.ssh_message = str(exc)
            logger.error("%s: %s", target.name, exc)
    if solarwinds_collector is not None and not (cancelled and cancelled()):
        result.checks.append(solarwinds_collector.collect_active_alerts(target))
    return finalise_device(result)
