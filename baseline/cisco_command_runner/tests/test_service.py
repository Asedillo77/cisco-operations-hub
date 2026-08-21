import logging
from pathlib import Path

from cisco_command_runner.service import run_job


def test_dry_run_does_not_require_credentials_or_connect(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.csv"
    inventory.write_text(
        "hostname,ip_address,device_type\nSW1,192.0.2.1,switch\n", encoding="utf-8"
    )
    output = run_job(
        inventory_file=inventory,
        commands_text="show version",
        output_root=tmp_path / "outputs",
        template_dir=Path(__file__).parents[1] / "templates",
        apply=False,
        max_devices=10,
        max_workers=2,
        logger=logging.getLogger("test"),
    )
    assert (output / "command_results_short.html").is_file()
    assert '"planned": 1' in (output / "command_results.json").read_text(encoding="utf-8")
