"""HTML, JSON, and CSV report writers."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from .models import AuditReport


def write_reports(report: AuditReport, output_dir: Path) -> list[Path]:
    """Write the same hydrated report to three review-friendly formats."""
    output_dir.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    json_path = output_dir / "catalyst_port_capacity.json"
    html_path = output_dir / "catalyst_port_capacity.html"
    csv_path = output_dir / "catalyst_port_capacity.csv"
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    environment = Environment(loader=PackageLoader("catalyst_port_capacity"), autoescape=select_autoescape())
    html_path.write_text(environment.get_template("port_capacity.html.j2").render(report=data), encoding="utf-8")
    fields = list(report.ports[0].to_dict()) if report.ports else list(report.to_dict()["counts"])
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        if report.ports:
            writer.writerows(port.to_dict() for port in report.ports)
    return [html_path, json_path, csv_path]
