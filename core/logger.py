"""Structured logging setup for APEX Trading System.

Uses structlog with JSON output, service_name context, UTC timestamps, and log level.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def get_logger(service_name: str) -> structlog.stdlib.BoundLogger:
    """Configure and return a structlog logger bound to a service name.

    Args:
        service_name: Identifier for the service producing log records.

    Returns:
        A structlog BoundLogger with JSON output and UTC timestamps.
    """
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Ensure stdlib handler is present
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    logger: structlog.stdlib.BoundLogger = structlog.get_logger(service_name).bind(
        service=service_name
    )
    return logger


def configure_root_logging(level: str = "INFO") -> None:
    """Configure the root logging level.

    Args:
        level: Logging level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.getLogger().setLevel(numeric_level)
