import csv
import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from cisco_operations_hub.adapters.connectivity_evidence import (
    CONNECTIVITY_ROOT,
    ConnectivityEvidenceAdapter,
)


def manual_values(output_root: Path) -> dict[str, object]:
    return {
        "host": "192.0.2.10",
        "name": "LAB-EDGE-01",
        "site": "Example Mobile Site",
        "transport": "cellular",
        "site_type": "mobile_unit",
        "platform": "cisco_xe",
        "edge_role": "single",
        "service_vrfs": "10,20",
        "solarwinds_alerts": "false",
        "output_root": str(output_root),
        "max_devices": 20,
        "ping_count": 15,
        "ping_timeout": 2,
    }


def test_manual_cellular_plan_preserves_conditional_checks(tmp_path: Path) -> None:
    result = ConnectivityEvidenceAdapter().validate(manual_values(tmp_path))

    assert result.valid is True
    assert result.details["devices"] == 1
    assert result.details["planned_checks"] == 7
    assert "show cellular 0/2/0 radio" in result.details["commands_by_device"]["LAB-EDGE-01"]


def test_solarwinds_request_is_visible_in_dry_run_plan(tmp_path: Path) -> None:
    values = manual_values(tmp_path)
    values["solarwinds_alerts"] = "true"

    result = ConnectivityEvidenceAdapter().validate(values)

    assert result.details["planned_checks"] == 8
    assert result.details["solarwinds"] == "planned"


def test_dry_run_report_performs_no_live_collection(tmp_path: Path) -> None:
    result = ConnectivityEvidenceAdapter().run(manual_values(tmp_path), apply=False)

    reports = list(result.output_directory.glob("*/**/*connectivity*.json"))
    assert result.status == "success"
    assert len(reports) == 1
    payload = json.loads(reports[0].read_text(encoding="utf-8"))
    assert payload["meta"]["dry_run"] is True
    assert payload["overall_status"] == "planned"
    assert payload["devices"][0]["ping"]["raw_output"] == ""


def test_live_collection_requires_confirmation_before_credentials(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="RUN LIVE READ-ONLY COMMANDS"):
        ConnectivityEvidenceAdapter().run(manual_values(tmp_path), apply=True)


def test_json_inventory_processes_all_sites_without_a_site_filter(tmp_path: Path) -> None:
    values = manual_values(tmp_path)
    values.pop("host")
    values["site"] = ""
    values["inventory_file"] = str(CONNECTIVITY_ROOT / "data" / "inventory.example.json")

    result = ConnectivityEvidenceAdapter().validate(values)

    assert result.details["devices"] == 2
    assert result.details["site_count"] == 2
    assert result.details["sites"] == ["Example Cellular Site", "Example Fixed Site"]


def test_inventory_scope_exposes_site_and_device_choices(tmp_path: Path) -> None:
    values = manual_values(tmp_path)
    values.pop("host")
    values["inventory_file"] = str(CONNECTIVITY_ROOT / "data" / "inventory.example.json")

    scope = ConnectivityEvidenceAdapter().inventory_scope(values)

    assert scope["device_count"] == 2
    assert scope["site_count"] == 2
    assert all({"id", "name", "site", "host"} <= device.keys() for device in scope["devices"])


def test_selected_sites_limit_the_validated_scope(tmp_path: Path) -> None:
    values = manual_values(tmp_path)
    values.pop("host")
    values["inventory_file"] = str(CONNECTIVITY_ROOT / "data" / "inventory.example.json")
    values["scope_mode"] = "sites"
    values["selected_sites"] = json.dumps(["Example Fixed Site"])

    result = ConnectivityEvidenceAdapter().validate(values)

    assert result.details["devices"] == 1
    assert result.details["sites"] == ["Example Fixed Site"]


