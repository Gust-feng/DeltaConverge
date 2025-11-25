"""Agent 框架的标准日志配置。

对 Python logging 的轻量封装，默认包含：
- 控制台 + 轮转文件处理器；
- 日志级别由环境变量 LOG_LEVEL 控制（默认 INFO）；
- 幂等配置，可安全多次调用。

用法：
    from Agent.core.logging.std_logger import get_logger
    logger = get_logger(__name__)
    logger.info("发生了事件", extra={"meta": {...}})
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_CONFIGURED = False


def _parse_level(level: Optional[str]) -> int:
    """将字符串/整数级别转换为 logging 级别（带安全默认值）。"""

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
    """配置根 logger（控制台 + 轮转文件处理器）。

    可重复调用，首次调用优先生效。
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
    """确保完成基础配置后返回指定名称的 logger。"""

    configure_logging(**kwargs)
    return logging.getLogger(name)


__all__ = ["get_logger", "configure_logging"]
