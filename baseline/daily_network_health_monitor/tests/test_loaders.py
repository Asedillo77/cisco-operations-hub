from pathlib import Path

import pytest

from daily_network_health_monitor.loaders import load_inventory, load_profiles


def test_sample_inventory_loads() -> None:
    devices = load_inventory(Path("samples/inventory.csv"), max_devices=5)
    assert [device.device_type for device in devices] == ["switch", "edge_router"]


def test_profiles_expand_vrf() -> None:
    profiles = load_profiles(Path("configs"))
    assert "show ip route vrf 2" in profiles["edge_router"].commands


def test_inventory_limit_is_enforced() -> None:
    with pytest.raises(ValueError, match="limit is 1"):
        load_inventory(Path("samples/inventory.csv"), max_devices=1)
