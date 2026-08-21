import logging


def configure_logging(debug: bool) -> logging.Logger:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return logging.getLogger("daily_network_health")
