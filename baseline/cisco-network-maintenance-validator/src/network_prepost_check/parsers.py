from __future__ import annotations

import re
from collections import Counter
from typing import Any


def parse_outputs(raw_outputs: dict[str, str]) -> dict[str, dict[str, Any]]:
    parsed: dict[str, dict[str, Any]] = {}
    for command, output in raw_outputs.items():
        command_error = _command_error(output)
        if command_error:
            parsed[command] = _parsed("command_error", 1, error=command_error)
        else:
            parser = _parser_for_command(command)
            parsed[command] = parser(output)
        parsed[command]["command"] = command
    return parsed


def _parser_for_command(command: str):
    normalized = command.lower().strip()
    parsers = {
        "show switch": parse_show_switch,
        "show version": parse_show_version,
        "show run": parse_show_running_config,
        "show running-config": parse_show_running_config,
        "show platform resources": parse_show_platform_resources,
        "show ip interface brief": parse_show_ip_interface_brief,
        "show cdp neigh": parse_show_cdp_neighbors,
        "show cdp neighbors": parse_show_cdp_neighbors,
        "show power inline": parse_show_power_inline,
        "show inventory": parse_show_inventory,
        "show switch stack-ports summary": parse_show_stack_ports_summary,
        "show stack-power": parse_show_stack_power,
        "show ip arp": parse_show_ip_arp,
        "show mac address-table": parse_show_mac_address_table,
        "show environment all": parse_show_environment_all,
        "show vlan": parse_show_vlan,
        "show ip protocols": parse_show_ip_protocols,
        "show ip ospf neigh": parse_show_ip_ospf_neighbor,
        "show ip ospf neighbor": parse_show_ip_ospf_neighbor,
        "show access-session": parse_show_access_session,
        "show device-tracking database": parse_show_device_tracking_database,
        "show etherchannel summary": parse_show_etherchannel_summary,
        "show lldp neighbors": parse_show_lldp_neighbors,
        "show sdwan control connections": parse_show_sdwan_control_connections,
        "show ip route": parse_show_ip_route,
    }
    if normalized.startswith("show interface status"):
        return parse_show_interface_status
    if normalized.startswith("show ip protocols"):
        return parse_show_ip_protocols
    if normalized.startswith("show ip route"):
        return parse_show_ip_route
    return parsers.get(normalized, parse_generic_output)


def parse_generic_output(output: str) -> dict[str, Any]:
    lines = _meaningful_lines(output)
    return _parsed("generic", len(lines), line_count=len(lines), empty=not bool(lines))


def parse_show_switch(output: str) -> dict[str, Any]:
    members = {}
    pattern = re.compile(
        r"^\*?\s*(\d+)\s+(\S+)\s+([0-9a-f.]+)\s+(\d+)\s+(\S+)\s+(\S+)",
        re.IGNORECASE,
    )
    for line in _meaningful_lines(output):
        match = pattern.match(line)
        if match:
            member, role, mac, priority, version, state = match.groups()
            members[member] = {
                "role": role,
                "mac": mac.lower(),
                "priority": int(priority),
                "version": version,
                "state": state,
            }
    ready = sorted(member for member, data in members.items() if data["state"].lower() == "ready")
    return _parsed(
        "show_switch",
        len(members),
        member_count=len(members),
        ready_member_count=len(ready),
        members=members,
        ready_members=ready,
    )


def parse_show_version(output: str) -> dict[str, Any]:
    version_match = re.search(r"Cisco IOS XE Software, Version\s+([^,\s]+)", output, re.I)
    if not version_match:
        version_match = re.search(r"Version\s+([^,\s]+)", output, re.I)
    uptime_match = re.search(r"^(.+?) uptime is (.+)$", output, re.I | re.M)
    reload_match = re.search(r"Last reload reason:\s*(.+)$", output, re.I | re.M)
    image_match = re.search(r'System image file is\s+"?([^"\r\n]+)', output, re.I)
    model_match = re.search(r"Model [Nn]umber\s*:\s*(\S+)", output)
    if not model_match:
        model_match = re.search(r"^cisco\s+(\S+)\s+.+bytes of memory", output, re.I | re.M)
    facts = {
        "device_hostname": uptime_match.group(1).strip() if uptime_match else None,
        "software_version": version_match.group(1) if version_match else None,
        "uptime": uptime_match.group(2).strip() if uptime_match else None,
        "last_reload_reason": reload_match.group(1).strip() if reload_match else None,
        "system_image": image_match.group(1).strip() if image_match else None,
        "model": model_match.group(1).strip() if model_match else None,
    }
    return _parsed("show_version", sum(value is not None for value in facts.values()), **facts)


