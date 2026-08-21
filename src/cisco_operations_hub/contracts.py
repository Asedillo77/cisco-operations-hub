from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolField:
    name: str
    label: str
    kind: str = "text"
    required: bool = False
    help_text: str = ""
    default: str | int | bool = ""
    apply_only: bool = False
    options: tuple[tuple[str, str], ...] = ()
    picker: str = ""
    extensions: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ToolDescription:
    tool_id: str
    name: str
    summary: str
    safety: str
    available: bool
    fields: tuple[ToolField, ...] = ()
    unavailable_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["fields"] = [asdict(item) for item in self.fields]
        return value


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunResult:
    status: str
    message: str
    output_directory: Path
    logs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "output_directory": str(self.output_directory),
            "logs": list(self.logs),
        }


class ToolAdapter(Protocol):
    def describe(self) -> ToolDescription: ...

    def validate(self, values: dict[str, Any]) -> ValidationResult: ...

    def run(self, values: dict[str, Any], *, apply: bool) -> RunResult: ...
