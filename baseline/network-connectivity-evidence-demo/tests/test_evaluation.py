from site_connectivity.evaluation import combine_device_status, evaluate_cellular_radio, evaluate_uptime
from site_connectivity.models import DeviceTarget, PingResult, Status
from site_connectivity.profiles import BASE_PROFILE, CELLULAR_PROFILE


def test_weak_cellular_radio_is_degraded() -> None:
    output = "RSSI = -83 dBm\nRSRP = -112 dBm\nRSRQ = -16 dB\nSINR = 4 dB"
    result = evaluate_cellular_radio(CELLULAR_PROFILE[0], output)
    assert result.status == Status.DEGRADED
    assert result.evidence["rsrp_dbm"] == -112


def test_reachability_and_cellular_are_correlated() -> None:
    ping = PingResult(status=Status.HEALTHY, received=4, loss_percent=0)
    cellular = evaluate_cellular_radio(CELLULAR_PROFILE[0], "RSRP = -115 dBm\nRSRQ = -17 dB")
    status, summary = combine_device_status(ping, Status.HEALTHY, [cellular])
    assert status == Status.DEGRADED
    assert "reachable" in summary


def test_fixed_site_uptime_is_informational_restart_context() -> None:
    result = evaluate_uptime(
        BASE_PROFILE[0],
        "EDGE01 uptime is 3 weeks, 2 days",
        DeviceTarget("EDGE01", "192.0.2.1", site_type="branch"),
    )
    assert result.status == Status.INFORMATIONAL
    assert "recent restart" in result.explanation


def test_mobile_site_short_uptime_is_not_a_fault() -> None:
    result = evaluate_uptime(
        BASE_PROFILE[0],
        "LAB-MOBILE-01 uptime is 2 hours",
        DeviceTarget("LAB-MOBILE-01", "192.0.2.2", site_type="mobile_unit"),
    )
    assert result.status == Status.INFORMATIONAL
    assert "normal for DMU and DMT equipment" in result.explanation
