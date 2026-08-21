from __future__ import annotations

import argparse
from pathlib import Path

from .logging_utils import configure_logging
from .models import CommandResult
from .reporting import build_report, write_reports
from .service import run_job

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_DIR = PACKAGE_TEMPLATE_DIR if PACKAGE_TEMPLATE_DIR.is_dir() else PROJECT_ROOT / "templates"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely run operational commands on Cisco devices."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    run_parser = subparsers.add_parser("run", help="Validate or execute a command run.")
    run_parser.add_argument("--inventory", type=Path, required=True)
    source = run_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--commands-file", type=Path)
    source.add_argument("--command", action="append", dest="commands")
    run_parser.add_argument("--credentials-file", type=Path)
    run_parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "outputs")
    run_parser.add_argument("--max-devices", type=int, default=50)
    run_parser.add_argument("--max-workers", type=int, default=3)
    run_parser.add_argument(
        "--result-handling",
        choices=("complete", "common-summary"),
        default="complete",
        help="Keep the normal preview or show a common parsed summary where supported.",
    )
    run_parser.add_argument("--apply", action="store_true")
    run_parser.add_argument("--debug", action="store_true")

    mock_parser = subparsers.add_parser("mock-report", help="Render sample reports without SSH.")
    mock_parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "outputs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.action == "mock-report":
        output = _mock_report(args.output_root)
        print(f"Mock reports created: {output}")
        return 0

    if args.apply and not args.credentials_file:
        raise SystemExit("--credentials-file is required with --apply in the CLI.")
    logger = configure_logging(args.debug)
    try:
        output = run_job(
            inventory_file=args.inventory,
            commands_file=args.commands_file,
            commands_text="\n".join(args.commands or []),
            credentials_file=args.credentials_file,
            output_root=args.output_root,
            template_dir=TEMPLATE_DIR,
            apply=args.apply,
            max_devices=args.max_devices,
            max_workers=args.max_workers,
            result_handling=args.result_handling.replace("-", "_"),
            logger=logger,
        )
    except (FileNotFoundError, OSError, ValueError, RuntimeError) as exc:
        logger.error("Run stopped: %s", exc)
        return 2
    print(f"Reports created: {output}")
    return 0


def _mock_report(output_root: Path) -> Path:
    results = [
        CommandResult(
            inventory_row=2,
            hostname="LAB-SW-01",
            ip_address="192.0.2.10",
            detected_hostname="LAB-SW-01",
            device_type="switch",
            command_number=1,
            command="show version",
            status="success",
            started_at="2026-08-19T09:30:00+10:00",
            finished_at="2026-08-19T09:30:01+10:00",
            duration_seconds=1.124,
            message="Command completed successfully.",
            output=(
                "Cisco IOS XE Software, Version 17.12.04\n"
                "LAB-SW-01 uptime is 22 weeks, 3 days, 4 hours\n"
                "System image file is flash:packages.conf"
            ),
        ),
        CommandResult(
            inventory_row=2,
            hostname="LAB-SW-01",
            ip_address="192.0.2.10",
            detected_hostname="LAB-SW-01",
            device_type="switch",
            command_number=2,
            command="show interfaces status",
            status="success",
            started_at="2026-08-19T09:30:01+10:00",
            finished_at="2026-08-19T09:30:03+10:00",
            duration_seconds=1.638,
            message="Command completed successfully.",
            output=(
                "Port      Name               Status       Vlan       Duplex Speed Type\n"
                "Gi1/0/1   User-A             connected    120        a-full a-100 "
                "10/100/1000BaseTX\n"
                "Gi1/0/2                      notconnect   1          auto   auto 10/100/1000BaseTX"
            ),
        ),
        CommandResult(
            inventory_row=3,
            hostname="LAB-RTR-01",
            ip_address="192.0.2.11",
            detected_hostname="",
            device_type="edge_router",
            command_number=1,
            command="show version",
            status="failed",
            started_at="2026-08-19T09:30:00+10:00",
            finished_at="2026-08-19T09:30:00+10:00",
            duration_seconds=0.0,
            message="SSH connection failed: connection timed out.",
        ),
    ]
    report = build_report("mock", 2, 2, results, result_handling="common_summary")
    return write_reports(report, output_root, TEMPLATE_DIR)


if __name__ == "__main__":
    raise SystemExit(main())
