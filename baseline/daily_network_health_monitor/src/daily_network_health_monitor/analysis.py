from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .models import Profile

Analysis = tuple[str, str, dict[str, Any]]


def analyse(command: str, output: str, profile: Profile) -> Analysis:
    lowered = output.lower()
    if not output.strip():
        return "unknown", "The device returned no output.", {}
    if any(
        marker in lowered for marker in ("invalid input", "unknown command", "incomplete command")
    ):
        return "unknown", "Command is unsupported or not applicable on this device.", {}
    handlers: tuple[tuple[str, Callable[[str, Profile], Analysis]], ...] = (
        ("show platform resources", _platform_resources),
        ("show environment all", _environment),
        ("show switch", _switch),
        ("show ip ospf neighbor", _ospf),
        ("show sdwan control connections", _sdwan),
        ("show ip interface brief", _ip_interfaces),
        ("show interface status | in connected", _connected),
        ("show interface status", _interface_status),
        ("show power inline", _power_inline),
        ("show cdp neighbors", _neighbors),
        ("show lldp neighbors", _neighbors),
        ("show ip route", _routes),
    )
    for prefix, handler in handlers:
        if command.startswith(prefix):
            return handler(output, profile)
    return "informational", "Command completed; raw evidence was collected for review.", {}


def _platform_resources(output: str, profile: Profile) -> Analysis:
    del profile
    resources: dict[str, dict[str, float | str | None]] = {}
    pattern = re.compile(
        r"^\s*(.+?)\s+(\S+\([^)]*\)|\d+(?:\.\d+)?%)\s+.*\s([HWC])\s*$",
        re.IGNORECASE,
    )
    for line in output.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        name, usage_text, state = match.groups()
        percent_match = re.search(r"(\d+(?:\.\d+)?)%", usage_text)
        resources[name.strip()] = {
            "usage_percent": float(percent_match.group(1)) if percent_match else None,
            "state": state.upper(),
        }
    if not resources:
        return "unknown", "Platform resource rows and Cisco states could not be parsed.", {}

    critical = [name for name, data in resources.items() if data["state"] == "C"]
    warning = [name for name, data in resources.items() if data["state"] == "W"]
    metrics: dict[str, Any] = {"resources": resources}
    if critical:
        return (
            "critical",
            f"Cisco reports Critical state for: {', '.join(critical)}.",
            metrics,
        )
    if warning:
        return (
            "warning",
            f"Cisco reports Warning state for: {', '.join(warning)}.",
            metrics,
        )
    return (
        "healthy",
        f"Cisco reports all {len(resources)} platform resource(s) in Healthy state.",
        metrics,
    )


def _environment(output: str, profile: Profile) -> Analysis:
    del profile
    supplies = _power_supply_rows(output)
    critical_issues: list[str] = []
    warning_issues: list[str] = []

    for member, member_supplies in supplies.items():
        healthy = [slot for slot, data in member_supplies.items() if data["healthy"]]
        unhealthy = [slot for slot, data in member_supplies.items() if not data["healthy"]]
        if unhealthy and not healthy:
            critical_issues.append(
                f"switch member {member} has no healthy power supply ({', '.join(unhealthy)})"
            )
        elif unhealthy:
            warning_issues.append(
                f"switch member {member} power redundancy degraded ({', '.join(unhealthy)})"
            )

    sensor_critical, sensor_warning = _environment_sensor_issues(output)
    critical_issues.extend(sensor_critical)
    warning_issues.extend(sensor_warning)
    metrics: dict[str, Any] = {
        "power_supplies": supplies,
        "critical_issues": critical_issues,
        "warning_issues": warning_issues,
    }
    if critical_issues:
        return "critical", f"Environment critical: {critical_issues[0]}.", metrics
    if warning_issues:
        return "warning", f"Environment warning: {warning_issues[0]}.", metrics
    if supplies or "environment" in output.lower() or "fan" in output.lower():
        return "healthy", "Power, fan, and temperature indicators appear healthy.", metrics
    return (
        "informational",
        "Environment output was collected but no known health rows were parsed.",
        {},
    )


