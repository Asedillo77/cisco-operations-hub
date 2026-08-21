from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from time import monotonic

from .models import CommandResult, DeviceTarget

NETMIKO_TYPES = {"switch": "cisco_ios", "edge_router": "cisco_ios"}


def plan_results(devices: list[DeviceTarget], commands: list[str]) -> list[CommandResult]:
    timestamp = _now()
    return [
        CommandResult(
            inventory_row=device.row_number,
            hostname=device.hostname,
            ip_address=device.ip_address,
            detected_hostname="",
            device_type=device.device_type,
            command_number=number,
            command=command,
            status="planned",
            started_at=timestamp,
            finished_at=timestamp,
            duration_seconds=0.0,
            message="Validated; no SSH connection was made in dry-run mode.",
        )
        for device in devices
        for number, command in enumerate(commands, start=1)
    ]


def execute_inventory(
    devices: list[DeviceTarget],
    commands: list[str],
    credentials: dict[str, str | int],
    max_workers: int,
    logger: logging.Logger,
) -> list[CommandResult]:
    workers = min(max(1, max_workers), len(devices))
    results: list[CommandResult] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="device") as executor:
        futures = {
            executor.submit(_execute_device, device, commands, credentials, logger): device
            for device in devices
        }
        for future in as_completed(futures):
            device = futures[future]
            try:
                results.extend(future.result())
            except Exception as exc:  # defensive boundary around a device worker
                logger.exception("Unexpected worker failure for %s", device.connection_target)
                results.extend(_device_failure_results(device, commands, str(exc)))
    return sorted(results, key=lambda item: (item.inventory_row, item.command_number))


def _execute_device(
    device: DeviceTarget,
    commands: list[str],
    credentials: dict[str, str | int],
    logger: logging.Logger,
) -> list[CommandResult]:
    from netmiko import ConnectHandler

    connection_data = {
        "device_type": NETMIKO_TYPES[device.device_type],
        "host": device.connection_target,
        "username": credentials["username"],
        "password": credentials["password"],
        "port": credentials.get("port", 22),
        "timeout": credentials.get("timeout", 30),
    }
    if credentials.get("secret"):
        connection_data["secret"] = credentials["secret"]

    logger.info("Row %s: connecting to %s", device.row_number, device.connection_target)
    try:
        connection = ConnectHandler(**connection_data)
    except Exception as exc:
        logger.error("Row %s: connection failed: %s", device.row_number, exc)
        return _device_failure_results(device, commands, f"SSH connection failed: {exc}")

    results: list[CommandResult] = []
    detected_hostname = ""
    try:
        detected_hostname = _hostname_from_prompt(connection.find_prompt())
        if credentials.get("secret"):
            logger.info("Row %s: entering enable mode", device.row_number)
            connection.enable()
        for number, command in enumerate(commands, start=1):
            started_at = _now()
            start = monotonic()
            logger.info("Row %s command %s: %s", device.row_number, number, command)
            try:
                output = connection.send_command(command, read_timeout=90)
                status, message = "success", "Command completed successfully."
            except Exception as exc:
                output = ""
                status, message = "failed", f"Command failed: {exc}"
                logger.error("Row %s command %s failed: %s", device.row_number, number, exc)
            results.append(
                CommandResult(
                    inventory_row=device.row_number,
                    hostname=device.hostname,
                    ip_address=device.ip_address,
                    detected_hostname=detected_hostname,
                    device_type=device.device_type,
                    command_number=number,
                    command=command,
                    status=status,
                    started_at=started_at,
                    finished_at=_now(),
                    duration_seconds=round(monotonic() - start, 3),
                    message=message,
                    output=output,
                )
            )
    finally:
        logger.info("Row %s: disconnecting from %s", device.row_number, device.connection_target)
        connection.disconnect()
    return results


def _device_failure_results(
    device: DeviceTarget, commands: list[str], message: str
) -> list[CommandResult]:
    timestamp = _now()
    return [
        CommandResult(
            inventory_row=device.row_number,
            hostname=device.hostname,
            ip_address=device.ip_address,
            detected_hostname="",
            device_type=device.device_type,
            command_number=number,
            command=command,
            status="failed",
            started_at=timestamp,
            finished_at=timestamp,
            duration_seconds=0.0,
            message=message,
        )
        for number, command in enumerate(commands, start=1)
    ]


def _hostname_from_prompt(prompt: str) -> str:
    return prompt.strip().rstrip("#>").split("(", 1)[0].strip()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
