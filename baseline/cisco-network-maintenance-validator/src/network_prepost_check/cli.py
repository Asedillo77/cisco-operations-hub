from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .compare import compare_parsed_outputs
from .config_loader import load_command_config
from .credentials import load_local_credentials
from .device_detection import default_config_name, resolve_device_type
from .diff_builder import build_command_diffs
from .inventory import DeviceTarget, load_inventory
from .logging_utils import build_logger
from .netmiko_runner import run_commands
from .output_store import (
    build_run_folder_name,
    find_latest_parsed_output,
    load_json_file,
    load_saved_command_outputs,
    local_timestamp,
    save_check_outputs,
    update_precheck_index,
)
from .parsers import parse_outputs
from .paths import PROJECT_ROOT
from .report_builder import build_report_data, write_reports


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    debug = args.debug or getattr(args, "sub_debug", False)
    logger = build_logger(debug)

    try:
        if args.command == "mock-report":
            return run_mock_report(args, logger)
        if args.command == "precheck":
            return run_precheck(args, logger)
        if args.command == "postcheck":
            return run_postcheck(args, logger)
    except Exception as exc:
        logger.error("%s", exc)
        if debug:
            logger.exception("Debug traceback")
        return 1

    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect and compare network device precheck/postcheck data."
    )
    parser.add_argument("--debug", action="store_true", help="Enable detailed logging.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    add_check_parser(subparsers, "precheck")
    add_check_parser(subparsers, "postcheck")

    mock_parser = subparsers.add_parser(
        "mock-report", help="Render a sample report from mock data."
    )
    mock_parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "outputs",
        help="Folder where mock reports are written.",
    )
    mock_parser.add_argument(
        "--template-file",
        type=Path,
        default=PROJECT_ROOT / "reports" / "prepost_report.html.j2",
        help="Jinja HTML report template.",
    )
    mock_parser.add_argument(
        "--debug", dest="sub_debug", action="store_true", help=argparse.SUPPRESS
    )
    return parser


def add_check_parser(subparsers: argparse._SubParsersAction, name: str) -> None:
    check_parser = subparsers.add_parser(name, help=f"Run a {name}.")
    check_parser.add_argument("--hostname", help="Single device hostname or IP address.")
    check_parser.add_argument(
        "--inventory-file",
        type=Path,
        help="CSV or JSON device inventory for multi-device execution.",
    )
    check_parser.add_argument(
        "--device-type",
        choices=["auto", "switch", "edge_router"],
        default="auto",
        help="Device type. Auto uses hostname naming safeguards.",
    )
    check_parser.add_argument(
        "--credentials-file",
        type=Path,
        required=True,
        help="Local credential text file for standalone testing.",
    )
    check_parser.add_argument("--commands-file", type=Path, help="JSON command config file.")
    check_parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "outputs",
        help="Root folder for captured outputs and reports.",
    )
    check_parser.add_argument(
        "--template-file",
        type=Path,
        default=PROJECT_ROOT / "reports" / "prepost_report.html.j2",
        help="Jinja HTML report template.",
    )
    check_parser.add_argument(
        "--apply",
        action="store_true",
        help="Connect to the device and run commands. Without this, only validation is performed.",
    )
    check_parser.add_argument(
        "--max-workers",
        type=int,
        default=5,
        help="Maximum number of devices processed in parallel for inventory runs.",
    )
    check_parser.add_argument(
        "--max-devices",
        type=int,
        default=50,
        help="Safety limit for inventory device count.",
    )
    check_parser.add_argument(
        "--debug", dest="sub_debug", action="store_true", help=argparse.SUPPRESS
    )

    if name == "postcheck":
        check_parser.add_argument(
            "--baseline-file",
            type=Path,
            help="Precheck parsed_outputs.json. Defaults to the latest saved precheck.",
        )
        check_parser.add_argument(
            "--delay-minutes",
            type=int,
            default=50,
            help="Recommended stabilization delay recorded in the report.",
        )
        check_parser.add_argument(
            "--wait",
            action="store_true",
            help="Wait for --delay-minutes before collecting postcheck output.",
        )


def run_precheck(
    args: argparse.Namespace,
    logger,
    credentials: dict[str, str | int] | None = None,
) -> int:
    targets = load_targets(args)
    if credentials is None:
        credentials = load_local_credentials(args.credentials_file)
        logger.info("Validated credential file.")
    else:
        logger.info("Validated manually entered credentials.")
    plans = [build_target_plan(args, target) for target in targets]
    log_plans(plans, logger)

    if not args.apply:
        logger.info("Dry-run complete. Add --apply to connect and collect precheck output.")
        return 0

    results = run_plans_in_parallel(
        plans,
        args.max_workers,
        lambda plan: run_precheck_plan(plan, args, credentials, logger),
    )
    return summarize_batch_results(results, logger)