def _power_supply_rows(output: str) -> dict[str, dict[str, dict[str, Any]]]:
    supplies: dict[str, dict[str, dict[str, Any]]] = {}
    for line in output.splitlines():
        match = re.match(r"^\s*(\d+)([A-Z])\s+(\S+)\s+(\S+)\s+(.+?)\s{2,}(\S+)\s+(\S+)\s+", line)
        if not match:
            continue
        member, slot, pid, serial, status, system_power, poe_power = match.groups()
        normalized_status = " ".join(status.split())
        healthy = normalized_status.lower() == "ok" and system_power.lower() == "good"
        supplies.setdefault(member, {})[slot] = {
            "pid": pid,
            "serial": serial,
            "status": normalized_status,
            "system_power": system_power,
            "poe_power": poe_power,
            "healthy": healthy,
        }
    return supplies


def _environment_sensor_issues(output: str) -> tuple[list[str], list[str]]:
    critical: list[str] = []
    warning: list[str] = []
    sensor_pattern = re.compile(
        r"^\s*(.+?)\s+(\d+)\s+(GOOD|GREEN|YELLOW|RED|WARNING|CRITICAL|FAULTY)\s+",
        re.IGNORECASE,
    )
    fan_pattern = re.compile(r"^\s*(\d+)\s+(\d+)\s+\d+\s+(\S+)\s+", re.IGNORECASE)
    for line in output.splitlines():
        sensor_match = sensor_pattern.match(line)
        if sensor_match:
            name, location, state = sensor_match.groups()
            if name.upper().startswith("PS"):
                continue
            state = state.upper()
            issue = f"{name.strip()} at location {location} is {state}"
            if state in {"RED", "CRITICAL", "FAULTY"}:
                critical.append(issue)
            elif state in {"YELLOW", "WARNING"}:
                warning.append(issue)
            continue
        fan_match = fan_pattern.match(line)
        if fan_match:
            member, fan, state = fan_match.groups()
            if state.lower() != "ok":
                critical.append(f"switch member {member} fan {fan} is {state}")
            continue
        lowered = line.lower()
        if re.search(r"\b(?:failed|fault|critical|shutdown|not ok)\b", lowered):
            critical.append(line.strip())
        elif re.search(r"\b(?:warning|over temp)\b", lowered):
            warning.append(line.strip())
    return critical, warning


def _switch(output: str, profile: Profile) -> Analysis:
    del profile
    pattern = re.compile(
        r"^\*?\s*(\d+)\s+(\S+)\s+([0-9a-f.]+)\s+(\d+)\s+(\S+)\s+(\S+)",
        re.IGNORECASE,
    )
    members = {}
    for line in output.splitlines():
        match = pattern.match(line.strip())
        if match:
            member, role, mac, priority, version, state = match.groups()
            members[member] = {
                "role": role,
                "mac": mac.lower(),
                "priority": int(priority),
                "version": version,
                "state": state,
            }
    if not members:
        return "unknown", "Switch stack members could not be parsed.", {"members": 0}
    bad = [
        f"member {member}: {data['state']}"
        for member, data in members.items()
        if str(data["state"]).lower() != "ready"
    ]
    if bad:
        return (
            "critical",
            f"Unexpected switch state detected: {', '.join(bad)}.",
            {"members": len(members), "ready": len(members) - len(bad)},
        )
    return (
        "healthy",
        f"All {len(members)} switch member(s) are Ready.",
        {"members": len(members), "ready": len(members)},
    )


def _ospf(output: str, profile: Profile) -> Analysis:
    del profile
    full = len(re.findall(r"\bFULL(?:/|-)", output, re.IGNORECASE))
    other = len(re.findall(r"\b(?:INIT|EXSTART|EXCHANGE|LOADING|DOWN|ATTEMPT)\b", output, re.I))
    if other:
        return (
            "critical",
            f"OSPF has {other} neighbor(s) not in FULL state.",
            {"full": full, "other": other},
        )
    if not full:
        return "warning", "No OSPF neighbors in FULL state were found.", {"full": 0}
    return "healthy", f"OSPF has {full} FULL neighbor(s).", {"full": full}


def _sdwan(output: str, profile: Profile) -> Analysis:
    del profile
    up = len(re.findall(r"(?im)^.*\bup\b.*$", output))
    down = len(re.findall(r"(?im)^.*\bdown\b.*$", output))
    if down:
        return (
            "critical",
            f"SD-WAN has {down} down control connection(s).",
            {"up": up, "down": down},
        )
    if not up:
        return "warning", "No active SD-WAN control connections were parsed.", {"up": 0}
    return "healthy", f"SD-WAN has {up} active control connection(s).", {"up": up}


