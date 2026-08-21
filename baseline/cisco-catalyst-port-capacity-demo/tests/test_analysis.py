from datetime import datetime

from catalyst_port_capacity.analysis import assess_device, assess_interface, natural_port_key
from catalyst_port_capacity.switch_cli import reportable_switchport


def test_physical_port_filter_and_sorting() -> None:
    assert reportable_switchport("TwoGigabitEthernet2/0/36")
    assert not reportable_switchport("TenGigabitEthernet2/1/1")
    assert not reportable_switchport("Port-channel10")
    names = ["Gi2/0/2", "Gi1/0/10", "Gi1/0/2"]
    assert sorted(names, key=natural_port_key) == ["Gi1/0/2", "Gi1/0/10", "Gi2/0/2"]


def test_port_sorting_follows_stack_members_across_interface_types() -> None:
    names = [
        "GigabitEthernet4/0/1",
        "TenGigabitEthernet1/0/37",
        "TwoGigabitEthernet2/0/1",
        "GigabitEthernet3/0/1",
        "TwoGigabitEthernet1/0/1",
    ]

    assert sorted(names, key=natural_port_key) == [
        "TwoGigabitEthernet1/0/1",
        "TenGigabitEthernet1/0/37",
        "TwoGigabitEthernet2/0/1",
        "GigabitEthernet3/0/1",
        "GigabitEthernet4/0/1",
    ]


def test_uptime_confidence_and_active_port() -> None:
    device = assess_device({"id": "x", "hostname": "switch.example.net", "uptimeSeconds": 70 * 86400})
    assert device.confidence == "HIGH"
    port = assess_interface(
        device,
        {"portName": "Gi1/0/1", "adminStatus": "UP", "status": "UP"},
        datetime.now().astimezone(),
    )
    assert port.usage_flag == "ACTIVE"
