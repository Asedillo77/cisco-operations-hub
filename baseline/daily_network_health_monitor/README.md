# Cisco Network Health Monitor

A dry-run-first Python tool that collects point-in-time operational evidence from Cisco switches
and edge routers, evaluates selected health indicators, and produces interactive HTML and JSON
reports.

This repository is a complete offline demonstration. Its inventory, addresses, hostnames, command
outputs, timestamps, and reports are fictional. No controller, production device, or real credential
is required to inspect the workflow.

## Why This Project Exists

Network maintenance checks and general command runners solve related but different problems. A
pre/post checker compares two points in time, while a command runner focuses on safe collection.
This project combines the reusable parts of both patterns into a daily health snapshot:

- device-type command profiles;
- bounded parallel SSH collection;
- explicit health interpretation;
- row-level evidence and failure handling;
- interactive reporting; and
- completion markers suitable for a later automation workflow.

The current release runs on demand. A future integration could schedule collection on a managed
workstation and publish a concise, permission-controlled summary to an approved collaboration
channel. Notification and cloud-sharing configuration are intentionally outside this public demo.

## Health Checks

Switch profiles collect stack-member readiness, platform resource state, interface state, connected
port counts, PoE state, environmental evidence, and CDP/LLDP neighbors. Edge-router profiles collect
IP interface state, routing protocol evidence for a configurable VRF, OSPF adjacency, SD-WAN control
connections, and global and VRF route evidence.

| Result | Meaning |
| --- | --- |
| `HEALTHY` | A supported parser verified the observed state. |
| `INFORMATIONAL` | Useful evidence was collected without claiming operational health. |
| `WARNING` | A degraded or reviewable condition was found. |
| `CRITICAL` | A serious supported health condition was found. |
| `UNKNOWN` | Output was empty, unsupported, or could not be parsed safely. |
| `FAILED` | Device connection or command collection failed. |

Examples include degraded PSU redundancy as a warning, a stack member without a healthy power
supply as critical, and count-only topology evidence as informational.

## Safety Model

- Dry-run is the default and opens no SSH connections.
- Live collection requires the explicit `--apply` option.
- Inventory size is checked before collection; the default limit is 50 enabled devices.
- Device concurrency is bounded and configurable.
- Commands are loaded from reviewed device-type JSON profiles.
- Credentials remain in memory and are excluded from reports.
- Unsupported commands and failed rows remain visible instead of being silently discarded.
- Reports are built under `staging` and moved to `ready` only after every artifact is complete.
- The supplied profiles contain operational `show` commands and do not change device configuration.

## Quick Offline Demo

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/) are recommended.

```powershell
uv sync --link-mode=copy
uv run cisco-network-health mock-report
```

Open the generated `report.html` beneath `outputs/ready/`. The summary cards filter Healthy,
Informational, Warning, Critical, Unknown, and Collection Failed results without leaving the page.
A pre-generated fictional report is also available in `sample_reports/`.

## Safe Inventory Validation

The sample inventory uses addresses reserved for documentation:

```powershell
uv run cisco-network-health run --inventory samples/inventory.csv --debug
```

Because `--apply` is omitted, this validates inventory, command profiles, report generation, and the
publication workflow without connecting to a device.

## Controlled Lab Collection

Copy `credentials/credentials.example.txt` to the ignored `credentials/credentials.txt` and update
the local copy. Then use an authorised lab inventory:

```powershell
uv run cisco-network-health run `
  --inventory samples/inventory.csv `
  --credentials-file credentials/credentials.txt `
  --max-devices 10 `
  --max-workers 3 `
  --apply `
  --debug
```

Review command compatibility and expected health states against the target platform before relying
on any severity classification.

## Reports

Each completed run contains `report.html`, `report.json`, `notification.json`, `complete.json`, and
the `raw_outputs/` directory. The HTML and JSON reports come from the same result model.
`notification.json` provides a compact summary for a future approved workflow, while
`complete.json` marks a fully written run.

Generated operational reports may contain sensitive hostnames, addresses, topology, routing, and
hardware details. Never publish a report captured from a real environment without reviewing and
sanitising it first.

## Validation

```powershell
uv lock --check
uv run python -m compileall -q src tests scripts
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
uv run python scripts/generate_sample_reports.py
```

The test suite covers input limits, VRF expansion, stack parsing, Cisco platform-resource states,
environmental severity, interface faults, PoE faults, unsupported commands, report grouping,
interactive filter markup, completion markers, and notification highlights.

## Project Layout

```text
configs/                         switch and edge-router command profiles
credentials/                     fictional credential-file example
samples/                         fictional inventory using documentation addresses
sample_reports/                  pre-generated offline report
scripts/generate_sample_reports.py
src/daily_network_health_monitor/
templates/                       interactive HTML report
tests/                           offline regression tests
```

## Limitations

- Cisco output varies across platforms and software releases.
- Informational counts require an expected-state policy or baseline before they imply health.
- Suspended interfaces can be intentional and may require site-specific exceptions.
- An empty redundant PSU slot can be intentional and may require an inventory expectation.
- This project does not replace monitoring, alert correlation, change control, or engineering review.

## License

MIT

