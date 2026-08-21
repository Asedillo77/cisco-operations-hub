"""Generate representative HTML and JSON reports without contacting devices."""

from __future__ import annotations

from pathlib import Path

from site_connectivity.evaluation import evaluate_cellular_radio
from site_connectivity.models import CommandResult, DeviceResult, DeviceTarget, PingResult, Status
from site_connectivity.profiles import CELLULAR_PROFILE
from site_connectivity.reporting import build_report, write_reports


def build_mock_results() -> list[DeviceResult]:
    """Return results covering healthy and degraded cellular evidence."""
    cellular = DeviceResult(
        target=DeviceTarget(
            "LAB-MOBILE-01",
            "192.0.2.10",
            "Example Campus",
            transport="cellular",
            site_type="mobile_unit",
        ),
        status=Status.DEGRADED,
        summary="The device is reachable, but weak cellular signal and packet loss may affect service.",
        ping=PingResult(
            status=Status.DEGRADED,
            transmitted=4,
            received=3,
            loss_percent=25.0,
            minimum_ms=83.0,
            average_ms=126.0,
            maximum_ms=184.0,
            message="The device is reachable with 25% packet loss.",
            raw_output="Mock ping: 4 sent, 3 received, 25% loss, average 126 ms.",
        ),
        ssh_status=Status.HEALTHY,
        ssh_message="SSH collection completed.",
        checks=[
            evaluate_cellular_radio(
                CELLULAR_PROFILE[0],
                "RSSI = -83 dBm\nRSRP = -112 dBm\nRSRQ = -16 dB\nSINR = 4.0 dB",
            ),
            CommandResult(
                "cellular_network",
                "show cellular 0/2/0 network",
                Status.UNKNOWN,
                "Cellular network registration evidence was collected for technical review.",
                "Automated interpretation will be refined with representative device output.",
                "Use the raw evidence when escalating to the network team.",
                "Current Service Status = Normal\nCurrent Service = Packet switched",
            ),
        ],
    )
    fixed = DeviceResult(
        target=DeviceTarget(
            "LAB-HUB-01",
            "192.0.2.20",
            "Example Campus",
            transport="fixed",
            site_type="dual_edge_hub",
        ),
        status=Status.HEALTHY,
        summary="The device is reachable and SSH collection completed successfully.",
        ping=PingResult(
            status=Status.HEALTHY,
            transmitted=4,
            received=4,
            loss_percent=0,
            minimum_ms=11,
            average_ms=13,
            maximum_ms=16,
            message="The device responded without packet loss. Average latency was 13 ms.",
        ),
        ssh_status=Status.HEALTHY,
        ssh_message="SSH collection completed.",
        checks=[
            CommandResult(
                "service_plane_health",
                "Correlated service-plane assessment",
                Status.HEALTHY,
                "DIA, corporate service VPN, and router-based SIG evidence look available.",
                "Each service plane is assessed separately to describe likely user impact.",
                "If router evidence is healthy, check endpoint client, authentication, policy, and platform status.",
                evidence={
                    "planes": [
                        {"name": "DIA", "status": "healthy", "summary": "One active default path is installed."},
                        {
                            "name": "Corporate Service VPN",
                            "status": "healthy",
                            "summary": "One service tunnel is active through the fixed transport.",
                        },
                        {
                            "name": "Secure Web Gateway",
                            "status": "healthy",
                            "summary": "Two router-based SIG tunnels are active.",
                        },
                    ],
                    "service_vrfs": ["10"],
                    "vrf_routing_verified": False,
                },
            ),
            CommandResult(
                "solarwinds_alerts",
                "SolarWinds active alerts API",
                Status.INFORMATIONAL,
                "SolarWinds node status is Up, with 1 active alert; the alert is 6.0 days old.",
                "SolarWinds currently reports the node as up. The dated alert is at least 24 hours old. The matched "
                "interface currently shows up/up, so the alert may be stale or uncleared.",
                "Review the alert reset condition if it remains active.",
                evidence={
                    "node_status": "Up",
                    "node": {
                        "LastSync": "2026-08-10T07:12:00Z",
                        "MachineType": "Cisco IOS XE Router",
                        "IOSVersion": "17.12.6",
                    },
                    "age_summary": "the alert is 6.0 days old",
                    "alert_count": 1,
                    "stale_alert_count": 1,
                    "interface_alert_matches": 1,
                    "interface_alerts_currently_up": 1,
                    "alerts": [
                        {
                            "AlertName": "Ethernet interface is down",
                            "Severity": 2,
                            "TriggeredDateTime": "2026-08-04T07:14:18Z",
                            "TriggeredMessage": "Interface is down",
                            "AgeText": "6.0 days old",
                            "InterfaceCurrentlyUp": True,
                        }
                    ],
                },
            ),
        ],
    )
    return [cellular, fixed]


def main() -> int:
    """Write mock reports into sample_reports."""
    project_root = Path(__file__).resolve().parent.parent
    report = build_report("Example Campus", build_mock_results(), dry_run=False)
    report["meta"]["generated_at"] = "2026-08-10T17:14:18+10:00"
    html_path, json_path = write_reports(report, project_root / "sample_reports")
    print(f"HTML: {html_path}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
