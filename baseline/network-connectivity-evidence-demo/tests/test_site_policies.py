from site_connectivity.evaluation import evaluate_cellular_network, evaluate_interfaces
from site_connectivity.models import DeviceTarget, Status
from site_connectivity.profiles import BASE_PROFILE, CELLULAR_PROFILE, cellular_collection_required, dry_run_checks

INTERFACE_CHECK = BASE_PROFILE[1]


def test_mobile_unit_lte_is_expected_transport() -> None:
    output = """
GigabitEthernet0/0/0   unassigned      YES unset  down                  down
Cellular0/2/0          192.0.2.11      YES IPCP   up                    up
Cellular0/2/1          unassigned      YES other  administratively down down
Tunnel20               192.0.2.11      YES TFTP   up                    up
"""
    target = DeviceTarget("LAB-MOBILE-01", "192.0.2.11", site_type="mobile_unit")
    result = evaluate_interfaces(INTERFACE_CHECK, output, target)
    assert result.status == Status.HEALTHY
    assert result.evidence["observed_transport"] == "cellular"


def test_mobile_unit_satellite_allows_cellular_to_be_down() -> None:
    output = """
GigabitEthernet0/0/0   unassigned      YES unset  up                    up
Cellular0/2/0          unassigned      YES IPCP   down                  down
Cellular0/2/1          unassigned      YES other  administratively down down
"""
    target = DeviceTarget("LAB-MOBILE-02", "192.0.2.12", site_type="mobile_unit")
    result = evaluate_interfaces(INTERFACE_CHECK, output, target)
    assert result.status == Status.HEALTHY
    assert result.evidence["observed_transport"] == "starlink"
    assert "Starlink" in result.summary


def test_portable_unit_requires_cellular() -> None:
    output = """
GigabitEthernet0/0/0   unassigned      YES unset  down                  down
Cellular0/2/0          192.0.2.14      YES IPCP   up                    up
"""
    target = DeviceTarget("LAB-PORTABLE-01", "192.0.2.14", site_type="portable_unit")
    result = evaluate_interfaces(INTERFACE_CHECK, output, target)
    assert result.status == Status.HEALTHY


def test_dual_edge_hub_detects_partial_path_failure() -> None:
    output = """
GigabitEthernet0/0/0   198.51.100.6    YES other  up                    up
Te0/0/5.992            192.0.2.238     YES other  up                    down
Tunnel104              192.0.2.238     YES TFTP   up                    down
"""
    target = DeviceTarget("LAB-HUB-02", "192.0.2.126", site_type="dual_edge_hub")
    result = evaluate_interfaces(INTERFACE_CHECK, output, target)
    assert result.status == Status.DEGRADED
    assert "Te0/0/5.992" in result.evidence["assigned_protocol_down"]


def test_branch_treats_unaddressed_cellular_as_standby() -> None:
    output = """
GigabitEthernet0/0/0   unassigned      YES unset  up                    up
Gi0/0/0.101            198.51.100.10   YES other  up                    up
Cellular0/2/0          unassigned      YES IPCP   up                    down
Cellular0/2/1          unassigned      YES IPCP   up                    up
Tunnel101              198.51.100.10   YES TFTP   up                    up
"""
    target = DeviceTarget("LAB-BRANCH-01", "192.0.2.38", site_type="branch")
    result = evaluate_interfaces(INTERFACE_CHECK, output, target)
    assert result.status == Status.HEALTHY
    assert result.evidence["observed_transport"] == "fixed"
    assert result.evidence["cellular_active_interfaces"] == []


def test_branch_reports_cellular_failover() -> None:
    output = """
GigabitEthernet0/0/0   unassigned      YES unset  down                  down
Cellular0/2/0          unassigned      YES IPCP   up                    up
"""
    target = DeviceTarget("TESTEDG01", "192.0.2.39", site_type="branch")
    result = evaluate_interfaces(INTERFACE_CHECK, output, target)
    assert result.status == Status.DEGRADED
    assert result.evidence["observed_transport"] == "cellular_failover"


def test_cellular_0_2_1_is_not_treated_as_a_wan_interface() -> None:
    output = """
GigabitEthernet0/0/0   unassigned      YES unset  down                  down
Cellular0/2/0          unassigned      YES IPCP   down                  down
Cellular0/2/1          192.0.2.1       YES IPCP   up                    up
"""
    target = DeviceTarget("LAB-PORTABLE-02", "192.0.2.5", site_type="portable_unit")
    result = evaluate_interfaces(INTERFACE_CHECK, output, target)
    assert result.status == Status.DOWN
    assert result.evidence["cellular_active_interfaces"] == []


def test_branch_fixed_primary_skips_cellular_commands() -> None:
    output = """
GigabitEthernet0/0/0   unassigned      YES unset  up                    up
Gi0/0/0.101            198.51.100.10   YES other  up                    up
Cellular0/2/0          unassigned      YES IPCP   up                    down
"""
    target = DeviceTarget(
        "LAB-BRANCH-01",
        "192.0.2.38",
        site_type="branch",
        transport="fixed_cellular_backup",
    )
    interface_result = evaluate_interfaces(INTERFACE_CHECK, output, target)
    assert not cellular_collection_required(target, [interface_result])
    assert all(not check.command.startswith("show cellular") for check in dry_run_checks(target))


def test_branch_failover_enables_cellular_commands() -> None:
    output = """
GigabitEthernet0/0/0   unassigned      YES unset  down                  down
Cellular0/2/0          unassigned      YES IPCP   up                    up
"""
    target = DeviceTarget(
        "TESTEDG01",
        "192.0.2.39",
        site_type="branch",
        transport="fixed_cellular_backup",
    )
    interface_result = evaluate_interfaces(INTERFACE_CHECK, output, target)
    assert cellular_collection_required(target, [interface_result])


def test_satellite_mobile_unit_skips_cellular_commands() -> None:
    target = DeviceTarget("LAB-MOBILE-02", "192.0.2.12", site_type="mobile_unit", transport="satellite")
    assert not cellular_collection_required(target, [])


def test_portable_unit_always_collects_cellular_diagnostics() -> None:
    target = DeviceTarget("LAB-PORTABLE-01", "192.0.2.14", site_type="portable_unit", transport="cellular")
    assert cellular_collection_required(target, [])


def test_telstra_and_optus_providers_are_recognised() -> None:
    telstra_output = """
Network = Telstra Mobile
Mobile Country Code (MCC) = 505
Mobile Network Code (MNC) = 01
Packet switch domain(PS) state = Attached
Registration state(EMM) = Registered
"""
    telstra = evaluate_cellular_network(CELLULAR_PROFILE[1], telstra_output)
    assert telstra.status == Status.HEALTHY
    assert telstra.evidence["provider_family"] == "Telstra"

    optus_output = telstra_output.replace("Telstra Mobile", "Optus").replace("MNC) = 01", "MNC) = 02")
    optus = evaluate_cellular_network(CELLULAR_PROFILE[1], optus_output)
    assert optus.status == Status.HEALTHY
    assert optus.evidence["provider_family"] == "Optus"
