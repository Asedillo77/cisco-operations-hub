from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

INDEX_FILE_NAME = ".prepost_index.json"
_INDEX_LOCK = Lock()


def local_timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")


def local_folder_timestamp() -> str:
    return datetime.now().astimezone().strftime("%d%m%y_%H%M%S")


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("_") or "output"


def build_run_folder_name(
    hostname: str,
    check_type: str,
    timestamp: str | None = None,
) -> str:
    label = safe_name(check_type).upper()
    return f"{safe_name(hostname)}_{label}_{timestamp or local_folder_timestamp()}"


def save_check_outputs(
    output_root: Path,
    run_folder_name: str,
    check_type: str,
    raw_outputs: dict[str, str],
    parsed_outputs: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Path]:
    base_dir = output_root / run_folder_name / check_type
    base_dir.mkdir(parents=True, exist_ok=True)

    raw_combined = base_dir / "raw_outputs.txt"
    with raw_combined.open("w", encoding="utf-8") as file_handle:
        for command, output in raw_outputs.items():
            file_handle.write(f"\n{'=' * 80}\n")
            file_handle.write(f"COMMAND: {command}\n")
            file_handle.write(f"{'=' * 80}\n")
            file_handle.write(output.rstrip())
            file_handle.write("\n")

    command_dir = base_dir / "commands"
    command_dir.mkdir(exist_ok=True)
    for command, output in raw_outputs.items():
        command_file = command_dir / f"{safe_name(command)}.txt"
        command_file.write_text(output.rstrip() + "\n", encoding="utf-8")

    parsed_file = base_dir / "parsed_outputs.json"
    parsed_file.write_text(
        json.dumps(parsed_outputs, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    metadata_file = base_dir / "metadata.json"
    metadata_file.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "run_folder": output_root / run_folder_name,
        "base_dir": base_dir,
        "raw_outputs": raw_combined,
        "parsed_outputs": parsed_file,
        "metadata": metadata_file,
    }


def update_precheck_index(
    output_root: Path,
    connection_target: str,
    hostname: str,
    parsed_file: Path,
) -> None:
    with _INDEX_LOCK:
        index = _load_index(output_root)
        index.setdefault("connection_targets", {})[connection_target] = str(parsed_file.resolve())
        index.setdefault("hostnames", {})[hostname] = str(parsed_file.resolve())
        _write_index(output_root, index)


def find_latest_parsed_output(output_root: Path, hostname: str, check_type: str) -> Path:
    indexed_file = _find_indexed_parsed_output(output_root, hostname, check_type)
    if indexed_file:
        return indexed_file

    parsed_files = sorted(
        output_root.glob(f"*/{check_type}/parsed_outputs.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    matching_files = [
        parsed_file
        for parsed_file in parsed_files
        if _metadata_matches(parsed_file.parent / "metadata.json", hostname)
    ]
    if matching_files:
        return matching_files[0]

    legacy_check_dir = output_root / hostname / check_type
    legacy_files = sorted(legacy_check_dir.glob("*/parsed_outputs.json"), reverse=True)
    if legacy_files:
        return legacy_files[0]

    if parsed_files:
        raise FileNotFoundError(f"Parsed {check_type} outputs exist, but none matched {hostname}.")
    raise FileNotFoundError(f"No parsed {check_type} outputs were found for {hostname}.")


def _find_indexed_parsed_output(output_root: Path, hostname: str, check_type: str) -> Path | None:
    if check_type != "precheck":
        return None

    index = _load_index(output_root)
    indexed_path = index.get("connection_targets", {}).get(hostname) or index.get(
        "hostnames", {}
    ).get(hostname)
    if not indexed_path:
        return None

    parsed_file = Path(indexed_path)
    if parsed_file.exists():
        return parsed_file
    return None


def _metadata_matches(metadata_file: Path, connection_target: str) -> bool:
    if not metadata_file.exists():
        return False
    metadata = load_json_file(metadata_file)
    return connection_target in {
        metadata.get("connection_target"),
        metadata.get("hostname"),
    }


def _load_index(output_root: Path) -> dict[str, Any]:
    index_file = output_root / INDEX_FILE_NAME
    if not index_file.exists():
        return {"connection_targets": {}, "hostnames": {}}
    return load_json_file(index_file)


def _write_index(output_root: Path, index: dict[str, Any]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    index_file = output_root / INDEX_FILE_NAME
    index_file.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")


def load_json_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def load_saved_command_outputs(
    parsed_file: Path,
    commands: list[str],
) -> dict[str, str]:
    command_dir = parsed_file.parent / "commands"
    outputs = {}
    for command in commands:
        command_file = command_dir / f"{safe_name(command)}.txt"
        if command_file.exists():
            outputs[command] = command_file.read_text(encoding="utf-8")
    return outputs
