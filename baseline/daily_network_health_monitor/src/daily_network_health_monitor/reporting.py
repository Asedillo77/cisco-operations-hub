from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Report, Result

SEVERITY = {
    "planned": 0,
    "healthy": 0,
    "informational": 0,
    "unknown": 1,
    "warning": 2,
    "critical": 3,
    "failed": 4,
}


def build_report(mode: str, devices: int, results: list[Result]) -> Report:
    now = datetime.now().astimezone()
    overall = max((result.health_status for result in results), key=SEVERITY.get)
    return Report(
        run_id=now.strftime("%Y%m%d_%H%M%S_%f"),
        mode=mode,
        generated_at=now.isoformat(timespec="seconds"),
        overall_status=overall,
        requested_devices=devices,
        results=results,
    )


def publish(report: Report, output_root: Path, template_dir: Path) -> Path:
    staging_root = output_root / "staging"
    ready_root = output_root / "ready"
    staging_root.mkdir(parents=True, exist_ok=True)
    ready_root.mkdir(parents=True, exist_ok=True)
    run_name = f"network_health_{report.run_id}"
    staging_dir = staging_root / run_name
    ready_dir = ready_root / run_name
    staging_dir.mkdir(exist_ok=False)
    raw_dir = staging_dir / "raw_outputs"
    raw_dir.mkdir()
    try:
        environment = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(("html", "xml")),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        html = environment.get_template("health_report.html.j2").render(report=report)
        (staging_dir / "report.html").write_text(html, encoding="utf-8")
        (staging_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2), encoding="utf-8"
        )
        _write_raw(raw_dir, report.results)
        notification = _notification(report, run_name)
        (staging_dir / "notification.json").write_text(
            json.dumps(notification, indent=2), encoding="utf-8"
        )
        manifest = {
            "run_id": report.run_id,
            "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "overall_status": report.overall_status,
            "files": ["report.html", "report.json", "notification.json"],
        }
        (staging_dir / "complete.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        staging_dir.replace(ready_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return ready_dir


def _notification(report: Report, run_name: str) -> dict[str, object]:
    highlights = [
        {
            "device": result.hostname or result.ip_address,
            "command": result.command,
            "status": result.health_status,
            "message": result.message,
        }
        for result in report.results
        if result.health_status in {"warning", "critical", "unknown", "failed"}
    ]
    return {
        "overall_status": report.overall_status,
        "headline": f"Daily network health: {report.overall_status.upper()}",
        "counts": report.counts,
        "highlights": highlights[:20],
        "report_file": f"{run_name}/report.html",
    }


def _write_raw(raw_dir: Path, results: list[Result]) -> None:
    for result in results:
        if not result.output:
            continue
        device_dir = raw_dir / _safe(result.hostname or result.ip_address)
        device_dir.mkdir(exist_ok=True)
        filename = f"{result.command_number:03d}_{_safe(result.command)[:60]}.txt"
        (device_dir / filename).write_text(result.output, encoding="utf-8")


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "device"
