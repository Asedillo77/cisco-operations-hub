import logging

from site_connectivity.engine import investigate_device
from site_connectivity.models import DeviceTarget, Status


def test_dry_run_does_not_require_credentials() -> None:
    result = investigate_device(
        DeviceTarget("EDGE01", "192.0.2.1", transport="cellular"),
        None,
        apply=False,
        logger=logging.getLogger("test"),
    )
    assert result.status == Status.PLANNED
    assert result.ping.status == Status.PLANNED
    assert len(result.checks) == 7


def test_dry_run_lists_optional_solarwinds_check() -> None:
    result = investigate_device(
        DeviceTarget("EDGE01", "192.0.2.1"),
        None,
        apply=False,
        logger=logging.getLogger("test"),
        solarwinds_requested=True,
    )
    assert result.checks[-1].check_id == "solarwinds_alerts"
    assert result.checks[-1].status == Status.PLANNED
