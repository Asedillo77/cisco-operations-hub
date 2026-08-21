from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from network_prepost_check.compare import compare_parsed_outputs  # noqa: E402
from network_prepost_check.config_loader import load_command_config  # noqa: E402
from network_prepost_check.diff_builder import build_command_diffs  # noqa: E402
from network_prepost_check.output_store import load_json_file  # noqa: E402
from network_prepost_check.parsers import parse_outputs  # noqa: E402
from network_prepost_check.report_builder import build_report_data, write_reports  # noqa: E402


def main() -> int:
    samples_dir = PROJECT_ROOT / "samples"
    precheck_file = samples_dir / "mock_switch_precheck_raw.json"
    postcheck_file = samples_dir / "mock_switch_postcheck_raw.json"
    template_file = PROJECT_ROOT / "reports" / "prepost_report.html.j2"
    output_dir = PROJECT_ROOT / "sample_reports"

    precheck_raw = load_json_file(precheck_file)
    postcheck_raw = load_json_file(postcheck_file)
    config = load_command_config(PROJECT_ROOT / "configs" / "switch_commands.json")
    results = compare_parsed_outputs(
        parse_outputs(precheck_raw),
        parse_outputs(postcheck_raw),
        config,
    )
    report = build_report_data(
        hostname="LABSW001",
        connection_target="192.0.2.10",
        device_type="switch",
        comparison_results=results,
        precheck_file=Path("samples/mock_switch_precheck_raw.json"),
        postcheck_file=Path("samples/mock_switch_postcheck_raw.json"),
        delay_minutes=50,
        diff_details=build_command_diffs(precheck_raw, postcheck_raw),
    )
    report["report_generated_at"] = "2026-08-14 10:00:00 AEST"
    paths = write_reports(report, output_dir, template_file)
    print("Generated sample reports:")
    for path in paths.values():
        print(f"- {path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
