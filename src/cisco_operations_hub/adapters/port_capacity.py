from __future__ import annotations

import csv
import json
import logging
import sys
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

from ..contracts import RunResult, ToolDescription, ToolField, ValidationResult
from ..inventory_files import prepare_tabular_inventory
from .command_runner import LIVE_CONFIRMATION, _bounded_int, _optional_path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PORT_CAPACITY_ROOT = PROJECT_ROOT / "baseline" / "cisco-catalyst-port-capacity-demo"
PORT_CAPACITY_SRC = PORT_CAPACITY_ROOT / "src"
DEFAULT_MOCK_DATA = PORT_CAPACITY_ROOT / "examples" / "mock_catalyst_data.json"
TARGET_COLUMNS = ("target", "management_ip", "ip_address", "device_id", "id")


def _load_preserved_modules() -> tuple[Any, Any, Any, Any, Any]:
    source = str(PORT_CAPACITY_SRC)
    if source not in sys.path:
        sys.path.insert(0, source)
    from catalyst_port_capacity import audit, client, config, mock, reporting

    return audit, client, config, mock, reporting


class PortCapacityAdapter:
    def describe(self) -> ToolDescription:
        return ToolDescription(
            tool_id="port-capacity",
            name="Catalyst Port Capacity",
            summary="Assess physical switchport capacity from Catalyst Center inventory evidence.",
            safety=(
                "Mock mode is offline. Live Catalyst Center requests require collection mode, "
                "credentials, and confirmation. Optional CLI validation runs read-only commands."
            ),
            available=True,
            fields=(
                ToolField(
                    "source_mode",
                    "Data source",
                    "select",
                    True,
                    default="mock",
                    options=(("mock", "Offline mock data"), ("live", "Live Catalyst Center")),
                ),
                ToolField(
                    "targets_text",
                    "Targets",
                    "textarea",
                    False,
                    "One management IP address or Catalyst device ID per line.",
                ),
                ToolField(
                    "inventory_file",
                    "Target inventory CSV or XLSX",
                    "path",
                    False,
                    "Use a target, management_ip, ip_address, device_id, or id column.",
                    picker="file",
                    extensions=(("Target inventories", "*.csv *.xlsx"),),
                ),
                ToolField(
                    "site_inventory_file",
                    "Configured sites JSON",
                    "path",
                    False,
                    "Load site names and their hostname/IP mappings into the selector below.",
                    picker="file",
                    extensions=(("Configured site inventories", "*.json"),),
                ),
                ToolField(
                    "mock_data",
                    "Mock Catalyst data",
                    "path",
                    False,
                    default=str(DEFAULT_MOCK_DATA),
                    picker="file",
                    extensions=(("JSON files", "*.json"),),
                ),
                ToolField(
                    "credentials_file",
                    "Catalyst Center credentials",
                    "path",
                    False,
                    "Required for live Catalyst Center collection.",
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
                ToolField("max_devices", "Maximum devices", "number", True, default=50),
                ToolField(
                    "verify_tls",
                    "TLS certificate verification",
                    "select",
                    True,
                    default="true",
                    options=(("true", "Enabled"), ("false", "Disabled for lab testing")),
                ),
                ToolField(
                    "cli_validation",
                    "Validate against live switch CLI",
                    "select",
                    True,
                    "Correlate DNAC rows with show interfaces status and ready stack members.",
                    default="true",
                    options=(("true", "Enabled"), ("false", "Disabled")),
                    apply_only=True,
                ),
            ),
        )

    def inventory_scope(self, values: dict[str, Any]) -> dict[str, Any]:
        sites = _load_site_inventory(_required_site_inventory(values))
        return {
            "sites": [
                {
                    "name": site_name,
                    "switches": switches,
                }
                for site_name, switches in sites.items()
            ],
            "site_count": len(sites),
            "device_count": sum(len(switches) for switches in sites.values()),
        }

    def validate(self, values: dict[str, Any]) -> ValidationResult:
        targets = _load_targets(values)
        max_devices = _bounded_int(values, "max_devices", default=50, minimum=1, maximum=500)
        if len(targets) > max_devices:
            raise ValueError(
                f"Target inventory has {len(targets)} devices; limit is {max_devices}."
            )
        source_mode = _source_mode(values)
        details: dict[str, Any] = {
            "targets": len(targets),
            "source": source_mode,
            "interface_collection": "requires collection mode",
            "cli_validation": "read-only; live source and collection mode only",
        }
        if source_mode == "mock":
            mock_path = _mock_path(values)
            _audit, _client, _config, mock, _reporting = _load_preserved_modules()
            mock_client = mock.MockCatalystCenterClient(mock_path)
            missing = []
            for target in targets:
                try:
                    mock_client.find_device(target)
                except LookupError:
                    missing.append(target)
            if missing:
                raise ValueError(f"Targets not found in mock data: {', '.join(missing)}")
            details["mock_data"] = str(mock_path)
            summary = f"Validated {len(targets)} target(s) against the offline mock fixture."
        else:
            summary = (
                f"Validated a live Catalyst Center plan for {len(targets)} target(s); "
                "no API request was made."
            )
        return ValidationResult(True, summary, details)

    def run(self, values: dict[str, Any], *, apply: bool) -> RunResult:
        validation = self.validate(values)
        targets = _load_targets(values)
        source_mode = _source_mode(values)
        audit, client, config, mock, reporting = _load_preserved_modules()
        if apply and str(values.get("confirmation", "")) != LIVE_CONFIRMATION:
            raise ValueError(f"Collection requires this confirmation: {LIVE_CONFIRMATION}")
        credentials = None
        if source_mode == "live":
            if not apply:
                raise ValueError("Live Catalyst Center access requires collection mode.")
            credentials_file = _optional_path(values, "credentials_file")
            if credentials_file is None:
                raise ValueError("Catalyst Center credentials are required for live collection.")
            credentials = _load_catalyst_credentials(config, credentials_file)
            if _cli_validation(values) and (
                not credentials.ssh_username or not credentials.ssh_password
            ):
                raise ValueError(
                    "CLI validation requires SSH username and password in the credentials file."
                )
            inventory_client = client.CatalystCenterClient(
                credentials.base_url,
                credentials.username,
                credentials.password,
                verify=_verify_tls(values),
            )
        else:
            inventory_client = mock.MockCatalystCenterClient(_mock_path(values))

        logger, stream = _memory_logger(bool(values.get("debug", False)))
        package_logger = logging.getLogger("catalyst_port_capacity")
        package_logger.addHandler(logger.handlers[0])
        package_logger.setLevel(logger.level)
        try:
            report = audit.run_audit(
                inventory_client,
                targets,
                dry_run=not apply,
                cli_credentials=(
                    credentials if source_mode == "live" and _cli_validation(values) else None
                ),
            )
            output_root = Path(str(values.get("output_root") or "outputs")).expanduser().resolve()
            run_dir = output_root / f"port_capacity_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            reporting.write_reports(report, run_dir)
        finally:
            package_logger.removeHandler(logger.handlers[0])
        logs = tuple(line for line in stream.getvalue().splitlines() if line)
        mode = "interface collection" if apply else "target-validation dry-run"
        return RunResult("success", f"{validation.summary} Completed {mode}.", run_dir, logs)


def _load_targets(values: dict[str, Any]) -> list[str]:
    direct = [line.strip() for line in str(values.get("targets_text", "")).splitlines()]
    targets = [target for target in direct if target and not target.startswith("#")]
    inventory_file = _optional_path(values, "inventory_file")
    site_inventory_file = _optional_path(values, "site_inventory_file")
    source_count = sum((bool(targets), inventory_file is not None, site_inventory_file is not None))
    if source_count > 1:
        raise ValueError(
            "Use one target source: manual targets, target CSV/XLSX, or configured sites JSON."
        )
    if site_inventory_file is not None:
        sites = _load_site_inventory(site_inventory_file)
        selected_site = str(values.get("configured_site", "")).strip()
        if not selected_site:
            raise ValueError("Select a configured site after loading the site inventory.")
        if selected_site not in sites:
            raise ValueError(f"Configured site was not found in the selected JSON: {selected_site}")
        selected_targets = set(_selected_site_targets(values))
        available = {item["ip_address"] for item in sites[selected_site]}
        if selected_targets:
            unknown = selected_targets - available
            if unknown:
                raise ValueError(
                    "One or more selected switches are not part of the configured site."
                )
            targets.extend(
                item["ip_address"]
                for item in sites[selected_site]
                if item["ip_address"] in selected_targets
            )
        else:
            targets.extend(item["ip_address"] for item in sites[selected_site])
    if inventory_file is not None:
        with (
            prepare_tabular_inventory(inventory_file) as prepared,
            prepared.open(encoding="utf-8-sig", newline="") as handle,
        ):
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("Target inventory has no header row.")
            for row_number, row in enumerate(reader, start=2):
                normalized = {
                    str(key).strip().lower(): str(value or "").strip()
                    for key, value in row.items()
                    if key is not None
                }
                target = next(
                    (normalized[column] for column in TARGET_COLUMNS if normalized.get(column)),
                    "",
                )
                if not target and any(normalized.values()):
                    raise ValueError(
                        f"Target inventory row {row_number} has no supported target value."
                    )
                if target:
                    targets.append(target)
    unique = list(dict.fromkeys(targets))
    if not unique:
        raise ValueError("Enter targets directly or provide a CSV/XLSX target inventory.")
    return unique


def _required_site_inventory(values: dict[str, Any]) -> Path:
    path = _optional_path(values, "site_inventory_file")
    if path is None:
        raise ValueError("Choose a configured sites JSON file first.")
    return path


def _load_site_inventory(path: Path) -> dict[str, list[dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError(f"Configured sites JSON was not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Configured sites JSON is invalid: {exc}") from exc
    if not isinstance(payload, dict) or not payload:
        raise ValueError("Configured sites JSON must be an object containing site names.")
    sites: dict[str, list[dict[str, str]]] = {}
    for raw_site, raw_switches in payload.items():
        site = str(raw_site).strip()
        if not site or not isinstance(raw_switches, list):
            raise ValueError("Each configured site must contain a list of switches.")
        switches = []
        for number, raw_switch in enumerate(raw_switches, start=1):
            if not isinstance(raw_switch, dict):
                raise ValueError(f"Configured site {site!r} switch {number} must be an object.")
            hostname = str(raw_switch.get("hostname") or "").strip()
            ip_address = str(raw_switch.get("ip_address") or "").strip()
            if not hostname or not ip_address:
                raise ValueError(
                    f"Configured site {site!r} switch {number} requires hostname and ip_address."
                )
            switches.append({"hostname": hostname, "ip_address": ip_address})
        if not switches:
            raise ValueError(f"Configured site {site!r} contains no switches.")
        sites[site] = switches
    return sites


def _selected_site_targets(values: dict[str, Any]) -> list[str]:
    value = values.get("selected_site_targets", [])
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Selected configured switches are invalid.") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Selected configured switches must be a list.")
    return [item.strip() for item in value if item.strip()]


def _source_mode(values: dict[str, Any]) -> str:
    mode = str(values.get("source_mode", "mock"))
    if mode not in {"mock", "live"}:
        raise ValueError("Data source must be mock or live.")
    return mode


def _mock_path(values: dict[str, Any]) -> Path:
    path = Path(str(values.get("mock_data") or DEFAULT_MOCK_DATA)).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Mock Catalyst data was not found: {path}")
    return path


def _verify_tls(values: dict[str, Any]) -> bool:
    value = str(values.get("verify_tls", "true")).lower()
    if value not in {"true", "false"}:
        raise ValueError("TLS certificate verification must be true or false.")
    return value == "true"


def _cli_validation(values: dict[str, Any]) -> bool:
    value = str(values.get("cli_validation", "true")).lower()
    if value not in {"true", "false"}:
        raise ValueError("CLI validation must be true or false.")
    return value == "true"


def _load_catalyst_credentials(config: Any, path: Path) -> Any:
    values: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid credentials entry on line {number}")
        key, value = line.split("=", 1)
        values[key.strip().lower()] = value.strip()

    def first(*names: str) -> str:
        return next((values[name] for name in names if values.get(name)), "")

    credentials = config.Credentials(
        base_url=first("catalyst_centre_base_url", "dnac_url", "url").rstrip("/"),
        username=first("catalyst_centre_username", "dnac_username", "username"),
        password=first("catalyst_centre_password", "dnac_password", "password"),
        ssh_username=first(
            "network_device_username", "ssh_username", "switch_username", "device_username"
        ),
        ssh_password=first(
            "network_device_password", "ssh_password", "switch_password", "device_password"
        ),
        ssh_secret=first("network_device_secret", "ssh_secret", "enable_secret"),
        ssh_device_type=first("ssh_device_type", "device_type", "netmiko_platform") or "cisco_xe",
    )
    missing = [
        label
        for label, value in (
            ("Catalyst Center URL", credentials.base_url),
            ("Catalyst Center username", credentials.username),
            ("Catalyst Center password", credentials.password),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Credentials file is missing: {', '.join(missing)}")
    return credentials


def _memory_logger(debug: bool) -> tuple[logging.Logger, StringIO]:
    stream = StringIO()
    logger = logging.getLogger(f"cisco_operations_hub.port_capacity.{id(stream)}")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger, stream
