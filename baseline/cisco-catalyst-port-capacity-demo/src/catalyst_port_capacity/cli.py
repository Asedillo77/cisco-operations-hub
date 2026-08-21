"""Command-line entry point for the port capacity audit."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .audit import run_audit
from .client import CatalystCenterClient
from .config import load_credentials
from .mock import MockCatalystCenterClient
from .reporting import write_reports


def build_parser() -> argparse.ArgumentParser:
    """Build the public command-line interface."""
    parser = argparse.ArgumentParser(description="Audit physical Cisco switchport capacity.")
    parser.add_argument("--targets", nargs="+", required=True, help="Management IP addresses or Catalyst device IDs")
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--mock-data", type=Path, help="Use an offline Catalyst fixture")
    parser.add_argument("--collect", action="store_true", help="Collect interface data; otherwise run validation only")
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--no-verify", action="store_true", help="Disable TLS verification for lab testing")
    parser.add_argument("--debug", action="store_true")
    return parser


def main() -> int:
    """Run the audit and return a process exit code."""
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    if args.mock_data:
        client = MockCatalystCenterClient(args.mock_data)
    else:
        credentials = load_credentials(args.credentials_file)
        client = CatalystCenterClient(
            credentials.base_url,
            credentials.username,
            credentials.password,
            verify=not args.no_verify,
        )
    report = run_audit(client, args.targets, dry_run=not args.collect)
    paths = write_reports(report, args.output_dir)
    for path in paths:
        logging.info("Created %s", path)
    return 1 if report.to_dict()["counts"]["failed_devices"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
