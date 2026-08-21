from __future__ import annotations

import difflib
import re

REDACT_PATTERNS = (
    re.compile(r"^(\s*(?:enable\s+)?secret(?:\s+\d+)?\s+).+$", re.IGNORECASE),
    re.compile(r"^(\s*password(?:\s+\d+)?\s+).+$", re.IGNORECASE),
    re.compile(r"^(\s*username\s+\S+.*?\s(?:password|secret)(?:\s+\d+)?\s+).+$", re.IGNORECASE),
    re.compile(r"^(\s*snmp-server\s+community\s+)\S+(.*)$", re.IGNORECASE),
    re.compile(r"^(\s*(?:key|string|pre-shared-key)\s+).+$", re.IGNORECASE),
)


def build_command_diffs(
    precheck_outputs: dict[str, str],
    postcheck_outputs: dict[str, str],
) -> list[dict[str, object]]:
    details = []
    for command in sorted(set(precheck_outputs) | set(postcheck_outputs)):
        before_lines = _report_lines(precheck_outputs.get(command, ""))
        after_lines = _report_lines(postcheck_outputs.get(command, ""))
        changed_lines = _changed_lines(before_lines, after_lines)
        if changed_lines:
            details.append(
                {
                    "command": command,
                    "added_count": sum(line["kind"] == "added" for line in changed_lines),
                    "removed_count": sum(line["kind"] == "removed" for line in changed_lines),
                    "lines": changed_lines,
                }
            )
    return details


def _changed_lines(before_lines: list[str], after_lines: list[str]) -> list[dict[str, str]]:
    changes = []
    for line in difflib.ndiff(before_lines, after_lines):
        marker = line[:2]
        text = line[2:]
        if not text.strip():
            continue
        if marker == "- ":
            changes.append({"kind": "removed", "text": text})
        elif marker == "+ ":
            changes.append({"kind": "added", "text": text})
    return changes


def _report_lines(output: str) -> list[str]:
    return [_redact_line(line.rstrip()) for line in output.splitlines() if line.strip()]


def _redact_line(line: str) -> str:
    for pattern in REDACT_PATTERNS:
        match = pattern.match(line)
        if not match:
            continue
        if len(match.groups()) == 2:
            return f"{match.group(1)}<redacted>{match.group(2)}"
        return f"{match.group(1)}<redacted>"
    return line
