from __future__ import annotations

import csv
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..contracts import RunResult, ToolDescription, ToolField, ValidationResult
from ..inventory_files import prepare_tabular_inventory
from .command_runner import LIVE_CONFIRMATION, _bounded_int, _optional_path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONNECTIVITY_ROOT = PROJECT_ROOT / "baseline" / "network-connectivity-evidence-demo"
CONNECTIVITY_SRC = CONNECTIVITY_ROOT / "src"
DEFAULT_MAX_DEVICES = 10
LARGE_RUN_THRESHOLD = 10


def _load_preserved_modules() -> tuple[Any, Any, Any, Any, Any, Any]:
    source = str(CONNECTIVITY_SRC)
    if source not in sys.path:
        sys.path.insert(0, source)
    from site_connectivity import credentials, engine, inventory, profiles, reporting, solarwinds

    return credentials, engine, inventory, profiles, reporting, solarwinds


class ConnectivityEvidenceAdapter:
    def describe(self) -> ToolDescription:
        return ToolDescription(
            tool_id="connectivity-evidence",
            name="Connectivity Evidence",
            summary=(
                "Plan or collect site reachability, routing, transport, and service-plane evidence."
            ),
            safety=(
                "Dry-run performs no ping, SSH, or SolarWinds request. Live collection requires "
                "credentials and confirmation."
            ),
            available=True,
            fields=(
                ToolField(
                    "inventory_file",
                    "Inventory CSV, XLSX, or JSON",
                    "path",
                    False,
                    "Provide an inventory or enter one manual host below, but not both.",
                    picker="file",
                    extensions=(("Connectivity inventories", "*.csv *.xlsx *.json"),),
                ),
                ToolField(
                    "site",
                    "Manual site label",
                    "text",
                    False,
                    "Used only with a manual host. Inventory runs include every listed site.",
                ),
                ToolField("host", "Manual host", "text", False),
                ToolField("name", "Manual display name", "text", False),
                ToolField(
                    "transport",
                    "Transport",
                    "select",
                    True,
                    default="unknown",
                    options=(
                        ("unknown", "Unknown"),
                        ("cellular", "Cellular"),
                        ("satellite", "Satellite"),
                        ("fixed", "Fixed"),
                        ("fixed_cellular_backup", "Fixed with cellular backup"),
                    ),
                ),
                ToolField(
                    "site_type",
                    "Site type",
                    "select",
                    True,
                    default="other",
                    options=(
                        ("other", "Other"),
                        ("mobile_unit", "Mobile unit"),
                        ("portable_unit", "Portable unit"),
                        ("dual_edge_hub", "Dual-edge hub"),
                        ("data_centre", "Data centre"),
                        ("branch", "Branch"),
                        ("warehouse", "Warehouse"),
                    ),
                ),
                ToolField("platform", "Netmiko platform", "text", True, default="cisco_xe"),
                ToolField(
                    "edge_role",
                    "Edge role",
                    "select",
                    True,
                    default="single",
                    options=(
                        ("single", "Single"),
                        ("primary", "Primary"),
                        ("secondary", "Secondary"),
                    ),
                ),
                ToolField(
                    "service_vrfs",
                    "Service VRFs",
                    "text",
                    True,
                    "Comma-separated VRF names.",
                    default="10",
                ),
                ToolField(
                    "credentials_file",
                    "Device credentials",
                    "path",
                    False,
                    "Required for live SSH collection.",
                    apply_only=True,
                    picker="file",
                    extensions=(("Credential text files", "*.txt"),),
                ),
                ToolField(
                    "solarwinds_alerts",
                    "SolarWinds evidence",
                    "select",
                    True,
                    default="false",
                    options=(("false", "Not requested"), ("true", "Include active alerts")),
                ),
                ToolField(
                    "solarwinds_credentials_file",
                    "SolarWinds credentials",
                    "path",
                    False,
                    "Required for live SolarWinds evidence.",
                    apply_only=True,
                    picker="file",
                    extensions=(("Credential text files", "*.txt"),),
                ),
                ToolField(
                    "output_root",
                    "Output folder",
                    "path",
                    True,
                    default="outputs",
                    picker="folder",
                ),
                ToolField(
                    "max_devices",
                    "Maximum devices",
                    "number",
                    True,
                    "Connectivity-specific safety ceiling. Increase only after reviewing the plan.",
                    default=DEFAULT_MAX_DEVICES,
                ),
                ToolField(
                    "concurrent_workers",
                    "Concurrent workers",
                    "number",
                    True,
                    "Devices are processed in parallel up to this limit.",
                    default=3,
                ),
                ToolField("ping_count", "Ping count", "number", True, default=15),
                ToolField("ping_timeout", "Ping timeout seconds", "number", True, default=2),
            ),
        )

    def validate(self, values: dict[str, Any]) -> ValidationResult:
        targets, sites = _load_targets(values)
        max_devices = _bounded_int(
            values,
            "max_devices",
            default=DEFAULT_MAX_DEVICES,
            minimum=1,
            maximum=200,
        )
        if len(targets) > max_devices:
            raise ValueError(
                f"The selected scope has {len(targets)} devices; the Connectivity Evidence "
                f"limit is {max_devices}. Review the dry-run scope before deliberately "
                "increasing Maximum devices."
            )
        _bounded_int(values, "ping_count", default=15, minimum=1, maximum=100)
        _bounded_int(values, "ping_timeout", default=2, minimum=1, maximum=30)
        workers = _bounded_int(values, "concurrent_workers", default=3, minimum=1, maximum=10)
        _credentials, _engine, _inventory, profiles, _reporting, _solarwinds = (
            _load_preserved_modules()
        )
        planned = {
            target.name: [check.command for check in profiles.dry_run_checks(target)]
            for target in targets
        }
        solarwinds_requested = _as_bool(values, "solarwinds_alerts")
        planned_checks = sum(len(commands) for commands in planned.values())
        if solarwinds_requested:
            planned_checks += len(targets)
        details: dict[str, Any] = {
            "sites": sites,
            "site_count": len(sites),
            "devices": len(targets),
            "planned_checks": planned_checks,
            "commands_by_device": planned,
            "solarwinds": "planned" if solarwinds_requested else "not requested",
            "concurrent_workers": workers,
            "estimated_batches": (len(targets) + workers - 1) // workers,
        }
        if len(targets) > LARGE_RUN_THRESHOLD:
            details["large_run_warning"] = (
                f"This selection exceeds the recommended {LARGE_RUN_THRESHOLD}-device "
                "Connectivity Evidence batch size. Review check volume and concurrency "
                "before live collection."
            )
        return ValidationResult(
            True,
            f"Validated {len(targets)} device(s), {len(sites)} site(s), and "
            f"{planned_checks} planned check(s).",
            details,
        )

    def inventory_scope(self, values: dict[str, Any]) -> dict[str, Any]:
        targets, _sites = _load_all_targets(values)
        if _optional_path(values, "inventory_file") is None:
            raise ValueError("Choose an inventory file to configure its run scope.")
        devices = [
            {
                "id": _target_id(target),
                "name": target.name,
                "site": target.site,
                "host": target.host,
                "transport": target.transport,
                "site_type": target.site_type,
                "edge_role": target.edge_role,
            }
            for target in targets
        ]
        return {
            "devices": devices,
            "device_count": len(devices),
            "sites": sorted({item["site"] for item in devices}, key=str.casefold),
            "site_count": len({item["site"] for item in devices}),
        }

    def run(self, values: dict[str, Any], *, apply: bool) -> RunResult:
        validation = self.validate(values)
        targets, sites = _load_targets(values)
        credentials_module, engine, _inventory, _profiles, reporting, solarwinds = (
            _load_preserved_modules()
        )
        device_credentials = None
        solarwinds_collector = None
        solarwinds_requested = _as_bool(values, "solarwinds_alerts")
        if apply:
            if str(values.get("confirmation", "")) != LIVE_CONFIRMATION:
                raise ValueError(f"Live collection requires this confirmation: {LIVE_CONFIRMATION}")
            credentials_file = _optional_path(values, "credentials_file")
            if credentials_file is None:
                raise ValueError("Device credentials are required for live collection.")
            device_credentials = credentials_module.load_credentials(credentials_file)

        logger, stream = _memory_logger(bool(values.get("debug", False)))
        if apply and solarwinds_requested:
            solarwinds_credentials_file = _optional_path(values, "solarwinds_credentials_file")
            if solarwinds_credentials_file is None:
                raise ValueError(
                    "SolarWinds credentials are required when its evidence is requested."
                )
            try:
                sw_credentials = credentials_module.load_solarwinds_credentials(
                    solarwinds_credentials_file
                )
                solarwinds_collector = solarwinds.SolarWindsAlertClient(sw_credentials, logger)
            except (OSError, ValueError, solarwinds.SolarWindsError) as exc:
                logger.error("SolarWinds evidence is unavailable: %s", exc)
                solarwinds_collector = solarwinds.UnavailableSolarWindsCollector(str(exc))

        ping_count = _bounded_int(values, "ping_count", default=15, minimum=1, maximum=100)
        ping_timeout = _bounded_int(values, "ping_timeout", default=2, minimum=1, maximum=30)
        workers = _bounded_int(values, "concurrent_workers", default=3, minimum=1, maximum=10)

        def investigate(target: Any) -> Any:
            return engine.investigate_device(
                target,
                device_credentials,
                apply=apply,
                ping_count=ping_count,
                ping_timeout=ping_timeout,
                logger=logger,
                solarwinds_collector=solarwinds_collector,
                solarwinds_requested=solarwinds_requested,
            )

        with ThreadPoolExecutor(max_workers=min(workers, len(targets))) as executor:
            results = list(executor.map(investigate, targets))
        output_root = Path(str(values.get("output_root") or "outputs")).expanduser().resolve()
        run_dir = output_root / f"connectivity_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        site_reports = []
        for site in sites:
            site_results = [result for result in results if result.target.site == site]
            report = reporting.build_report(site, site_results, dry_run=not apply)
            site_dir = run_dir / _safe_folder(site)
            html_path, json_path = reporting.write_reports(report, site_dir)
            site_reports.append(
                {
                    "site": site,
                    "devices": len(site_results),
                    "status": report["overall_status"],
                    "summary": report["summary"],
                    "html_report": str(html_path.relative_to(run_dir)),
                    "json_report": str(json_path.relative_to(run_dir)),
                }
            )
        _write_run_summary(run_dir, site_reports, dry_run=not apply)
        logs = tuple(line for line in stream.getvalue().splitlines() if line)
        mode = "live collection" if apply else "dry-run"
        return RunResult("success", f"{validation.summary} Completed {mode}.", run_dir, logs)


