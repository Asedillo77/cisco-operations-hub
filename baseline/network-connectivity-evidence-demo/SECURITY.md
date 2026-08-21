# Security Notes

This repository contains fictional examples only. The committed inventory and sample reports use reserved
documentation address ranges and do not represent a production environment.

Before publishing changes:

- exclude populated credentials and local inventory files;
- exclude reports generated from operational devices;
- search for organisation names, internal hostnames, routable addresses, usernames, tokens, and passwords;
- confirm that all sample router output is synthetic;
- review the complete Git history, not only the current files.

The live workflow performs ICMP checks, read-only SSH commands, and optional read-only monitoring queries. Device
configuration changes and alert acknowledgement are outside the scope of the project.
