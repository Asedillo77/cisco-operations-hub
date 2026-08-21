# Cisco Catalyst Port Capacity Auditor

A read-only Python tool that turns Cisco Catalyst Center interface telemetry into a practical physical-port capacity report. It is aimed at planning conversations such as whether an existing access switch has enough usable ports or whether additional hardware needs to be considered.

The project includes a complete offline demonstration. No controller, switch, production hostname, or real credential is required to inspect the workflow and sample output.

## What It Does

- Finds Catalyst devices by management IP address or device UUID.
- Retrieves device uptime and interface inventory through Catalyst Center APIs.
- Keeps front-panel physical ports and removes VLANs, port channels, app-hosting ports, and uplink-module interfaces such as `TenGigabitEthernet1/1/1`.
- Compares the newest incoming or outgoing packet timestamp with report time.
- Limits the observed inactivity period to device uptime, because a reboot shortens the available evidence window.
- Uses a fixed 60-day observation threshold to label device evidence as `HIGH` or `LOW` confidence.
- Produces matching HTML, JSON, and CSV reports.

`POTENTIALLY_UNUSED` is a review recommendation only. The tool does not disable ports or change configuration.

## Quick Offline Demo

Python 3.11 or later is required.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
catalyst-port-capacity --mock-data examples/mock_catalyst_data.json --targets 192.0.2.11 192.0.2.12 --collect --output-dir reports
```

Open `reports/catalyst_port_capacity.html` to review the result. The fixture uses reserved documentation addresses and fictional device names.

## Live Lab Use

Create a local credentials file from `examples/credentials.example.txt`. The populated file is excluded by `.gitignore` and should remain local.

The default command validates authentication and device resolution without retrieving interfaces:

```powershell
catalyst-port-capacity --credentials-file credentials.txt --targets 192.0.2.11
```

After the validation result looks correct, enable read-only interface collection:

```powershell
catalyst-port-capacity --credentials-file credentials.txt --targets 192.0.2.11 --collect --output-dir reports
```

Use `--debug` for detailed processing logs. `--no-verify` is available for isolated labs with self-signed certificates; certificate verification should remain enabled where a trusted certificate is available.

Credentials can alternatively come from these environment variables:

```text
CATALYST_CENTRE_BASE_URL
CATALYST_CENTRE_USERNAME
CATALYST_CENTRE_PASSWORD
NETWORK_DEVICE_USERNAME
NETWORK_DEVICE_PASSWORD
```

The network-device values are reserved for optional SSH validation work and are not used by the current API-only release.

## Classification

| Result | Meaning |
| --- | --- |
| `ACTIVE` | The interface is administratively and operationally up. |
| `POTENTIALLY_UNUSED` | The interface is admin-up, operationally down, and has at least 60 days without observed packet activity. |
| `REVIEW` | The available evidence is shorter, missing, or otherwise insufficient for an unused-port recommendation. |

Device confidence is `HIGH` after at least 60 days of uptime. A shorter uptime produces `LOW` confidence and a visible warning in the report.

## Project Layout

```text
examples/                       Fictional credentials and Catalyst responses
sample_reports/                 Pre-generated HTML, JSON, and CSV examples
scripts/generate_sample_reports.py
src/catalyst_port_capacity/     Client, analysis, orchestration, and reporting
tests/                          Offline regression tests
```

## Validation

```powershell
ruff format --check .
ruff check .
python -m pytest -q
python -m compileall -q src tests scripts
python scripts/generate_sample_reports.py
```

## Security Notes

- The repository contains no live credentials or production inventory.
- Authentication tokens and passwords are never written to reports or logs.
- API operations are read-only.
- Example addresses use the `192.0.2.0/24` documentation range.
- Reports can still contain operational information when run against a real environment. Review generated files before sharing them.

## Limitations

- Packet timestamps depend on Catalyst Center collection quality and retention.
- A switch reboot limits the trustworthy observation window.
- Port availability does not prove that cabling, licensing, power, optics, or design capacity is suitable.
- Operational approval is still required before reclaiming any interface.
