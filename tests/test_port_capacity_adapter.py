import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from cisco_operations_hub.adapters.command_runner import LIVE_CONFIRMATION
from cisco_operations_hub.adapters.port_capacity import (
    DEFAULT_MOCK_DATA,
    PortCapacityAdapter,
    _load_catalyst_credentials,
    _load_preserved_modules,
)


def request_values(output_root: Path) -> dict[str, object]:
    return {
        "source_mode": "mock",
        "targets_text": "192.0.2.11\n192.0.2.12",
        "mock_data": str(DEFAULT_MOCK_DATA),
        "output_root": str(output_root),
        "max_devices": 50,
        "verify_tls": "true",
    }


def test_mock_plan_validates_targets_without_collection(tmp_path: Path) -> None:
    result = PortCapacityAdapter().validate(request_values(tmp_path))

    assert result.valid is True
    assert result.details["targets"] == 2
    assert result.details["source"] == "mock"


def test_mock_dry_run_writes_isolated_report_folder(tmp_path: Path) -> None:
    result = PortCapacityAdapter().run(request_values(tmp_path), apply=False)

    assert result.status == "success"
    assert result.output_directory.parent == tmp_path
    assert (result.output_directory / "catalyst_port_capacity.html").is_file()
    assert (result.output_directory / "catalyst_port_capacity.json").is_file()
    assert (result.output_directory / "catalyst_port_capacity.csv").is_file()


def test_mock_interface_collection_requires_confirmation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="RUN LIVE READ-ONLY COMMANDS"):
        PortCapacityAdapter().run(request_values(tmp_path), apply=True)


def test_mock_interface_collection_preserves_port_analysis(tmp_path: Path) -> None:
    values = request_values(tmp_path)
    values["confirmation"] = LIVE_CONFIRMATION

    result = PortCapacityAdapter().run(values, apply=True)

    report = (result.output_directory / "catalyst_port_capacity.json").read_text(encoding="utf-8")
    assert '"ports": 4' in report
    assert '"UNUSED_DOWN"' in report
    assert "TenGigabitEthernet1/1/1" not in report


def test_future_dnac_timestamp_is_clamped_to_zero_days() -> None:
    _load_preserved_modules()
    from catalyst_port_capacity.analysis import assess_interface  # noqa: PLC0415
    from catalyst_port_capacity.models import DeviceSummary  # noqa: PLC0415

    generated_at = datetime.now().astimezone()
    future_activity = generated_at + timedelta(hours=10)
    device = DeviceSummary(
        name="LAB-SW-01",
        management_ip="192.0.2.11",
        device_id="device-1",
        uptime="100 days",
        uptime_days=100,
        confidence="HIGH",
    )

    result = assess_interface(
        device,
        {
            "portName": "GigabitEthernet1/0/1",
            "adminStatus": "UP",
            "status": "UP",
            "lastIncomingPacketTime": future_activity.isoformat(),
            "lastOutgoingPacketTime": future_activity.isoformat(),
        },
        generated_at,
    )

    assert result.days_unused == 0
    assert result.observed_unused_days == 0


def test_html_groups_ports_by_switch_without_repeating_device_columns(tmp_path: Path) -> None:
    values = request_values(tmp_path)
    values["confirmation"] = LIVE_CONFIRMATION

    result = PortCapacityAdapter().run(values, apply=True)

    report = (result.output_directory / "catalyst_port_capacity.html").read_text(encoding="utf-8")
    assert "Switch Summary" in report
    assert report.count("192.0.2.11") == 1
    assert report.count("192.0.2.12") == 1
    assert "<th>Device</th>" not in report
    assert "<th>MAC Address</th>" in report
    assert "--teal:#007f78" in report
    assert "--red:#c92318" not in report


def test_xlsx_target_inventory_is_supported(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["management_ip"])
    sheet.append(["192.0.2.11"])
    sheet.append(["192.0.2.12"])
    inventory = tmp_path / "targets.xlsx"
    workbook.save(inventory)
    workbook.close()
    values = request_values(tmp_path)
    values["targets_text"] = ""
    values["inventory_file"] = str(inventory)

    result = PortCapacityAdapter().validate(values)

    assert result.details["targets"] == 2


def test_configured_sites_json_populates_site_and_switch_choices(tmp_path: Path) -> None:
    site_inventory = tmp_path / "configured_sites.json"
    site_inventory.write_text(
        json.dumps(
            {
                "Example Site": [
                    {"hostname": "LAB-SW-01", "ip_address": "192.0.2.11"},
                    {"hostname": "LAB-SW-02", "ip_address": "192.0.2.12"},
                ],
                "Other Site": [{"hostname": "LAB-SW-03", "ip_address": "192.0.2.13"}],
            }
        ),
        encoding="utf-8",
    )
    values = request_values(tmp_path)
    values["targets_text"] = ""
    values["site_inventory_file"] = str(site_inventory)

    scope = PortCapacityAdapter().inventory_scope(values)

    assert scope["site_count"] == 2
    assert scope["device_count"] == 3
    assert scope["sites"][0]["switches"][0] == {
        "hostname": "LAB-SW-01",
        "ip_address": "192.0.2.11",
    }