def parse_show_running_config(output: str) -> dict[str, Any]:
    lines = [line.rstrip() for line in output.splitlines()]
    config_lines = [line for line in lines if line.strip() and not line.lstrip().startswith("!")]
    top_level = [line.strip() for line in config_lines if not line.startswith(" ")]
    return _parsed(
        "show_running_config",
        len(config_lines),
        config_line_count=len(config_lines),
        interface_stanza_count=sum(line.startswith("interface ") for line in top_level),
        router_stanza_count=sum(line.startswith("router ") for line in top_level),
        vlan_stanza_count=sum(bool(re.match(r"^vlan\s+\d", line)) for line in top_level),
        shutdown_count=sum(line.strip() == "shutdown" for line in config_lines),
    )


def parse_show_platform_resources(output: str) -> dict[str, Any]:
    resources = {}
    for line in _meaningful_lines(output):
        match = re.match(r"^\s*(.+?)\s+(\S+\([^)]*\)|\d+(?:\.\d+)?%)\s+.*\s([HWC])\s*$", line)
        if not match:
            continue
        name, usage_text, state = match.groups()
        percent_match = re.search(r"(\d+(?:\.\d+)?)%", usage_text)
        resources[name.strip()] = {
            "usage_percent": float(percent_match.group(1)) if percent_match else None,
            "state": state,
        }
    return _parsed("show_platform_resources", len(resources), resources=resources)


def parse_show_interface_status(output: str) -> dict[str, Any]:
    status_words = {
        "connected",
        "notconnect",
        "disabled",
        "err-disabled",
        "inactive",
        "sfpabsent",
        "suspended",
        "monitoring",
    }
    interfaces = {}
    for line in _meaningful_lines(output):
        if line.lower().startswith("port "):
            continue
        parts = line.split()
        status_index = next(
            (index for index, part in enumerate(parts) if part.lower() in status_words), None
        )
        if status_index is None or status_index + 3 >= len(parts):
            continue
        status = parts[status_index].lower()
        interfaces[parts[0]] = {
            "status": status,
            "vlan": parts[status_index + 1],
            "duplex": parts[status_index + 2],
            "speed": parts[status_index + 3],
        }
    counts = Counter(item["status"] for item in interfaces.values())
    return _parsed(
        "show_interface_status",
        len(interfaces),
        interface_count=len(interfaces),
        connected_count=counts.get("connected", 0),
        status_counts=dict(sorted(counts.items())),
        interfaces=interfaces,
    )


def parse_show_ip_interface_brief(output: str) -> dict[str, Any]:
    interfaces = {}
    pattern = re.compile(r"^(\S+)\s+(\S+)\s+\S+\s+\S+\s+(.+?)\s+(up|down)\s*$", re.I)
    for line in _meaningful_lines(output):
        if line.lower().startswith("interface "):
            continue
        match = pattern.match(line)
        if match:
            name, address, status, protocol = match.groups()
            interfaces[name] = {
                "ip_address": address,
                "status": status.strip().lower(),
                "protocol": protocol.lower(),
            }
    up_up = sorted(
        name
        for name, data in interfaces.items()
        if data["status"] == "up" and data["protocol"] == "up"
    )
    return _parsed(
        "show_ip_interface_brief",
        len(interfaces),
        interface_count=len(interfaces),
        up_up_count=len(up_up),
        up_up_interfaces=up_up,
        interfaces=interfaces,
    )