def _load_targets(values: dict[str, Any]) -> tuple[list[Any], list[str]]:
    targets, sites = _load_all_targets(values)
    if _optional_path(values, "inventory_file") is None:
        return targets, sites
    mode = str(values.get("scope_mode", "all")).strip().lower() or "all"
    if mode == "all":
        return targets, sites
    if mode == "sites":
        selected_sites = set(_selection_values(values, "selected_sites"))
        targets = [target for target in targets if target.site in selected_sites]
    elif mode == "devices":
        selected_devices = set(_selection_values(values, "selected_devices"))
        targets = [target for target in targets if _target_id(target) in selected_devices]
    else:
        raise ValueError("Run scope must be all devices, selected sites, or selected devices.")
    if not targets:
        raise ValueError("The selected run scope contains no devices.")
    sites = sorted({target.site for target in targets}, key=str.casefold)
    return targets, sites


def _load_all_targets(values: dict[str, Any]) -> tuple[list[Any], list[str]]:
    _credentials, _engine, inventory, _profiles, _reporting, _solarwinds = _load_preserved_modules()
    inventory_file = _optional_path(values, "inventory_file")
    host = str(values.get("host", "")).strip()
    if inventory_file and host:
        raise ValueError("Provide an inventory or a manual host, not both.")
    if inventory_file:
        if inventory_file.suffix.lower() == ".json":
            targets = inventory.load_inventory(inventory_file)
        else:
            targets = []
            with (
                prepare_tabular_inventory(inventory_file) as prepared,
                prepared.open(encoding="utf-8-sig", newline="") as handle,
            ):
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    raise ValueError("Connectivity inventory has no header row.")
                for row_number, row in enumerate(reader, start=2):
                    normalized = {
                        str(key).strip().lower(): str(value or "").strip()
                        for key, value in row.items()
                        if key is not None
                    }
                    if not any(normalized.values()):
                        continue
                    try:
                        targets.append(inventory.target_from_mapping(normalized))
                    except (TypeError, ValueError) as exc:
                        raise ValueError(f"Connectivity inventory row {row_number}: {exc}") from exc
        sites = inventory.sites_from_inventory(targets)
        return targets, sites
    if not host:
        raise ValueError("Provide an inventory or a manual host.")
    site = str(values.get("site", "")).strip() or "Ad hoc"
    target = inventory.target_from_mapping(
        {
            "name": str(values.get("name", "")).strip() or host,
            "host": host,
            "site": site,
            "platform": str(values.get("platform", "cisco_xe")),
            "transport": str(values.get("transport", "unknown")),
            "site_type": str(values.get("site_type", "other")),
            "edge_role": str(values.get("edge_role", "single")),
            "service_vrfs": str(values.get("service_vrfs", "10")),
        }
    )
    return [target], [site]


