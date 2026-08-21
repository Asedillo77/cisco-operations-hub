from daily_network_health_monitor.runner import _hostname_from_prompt


def test_hostname_from_standard_prompt() -> None:
    assert _hostname_from_prompt("LAB-SW-02#") == "LAB-SW-02"


def test_hostname_from_configuration_prompt() -> None:
    assert _hostname_from_prompt("LAB-SW-02(config)#") == "LAB-SW-02"
