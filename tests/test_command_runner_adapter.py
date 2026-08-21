from pathlib import Path

import pytest

from cisco_operations_hub.adapters import command_runner
from cisco_operations_hub.adapters.command_runner import CommandRunnerAdapter

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "baseline" / "cisco_command_runner" / "samples" / "inventory.csv"


def request_values(output_root: Path) -> dict[str, object]:
    return {
        "inventory_file": str(INVENTORY),
        "commands_text": "show version\nshow interfaces status",
        "output_root": str(output_root),
        "max_devices": 50,
        "max_workers": 3,
        "result_handling": "complete",
    }


def test_validate_uses_preserved_inventory_and_command_logic(tmp_path: Path) -> None:
    result = CommandRunnerAdapter().validate(request_values(tmp_path))

    assert result.valid is True
    assert result.details["devices"] == 2
    assert result.details["commands"] == ["show version", "show interfaces status"]


def test_blocked_command_is_rejected(tmp_path: Path) -> None:
    values = request_values(tmp_path)
    values["commands_text"] = "reload"

    with pytest.raises(ValueError, match="blocked"):
        CommandRunnerAdapter().validate(values)


def test_command_file_uses_preserved_loader(tmp_path: Path) -> None:
    command_file = tmp_path / "commands.csv"
    command_file.write_text("command\nshow version\nshow ip route\n", encoding="utf-8")
    values = request_values(tmp_path)
    values["commands_text"] = ""
    values["commands_file"] = str(command_file)

    result = CommandRunnerAdapter().validate(values)

    assert result.details["commands"] == ["show version", "show ip route"]


def test_command_file_and_manual_commands_are_mutually_exclusive(tmp_path: Path) -> None:
    values = request_values(tmp_path)
    values["commands_file"] = str(tmp_path / "commands.txt")

    with pytest.raises(ValueError, match="not both"):
        CommandRunnerAdapter().validate(values)


def test_dry_run_creates_preserved_reports_without_credentials(tmp_path: Path) -> None:
    result = CommandRunnerAdapter().run(request_values(tmp_path), apply=False)

    assert result.status == "success"
    assert (result.output_directory / "command_results_short.html").is_file()
    assert (result.output_directory / "command_results_standard.html").is_file()
    assert (result.output_directory / "command_results.json").is_file()


def test_live_run_requires_exact_confirmation(tmp_path: Path) -> None:
    values = request_values(tmp_path)
    values["credentials_file"] = "credentials.txt"

    with pytest.raises(ValueError, match="RUN LIVE READ-ONLY COMMANDS"):
        CommandRunnerAdapter().run(values, apply=True)


def test_missing_netmiko_returns_installation_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = request_values(tmp_path)
    values["credentials_file"] = "credentials.txt"
    values["confirmation"] = "RUN LIVE READ-ONLY COMMANDS"
    monkeypatch.setattr(command_runner, "find_spec", lambda _name: None)

    with pytest.raises(RuntimeError, match="uv sync"):
        CommandRunnerAdapter().run(values, apply=True)
