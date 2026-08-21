"""Cross-platform ping collection and interpretation."""

from __future__ import annotations

import platform
import re
import subprocess

from .models import PingResult, Status
from .thresholds import assess_latency, assess_packet_loss

WINDOWS_PACKETS = re.compile(
    r"Packets:\s+Sent\s*=\s*(?P<sent>\d+),\s+Received\s*=\s*(?P<received>\d+),.*?\((?P<loss>[\d.]+)%\s+loss\)",
    re.IGNORECASE,
)
WINDOWS_LATENCY = re.compile(
    r"Minimum\s*=\s*(?P<minimum>\d+)ms,\s+Maximum\s*=\s*(?P<maximum>\d+)ms,\s+Average\s*=\s*(?P<average>\d+)ms",
    re.IGNORECASE,
)
POSIX_PACKETS = re.compile(
    r"(?P<sent>\d+)\s+packets transmitted,\s+(?P<received>\d+).*?(?P<loss>[\d.]+)%\s+packet loss",
    re.IGNORECASE,
)
POSIX_LATENCY = re.compile(
    r"(?:rtt|round-trip).*?=\s*(?P<minimum>[\d.]+)/(?P<average>[\d.]+)/(?P<maximum>[\d.]+)/",
    re.IGNORECASE,
)


def parse_ping_output(raw_output: str, return_code: int) -> PingResult:
    """Parse Windows, Linux, or macOS ping output into one result."""
    result = PingResult(raw_output=raw_output)
    packet_match = WINDOWS_PACKETS.search(raw_output) or POSIX_PACKETS.search(raw_output)
    latency_match = WINDOWS_LATENCY.search(raw_output) or POSIX_LATENCY.search(raw_output)
    if packet_match:
        result.transmitted = int(packet_match.group("sent"))
        result.received = int(packet_match.group("received"))
        result.loss_percent = float(packet_match.group("loss"))
    if latency_match:
        result.minimum_ms = float(latency_match.group("minimum"))
        result.average_ms = float(latency_match.group("average"))
        result.maximum_ms = float(latency_match.group("maximum"))

    latency_assessment = assess_latency(result.average_ms) if result.average_ms is not None else None
    if latency_assessment:
        result.latency_rating = latency_assessment.rating
        result.latency_explanation = latency_assessment.explanation
    loss_assessment = assess_packet_loss(result.loss_percent) if result.loss_percent is not None else None
    if loss_assessment:
        result.loss_rating = loss_assessment.rating
        result.loss_explanation = loss_assessment.explanation

    if return_code != 0 or result.received == 0:
        result.status = Status.DOWN
        result.message = "The device did not respond to ICMP reachability checks."
    elif result.loss_percent is None:
        result.status = Status.UNKNOWN
        result.message = "The device responded, but ping statistics could not be interpreted."
    elif result.loss_percent > 0:
        result.status = Status.DEGRADED
        latency = f" Average latency was {result.average_ms:g} ms." if result.average_ms is not None else ""
        result.message = (
            f"The device is reachable, but {result.loss_percent:g}% packet loss was observed "
            f"({loss_assessment.rating if loss_assessment else 'degraded'}).{latency}"
        )
    elif latency_assessment and latency_assessment.status == Status.DEGRADED:
        result.status = Status.DEGRADED
        result.message = (
            f"The device responded without packet loss, but average latency was "
            f"{result.average_ms:g} ms ({latency_assessment.rating})."
        )
    else:
        result.status = Status.HEALTHY
        latency = f" Average latency was {result.average_ms:g} ms." if result.average_ms is not None else ""
        result.message = f"The device responded without packet loss.{latency}"
    return result


def run_ping(host: str, count: int = 15, timeout_seconds: int = 2) -> PingResult:
    """Run a bounded system ping and return parsed evidence."""
    if count < 1 or count > 20:
        raise ValueError("Ping count must be between 1 and 20.")
    if timeout_seconds < 1 or timeout_seconds > 10:
        raise ValueError("Ping timeout must be between 1 and 10 seconds.")
    if platform.system().casefold() == "windows":
        command = ["ping", "-n", str(count), "-w", str(timeout_seconds * 1000), host]
    else:
        command = ["ping", "-c", str(count), "-W", str(timeout_seconds), host]
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            text=True,
            timeout=(count * timeout_seconds) + 5,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return PingResult(
            status=Status.DOWN,
            message=(
                f"The device did not complete the {count}-packet ICMP test within the allowed time. "
                "No reliable ping response was received."
            ),
            raw_output=str(exc),
        )
    except OSError as exc:
        return PingResult(status=Status.UNKNOWN, message=f"Ping could not be completed: {exc}")
    raw_output = (completed.stdout or "") + (completed.stderr or "")
    return parse_ping_output(raw_output, completed.returncode)
