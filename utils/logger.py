"""
Structured logging configuration.
All modules obtain a logger via get_logger(name).
Three sinks: stdout, logs/app.log (INFO+), logs/errors.log (ERROR+).
"""

import logging
import sys
from pathlib import Path

# Avoid circular import: read LOG_LEVEL directly from env here,
# not from config.settings, because settings imports nothing from utils.
import os
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')

_LOG_LEVEL_STR: str = os.getenv('LOG_LEVEL', 'INFO').upper()
_APP_NAME: str = os.getenv('APP_NAME', 'financial-guardian')
_LOG_LEVEL: int = getattr(logging, _LOG_LEVEL_STR, logging.INFO)

LOG_DIR = Path(__file__).parent.parent / 'logs'
LOG_DIR.mkdir(exist_ok=True)

_FORMATTER = logging.Formatter(
    fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Module-level handlers — created once, shared across all loggers
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setLevel(_LOG_LEVEL)
_console_handler.setFormatter(_FORMATTER)

_file_handler = logging.FileHandler(LOG_DIR / 'app.log', encoding='utf-8')
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(_FORMATTER)

_error_handler = logging.FileHandler(LOG_DIR / 'errors.log', encoding='utf-8')
_error_handler.setLevel(logging.ERROR)
_error_handler.setFormatter(_FORMATTER)

# Suppress noisy third-party loggers
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger scoped under the application name.

    Args:
        name: Module name, e.g. 'holdings.kite_sync'

    Returns:
        Configured Logger instance.
    """
    full_name = f"{_APP_NAME}.{name}"
    logger = logging.getLogger(full_name)

    if not logger.handlers:
        logger.setLevel(_LOG_LEVEL)
        logger.addHandler(_console_handler)
        logger.addHandler(_file_handler)
        logger.addHandler(_error_handler)
        logger.propagate = False  # Prevent duplicate output via root logger

    return logger