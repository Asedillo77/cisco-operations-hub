from pathlib import Path

import pytest
from openpyxl import Workbook

from cisco_operations_hub.adapters.health_monitor import (
    HEALTH_MONITOR_ROOT,
    HealthMonitorAdapter,
)

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = HEALTH_MONITOR_ROOT / "samples" / "inventory.csv"


def request_values(output_root: Path) -> dict[str, object]:
    return {
        "inventory_file": str(INVENTORY),
        "config_dir": str(HEALTH_MONITOR_ROOT / "configs"),
        "output_root": str(output_root),
        "max_devices": 50,
        "max_workers": 3,
    }


def test_validate_uses_preserved_inventory_and_profiles(tmp_path: Path) -> None:
    result = HealthMonitorAdapter().validate(request_values(tmp_path))

    assert result.valid is True
    assert result.details["devices"] == 2
    assert result.details["planned_checks"] > 2
    assert set(result.details["commands_by_device_type"]) == {"switch", "edge_router"}


def test_dry_run_publishes_complete_ready_report(tmp_path: Path) -> None:
    result = HealthMonitorAdapter().run(request_values(tmp_path), apply=False)

    assert result.status == "success"
    assert result.output_directory.parent.name == "ready"
    assert (result.output_directory / "report.html").is_file()
    assert (result.output_directory / "report.json").is_file()
    assert (result.output_directory / "notification.json").is_file()
    assert (result.output_directory / "complete.json").is_file()


def test_xlsx_inventory_matches_csv_device_and_check_counts(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["hostname", "ip_address", "device_type", "enabled"])
    sheet.append(["LAB-SW-01", "192.0.2.10", "switch", True])
    sheet.append(["LAB-ER-01", "192.0.2.11", "edge_router", True])
    xlsx_path = tmp_path / "inventory.xlsx"
    workbook.save(xlsx_path)
    workbook.close()
    values = request_values(tmp_path / "reports")
    values["inventory_file"] = str(xlsx_path)

    result = HealthMonitorAdapter().validate(values)

    assert result.details["devices"] == 2
    assert result.details["planned_checks"] == 14


def test_live_run_requires_credentials_and_confirmation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="RUN LIVE READ-ONLY COMMANDS"):
        HealthMonitorAdapter().run(request_values(tmp_path), apply=True)
