"""Offline Catalyst Center adapter for demonstrations and tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class MockCatalystCenterClient:
    """Serve Catalyst-like responses from a local JSON fixture."""

    def __init__(self, path: Path) -> None:
        self.payload = json.loads(path.read_text(encoding="utf-8"))

    def authenticate(self) -> None:
        """Match the live client contract without network access."""

    def find_device(self, target: str) -> dict[str, Any]:
        """Find a fixture device by ID or management address."""
        for device in self.payload["devices"]:
            if target in {device["id"], device["managementIpAddress"]}:
                return device
        raise LookupError(f"No mock device found for {target!r}")

    def get_interfaces(self, device_id: str) -> list[dict[str, Any]]:
        """Return fixture interfaces for one device."""
        return list(self.payload["interfaces"].get(device_id, []))
