"""Read-only Cisco SSH command collection through Netmiko."""

from __future__ import annotations

import logging
from collections.abc import Callable

from .credentials import Credentials
from .evaluation import evaluate_command
from .models import CommandResult, DeviceTarget, Status
from .profiles import CELLULAR_PROFILE, CommandCheck, cellular_collection_required


class CollectionError(RuntimeError):
    """Raised when an SSH session cannot be established."""


def collect_commands(
    target: DeviceTarget,
    credentials: Credentials,
    checks: list[CommandCheck],
    logger: logging.Logger,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[Status, str, list[CommandResult]]:
    """Connect once and collect each approved read-only command."""
    try:
        from netmiko import ConnectHandler
        from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException
    except ModuleNotFoundError as exc:
        raise CollectionError("Netmiko is required for live SSH collection.") from exc

    device = {
        "device_type": target.platform,
        "host": target.host,
        "username": credentials.username,
        "password": credentials.password,
        "secret": credentials.secret,
        "timeout": 20,
    }
    results: list[CommandResult] = []
    connection = None
    try:
        logger.info("Connecting to %s (%s)", target.name, target.host)
        connection = ConnectHandler(**device)
        if credentials.secret:
            connection.enable()
        for check in checks:
            if cancelled and cancelled():
                return Status.UNKNOWN, "Collection was cancelled.", results
            logger.info("Processing %s: %s", target.name, check.command)
            try:
                output = connection.send_command(check.command, read_timeout=30)
                results.append(evaluate_command(check, output, target))
            except Exception as exc:  # Each failed check remains visible in the report.
                logger.exception("Command failed for %s: %s", target.name, check.command)
                results.append(
                    CommandResult(
                        check.check_id,
                        check.command,
                        Status.UNKNOWN,
                        "The command could not be completed.",
                        str(exc),
                        "Review the device session and command support.",
                    )
                )
        if cellular_collection_required(target, results):
            logger.info("Cellular transport is relevant for %s; collecting cellular evidence", target.name)
            for check in CELLULAR_PROFILE:
                if cancelled and cancelled():
                    return Status.UNKNOWN, "Collection was cancelled.", results
                logger.info("Processing %s: %s", target.name, check.command)
                try:
                    output = connection.send_command(check.command, read_timeout=30)
                    results.append(evaluate_command(check, output, target))
                except Exception as exc:
                    logger.exception("Command failed for %s: %s", target.name, check.command)
                    results.append(
                        CommandResult(
                            check.check_id,
                            check.command,
                            Status.UNKNOWN,
                            "The command could not be completed.",
                            str(exc),
                            "Review the device session and command support.",
                        )
                    )
        else:
            logger.info("Skipping cellular commands for %s; cellular is not the active transport", target.name)
        return Status.HEALTHY, "SSH collection completed.", results
    except NetmikoAuthenticationException as exc:
        raise CollectionError("SSH authentication failed. Check the supplied credentials.") from exc
    except NetmikoTimeoutException as exc:
        raise CollectionError("SSH connection timed out.") from exc
    except Exception as exc:
        raise CollectionError(f"SSH collection failed: {exc}") from exc
    finally:
        if connection is not None:
            connection.disconnect()