def _ip_interfaces(output: str, profile: Profile) -> Analysis:
    del profile
    down = len(
        re.findall(r"(?im)^\S+\s+\S+\s+\S+\s+\S+\s+(?:administratively )?down\s+down\s*$", output)
    )
    up = len(re.findall(r"(?im)^\S+\s+\S+\s+\S+\s+\S+\s+up\s+up\s*$", output))
    message = (
        f"Parsed {up} up/up and {down} down interface(s); review expected states in raw output."
    )
    return "informational", message, {"up_up": up, "down": down}


def _connected(output: str, profile: Profile) -> Analysis:
    del profile
    count = len([line for line in output.splitlines() if " connected " in f" {line.lower()} "])
    return "informational", f"Found {count} connected interface(s).", {"connected": count}


def _interface_status(output: str, profile: Profile) -> Analysis:
    del profile
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
    interfaces: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if not parts or parts[0].lower() == "port":
            continue
        status = next((part.lower() for part in parts if part.lower() in status_words), None)
        if status:
            interfaces[parts[0]] = status
    if not interfaces:
        return "unknown", "Interface status rows could not be parsed.", {}
    err_disabled = sorted(name for name, status in interfaces.items() if status == "err-disabled")
    suspended = sorted(name for name, status in interfaces.items() if status == "suspended")
    counts = {
        status: list(interfaces.values()).count(status)
        for status in sorted(set(interfaces.values()))
    }
    metrics: dict[str, Any] = {
        "interface_count": len(interfaces),
        "status_counts": counts,
        "err_disabled": err_disabled,
        "suspended": suspended,
    }
    issues = []
    if err_disabled:
        issues.append(f"err-disabled: {', '.join(err_disabled)}")
    if suspended:
        issues.append(f"suspended: {', '.join(suspended)}")
    if issues:
        return "warning", f"Interface state requires review ({'; '.join(issues)}).", metrics
    return "healthy", f"Parsed {len(interfaces)} interfaces with no fault states.", metrics


def _power_inline(output: str, profile: Profile) -> Analysis:
    del profile
    interfaces: dict[str, str] = {}
    fault_states = {"fault", "faulty", "deny", "denied", "overload", "short", "error"}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 3 or not re.match(r"^(?:Gi|Fa|Te|Tw|Hu|Eth|Fo)\S+$", parts[0], re.I):
            continue
        interfaces[parts[0]] = parts[2].lower()
    if not interfaces:
        return "informational", "No PoE interface rows were parsed; raw output is available.", {}
    faulty = sorted(name for name, state in interfaces.items() if state in fault_states)
    powered = sorted(name for name, state in interfaces.items() if state == "on")
    metrics: dict[str, Any] = {
        "interface_count": len(interfaces),
        "powered_count": len(powered),
        "faulty": faulty,
    }
    if faulty:
        return "warning", f"PoE fault state detected on: {', '.join(faulty)}.", metrics
    return "healthy", f"Parsed {len(interfaces)} PoE interfaces with no fault states.", metrics


def _neighbors(output: str, profile: Profile) -> Analysis:
    del profile
    if re.search(r"(?im)^%\s*(?:CDP|LLDP) is not enabled", output):
        protocol = "LLDP" if "lldp" in output.lower() else "CDP"
        return "informational", f"{protocol} is not enabled on this device.", {"neighbors": 0}
    total_match = re.search(r"Total entries displayed\s*:\s*(\d+)", output, re.I)
    if total_match:
        count = int(total_match.group(1))
    else:
        lines = [line for line in output.splitlines() if line.strip()]
        count = max(0, len(lines) - 2)
    return (
        "informational",
        f"Parsed approximately {count} neighbor entry/entries.",
        {"neighbors": count},
    )


def _routes(output: str, profile: Profile) -> Analysis:
    del profile
    routes = len(re.findall(r"(?im)^\s*[A-Z][A-Z*+ ]*\s+\d{1,3}(?:\.\d{1,3}){3}", output))
    return (
        "informational",
        f"Parsed {routes} route entry/entries; no expected-route policy is configured.",
        {"routes": routes},
    )
