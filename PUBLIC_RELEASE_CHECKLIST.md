# Public release checklist

Run this checklist before publishing a new snapshot.

- Confirm the office working copy is not inside this repository.
- Use synthetic inventories and documentation IP ranges in all samples.
- Check that credentials, device output, reports, logs, and local environments are ignored.
- Search tracked files for organization names, usernames, workstation paths, email addresses, tokens, passwords, public IP addresses, serial numbers, and production hostnames.
- Run syntax, Ruff, type, and test checks.
- Generate representative mock reports and review them at desktop and narrow browser widths.
- Review `git diff` and the complete Git history before pushing.

Live collection should remain disabled until the operator deliberately supplies local credentials and enters the confirmation phrase shown by the interface.
