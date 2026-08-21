"""Configuration loading for the standalone auditor."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Credentials:
    """Credentials used for Catalyst Center and optional switch validation."""

    base_url: str
    username: str
    password: str
    ssh_username: str = ""
    ssh_password: str = ""
    ssh_secret: str = ""
    ssh_device_type: str = "cisco_xe"


def load_credentials(path: Path | None = None) -> Credentials:
    """Load key/value credentials from a local file, with environment overrides."""
    values: dict[str, str] = {}
    if path:
        for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"Invalid credentials entry on line {number}")
            key, value = line.split("=", 1)
            values[key.strip().lower()] = value.strip()

    def setting(name: str) -> str:
        return os.getenv(name.upper(), values.get(name.lower(), "")).strip()

    credentials = Credentials(
        base_url=setting("catalyst_centre_base_url").rstrip("/"),
        username=setting("catalyst_centre_username"),
        password=setting("catalyst_centre_password"),
        ssh_username=setting("network_device_username"),
        ssh_password=setting("network_device_password"),
        ssh_secret=setting("network_device_secret"),
        ssh_device_type=setting("ssh_device_type") or "cisco_xe",
    )
    missing = [
        name
        for name, value in (
            ("CATALYST_CENTRE_BASE_URL", credentials.base_url),
            ("CATALYST_CENTRE_USERNAME", credentials.username),
            ("CATALYST_CENTRE_PASSWORD", credentials.password),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required setting(s): {', '.join(missing)}")
    return credentials
