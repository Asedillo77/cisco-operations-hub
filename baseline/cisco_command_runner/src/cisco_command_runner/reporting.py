from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import CommandResult, RunReport
from .result_summaries import summarize_result

SECRET_PATTERNS = (
    re.compile(r"(?im)^(\s*(?:username\s+\S+\s+(?:password|secret)|enable\s+secret)\s+).+$"),
    re.compile(r"(?im)^(\s*(?:snmp-server community|key-string)\s+)\S+.*$"),
)


def build_report(
    mode: str,
    devices: int,
    commands: int,
    results: list[CommandResult],
    result_handling: str = "complete",
) -> RunReport:
    if result_handling not in {"complete", "common_summary"}:
        raise ValueError(f"Unsupported result handling mode: {result_handling}")
    now = datetime.now().astimezone()
    prepared_results = [
        _prepare_result(result, result_handling=result_handling) for result in results
    ]
    return RunReport(
        run_id=now.strftime("%Y%m%d_%H%M%S_%f"),
        mode=mode,
        generated_at=now.isoformat(timespec="seconds"),
        requested_devices=devices,
        requested_commands=commands,
        result_handling=result_handling,
        results=prepared_results,
    )


def write_reports(report: RunReport, output_root: Path, template_dir: Path) -> Path:
    run_dir = output_root / f"command_run_{report.run_id}"
    raw_dir = run_dir / "raw_outputs"
    raw_dir.mkdir(parents=True, exist_ok=False)

    environment = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.get_template("command_report.html.j2")
    result_groups = _group_results(report.results)
    for view in ("short", "standard"):
        html = template.render(
            report=report,
            result_groups=result_groups,
            view=view,
            preview=_preview,
        )
        (run_dir / f"command_results_{view}.html").write_text(html, encoding="utf-8")

    (run_dir / "command_results.json").write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_csv(run_dir / "command_results_summary.csv", report.results, detail=False)
    _write_csv(run_dir / "command_results_detail.csv", report.results, detail=True)
    _write_raw_outputs(raw_dir, report.results)
    return run_dir


def _write_csv(path: Path, results: list[CommandResult], detail: bool) -> None:
    common = ["hostname", "ip_address", "command", "status"]
    fields = common + (["output"] if detail else ["result_preview", "message"])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            row = {name: getattr(result, name) for name in common}
            if detail:
                row["output"] = result.output
            else:
                row["result_preview"] = result.result_summary or _preview(result.output)
                row["message"] = result.message
            writer.writerow(row)


def _write_raw_outputs(raw_dir: Path, results: list[CommandResult]) -> None:
    for result in results:
        if not result.output:
            continue
        device_dir = raw_dir / _safe_name(result.detected_hostname or result.hostname)
        device_dir.mkdir(exist_ok=True)
        command_name = _safe_name(result.command)[:60]
        filename = f"{result.command_number:03d}_{command_name}.txt"
        (device_dir / filename).write_text(result.output, encoding="utf-8")


def _prepare_result(result: CommandResult, result_handling: str) -> CommandResult:
    values = result.to_dict()
    output = values["output"]
    for pattern in SECRET_PATTERNS:
        output = pattern.sub(r"\1<redacted>", output)
    values["output"] = output
    if result_handling == "common_summary":
        summary, fields = summarize_result(result.command, output)
        values["result_summary"] = summary
        values["extracted_fields"] = fields
    return CommandResult(**values)


def _preview(output: str, limit: int = 120) -> str:
    compact = " ".join(output.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "device"


def _group_results(results: list[CommandResult]) -> list[list[CommandResult]]:
    groups: list[list[CommandResult]] = []
    previous_key: tuple[int, str, str] | None = None
    for result in results:
        key = (result.inventory_row, result.hostname, result.ip_address)
        if key != previous_key:
            groups.append([])
            previous_key = key
        groups[-1].append(result)
    return groups
