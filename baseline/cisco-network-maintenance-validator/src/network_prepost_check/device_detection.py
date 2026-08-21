from __future__ import annotations

SUPPORTED_DEVICE_TYPES = {"switch", "edge_router"}


def resolve_device_type(hostname: str, requested_device_type: str | None) -> str:
    if requested_device_type and requested_device_type != "auto":
        normalized = requested_device_type.strip().lower()
        if normalized not in SUPPORTED_DEVICE_TYPES:
            raise ValueError(f"Unsupported device type: {requested_device_type}")
        return normalized

    normalized_hostname = hostname.upper()
    if "SW0" in normalized_hostname:
        return "switch"
    if "EDG0" in normalized_hostname:
        return "edge_router"

    raise ValueError(
        "Device type could not be detected from hostname. Use --device-type switch "
        "or --device-type edge_router."
    )


def default_config_name(device_type: str) -> str:
    if device_type == "switch":
        return "switch_commands.json"
    if device_type == "edge_router":
        return "edge_router_commands.json"
    raise ValueError(f"Unsupported device type: {device_type}")
