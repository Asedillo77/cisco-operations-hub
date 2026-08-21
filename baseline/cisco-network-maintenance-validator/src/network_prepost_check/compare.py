from __future__ import annotations

from collections import Counter
from typing import Any

SEVERITY_ORDER = {"ok": 0, "expected": 1, "warning": 2, "critical": 3}


def compare_parsed_outputs(
    precheck: dict[str, dict[str, Any]],
    postcheck: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    results = []
    commands = sorted(set(precheck) | set(postcheck))
    for command in commands:
        before = precheck.get(command)
        after = postcheck.get(command)
        if before is None:
            results.append(
                _result(
                    command,
                    "Command availability",
                    "expected",
                    "Command output exists only in the postcheck.",
                )
            )
            continue
        if after is None:
            results.append(
                _result(
                    command,
                    "Command availability",
                    "critical",
                    "Command output is missing from the postcheck.",
                )
            )
            continue
        _validate_baseline_structure(command, before)
        if after.get("parser") == "show_ip_ospf_neighbor":
            results.extend(
                _compare_ospf_with_protocol_context(
                    command,
                    before,
                    after,
                    config,
                    _parsed_by_type(precheck, "show_ip_protocols"),
                    _parsed_by_type(postcheck, "show_ip_protocols"),
                )
            )
            continue
        results.extend(_compare_command(command, before, after, config))
    return results


def _validate_baseline_structure(command: str, baseline: dict[str, Any]) -> None:
    structured_fields = {
        "show_switch": "members",
        "show_interface_status": "interfaces",
        "show_ip_interface_brief": "interfaces",
        "show_ip_ospf_neighbor": "neighbors",
        "show_etherchannel_summary": "port_channels",
        "show_vlan": "vlans",
    }
    field = structured_fields.get(str(baseline.get("parser")))
    if field and not isinstance(baseline.get(field), dict):
        raise ValueError(
            f"Baseline data for '{command}' is not compatible with the enhanced checks. "
            "Run a fresh precheck before running the postcheck."
        )


def summarize_results(results: list[dict[str, Any]]) -> dict[str, int | str]:
    counts = Counter(result["severity"] for result in results)
    overall = "ok"
    for severity in ("critical", "warning", "expected"):
        if counts[severity]:
            overall = severity
            break
    return {
        "overall_status": overall,
        "ok_count": counts["ok"],
        "expected_count": counts["expected"],
        "warning_count": counts["warning"],
        "critical_count": counts["critical"],
        "total_checks": len(results),
    }


def _parsed_by_type(outputs: dict[str, dict[str, Any]], parser: str) -> dict[str, Any] | None:
    return next((data for data in outputs.values() if data.get("parser") == parser), None)


def _compare_command(
    command: str,
    before: dict[str, Any],
    after: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    parser = after.get("parser")
    handlers = {
        "show_switch": _compare_show_switch,
        "show_version": _compare_show_version,
        "show_running_config": _compare_running_config,
        "show_platform_resources": _compare_platform_resources,
        "show_interface_status": _compare_interface_status,
        "show_ip_interface_brief": _compare_ip_interface_brief,
        "show_ip_ospf_neighbor": _compare_ospf_neighbors,
        "show_ip_protocols": _compare_ip_protocols,
        "show_etherchannel_summary": _compare_etherchannel,
        "show_environment_all": _compare_environment,
        "show_stack_ports_summary": _compare_stack_ports,
        "show_stack_power": _compare_stack_power,
        "show_power_inline": _compare_power_inline,
        "show_inventory": _compare_inventory,
        "show_vlan": _compare_vlans,
        "show_cdp_neighbors": _compare_topology_neighbors,
        "show_lldp_neighbors": _compare_topology_neighbors,
        "show_access_session": _compare_access_sessions,
        "show_device_tracking_database": _compare_device_tracking,
        "show_ip_arp": _compare_arp,
        "show_mac_address_table": _compare_mac_table,
        "show_sdwan_control_connections": _compare_sdwan,
        "show_ip_route": _compare_routes,
        "command_error": _compare_command_error,
    }
    handler = handlers.get(parser)
    if handler:
        return handler(command, before, after, config)
    return _compare_generic(command, before, after, config)


def _compare_show_switch(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    before_members = before.get("members") or {}
    after_members = after.get("members") or {}
    missing = sorted(set(before_members) - set(after_members))
    replaced = sorted(
        member
        for member in set(before_members) & set(after_members)
        if before_members[member].get("mac") != after_members[member].get("mac")
    )
    not_ready = sorted(
        member
        for member, data in after_members.items()
        if str(data.get("state", "")).lower() != "ready"
    )
    results = [
        _presence_result(command, "Stack member identity", missing, replaced, critical=True),
        _issue_result(
            command,
            "Stack member state",
            not_ready,
            "All postcheck stack members are Ready.",
            "Stack members not Ready",
            "critical",
        ),
    ]
    role_changes = sorted(
        member
        for member in set(before_members) & set(after_members)
        if before_members[member].get("role") != after_members[member].get("role")
    )
    results.append(
        _change_result(
            command,
            "Stack roles",
            role_changes,
            "Stack member roles are unchanged.",
            "Stack roles changed after maintenance",
            "expected",
        )
    )
    before_shutdown = int(before.get("shutdown_count") or 0)
    after_shutdown = int(after.get("shutdown_count") or 0)
    results.append(
        _result(
            command,
            "Shutdown statements",
            "warning" if after_shutdown > before_shutdown else "ok",
            "Shutdown statement count increased."
            if after_shutdown > before_shutdown
            else "Shutdown statement count did not increase.",
            before_shutdown,
            after_shutdown,
        )
    )
    return results


def _compare_show_version(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    results = []
    for key, check, changed_severity in (
        ("software_version", "Software version", "expected"),
        ("system_image", "System image", "warning"),
        ("model", "Hardware model", "critical"),
    ):
        before_value = before.get(key)
        after_value = after.get(key)
        changed = before_value != after_value
        results.append(
            _result(
                command,
                check,
                changed_severity if changed else "ok",
                f"{check} changed after maintenance." if changed else f"{check} is unchanged.",
                before_value,
                after_value,
            )
        )
    results.append(
        _result(
            command,
            "Uptime",
            "expected",
            "Uptime normally changes across a maintenance window.",
            before.get("uptime"),
            after.get("uptime"),
        )
    )
    return results


def _compare_running_config(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    results = []
    for key, check, drop_severity in (
        ("interface_stanza_count", "Interface configuration", "critical"),
        ("router_stanza_count", "Routing configuration", "critical"),
        ("vlan_stanza_count", "VLAN configuration", "warning"),
    ):
        results.append(_count_drop_check(command, check, before, after, key, drop_severity))
    before_lines = int(before.get("config_line_count") or 0)
    after_lines = int(after.get("config_line_count") or 0)
    changed = before_lines != after_lines
    results.append(
        _result(
            command,
            "Configuration size",
            "expected" if changed else "ok",
            "Configuration line count changed; review the detailed differences."
            if changed
            else "Configuration line count is unchanged.",
            before_lines,
            after_lines,
        )
    )
    return results


def _compare_platform_resources(
    command: str, before: dict, after: dict, config: dict
) -> list[dict]:
    del config
    before_resources = before.get("resources") or {}
    resources = after.get("resources") or {}
    missing = sorted(set(before_resources) - set(resources))
    unhealthy = sorted(name for name, data in resources.items() if data.get("state") != "H")
    return [
        _issue_result(
            command,
            "Resource coverage",
            missing,
            "All baseline platform resources are still reported.",
            "Platform resources no longer reported",
            "warning",
        ),
        _issue_result(
            command,
            "Resource health",
            unhealthy,
            "All reported platform resources are Healthy.",
            "Platform resources in Warning or Critical state",
            "critical",
        ),
    ]


def _compare_interface_status(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    before_interfaces = before.get("interfaces") or {}
    after_interfaces = after.get("interfaces") or {}
    baseline_connected = {
        name for name, data in before_interfaces.items() if data.get("status") == "connected"
    }
    lost = sorted(
        name
        for name in baseline_connected
        if after_interfaces.get(name, {}).get("status") != "connected"
    )
    problem_states = {"err-disabled", "suspended", "disabled", "inactive"}
    new_problems = sorted(
        name
        for name, data in after_interfaces.items()
        if data.get("status") in problem_states
        and before_interfaces.get(name, {}).get("status") != data.get("status")
    )
    vlan_changes = sorted(
        name
        for name in baseline_connected & set(after_interfaces)
        if before_interfaces[name].get("vlan") != after_interfaces[name].get("vlan")
    )
    lost_percent = len(lost) / len(baseline_connected) * 100 if baseline_connected else 0
    critical_percent = float(config.get("connected_interface_critical_drop_percent", 20))
    lost_severity = "critical" if lost_percent >= critical_percent else "warning"
    return [
        _issue_result(
            command,
            "Baseline connected ports",
            lost,
            "All baseline connected interfaces remain connected.",
            "Baseline connected interfaces no longer connected",
            lost_severity,
            len(baseline_connected),
            len(baseline_connected) - len(lost),
        ),
        _issue_result(
            command,
            "Problem interface states",
            new_problems,
            "No new problem interface states were found.",
            "Interfaces entered a problem state",
            "critical",
        ),
        _change_result(
            command,
            "Connected-port VLAN",
            vlan_changes,
            "Connected-interface VLAN values are unchanged.",
            "Connected-interface VLAN values changed",
            "warning",
        ),
    ]


def _compare_ip_interface_brief(
    command: str, before: dict, after: dict, config: dict
) -> list[dict]:
    del config
    before_interfaces = before.get("interfaces") or {}
    after_interfaces = after.get("interfaces") or {}
    baseline_up = set(before.get("up_up_interfaces") or [])
    lost = sorted(
        name for name in baseline_up if name not in set(after.get("up_up_interfaces") or [])
    )
    ip_changes = sorted(
        name
        for name in set(before_interfaces) & set(after_interfaces)
        if before_interfaces[name].get("ip_address") != after_interfaces[name].get("ip_address")
    )
    return [
        _issue_result(
            command,
            "Up/up interfaces",
            lost,
            "All baseline up/up interfaces remain up/up.",
            "Baseline up/up interfaces lost operational state",
            "critical",
            len(baseline_up),
            len(baseline_up) - len(lost),
        ),
        _change_result(
            command,
            "Interface IP addresses",
            ip_changes,
            "Interface IP addresses are unchanged.",
            "Interface IP addresses changed",
            "warning",
        ),
    ]


def _compare_ospf_neighbors(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    before_neighbors = before.get("neighbors") or {}
    after_neighbors = after.get("neighbors") or {}
    missing = sorted(set(before_neighbors) - set(after_neighbors))
    not_full = sorted(
        neighbor
        for neighbor, data in after_neighbors.items()
        if not str(data.get("state", "")).upper().startswith("FULL")
    )
    new = sorted(set(after_neighbors) - set(before_neighbors))
    path_changes = sorted(
        neighbor
        for neighbor in set(before_neighbors) & set(after_neighbors)
        if (
            before_neighbors[neighbor].get("interface"),
            before_neighbors[neighbor].get("address"),
        )
        != (
            after_neighbors[neighbor].get("interface"),
            after_neighbors[neighbor].get("address"),
        )
    )
    return [
        _issue_result(
            command,
            "Baseline neighbor identity",
            missing,
            "All baseline OSPF neighbors remain present.",
            "Missing baseline OSPF neighbors",
            "critical",
            len(before_neighbors),
            len(before_neighbors) - len(missing),
        ),
        _issue_result(
            command,
            "Neighbor adjacency state",
            not_full,
            "All postcheck OSPF neighbors are FULL.",
            "OSPF neighbors not in FULL state",
            "critical",
        ),
        _change_result(
            command,
            "New neighbors",
            new,
            "No new OSPF neighbors were found.",
            "New OSPF neighbors found",
            "expected",
        ),
        _change_result(
            command,
            "Neighbor path",
            path_changes,
            "OSPF neighbor interfaces and addresses are unchanged.",
            "OSPF neighbor interface or address changed",
            "warning",
        ),
    ]


def _compare_ospf_with_protocol_context(
    command: str,
    before: dict,
    after: dict,
    config: dict,
    before_protocols: dict[str, Any] | None,
    after_protocols: dict[str, Any] | None,
) -> list[dict]:
    before_neighbors = before.get("neighbors") or {}
    after_neighbors = after.get("neighbors") or {}
    neighbors_required = bool(config.get("ospf_neighbors_required"))
    required_result = _result(
        command,
        "Required OSPF neighbors",
        "critical" if not after_neighbors else "ok",
        "No OSPF neighbors are present on this edge router."
        if not after_neighbors
        else "The edge router has OSPF neighbors.",
        len(before_neighbors),
        len(after_neighbors),
    )
    if before_protocols is None or after_protocols is None:
        results = _compare_ospf_neighbors(command, before, after, config)
        if neighbors_required:
            results.append(required_result)
        return results

    before_ospf = bool(before_protocols.get("ospf_running"))
    after_ospf = bool(after_protocols.get("ospf_running"))
    if (
        not neighbors_required
        and not before_ospf
        and not after_ospf
        and not before_neighbors
        and not after_neighbors
    ):
        return [
            _result(
                command,
                "OSPF applicability",
                "ok",
                "Not applicable: OSPF is not running on this switch.",
                "Not running",
                "Not running",
            )
        ]

    results = _compare_ospf_neighbors(command, before, after, config)
    if before_ospf and not after_ospf:
        results.append(
            _result(
                command,
                "OSPF protocol state",
                "critical",
                "OSPF was running during the precheck but is not running after the change.",
                "Running",
                "Not running",
            )
        )
    elif not neighbors_required and after_ospf and not after_neighbors and not before_neighbors:
        results.append(
            _result(
                command,
                "OSPF neighbor availability",
                "warning",
                "OSPF is running, but neither check reported neighbors; confirm this is intended.",
                0,
                0,
            )
        )
    if neighbors_required:
        results.append(required_result)
    return results


def _compare_ip_protocols(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    before_instances = set(before.get("protocol_instances") or [])
    after_instances = set(after.get("protocol_instances") or [])
    missing = sorted(before_instances - after_instances)
    added = sorted(after_instances - before_instances)
    missing_severity = (
        "critical" if any(item.lower().startswith("ospf ") for item in missing) else "warning"
    )
    return [
        _issue_result(
            command,
            "Routing protocol identity",
            missing,
            "All baseline routing protocol instances remain configured.",
            "Baseline routing protocol instances are missing",
            missing_severity,
            _summarize_items(sorted(before_instances)) if before_instances else "None",
            _summarize_items(sorted(after_instances)) if after_instances else "None",
        ),
        _change_result(
            command,
            "New routing protocols",
            added,
            "No new routing protocol instances were found.",
            "New routing protocol instances found",
            "expected",
        ),
    ]


def _compare_etherchannel(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    before_channels = before.get("port_channels") or {}
    after_channels = after.get("port_channels") or {}
    missing_channels = sorted(set(before_channels) - set(after_channels))
    missing_members = sorted(
        set(before.get("healthy_members") or []) - set(after.get("healthy_members") or [])
    )
    before_unhealthy = {
        name for name, data in before_channels.items() if "U" not in str(data.get("flags", ""))
    }
    after_unhealthy = {
        name for name, data in after_channels.items() if "U" not in str(data.get("flags", ""))
    }
    newly_unhealthy = sorted(after_unhealthy - before_unhealthy)
    return [
        _issue_result(
            command,
            "Port-channel identity",
            missing_channels,
            "All baseline port-channels remain present.",
            "Missing baseline port-channels",
            "critical",
        ),
        _issue_result(
            command,
            "Bundled members",
            missing_members,
            "All baseline bundled members remain bundled.",
            "Baseline EtherChannel members no longer bundled",
            "critical",
        ),
        _issue_result(
            command,
            "Port-channel state",
            newly_unhealthy,
            "No port-channels newly entered a not-in-use state.",
            "Port-channels newly not in use",
            "critical",
        ),
    ]


def _compare_environment(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    before_issues = set(before.get("issue_lines") or [])
    after_issues = set(after.get("issue_lines") or [])
    new_issues = sorted(after_issues - before_issues)
    return [
        _issue_result(
            command,
            "Environmental health",
            new_issues,
            "No new environmental faults were found.",
            "New environmental faults",
            "critical",
            len(before_issues),
            len(after_issues),
        )
    ]


def _compare_stack_ports(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    before_ports = before.get("ports") or {}
    after_ports = after.get("ports") or {}
    missing = sorted(set(before_ports) - set(after_ports))
    unhealthy = sorted(after.get("unhealthy_ports") or [])
    neighbor_changes = sorted(
        port
        for port in set(before_ports) & set(after_ports)
        if before_ports[port].get("neighbor") != after_ports[port].get("neighbor")
    )
    return [
        _issue_result(
            command,
            "Stack-port identity",
            missing,
            "All baseline stack ports remain present.",
            "Missing baseline stack ports",
            "critical",
        ),
        _issue_result(
            command,
            "Stack-port health",
            unhealthy,
            "All postcheck stack ports are healthy and synchronized.",
            "Unhealthy stack ports",
            "critical",
        ),
        _change_result(
            command,
            "Stack-port neighbor",
            neighbor_changes,
            "Stack-port neighbors are unchanged.",
            "Stack-port neighbor changed",
            "warning",
        ),
    ]


def _compare_stack_power(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    before_stacks = before.get("stacks") or {}
    after_stacks = after.get("stacks") or {}
    missing = sorted(set(before_stacks) - set(after_stacks))
    unhealthy = sorted(
        name
        for name, data in after_stacks.items()
        if str(data.get("topology", "")).lower() != "ring"
    )
    supply_drops = sorted(
        name
        for name in set(before_stacks) & set(after_stacks)
        if (after_stacks[name].get("power_supply_count") or 0)
        < (before_stacks[name].get("power_supply_count") or 0)
    )
    switch_drops = sorted(
        name
        for name in set(before_stacks) & set(after_stacks)
        if (after_stacks[name].get("switch_count") or 0)
        < (before_stacks[name].get("switch_count") or 0)
    )
    zero_total_power = sorted(
        name
        for name in set(before_stacks) & set(after_stacks)
        if (before_stacks[name].get("total_power") or 0) > 0
        and (after_stacks[name].get("total_power") or 0) <= 0
    )
    negative_available_power = sorted(
        name
        for name, data in after_stacks.items()
        if data.get("available_power") is not None and data["available_power"] < 0
    )
    before_total = _stack_power_values(before_stacks, "total_power", zero_total_power)
    after_total = _stack_power_values(after_stacks, "total_power", zero_total_power)
    before_available = _stack_power_values(
        before_stacks, "available_power", negative_available_power
    )
    after_available = _stack_power_values(after_stacks, "available_power", negative_available_power)
    return [
        _issue_result(
            command,
            "Power-stack identity",
            missing,
            "Power stacks are present.",
            "Missing power stacks",
            "critical",
        ),
        _issue_result(
            command,
            "Power-stack topology",
            unhealthy,
            "All power stacks use Ring topology.",
            "Power stacks not in Ring topology",
            "critical",
        ),
        _issue_result(
            command,
            "Power supplies",
            supply_drops,
            "Power-supply counts did not decrease.",
            "Power-supply count decreased",
            "critical",
        ),
        _issue_result(
            command,
            "Power-stack members",
            switch_drops,
            "Power-stack member counts did not decrease.",
            "Power-stack member count decreased",
            "critical",
        ),
        _issue_result(
            command,
            "Total stack power",
            zero_total_power,
            "Total stack power remains above zero.",
            "Total stack power dropped to zero",
            "critical",
            before_total,
            after_total,
        ),
        _issue_result(
            command,
            "Available stack power",
            negative_available_power,
            "Available stack power is not negative.",
            "Available stack power is negative",
            "critical",
            before_available,
            after_available,
        ),
    ]


def _stack_power_values(
    stacks: dict[str, dict[str, Any]], field: str, names: list[str]
) -> str | None:
    if not names:
        return None
    return ", ".join(f"{name}: {stacks.get(name, {}).get(field, 'N/A')} W" for name in names)


def _compare_power_inline(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    lost_power = sorted(
        set(before.get("powered_ports") or []) - set(after.get("powered_ports") or [])
    )
    new_faults = sorted(set(after.get("fault_ports") or []) - set(before.get("fault_ports") or []))
    return [
        _issue_result(
            command,
            "Powered ports",
            lost_power,
            "All baseline powered ports remain powered.",
            "Baseline powered ports no longer powered",
            "warning",
        ),
        _issue_result(
            command,
            "Inline-power faults",
            new_faults,
            "No new inline-power faults were found.",
            "New inline-power faults",
            "critical",
        ),
    ]


def _compare_inventory(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    before_items = before.get("items") or {}
    after_items = after.get("items") or {}
    missing = sorted(set(before_items) - set(after_items))
    changed = sorted(
        name
        for name in set(before_items) & set(after_items)
        if before_items[name] != after_items[name]
    )
    return [
        _issue_result(
            command,
            "Inventory presence",
            missing,
            "All baseline inventory items remain present.",
            "Missing inventory items",
            "critical",
        ),
        _change_result(
            command,
            "Hardware identity",
            changed,
            "PID, VID, and serial values are unchanged.",
            "Hardware identity changed",
            "warning",
        ),
    ]


def _compare_vlans(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    before_vlans = before.get("vlans") or {}
    after_vlans = after.get("vlans") or {}
    missing = sorted(set(before_vlans) - set(after_vlans), key=int)
    degraded = sorted(
        (
            vlan
            for vlan in set(before_vlans) & set(after_vlans)
            if before_vlans[vlan].get("status") == "active"
            and after_vlans[vlan].get("status") != "active"
        ),
        key=int,
    )
    renamed = sorted(
        (
            vlan
            for vlan in set(before_vlans) & set(after_vlans)
            if before_vlans[vlan].get("name") != after_vlans[vlan].get("name")
        ),
        key=int,
    )
    return [
        _issue_result(
            command,
            "VLAN identity",
            missing,
            "All baseline VLANs remain present.",
            "Missing baseline VLANs",
            "critical",
        ),
        _issue_result(
            command,
            "VLAN state",
            degraded,
            "No baseline-active VLANs became inactive.",
            "Baseline-active VLANs no longer active",
            "critical",
        ),
        _change_result(
            command,
            "VLAN names",
            renamed,
            "VLAN names are unchanged.",
            "VLAN names changed",
            "warning",
        ),
    ]


def _compare_topology_neighbors(
    command: str, before: dict, after: dict, config: dict
) -> list[dict]:
    del config
    before_neighbors = before.get("neighbors") or {}
    after_neighbors = after.get("neighbors") or {}
    missing = sorted(set(before_neighbors) - set(after_neighbors))
    port_changes = sorted(
        key
        for key in set(before_neighbors) & set(after_neighbors)
        if before_neighbors[key].get("port_id") != after_neighbors[key].get("port_id")
    )
    return [
        _issue_result(
            command,
            "Neighbor presence",
            missing,
            "All baseline neighbors remain present.",
            "Missing baseline neighbors",
            "warning",
            len(before_neighbors),
            len(after_neighbors),
        ),
        _change_result(
            command,
            "Remote port",
            port_changes,
            "Remote neighbor ports are unchanged.",
            "Remote neighbor ports changed",
            "warning",
        ),
    ]


def _compare_access_sessions(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    baseline = set(before.get("authorized_sessions") or [])
    current = set(after.get("authorized_sessions") or [])
    missing = sorted(baseline - current)
    drop_percent = len(missing) / len(baseline) * 100 if baseline else 0
    threshold = float(config.get("access_session_warning_drop_percent", 20))
    severity = "warning" if drop_percent >= threshold else "expected"
    unauthorized = sorted(
        key
        for key, data in (after.get("sessions") or {}).items()
        if str(data.get("status", "")).lower() != "auth"
    )
    return [
        _issue_result(
            command,
            "Authorized sessions",
            missing,
            "All baseline authorized sessions remain authorized.",
            "Baseline authorized sessions missing",
            severity,
            len(baseline),
            len(current),
        ),
        _issue_result(
            command,
            "Session state",
            unauthorized,
            "All reported postcheck sessions are authorized.",
            "Sessions not authorized",
            "warning",
        ),
    ]


def _compare_device_tracking(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    baseline = set(before.get("reachable_bindings") or [])
    current = set(after.get("reachable_bindings") or [])
    missing = sorted(baseline - current)
    drop_percent = len(missing) / len(baseline) * 100 if baseline else 0
    threshold = float(config.get("dynamic_table_warning_drop_percent", 25))
    severity = "warning" if drop_percent >= threshold else "expected"
    bad_states = sorted(
        key
        for key, data in (after.get("bindings") or {}).items()
        if data.get("state") in {"DOWN", "INCOMPLETE"}
    )
    return [
        _issue_result(
            command,
            "Reachable bindings",
            missing,
            "Baseline reachable binding count is stable.",
            "Baseline reachable bindings missing",
            severity,
            len(baseline),
            len(current),
        ),
        _issue_result(
            command,
            "Binding state",
            bad_states,
            "No DOWN or INCOMPLETE bindings were found.",
            "Bindings in DOWN or INCOMPLETE state",
            "warning",
        ),
    ]


def _compare_arp(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    before_entries = before.get("entries") or {}
    after_entries = after.get("entries") or {}
    changed = sorted(
        address
        for address in set(before_entries) & set(after_entries)
        if before_entries[address] != after_entries[address]
    )
    new_incomplete = sorted(
        set(after.get("incomplete_entries") or []) - set(before.get("incomplete_entries") or [])
    )
    return [
        _issue_result(
            command,
            "Incomplete ARP entries",
            new_incomplete,
            "No new incomplete ARP entries were found.",
            "New incomplete ARP entries",
            "warning",
        ),
        _change_result(
            command,
            "ARP bindings",
            changed,
            "Stable ARP bindings are unchanged.",
            "ARP MAC or interface changed",
            "expected",
        ),
        _count_movement_result(
            command,
            "ARP entry count",
            before.get("entry_count"),
            after.get("entry_count"),
            "expected",
        ),
    ]


def _compare_mac_table(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    before_static = set(before.get("static_entries") or [])
    after_static = set(after.get("static_entries") or [])
    missing_static = sorted(before_static - after_static)
    before_dynamic = int(before.get("dynamic_count") or 0)
    after_dynamic = int(after.get("dynamic_count") or 0)
    drop_percent = (
        (before_dynamic - after_dynamic) / before_dynamic * 100
        if before_dynamic and after_dynamic < before_dynamic
        else 0
    )
    threshold = float(config.get("dynamic_table_warning_drop_percent", 25))
    severity = "warning" if drop_percent >= threshold else "expected"
    moves = sorted(
        key
        for key in set(before.get("entries") or {}) & set(after.get("entries") or {})
        if (before.get("entries") or {})[key].get("port")
        != (after.get("entries") or {})[key].get("port")
    )
    return [
        _issue_result(
            command,
            "Static MAC entries",
            missing_static,
            "All baseline static MAC entries remain present.",
            "Missing baseline static MAC entries",
            "critical",
        ),
        _count_movement_result(
            command, "Dynamic MAC count", before_dynamic, after_dynamic, severity
        ),
        _change_result(
            command,
            "MAC port movement",
            moves,
            "No retained MAC entries moved ports.",
            "MAC entries moved ports",
            "expected",
        ),
    ]


def _compare_sdwan(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    baseline = set((before.get("connections") or {}).keys())
    current = set((after.get("connections") or {}).keys())
    missing = sorted(baseline - current)
    severity = "critical" if baseline and not current else "warning"
    return [
        _issue_result(
            command,
            "Control connections",
            missing,
            "All baseline SD-WAN control connections remain present.",
            "Missing SD-WAN control connections",
            severity,
            len(baseline),
            len(current),
        )
    ]


def _compare_routes(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    before_routes = before.get("routes") or {}
    after_routes = after.get("routes") or {}
    missing = sorted(set(before_routes) - set(after_routes))
    next_hop_changes = sorted(
        prefix
        for prefix in set(before_routes) & set(after_routes)
        if before_routes[prefix] != after_routes[prefix]
    )
    drop_percent = len(missing) / len(before_routes) * 100 if before_routes else 0
    threshold = float(config.get("route_warning_drop_percent", 25))
    severity = "warning" if drop_percent >= threshold else "expected"
    default_lost = before.get("default_route_present") and not after.get("default_route_present")
    return [
        _result(
            command,
            "Default route",
            "critical" if default_lost else "ok",
            "Baseline default route is missing."
            if default_lost
            else "Default-route presence is acceptable.",
            before.get("default_route_present"),
            after.get("default_route_present"),
        ),
        _issue_result(
            command,
            "Route prefixes",
            missing,
            "All baseline route prefixes remain present.",
            "Missing baseline route prefixes",
            severity,
            len(before_routes),
            len(after_routes),
        ),
        _change_result(
            command,
            "Route path",
            next_hop_changes,
            "Retained route protocols and next hops are unchanged.",
            "Route protocol or next hop changed",
            "warning",
        ),
    ]


def _compare_generic(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    before_count = int(before.get("line_count") or 0)
    after_count = int(after.get("line_count") or 0)
    changed = before_count != after_count
    return [
        _result(
            command,
            "Output coverage",
            "expected" if changed else "ok",
            "Generic output line count changed; review the detailed differences."
            if changed
            else "Generic output line count is unchanged.",
            before_count,
            after_count,
        )
    ]


def _compare_command_error(command: str, before: dict, after: dict, config: dict) -> list[dict]:
    del config
    same_error = before.get("error") == after.get("error")
    return [
        _result(
            command,
            "Command support",
            "expected" if same_error else "warning",
            "The device does not support this command."
            if same_error
            else "The command error changed between checks.",
            before.get("error"),
            after.get("error"),
        )
    ]


def _presence_result(
    command: str,
    check: str,
    missing: list[str],
    replaced: list[str],
    critical: bool,
) -> dict[str, Any]:
    issues = [*(f"missing {item}" for item in missing), *(f"replaced {item}" for item in replaced)]
    return _issue_result(
        command,
        check,
        issues,
        "All baseline identities remain present and unchanged.",
        "Identity changes",
        "critical" if critical else "warning",
    )


def _count_drop_check(
    command: str,
    check: str,
    before: dict,
    after: dict,
    key: str,
    severity: str,
) -> dict[str, Any]:
    before_count = int(before.get(key) or 0)
    after_count = int(after.get(key) or 0)
    dropped = after_count < before_count
    return _result(
        command,
        check,
        severity if dropped else "ok",
        f"{check} count decreased." if dropped else f"{check} count did not decrease.",
        before_count,
        after_count,
    )


def _count_movement_result(
    command: str,
    check: str,
    before_value: Any,
    after_value: Any,
    changed_severity: str,
) -> dict[str, Any]:
    changed = before_value != after_value
    return _result(
        command,
        check,
        changed_severity if changed else "ok",
        f"{check} changed." if changed else f"{check} is unchanged.",
        before_value,
        after_value,
    )


def _issue_result(
    command: str,
    check: str,
    issues: list[str],
    ok_message: str,
    issue_message: str,
    issue_severity: str,
    before_value: Any = None,
    after_value: Any = None,
) -> dict[str, Any]:
    if issues:
        message = f"{issue_message}: {_summarize_items(issues)}."
        return _result(command, check, issue_severity, message, before_value, after_value)
    return _result(command, check, "ok", ok_message, before_value, after_value)


def _change_result(
    command: str,
    check: str,
    changes: list[str],
    unchanged_message: str,
    changed_message: str,
    changed_severity: str,
) -> dict[str, Any]:
    if changes:
        return _result(
            command,
            check,
            changed_severity,
            f"{changed_message}: {_summarize_items(changes)}.",
            "unchanged",
            f"{len(changes)} change(s)",
        )
    return _result(command, check, "ok", unchanged_message, "unchanged", "unchanged")


def _summarize_items(items: list[str], limit: int = 12) -> str:
    shown = items[:limit]
    summary = ", ".join(str(item) for item in shown)
    remaining = len(items) - len(shown)
    return f"{summary} (+{remaining} more)" if remaining else summary


def _result(
    command: str,
    check: str,
    severity: str,
    message: str,
    before_value: Any = None,
    after_value: Any = None,
) -> dict[str, Any]:
    return {
        "command": command,
        "check": check,
        "severity": severity,
        "message": message,
        "before": before_value,
        "after": after_value,
        "sort_order": SEVERITY_ORDER[severity],
    }
