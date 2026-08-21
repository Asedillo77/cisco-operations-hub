"""Read-only switch CLI inventory used to validate Catalyst Center evidence."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

LOGGER = logging.getLogger(__name__)
EXCLUDED_PORT_PREFIXES = (
    "ap", "be", "bluetooth", "cell", "lo", "mgmt", "nu", "po", "port-channel", "tun", "vl"
)


@dataclass(slots=True)
class CliPortInventory:
    """Physical ports observed directly on a switch."""

    host: str
    ports: set[str]
    ready_switches: set[str] | None


def compact_interface_name(interface_name: str) -> str:
    """Normalize long and short Cisco interface names for correlation."""
    compact = re.sub(r"\s+", "", interface_name).lower()
    replacements = {
        "twentyfivegigabitethernet": "tw",
        "fortygigabitethernet": "fo",
        "tengigabitethernet": "te",
        "twogigabitethernet": "tw",
        "gigabitethernet": "gi",
        "fastethernet": "fa",
        "ethernet": "eth",
    }
    for long_name, short_name in replacements.items():
        compact = compact.replace(long_name, short_name)
    return compact


def _interface_number_parts(interface_name: str) -> list[str]:
    compact = compact_interface_name(interface_name)
    match = re.match(r"^[a-z-]+(\d+(?:/\d+)+)$", compact)
    return match.group(1).split("/") if match else []


def reportable_switchport(interface_name: str, ready_switches: set[str] | None = None) -> bool:
    """Return whether an interface is a physical x/0/x switchport in scope."""
    compact = compact_interface_name(interface_name)
    if not compact or compact.startswith(EXCLUDED_PORT_PREFIXES):
        return False
    parts = _interface_number_parts(compact)
    if (
        len(parts) != 3
        or parts[1] != "0"
        or (ready_switches is not None and parts[0] not in ready_switches)
    ):
        return False
    return re.match(r"^(gi|te|tw|fo|fa|eth)\d+/\d+/\d+$", compact) is not None


def parse_show_interfaces_status_ports(output: str) -> set[str]:
    """Parse physical port names from show interfaces status."""
    ports: set[str] = set()
    for line in output.splitlines():
        values = line.strip().split(maxsplit=1)
        if values and reportable_switchport(values[0]):
            ports.add(compact_interface_name(values[0]))
    return ports


def parse_ready_switch_members(output: str) -> set[str] | None:
    """Parse Ready stack members from show switch, if the command is supported."""
    members: set[str] = set()
    saw_switch_table = False
    for line in output.splitlines():
        if re.match(r"^\s*\*?\d+\s+", line):
            saw_switch_table = True
            parts = line.split()
            if parts[-1].lower() == "ready":
                members.add(parts[0].lstrip("*"))
    return members if saw_switch_table else None


def collect_cli_port_inventory(
    host: str,
    *,
    username: str,
    password: str,
    secret: str = "",
    device_type: str = "cisco_xe",
) -> CliPortInventory:
    """Run the preserved read-only CLI commands and return normalized ports."""
    connection = {
        "device_type": device_type,
        "host": host,
        "username": username,
        "password": password,
        "secret": secret or password,
        "fast_cli": False,
    }
    try:
        with ConnectHandler(**connection) as net_connect:
            if connection["secret"]:
                try:
                    net_connect.enable()
                except Exception:
                    LOGGER.debug("Enable mode failed or was not required for %s", host)
            status_output = net_connect.send_command("show interfaces status", read_timeout=60)
            try:
                switch_output = net_connect.send_command("show switch", read_timeout=60)
            except Exception:
                switch_output = ""
                LOGGER.debug("show switch failed or is unsupported on %s", host)
    except (NetmikoAuthenticationException, NetmikoTimeoutException):
        raise
    except Exception as exc:
        raise RuntimeError(f"CLI collection failed for {host}: {exc}") from exc

    if not str(status_output).strip():
        raise ValueError(f"Switch {host} returned no show interfaces status output.")
    ready_switches = parse_ready_switch_members(switch_output)
    raw_ports = parse_show_interfaces_status_ports(status_output)
    ports = (
        raw_ports
        if ready_switches is None
        else {port for port in raw_ports if reportable_switchport(port, ready_switches)}
    )
    LOGGER.info("CLI validation for %s collected %d reportable port(s)", host, len(ports))
    return CliPortInventory(host=host, ports=ports, ready_switches=ready_switches)