def _selection_values(values: dict[str, Any], name: str) -> list[str]:
    value = values.get(name, [])
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name.replace('_', ' ').title()} is invalid.") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name.replace('_', ' ').title()} must be a list.")
    return [item.strip() for item in value if item.strip()]


def _target_id(target: Any) -> str:
    return "||".join((target.site, target.name, target.host))


def _safe_folder(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "site"


def _write_run_summary(run_dir: Path, site_reports: list[dict[str, Any]], *, dry_run: bool) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "site_count": len(site_reports),
        "device_count": sum(item["devices"] for item in site_reports),
        "sites": site_reports,
    }
    template_root = PROJECT_ROOT / "templates"
    environment = Environment(
        loader=FileSystemLoader(template_root),
        autoescape=select_autoescape(default=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    html = environment.get_template("connectivity_run_summary.html.j2").render(summary=summary)
    (run_dir / "run_summary.html").write_text(html, encoding="utf-8")
    (run_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def _as_bool(values: dict[str, Any], name: str) -> bool:
    value = str(values.get(name, "false")).lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name.replace('_', ' ').title()} must be true or false.")
    return value == "true"


def _memory_logger(debug: bool) -> tuple[logging.Logger, StringIO]:
    stream = StringIO()
    logger = logging.getLogger(f"cisco_operations_hub.connectivity.{id(stream)}")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger, stream
