from site_connectivity.models import Status
from site_connectivity.thresholds import (
    assess_latency,
    assess_packet_loss,
    assess_rsrp,
    assess_rsrq,
    assess_rssi,
    assess_sinr,
)


def test_latency_boundaries() -> None:
    assert assess_latency(150).rating == "good"
    assert assess_latency(150.1).rating == "elevated"
    assert assess_latency(300.1).rating == "poor"
    assert assess_latency(500.1).rating == "very poor"


def test_lte_signal_reference_boundaries() -> None:
    assert assess_rssi(-64).rating == "excellent"
    assert assess_rssi(-95).rating == "very poor"
    assert assess_rsrp(-80).rating == "excellent"
    assert assess_rsrp(-101).status == Status.DEGRADED
    assert assess_rsrq(-10).rating == "excellent"
    assert assess_rsrq(-20).rating == "poor"
    assert assess_sinr(20).rating == "excellent"
    assert assess_sinr(0).rating == "poor"


def test_packet_loss_boundaries() -> None:
    assert assess_packet_loss(0).rating == "none"
    assert assess_packet_loss(10).rating == "intermittent"
    assert assess_packet_loss(25).rating == "high"
    assert assess_packet_loss(25.1).rating == "severe"
