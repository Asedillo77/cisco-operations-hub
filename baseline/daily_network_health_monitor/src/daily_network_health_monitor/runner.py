from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from time import monotonic

from .analysis import analyse
from .models import Device, Profile, Result


def plan(devices: list[Device], profiles: dict[str, Profile]) -> list[Result]:
    now = _now()
    return [
        Result(
            hostname=device.hostname,
            ip_address=device.ip_address,
            device_type=device.device_type,
            inventory_row=device.row_number,
            command_number=number,
            command=command,
            collection_status="planned",
            health_status="planned",
            message="Validated; no SSH connection was made in dry-run mode.",
            started_at=now,
            finished_at=now,
        )
        for device in devices
        for number, command in enumerate(profiles[device.device_type].commands, start=1)
    ]


def collect(
    devices: list[Device],
    profiles: dict[str, Profile],
    credentials: dict[str, str | int],
    max_workers: int,
    logger: logging.Logger,
) -> list[Result]:
    results: list[Result] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(devices))) as executor:
        futures = {
            executor.submit(
                _collect_device, device, profiles[device.device_type], credentials, logger
            ): device
            for device in devices
        }
        for future in as_completed(futures):
            device = futures[future]
            try:
                results.extend(future.result())
            except Exception as exc:
                logger.exception("Row %s: unexpected worker failure", device.row_number)
                results.extend(_failed_device(device, profiles[device.device_type], str(exc)))
    return sorted(results, key=lambda result: (result.inventory_row, result.command_number))


def _collect_device(
    device: Device,
    profile: Profile,
    credentials: dict[str, str | int],
    logger: logging.Logger,
) -> list[Result]:
    from netmiko import ConnectHandler

    connection_data = {
        "device_type": profile.netmiko_device_type,
        "host": device.target,
        "username": credentials["username"],
        "password": credentials["password"],
        "secret": credentials.get("secret", ""),
        "port": credentials.get("port", 22),
        "timeout": credentials.get("timeout", 30),
    }
    logger.info("Row %s: connecting to %s", device.row_number, device.target)
    try:
        connection = ConnectHandler(**connection_data)
    except Exception as exc:
        logger.error("Row %s: connection failed: %s", device.row_number, exc)
        return _failed_device(device, profile, f"SSH connection failed: {exc}")
    results: list[Result] = []
    try:
        try:
            detected_hostname = _hostname_from_prompt(connection.find_prompt())
        except Exception as exc:
            detected_hostname = ""
            logger.warning("Row %s: hostname prompt detection failed: %s", device.row_number, exc)
        report_hostname = device.hostname or detected_hostname
        if not device.hostname and detected_hostname:
            logger.info(
                "Row %s: detected hostname %s from device prompt",
                device.row_number,
                detected_hostname,
            )
        if credentials.get("secret"):
            connection.enable()
        for number, command in enumerate(profile.commands, start=1):
            started = _now()
            timer = monotonic()
            logger.info("Row %s command %s: %s", device.row_number, number, command)
            try:
                output = connection.send_command(command, read_timeout=90)
                health, message, metrics = analyse(command, output, profile)
                collection_status = "success"
            except Exception as exc:
                output, metrics = "", {}
                collection_status, health = "failed", "failed"
                message = f"Command failed: {exc}"
                logger.error("Row %s command %s failed: %s", device.row_number, number, exc)
            results.append(
                Result(
                    hostname=report_hostname,
                    ip_address=device.ip_address,
                    device_type=device.device_type,
                    inventory_row=device.row_number,
                    command_number=number,
                    command=command,
                    collection_status=collection_status,
                    health_status=health,
                    message=message,
                    output=output,
                    metrics=metrics,
                    started_at=started,
                    finished_at=_now(),
                    duration_seconds=round(monotonic() - timer, 3),
                )
            )
    finally:
        connection.disconnect()
    return results


def _failed_device(device: Device, profile: Profile, message: str) -> list[Result]:
    now = _now()
    return [
        Result(
            hostname=device.hostname,
            ip_address=device.ip_address,
            device_type=device.device_type,
            inventory_row=device.row_number,
            command_number=number,
            command=command,
            collection_status="failed",
            health_status="failed",
            message=message,
            started_at=now,
            finished_at=now,
        )
        for number, command in enumerate(profile.commands, start=1)
    ]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _hostname_from_prompt(prompt: str) -> str:
    return prompt.strip().rstrip("#>").split("(", 1)[0].strip()
