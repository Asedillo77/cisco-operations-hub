from pathlib import Path

from catalyst_port_capacity.audit import run_audit
from catalyst_port_capacity.mock import MockCatalystCenterClient
from catalyst_port_capacity.reporting import write_reports


def test_mock_audit_filters_logical_ports_and_renders(tmp_path: Path) -> None:
    fixture = Path(__file__).parents[1] / "examples" / "mock_catalyst_data.json"
    report = run_audit(MockCatalystCenterClient(fixture), ["192.0.2.11"], dry_run=False)
    assert [port.port_name for port in report.ports] == ["GigabitEthernet1/0/1", "GigabitEthernet1/0/2"]
    paths = write_reports(report, tmp_path)
    assert all(path.exists() for path in paths)
    assert "Cisco Catalyst Port Capacity Report" in paths[0].read_text(encoding="utf-8")
