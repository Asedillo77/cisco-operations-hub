"""Central operational thresholds for latency and LTE radio measurements."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Status


@dataclass(frozen=True, slots=True)
class Assessment:
    """One normalised measurement assessment."""

    rating: str
    status: Status
    explanation: str


def assess_latency(average_ms: float) -> Assessment:
    """Assess average round-trip latency using initial service-desk bands."""
    if average_ms <= 150:
        return Assessment("good", Status.HEALTHY, "Average latency is within the initial target of 150 ms or less.")
    if average_ms <= 300:
        return Assessment(
            "elevated",
            Status.DEGRADED,
            "Average latency is elevated. This may be noticeable for interactive applications, especially on 4G.",
        )
    if average_ms <= 500:
        return Assessment(
            "poor",
            Status.DEGRADED,
            "Average latency is poor and is likely to cause noticeable slowness or delayed application responses.",
        )
    return Assessment(
        "very poor",
        Status.DEGRADED,
        "Average latency is very poor and can severely affect interactive applications even though the site replies.",
    )


def assess_packet_loss(loss_percent: float) -> Assessment:
    """Assess packet loss while preserving successful reachability."""
    if loss_percent <= 0:
        return Assessment("none", Status.HEALTHY, "No packet loss was observed during this sample.")
    if loss_percent <= 10:
        return Assessment(
            "intermittent",
            Status.DEGRADED,
            "Intermittent packet loss was observed and may contribute to brief pauses or retries.",
        )
    if loss_percent <= 25:
        return Assessment(
            "high",
            Status.DEGRADED,
            "Packet loss is high and is likely to affect application reliability and performance.",
        )
    return Assessment(
        "severe",
        Status.DEGRADED,
        "Packet loss is severe and the connection may appear intermittent or unusable.",
    )


def assess_rssi(value: float) -> Assessment:
    """Assess LTE RSSI as supporting wideband power evidence."""
    if value > -65:
        return Assessment("excellent", Status.HEALTHY, "Overall received radio power is excellent.")
    if value >= -75:
        return Assessment("good", Status.HEALTHY, "Overall received radio power is good.")
    if value >= -85:
        return Assessment("fair", Status.DEGRADED, "Overall received radio power is fair but still useful.")
    if value > -95:
        return Assessment("poor", Status.DEGRADED, "Overall received radio power is poor and performance may drop.")
    return Assessment("very poor", Status.DEGRADED, "Overall received radio power is very poor and service may drop.")


def assess_rsrp(value: float) -> Assessment:
    """Assess LTE reference-signal strength."""
    if value >= -80:
        return Assessment("excellent", Status.HEALTHY, "LTE reference-signal strength is excellent.")
    if value >= -90:
        return Assessment("good", Status.HEALTHY, "LTE reference-signal strength is good.")
    if value >= -100:
        return Assessment(
            "fair to poor",
            Status.DEGRADED,
            "LTE signal strength is marginal; reliable service is possible, but drop-outs may occur.",
        )
    return Assessment(
        "poor",
        Status.DEGRADED,
        "LTE reference-signal strength is poor and performance or stability may be affected.",
    )


def assess_rsrq(value: float) -> Assessment:
    """Assess LTE reference-signal quality."""
    if value >= -10:
        return Assessment("excellent", Status.HEALTHY, "LTE reference-signal quality is excellent.")
    if value >= -15:
        return Assessment("good", Status.HEALTHY, "LTE reference-signal quality is good.")
    if value > -20:
        return Assessment(
            "fair to poor",
            Status.DEGRADED,
            "LTE signal quality is marginal and may indicate interference or congestion.",
        )
    return Assessment(
        "poor",
        Status.DEGRADED,
        "LTE signal quality is poor; interference or congestion may severely affect performance.",
    )


def assess_sinr(value: float) -> Assessment:
    """Assess LTE signal-to-interference-plus-noise ratio."""
    if value >= 20:
        return Assessment("excellent", Status.HEALTHY, "The useful LTE signal is very clear relative to interference.")
    if value >= 13:
        return Assessment("good", Status.HEALTHY, "The useful LTE signal is clear relative to interference.")
    if value > 0:
        return Assessment(
            "fair to poor",
            Status.DEGRADED,
            "Interference or noise may restrict throughput and contribute to inconsistent performance.",
        )
    return Assessment(
        "poor",
        Status.DEGRADED,
        "Interference or noise is severe and LTE performance is likely to be substantially affected.",
    )


SIGNAL_ASSESSORS = {
    "rssi_dbm": assess_rssi,
    "rsrp_dbm": assess_rsrp,
    "rsrq_db": assess_rsrq,
    "sinr_db": assess_sinr,
}
