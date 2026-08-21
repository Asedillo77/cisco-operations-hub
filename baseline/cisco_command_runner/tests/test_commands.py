from pathlib import Path

import pytest

from cisco_command_runner.commands import load_commands, parse_command_text


def test_operational_commands_are_normalized_and_deduplicated() -> None:
    assert parse_command_text("show version\nSHOW VERSION\nping 192.0.2.1\n") == [
        "show version",
        "ping 192.0.2.1",
    ]


@pytest.mark.parametrize(
    "command",
    ["configure terminal", "reload", "write memory", "delete flash:test", "shutdown"],
)
def test_configuration_and_destructive_commands_are_blocked(command: str) -> None:
    with pytest.raises(ValueError, match="blocked"):
        parse_command_text(command)


def test_unknown_command_prefix_is_rejected() -> None:
    with pytest.raises(ValueError, match="not an approved operational command"):
        parse_command_text("clear counters")


def test_load_json_profile(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"
    path.write_text('{"commands": ["show version"]}', encoding="utf-8")
    assert load_commands(path) == ["show version"]
