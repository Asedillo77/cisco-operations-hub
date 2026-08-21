import logging
from datetime import UTC, datetime

from site_connectivity.credentials import SolarWindsCredentials
from site_connectivity.models import DeviceTarget, Status
from site_connectivity.solarwinds import SolarWindsAlertClient, UnavailableSolarWindsCollector


class FakeSwisClient:
    def __init__(self, alerts: list[dict[str, object]], interfaces: list[dict[str, object]] | None = None) -> None:
        self.alerts = alerts
        self.interfaces = interfaces or []

    def query(self, query: str, **params: object) -> dict[str, object]:
        if "Orion.OrionServers" in query:
            return {"results": [{"HostName": "solarwinds.example"}]}
        if "FROM Orion.Nodes" in query:
            if "WHERE NodeID" in query:
                return {
                    "results": [
                        {
                            "NodeID": 42,
                            "Caption": "EDGE01",
                            "Status": 1,
                            "StatusDescription": "Up",
                            "LastSync": "2026-08-11T01:55:00Z",
                        }
                    ]
                }
            return {"results": [{"NodeID": 42, "Caption": "EDGE01", "IPAddress": "192.0.2.1"}]}
        if "Orion.NPM.Interfaces" in query:
            return {"results": self.interfaces}
        assert params["node_id"] == 42
        return {"results": self.alerts}


class AlternateIdentitySwisClient(FakeSwisClient):
    def query(self, query: str, **params: object) -> dict[str, object]:
        if "FROM Orion.Nodes" in query:
            if "WHERE NodeID" in query:
                return {"results": [{"NodeID": 250, "Caption": "LAB-HUB-01", "Status": 1, "StatusDescription": "Up"}]}
            assert params == {"caption": "LAB-HUB-01", "ip_address": "192.0.2.250"}
            return {"results": [{"NodeID": 250, "Caption": "LAB-HUB-01", "IPAddress": "192.0.2.250"}]}
        if "Orion.OrionServers" not in query:
            assert params["node_id"] == 250
            return {"results": self.alerts}
        return super().query(query, **params)


class DownNodeSwisClient(FakeSwisClient):
    def query(self, query: str, **params: object) -> dict[str, object]:
        if "FROM Orion.Nodes" in query and "WHERE NodeID" in query:
            return {"results": [{"NodeID": 42, "Caption": "EDGE01", "Status": 2}]}
        return super().query(query, **params)


def make_collector(alerts: list[dict[str, object]]) -> SolarWindsAlertClient:
    fake = FakeSwisClient(alerts)
    return SolarWindsAlertClient(
        SolarWindsCredentials("solarwinds.example", "user", "password"),
        logging.getLogger("test"),
        client_factory=lambda **_kwargs: fake,
    )


def test_no_active_solarwinds_alerts_is_healthy() -> None:
    result = make_collector([]).collect_active_alerts(DeviceTarget("EDGE01", "192.0.2.1"))
    assert result.status == Status.HEALTHY
    assert result.evidence["node_id"] == 42


def test_active_alert_on_up_solarwinds_node_is_informational() -> None:
    alert = {
        "AlertName": "Node is down",
        "Severity": 2,
        "TriggeredDateTime": "2026-08-09T02:00:00Z",
    }
    fake = FakeSwisClient([alert])
    collector = SolarWindsAlertClient(
        SolarWindsCredentials("solarwinds.example", "user", "password"),
        logging.getLogger("test"),
        client_factory=lambda **_kwargs: fake,
        now_factory=lambda: datetime(2026, 8, 11, 2, 0, tzinfo=UTC),
    )
    result = collector.collect_active_alerts(DeviceTarget("EDGE01", "192.0.2.1"))
    assert result.status == Status.INFORMATIONAL
    assert result.evidence["alerts"][0]["AgeText"] == "2.0 days old"
    assert result.evidence["node_status"] == "Up"
    assert result.evidence["stale_alert_count"] == 1


def test_down_solarwinds_node_is_down_even_with_active_alerts() -> None:
    fake = DownNodeSwisClient([{"AlertName": "Node is down", "Severity": 2}])
    collector = SolarWindsAlertClient(
        SolarWindsCredentials("solarwinds.example", "user", "password"),
        logging.getLogger("test"),
        client_factory=lambda **_kwargs: fake,
    )
    result = collector.collect_active_alerts(DeviceTarget("EDGE01", "192.0.2.1"))
    assert result.status == Status.DOWN
    assert result.evidence["node_status"] == "Down"


def test_unavailable_solarwinds_is_visible_but_non_blocking() -> None:
    result = UnavailableSolarWindsCollector("Authentication failed").collect_active_alerts(
        DeviceTarget("EDGE01", "192.0.2.1")
    )
    assert result.status == Status.UNKNOWN
    assert "Authentication failed" in result.summary


def test_solarwinds_identity_can_differ_from_ssh_identity() -> None:
    fake = AlternateIdentitySwisClient([])
    collector = SolarWindsAlertClient(
        SolarWindsCredentials("solarwinds.example", "user", "password"),
        logging.getLogger("test"),
        client_factory=lambda **_kwargs: fake,
    )
    target = DeviceTarget(
        "IDCEDGE01",
        "192.0.2.250",
        solarwinds_name="LAB-HUB-01",
        solarwinds_ip="192.0.2.250",
    )
    result = collector.collect_active_alerts(target)
    assert result.status == Status.HEALTHY
    assert result.evidence["node_id"] == 250


def test_old_interface_alert_is_correlated_with_current_up_interface() -> None:
    alert = {
        "AlertName": "Interface is down",
        "EntityCaption": "GigabitEthernet0/0/0.101",
        "TriggeredDateTime": "2026-08-05T02:00:00.0000000Z",
    }
    interface = {
        "Caption": "GigabitEthernet0/0/0.101 · VPN 0 Internet Interface",
        "Status": 1,
        "OperStatus": 1,
    }
    fake = FakeSwisClient([alert], [interface])
    collector = SolarWindsAlertClient(
        SolarWindsCredentials("solarwinds.example", "user", "password"),
        logging.getLogger("test"),
        client_factory=lambda **_kwargs: fake,
        now_factory=lambda: datetime(2026, 8, 11, 2, 0, tzinfo=UTC),
    )
    result = collector.collect_active_alerts(DeviceTarget("EDGE01", "192.0.2.1"))
    assert result.evidence["interface_alert_matches"] == 1
    assert result.evidence["interface_alerts_currently_up"] == 1
    assert result.evidence["alerts"][0]["InterfaceCurrentlyUp"] is True
    assert "currently show up/up" in result.explanation


def test_solarwinds_status_description_does_not_duplicate_status_wording() -> None:
    fake = FakeSwisClient([])
    fake.query = lambda query, **_params: (
        {
            "results": [
                {
                    "NodeID": 42,
                    "Caption": "EDGE01",
                    "Status": 3,
                    "StatusDescription": "Node status is Warning, One or more interfaces are Down.",
                }
            ]
        }
        if "FROM Orion.Nodes" in query and "WHERE NodeID" in query
        else {"results": []}
    )
    collector = SolarWindsAlertClient(
        SolarWindsCredentials("solarwinds.example", "user", "password"),
        logging.getLogger("test"),
        client_factory=lambda **_kwargs: fake,
    )
    result = collector.collect_active_alerts(DeviceTarget("EDGE01", "192.0.2.1", solarwinds_node_id=42))
    assert result.evidence["node_status"] == "Warning"
    assert result.evidence["node_status_detail"] == "One or more interfaces are Down."
    assert "Node status is Node status is" not in result.summary
