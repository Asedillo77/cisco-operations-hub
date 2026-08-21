import json
from pathlib import Path

from daily_network_health_monitor.models import Result
from daily_network_health_monitor.reporting import build_report, publish


def test_publish_creates_complete_ready_run(tmp_path: Path) -> None:
    result = Result(
        hostname="LAB-SW-01",
        ip_address="192.0.2.10",
        device_type="switch",
        inventory_row=2,
        command_number=1,
        command="show environment all",
        collection_status="success",
        health_status="healthy",
        message="Healthy.",
        output="FAN 1 OK",
    )
    report = build_report("mock", 1, [result])
    output = publish(report, tmp_path, Path("templates"))
    assert output.parent.name == "ready"
    assert (output / "report.html").exists()
    assert (output / "report.json").exists()
    assert (output / "notification.json").exists()
    assert (output / "complete.json").exists()
    assert not list((tmp_path / "staging").iterdir())
    notification = json.loads((output / "notification.json").read_text(encoding="utf-8"))
    assert notification["overall_status"] == "healthy"


def test_report_groups_repeated_device_and_type_cells(tmp_path: Path) -> None:
    results = [
        Result(
            hostname="LAB-SW-01",
            ip_address="192.0.2.10",
            device_type="switch",
            inventory_row=2,
            command_number=number,
            command=command,
            collection_status="success",
            health_status="healthy" if number == 1 else "warning",
            message="Healthy.",
        )
        for number, command in enumerate(("show switch", "show environment all"), start=1)
    ]
    output = publish(build_report("mock", 1, results), tmp_path, Path("templates"))
    html = (output / "report.html").read_text(encoding="utf-8")
    assert html.count("<strong>LAB-SW-01</strong>") == 1
    assert html.count('rowspan="2"') == 3
    assert "<th>Hostname</th><th>IP Address</th><th>Type</th>" in html
    assert 'data-filter="warning"' in html
    assert 'data-filter="critical"' in html
    assert 'data-filter="informational"' in html
    assert 'data-filter="failed"' in html
    assert 'data-group="2" data-health="healthy"' in html
    assert 'data-group="2" data-health="warning"' in html
    assert "function applyFilter(filter)" in html
    assert "placeGroupCells(cells, matches[0], matches.length)" in html


def test_failed_collection_is_highlighted_in_notification(tmp_path: Path) -> None:
    result = Result(
        hostname="LAB-SW-01",
        ip_address="192.0.2.10",
        device_type="switch",
        inventory_row=2,
        command_number=1,
        command="show switch",
        collection_status="failed",
        health_status="failed",
        message="SSH connection failed.",
    )
    output = publish(build_report("mock", 1, [result]), tmp_path, Path("templates"))
    notification = json.loads((output / "notification.json").read_text(encoding="utf-8"))
    assert notification["overall_status"] == "failed"
    assert notification["counts"]["failed"] == 1
    assert notification["highlights"][0]["status"] == "failed"
