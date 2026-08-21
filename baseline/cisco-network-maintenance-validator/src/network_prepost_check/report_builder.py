from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .compare import summarize_results


def local_report_timestamp() -> str:
    now = datetime.now().astimezone()
    timezone_name = now.tzname() or now.strftime("%z")
    return f"{now:%Y-%m-%d %H:%M:%S} {timezone_name}"


def build_report_data(
    hostname: str,
    connection_target: str,
    device_type: str,
    comparison_results: list[dict[str, Any]],
    precheck_file: Path,
    postcheck_file: Path,
    delay_minutes: int,
    diff_details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sorted_results = sorted(
        comparison_results,
        key=lambda item: (-int(item["sort_order"]), item["command"]),
    )
    summary = summarize_results(sorted_results)
    return {
        "hostname": hostname,
        "connection_target": connection_target,
        "device_type": device_type,
        "report_generated_at": local_report_timestamp(),
        "delay_minutes": delay_minutes,
        "precheck_file": str(precheck_file),
        "postcheck_file": str(postcheck_file),
        "summary": summary,
        "results": sorted_results,
        "diff_details": diff_details or [],
    }


def write_reports(
    report_data: dict[str, Any], reports_dir: Path, template_path: Path
) -> dict[str, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    hostname = report_data["hostname"]
    json_file = reports_dir / f"{hostname}_postcheck_report.json"
    text_file = reports_dir / f"{hostname}_postcheck_report.txt"
    html_file = reports_dir / f"{hostname}_postcheck_report.html"

    json_file.write_text(json.dumps(report_data, indent=2, sort_keys=True), encoding="utf-8")
    text_file.write_text(render_text_report(report_data), encoding="utf-8")
    html_file.write_text(render_html_report(report_data, template_path), encoding="utf-8")

    return {"json": json_file, "text": text_file, "html": html_file}


def render_text_report(report_data: dict[str, Any]) -> str:
    summary = report_data["summary"]
    lines = [
        f"Network Maintenance Validation Report - {report_data['hostname']}",
        f"Connection Target: {report_data['connection_target']}",
        f"Device Type: {report_data['device_type']}",
        f"Generated: {report_data['report_generated_at']}",
        f"Postcheck Delay: {report_data['delay_minutes']} minute(s)",
        "",
        "Summary",
        f"Overall Status: {summary['overall_status'].upper()}",
        f"OK: {summary['ok_count']}",
        f"Expected: {summary['expected_count']}",
        f"Warning: {summary['warning_count']}",
        f"Critical: {summary['critical_count']}",
        "",
        "Results",
    ]
    for item in report_data["results"]:
        lines.append(
            f"[{item['severity'].upper()}] {item['command']} | {item.get('check', 'Output')} | "
            f"Before: {item['before']} | After: {item['after']} | {item['message']}"
        )
    lines.append("")
    return "\n".join(lines)


def render_html_report(report_data: dict[str, Any], template_path: Path) -> str:
    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError as exc:
        requirements_file = template_path.parent.parent / "requirements.txt"
        install_command = (
            f'python -m pip install -r "{requirements_file}"'
            if requirements_file.exists()
            else "python -m pip install jinja2"
        )
        raise RuntimeError(
            "Jinja2 is required to render HTML reports. "
            f"Install the report dependency with: {install_command}"
        ) from exc

    environment = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=True,
    )
    template = environment.get_template(template_path.name)
    return template.render(**report_data)