def run_postcheck(
    args: argparse.Namespace,
    logger,
    credentials: dict[str, str | int] | None = None,
) -> int:
    targets = load_targets(args)
    if args.inventory_file and args.baseline_file:
        raise ValueError("--baseline-file can only be used with a single --hostname run.")

    if credentials is None:
        credentials = load_local_credentials(args.credentials_file)
        logger.info("Validated credential file.")
    else:
        logger.info("Validated manually entered credentials.")
    plans = [build_target_plan(args, target) for target in targets]
    log_plans(plans, logger)

    if not args.apply:
        logger.info(
            "Dry-run complete. Add --apply to connect, collect postcheck output, and compare."
        )
        return 0

    if args.wait and args.delay_minutes > 0:
        wait_seconds = args.delay_minutes * 60
        logger.info("Waiting %s minute(s) before postcheck collection.", args.delay_minutes)
        time.sleep(wait_seconds)

    results = run_plans_in_parallel(
        plans,
        args.max_workers,
        lambda plan: run_postcheck_plan(plan, args, credentials, logger),
    )
    return summarize_batch_results(results, logger)


def run_precheck_plan(
    plan: dict,
    args: argparse.Namespace,
    credentials: dict,
    logger,
) -> dict:
    target = plan["target"]
    device_type = plan["device_type"]
    config = plan["config"]
    raw_outputs = run_commands(
        target.connection_target,
        config["commands"],
        credentials,
        config["netmiko_device_type"],
        logger,
    )
    parsed_outputs = parse_outputs(raw_outputs.raw_outputs)
    display_hostname = _display_hostname(
        target.connection_target, raw_outputs.detected_hostname, parsed_outputs
    )
    run_folder_name = build_run_folder_name(display_hostname, "pre")
    metadata = {
        "connection_target": target.connection_target,
        "hostname": display_hostname,
        "run_folder": run_folder_name,
        "device_type": device_type,
        "check_type": "precheck",
        "command_count": len(config["commands"]),
        "timestamp": local_timestamp(),
    }
    saved = save_check_outputs(
        args.output_root,
        run_folder_name,
        "precheck",
        raw_outputs.raw_outputs,
        parsed_outputs,
        metadata,
    )
    update_precheck_index(
        args.output_root,
        target.connection_target,
        display_hostname,
        saved["parsed_outputs"],
    )
    logger.info("Precheck saved for %s to %s", target.connection_target, saved["base_dir"])
    return {
        "target": target.connection_target,
        "status": "success",
        "message": str(saved["base_dir"]),
    }


def run_postcheck_plan(
    plan: dict,
    args: argparse.Namespace,
    credentials: dict,
    logger,
) -> dict:
    target = plan["target"]
    device_type = plan["device_type"]
    config = plan["config"]
    baseline_file = args.baseline_file or find_latest_parsed_output(
        args.output_root,
        target.connection_target,
        "precheck",
    )
    logger.info("Using baseline file for %s: %s", target.connection_target, baseline_file)

    raw_outputs = run_commands(
        target.connection_target,
        config["commands"],
        credentials,
        config["netmiko_device_type"],
        logger,
    )
    parsed_outputs = parse_outputs(raw_outputs.raw_outputs)
    display_hostname = _display_hostname(
        target.connection_target, raw_outputs.detected_hostname, parsed_outputs
    )
    run_folder_name = build_run_folder_name(display_hostname, "post")
    metadata = {
        "connection_target": target.connection_target,
        "hostname": display_hostname,
        "run_folder": run_folder_name,
        "device_type": device_type,
        "check_type": "postcheck",
        "command_count": len(config["commands"]),
        "delay_minutes": args.delay_minutes,
        "timestamp": local_timestamp(),
    }
    saved = save_check_outputs(
        args.output_root,
        run_folder_name,
        "postcheck",
        raw_outputs.raw_outputs,
        parsed_outputs,
        metadata,
    )
    precheck_outputs = load_json_file(baseline_file)
    comparison_results = compare_parsed_outputs(precheck_outputs, parsed_outputs, config)
    precheck_raw_outputs = load_saved_command_outputs(
        baseline_file,
        list(set(precheck_outputs) | set(parsed_outputs)),
    )
    diff_details = (
        build_command_diffs(precheck_raw_outputs, raw_outputs.raw_outputs)
        if precheck_raw_outputs
        else []
    )
    report_data = build_report_data(
        display_hostname,
        target.connection_target,
        device_type,
        comparison_results,
        baseline_file,
        saved["parsed_outputs"],
        args.delay_minutes,
        diff_details,
    )
    report_paths = write_reports(
        report_data,
        saved["run_folder"] / "reports",
        args.template_file,
    )
    logger.info("Postcheck saved for %s to %s", target.connection_target, saved["base_dir"])
    logger.info(
        "Reports saved for %s: %s",
        target.connection_target,
        ", ".join(str(path) for path in report_paths.values()),
    )
    return {
        "target": target.connection_target,
        "status": "success",
        "message": str(report_paths["html"]),
    }


