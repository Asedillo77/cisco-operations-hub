from site_connectivity.evaluation import evaluate_command, evaluate_interfaces, finalise_device
from site_connectivity.models import DeviceResult, DeviceTarget, PingResult, Status
from site_connectivity.profiles import BASE_PROFILE


def test_satellite_primary_and_cellular_standby_service_planes_are_healthy() -> None:
    target = DeviceTarget("LAB-MOBILE-02", "192.0.2.24", transport="satellite", site_type="mobile_unit")
    outputs = {
        "interface_state": """
GigabitEthernet0/0/0 198.51.100.245 YES DHCP up up
Cellular0/2/0 unassigned YES IPCP up down
Tunnel10 198.51.100.245 YES TFTP up up
Tunnel20 unassigned NO TFTP up down
Tunnel101 198.51.100.245 YES TFTP up up
Tunnel102 unassigned NO TFTP up down
Tunnel201 198.51.100.245 YES TFTP up up
Tunnel202 unassigned NO TFTP up down
""",
        "default_route": "S* 0.0.0.0/0 [1/0] via 198.51.100.1",
        "transport_descriptions": """
Gi0/0/0 up up VPN 0 Starlink Interface
Cellular0/2/0 up down VPN 0 Cellular Interface
""",
        "tunnel_topology": """
interface Tunnel10
 tunnel source GigabitEthernet0/0/0
interface Tunnel20
 tunnel source Cellular0/2/0
interface Tunnel101
 tunnel source GigabitEthernet0/0/0
 tunnel destination 203.0.113.38
 tunnel vrf multiplexing
interface Tunnel102
 tunnel source Cellular0/2/0
 tunnel destination 203.0.113.38
 tunnel vrf multiplexing
interface Tunnel201
 tunnel source GigabitEthernet0/0/0
 tunnel destination 203.0.113.39
 tunnel vrf multiplexing
interface Tunnel202
 tunnel source Cellular0/2/0
 tunnel destination 203.0.113.39
 tunnel vrf multiplexing
""",
    }
    checks = [evaluate_command(check, outputs[check.check_id], target) for check in BASE_PROFILE[1:]]
    result = DeviceResult(
        target,
        Status.UNKNOWN,
        "Pending",
        PingResult(status=Status.HEALTHY),
        Status.HEALTHY,
        "SSH complete",
        checks,
    )
    finalise_device(result)
    service = result.checks[-1]
    planes = {plane["name"]: plane for plane in service.evidence["planes"]}
    assert service.status == Status.HEALTHY
    assert planes["DIA"]["status"] == Status.HEALTHY
    assert planes["Corporate Service VPN"]["status"] == Status.HEALTHY
    assert planes["Netskope SIG"]["status"] == Status.HEALTHY
    assert "cellular" in planes["Backup and Failover"]["summary"]


def test_secondary_hub_expected_tunnel_down_does_not_degrade_physical_wan() -> None:
    target = DeviceTarget(
        "LAB-HUB-02",
        "192.0.2.2",
        site_type="dual_edge_hub",
        transport="fixed",
        edge_role="secondary",
    )
    output = """
GigabitEthernet0/0/0 203.0.113.2 YES other up up
Tunnel0 203.0.113.2 YES TFTP up up
Tunnel103 203.0.113.2 YES TFTP up up
Tunnel104 192.0.2.238 YES TFTP up down
Tunnel203 203.0.113.2 YES TFTP up up
Tunnel204 192.0.2.238 YES TFTP up down
Tunnel205 192.0.2.238 YES TFTP up down
"""
    result = evaluate_interfaces(BASE_PROFILE[1], output, target)
    assert result.status == Status.HEALTHY
    assert result.evidence["addressed_non_tunnel_down"] == []
