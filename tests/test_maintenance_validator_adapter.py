import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from cisco_operations_hub.adapters.maintenance_validator import (
    MAINTENANCE_ROOT,
    MaintenanceValidatorAdapter,
)


def precheck_values(output_root: Path) -> dict[str, object]:
    return {
        "operation": "precheck",
        "hostname": "192.0.2.10",
        "device_type": "switch",
        "output_root": str(output_root),
        "max_workers": 3,
        "max_devices": 20,
        "delay_minutes": 50,
    }


def test_offline_sample_is_available_without_targets(tmp_path: Path) -> None:
    result = MaintenanceValidatorAdapter().validate(
        {"operation": "mock", "output_root": str(tmp_path)}
    )

    assert result.valid is True
    assert result.details["connections"] == 0


def test_precheck_validation_uses_preserved_switch_profile(tmp_path: Path) -> None:
    result = MaintenanceValidatorAdapter().validate(precheck_values(tmp_path))

    assert result.details["devices"] == 1
    assert result.details["planned_commands"] > 10
    assert "show version" in result.details["commands_by_device"]["192.0.2.10"]


def test_edge_router_profile_preserves_version_comparisons(tmp_path: Path) -> None:
    values = precheck_values(tmp_path)
    values["device_type"] = "edge_router"

    result = MaintenanceValidatorAdapter().validate(values)
    commands = result.details["commands_by_device"]["192.0.2.10"]

    assert "show version" in commands
    assert len(commands) == 7


def test_precheck_dry_run_writes_html_and_json_plan(tmp_path: Path) -> None:
    result = MaintenanceValidatorAdapter().run(precheck_values(tmp_path), apply=False)

    assert (result.output_directory / "maintenance_plan.html").is_file()
    payload = json.loads(
        (result.output_directory / "maintenance_plan.json").read_text(encoding="utf-8")
    )
    assert payload["dry_run"] is True
    assert payload["details"]["workflow"] == "precheck"


def test_live_collection_requires_exact_confirmation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="RUN LIVE READ-ONLY COMMANDS"):
        MaintenanceValidatorAdapter().run(precheck_values(tmp_path), apply=True)


def test_xlsx_inventory_supports_switch_and_edge_router(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["hostname", "device_type"])
    sheet.append(["192.0.2.10", "switch"])
    sheet.append(["192.0.2.11", "edge_router"])
    inventory = tmp_path / "maintenance.xlsx"
    workbook.save(inventory)
    workbook.close()
    values = precheck_values(tmp_path)
    values.pop("hostname")
    values["inventory_file"] = str(inventory)

    result = MaintenanceValidatorAdapter().validate(values)

    assert result.details["devices"] == 2
    assert result.details["estimated_batches"] == 1


def test_offline_sample_renders_preserved_reports(tmp_path: Path) -> None:
    result = MaintenanceValidatorAdapter().run(
        {"operation": "mock", "output_root": str(tmp_path)}, apply=False
    )

    reports = result.output_directory / "reports"
    assert list(reports.glob("*.html"))
    assert list(reports.glob("*.json"))
    assert list(reports.glob("*.txt"))


def test_preserved_maintenance_source_is_present() -> None:
    assert (MAINTENANCE_ROOT / "src" / "network_prepost_check" / "compare.py").is_file()
