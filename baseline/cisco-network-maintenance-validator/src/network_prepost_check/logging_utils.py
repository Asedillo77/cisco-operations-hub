from __future__ import annotations

import logging


def build_logger(debug: bool) -> logging.Logger:
    logger = logging.getLogger("network_prepost_check")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG if debug else logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
