from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandRunResult:
    raw_outputs: dict[str, str]
    detected_hostname: str | None


def run_commands(
    hostname: str,
    commands: Iterable[str],
    credentials: dict[str, str | int],
    netmiko_device_type: str,
    logger: logging.Logger,
) -> CommandRunResult:
    try:
        from netmiko import ConnectHandler
    except ImportError as exc:
        raise RuntimeError("Netmiko is required for device connections.") from exc

    device = {
        "device_type": netmiko_device_type,
        "host": hostname,
        "username": credentials["username"],
        "password": credentials["password"],
        "port": credentials.get("port", 22),
        "timeout": credentials.get("timeout", 30),
    }
    if credentials.get("secret"):
        device["secret"] = credentials["secret"]

    outputs: dict[str, str] = {}
    logger.info("Connecting to %s", hostname)
    connection = ConnectHandler(**device)
    try:
        detected_hostname = _hostname_from_prompt(connection.find_prompt())
        if detected_hostname:
            logger.info("Connected device prompt hostname: %s", detected_hostname)
        if credentials.get("secret"):
            logger.debug("Entering enable mode when required")
            connection.enable()
        for index, command in enumerate(commands, start=1):
            logger.info("Running command %s: %s", index, command)
            outputs[command] = connection.send_command(command, read_timeout=90)
    finally:
        logger.info("Disconnecting from %s", hostname)
        connection.disconnect()

    return CommandRunResult(raw_outputs=outputs, detected_hostname=detected_hostname)


def _hostname_from_prompt(prompt: str) -> str | None:
    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        return None

    hostname = cleaned_prompt.rstrip("#>").split("(", 1)[0].strip()
    return hostname or None
