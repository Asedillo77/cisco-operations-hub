import csv
from pathlib import Path

import pytest
from openpyxl import Workbook

from cisco_operations_hub.inventory_files import RUNTIME_ROOT, prepare_tabular_inventory


def create_xlsx(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["hostname", "ip_address", "device_type", "enabled"])
    sheet.append(["LAB-SW-01", "192.0.2.10", "switch", True])
    sheet.append(["LAB-ER-01", "192.0.2.11", "edge_router", True])
    workbook.save(path)
    workbook.close()


def test_csv_is_used_without_conversion(tmp_path: Path) -> None:
    source = tmp_path / "inventory.csv"
    source.write_text("hostname,ip_address,device_type\nLAB-SW-01,192.0.2.10,switch\n")

    with prepare_tabular_inventory(source) as prepared:
        assert prepared == source.resolve()


def test_xlsx_is_normalized_and_runtime_copy_is_removed(tmp_path: Path) -> None:
    source = tmp_path / "inventory.xlsx"
    create_xlsx(source)

    with prepare_tabular_inventory(source) as prepared:
        runtime_folder = prepared.parent
        with prepared.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert rows[0]["hostname"] == "LAB-SW-01"
        assert rows[1]["device_type"] == "edge_router"
        assert runtime_folder.parent == RUNTIME_ROOT
        assert runtime_folder.is_dir()

    assert not runtime_folder.exists()


def test_unsupported_inventory_format_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "inventory.json"
    source.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="CSV or XLSX"), prepare_tabular_inventory(source):
        pass
