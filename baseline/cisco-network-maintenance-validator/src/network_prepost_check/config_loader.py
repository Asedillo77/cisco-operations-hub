from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_command_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    commands = config.get("commands")
    if not isinstance(commands, list) or not commands:
        raise ValueError(f"Command config has no usable commands list: {config_path}")

    cleaned_commands = []
    for command in commands:
        if not isinstance(command, str) or not command.strip():
            raise ValueError(f"Command config contains an invalid command: {command!r}")
        cleaned_commands.append(command.strip())

    config["commands"] = cleaned_commands
    config.setdefault("netmiko_device_type", "cisco_ios")
    return config
