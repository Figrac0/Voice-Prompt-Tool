from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import AppConfig


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging(config: AppConfig) -> logging.Logger:
    log_dir = config.paths.logs_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    logger_name = config.app_slug
    logger = logging.getLogger(logger_name)
    logger.setLevel(_resolve_log_level(config.log_level))
    logger.propagate = False

    if logger.handlers:
        return logger

    log_file = log_dir / f"{logger_name}.log"
    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=1_048_576,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.debug("Logger configured. Writing to %s", log_file)
    return logger


def build_emergency_logger(project_root: Path) -> logging.Logger:
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("voice_prompt_tool.bootstrap")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    handler = RotatingFileHandler(
        filename=log_dir / "bootstrap.log",
        maxBytes=262_144,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    return logger


def _resolve_log_level(log_level: str) -> int:
    return getattr(logging, log_level.upper(), logging.INFO)