def test_configured_site_selection_limits_audit_targets(tmp_path: Path) -> None:
    site_inventory = tmp_path / "configured_sites.json"
    site_inventory.write_text(
        json.dumps(
            {
                "Example Site": [
                    {"hostname": "LAB-SW-01", "ip_address": "192.0.2.11"},
                    {"hostname": "LAB-SW-02", "ip_address": "192.0.2.12"},
                ]
            }
        ),
        encoding="utf-8",
    )
    values = request_values(tmp_path)
    values["targets_text"] = ""
    values["site_inventory_file"] = str(site_inventory)
    values["configured_site"] = "Example Site"
    values["selected_site_targets"] = json.dumps(["192.0.2.12"])

    result = PortCapacityAdapter().validate(values)

    assert result.details["targets"] == 1


def test_target_sources_are_mutually_exclusive(tmp_path: Path) -> None:
    values = request_values(tmp_path)
    values["site_inventory_file"] = str(tmp_path / "configured_sites.json")

    with pytest.raises(ValueError, match="Use one target source"):
        PortCapacityAdapter().validate(values)


def test_legacy_dnac_credential_keys_remain_compatible(tmp_path: Path) -> None:
    _audit, _client, config, _mock, _reporting = _load_preserved_modules()
    credentials_file = tmp_path / "dnac_credentials.txt"
    credentials_file.write_text(
        "url=https://catalyst.example.test\n"
        "username=service-account\n"
        "password=private-value\n"
        "ssh_username=network-reader\n"
        "ssh_password=private-ssh-value\n"
        "ssh_secret=private-enable-value\n"
        "ssh_device_type=cisco_xe\n",
        encoding="utf-8",
    )

    credentials = _load_catalyst_credentials(config, credentials_file)

    assert credentials.base_url == "https://catalyst.example.test"
    assert credentials.username == "service-account"
    assert credentials.ssh_username == "network-reader"
    assert credentials.ssh_password == "private-ssh-value"
    assert credentials.ssh_secret == "private-enable-value"
    assert credentials.ssh_device_type == "cisco_xe"


def test_cli_parsers_keep_ready_stack_member_ports() -> None:
    _load_preserved_modules()
    from catalyst_port_capacity.switch_cli import (  # noqa: PLC0415
        parse_ready_switch_members,
        parse_show_interfaces_status_ports,
        reportable_switchport,
    )

    status = (
        "Port      Name               Status       Vlan       Duplex  Speed Type\n"
        "Gi1/0/1   User port          connected    10         a-full a-1000 10/100/1000BaseTX\n"
        "Gi2/0/1   Spare              notconnect   20           auto   auto 10/100/1000BaseTX\n"
        "Te1/1/1   Uplink             connected    trunk      a-full a-10G 10GBase-SR\n"
        "Po1       Uplink             connected    trunk      a-full a-1000 EtherChannel\n"
    )
    switch = (
        "Switch/Stack Mac Address : 0011.2233.4455\n"
        " 1       Active   0011.2233.4455     15     V01     Ready\n"
        " 2       Member   0011.2233.4466     14     V01     Provisioned\n"
    )

    ports = parse_show_interfaces_status_ports(status)
    ready = parse_ready_switch_members(switch)

    assert ports == {"gi1/0/1", "gi2/0/1"}
    assert ready == {"1"}
    assert reportable_switchport("GigabitEthernet1/0/1", ready) is True
    assert reportable_switchport("GigabitEthernet2/0/1", ready) is False
    assert reportable_switchport("TenGigabitEthernet1/1/1", ready) is False


def test_v7_dnac_aliases_statuses_confidence_and_sorting_are_preserved() -> None:
    _load_preserved_modules()
    from catalyst_port_capacity.analysis import (  # noqa: PLC0415
        assess_device,
        assess_interface,
        natural_port_key,
    )

    device = assess_device(
        {
            "id": "device-1",
            "hostname": "LAB-SW-01",
            "managementIpAddress": "192.0.2.11",
            "uptimeSeconds": "",
        }
    )
    connected = assess_interface(
        device,
        {
            "interfaceName": "TwentyFiveGigabitEthernet1/0/2",
            "interfaceDescription": "Alias description",
            "interfaceMacAddress": "00:11:22:33:44:55",
            "adminState": "UP",
            "ifOperStatus": "connected",
        },
        datetime.now(UTC),
    )
    uplink_module = assess_interface(
        device,
        {"ifName": "TenGigabitEthernet1/1/1", "ifOperStatus": "down"},
        datetime.now(UTC),
    )

    assert device.confidence == "UNKNOWN"
    assert connected is not None
    assert connected.description == "Alias description"
    assert connected.mac_address == "00:11:22:33:44:55"
    assert connected.usage_flag == "ACTIVE"
    assert connected.confidence == "UNKNOWN"
    assert uplink_module is None
    assert sorted(
        ["TenGigabitEthernet2/0/1", "GigabitEthernet1/0/2", "TwoGigabitEthernet1/0/1"],
        key=natural_port_key,
    ) == ["TwoGigabitEthernet1/0/1", "GigabitEthernet1/0/2", "TenGigabitEthernet2/0/1"]


