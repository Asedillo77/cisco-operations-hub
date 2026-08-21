from __future__ import annotations

import csv
import json
import re
from pathlib import Path

SAFE_PREFIXES = ("show", "ping", "traceroute")
BLOCKED_PATTERNS = (
    r"^conf(?:igure)?(?:\s+terminal)?\b",
    r"^reload\b",
    r"^write(?:\s|$)",
    r"^erase(?:\s|$)",
    r"^delete(?:\s|$)",
    r"^copy(?:\s|$)",
    r"^no(?:\s|$)",
    r"^shutdown(?:\s|$)",
    r"^enable(?:\s|$)",
    r"^terminal\s+monitor\b",
    r"[\r\n]",
)


def parse_command_text(text: str) -> list[str]:
    return validate_commands(
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def load_commands(path: Path) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(f"Command file was not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return parse_command_text(path.read_text(encoding="utf-8-sig"))
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        values = data.get("commands") if isinstance(data, dict) else data
        if not isinstance(values, list):
            raise ValueError("Command JSON must be a list or contain a commands list.")
        return validate_commands(str(value).strip() for value in values)
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or "command" not in {
                name.strip().lower() for name in reader.fieldnames
            }:
                raise ValueError("Command CSV requires a command column.")
            rows = []
            for row in reader:
                normalized = {str(key).strip().lower(): value for key, value in row.items()}
                rows.append(str(normalized.get("command") or "").strip())
            return validate_commands(rows)
    raise ValueError("Command file must be TXT, CSV, or JSON.")


def validate_commands(commands: object) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    errors: list[str] = []
    for number, value in enumerate(commands, start=1):
        command = str(value).strip()
        if not command:
            continue
        lowered = command.lower()
        if any(re.search(pattern, lowered) for pattern in BLOCKED_PATTERNS):
            errors.append(f"Command {number} is blocked: {command}")
            continue
        if not lowered.startswith(SAFE_PREFIXES):
            errors.append(f"Command {number} is not an approved operational command: {command}")
            continue
        if lowered not in seen:
            seen.add(lowered)
            clean.append(command)
    if errors:
        raise ValueError("Command validation failed:\n" + "\n".join(errors))
    if not clean:
        raise ValueError("At least one command is required.")
    return clean
