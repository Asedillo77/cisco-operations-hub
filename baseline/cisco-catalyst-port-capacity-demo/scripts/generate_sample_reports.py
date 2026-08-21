"""Generate public sample reports from fictional offline data."""

from pathlib import Path

from catalyst_port_capacity.audit import run_audit
from catalyst_port_capacity.mock import MockCatalystCenterClient
from catalyst_port_capacity.reporting import write_reports

ROOT = Path(__file__).parents[1]
client = MockCatalystCenterClient(ROOT / "examples" / "mock_catalyst_data.json")
report = run_audit(client, ["192.0.2.11", "192.0.2.12"], dry_run=False)
write_reports(report, ROOT / "sample_reports")