def test_cli_collection_runs_preserved_read_only_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    _load_preserved_modules()
    from catalyst_port_capacity import switch_cli  # noqa: PLC0415

    commands: list[tuple[str, int]] = []
    connection_values: dict[str, object] = {}

    class FakeConnection:
        def __init__(self, **kwargs: object) -> None:
            connection_values.update(kwargs)

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def enable(self) -> None:
            return None

        def send_command(self, command: str, *, read_timeout: int) -> str:
            commands.append((command, read_timeout))
            if command == "show switch":
                return " 1 Active 0011.2233.4455 15 V01 Ready\n"
            return (
                "Port      Name               Status       Vlan       Duplex Speed Type\n"
                "Gi1/0/1   User port          connected    10         full   1000  copper\n"
            )

    monkeypatch.setattr(switch_cli, "ConnectHandler", FakeConnection)

    inventory = switch_cli.collect_cli_port_inventory(
        "192.0.2.11",
        username="network-reader",
        password="ssh-password",
        secret="enable-secret",
        device_type="cisco_xe",
    )

    assert commands == [("show interfaces status", 60), ("show switch", 60)]
    assert connection_values["host"] == "192.0.2.11"
    assert connection_values["username"] == "network-reader"
    assert inventory.ports == {"gi1/0/1"}


def test_audit_correlates_dnac_rows_with_live_cli_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit, _client, config, _mock, _reporting = _load_preserved_modules()

    class FakeClient:
        def authenticate(self) -> None:
            return None

        def find_device(self, target: str) -> dict[str, object]:
            return {
                "id": "device-1",
                "hostname": "LAB-SW-01",
                "managementIpAddress": target,
                "uptimeSeconds": 10_000_000,
                "upTime": "115 days",
            }

        def get_interfaces(self, device_id: str) -> list[dict[str, object]]:
            assert device_id == "device-1"
            return [
                {"portName": "GigabitEthernet1/0/1", "adminStatus": "UP", "status": "UP"},
                {"portName": "GigabitEthernet1/0/2", "adminStatus": "UP", "status": "DOWN"},
            ]

    monkeypatch.setattr(
        audit,
        "collect_cli_port_inventory",
        lambda *args, **kwargs: SimpleNamespace(ports={"gi1/0/1"}, ready_switches={"1"}),
    )
    credentials = config.Credentials(
        base_url="https://catalyst.example.test",
        username="api-user",
        password="api-password",
        ssh_username="network-reader",
        ssh_password="ssh-password",
    )

    report = audit.run_audit(
        FakeClient(), ["192.0.2.11"], dry_run=False, cli_credentials=credentials
    )

    assert report.cli_validation is True
    assert [port.port_name for port in report.ports] == ["GigabitEthernet1/0/1"]
    assert report.ports[0].cli_verified is True
    assert report.devices[0].cli_validation_status == "success"
    assert "retained 1 of 2 DNAC row" in report.messages[0]


def test_cli_failure_matches_v7_device_failure_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    audit, _client, config, _mock, _reporting = _load_preserved_modules()

    class FakeClient:
        def authenticate(self) -> None:
            return None

        def find_device(self, target: str) -> dict[str, object]:
            return {
                "id": "device-1",
                "hostname": "LAB-SW-01",
                "managementIpAddress": target,
                "uptimeSeconds": 10_000_000,
            }

        def get_interfaces(self, device_id: str) -> list[dict[str, object]]:
            return [{"portName": "GigabitEthernet1/0/1", "adminStatus": "UP", "status": "UP"}]

    def fail_cli(*args: object, **kwargs: object) -> None:
        raise RuntimeError("SSH authentication failed")

    monkeypatch.setattr(audit, "collect_cli_port_inventory", fail_cli)
    credentials = config.Credentials(
        base_url="https://catalyst.example.test",
        username="api-user",
        password="api-password",
        ssh_username="network-reader",
        ssh_password="ssh-password",
    )

    report = audit.run_audit(
        FakeClient(), ["192.0.2.11"], dry_run=False, cli_credentials=credentials
    )

    assert report.ports == []
    assert report.devices[0].collection_status == "failed"
    assert report.devices[0].cli_validation_status == "failed"
    assert report.devices[0].message == "SSH authentication failed"


def test_live_plan_validation_does_not_require_or_call_credentials(tmp_path: Path) -> None:
    values = request_values(tmp_path)
    values["source_mode"] = "live"

    result = PortCapacityAdapter().validate(values)

    assert result.valid is True
    assert "no API request was made" in result.summary


def test_live_source_cannot_run_without_collection_mode(tmp_path: Path) -> None:
    values = request_values(tmp_path)
    values["source_mode"] = "live"

    with pytest.raises(ValueError, match="requires collection mode"):
        PortCapacityAdapter().run(values, apply=False)
