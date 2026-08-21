# Security Policy

## Reporting a Vulnerability

Do not open a public issue containing credentials, device configurations, internal hostnames, addresses, or other operational data. Report security concerns privately to the repository owner.

## Operational Guidance

- Use a dedicated least-privilege account suitable for read-only command collection.
- Keep populated credential files outside version control.
- Review every command and dry-run report before enabling Apply mode.
- Use conservative concurrency limits when testing a new environment.
- Treat generated reports as potentially sensitive because they may contain device inventory, software versions, configurations, and topology evidence.
- Remove or anonymize operational data before sharing reports externally.

This project restricts command execution to approved operational prefixes, but operators remain responsible for reviewing platform-specific command behaviour.
