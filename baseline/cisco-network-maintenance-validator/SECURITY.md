# Security Policy

## Public repository rules

This repository contains fictional demonstration data only. Before publishing changes, check that source files, fixtures, tests, screenshots, and generated reports do not contain:

- production hostnames, domains, addresses, serial numbers, interface descriptions, or topology details;
- usernames, passwords, enable secrets, tokens, private keys, or populated credential files;
- internal filesystem paths, ticket numbers, change references, or organisation-specific branding;
- raw output or reports collected from a live environment.

Use RFC documentation address ranges in examples: `192.0.2.0/24`, `198.51.100.0/24`, and `203.0.113.0/24`.

## Operational use

- Use an authorised account with the least privilege needed to run show commands.
- Review command profiles before connecting to a different platform or software release.
- Run dry-run validation before adding `--apply`.
- Treat generated output as operationally sensitive even when credentials are redacted.
- Store real credentials and reports outside source control.

## Reporting a concern

Do not open a public issue containing credentials or live network evidence. Remove sensitive content first and provide a minimal fictional reproduction where possible.
