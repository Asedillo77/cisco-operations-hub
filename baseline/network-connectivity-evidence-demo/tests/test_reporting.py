from site_connectivity.models import CommandResult, DeviceResult, DeviceTarget, PingResult, Status
from site_connectivity.reporting import build_report, render_html


def test_html_report_contains_responsive_branding() -> None:
    result = DeviceResult(
        DeviceTarget("EDGE01", "192.0.2.1", "Test Site"),
        Status.HEALTHY,
        "Healthy",
        PingResult(status=Status.HEALTHY, message="Reachable"),
        Status.HEALTHY,
        "SSH complete",
    )
    html = render_html(build_report("Test Site", [result], dry_run=False))
    assert "--teal-700: #0F766E" in html
    assert "width: max-content" in html
    assert "overflow-x: auto" in html
    assert "Test Site" in html


def test_dual_edge_site_is_degraded_when_one_router_is_down() -> None:
    healthy = DeviceResult(
        DeviceTarget("EDGE01", "192.0.2.1", "Example Hub", site_type="dual_edge_hub"),
        Status.HEALTHY,
        "Healthy",
        PingResult(status=Status.HEALTHY),
        Status.HEALTHY,
    )
    down = DeviceResult(
        DeviceTarget("EDGE02", "192.0.2.2", "Example Hub", site_type="dual_edge_hub"),
        Status.DOWN,
        "Down",
        PingResult(status=Status.DOWN),
        Status.DOWN,
    )
    report = build_report("Example Hub", [healthy, down], dry_run=False)
    assert report["overall_status"] == Status.DEGRADED


def test_unreachable_site_summary_is_clear() -> None:
    result = DeviceResult(
        DeviceTarget("EDGE01", "192.0.2.1", "Remote Site"),
        Status.DOWN,
        "Unavailable",
        PingResult(status=Status.DOWN),
        Status.DOWN,
        "SSH timed out",
    )
    report = build_report("Remote Site", [result], dry_run=False)
    assert report["overall_status"] == Status.DOWN
    assert "appears down or unavailable" in report["summary"]
    assert "provider WAN circuit" in report["summary"]


def test_report_displays_mobile_site_label() -> None:
    result = DeviceResult(
        DeviceTarget("LAB-MOBILE-01", "192.0.2.11", "Mobile", site_type="mobile_unit"),
        Status.HEALTHY,
        "Healthy",
        PingResult(status=Status.HEALTHY),
    )
    report = build_report("Mobile", [result], dry_run=False)
    html = render_html(report)
    assert report["devices"][0]["target"]["site_type_label"] == "DMU"
    assert "Site type: DMU" in html
    assert "Network Connectivity Evidence Explorer" in html


def test_report_builds_generic_health_overview_and_priority_findings() -> None:
    route = CommandResult(
        "default_route",
        "show ip route",
        Status.DEGRADED,
        "Multiple default paths are installed.",
        "One active default route is expected.",
        "Confirm the intended primary path.",
    )
    result = DeviceResult(
        DeviceTarget("EDGE01", "192.0.2.1", "Any Site", site_type="other"),
        Status.DEGRADED,
        "Degraded",
        PingResult(status=Status.HEALTHY, message="Reachable"),
        Status.HEALTHY,
        "SSH complete",
        [route],
    )
    report = build_report("Any Site", [result], dry_run=False)
    html = render_html(report)
    assert any(item["label"] == "WAN and Routing" for item in report["devices"][0]["health_overview"])
    assert report["priority_findings"][0]["label"] == "Default Route"
    assert "Key findings: Multiple default paths are installed" in report["summary"]
    assert "Priority findings and next steps" in html


def test_route_only_service_plane_finding_is_not_repeated() -> None:
    route = CommandResult(
        "default_route",
        "show ip route",
        Status.DEGRADED,
        "Multiple default paths are installed.",
        "One active default route is expected.",
        "Confirm the intended primary path.",
    )
    service_plane = CommandResult(
        "service_plane_health",
        "Correlated service-plane assessment",
        Status.DEGRADED,
        "Multiple active IPv4 default paths are installed; unintended load sharing is possible.",
        "Service-plane correlation.",
        "Investigate the affected service plane.",
        evidence={
            "planes": [
                {"name": "DIA", "status": "degraded"},
                {"name": "Corporate Service VPN", "status": "healthy"},
                {"name": "Netskope SIG", "status": "healthy"},
            ]
        },
    )
    result = DeviceResult(
        DeviceTarget("EDGE01", "192.0.2.1"),
        Status.DEGRADED,
        "Degraded",
        PingResult(status=Status.HEALTHY),
        Status.HEALTHY,
        checks=[route, service_plane],
    )

    report = build_report("Site", [result], dry_run=False)

    assert [finding["label"] for finding in report["priority_findings"]] == ["Default Route"]
    assert report["summary"].count("default") == 1
