# Cisco Operational Command Runner

A dry-run-first Python application for running approved operational commands across Cisco switches and edge routers. It provides both a Windows desktop interface and a command-line interface, accepts CSV or XLSX inventories, and creates matching HTML, JSON, CSV, and raw-text reports.

The repository includes a complete offline demonstration using fictional devices and reserved documentation addresses. No network access or credentials are needed to inspect the workflow and sample reports.

This is an independent demonstration project. It is not affiliated with or endorsed by Cisco Systems.

## Features

- Imports device inventories from CSV or XLSX.
- Accepts commands from the GUI, repeated CLI arguments, TXT, CSV, or JSON profiles.
- Defaults to dry-run and requires an explicit apply choice before opening SSH connections.
- Permits `show`, `ping`, and `traceroute` operational commands.
- Rejects common configuration and destructive commands.
- Enforces a configurable device limit before execution.
- Uses bounded parallel processing for multi-device runs.
- Supports manual credentials in the GUI or a local ignored credential file.
- Keeps row-level successes and failures visible.
- Redacts common secret-bearing configuration lines from exported evidence.
- Groups multiple command rows under one device identity in HTML reports.
- Provides optional summaries for supported `show version` output.
- Generates short and standard HTML, summary and detail CSV, JSON, and raw text reports.

## Safety Model

Running without `--apply` validates the inventory and commands, creates planned report rows, and makes no SSH connection.

Live execution requires:

```text
--apply
```

The desktop interface presents a separate Apply checkbox and confirmation dialog. The initial release is intentionally limited to operational command prefixes. Configuration mode, reload, erase, delete, copy, shutdown, and similar commands are rejected.

Review command profiles and the dry-run report before live use. Start with a small device set and conservative worker count.

## Installation With uv

Python 3.11 or newer is recommended. The desktop interface also requires Tcl/Tk, which is included with standard Windows Python installations.

```powershell
uv sync
```

Start the desktop interface:

```powershell
uv run cisco-command-runner-gui
```

On Windows, `Launch_GUI.bat` synchronizes the environment and launches the interface.

## Offline Demo

Validate the fictional CSV inventory without contacting any device:

```powershell
uv run cisco-command-runner run `
  --inventory samples/inventory.csv `
  --commands-file samples/safe_commands.txt
```

Render populated example reports without credentials or network access:

```powershell
uv run cisco-command-runner mock-report
```

The fixtures use names such as `LAB-SW-01` and addresses from `192.0.2.0/24`, which is reserved for documentation.

Pre-generated examples are available in [`sample_reports`](sample_reports), including the [short HTML report](sample_reports/command_results_short.html) and [standard HTML report](sample_reports/command_results_standard.html).

## Inventory Format

CSV and XLSX inventories use the same columns:

| hostname | ip_address | device_type | enabled |
|---|---|---|---|
| LAB-SW-01 | 192.0.2.10 | switch | true |
| LAB-RTR-01 | 192.0.2.11 | edge_router | true |

Either `hostname` or `ip_address` is required. When both are supplied, the IP address is used as the SSH target and the hostname remains the requested report identity. Supported device types are `switch` and `edge_router`. Empty and disabled rows are ignored.

## Command Profiles

- TXT uses one command per line. Blank lines and lines beginning with `#` are ignored.
- CSV requires a `command` column.
- JSON accepts a list or an object containing a `commands` list.

Duplicate commands are removed while retaining their original order.

## Credentials

Copy `credentials/credentials.example.txt` to `credentials/credentials.txt` for local testing. The populated file is ignored by Git.

```text
username=lab_username
password=replace_locally
secret=replace_locally
port=22
timeout=30
```

Credentials are not written to reports or logs. Shared secrets should not be placed in inventories or command profiles.

## Live Lab Example

Run the dry-run first, review its reports, and then add the explicit apply option:

```powershell
uv run cisco-command-runner run `
  --inventory samples/inventory.xlsx `
  --commands-file samples/safe_commands.txt `
  --credentials-file credentials/credentials.txt `
  --max-devices 25 `
  --max-workers 3 `
  --result-handling common-summary `
  --apply
```

## Reports

Each run creates:

```text
command_results_short.html
command_results_standard.html
command_results.json
command_results_summary.csv
command_results_detail.csv
raw_outputs/
```

The Result column retains the output preview and expandable evidence. When common summaries are selected, the separate Summary column displays supported parsed fields without another expander. Full output remains available in every mode.

HTML tables group consecutive commands for each device and adjust column widths from their content. Wider tables use horizontal scrolling. Result and message fields wrap for readability.

## Project Layout

```text
credentials/                 Fictional credential-file example
samples/                     CSV, XLSX, TXT, and JSON examples
sample_reports/              Pre-generated offline report examples
src/cisco_command_runner/    Application source
templates/                   HTML report template
tests/                       Offline regression tests
```

## Validation

```powershell
uv run ruff format --check .
uv run ruff check .
uv run python -m compileall -q src tests
uv run pytest -q
uv run cisco-command-runner mock-report
```

## Security Notes

- Keep populated credential files, real inventories, logs, and generated operational reports out of source control.
- Use a least-privilege account appropriate for read-only operational collection.
- Review commands before Apply mode and start with a small worker count.
- Generated reports can contain hostnames, addresses, software versions, configurations, and topology details. Review every report before sharing.
- The included examples contain fictional names and reserved documentation addresses only.

## License

MIT. See [LICENSE](LICENSE).
