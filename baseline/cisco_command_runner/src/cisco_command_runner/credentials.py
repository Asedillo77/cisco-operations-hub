from __future__ import annotations

from pathlib import Path


def load_credentials(path: Path) -> dict[str, str | int]:
    if not path.is_file():
        raise FileNotFoundError(f"Credential file was not found: {path}")
    values: dict[str, str | int] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Credential line {number} must use key=value format.")
        key, value = line.split("=", 1)
        values[key.strip().lower()] = value.strip()
    return validate_credentials(values)


def validate_credentials(values: dict[str, str | int]) -> dict[str, str | int]:
    cleaned = {
        str(key).strip().lower(): value
        for key, value in values.items()
        if value is not None and str(value).strip()
    }
    missing = [name for name in ("username", "password") if not cleaned.get(name)]
    if missing:
        raise ValueError(f"Credentials are missing: {', '.join(missing)}.")
    cleaned["username"] = str(cleaned["username"]).strip()
    cleaned["password"] = str(cleaned["password"])
    if "secret" in cleaned:
        cleaned["secret"] = str(cleaned["secret"])
    for name, default in (("port", 22), ("timeout", 30)):
        number = int(cleaned.get(name, default))
        if number < 1:
            raise ValueError(f"Credential {name} must be at least 1.")
        cleaned[name] = number
    return cleaned