def parse_show_ip_ospf_neighbor(output: str) -> dict[str, Any]:
    neighbors = {}
    for line in _meaningful_lines(output):
        parts = line.split()
        if len(parts) < 6 or not _is_ipv4(parts[0]):
            continue
        neighbor_id = parts[0]
        neighbors[neighbor_id] = {
            "state": parts[2],
            "address": parts[-2] if _is_ipv4(parts[-2]) else None,
            "interface": parts[-1],
        }
    full = sorted(
        key for key, data in neighbors.items() if data["state"].upper().startswith("FULL")
    )
    return _parsed(
        "show_ip_ospf_neighbor",
        len(neighbors),
        neighbor_count=len(neighbors),
        full_neighbor_count=len(full),
        neighbor_ids=sorted(neighbors),
        full_neighbor_ids=full,
        neighbors=neighbors,
    )


def parse_show_ip_protocols(output: str) -> dict[str, Any]:
    instances = sorted(
        {
            match.strip()
            for match in re.findall(r'^\s*Routing Protocol is\s+"([^"]+)"', output, re.I | re.M)
        }
    )
    protocols = sorted({instance.split()[0].lower() for instance in instances if instance.split()})
    ospf_processes = sorted(
        instance for instance in instances if instance.lower().startswith("ospf ")
    )
    return _parsed(
        "show_ip_protocols",
        len(instances),
        protocol_instances=instances,
        protocols=protocols,
        ospf_running=bool(ospf_processes),
        ospf_processes=ospf_processes,
    )


def parse_show_etherchannel_summary(output: str) -> dict[str, Any]:
    channels = {}
    pattern = re.compile(r"^(\d+)\s+(Po\d+)\(([^)]+)\)\s+(\S+)\s+(.+)$", re.I)
    for line in _meaningful_lines(output):
        match = pattern.match(line)
        if not match:
            continue
        group, name, flags, protocol, members_text = match.groups()
        members = {}
        for member, member_flags in re.findall(r"(\S+)\(([^)]+)\)", members_text):
            members[member] = member_flags
        channels[name] = {
            "group": group,
            "flags": flags,
            "protocol": protocol,
            "members": members,
        }
    healthy_members = sorted(
        f"{channel}:{member}"
        for channel, data in channels.items()
        for member, flags in data["members"].items()
        if "P" in flags
    )
    return _parsed(
        "show_etherchannel_summary",
        len(channels),
        port_channel_count=len(channels),
        healthy_member_count=len(healthy_members),
        healthy_members=healthy_members,
        port_channels=channels,
    )


def parse_show_environment_all(output: str) -> dict[str, Any]:
    unhealthy = []
    health_words = {"good", "green", "ok", "normal"}
    issue_words = {"alarm", "critical", "fail", "failed", "fault", "shutdown", "bad"}
    for line in _meaningful_lines(output):
        lowered = line.lower()
        if "no alarm" in lowered:
            continue
        fan_match = re.match(r"^\s*(\d+)\s+(\d+)\s+\d+\s+(\S+)\s+", line)
        if fan_match:
            switch, fan, state = fan_match.groups()
            if state.lower() != "ok":
                unhealthy.append(f"Switch {switch} fan {fan}: {state}")
            continue
        if any(re.search(rf"\b{word}\b", lowered) for word in issue_words):
            unhealthy.append(line.strip())
            continue
        sensor_match = re.match(r"^\s*(.+?)\s+(\d+[A-Z]?)\s+(\S+)\s+", line)
        if sensor_match and sensor_match.group(3).lower() not in health_words:
            state = sensor_match.group(3).lower()
            if state not in {"location", "pid", "serial#"}:
                unhealthy.append(line.strip())
    return _parsed(
        "show_environment_all",
        1 if output.strip() else 0,
        issue_count=len(set(unhealthy)),
        issue_lines=sorted(set(unhealthy)),
    )


