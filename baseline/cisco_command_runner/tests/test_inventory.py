from pathlib import Path

import pytest
from openpyxl import Workbook

from cisco_command_runner.inventory import load_inventory


def test_load_csv_normalizes_device_rows(tmp_path: Path) -> None:
    path = tmp_path / "inventory.csv"
    path.write_text(
        "Hostname,IP Address,Device Type,Enabled\nSW1,192.0.2.1,switch,true\n"
        "ER1,192.0.2.2,edge_router,false\n",
        encoding="utf-8",
    )
    devices = load_inventory(path)
    assert len(devices) == 1
    assert devices[0].hostname == "SW1"
    assert devices[0].connection_target == "192.0.2.1"
    assert devices[0].row_number == 2


def test_load_xlsx_inventory(tmp_path: Path) -> None:
    path = tmp_path / "inventory.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["hostname", "ip_address", "device_type", "enabled"])
    sheet.append(["SW1", "192.0.2.1", "switch", True])
    workbook.save(path)
    workbook.close()
    assert load_inventory(path)[0].hostname == "SW1"


def test_inventory_limit_is_checked_before_execution(tmp_path: Path) -> None:
    path = tmp_path / "inventory.csv"
    path.write_text(
        "hostname,ip_address,device_type\nSW1,192.0.2.1,switch\nSW2,192.0.2.2,switch\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="limit is 1"):
        load_inventory(path, max_devices=1)


def test_invalid_rows_are_reported_with_row_number(tmp_path: Path) -> None:
    path = tmp_path / "inventory.csv"
    path.write_text("hostname,ip_address,device_type\nSW1,192.0.2.1,firewall\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Row 2"):
        load_inventory(path)
