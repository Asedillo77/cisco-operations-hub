from daily_network_health_monitor.analysis import analyse
from daily_network_health_monitor.models import Profile


def switch_profile() -> Profile:
    return Profile(
        "switch",
        "cisco_ios",
        ("show platform resources",),
        {
            "cpu_warning_percent": 80,
            "cpu_critical_percent": 90,
            "memory_warning_percent": 80,
            "memory_critical_percent": 90,
        },
    )


def test_platform_resources_use_cisco_state_not_maximum_percent() -> None:
    output = """Resource Usage Max Warning Critical State
Control Processor 2.55% 100% 90% 95% H
DRAM 3671MB(48%) 7564MB 85% 90% H
TMPFS 352MB(4%) 7564MB 40% 50% H
"""
    status, message, metrics = analyse("show platform resources", output, switch_profile())
    assert status == "healthy"
    assert message == "Cisco reports all 3 platform resource(s) in Healthy state."
    assert metrics["resources"]["Control Processor"] == {
        "usage_percent": 2.55,
        "state": "H",
    }
    assert metrics["resources"]["DRAM"] == {"usage_percent": 48.0, "state": "H"}


def test_platform_resource_warning_uses_cisco_state() -> None:
    output = """Resource Usage Max Warning Critical State
Control Processor 91% 100% 90% 95% W
DRAM 3671MB(48%) 7564MB 85% 90% H
"""
    status, message, metrics = analyse("show platform resources", output, switch_profile())
    assert status == "warning"
    assert message == "Cisco reports Warning state for: Control Processor."
    assert metrics["resources"]["Control Processor"]["state"] == "W"


def test_platform_resource_critical_uses_cisco_state() -> None:
    output = "DRAM 7000MB(92%) 7564MB 85% 90% C"
    status, message, _ = analyse("show platform resources", output, switch_profile())
    assert status == "critical"
    assert message == "Cisco reports Critical state for: DRAM."


def test_environment_failure_is_critical() -> None:
    status, message, _ = analyse(
        "show environment all", "FAN 1 OK\nPower Supply 2 FAILED", switch_profile()
    )
    assert status == "critical"
    assert "FAILED" in message


def test_environment_single_missing_supply_is_warning() -> None:
    output = """Sensor List: Environmental Monitoring
SW  PID                 Serial#     Status           Sys Pwr  PoE Pwr  Watts
--  ------------------  ----------  ---------------  -------  -------  -----
2A  PWR-C1-715WAC-P     DCC2812C0SN  OK              Good     Good     715
2B  Unknown             Unknown      No Input Power  Bad      Bad      Unknown
"""
    status, message, metrics = analyse("show environment all", output, switch_profile())
    assert status == "warning"
    assert "switch member 2 power redundancy degraded (B)" in message
    assert metrics["power_supplies"]["2"]["A"]["healthy"] is True
    assert metrics["power_supplies"]["2"]["B"]["healthy"] is False


def test_environment_member_without_healthy_supply_is_critical() -> None:
    output = """Sensor List: Environmental Monitoring
SW  PID                 Serial#     Status           Sys Pwr  PoE Pwr  Watts
1A  Unknown             Unknown      No Input Power  Bad      Bad      Unknown
1B  Unknown             Unknown      No Input Power  Bad      Bad      Unknown
"""
    status, message, metrics = analyse("show environment all", output, switch_profile())
    assert status == "critical"
    assert "switch member 1 has no healthy power supply (A, B)" in message
    assert len(metrics["critical_issues"]) == 1


def test_interface_fault_states_are_warning() -> None:
    output = """Port Name Status Vlan Duplex Speed Type
Gi1/0/1 User connected 10 a-full a-1000 BaseTX
Gi1/0/8 err-disabled 1 auto auto BaseTX
Gi1/0/9 FW2_TRUNK suspended trunk auto a-1000 BaseTX
"""
    status, message, metrics = analyse("show interface status", output, switch_profile())
    assert status == "warning"
    assert "err-disabled: Gi1/0/8" in message
    assert "suspended: Gi1/0/9" in message
    assert metrics["status_counts"] == {"connected": 1, "err-disabled": 1, "suspended": 1}


def test_power_inline_fault_is_warning() -> None:
    output = """Interface Admin Oper Power Device Class Max
Gi1/0/44 auto on 15.4 Phone 3 30.0
Gi1/0/45 auto faulty 0.0 n/a n/a 30.0
Gi1/0/46 auto off 0.0 n/a n/a 30.0
"""
    status, message, metrics = analyse("show power inline", output, switch_profile())
    assert status == "warning"
    assert message == "PoE fault state detected on: Gi1/0/45."
    assert metrics["powered_count"] == 1


def test_lldp_disabled_is_informational() -> None:
    status, message, metrics = analyse(
        "show lldp neighbors", "% LLDP is not enabled", switch_profile()
    )
    assert status == "informational"
    assert message == "LLDP is not enabled on this device."
    assert metrics == {"neighbors": 0}


def test_unanalysed_command_is_informational() -> None:
    status, message, metrics = analyse(
        "show ip protocols vrf 2", 'Routing Protocol is "ospf 2"', switch_profile()
    )
    assert status == "informational"
    assert "raw evidence" in message
    assert metrics == {}


def test_unsupported_command_is_unknown() -> None:
    status, _, _ = analyse(
        "show power inline", "% Invalid input detected at '^' marker.", switch_profile()
    )
    assert status == "unknown"


def test_show_switch_reads_state_after_version() -> None:
    output = """Switch/Stack Mac Address : cced.4de7.5700 - Local Mac Address
Switch#   Role    Mac Address     Priority Version  State
---------------------------------------------------------
*1       Active   cced.4de7.5700     15     V03     Ready
 2       Standby  a0bc.6fad.b400     14     V05     Ready
"""
    status, message, metrics = analyse("show switch", output, switch_profile())
    assert status == "healthy"
    assert message == "All 2 switch member(s) are Ready."
    assert metrics == {"members": 2, "ready": 2}


def test_show_switch_reports_member_not_ready() -> None:
    output = """Switch# Role Mac Address Priority Version State
*1 Active 0011.2233.4455 15 V01 Ready
 2 Member 0066.7788.99aa 14 V01 Init
"""
    status, message, metrics = analyse("show switch", output, switch_profile())
    assert status == "critical"
    assert "member 2: Init" in message
    assert metrics == {"members": 2, "ready": 1}