def parse_show_stack_ports_summary(output: str) -> dict[str, Any]:
    ports = {}
    for line in _meaningful_lines(output):
        parts = line.split()
        if len(parts) < 8 or not re.match(r"^\d+/\d+$", parts[0]):
            continue
        ports[parts[0]] = {
            "status": parts[1],
            "neighbor": parts[2],
            "link_ok": parts[4],
            "link_active": parts[5],
            "sync_ok": parts[6],
            "loopback": parts[-1],
        }
    unhealthy = sorted(
        name
        for name, data in ports.items()
        if data["status"].lower() != "ok"
        or data["link_ok"].lower() != "yes"
        or data["link_active"].lower() != "yes"
        or data["sync_ok"].lower() != "yes"
        or data["loopback"].lower() != "no"
    )
    return _parsed(
        "show_stack_ports_summary",
        len(ports),
        port_count=len(ports),
        unhealthy_count=len(unhealthy),
        unhealthy_ports=unhealthy,
        ports=ports,
    )


def parse_show_stack_power(output: str) -> dict[str, Any]:
    stacks = {}
    for line in _meaningful_lines(output):
        parts = line.split()
        if len(parts) >= 9 and parts[1] in {"SP-PS", "SP-RPS", "Power-Sharing", "Redundant"}:
            stacks[parts[0]] = {
                "mode": parts[1],
                "topology": parts[2],
                "total_power": _to_number(parts[3]),
                "available_power": _to_number(parts[6]),
                "switch_count": _to_number(parts[7]),
                "power_supply_count": _to_number(parts[8]),
            }
    return _parsed("show_stack_power", len(stacks), stacks=stacks)


def parse_show_power_inline(output: str) -> dict[str, Any]:
    ports = {}
    for line in _meaningful_lines(output):
        parts = line.split()
        if len(parts) < 4 or not _looks_like_interface(parts[0]):
            continue
        if parts[1].lower() not in {"auto", "static", "off", "never"}:
            continue
        ports[parts[0]] = {
            "admin": parts[1].lower(),
            "oper": parts[2].lower(),
            "power_watts": _to_number(parts[3]),
        }
    powered = sorted(name for name, data in ports.items() if data["oper"] == "on")
    faults = sorted(
        name
        for name, data in ports.items()
        if data["oper"] in {"deny", "fault", "error", "overdrawn"}
    )
    return _parsed(
        "show_power_inline",
        len(ports),
        port_count=len(ports),
        powered_count=len(powered),
        powered_ports=powered,
        fault_count=len(faults),
        fault_ports=faults,
        ports=ports,
    )


def parse_show_inventory(output: str) -> dict[str, Any]:
    items = {}
    pending_name = None
    for line in output.splitlines():
        name_match = re.match(r'^NAME:\s*"([^"]+)"', line.strip())
        if name_match:
            pending_name = name_match.group(1).strip()
            continue
        details_match = re.match(
            r"^PID:\s*([^,]*),\s*VID:\s*([^,]*),\s*SN:\s*(.*)$", line.strip(), re.I
        )
        if details_match and pending_name:
            pid, vid, serial = (value.strip() for value in details_match.groups())
            items[pending_name] = {"pid": pid, "vid": vid, "serial": serial}
            pending_name = None
    return _parsed("show_inventory", len(items), item_count=len(items), items=items)


def parse_show_vlan(output: str) -> dict[str, Any]:
    vlans = {}
    for line in _meaningful_lines(output):
        match = re.match(r"^(\d+)\s+(\S+)\s+(active|act/unsup|suspend|shutdown)\b", line, re.I)
        if match:
            vlan_id, name, status = match.groups()
            vlans[vlan_id] = {"name": name, "status": status.lower()}
    active = sorted((key for key, data in vlans.items() if data["status"] == "active"), key=int)
    return _parsed(
        "show_vlan",
        len(vlans),
        vlan_count=len(vlans),
        active_vlan_count=len(active),
        active_vlans=active,
        vlans=vlans,
    )