def test_selected_devices_support_cross_site_scope_and_batch_plan(tmp_path: Path) -> None:
    adapter = ConnectivityEvidenceAdapter()
    values = manual_values(tmp_path)
    values.pop("host")
    values["inventory_file"] = str(CONNECTIVITY_ROOT / "data" / "inventory.example.json")
    scope = adapter.inventory_scope(values)
    values["scope_mode"] = "devices"
    values["selected_devices"] = json.dumps([device["id"] for device in scope["devices"]])
    values["concurrent_workers"] = 1

    result = adapter.validate(values)

    assert result.details["devices"] == 2
    assert result.details["site_count"] == 2
    assert result.details["concurrent_workers"] == 1
    assert result.details["estimated_batches"] == 2


def test_empty_selected_scope_is_rejected(tmp_path: Path) -> None:
    values = manual_values(tmp_path)
    values.pop("host")
    values["inventory_file"] = str(CONNECTIVITY_ROOT / "data" / "inventory.example.json")
    values["scope_mode"] = "devices"
    values["selected_devices"] = "[]"

    with pytest.raises(ValueError, match="contains no devices"):
        ConnectivityEvidenceAdapter().validate(values)


def test_inventory_ignores_manual_site_label_and_writes_site_reports(tmp_path: Path) -> None:
    values = manual_values(tmp_path)
    values.pop("host")
    values["site"] = "Example Cellular Site"
    values["inventory_file"] = str(CONNECTIVITY_ROOT / "data" / "inventory.example.json")

    result = ConnectivityEvidenceAdapter().run(values, apply=False)
    summary = json.loads((result.output_directory / "run_summary.json").read_text(encoding="utf-8"))

    assert summary["site_count"] == 2
    assert summary["device_count"] == 2
    assert {item["site"] for item in summary["sites"]} == {
        "Example Cellular Site",
        "Example Fixed Site",
    }
    assert (result.output_directory / "run_summary.html").is_file()
    assert all(
        (result.output_directory / item["html_report"]).is_file() for item in summary["sites"]
    )


def test_xlsx_inventory_preserves_service_vrfs(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        ["site", "name", "host", "platform", "transport", "site_type", "edge_role", "service_vrfs"]
    )
    sheet.append(
        [
            "Example Branch",
            "LAB-EDGE-02",
            "192.0.2.20",
            "cisco_xe",
            "fixed",
            "branch",
            "single",
            "10,20",
        ]
    )
    inventory = tmp_path / "connectivity.xlsx"
    workbook.save(inventory)
    workbook.close()
    values = manual_values(tmp_path)
    values.pop("host")
    values["site"] = "Example Branch"
    values["inventory_file"] = str(inventory)

    result = ConnectivityEvidenceAdapter().validate(values)

    assert result.details["devices"] == 1
    assert result.details["planned_checks"] == 5


def test_default_limit_stops_more_than_ten_selected_devices(tmp_path: Path) -> None:
    inventory = tmp_path / "large_inventory.csv"
    with inventory.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["site", "name", "host"])
        writer.writeheader()
        for number in range(1, 12):
            writer.writerow(
                {
                    "site": "Example Branch",
                    "name": f"LAB-EDGE-{number:02d}",
                    "host": f"192.0.2.{number}",
                }
            )
    values = manual_values(tmp_path)
    values.pop("host")
    values["inventory_file"] = str(inventory)
    values["site"] = "Example Branch"
    values["max_devices"] = 10

    with pytest.raises(ValueError, match="selected scope has 11 devices"):
        ConnectivityEvidenceAdapter().validate(values)


def test_deliberate_limit_increase_returns_large_run_warning(tmp_path: Path) -> None:
    inventory = tmp_path / "large_inventory.csv"
    rows = ["site,name,host"] + [
        f"Example Branch,LAB-EDGE-{number:02d},198.51.100.{number}" for number in range(1, 12)
    ]
    inventory.write_text("\n".join(rows), encoding="utf-8")
    values = manual_values(tmp_path)
    values.pop("host")
    values["inventory_file"] = str(inventory)
    values["site"] = "Example Branch"
    values["max_devices"] = 11

    result = ConnectivityEvidenceAdapter().validate(values)

    assert result.details["devices"] == 11
    assert "large_run_warning" in result.details
