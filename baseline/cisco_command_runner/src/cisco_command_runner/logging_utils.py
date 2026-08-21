from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(debug: bool, log_file: Path | None = None) -> logging.Logger:
    logger = logging.getLogger("cisco_command_runner")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger
