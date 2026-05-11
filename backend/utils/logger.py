"""Logging helpers for the backend."""

from __future__ import annotations

import logging

from backend import config


def configure_logging(level: str | None = None) -> None:
    resolved_level = getattr(logging, (level or config.LOG_LEVEL).upper(), logging.INFO)
    logging.basicConfig(
        level=resolved_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
