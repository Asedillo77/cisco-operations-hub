from __future__ import annotations

import argparse
from pathlib import Path

from .analysis import analyse
from .loaders import load_profiles
from .logging_utils import configure_logging
from .models import Device, Result
from .reporting import build_report, publish
from .service import run_monitor

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a point-in-time Cisco health report.")
    subparsers = parser.add_subparsers(dest="action", required=True)
    run_parser = subparsers.add_parser("run", help="Validate or collect device health.")
    run_parser.add_argument("--inventory", type=Path, required=True)
    run_parser.add_argument("--config-dir", type=Path, default=PROJECT_ROOT / "configs")
    run_parser.add_argument("--credentials-file", type=Path)
    run_parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "outputs")
    run_parser.add_argument("--max-devices", type=int, default=50)
    run_parser.add_argument("--max-workers", type=int, default=3)
    run_parser.add_argument("--apply", action="store_true")
    run_parser.add_argument("--debug", action="store_true")
    mock_parser = subparsers.add_parser("mock-report", help="Render a reviewable sample report.")
    mock_parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "outputs")
    mock_parser.add_argument("--debug", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = configure_logging(args.debug)
    try:
        if args.action == "mock-report":
            output = _mock_report(args.output_root)
        else:
            output = run_monitor(
                inventory_file=args.inventory,
                config_dir=args.config_dir,
                output_root=args.output_root,
                template_dir=PROJECT_ROOT / "templates",
                apply=args.apply,
                credentials_file=args.credentials_file,
                max_devices=args.max_devices,
                max_workers=args.max_workers,
                logger=logger,
            )
    except (FileNotFoundError, OSError, ValueError, RuntimeError) as exc:
        logger.error("Run stopped: %s", exc)
        return 2
    print(f"Report created: {output}")
    return 0


def _mock_report(output_root: Path) -> Path:
    profiles = load_profiles(PROJECT_ROOT / "configs")
    fixtures = [
        (
            Device("LAB-SW-01", "192.0.2.10", "switch", 2),
            "show platform resources",
            (
                "Resource Usage Max Warning Critical State\n"
                "Control Processor 91% 100% 90% 95% W\n"
                "DRAM 3671MB(48%) 7564MB 85% 90% H"
            ),
        ),
        (
            Device("LAB-SW-01", "192.0.2.10", "switch", 2),
            "show environment all",
            "FAN 1 is OK\nPower Supply 1 is OK\nTEMPERATURE is OK",
        ),
        (
            Device("LAB-ER-01", "192.0.2.11", "edge_router", 3),
            "show ip ospf neighbor",
            (
                "Neighbor ID Pri State Dead Time Address Interface\n"
                "198.51.100.1 1 FULL/DR 00:00:32 192.0.2.1 Gi0/0"
            ),
        ),
        (
            Device("LAB-ER-01", "192.0.2.11", "edge_router", 3),
            "show sdwan control connections",
            "peer-type protocol state\nvsmart dtls up\nvmanage tls down",
        ),
    ]
    results: list[Result] = []
    for number, (device, command, output) in enumerate(fixtures, start=1):
        status, message, metrics = analyse(command, output, profiles[device.device_type])
        results.append(
            Result(
                hostname=device.hostname,
                ip_address=device.ip_address,
                device_type=device.device_type,
                inventory_row=device.row_number,
                command_number=number,
                command=command,
                collection_status="success",
                health_status=status,
                message=message,
                output=output,
                metrics=metrics,
                started_at="2026-08-20T09:00:00+10:00",
                finished_at="2026-08-20T09:00:01+10:00",
                duration_seconds=1.0,
            )
        )
    return publish(build_report("mock", 2, results), output_root, PROJECT_ROOT / "templates")


if __name__ == "__main__":
    raise SystemExit(main())
