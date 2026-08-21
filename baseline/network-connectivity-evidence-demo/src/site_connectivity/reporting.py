"""Branded HTML and matching JSON report generation."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import CommandResult, DeviceResult, Status

STATUS_ORDER = {
    Status.DOWN: 5,
    Status.DEGRADED: 4,
    Status.UNKNOWN: 3,
    Status.PLANNED: 2,
    Status.INFORMATIONAL: 1,
    Status.HEALTHY: 0,
}
SITE_TYPE_LABELS = {
    "dmu": "DMU",
    "dmt": "DMT",
    "processing_centre": "Processing Centre",
    "datacentre": "Datacentre",
    "donor_centre": "Donor Centre",
    "warehouse": "Warehouse",
    "other": "Other",
}


def _report_time() -> datetime:
    """Return Sydney time, falling back to the configured local Windows timezone."""
    try:
        return datetime.now(ZoneInfo("Australia/Sydney"))
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone()


def build_report(site: str, results: list[DeviceResult], *, dry_run: bool) -> dict[str, Any]:
    """Build the one data shape used by both report formats."""
    overall = _site_status(results)
    counts = {status.value: sum(result.status == status for result in results) for status in Status}
    priority_findings = _priority_findings(results)
    return {
        "meta": {
            "site": site,
            "generated_at": _report_time().isoformat(timespec="seconds"),
            "dry_run": dry_run,
            "device_count": len(results),
        },
        "overall_status": overall.value,
        "summary": _overall_summary(overall, dry_run, results),
        "counts": counts,
        "priority_findings": priority_findings,
        "devices": [_device_report_data(result) for result in results],
    }


def _device_report_data(result: DeviceResult) -> dict[str, Any]:
    """Add display-only labels without changing the collection models."""
    data = result.as_dict()
    site_type = result.target.site_type.casefold()
    data["target"]["site_type_label"] = SITE_TYPE_LABELS.get(site_type, site_type.replace("_", " ").title())
    data["health_overview"] = _health_overview(result)
    return data


def _health_overview(result: DeviceResult) -> list[dict[str, str]]:
    """Build compact, generic health cards from the same interpreted checks."""
    cards = [
        {
            "label": "Reachability",
            "status": result.ping.status.value,
            "message": result.ping.message,
        },
        {
            "label": "Router Access",
            "status": result.ssh_status.value,
            "message": result.ssh_message,
        },
    ]
    groups = (
        ("WAN and Routing", {"interface_state", "default_route"}),
        ("Cellular", {"cellular_radio", "cellular_network"}),
        ("Monitoring", {"solarwinds_alerts"}),
        ("Service Planes", {"service_plane_health"}),
    )
    for label, check_ids in groups:
        checks = [check for check in result.checks if check.check_id in check_ids]
        if not checks:
            continue
        worst = max(checks, key=lambda check: STATUS_ORDER[check.status])
        cards.append({"label": label, "status": worst.status.value, "message": worst.summary})
    return cards


def _priority_findings(results: list[DeviceResult]) -> list[dict[str, str]]:
    """Return only actionable degraded/down findings for the report landing section."""
    findings: list[dict[str, str]] = []
    for result in results:
        if result.ping.status in {Status.DOWN, Status.DEGRADED}:
            findings.append(
                {
                    "device": result.target.name,
                    "label": "Ping reachability",
                    "status": result.ping.status.value,
                    "summary": result.ping.message,
                    "action": "Review site power, WAN service, and the network path.",
                }
            )
        if result.ssh_status == Status.DOWN:
            findings.append(
                {
                    "device": result.target.name,
                    "label": "Router access",
                    "status": result.ssh_status.value,
                    "summary": result.ssh_message,
                    "action": "Check management reachability, device availability, and credentials.",
                }
            )
        for check in _actionable_checks(result):
            findings.append(
                {
                    "device": result.target.name,
                    "label": check.check_id.replace("_", " ").title(),
                    "status": check.status.value,
                    "summary": check.summary,
                    "action": check.recommended_action,
                }
            )
    return findings


def _actionable_checks(result: DeviceResult) -> list[CommandResult]:
    """Return actionable checks without repeating a route-only service-plane conclusion."""
    checks = [check for check in result.checks if check.status in {Status.DOWN, Status.DEGRADED}]
    route_is_actionable = any(check.check_id == "default_route" for check in checks)
    if not route_is_actionable:
        return checks
    return [
        check
        for check in checks
        if check.check_id != "service_plane_health" or not _service_plane_only_repeats_dia(check)
    ]


def _service_plane_only_repeats_dia(check: CommandResult) -> bool:
    planes = check.evidence.get("planes", [])
    affected = {
        str(plane.get("name")) for plane in planes if plane.get("status") in {Status.DOWN.value, Status.DEGRADED.value}
    }
    return affected == {"DIA"}


def _site_status(results: list[DeviceResult]) -> Status:
    """Calculate site health while recognising dual-edge processing-centre redundancy."""
    if not results:
        return Status.UNKNOWN
    site_types = {result.target.site_type.casefold() for result in results}
    if site_types == {"processing_centre"} and len(results) > 1:
        healthy_count = sum(result.status == Status.HEALTHY for result in results)
        if healthy_count == len(results):
            return Status.HEALTHY
        if healthy_count > 0:
            return Status.DEGRADED
    return max((result.status for result in results), key=STATUS_ORDER.get)


def _overall_summary(status: Status, dry_run: bool, results: list[DeviceResult]) -> str:
    if dry_run:
        return "The planned checks were validated. No device connections were made."
    all_unreachable = bool(results) and all(
        result.ping.status == Status.DOWN and result.ssh_status != Status.HEALTHY for result in results
    )
    if status == Status.DOWN and all_unreachable:
        return (
            "The site did not respond to ping and SSH could not be established. It appears down or unavailable. "
            "Possible causes include loss of site power, local router equipment, or the provider WAN circuit. "
            "Confirm site power and any known provider outage, then escalate with this report."
        )
    if status == Status.DEGRADED:
        summaries = [check.summary.rstrip(".") for result in results for check in _actionable_checks(result)]
        if summaries:
            key_findings = "; ".join(summaries[:2])
            return f"The site is reachable, but degraded evidence requires review. Key findings: {key_findings}."
    summaries = {
        Status.HEALTHY: "All tested devices were reachable and live collection completed.",
        Status.DEGRADED: "The site is reachable, but one or more results indicate degraded connectivity.",
        Status.DOWN: "One or more devices could not be reached or have a critical connectivity failure.",
        Status.UNKNOWN: "The available evidence is not sufficient for a firm site conclusion.",
        Status.PLANNED: "The checks have not been run.",
        Status.INFORMATIONAL: "Information was collected without indicating health or failure.",
    }
    return summaries[status]


def render_html(report: dict[str, Any]) -> str:
    """Render the responsive HTML report with autoescaping enabled."""
    environment = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(default=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return environment.get_template("site_connectivity_report.html.j2").render(report=report)


def write_reports(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    """Write paired HTML and JSON reports."""
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_site = re.sub(r"[^A-Za-z0-9_.-]+", "_", report["meta"]["site"]).strip("_") or "site"
    timestamp = datetime.fromisoformat(report["meta"]["generated_at"]).strftime("%Y%m%d_%H%M%S")
    prefix = f"{safe_site}_connectivity_{timestamp}"
    html_path = output_dir / f"{prefix}.html"
    json_path = output_dir / f"{prefix}.json"
    html_path.write_text(render_html(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return html_path, json_path
