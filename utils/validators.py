"""
Input validation helpers.
Used across holdings sync, data pipeline, and alert modules.
"""

import re
from datetime import date
from typing import Any, Optional


# NSE/BSE ticker: 1–20 alphanumeric characters, hyphens, and ampersands
_TICKER_RE = re.compile(r'^[A-Z0-9\-&]{1,20}$')

# ISIN: 2-letter country code + 10 alphanumeric characters
_ISIN_RE = re.compile(r'^[A-Z]{2}[A-Z0-9]{10}$')

# Fund code: alphanumeric, hyphens, underscores
_FUND_CODE_RE = re.compile(r'^[A-Z0-9\-_]{1,50}$')


def is_valid_ticker(ticker: Any) -> bool:
    """Return True if the value is a well-formed NSE/BSE ticker symbol."""
    if not isinstance(ticker, str):
        return False
    return bool(_TICKER_RE.match(ticker.upper()))


def is_valid_isin(isin: Any) -> bool:
    """Return True if the value matches the ISIN format (not a checksum validation)."""
    if not isinstance(isin, str):
        return False
    return bool(_ISIN_RE.match(isin.upper()))


def is_valid_fund_code(code: Any) -> bool:
    """Return True if the value is a plausible Groww fund code."""
    if not isinstance(code, str):
        return False
    return bool(_FUND_CODE_RE.match(code.upper()))


def is_positive_number(value: Any) -> bool:
    """Return True if value is a positive int or float."""
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def is_non_negative_number(value: Any) -> bool:
    """Return True if value is zero or a positive int or float."""
    try:
        return float(value) >= 0
    except (TypeError, ValueError):
        return False


def sanitize_text(text: Any, max_length: int = 500) -> Optional[str]:
    """
    Strip leading/trailing whitespace and truncate to max_length.
    Returns None if input is not a non-empty string.
    """
    if not isinstance(text, str):
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


def validate_date_string(date_str: Any, fmt: str = '%Y-%m-%d') -> Optional[date]:
    """
    Parse a date string and return a date object, or None if invalid.
    """
    if not isinstance(date_str, str):
        return None
    try:
        from datetime import datetime
        return datetime.strptime(date_str.strip(), fmt).date()
    except (ValueError, AttributeError):
        return None