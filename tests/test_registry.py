from cisco_operations_hub.registry import build_registry


def test_registry_exposes_all_preserved_tools() -> None:
    registry = build_registry()

    assert set(registry) == {
        "command-runner",
        "health-monitor",
        "port-capacity",
        "connectivity-evidence",
        "maintenance-validator",
    }
    assert registry["command-runner"].describe().available is True
    assert registry["health-monitor"].describe().available is True
    assert registry["port-capacity"].describe().available is True
    assert registry["connectivity-evidence"].describe().available is True
    assert registry["maintenance-validator"].describe().available is True
    assert sum(adapter.describe().available for adapter in registry.values()) == 5