def run_mock_report(args: argparse.Namespace, logger) -> int:
    precheck_file = PROJECT_ROOT / "samples" / "mock_switch_precheck_raw.json"
    postcheck_file = PROJECT_ROOT / "samples" / "mock_switch_postcheck_raw.json"
    config = load_command_config(PROJECT_ROOT / "configs" / "switch_commands.json")
    precheck_raw = load_json_file(precheck_file)
    postcheck_raw = load_json_file(postcheck_file)
    precheck_outputs = parse_outputs(precheck_raw)
    postcheck_outputs = parse_outputs(postcheck_raw)
    comparison_results = compare_parsed_outputs(precheck_outputs, postcheck_outputs, config)
    diff_details = build_command_diffs(precheck_raw, postcheck_raw)
    report_data = build_report_data(
        "LABSW001",
        "192.0.2.10",
        "switch",
        comparison_results,
        precheck_file,
        postcheck_file,
        delay_minutes=50,
        diff_details=diff_details,
    )
    run_folder_name = build_run_folder_name("LABSW001", "post")
    report_paths = write_reports(
        report_data,
        args.output_root / run_folder_name / "reports",
        args.template_file,
    )
    logger.info("Mock reports saved: %s", ", ".join(str(path) for path in report_paths.values()))
    return 0


def load_targets(args: argparse.Namespace) -> list[DeviceTarget]:
    if args.inventory_file and args.hostname:
        raise ValueError("Use either --hostname or --inventory-file, not both.")
    if args.inventory_file:
        targets = load_inventory(args.inventory_file)
    elif args.hostname:
        device_type = args.device_type if args.device_type != "auto" else None
        targets = [
            DeviceTarget(
                connection_target=args.hostname,
                device_type=device_type,
                commands_file=args.commands_file,
            )
        ]
    else:
        raise ValueError("Provide either --hostname or --inventory-file.")

    if len(targets) > args.max_devices:
        raise ValueError(
            f"Inventory has {len(targets)} device(s), above --max-devices {args.max_devices}."
        )
    return targets


def build_target_plan(args: argparse.Namespace, target: DeviceTarget) -> dict:
    requested_device_type = target.device_type or args.device_type
    device_type = resolve_device_type(target.connection_target, requested_device_type)
    commands_file = target.commands_file or args.commands_file
    if commands_file is None:
        commands_file = PROJECT_ROOT / "configs" / default_config_name(device_type)
    config = load_command_config(commands_file)
    return {"target": target, "device_type": device_type, "config": config}


def run_plans_in_parallel(plans: list[dict], max_workers: int, worker) -> list[dict]:
    if max_workers < 1:
        raise ValueError("--max-workers must be 1 or higher.")

    worker_count = min(max_workers, len(plans))
    results = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(worker, plan): plan for plan in plans}
        for future in as_completed(futures):
            plan = futures[future]
            target = plan["target"].connection_target
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"target": target, "status": "failed", "message": str(exc)})
    return results


def summarize_batch_results(results: list[dict], logger) -> int:
    success_count = sum(1 for result in results if result["status"] == "success")
    failed = [result for result in results if result["status"] != "success"]
    logger.info("Batch complete. Successful: %s. Failed: %s.", success_count, len(failed))
    for result in sorted(results, key=lambda item: item["target"]):
        logger.info("%s | %s | %s", result["target"], result["status"], result["message"])
    return 1 if failed else 0


def log_plans(plans: list[dict], logger) -> None:
    logger.info("Device count: %s", len(plans))
    for plan in plans:
        target = plan["target"]
        logger.info(
            "Validated %s as %s with %s command(s).",
            target.connection_target,
            plan["device_type"],
            len(plan["config"]["commands"]),
        )
        _log_command_plan(plan["config"]["commands"], logger)


def _log_command_plan(commands: list[str], logger) -> None:
    logger.info("Command count: %s", len(commands))
    for index, command in enumerate(commands, start=1):
        logger.debug("Planned command %s: %s", index, command)


def _display_hostname(
    connection_target: str,
    prompt_hostname: str | None,
    parsed_outputs: dict,
) -> str:
    version_hostname = (parsed_outputs.get("show version") or {}).get("device_hostname")
    return version_hostname or prompt_hostname or connection_target


if __name__ == "__main__":
    sys.exit(main())
