import subprocess
from typing import NoReturn

from pytest import MonkeyPatch

from site_connectivity import reachability
from site_connectivity.models import Status
from site_connectivity.reachability import parse_ping_output, run_ping


def test_windows_ping_is_parsed() -> None:
    output = """
    Packets: Sent = 4, Received = 3, Lost = 1 (25% loss),
    Minimum = 83ms, Maximum = 184ms, Average = 126ms
    """
    result = parse_ping_output(output, 0)
    assert result.status == Status.DEGRADED
    assert result.loss_percent == 25
    assert result.loss_rating == "high"
    assert result.average_ms == 126


def test_unreachable_ping_is_down() -> None:
    result = parse_ping_output("Request timed out.", 1)
    assert result.status == Status.DOWN


def test_elevated_latency_degrades_reachable_result() -> None:
    output = """
    Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),
    Minimum = 140ms, Maximum = 220ms, Average = 151ms
    """
    result = parse_ping_output(output, 0)
    assert result.status == Status.DEGRADED
    assert result.latency_rating == "elevated"


def test_very_poor_latency_remains_reachable_but_degraded() -> None:
    output = """
    Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),
    Minimum = 480ms, Maximum = 620ms, Average = 501ms
    """
    result = parse_ping_output(output, 0)
    assert result.status == Status.DEGRADED
    assert result.latency_rating == "very poor"


def test_ping_process_timeout_is_treated_as_unreachable(monkeypatch: MonkeyPatch) -> None:
    def timeout(*_args: object, **_kwargs: object) -> NoReturn:
        raise subprocess.TimeoutExpired(["ping"], 35)

    monkeypatch.setattr(reachability.platform, "system", lambda: "Windows")
    monkeypatch.setattr(subprocess, "run", timeout)
    result = run_ping("192.0.2.1")
    assert result.status == Status.DOWN
    assert "No reliable ping response" in result.message
