"""Small Catalyst Center API client used by the standalone audit."""

from __future__ import annotations

import logging
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


class CatalystCenterClient:
    """Read device and interface inventory from Catalyst Center."""

    def __init__(self, base_url: str, username: str, password: str, *, verify: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.verify = verify

    def authenticate(self) -> None:
        """Request an authentication token and attach it to the session."""
        LOGGER.info("Authenticating to Catalyst Center at %s", self.base_url)
        response = self.session.post(
            f"{self.base_url}/dna/system/api/v1/auth/token",
            auth=(self.username, self.password),
            timeout=30,
        )
        response.raise_for_status()
        token = response.json().get("Token") or response.json().get("token")
        if not token:
            raise RuntimeError("Catalyst Center authentication response did not contain a token")
        self.session.headers.update({"X-Auth-Token": token, "Accept": "application/json"})

    def _get(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}{path}", params=params, timeout=60)
        response.raise_for_status()
        return response.json()

    def find_device(self, target: str) -> dict[str, Any]:
        """Find one device by UUID or management IP address."""
        if "-" in target and len(target) >= 32:
            payload = self._get(f"/dna/intent/api/v1/network-device/{target}")
        else:
            payload = self._get(
                "/dna/intent/api/v1/network-device",
                params={"managementIpAddress": target},
            )
        response = payload.get("response")
        if isinstance(response, list):
            if len(response) != 1:
                raise LookupError(f"Expected one device for {target!r}, found {len(response)}")
            return response[0]
        if isinstance(response, dict):
            return response
        raise LookupError(f"No Catalyst Center device found for {target!r}")

    def get_interfaces(self, device_id: str) -> list[dict[str, Any]]:
        """Return interface inventory and packet timestamps for a device."""
        payload = self._get(f"/dna/intent/api/v1/interface/network-device/{device_id}")
        response = payload.get("response", [])
        if not isinstance(response, list):
            raise RuntimeError("Unexpected interface response from Catalyst Center")
        return response
