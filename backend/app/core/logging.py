"""Application logging conventions."""

import logging


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger without logging secrets or sensitive payloads."""

    return logging.getLogger(f"app.{name}")
