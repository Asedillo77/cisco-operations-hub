"""Command-line entry point for standalone troubleshooting."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .credentials import load_credentials, load_solarwinds_credentials
from .engine import investigate_device
from .inventory import devices_for_site, load_inventory, sites_from_inventory, target_from_mapping
from .reporting import build_report, write_reports
from .solarwinds import SolarWindsAlertClient, SolarWindsError, UnavailableSolarWindsCollector


def parse_args() -> argparse.Namespace:
    """Parse standalone command-line options."""
    parser = argparse.ArgumentParser(description="Generate a plain-language network connectivity evidence report.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--inventory", type=Path, help="JSON inventory containing site edge routers")
    target.add_argument("--host", help="Single device IP address or hostname")
    parser.add_argument("--site", help="Site to select from inventory, or label for a manual host")
    parser.add_argument("--name", help="Display name for a manual device")
    parser.add_argument(
        "--transport",
        choices=["cellular", "satellite", "fixed", "fixed_cellular_backup", "unknown"],
        default="unknown",
    )
    parser.add_argument(
        "--site-type",
        choices=["mobile_unit", "portable_unit", "dual_edge_hub", "data_centre", "branch", "warehouse", "other"],
        default="other",
    )
    parser.add_argument("--platform", default="cisco_xe")
    parser.add_argument("--edge-role", choices=["single", "primary", "secondary"], default="single")
    parser.add_argument("--service-vrf", action="append", dest="service_vrfs")
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--solarwinds-alerts", action="store_true", help="Include active SolarWinds alerts")
    parser.add_argument("--solarwinds-credentials-file", type=Path)
    parser.add_argument("--report-dir", type=Path, default=Path("reports"))
    parser.add_argument("--ping-count", type=int, default=15)
    parser.add_argument("--ping-timeout", type=int, default=2)
    parser.add_argument("--apply", action="store_true", help="Perform live ping and read-only SSH collection")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Run a dry-run by default and require --apply for live collection."""
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logger = logging.getLogger("site_connectivity")
    if args.inventory:
        targets = load_inventory(args.inventory)
        sites = sites_from_inventory(targets)
        if not args.site:
            raise SystemExit(f"--site is required with --inventory. Available sites: {', '.join(sites)}")
        targets = devices_for_site(targets, args.site)
        if not targets:
            raise SystemExit(f"No devices found for site: {args.site}")
        site = args.site
    else:
        site = args.site or "Ad hoc"
        targets = [
            target_from_mapping(
                {
                    "name": args.name or args.host,
                    "host": args.host,
                    "site": site,
                    "platform": args.platform,
                    "transport": args.transport,
                    "site_type": args.site_type,
                    "edge_role": args.edge_role,
                    "service_vrfs": args.service_vrfs or ["10"],
                }
            )
        ]
    credentials = load_credentials(args.credentials_file) if args.credentials_file else None
    if args.apply and credentials is None:
        raise SystemExit("--credentials-file is required with --apply.")
    if args.apply and args.solarwinds_alerts and args.solarwinds_credentials_file is None:
        raise SystemExit("--solarwinds-credentials-file is required for live SolarWinds alert checks.")

    solarwinds_collector = None
    if args.apply and args.solarwinds_alerts:
        try:
            solarwinds_credentials = load_solarwinds_credentials(args.solarwinds_credentials_file)
            solarwinds_collector = SolarWindsAlertClient(solarwinds_credentials, logger)
        except (OSError, ValueError, SolarWindsError) as exc:
            logger.error("SolarWinds alert checks are unavailable: %s", exc)
            solarwinds_collector = UnavailableSolarWindsCollector(str(exc))
    results = [
        investigate_device(
            target,
            credentials,
            apply=args.apply,
            ping_count=args.ping_count,
            ping_timeout=args.ping_timeout,
            logger=logger,
            solarwinds_collector=solarwinds_collector,
            solarwinds_requested=args.solarwinds_alerts,
        )
        for target in targets
    ]
    html_path, json_path = write_reports(build_report(site, results, dry_run=not args.apply), args.report_dir)
    logger.info("HTML report: %s", html_path.resolve())
    logger.info("JSON report: %s", json_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