def parse_show_cdp_neighbors(output: str) -> dict[str, Any]:
    neighbors = {}
    pending_device = None
    interface_pattern = re.compile(
        r"\b((?:Gig|Ten|Two|Fas|Eth|Te|Gi|Tw)\s*\d+(?:/\d+)+)\s+(\d+)\s+"
    )
    for line in _meaningful_lines(output):
        if line.startswith(("Capability", "Device ID", "Total cdp", "S -", "D -")):
            continue
        match = interface_pattern.search(line)
        if not match:
            pending_device = line.strip()
            continue
        prefix = line[: match.start()].strip()
        device = prefix or pending_device
        if not device:
            continue
        local_interface = re.sub(r"\s+", "", match.group(1))
        remainder = line[match.end() :].split()
        port_id = " ".join(remainder[-2:]) if len(remainder) >= 2 else ""
        key = f"{device}|{local_interface}"
        neighbors[key] = {
            "device_id": device,
            "local_interface": local_interface,
            "port_id": port_id,
        }
        pending_device = None
    return _parsed(
        "show_cdp_neighbors",
        len(neighbors),
        neighbor_count=len(neighbors),
        neighbors=neighbors,
    )


def parse_show_lldp_neighbors(output: str) -> dict[str, Any]:
    neighbors = {}
    interface_pattern = re.compile(r"(?:Gi|Te|Tw|Fa|Eth|Po)\d+(?:/\d+)+", re.I)
    for line in _meaningful_lines(output):
        if line.startswith(("Capability", "(", "Device ID")):
            continue
        match = interface_pattern.search(line)
        if not match:
            continue
        device = line[: match.start()].strip()
        local_interface = match.group(0)
        remainder = line[match.end() :].split()
        if not device or not remainder:
            continue
        port_id = remainder[-1]
        key = f"{device}|{local_interface}"
        neighbors[key] = {
            "device_id": device,
            "local_interface": local_interface,
            "port_id": port_id,
        }
    return _parsed(
        "show_lldp_neighbors",
        len(neighbors),
        neighbor_count=len(neighbors),
        neighbors=neighbors,
    )


def parse_show_access_session(output: str) -> dict[str, Any]:
    sessions = {}
    for line in _meaningful_lines(output):
        parts = line.split()
        if len(parts) < 6 or not _looks_like_interface(parts[0]) or not _is_mac(parts[1]):
            continue
        interface, mac, method, domain, status = parts[:5]
        key = f"{interface}|{mac.lower()}"
        sessions[key] = {
            "interface": interface,
            "mac": mac.lower(),
            "method": method.lower(),
            "domain": domain.upper(),
            "status": status,
        }
    authorized = sorted(key for key, data in sessions.items() if data["status"].lower() == "auth")
    return _parsed(
        "show_access_session",
        len(sessions),
        session_count=len(sessions),
        authorized_count=len(authorized),
        authorized_sessions=authorized,
        sessions=sessions,
    )


def parse_show_device_tracking_database(output: str) -> dict[str, Any]:
    bindings = {}
    states = {"REACHABLE", "STALE", "VERIFY", "DOWN", "INCOMPLETE", "PROBE"}
    for line in _meaningful_lines(output):
        parts = line.split()
        if len(parts) < 8 or parts[0] not in {"ARP", "ND", "DH4", "DH6", "PKT", "API", "L", "S"}:
            continue
        if not _is_mac(parts[2]):
            continue
        state = next((part.upper() for part in parts[6:] if part.upper() in states), "UNKNOWN")
        key = f"{parts[1]}|{parts[2].lower()}"
        bindings[key] = {
            "address": parts[1],
            "mac": parts[2].lower(),
            "interface": parts[3],
            "vlan": parts[4],
            "state": state,
        }
    reachable = sorted(key for key, data in bindings.items() if data["state"] == "REACHABLE")
    return _parsed(
        "show_device_tracking_database",
        len(bindings),
        binding_count=len(bindings),
        reachable_count=len(reachable),
        reachable_bindings=reachable,
        bindings=bindings,
    )


def parse_show_ip_arp(output: str) -> dict[str, Any]:
    entries = {}
    for line in _meaningful_lines(output):
        parts = line.split()
        if len(parts) < 5 or parts[0].lower() not in {"internet", "internet6"}:
            continue
        address = parts[1]
        mac = parts[3].lower()
        interface = parts[-1] if len(parts) >= 6 else None
        entries[address] = {"mac": mac, "interface": interface}
    incomplete = sorted(key for key, data in entries.items() if data["mac"].lower() == "incomplete")
    return _parsed(
        "show_ip_arp",
        len(entries),
        entry_count=len(entries),
        incomplete_count=len(incomplete),
        incomplete_entries=incomplete,
        entries=entries,
    )


