"""Optional read-only SolarWinds active-alert collection."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from .credentials import SolarWindsCredentials
from .models import CommandResult, DeviceTarget, Status


class SwisQueryClient(Protocol):
    """Small subset of the Orion SDK client used by this tool."""

    def query(self, query: str, **params: object) -> dict[str, Any]:
        """Run one parameterised SWQL query."""


class SolarWindsCollector(Protocol):
    """Interface accepted by the troubleshooting engine."""

    def collect_active_alerts(self, target: DeviceTarget) -> CommandResult:
        """Collect active alerts for one target."""


class SolarWindsError(RuntimeError):
    """Raised when the optional SolarWinds connection cannot be prepared."""


class SolarWindsAlertClient:
    """Resolve SolarWinds nodes and retrieve their active alerts."""

    def __init__(
        self,
        credentials: SolarWindsCredentials,
        logger: logging.Logger,
        client_factory: Callable[..., SwisQueryClient] | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        """Create and validate the read-only SWIS connection."""
        self.logger = logger
        self.now_factory = now_factory or (lambda: datetime.now(UTC))
        if client_factory is None:
            try:
                from orionsdk import SwisClient
            except ImportError as exc:
                raise SolarWindsError("Optional dependency 'orionsdk' is not installed.") from exc
            client_factory = SwisClient
        try:
            self.client = client_factory(
                hostname=credentials.hostname,
                username=credentials.username,
                password=credentials.password,
                verify=False,
                port=credentials.port,
            )
            self.client.query("SELECT TOP 1 HostName FROM Orion.OrionServers")
        except Exception as exc:
            raise SolarWindsError(f"SolarWinds connection failed: {exc}") from exc

    def _resolve_node_id(self, target: DeviceTarget) -> int | None:
        if target.solarwinds_node_id is not None:
            return target.solarwinds_node_id
        solarwinds_name = target.solarwinds_name or target.name
        solarwinds_ip = target.solarwinds_ip or target.host
        query = """
            SELECT TOP 5 NodeID, Caption, IPAddress
            FROM Orion.Nodes
            WHERE Caption = @caption OR IPAddress = @ip_address
        """
        response = self.client.query(query, caption=solarwinds_name, ip_address=solarwinds_ip)
        rows = response.get("results", [])
        exact = [
            row
            for row in rows
            if str(row.get("Caption", "")).casefold() == solarwinds_name.casefold()
            or str(row.get("IPAddress", "")) == solarwinds_ip
        ]
        if len(exact) != 1:
            return None
        return int(exact[0]["NodeID"])

    def collect_active_alerts(self, target: DeviceTarget) -> CommandResult:
        """Return a normalised check containing active SolarWinds alerts."""
        try:
            node_id = self._resolve_node_id(target)
            if node_id is None:
                return _unknown_result(
                    "SolarWinds node mapping could not be resolved uniquely.",
                    "Add solarwinds_node_id to the inventory or verify the device name and management address.",
                )
            self.logger.info("Checking SolarWinds active alerts for %s (NodeID %s)", target.name, node_id)
            node_response = self.client.query(
                """
                SELECT TOP 1 NodeID, Caption, IPAddress, Status, StatusDescription, LastSync,
                    SystemUpTime, MachineType, Vendor, IOSVersion
                FROM Orion.Nodes
                WHERE NodeID = @node_id
                """,
                node_id=node_id,
            )
            node_rows = node_response.get("results", [])
            node = node_rows[0] if node_rows else {}
            node_status_code = int(node["Status"]) if node.get("Status") is not None else None
            node_status = _node_status_label(node_status_code)
            node_status_detail = _clean_status_description(node.get("StatusDescription"), node_status)
            query = """
                SELECT
                    AC.Name AS AlertName,
                    AC.Severity,
                    AO.EntityCaption,
                    AO.EntityDetailsUrl,
                    AA.TriggeredDateTime,
                    AA.TriggeredMessage,
                    AA.Acknowledged,
                    AA.AcknowledgedBy
                FROM Orion.AlertActive AS AA
                JOIN Orion.AlertObjects AS AO ON AA.AlertObjectID = AO.AlertObjectID
                JOIN Orion.AlertConfigurations AS AC ON AO.AlertID = AC.AlertID
                WHERE AO.RelatedNodeId = @node_id
                ORDER BY AA.TriggeredDateTime DESC
            """
            response = self.client.query(query, node_id=node_id)
            alerts = [dict(alert) for alert in response.get("results", [])]
            interface_response = self.client.query(
                """
                SELECT InterfaceID, NodeID, Caption, Status, OperStatus, Speed, InterfaceType, LastSync
                FROM Orion.NPM.Interfaces
                WHERE NodeID = @node_id
                ORDER BY Caption
                """,
                node_id=node_id,
            )
            interfaces = interface_response.get("results", [])
            correlation = _correlate_alerts(alerts, interfaces, self.now_factory())
        except Exception as exc:
            self.logger.exception("SolarWinds alert collection failed for %s", target.name)
            return _unknown_result(
                f"SolarWinds active alerts could not be checked: {exc}",
                "Verify API access and test the SWQL query in SWQL Studio.",
            )
        if not alerts:
            status = Status.HEALTHY if node_status_code == 1 else _monitoring_status(node_status_code)
            return CommandResult(
                "solarwinds_alerts",
                "SolarWinds active alerts API",
                status,
                f"SolarWinds node status is {node_status}; no active alerts are mapped to this edge router.",
                "The current SolarWinds node poll is the primary monitoring signal for this check.",
                "Review the node status if it differs from the live reachability result.",
                evidence={
                    "node_id": node_id,
                    "node_status": node_status,
                    "node_status_code": node_status_code,
                    "node_status_detail": node_status_detail,
                    "node": node,
                    "interfaces_checked": len(interfaces),
                    "alert_count": 0,
                    "alerts": [],
                },
            )
        status = Status.INFORMATIONAL if node_status_code == 1 else _monitoring_status(node_status_code)
        age_summary = correlation["age_summary"]
        if status == Status.DOWN:
            explanation = f"SolarWinds currently reports the node as down. {node_status_detail}"
        elif status == Status.INFORMATIONAL:
            stale_detail = _stale_alert_detail(correlation)
            interface_detail = _interface_alert_detail(correlation)
            explanation = (
                "SolarWinds currently reports the node as up. "
                f"{stale_detail}{interface_detail}"
                "Active alerts may be old or uncleared and do not override healthy live evidence."
            )
        else:
            explanation = f"{node_status_detail} The current node status and alerts require live-check correlation."
        return CommandResult(
            "solarwinds_alerts",
            "SolarWinds active alerts API",
            status,
            f"SolarWinds node status is {node_status}, with {len(alerts)} active alert(s); {age_summary}.",
            explanation,
            "Review alert age and affected objects; investigate alerts that agree with the current live checks.",
            evidence={
                "node_id": node_id,
                "node_status": node_status,
                "node_status_code": node_status_code,
                "node_status_detail": node_status_detail,
                "node": node,
                "interfaces_checked": len(interfaces),
                "alert_count": len(alerts),
                "alerts": alerts,
                **correlation,
            },
        )


class UnavailableSolarWindsCollector:
    """Return visible unknown results when optional setup fails."""

    def __init__(self, reason: str) -> None:
        """Store the setup failure without exposing credentials."""
        self.reason = reason

    def collect_active_alerts(self, target: DeviceTarget) -> CommandResult:
        """Return an unknown check rather than blocking router diagnostics."""
        del target
        return _unknown_result(self.reason, "Check the optional SolarWinds credentials, dependency, and connectivity.")


def _unknown_result(summary: str, action: str) -> CommandResult:
    return CommandResult(
        "solarwinds_alerts",
        "SolarWinds active alerts API",
        Status.UNKNOWN,
        summary,
        "The optional monitoring check was unable to provide a reliable result.",
        action,
    )


def _node_status_label(status_code: int | None) -> str:
    labels = {1: "Up", 2: "Down", 3: "Warning", 9: "Unreachable", 14: "Critical", 15: "Partly Available"}
    if status_code is None:
        return "Unable to verify"
    return labels.get(status_code, f"Status code {status_code}")


def _monitoring_status(status_code: int | None) -> Status:
    if status_code == 1:
        return Status.HEALTHY
    if status_code == 2:
        return Status.DOWN
    if status_code in {3, 9, 14, 15}:
        return Status.DEGRADED
    return Status.UNKNOWN


def _clean_status_description(value: object, fallback: str) -> str:
    description = str(value or "").strip()
    if not description:
        return f"SolarWinds reports {fallback}."
    description = description.removeprefix("Node status is ").strip()
    if description.casefold().startswith(fallback.casefold()):
        description = description[len(fallback) :].lstrip(" ,:-")
    if not description:
        return f"SolarWinds reports {fallback}."
    return description[0].upper() + description[1:]


def _parse_solarwinds_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        timestamp = value.strip().replace("Z", "+00:00")
        if "." in timestamp:
            prefix, suffix = timestamp.split(".", 1)
            fraction = suffix
            timezone_suffix = ""
            for marker in ("+", "-"):
                if marker in suffix:
                    fraction, zone = suffix.split(marker, 1)
                    timezone_suffix = marker + zone
                    break
            timestamp = f"{prefix}.{fraction[:6]}{timezone_suffix}"
        try:
            parsed = datetime.fromisoformat(timestamp)
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _age_text(hours: float) -> str:
    if hours >= 48:
        return f"{hours / 24:.1f} days old"
    if hours >= 24:
        return f"{hours / 24:.1f} day old"
    if hours >= 1:
        return f"{hours:.1f} hours old"
    return "less than 1 hour old"


def _interface_key(value: object) -> str:
    caption = str(value or "").split("·", 1)[0].strip()
    return caption.casefold()


def _correlate_alerts(alerts: list[dict[str, Any]], interfaces: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    current_time = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    interface_index = {_interface_key(interface.get("Caption")): interface for interface in interfaces}
    ages: list[float] = []
    matched_interfaces = 0
    matched_interfaces_up = 0
    for alert in alerts:
        triggered = _parse_solarwinds_time(alert.get("TriggeredDateTime"))
        if triggered is not None:
            age_hours = max(0.0, (current_time - triggered).total_seconds() / 3600)
            alert["AgeHours"] = round(age_hours, 1)
            alert["AgeText"] = _age_text(age_hours)
            ages.append(age_hours)
        interface = interface_index.get(_interface_key(alert.get("EntityCaption")))
        if interface is not None:
            matched_interfaces += 1
            interface_up = interface.get("Status") == 1 and interface.get("OperStatus") == 1
            matched_interfaces_up += int(interface_up)
            alert["CurrentInterfaceStatus"] = interface.get("Status")
            alert["CurrentInterfaceOperStatus"] = interface.get("OperStatus")
            alert["InterfaceCurrentlyUp"] = interface_up
    oldest = max(ages) if ages else None
    newest = min(ages) if ages else None
    if oldest is None or newest is None:
        age_summary = "alert age could not be calculated"
    elif len(ages) == 1:
        age_summary = f"the alert is {_age_text(oldest)}"
    else:
        age_summary = f"the oldest is {_age_text(oldest)} and the newest is {_age_text(newest)}"
    return {
        "oldest_alert_age_hours": round(oldest, 1) if oldest is not None else None,
        "newest_alert_age_hours": round(newest, 1) if newest is not None else None,
        "stale_alert_count": sum(age >= 24 for age in ages),
        "alerts_with_known_age": len(ages),
        "age_summary": age_summary,
        "interface_alert_matches": matched_interfaces,
        "interface_alerts_currently_up": matched_interfaces_up,
    }


def _stale_alert_detail(correlation: dict[str, Any]) -> str:
    known = correlation["alerts_with_known_age"]
    stale = correlation["stale_alert_count"]
    if not known:
        return "Alert trigger ages could not be calculated. "
    if stale == known:
        return f"All {known} dated alert(s) are at least 24 hours old. "
    if stale:
        return f"{stale} of {known} dated alert(s) are at least 24 hours old. "
    return "All dated alerts were triggered within the last 24 hours. "


def _interface_alert_detail(correlation: dict[str, Any]) -> str:
    matched = correlation["interface_alert_matches"]
    current_up = correlation["interface_alerts_currently_up"]
    if not matched:
        return ""
    return f"{current_up} of {matched} matched interface alert object(s) currently show up/up. "
