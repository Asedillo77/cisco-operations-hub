# Cisco Operations Hub

Cisco Operations Hub is a local browser interface that brings five Cisco operations workflows into one consistent, safety-focused application:

- Operational Command Runner
- Daily Health Monitor
- Catalyst Port Capacity Auditor
- Network Connectivity Evidence Explorer
- Network Maintenance Validator

The independently tested implementations are preserved under `baseline/`. The browser adapters reuse their inventory handling, collection, analysis, comparison, and reporting logic instead of replacing it with a second implementation.

This repository is the public demonstration edition. Its examples use synthetic devices, documentation IP ranges, placeholder credentials, and public-safe teal report styling. Generated reports, populated credentials, local environments, and runtime output are deliberately excluded from source control.

## Safety model

- The server binds only to a loopback address.
- Dry-run is the default and does not connect to network devices.
- Live collection requires a credentials file and the exact confirmation phrase shown in the interface.
- Catalyst Port Capacity can correlate DNAC interface evidence with read-only switch CLI inventory
  from `show interfaces status` and `show switch`. CLI failures remain visible and do not silently
  pass as successful validation. Port filtering, normalization, confidence, status classification,
  sorting, and CLI correlation follow the preserved v7 Nautobot port-reclaim behavior.
- The browser receives file paths and execution results, never credential contents.
- Requests that change execution state require a per-process request token.
- The public-safe teal theme is the default. Internal branding is not included in public sample output.
- Device-list inventories accept CSV or XLSX. Structured JSON remains available where a tool needs nested configuration that cannot be represented safely as a simple table.
- Connectivity Evidence defaults to a 10-device selected-scope ceiling. Larger plans require a deliberate limit increase and display a large-run warning before live collection.

## Before using live collection

Start with the supplied synthetic samples and dry-run mode. Copy the relevant `credentials.example.txt` file to a location outside the repository, populate it locally, and select it in the interface only when live collection is required. Never commit credentials, exported production inventories, device output, or generated reports.

## Run with uv

Install the development environment:

```powershell
uv sync --extra dev
```

Start the local interface:

```powershell
uv run cisco-operations-hub
```

The application opens `http://127.0.0.1:8765/` in the default browser. Use `--no-browser` when the page should not open automatically.

## Validation

```powershell
uv run python -m compileall -q src tests
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -q
```

## Included workflows

| Tool | Status |
|---|---|
| Operational Command Runner | Dry-run and live adapter available |
| Daily Health Monitor | Dry-run and live adapter available |
| Catalyst Port Capacity | Offline mock and controlled live adapter available |
| Connectivity Evidence | Dry-run and controlled live adapter available |
| Maintenance Validator | Pre-check, post-check, comparison, and reporting adapter available |

The private working copy is maintained separately from this public demonstration repository.
