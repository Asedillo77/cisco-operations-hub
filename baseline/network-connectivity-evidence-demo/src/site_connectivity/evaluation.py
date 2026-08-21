"""Translate technical command output into service-desk guidance."""

from __future__ import annotations

import re

from .models import CommandResult, DeviceResult, DeviceTarget, PingResult, Status
from .profiles import CommandCheck
from .thresholds import SIGNAL_ASSESSORS

SIGNAL_PATTERNS = {
    "rssi_dbm": re.compile(r"RSSI\s*(?:=|:)\s*(-?\d+)", re.IGNORECASE),
    "rsrp_dbm": re.compile(r"RSRP\s*(?:=|:)\s*(-?\d+)", re.IGNORECASE),
    "rsrq_db": re.compile(r"RSRQ\s*(?:=|:)\s*(-?\d+)", re.IGNORECASE),
    "sinr_db": re.compile(r"(?:SINR|SNR)\s*(?:=|:)\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE),
}
INTERFACE_LINE = re.compile(
    r"^(?P<interface>\S+)\s+(?P<ip>\S+)\s+(?:YES|NO)\s+\S+\s+"
    r"(?P<status>administratively down|up|down)\s+(?P<protocol>up|down)\s*$",
    re.IGNORECASE,
)
NETWORK_FIELDS = {
    "provider": re.compile(r"^Network\s*=\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    "mcc": re.compile(r"Mobile Country Code \(MCC\)\s*=\s*(\d+)", re.IGNORECASE),
    "mnc": re.compile(r"Mobile Network Code \(MNC\)\s*=\s*(\d+)", re.IGNORECASE),
    "registration": re.compile(r"Registration state\(EMM\)\s*=\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    "packet_state": re.compile(r"Packet switch domain\(PS\) state\s*=\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    "service_status": re.compile(r"Current Service Status\s*=\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    "system_mode": re.compile(r"System Mode\s*=\s*(.+)$", re.IGNORECASE | re.MULTILINE),
}
DEFAULT_PREFIX = "0.0.0.0/0"
VIA_PATH = re.compile(r"\bvia\s+(?P<next_hop>\d{1,3}(?:\.\d{1,3}){3})(?:,\s*(?P<interface>\S+))?", re.IGNORECASE)
DIRECT_PATH = re.compile(r"directly connected,\s*(?P<interface>\S+)", re.IGNORECASE)
LAST_RESORT = re.compile(r"Gateway of last resort is\s+(?P<next_hop>\d{1,3}(?:\.\d{1,3}){3})", re.IGNORECASE)
DESCRIPTION_LINE = re.compile(
    r"^(?P<interface>\S+)\s+(?P<status>admin down|up|down)\s+(?P<protocol>up|down)\s*(?P<description>.*)$",
    re.IGNORECASE,
)
TUNNEL_INTERFACE = re.compile(r"^interface\s+(?P<interface>Tunnel\d+)", re.IGNORECASE)


def _metric(output: str, name: str) -> float | None:
    match = SIGNAL_PATTERNS[name].search(output)
    return float(match.group(1)) if match else None


def evaluate_cellular_radio(check: CommandCheck, output: str) -> CommandResult:
    """Interpret common Cisco cellular radio measurements conservatively."""
    evidence = {name: value for name in SIGNAL_PATTERNS if (value := _metric(output, name)) is not None}
    if not evidence:
        return CommandResult(
            check.check_id,
            check.command,
            Status.UNKNOWN,
            "Cellular radio output was collected but recognised signal measurements were not found.",
            "The output format may differ for this router model or software release.",
            "Ask the network team to review the raw output and confirm the applicable parser.",
            output,
        )
    assessments = {name: SIGNAL_ASSESSORS[name](value) for name, value in evidence.items()}
    evidence["assessments"] = {
        name: {
            "rating": assessment.rating,
            "status": assessment.status,
            "explanation": assessment.explanation,
        }
        for name, assessment in assessments.items()
    }
    primary_names = [name for name in ("rsrp_dbm", "rsrq_db", "sinr_db") if name in assessments]
    primary_assessments = [assessments[name] for name in primary_names]
    if not primary_assessments and "rssi_dbm" in assessments:
        primary_assessments = [assessments["rssi_dbm"]]
    degraded = any(assessment.status == Status.DEGRADED for assessment in primary_assessments)
    status = Status.DEGRADED if degraded else Status.HEALTHY
    rating_summary = ", ".join(
        f"{name.removesuffix('_dbm').removesuffix('_db').upper()}: {assessment.rating}"
        for name, assessment in assessments.items()
    )
    summary = f"Cellular radio assessment — {rating_summary}."
    explanation = (
        "One or more primary LTE measurements indicate marginal signal or interference that may contribute to "
        "slowness, packet loss, or unstable tunnels."
        if degraded
        else "The primary LTE measurements are good; reachability and tunnel results are still considered."
    )
    action = (
        "Check user impact, antenna connections and placement, and whether performance changes by time of day."
        if degraded
        else "No radio-specific action is indicated unless latency, loss, or tunnel checks show a problem."
    )
    return CommandResult(check.check_id, check.command, status, summary, explanation, action, output, evidence)


def _short_interface(name: str) -> str:
    shortened = re.sub(r"^GigabitEthernet", "Gi", name, flags=re.IGNORECASE)
    return re.sub(r"^TenGigabitEthernet", "Te", shortened, flags=re.IGNORECASE)


def evaluate_interfaces(check: CommandCheck, output: str, target: DeviceTarget) -> CommandResult:
    """Interpret WAN interface state according to the site's expected design."""
    interfaces: dict[str, dict[str, str | bool]] = {}
    for line in output.splitlines():
        if match := INTERFACE_LINE.match(line.strip()):
            name = _short_interface(match.group("interface"))
            ip_address = match.group("ip")
            interfaces[name] = {
                "ip": ip_address,
                "status": match.group("status").casefold(),
                "protocol": match.group("protocol").casefold(),
                "active": ip_address.casefold() != "unassigned" and match.group("protocol").casefold() == "up",
            }
    if not interfaces:
        return CommandResult(
            check.check_id,
            check.command,
            Status.UNKNOWN,
            "Interface output was collected but could not be interpreted.",
            "The device output did not match the expected Cisco interface table format.",
            "Ask the network team to review the raw output and platform type.",
            output,
        )

    fixed_names = [name for name in interfaces if name == "Gi0/0/0" or name.startswith("Gi0/0/0.")]
    fixed_link_up = any(
        interfaces[name]["status"] == "up" and interfaces[name]["protocol"] == "up" for name in fixed_names
    )
    fixed_active = fixed_link_up or any(bool(interfaces[name]["active"]) for name in fixed_names)
    cellular_names = [name for name in interfaces if name.casefold() == "cellular0/2/0"]
    cellular_up = [name for name in cellular_names if interfaces[name]["protocol"] == "up"]
    cellular_active = [name for name in cellular_names if bool(interfaces[name]["active"])]
    assigned_protocol_down = [
        name for name, state in interfaces.items() if state["ip"] != "unassigned" and state["protocol"] == "down"
    ]
    evidence = {
        "interfaces": interfaces,
        "fixed_wan_link_up": fixed_link_up,
        "fixed_wan_active": fixed_active,
        "cellular_up_interfaces": cellular_up,
        "cellular_active_interfaces": cellular_active,
        "cellular_interfaces": {name: interfaces[name] for name in cellular_names},
        "assigned_protocol_down": assigned_protocol_down,
        "observed_transport": "fixed" if fixed_active else ("cellular" if cellular_active else "none"),
    }
    site_type = target.site_type.casefold()
    if site_type == "dmt":
        status = Status.HEALTHY if cellular_active else Status.DOWN
        summary = (
            "The DMT is using its expected cellular WAN connection."
            if cellular_active
            else "The DMT does not have an active cellular WAN address."
        )
        action = (
            "No transport action is indicated."
            if cellular_active
            else "Check cellular registration, SIM, and radio state."
        )
    elif site_type == "dmu":
        if fixed_active and not cellular_active:
            status = Status.HEALTHY
            summary = "The DMU appears to be using Starlink; the cellular interface is expected to be inactive."
            action = "No cellular action is indicated while Starlink and reachability remain healthy."
            evidence["observed_transport"] = "starlink"
        elif cellular_active and not fixed_active:
            status = Status.HEALTHY
            summary = "The DMU appears to be using its cellular WAN connection."
            action = "Confirm cellular signal and provider results below."
        elif fixed_active and cellular_active:
            status = Status.DEGRADED
            summary = "Both Starlink-facing and cellular WAN evidence appear active."
            action = "Confirm the intended primary path and whether a failover or transition is in progress."
        else:
            status = Status.DOWN
            summary = "No active DMU WAN transport was identified."
            action = "Check Starlink handoff, cellular registration, site power, and cabling."
    elif site_type in {"datacentre", "donor_centre", "warehouse"}:
        if fixed_active:
            status = Status.HEALTHY
            summary = "The fixed/NBN WAN is active; cellular is treated as standby even if its line protocol is up."
            action = "No failover action is indicated unless reachability or SD-WAN checks are degraded."
        elif cellular_up:
            status = Status.DEGRADED
            summary = "The fixed/NBN WAN is unavailable and the site appears to be using cellular backup."
            action = "Check for an NBN or carrier outage and confirm that service is stable on cellular failover."
            evidence["observed_transport"] = "cellular_failover"
        else:
            status = Status.DOWN
            summary = "Neither the fixed/NBN WAN nor cellular backup appears active."
            action = "Check site power, NBN handoff, cellular registration, and physical connectivity."
    elif site_type == "processing_centre":
        addressed_non_tunnel_down = [
            name for name in assigned_protocol_down if not name.casefold().startswith("tunnel")
        ]
        evidence["addressed_non_tunnel_down"] = addressed_non_tunnel_down
        if fixed_active and addressed_non_tunnel_down:
            status = Status.DEGRADED
            summary = "The ISP-facing WAN is active, but one or more addressed interfaces or tunnels are down."
            action = "Correlate this edge router with its peer and identify the affected ISP or SD-WAN path."
        elif fixed_active:
            status = Status.HEALTHY
            summary = "The processing-centre ISP-facing WAN is active."
            action = "Review both edge routers to confirm site redundancy."
        else:
            status = Status.DOWN
            summary = "The processing-centre ISP-facing WAN is not active on this edge router."
            action = "Correlate both edge routers and ISP paths."
    else:
        status = Status.UNKNOWN
        summary = "Interface state was parsed, but no site transport policy is assigned."
        action = "Assign a site_type in inventory so expected WAN behaviour can be evaluated."
    return CommandResult(
        check.check_id,
        check.command,
        status,
        summary,
        "The conclusion uses assigned IP addresses and line protocol, not interface state alone.",
        action,
        output,
        evidence,
    )


def _transport_type(description: str) -> str:
    value = description.casefold()
    if "cellular" in value:
        return "cellular"
    if "starlink" in value:
        return "starlink"
    if "tc4" in value:
        return "tc4"
    if "tloc" in value or "tunnel internet" in value:
        return "tloc_extension"
    if "internet" in value or "vpn 0" in value:
        return "fixed_internet"
    return "unknown"


def evaluate_transport_descriptions(check: CommandCheck, output: str) -> CommandResult:
    """Identify physical transport purpose from operational interface descriptions."""
    descriptions: dict[str, dict[str, str]] = {}
    for raw_line in output.splitlines():
        if match := DESCRIPTION_LINE.match(raw_line.strip()):
            name = _short_interface(match.group("interface"))
            description = match.group("description").strip()
            descriptions[name] = {
                "status": match.group("status").casefold(),
                "protocol": match.group("protocol").casefold(),
                "description": description,
                "transport_type": _transport_type(description),
            }
    recognised = {name: data for name, data in descriptions.items() if data["transport_type"] != "unknown"}
    if not descriptions:
        return CommandResult(
            check.check_id,
            check.command,
            Status.UNKNOWN,
            "Interface descriptions could not be interpreted.",
            "Transport labels are unavailable, so tunnel sources cannot be named reliably.",
            "Review command support and the raw output.",
            output,
        )
    return CommandResult(
        check.check_id,
        check.command,
        Status.INFORMATIONAL,
        f"Collected interface descriptions; {len(recognised)} transport interface(s) were recognised.",
        "Descriptions label physical transports without assuming a fixed port number.",
        "Review unrecognised descriptions when a transport cannot be classified.",
        output,
        {"descriptions": descriptions, "recognised_transports": recognised},
    )


def evaluate_tunnel_topology(check: CommandCheck, output: str) -> CommandResult:
    """Map tunnel interfaces to their sources and distinguish service VPN from SIG."""
    tunnels: dict[str, dict[str, object]] = {}
    current: dict[str, object] | None = None
    for raw_line in output.splitlines():
        stripped = raw_line.strip()
        if match := TUNNEL_INTERFACE.match(stripped):
            name = match.group("interface")
            current = {"interface": name, "source": None, "destination": None, "vrf_multiplexing": False}
            tunnels[name] = current
        elif current is not None and stripped.startswith("tunnel source "):
            current["source"] = _short_interface(stripped.removeprefix("tunnel source ").strip())
        elif current is not None and stripped.startswith("tunnel destination "):
            current["destination"] = stripped.removeprefix("tunnel destination ").strip()
        elif current is not None and stripped == "tunnel vrf multiplexing":
            current["vrf_multiplexing"] = True
    for tunnel in tunnels.values():
        tunnel["role"] = "web_gateway" if tunnel["destination"] and tunnel["vrf_multiplexing"] else "service_vpn"
    if not tunnels:
        return CommandResult(
            check.check_id,
            check.command,
            Status.UNKNOWN,
            "Tunnel topology could not be interpreted.",
            "Service VPN and router-based SIG tunnel roles cannot be separated safely.",
            "Review command support and the raw output.",
            output,
        )
    service_count = sum(tunnel["role"] == "service_vpn" for tunnel in tunnels.values())
    sig_count = sum(tunnel["role"] == "web_gateway" for tunnel in tunnels.values())
    return CommandResult(
        check.check_id,
        check.command,
        Status.INFORMATIONAL,
        f"Mapped {service_count} service VPN tunnel(s) and {sig_count} router-based SIG tunnel(s).",
        "Tunnel roles are derived from source, destination, and VRF-multiplexing configuration.",
        "Use the service-plane assessment rather than tunnel numbers alone.",
        output,
        {"tunnels": tunnels, "service_tunnel_count": service_count, "sig_tunnel_count": sig_count},
    )


def evaluate_cellular_network(check: CommandCheck, output: str) -> CommandResult:
    """Extract registration and carrier details for one cellular interface."""
    evidence: dict[str, str] = {}
    for name, pattern in NETWORK_FIELDS.items():
        if match := pattern.search(output):
            evidence[name] = match.group(1).strip()
    if not evidence:
        return CommandResult(
            check.check_id,
            check.command,
            Status.UNKNOWN,
            "No recognised cellular registration information was returned.",
            "The interface may be standby, unsupported, or unavailable.",
            "Correlate this result with the active transport identified from interface state.",
            output,
        )
    provider = evidence.get("provider", "Unknown provider")
    registered = evidence.get("registration", "").casefold() == "registered"
    attached = evidence.get("packet_state", "").casefold() == "attached"
    provider_key = provider.casefold()
    mnc = evidence.get("mnc", "").lstrip("0")
    if "telstra" in provider_key or (evidence.get("mcc") == "505" and mnc == "1"):
        provider_family = "Telstra"
    elif "optus" in provider_key or (evidence.get("mcc") == "505" and mnc == "2"):
        provider_family = "Optus"
    else:
        provider_family = "Unrecognised"
    evidence["provider_family"] = provider_family
    status = Status.HEALTHY if registered and attached and provider_family != "Unrecognised" else Status.DEGRADED
    if registered and attached:
        summary = f"The modem is registered and attached to {provider}."
    else:
        summary = f"The modem is not fully registered and attached; reported network is {provider}."
    if provider_family == "Unrecognised":
        summary += " The carrier does not match the currently recognised Telstra or Optus services."
    return CommandResult(
        check.check_id,
        check.command,
        status,
        summary,
        "The single Cellular0/2/0 modem can register through the Telstra or Optus SIM service.",
        "Verify the SIM/provider assignment if the reported carrier is unexpected.",
        output,
        evidence,
    )


def evaluate_uptime(check: CommandCheck, output: str, target: DeviceTarget) -> CommandResult:
    """Present uptime as context rather than a health verdict."""
    uptime_text = next((line.strip() for line in output.splitlines() if line.strip()), "Uptime was not returned.")
    mobile_site = target.site_type.casefold() in {"dmu", "dmt"}
    explanation = (
        "Short uptime can be normal for DMU and DMT equipment because the vehicle or portable kit may be powered off "
        "between operations."
        if mobile_site
        else "Uptime is informational and may help identify a recent restart at a fixed physical site."
    )
    return CommandResult(
        check.check_id,
        check.command,
        Status.INFORMATIONAL,
        uptime_text,
        explanation,
        "Use uptime as supporting context; do not treat it alone as proof of a fault.",
        output,
        {"uptime_text": uptime_text, "mobile_site": mobile_site},
    )


def evaluate_default_route(check: CommandCheck, output: str, target: DeviceTarget) -> CommandResult:
    """Identify the active default path or possible equal-cost/load-balanced paths."""
    paths: list[dict[str, str | None]] = []
    in_default_block = False
    for raw_line in output.splitlines():
        stripped = raw_line.strip()
        if DEFAULT_PREFIX in stripped:
            in_default_block = True
            route_text = stripped
        elif in_default_block and re.match(r"^\[\d+/\d+\]\s+via\s+", stripped):
            route_text = stripped
        else:
            if stripped and not raw_line[:1].isspace():
                in_default_block = False
            continue
        for match in VIA_PATH.finditer(route_text):
            paths.append({"next_hop": match.group("next_hop"), "interface": match.group("interface")})
        if match := DIRECT_PATH.search(route_text):
            paths.append({"next_hop": None, "interface": match.group("interface")})

    if not paths and (match := LAST_RESORT.search(output)):
        paths.append({"next_hop": match.group("next_hop"), "interface": None})
    unique_paths = list({(path["next_hop"], path["interface"]): path for path in paths}.values())
    next_hops = [str(path["next_hop"]) for path in unique_paths if path["next_hop"]]
    interfaces = [str(path["interface"]) for path in unique_paths if path["interface"]]
    uses_cellular = any(interface.casefold() == "cellular0/2/0" for interface in interfaces)
    load_balanced = len(unique_paths) > 1
    dual_edge = target.edge_role in {"primary", "secondary"}
    evidence = {
        "default_paths": unique_paths,
        "default_next_hops": next_hops,
        "default_interfaces": interfaces,
        "path_count": len(unique_paths),
        "load_balanced": load_balanced,
        "uses_cellular": uses_cellular,
        "dual_edge": dual_edge,
    }
    if not unique_paths:
        return CommandResult(
            check.check_id,
            check.command,
            Status.DEGRADED,
            "No IPv4 default route was identified.",
            "Without a usable default route, internet or upstream connectivity may be unavailable.",
            "Check the WAN handoff, addressing, and intended default-route configuration.",
            output,
            evidence,
        )
    path_description = ", ".join(str(path["interface"] or path["next_hop"] or "unknown path") for path in unique_paths)
    backup_site = target.site_type.casefold() in {"donor_centre", "warehouse"} or (
        target.transport.casefold() == "fixed_cellular_backup"
    )
    if dual_edge and len(unique_paths) == 2:
        status = Status.HEALTHY
        summary = f"Two default paths are installed for the dual-edge design ({path_description})."
        explanation = (
            "The device is marked as part of a dual-edge pair, where local and peer/TLOC default paths provide "
            "the expected path resilience."
        )
        action = "No routing action is indicated while both expected paths remain usable."
    elif dual_edge and len(unique_paths) == 1:
        status = Status.DEGRADED
        summary = f"Only one default path is installed on a dual-edge device ({path_description})."
        explanation = "Basic routing remains available, but the expected peer/TLOC path resilience is reduced."
        action = "Check the peer edge and TLOC-extension path before a second failure affects service."
    elif load_balanced:
        status = Status.DEGRADED
        summary = f"Multiple default paths are installed ({path_description})."
        explanation = (
            "Single-edge network designs expect one active IPv4 default route, even when multiple uplinks or backup "
            "services are available. Concurrent defaults may cause unintended load sharing or path selection."
        )
        action = "Confirm the intended primary path and remove or de-preference any unintended active default route."
    elif uses_cellular and backup_site:
        status = Status.DEGRADED
        summary = "The installed default route uses Cellular0/2/0."
        explanation = "The site appears to be routing through cellular instead of its expected fixed-primary service."
        action = "Check the fixed/NBN service and confirm whether cellular failover is expected."
    else:
        status = Status.HEALTHY
        summary = f"A usable IPv4 default path is installed through {path_description}."
        explanation = (
            "The routing table contains an upstream path for destinations outside directly connected networks."
        )
        action = "No default-route action is indicated unless the installed path differs from the site design."
    return CommandResult(
        check.check_id,
        check.command,
        status,
        summary,
        explanation,
        action,
        output,
        evidence,
    )


def evaluate_command(check: CommandCheck, output: str, target: DeviceTarget) -> CommandResult:
    """Evaluate a command using a specific parser where available."""
    if check.check_id == "device_uptime":
        return evaluate_uptime(check, output, target)
    if check.check_id == "interface_state":
        return evaluate_interfaces(check, output, target)
    if check.check_id == "default_route":
        return evaluate_default_route(check, output, target)
    if check.check_id == "transport_descriptions":
        return evaluate_transport_descriptions(check, output)
    if check.check_id == "tunnel_topology":
        return evaluate_tunnel_topology(check, output)
    if check.check_id == "cellular_radio":
        return evaluate_cellular_radio(check, output)
    if check.check_id == "cellular_network":
        return evaluate_cellular_network(check, output)
    if not output.strip():
        return CommandResult(
            check.check_id,
            check.command,
            Status.UNKNOWN,
            f"No output was returned for {check.label.lower()}.",
            "The command may be unsupported, timed out, or returned no matching information.",
            "Ask the network team to review the command support and raw session log.",
            output,
        )
    return CommandResult(
        check.check_id,
        check.command,
        Status.UNKNOWN,
        f"{check.label} evidence was collected for technical review.",
        "Automated interpretation for this command will be added after its expected outputs are confirmed.",
        "Use the raw evidence below when escalating to the network team.",
        output,
    )


def combine_device_status(ping: PingResult, ssh_status: Status, checks: list[CommandResult]) -> tuple[Status, str]:
    """Correlate reachability, SSH, and command evidence without overstating certainty."""
    check_states = {check.status for check in checks}
    if ping.status == Status.DOWN and ssh_status != Status.HEALTHY:
        return (
            Status.DOWN,
            "The device did not respond to ping and SSH could not be established. The site appears unavailable; "
            "possible causes include loss of site power, local router equipment, or the provider circuit.",
        )
    if Status.DOWN in check_states:
        return Status.DOWN, "The device is reachable, but a critical connectivity check is down."
    if ping.status == Status.DEGRADED or Status.DEGRADED in check_states:
        return Status.DEGRADED, "The device is reachable, but one or more checks indicate degraded connectivity."
    if ssh_status == Status.HEALTHY and ping.status == Status.HEALTHY:
        return Status.HEALTHY, "The device is reachable and SSH collection completed successfully."
    return Status.UNKNOWN, "Some evidence was collected, but there is not enough information for a firm conclusion."


def finalise_device(result: DeviceResult) -> DeviceResult:
    """Update the overall device conclusion from its collected evidence."""
    interface_check = next((check for check in result.checks if check.check_id == "interface_state"), None)
    if interface_check:
        active_interfaces = interface_check.evidence.get("cellular_active_interfaces", [])
        if not active_interfaces and interface_check.evidence.get("observed_transport") == "cellular_failover":
            active_interfaces = interface_check.evidence.get("cellular_up_interfaces", [])
        providers: list[str] = []
        for _interface_name in active_interfaces:
            network_check = next((check for check in result.checks if check.check_id == "cellular_network"), None)
            if network_check and network_check.evidence.get("provider"):
                providers.append(str(network_check.evidence["provider"]))
        interface_check.evidence["active_cellular_providers"] = providers
        if providers:
            interface_check.summary += f" Active cellular provider: {', '.join(providers)}."
        elif active_interfaces:
            interface_check.status = Status.DEGRADED
            interface_check.summary += " The active cellular provider could not be confirmed."
            interface_check.recommended_action = (
                "Confirm cellular registration and whether the modem is using Telstra or Optus before escalation."
            )
    service_plane_check = _evaluate_service_planes(result)
    if service_plane_check is not None:
        result.checks.append(service_plane_check)
    result.status, result.summary = combine_device_status(result.ping, result.ssh_status, result.checks)
    return result


def _evaluate_service_planes(result: DeviceResult) -> CommandResult | None:
    interface_check = next((check for check in result.checks if check.check_id == "interface_state"), None)
    route_check = next((check for check in result.checks if check.check_id == "default_route"), None)
    description_check = next((check for check in result.checks if check.check_id == "transport_descriptions"), None)
    topology_check = next((check for check in result.checks if check.check_id == "tunnel_topology"), None)
    if not interface_check or not route_check or not topology_check:
        return None

    interfaces = interface_check.evidence.get("interfaces", {})
    descriptions = description_check.evidence.get("descriptions", {}) if description_check else {}
    tunnels = topology_check.evidence.get("tunnels", {})
    enriched: list[dict[str, object]] = []
    for tunnel in tunnels.values():
        item = dict(tunnel)
        state = interfaces.get(_short_interface(str(item["interface"])), {})
        source = str(item.get("source") or "")
        source_description = descriptions.get(source, {})
        item["status"] = state.get("status")
        item["protocol"] = state.get("protocol")
        item["ip"] = state.get("ip")
        item["active"] = state.get("protocol") == "up" and state.get("ip") not in {None, "unassigned"}
        item["source_description"] = source_description.get("description", "")
        item["source_transport"] = source_description.get("transport_type", "unknown")
        enriched.append(item)

    planes: list[dict[str, str]] = []
    route_count = int(route_check.evidence.get("path_count", 0))
    dual_edge = result.target.edge_role in {"primary", "secondary"}
    if route_count == 1 and not dual_edge:
        planes.append(
            {"name": "DIA", "status": Status.HEALTHY.value, "summary": "One active IPv4 default path is installed."}
        )
    elif route_count == 2 and dual_edge:
        planes.append(
            {
                "name": "DIA",
                "status": Status.HEALTHY.value,
                "summary": "Two default paths are installed for the expected dual-edge design.",
            }
        )
    elif route_count == 1 and dual_edge:
        planes.append(
            {
                "name": "DIA",
                "status": Status.DEGRADED.value,
                "summary": "Only one default path remains on a dual-edge device; path resilience is reduced.",
            }
        )
    elif route_count > 1:
        planes.append(
            {
                "name": "DIA",
                "status": Status.DEGRADED.value,
                "summary": "Multiple active IPv4 default paths are installed; unintended load sharing is possible.",
            }
        )
    else:
        planes.append(
            {"name": "DIA", "status": Status.DOWN.value, "summary": "No active IPv4 default path was identified."}
        )

    service_tunnels = [tunnel for tunnel in enriched if tunnel["role"] == "service_vpn"]
    active_service = [tunnel for tunnel in service_tunnels if tunnel["active"]]
    if active_service:
        sources = sorted({str(tunnel["source_transport"]).replace("_", " ") for tunnel in active_service})
        planes.append(
            {
                "name": "Corporate Service VPN",
                "status": Status.HEALTHY.value,
                "summary": f"{len(active_service)} service tunnel(s) are active via {', '.join(sources)}.",
            }
        )
    else:
        planes.append(
            {
                "name": "Corporate Service VPN",
                "status": Status.DOWN.value,
                "summary": "No active service VPN tunnel was identified; corporate traffic may be affected.",
            }
        )

    sig_tunnels = [tunnel for tunnel in enriched if tunnel["role"] == "web_gateway"]
    active_sig = [tunnel for tunnel in sig_tunnels if tunnel["active"]]
    if len(active_sig) >= 2:
        sig_status = Status.HEALTHY
        sig_summary = f"{len(active_sig)} router-based Netskope SIG tunnels are active."
    elif len(active_sig) == 1:
        sig_status = Status.DEGRADED
        sig_summary = "Only one router-based Netskope SIG tunnel is active; resilience is reduced."
    elif sig_tunnels:
        sig_status = Status.DOWN
        sig_summary = "No router-based Netskope SIG tunnel is active; selected non-client traffic may be affected."
    else:
        sig_status = Status.UNKNOWN
        sig_summary = "No router-based Netskope SIG tunnel configuration was identified."
    planes.append({"name": "Netskope SIG", "status": sig_status.value, "summary": sig_summary})

    configured_transports = {
        str(tunnel["source_transport"]) for tunnel in enriched if tunnel["source_transport"] != "unknown"
    }
    active_transports = {
        str(tunnel["source_transport"]) for tunnel in active_service if tunnel["source_transport"] != "unknown"
    }
    standby = configured_transports - active_transports
    if standby:
        planes.append(
            {
                "name": "Backup and Failover",
                "status": Status.INFORMATIONAL.value,
                "summary": (
                    "Configured standby transport(s): "
                    f"{', '.join(sorted(value.replace('_', ' ') for value in standby))}."
                ),
            }
        )

    severity = {Status.DOWN.value: 3, Status.DEGRADED.value: 2, Status.UNKNOWN.value: 1}
    worst = max(planes, key=lambda plane: severity.get(plane["status"], 0))
    overall_status = Status(worst["status"]) if worst["status"] in severity else Status.HEALTHY
    actionable = [plane["summary"] for plane in planes if plane["status"] in {Status.DOWN.value, Status.DEGRADED.value}]
    summary = (
        " ".join(actionable)
        if actionable
        else "DIA, corporate service VPN, and router-based SIG evidence look available."
    )
    return CommandResult(
        "service_plane_health",
        "Correlated service-plane assessment",
        overall_status,
        summary,
        "DIA, corporate service VPN, and router-based Netskope SIG are assessed separately to describe likely impact.",
        "Investigate only the affected service plane. If router evidence is healthy, check the endpoint Netskope "
        "client, authentication, policy, and platform status.",
        evidence={
            "planes": planes,
            "tunnels": enriched,
            "edge_role": result.target.edge_role,
            "service_vrfs": list(result.target.service_vrfs),
            "vrf_routing_verified": False,
        },
    )
