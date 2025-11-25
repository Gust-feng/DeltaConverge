"""Standard logging setup for the agent framework.

Provides a thin wrapper around Python's logging with sane defaults:
- console + rotating file handler
- level controlled via LOG_LEVEL env (default INFO)
- idempotent configuration (safe to call multiple times)

Usage:
    from Agent.core.logging.std_logger import get_logger
    logger = get_logger(__name__)
    logger.info("something happened", extra={"meta": {...}})
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_CONFIGURED = False


def _parse_level(level: Optional[str]) -> int:
    """Translate string/int level to logging level with a safe default."""

    if isinstance(level, int):
        return level
    if isinstance(level, str):
        try:
            return logging.getLevelName(level.upper())
        except Exception:
            return logging.INFO
    env_level = os.getenv("LOG_LEVEL", "INFO")
    try:
        return logging.getLevelName(env_level.upper())
    except Exception:
        return logging.INFO


def configure_logging(
    level: Optional[str] = None,
    log_dir: str | Path = "log/runtime",
    filename: str = "agent.log",
    max_bytes: int = 5_000_000,
    backup_count: int = 5,
    console: bool = True,
) -> logging.Logger:
    """Configure root logger with console + rotating file handlers.

    Safe to call multiple times; the first invocation wins.
    """

    global _CONFIGURED
    if _CONFIGURED:
        return logging.getLogger()

    Path(log_dir).mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(_parse_level(level))

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    file_handler = RotatingFileHandler(
        Path(log_dir) / filename,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        root.addHandler(console_handler)

    _CONFIGURED = True
    return root


def get_logger(
    name: str,
    **kwargs,
) -> logging.Logger:
    """Return a logger after ensuring base configuration is set."""

    configure_logging(**kwargs)
    return logging.getLogger(name)


__all__ = ["get_logger", "configure_logging"]
