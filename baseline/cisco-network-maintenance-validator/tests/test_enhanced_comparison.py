from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from network_prepost_check.compare import compare_parsed_outputs
from network_prepost_check.output_store import (
    build_run_folder_name,
    find_latest_parsed_output,
    update_precheck_index,
)
from network_prepost_check.parsers import parse_outputs

CONFIG = {
    "connected_interface_critical_drop_percent": 20,
    "access_session_warning_drop_percent": 20,
    "dynamic_table_warning_drop_percent": 25,
    "route_warning_drop_percent": 25,
}


class OutputFolderTests(unittest.TestCase):
    def test_precheck_folder_name_includes_run_type(self) -> None:
        folder = build_run_folder_name("LABSW004", "pre", "010826_165000")
        self.assertEqual(folder, "LABSW004_PRE_010826_165000")

    def test_postcheck_folder_name_includes_run_type(self) -> None:
        folder = build_run_folder_name("LABSW004", "post", "010826_165215")
        self.assertEqual(folder, "LABSW004_POST_010826_165215")

    def test_precheck_index_finds_typed_run_folder(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            run_folder = build_run_folder_name("LABSW004", "pre", "010826_165000")
            parsed_file = output_root / run_folder / "precheck" / "parsed_outputs.json"
            parsed_file.parent.mkdir(parents=True)
            parsed_file.write_text("{}", encoding="utf-8")
            update_precheck_index(output_root, "192.0.2.10", "LABSW004", parsed_file)

            found = find_latest_parsed_output(output_root, "192.0.2.10", "precheck")

            self.assertEqual(found, parsed_file)


class ParserCoverageTests(unittest.TestCase):
    def test_all_configured_command_families_have_structured_parsers(self) -> None:
        raw = {
            "show switch": """Switch# Role Mac Address Priority Version State
*1 Active 0011.2233.4455 15 V01 Ready
 2 Standby 0066.7788.99aa 14 V01 Ready
""",
            "show version": """Cisco IOS XE Software, Version 17.09.04a
TESTSW01 uptime is 5 weeks, 2 days
System image file is \"flash:packages.conf\"
Last reload reason: Reload Command
Model Number : C9300-48U
""",
            "show run": """hostname TESTSW01
!
interface Vlan10
 ip address 192.0.2.1 255.255.255.0
!
router ospf 1
!
vlan 10
""",
            "show platform resources": """Resource Usage Max Warning Critical State
Control Processor 4.80% 100% 90% 95% H
DRAM 3607MB(47%) 7566MB 85% 90% H
""",
            "show interface status": """Port Name Status Vlan Duplex Speed Type
Gi1/0/1 Uplink connected trunk a-full a-1000 10/100/1000BaseTX
Gi1/0/2 User notconnect 10 auto auto 10/100/1000BaseTX
""",
            "show interface status | in connected": (
                "Gi1/0/1 Uplink connected trunk a-full a-1000 10/100/1000BaseTX\n"
            ),
            "show ip interface brief": """Interface IP-Address OK? Method Status Protocol
Vlan10 192.0.2.1 YES NVRAM up up
Vlan20 unassigned YES unset administratively down down
""",
            "show cdp neigh": """Device ID Local Intrfce Holdtme Capability Platform Port ID
DIST01.example.test
                 Gig 1/0/1 153 R S C C9300 Gig 1/0/48
""",
            "show power inline": """Interface Admin Oper Power Device Class Max
Gi1/0/1 auto on 15.4 Phone 3 30.0
""",
            "show inventory": """NAME: \"Switch 1\", DESCR: \"C9300-48U\"
PID: C9300-48U, VID: V01, SN: TESTSERIAL1
""",
            "show switch stack-ports summary": """Sw#/Port# Port Status Neighbor/Port
1/1 OK 2/2 50cm Yes Yes Yes 1 No
""",
            "show stack-power": "Powerstack-1 SP-PS Ring 2200 30 500 1670 2 4\n",
            "show ip arp": """Protocol Address Age (min) Hardware Addr Type Interface
Internet 192.0.2.2 10 0011.2233.4455 ARPA Vlan10
""",
            "show mac address-table": """Vlan Mac Address Type Ports
10 0011.2233.4455 DYNAMIC Gi1/0/1
10 00aa.bbcc.ddee STATIC Vl10
""",
            "show environment all": """Sensor Location State Reading Range
SYSTEM INLET 1 GREEN 25 Celsius 0 - 56
1 1 5440 OK Front to Back
""",
            "show vlan": """VLAN Name Status Ports
10 USERS active Gi1/0/1
1002 fddi-default act/unsup
""",
            "show ip ospf neigh": """Neighbor ID Pri State Dead Time Address Interface
192.0.2.2 1 FULL/DR 00:00:32 192.0.2.2 Vlan10
""",
            "show ip protocols": 'Routing Protocol is "ospf 10"\n',
            "show access-session": """Interface MAC Address Method Domain Status Fg Session ID
Gi1/0/1 0011.2233.4455 dot1x DATA Auth AABBCC
""",
            "show device-tracking database": """Network Layer Address Link Layer Address
ARP 192.0.2.2 0011.2233.4455 Gi1/0/1 10 0005 20s REACHABLE 200s
""",
            "show etherchannel summary": ("1 Po1(SU) LACP Gi1/0/47(P) Gi2/0/47(P)\n"),
            "show lldp neighbors": """Device ID Local Intf Hold-time Capability Port ID
DIST01 Gi1/0/1 120 B,R Gi1/0/48
""",
            "show sdwan control connections": "vsmart 192.0.2.10 203.0.113.10 up\n",
            "show ip route": """S* 0.0.0.0/0 [1/0] via 192.0.2.254
O E2 198.51.100.0/24 [110/20] via 192.0.2.2
""",
        }
        parsed = parse_outputs(raw)
        expected_parsers = {
            "show_switch",
            "show_version",
            "show_running_config",
            "show_platform_resources",
            "show_interface_status",
            "show_ip_interface_brief",
            "show_cdp_neighbors",
            "show_power_inline",
            "show_inventory",
            "show_stack_ports_summary",
            "show_stack_power",
            "show_ip_arp",
            "show_mac_address_table",
            "show_environment_all",
            "show_vlan",
            "show_ip_ospf_neighbor",
            "show_ip_protocols",
            "show_access_session",
            "show_device_tracking_database",
            "show_etherchannel_summary",
            "show_lldp_neighbors",
            "show_sdwan_control_connections",
            "show_ip_route",
        }
        self.assertEqual({value["parser"] for value in parsed.values()}, expected_parsers)
        for command, data in parsed.items():
            with self.subTest(command=command):
                self.assertTrue(data["parse_success"])
                self.assertGreater(data["matched_rows"], 0)

    def test_volatile_ages_and_holdtimes_are_not_stored(self) -> None:
        before = parse_outputs(
            {
                "show ip arp": "Internet 192.0.2.2 10 0011.2233.4455 ARPA Vlan10\n",
                "show cdp neigh": "DIST01 Gig 1/0/1 100 R S C C9300 Gig 1/0/48\n",
                "show device-tracking database": (
                    "ARP 192.0.2.2 0011.2233.4455 Gi1/0/1 10 0005 20s REACHABLE 200s\n"
                ),
            }
        )
        after = parse_outputs(
            {
                "show ip arp": "Internet 192.0.2.2 25 0011.2233.4455 ARPA Vlan10\n",
                "show cdp neigh": "DIST01 Gig 1/0/1 155 R S C C9300 Gig 1/0/48\n",
                "show device-tracking database": (
                    "ARP 192.0.2.2 0011.2233.4455 Gi1/0/1 10 0005 80s REACHABLE 140s\n"
                ),
            }
        )
        self.assertEqual(before, after)

    def test_invalid_command_is_reported_as_command_error(self) -> None:
        parsed = parse_outputs({"show stack-power": "% Invalid input detected at '^' marker.\n"})
        self.assertEqual(parsed["show stack-power"]["parser"], "command_error")


class ComparisonBehaviorTests(unittest.TestCase):
    def _compare(self, before_raw: dict[str, str], after_raw: dict[str, str]) -> list[dict]:
        return compare_parsed_outputs(
            parse_outputs(before_raw),
            parse_outputs(after_raw),
            CONFIG,
        )

    def test_edge_show_version_produces_all_v13_comparisons(self) -> None:
        before = {
            "show version": (
                "Cisco IOS XE Software, Version 17.12.07b\n"
                "LABEDG01 uptime is 11 weeks, 4 days\n"
                'System image file is "bootflash:packages.conf"\n'
                "Model Number : C8200-1N-4T\n"
            )
        }
        after = {"show version": before["show version"].replace("11 weeks, 4 days", "11 weeks, 5 days")}

        results = self._compare(before, after)

        self.assertEqual(
            {item["check"] for item in results},
            {"Uptime", "Software version", "System image", "Hardware model"},
        )
        uptime = next(item for item in results if item["check"] == "Uptime")
        self.assertEqual(uptime["severity"], "expected")

    def test_same_count_ospf_neighbor_replacement_is_critical(self) -> None:
        before = {
            "show ip ospf neigh": (
                "192.0.2.1 1 FULL/DR 00:00:30 192.0.2.1 Vlan10\n"
                "192.0.2.2 1 FULL/BDR 00:00:30 192.0.2.2 Vlan10\n"
            )
        }
        after = {
            "show ip ospf neigh": (
                "192.0.2.1 1 FULL/DR 00:00:30 192.0.2.1 Vlan10\n"
                "192.0.2.3 1 FULL/BDR 00:00:30 192.0.2.3 Vlan10\n"
            )
        }
        results = self._compare(before, after)
        identity = next(item for item in results if item["check"] == "Baseline neighbor identity")
        self.assertEqual(identity["severity"], "critical")
        self.assertIn("192.0.2.2", identity["message"])

    def test_non_full_ospf_state_is_critical(self) -> None:
        before = {"show ip ospf neigh": "192.0.2.1 1 FULL/DR 00:00:30 192.0.2.1 Vlan10\n"}
        after = {"show ip ospf neigh": "192.0.2.1 1 EXSTART/DR 00:00:30 192.0.2.1 Vlan10\n"}
        state = next(
            item
            for item in self._compare(before, after)
            if item["check"] == "Neighbor adjacency state"
        )
        self.assertEqual(state["severity"], "critical")

    def test_ospf_is_not_applicable_when_protocol_is_not_running(self) -> None:
        raw = {
            "show ip protocols": "No routing protocols configured.\n",
            "show ip ospf neigh": "",
        }
        results = self._compare(raw, raw)
        applicability = next(item for item in results if item["check"] == "OSPF applicability")
        self.assertEqual(applicability["severity"], "ok")
        self.assertEqual(
            applicability["message"],
            "Not applicable: OSPF is not running on this switch.",
        )

    def test_running_ospf_without_neighbors_is_warning(self) -> None:
        raw = {
            "show ip protocols": 'Routing Protocol is "ospf 10"\n',
            "show ip ospf neigh": "",
        }
        results = self._compare(raw, raw)
        availability = next(
            item for item in results if item["check"] == "OSPF neighbor availability"
        )
        self.assertEqual(availability["severity"], "warning")

    def test_removed_ospf_process_is_critical(self) -> None:
        before = {
            "show ip protocols": 'Routing Protocol is "ospf 10"\n',
            "show ip ospf neigh": "",
        }
        after = {
            "show ip protocols": "No routing protocols configured.\n",
            "show ip ospf neigh": "",
        }
        results = self._compare(before, after)
        protocol_state = next(item for item in results if item["check"] == "OSPF protocol state")
        self.assertEqual(protocol_state["severity"], "critical")

    def test_edge_router_requires_ospf_neighbors(self) -> None:
        raw = {
            "show ip protocols vrf 2": 'Routing Protocol is "ospf 20"\n',
            "show ip ospf neigh": "",
        }
        results = compare_parsed_outputs(
            parse_outputs(raw),
            parse_outputs(raw),
            {**CONFIG, "device_type": "edge_router", "ospf_neighbors_required": True},
        )
        required = next(item for item in results if item["check"] == "Required OSPF neighbors")
        self.assertEqual(required["severity"], "critical")
        self.assertIn("edge router", required["message"])

    def test_edge_router_with_full_ospf_neighbor_is_ok(self) -> None:
        raw = {
            "show ip protocols vrf 2": 'Routing Protocol is "ospf 20"\n',
            "show ip ospf neigh": "192.0.2.1 1 FULL/DR 00:00:30 192.0.2.1 Gi0/0/0\n",
        }
        results = compare_parsed_outputs(
            parse_outputs(raw),
            parse_outputs(raw),
            {**CONFIG, "device_type": "edge_router", "ospf_neighbors_required": True},
        )
        required = next(item for item in results if item["check"] == "Required OSPF neighbors")
        self.assertEqual(required["severity"], "ok")

    def test_vrf_route_command_uses_structured_route_parser(self) -> None:
        parsed = parse_outputs(
            {
                "show ip route vrf 2": (
                    "S* 0.0.0.0/0 [1/0] via 192.0.2.254\nO 198.51.100.0/24 [110/20] via 192.0.2.1\n"
                )
            }
        )
        routes = parsed["show ip route vrf 2"]
        self.assertEqual(routes["parser"], "show_ip_route")
        self.assertEqual(routes["route_count"], 2)
        self.assertTrue(routes["default_route_present"])

    def test_lost_up_interface_is_critical(self) -> None:
        before = {"show ip interface brief": "Vlan10 192.0.2.1 YES NVRAM up up\n"}
        after = {"show ip interface brief": "Vlan10 192.0.2.1 YES NVRAM down down\n"}
        result = next(
            item for item in self._compare(before, after) if item["check"] == "Up/up interfaces"
        )
        self.assertEqual(result["severity"], "critical")

    def test_unchanged_legacy_vlan_state_is_ok(self) -> None:
        raw = {"show vlan": "1002 fddi-default act/unsup\n"}
        result = next(item for item in self._compare(raw, raw) if item["check"] == "VLAN state")
        self.assertEqual(result["severity"], "ok")

    def test_missing_static_mac_is_critical(self) -> None:
        before = {"show mac address-table": "10 00aa.bbcc.ddee STATIC Vl10\n"}
        after = {"show mac address-table": "10 0011.2233.4455 DYNAMIC Gi1/0/1\n"}
        result = next(
            item for item in self._compare(before, after) if item["check"] == "Static MAC entries"
        )
        self.assertEqual(result["severity"], "critical")

    def test_lost_default_route_is_critical(self) -> None:
        before = {"show ip route": "S* 0.0.0.0/0 [1/0] via 192.0.2.254\n"}
        after = {"show ip route": "O 198.51.100.0/24 [110/20] via 192.0.2.2\n"}
        result = next(
            item for item in self._compare(before, after) if item["check"] == "Default route"
        )
        self.assertEqual(result["severity"], "critical")

    def test_lost_sdwan_connection_is_critical(self) -> None:
        before = {"show sdwan control connections": "vsmart 192.0.2.10 203.0.113.10 up\n"}
        after = {"show sdwan control connections": "No control connections\n"}
        result = next(
            item for item in self._compare(before, after) if item["check"] == "Control connections"
        )
        self.assertEqual(result["severity"], "critical")

    def test_zero_and_negative_stack_power_are_critical(self) -> None:
        before = {"show stack-power": "Powerstack-2 SP-PS Ring 8800 30 1760 7010 4 8\n"}
        after = {"show stack-power": "Powerstack-2 SP-PS Ring 0 30 0 -30 0 0\n"}
        results = self._compare(before, after)
        total = next(item for item in results if item["check"] == "Total stack power")
        available = next(item for item in results if item["check"] == "Available stack power")
        self.assertEqual(total["severity"], "critical")
        self.assertEqual(total["before"], "Powerstack-2: 8800 W")
        self.assertEqual(total["after"], "Powerstack-2: 0 W")
        self.assertEqual(available["severity"], "critical")
        self.assertEqual(available["after"], "Powerstack-2: -30 W")

    def test_legacy_baseline_requests_fresh_precheck(self) -> None:
        baseline = {
            "show switch": {
                "parser": "show_switch",
                "members": [{"member": "1", "state": "Ready"}],
            }
        }
        postcheck = parse_outputs({"show switch": "*1 Active 0011.2233.4455 15 V01 Ready\n"})
        with self.assertRaisesRegex(ValueError, "Run a fresh precheck"):
            compare_parsed_outputs(baseline, postcheck, CONFIG)


if __name__ == "__main__":
    unittest.main()
