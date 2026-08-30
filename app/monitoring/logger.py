"""
Structured Logging — loguru-based logging with file rotation.
"""

import sys
import os

from loguru import logger


def setup_logging(debug: bool = True):
    """Configure loguru with file + console output."""
    # Remove default handler
    logger.remove()

    # Console handler (colorful)
    logger.add(
        sys.stderr,
        level="DEBUG" if debug else "INFO",
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # File handler (JSON-like, rotated)
    log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
    os.makedirs(log_dir, exist_ok=True)

    logger.add(
        os.path.join(log_dir, "app_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    )

    logger.info("📋 Logging initialized")
