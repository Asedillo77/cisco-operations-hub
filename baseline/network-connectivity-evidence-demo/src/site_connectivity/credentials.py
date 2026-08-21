"""Local credential-file loading for non-production standalone testing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class Credentials:
    """Device credentials kept in memory for one run."""

    username: str
    password: str
    secret: str | None = None


@dataclass(frozen=True, slots=True)
class SolarWindsCredentials:
    """Standalone SolarWinds SWIS connection settings."""

    hostname: str
    username: str
    password: str
    port: int = 17774


def _load_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid credentials line {line_number}; expected key=value.")
        key, value = line.split("=", 1)
        values[key.strip().casefold()] = value.strip()
    return values


def load_credentials(path: Path) -> Credentials:
    """Load device credentials without logging secret values."""
    values = _load_values(path)
    if not values.get("username") or not values.get("password"):
        raise ValueError("Credentials file must define username and password.")
    return Credentials(values["username"], values["password"], values.get("secret") or None)


def load_solarwinds_credentials(path: Path) -> SolarWindsCredentials:
    """Load standalone SolarWinds credentials from a local text file."""
    values = _load_values(path)
    required = ("solarwinds_hostname", "solarwinds_username", "solarwinds_password")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"SolarWinds credentials file is missing: {', '.join(missing)}")
    try:
        port = int(values.get("solarwinds_port", "17774"))
    except ValueError as exc:
        raise ValueError("solarwinds_port must be a number.") from exc
    hostname = _normalise_solarwinds_hostname(values["solarwinds_hostname"])
    return SolarWindsCredentials(
        hostname,
        values["solarwinds_username"],
        values["solarwinds_password"],
        port,
    )


def _normalise_solarwinds_hostname(value: str) -> str:
    """Accept a hostname or pasted web URL and retain only the server name."""
    candidate = value.strip()
    parsed = urlparse(candidate if "://" in candidate else f"//{candidate}")
    if not parsed.hostname:
        raise ValueError("solarwinds_hostname must contain a valid server hostname or URL.")
    return parsed.hostname
