from site_connectivity.evaluation import evaluate_default_route
from site_connectivity.models import DeviceTarget, Status
from site_connectivity.profiles import BASE_PROFILE

ROUTE_CHECK = BASE_PROFILE[2]


def test_branch_fixed_default_route_is_identified() -> None:
    output = """
Gateway of last resort is 198.51.100.1 to network 0.0.0.0

S*    0.0.0.0/0 [1/0] via 198.51.100.1
C        198.51.100.0/30 is directly connected, GigabitEthernet0/0/0.101
L        198.51.100.2/32 is directly connected, GigabitEthernet0/0/0.101
"""
    target = DeviceTarget(
        "LAB-BRANCH-01",
        "192.0.2.20",
        site_type="branch",
        transport="fixed_cellular_backup",
    )
    result = evaluate_default_route(ROUTE_CHECK, output, target)
    assert result.status == Status.HEALTHY
    assert result.evidence["default_next_hops"] == ["198.51.100.1"]
    assert not result.evidence["load_balanced"]


def test_fixed_primary_site_flags_fixed_and_cellular_defaults() -> None:
    output = """
S*    0.0.0.0/0 [1/0] via 198.51.100.1
S*    0.0.0.0/0 is directly connected, Cellular0/2/0
"""
    target = DeviceTarget(
        "TESTEDG01",
        "192.0.2.21",
        site_type="branch",
        transport="fixed_cellular_backup",
    )
    result = evaluate_default_route(ROUTE_CHECK, output, target)
    assert result.status == Status.DEGRADED
    assert result.evidence["load_balanced"]
    assert result.evidence["uses_cellular"]


def test_missing_default_route_is_degraded() -> None:
    target = DeviceTarget("EDGE01", "192.0.2.22", site_type="other")
    result = evaluate_default_route(ROUTE_CHECK, "Gateway of last resort is not set", target)
    assert result.status == Status.DEGRADED


def test_multiple_defaults_are_degraded_for_single_edge_device() -> None:
    output = """
S*    0.0.0.0/0 [1/0] via 192.0.2.1
                [1/0] via 198.51.100.1
"""
    target = DeviceTarget("EDGE01", "192.0.2.22", site_type="dual_edge_hub", transport="fixed")
    result = evaluate_default_route(ROUTE_CHECK, output, target)
    assert result.status == Status.DEGRADED
    assert result.evidence["path_count"] == 2
    assert "one active IPv4 default route" in result.explanation


def test_two_defaults_are_healthy_for_dual_edge_device() -> None:
    output = """
S*    0.0.0.0/0 [1/0] via 192.0.2.1
                [1/0] via 198.51.100.1
"""
    target = DeviceTarget(
        "EDGE01",
        "192.0.2.22",
        site_type="dual_edge_hub",
        transport="fixed",
        edge_role="primary",
    )
    result = evaluate_default_route(ROUTE_CHECK, output, target)
    assert result.status == Status.HEALTHY
    assert result.evidence["dual_edge"] is True
    assert "dual-edge design" in result.summary


def test_one_default_is_degraded_redundancy_for_dual_edge_device() -> None:
    target = DeviceTarget("EDGE02", "192.0.2.23", edge_role="secondary")
    result = evaluate_default_route(ROUTE_CHECK, "S* 0.0.0.0/0 [1/0] via 192.0.2.1", target)
    assert result.status == Status.DEGRADED
    assert "resilience is reduced" in result.explanation
