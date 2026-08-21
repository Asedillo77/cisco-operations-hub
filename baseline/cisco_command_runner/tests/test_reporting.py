import csv
import json
from pathlib import Path

from cisco_command_runner.models import CommandResult
from cisco_command_runner.reporting import build_report, write_reports


def _result(output: str) -> CommandResult:
    return CommandResult(
        inventory_row=2,
        hostname="SW1",
        ip_address="192.0.2.1",
        detected_hostname="SW1",
        device_type="switch",
        command_number=1,
        command="show running-config",
        status="success",
        started_at="2026-08-19T10:00:00+10:00",
        finished_at="2026-08-19T10:00:01+10:00",
        duration_seconds=1.0,
        message="Command completed successfully.",
        output=output,
    )


def test_all_report_formats_are_created_and_expandable(tmp_path: Path) -> None:
    template_dir = Path(__file__).parents[1] / "templates"
    report = build_report("apply", 1, 1, [_result("line one\nline two")])
    run_dir = write_reports(report, tmp_path, template_dir)
    expected = {
        "command_results_short.html",
        "command_results_standard.html",
        "command_results.json",
        "command_results_summary.csv",
        "command_results_detail.csv",
    }
    assert expected.issubset({path.name for path in run_dir.iterdir()})
    short_html = (run_dir / "command_results_short.html").read_text(encoding="utf-8")
    assert "Hostname" in short_html
    assert "Show full result" in short_html
    assert "line one\nline two" in short_html
    assert "width: max-content" in short_html
    assert "min-width: 100%" in short_html
    assert "table-layout: auto" in short_html
    assert "white-space: nowrap" in short_html

    data = json.loads((run_dir / "command_results.json").read_text(encoding="utf-8"))
    assert data["counts"]["success"] == 1
    with (run_dir / "command_results_detail.csv").open(encoding="utf-8-sig", newline="") as file:
        assert next(csv.DictReader(file))["output"] == "line one\nline two"


def test_secret_bearing_output_is_redacted(tmp_path: Path) -> None:
    template_dir = Path(__file__).parents[1] / "templates"
    report = build_report("apply", 1, 1, [_result("enable secret VerySecretValue")])
    run_dir = write_reports(report, tmp_path, template_dir)
    content = (run_dir / "command_results.json").read_text(encoding="utf-8")
    assert "VerySecretValue" not in content
    assert "<redacted>" in content


def test_back_to_back_reports_use_separate_run_folders(tmp_path: Path) -> None:
    template_dir = Path(__file__).parents[1] / "templates"
    first = build_report("dry-run", 1, 1, [_result("")])
    second = build_report("dry-run", 1, 1, [_result("")])
    assert write_reports(first, tmp_path, template_dir) != write_reports(
        second, tmp_path, template_dir
    )


def test_common_summary_is_explicit_and_full_output_is_preserved(tmp_path: Path) -> None:
    template_dir = Path(__file__).parents[1] / "templates"
    output = "Cisco IOS XE Software, Version 17.12.07b\nROM: 17.6(8.1r)"
    result = _result(output)
    result.command = "show version"
    report = build_report("apply", 1, 1, [result], result_handling="common_summary")
    run_dir = write_reports(report, tmp_path, template_dir)
    item = report.results[0]
    assert item.extracted_fields["IOS Version"] == "17.12.07b"
    assert item.result_summary.startswith("IOS Version: 17.12.07b")
    assert item.output == output
    html = (run_dir / "command_results_short.html").read_text(encoding="utf-8")
    assert "<strong>IOS Version:</strong> 17.12.07b" in html
    assert output in html


def test_device_identity_cells_are_grouped_across_command_rows(tmp_path: Path) -> None:
    template_dir = Path(__file__).parents[1] / "templates"
    first = _result("first output")
    second = _result("second output")
    second.command_number = 2
    second.command = "show inventory"
    report = build_report("apply", 1, 2, [first, second])
    run_dir = write_reports(report, tmp_path, template_dir)

    short_html = (run_dir / "command_results_short.html").read_text(encoding="utf-8")
    standard_html = (run_dir / "command_results_standard.html").read_text(encoding="utf-8")
    assert short_html.count('rowspan="2"') == 2
    assert standard_html.count('rowspan="2"') == 4
    assert short_html.count(">SW1</td>") == 1
    assert short_html.count(">192.0.2.1</td>") == 1
    assert "<th>Result</th><th>Summary</th>" in short_html
