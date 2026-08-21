# Cisco Network Maintenance Validator

A read-only Python tool for collecting Cisco IOS XE prechecks and postchecks, comparing operational state, and producing HTML, JSON, and text evidence for maintenance review.

The project supports Catalyst switches and Catalyst SD-WAN edge routers. It includes a complete offline demonstration, so the parsing, comparison, and reporting workflow can be reviewed without network access or credentials.

This is an independent demonstration project. It is not affiliated with or endorsed by Cisco.

## Highlights

- Dry-run is the default; device connections require an explicit `--apply`.
- Accepts one device or a CSV/JSON inventory with controlled parallel processing.
- Saves raw command output and structured parsed data for both checks.
- Compares identities and operational state rather than relying only on line counts.
- Classifies findings as `OK`, `EXPECTED`, `WARNING`, or `CRITICAL`.
- Preserves exact added and removed command lines beneath the summary.
- Redacts common Cisco configuration secret and password lines from report differences.
- Provides a Tkinter desktop interface and a Windows launcher.

## Comparison Coverage

Switch checks include stack membership, software state, interfaces, VLANs, EtherChannels, OSPF, routing tables, power, environmental state, inventory, access sessions, device tracking, ARP, MAC tables, and CDP/LLDP neighbors.

Edge-router checks include interface state, VRF-aware OSPF context, OSPF adjacency state, Catalyst SD-WAN control connections, the global underlay routing table, and the VRF 2 service routing table.

Command profiles and percentage-drop thresholds are stored in `configs/` so they can be reviewed and adjusted without changing Python code.

## Offline Demo

Python 3.10 or newer is required.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:PYTHONPATH = "src"
python -m network_prepost_check.cli mock-report --output-root sample_reports
```

For deterministic portfolio samples:

```powershell
python scripts\generate_sample_report.py
```

The examples use fictional device names, locally administered MAC addresses, and addresses reserved for documentation.

## Dry-Run Validation

Create a private credential file from `credentials/credentials.example.txt`. The populated file is ignored by Git.

```powershell
$env:PYTHONPATH = "src"
python -m network_prepost_check.cli precheck `
  --hostname 192.0.2.10 `
  --device-type switch `
  --credentials-file credentials\credentials.txt
```

This validates credentials, target selection, command configuration, and safety limits without connecting to the device.

## Live Read-Only Collection

Collect a precheck after the dry-run has been reviewed:

```powershell
python -m network_prepost_check.cli precheck `
  --hostname 192.0.2.10 `
  --device-type switch `
  --credentials-file credentials\credentials.txt `
  --apply
```

Run the postcheck after the maintenance stabilisation period:

```powershell
python -m network_prepost_check.cli postcheck `
  --hostname 192.0.2.10 `
  --device-type switch `
  --credentials-file credentials\credentials.txt `
  --delay-minutes 50 `
  --apply
```

The postcheck locates the latest matching baseline automatically. Output folders identify the device, run type, and local timestamp:

```text
LABSW001_PRE_140826_090000/
LABSW001_POST_140826_100000/
```

Use `samples/inventory.csv` or `samples/inventory.json` with `--inventory-file` for multi-device runs. `--max-workers` controls concurrency and `--max-devices` limits inventory size.

## Desktop Interface

On Windows, double-click `Launch_GUI.bat`. It creates a local `.venv`, reuses compatible packages already installed on the computer, installs missing requirements, and opens the interface. A copied or broken virtual environment is rebuilt against the current computer's Python installation.

Do not copy `.venv` between computers; virtual environments contain machine-specific paths.

## Project Layout

```text
configs/                         Switch and edge-router command profiles
credentials/                     Example local credential format
reports/                         Jinja HTML template
samples/                         Fictional inventory and command captures
sample_reports/                  Pre-generated fictional reports
scripts/generate_sample_report.py
src/network_prepost_check/       Collection, parsing, comparison, storage, CLI, and GUI
tests/                           Offline parser and comparison tests
```

## Validation

```powershell
python -m compileall -q src tests scripts
ruff format --check .
ruff check --no-cache .
python -m unittest discover -s tests -v
python scripts\generate_sample_report.py
```

## Security

- Use an authorised read-only account and test against a controlled lab first.
- Keep populated credentials, production inventories, raw captures, logs, and generated operational reports out of source control.
- Review reports before sharing because command output can expose addresses, names, routes, serial numbers, and topology.
- The tool runs show commands only and does not modify configuration.
- See [SECURITY.md](SECURITY.md) for public-repository handling guidance.

## License

MIT. See [LICENSE](LICENSE).
