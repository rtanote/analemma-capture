"""Logging configuration module for Analemma Capture System."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from analemma.config import LoggingConfig


def setup_logger(
    config: Optional[LoggingConfig] = None,
    name: str = "analemma",
) -> logging.Logger:
    """Set up and configure the application logger.

    Args:
        config: Logging configuration. If None, uses defaults.
        name: Logger name.

    Returns:
        Configured logger instance.
    """
    if config is None:
        config = LoggingConfig()

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, config.level))

    # Clear existing handlers
    logger.handlers.clear()

    # Log format
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, config.level))
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (if configured)
    if config.file:
        try:
            # Ensure log directory exists
            log_path = Path(config.file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=config.max_size_mb * 1024 * 1024,
                backupCount=config.backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(getattr(logging, config.level))
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except PermissionError:
            logger.warning(
                f"Cannot write to log file {config.file}, logging to console only"
            )
        except OSError as e:
            logger.warning(f"Error setting up file logging: {e}, logging to console only")

    return logger


def get_logger(name: str = "analemma") -> logging.Logger:
    """Get an existing logger or create a basic one.

    Args:
        name: Logger name.

    Returns:
        Logger instance.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        # Set up a basic console handler if not configured
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
