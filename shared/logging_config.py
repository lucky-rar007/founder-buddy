"""
Centralized Logging Configuration.

Configures dual-handler logging:
  1. File Handler: Writes detailed logs to logs/founder_buddy.log with 10MB rotation.
  2. Console Handler: Outputs clean, formatted logs to standard error/out.
"""

from __future__ import annotations

import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR = _WORKSPACE_ROOT / "logs"
_LOG_FILE = _LOG_DIR / "founder_buddy.log"


def setup_logging(log_level: int = logging.INFO) -> None:
    """
    Configures centralized logging for the application.
    Creates logs/ directory if it doesn't exist.
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    
    # Avoid duplicate handlers if already initialized
    if root_logger.hasHandlers():
        return

    root_logger.setLevel(log_level)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. Rotating File Handler (10 MB per file, max 5 backups)
    file_handler = RotatingFileHandler(
        _LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # 2. Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    logging.info(f"[Logging] File logger active. Diagnostic logs saved to: {_LOG_FILE}")


# Automatically setup logging when imported
setup_logging()
