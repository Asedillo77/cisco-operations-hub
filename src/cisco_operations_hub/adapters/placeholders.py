from __future__ import annotations

from typing import Any

from ..contracts import RunResult, ToolDescription, ValidationResult


class PlaceholderAdapter:
    def __init__(self, tool_id: str, name: str, summary: str) -> None:
        self._description = ToolDescription(
            tool_id=tool_id,
            name=name,
            summary=summary,
            safety="Not enabled in this milestone.",
            available=False,
            unavailable_reason="The preserved tool is awaiting its behavior-preserving adapter.",
        )

    def describe(self) -> ToolDescription:
        return self._description

    def validate(self, values: dict[str, Any]) -> ValidationResult:
        del values
        return ValidationResult(False, self._description.unavailable_reason)

    def run(self, values: dict[str, Any], *, apply: bool) -> RunResult:
        del values, apply
        raise RuntimeError(self._description.unavailable_reason)
