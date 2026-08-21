import json
from pathlib import Path

import pytest

from site_connectivity.inventory import devices_for_site, load_inventory, sites_from_inventory


def test_inventory_is_normalised_and_filtered(tmp_path: Path) -> None:
    path = tmp_path / "inventory.json"
    path.write_text(
        json.dumps(
            {
                "devices": [
                    {"site": "Site B", "name": "R2", "host": "192.0.2.2"},
                    {"site": "Site A", "name": "R1", "host": "192.0.2.1", "transport": "CELLULAR"},
                ]
            }
        ),
        encoding="utf-8",
    )
    targets = load_inventory(path)
    assert sites_from_inventory(targets) == ["Site A", "Site B"]
    assert devices_for_site(targets, "Site A")[0].is_cellular


def test_inventory_rejects_invalid_host(tmp_path: Path) -> None:
    path = tmp_path / "inventory.json"
    path.write_text('[{"name":"bad","host":"router; reboot"}]', encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid device hostname"):
        load_inventory(path)


def test_inventory_loads_edge_role_and_service_vrfs(tmp_path: Path) -> None:
    path = tmp_path / "inventory.json"
    path.write_text(
        '[{"name":"EDGE02","host":"192.0.2.2","edge_role":"secondary","service_vrfs":["10","20"]}]',
        encoding="utf-8",
    )
    target = load_inventory(path)[0]
    assert target.edge_role == "secondary"
    assert target.service_vrfs == ("10", "20")


@pytest.mark.parametrize(
    ("site_type", "expected"),
    [
        ("dmu", "dmu"),
        ("mobile_unit", "dmu"),
        ("dmt", "dmt"),
        ("portable_unit", "dmt"),
        ("donor_centre", "donor_centre"),
        ("branch", "donor_centre"),
        ("processing_centre", "processing_centre"),
        ("dual_edge_hub", "processing_centre"),
    ],
)
def test_inventory_accepts_v7_and_browser_site_type_aliases(tmp_path: Path, site_type: str, expected: str) -> None:
    path = tmp_path / "inventory.json"
    path.write_text(
        json.dumps([{"name": "EDGE01", "host": "192.0.2.1", "site_type": site_type}]),
        encoding="utf-8",
    )

    assert load_inventory(path)[0].site_type == expected
