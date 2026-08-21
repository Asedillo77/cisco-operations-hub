from __future__ import annotations

import re

SHOW_VERSION_PATTERNS = (
    ("IOS Version", re.compile(r"(?im)^Cisco IOS XE Software,\s*Version\s+(\S+)")),
    ("ROM Version", re.compile(r"(?im)^ROM:\s*(.+?)\s*$")),
    ("Uptime", re.compile(r"(?im)^\S+\s+uptime is\s+(.+?)\s*$")),
    ("Reload Reason", re.compile(r"(?im)^Last reload reason:\s*(.+?)\s*$")),
    ("Model", re.compile(r"(?im)^cisco\s+(\S+)\s+\(.+?\)\s+processor\b")),
    ("Serial Number", re.compile(r"(?im)^Processor board ID\s+(\S+)")),
    ("System Image", re.compile(r'(?im)^System image file is\s+"?([^"\r\n]+)"?\s*$')),
)


def summarize_result(command: str, output: str) -> tuple[str, dict[str, str]]:
    if not _is_show_version(command) or not output.strip():
        return "", {}

    fields: dict[str, str] = {}
    for label, pattern in SHOW_VERSION_PATTERNS:
        match = pattern.search(output)
        if match:
            fields[label] = match.group(1).strip()
    summary = " · ".join(f"{label}: {value}" for label, value in fields.items())
    return summary, fields


def _is_show_version(command: str) -> bool:
    base_command = command.strip().lower().split("|", 1)[0].strip()
    return base_command in {"show version", "sh version", "sho version"}