def parse_show_mac_address_table(output: str) -> dict[str, Any]:
    entries = {}
    pattern = re.compile(r"^\s*(All|\d+)\s+([0-9a-f.]+)\s+(STATIC|DYNAMIC)\s+(\S+)", re.I)
    for line in _meaningful_lines(output):
        match = pattern.match(line)
        if not match:
            continue
        vlan, mac, entry_type, port = match.groups()
        key = f"{vlan}|{mac.lower()}"
        entries[key] = {"vlan": vlan, "mac": mac.lower(), "type": entry_type.upper(), "port": port}
    static_entries = sorted(key for key, data in entries.items() if data["type"] == "STATIC")
    dynamic_entries = sorted(key for key, data in entries.items() if data["type"] == "DYNAMIC")
    return _parsed(
        "show_mac_address_table",
        len(entries),
        entry_count=len(entries),
        static_count=len(static_entries),
        dynamic_count=len(dynamic_entries),
        static_entries=static_entries,
        dynamic_entries=dynamic_entries,
        entries=entries,
    )


def parse_show_sdwan_control_connections(output: str) -> dict[str, Any]:
    connections = {}
    for line in _meaningful_lines(output):
        parts = line.split()
        lowered = [part.lower() for part in parts]
        if len(parts) < 4 or not any(state in lowered for state in {"up", "connect", "connected"}):
            continue
        identity = "|".join(parts[:3])
        state = next(part for part in parts if part.lower() in {"up", "connect", "connected"})
        connections[identity] = {"state": state.lower(), "fields": parts[:4]}
    return _parsed(
        "show_sdwan_control_connections",
        len(connections),
        connected_count=len(connections),
        connections=connections,
    )


def parse_show_ip_route(output: str) -> dict[str, Any]:
    routes = {}
    protocol_counts: Counter[str] = Counter()
    pattern = re.compile(r"^([A-Z](?:\s+[A-Z0-9]+)?\*?)\s+(\d+\.\d+\.\d+\.\d+/\d+)\s+(.+)$")
    for line in _meaningful_lines(output):
        match = pattern.match(line)
        if not match:
            continue
        protocol, prefix, details = match.groups()
        next_hop_match = re.search(r"via\s+(\d+\.\d+\.\d+\.\d+)", details)
        normalized_protocol = " ".join(protocol.split())
        routes[prefix] = {
            "protocol": normalized_protocol,
            "next_hop": next_hop_match.group(1) if next_hop_match else None,
        }
        protocol_counts[normalized_protocol] += 1
    return _parsed(
        "show_ip_route",
        len(routes),
        route_count=len(routes),
        default_route_present="0.0.0.0/0" in routes,
        protocol_counts=dict(sorted(protocol_counts.items())),
        routes=routes,
    )


def _parsed(parser: str, matched_rows: int, **facts: Any) -> dict[str, Any]:
    return {
        "parser": parser,
        "matched_rows": matched_rows,
        "parse_success": matched_rows > 0,
        **facts,
    }


def _meaningful_lines(output: str) -> list[str]:
    return [line.rstrip() for line in output.splitlines() if line.strip()]


def _is_ipv4(value: str) -> bool:
    return bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", value))


def _is_mac(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{4}(?:\.[0-9a-f]{4}){2}", value, re.I))


def _looks_like_interface(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z-]+\d+(?:/\d+)+$", value))


def _to_number(value: str) -> int | float | None:
    try:
        number = float(value)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _command_error(output: str) -> str | None:
    for line in _meaningful_lines(output):
        stripped = line.strip()
        if stripped.startswith("%") and any(
            phrase in stripped.lower()
            for phrase in ("invalid input", "incomplete command", "ambiguous command")
        ):
            return stripped
    return None
