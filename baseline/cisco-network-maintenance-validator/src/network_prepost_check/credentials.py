from __future__ import annotations

from pathlib import Path


def load_local_credentials(credentials_file: Path) -> dict[str, str | int]:
    if not credentials_file.exists():
        raise FileNotFoundError(f"Credential file was not found: {credentials_file}")

    credentials: dict[str, str | int] = {}
    with credentials_file.open("r", encoding="utf-8") as file_handle:
        for line_number, raw_line in enumerate(file_handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"Credential file line {line_number} must use key=value format.")
            key, value = line.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if not key:
                raise ValueError(f"Credential file line {line_number} has an empty key.")
            credentials[key] = value

    for numeric_key in ("port", "timeout"):
        if numeric_key in credentials:
            credentials[numeric_key] = int(str(credentials[numeric_key]))

    return validate_credentials(credentials)


def validate_credentials(credentials: dict[str, str | int]) -> dict[str, str | int]:
    normalized = {
        str(key).strip().lower(): value
        for key, value in credentials.items()
        if value is not None and str(value).strip()
    }
    missing = [key for key in ("username", "password") if not normalized.get(key)]
    if missing:
        raise ValueError(f"Credentials are missing required key(s): {', '.join(missing)}")

    normalized["username"] = str(normalized["username"]).strip()
    for numeric_key, default in (("port", 22), ("timeout", 30)):
        value = int(normalized.get(numeric_key, default))
        if value < 1:
            raise ValueError(f"Credential {numeric_key} must be 1 or higher.")
        normalized[numeric_key] = value
    return normalized
