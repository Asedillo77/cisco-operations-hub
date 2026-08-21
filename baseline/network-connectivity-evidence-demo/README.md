# Network Connectivity Evidence Explorer

A read-only Python troubleshooting tool for Cisco IOS XE edge routers. It combines ICMP reachability, SSH command
output, routing evidence, tunnel state, cellular measurements, and optional SolarWinds context into matching HTML and
JSON reports.

The report is designed for a mixed audience. The opening section gives a concise operational summary, while the
device sections preserve the evidence needed for engineering review and escalation.

This is an independent demonstration project. It is not affiliated with or endorsed by Cisco, SolarWinds, or any
telecommunications provider.

## Highlights

- Dry-run is the default; live ping and read-only SSH collection require `--apply`.
- Supports individual routers or a JSON inventory grouped by site.
- Uses site archetypes for branch, mobile, portable, warehouse, data-centre, and dual-edge hub designs.
- Runs cellular commands only when the observed or expected transport makes them relevant.
- Interprets packet loss, latency, default paths, WAN state, cellular registration, and LTE signal measurements.
- Separates direct internet access, service VPN, secure-web-gateway tunnels, and backup/failover evidence.
- Treats current monitoring state as primary context and keeps old active alerts visible without automatically
  overriding healthy live evidence.
- Produces responsive Jinja HTML with content-sized columns and horizontal scrolling for wide results.
- Includes a Tkinter desktop interface and a command-line interface.

The tool does not change device configuration, routing, tunnel state, or monitoring alerts.

## Offline Sample

Python 3.11 or newer is recommended.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python scripts\generate_mock_report.py
```

The generated HTML and JSON files are written to `sample_reports`. All sample names are fictional and all addresses
come from RFC documentation ranges.

## Dry-Run Planning

The following command creates a report showing the planned checks. It does not ping or connect to the router:

```powershell
connectivity-evidence `
  --host 192.0.2.10 `
  --name LAB-BRANCH-01 `
  --site "Example Branch" `
  --site-type branch `
  --transport fixed_cellular_backup
```

An inventory-based dry run is also available:

```powershell
connectivity-evidence `
  --inventory data\inventory.example.json `
  --site "Example Cellular Site"
```

## Live Read-Only Collection

Copy `credentials.example.txt` to `credentials.txt` and keep the populated file outside source control. Live mode is
explicit:

```powershell
connectivity-evidence `
  --inventory data\inventory.local.json `
  --site "Lab Branch" `
  --credentials-file credentials.txt `
  --report-dir reports `
  --debug `
  --apply
```

The approved command profile currently contains:

```text
show version | include uptime
show ip interface brief
show ip route
show interfaces description
show running-config | section ^interface Tunnel
```

When cellular evidence is relevant, the collector also runs:

```text
show cellular 0/2/0 radio
show cellular 0/2/0 network
```

Command support and interface numbering vary by platform and software release. Review the profile before using the
live mode in a lab or another authorised environment.

## Optional SolarWinds Context

Install the optional dependency:

```powershell
python -m pip install -e ".[solarwinds]"
```

Copy `solarwinds_credentials.example.txt` to a private local file, then add both options to a live run:

```text
--solarwinds-alerts
--solarwinds-credentials-file solarwinds_credentials.txt
```

Router SSH credentials and SolarWinds credentials are intentionally separate. Monitoring queries are read-only.

## Desktop Interface

```powershell
connectivity-evidence-gui
```

The interface starts in dry-run mode. Live collection requires an explicit checkbox and confirmation.

## Evidence Model

| Area | Interpretation |
| --- | --- |
| Reachability | Packet loss and average latency are reported independently. |
| WAN state | Assigned addresses and line protocol are considered together. |
| Default route | Single-edge and declared dual-edge designs use different path expectations. |
| Cellular | RSRP, RSRQ, SINR/SNR, and RSSI are explained in plain language. |
| Tunnels | Configuration structure and live interface state are correlated; tunnel numbers alone are not treated as proof. |
| Monitoring | Current node state is stronger evidence than an old uncleared alert. |

Results are diagnostic evidence, not proof of root cause. A healthy edge-router report does not rule out endpoint,
authentication, DNS, application, policy, or upstream service issues.

## Validation

```powershell
python -m compileall -q src tests scripts
ruff format --check .
ruff check --no-cache .
pytest -q
python scripts\generate_mock_report.py
```

## Project Layout

```text
src/site_connectivity/   Collection, evaluation, reporting, CLI, GUI, and Jinja template
tests/                   Offline parsing, policy, reporting, and monitoring tests
data/                    Fictional inventory example
scripts/                 Deterministic sample-report generator
sample_reports/          Pre-generated fictional HTML and JSON reports
```

## Security

- Keep populated credential files, production inventories, logs, and generated operational reports out of Git.
- Use an authorised read-only account and a controlled lab before connecting to live devices.
- Review reports before sharing because command output can expose names, addresses, routes, and topology.
- See [SECURITY.md](SECURITY.md) for the public-repository handling rules.

## License

MIT. See [LICENSE](LICENSE).
