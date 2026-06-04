"""
Date and time utilities.
All internal times are stored in UTC.
All display and scheduling logic uses IST (Asia/Kolkata).
"""

from datetime import datetime, time, date, timedelta
from typing import Optional

import pytz

from config.settings import (
    TIMEZONE,
    MARKET_OPEN_TIME,
    MARKET_CLOSE_TIME,
    PRE_MARKET_START,
    POST_MARKET_END,
)

IST: pytz.BaseTzInfo = pytz.timezone(TIMEZONE)
UTC: pytz.BaseTzInfo = pytz.utc

# Known NSE trading holidays for the current year.
# Populated from the NSE holiday calendar — update annually.
# Format: date objects, YYYY-MM-DD.
# TODO: replace with a live NSE holiday API call in Phase 7.
NSE_HOLIDAYS_2026: frozenset[date] = frozenset({
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 20),   # Holi (tentative — verify with NSE)
    date(2026, 4, 2),    # Ram Navami (tentative)
    date(2026, 4, 3),    # Good Friday (tentative)
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti / Baisakhi (tentative)
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 8, 15),   # Independence Day
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 10, 20),  # Diwali Laxmi Puja (tentative)
    date(2026, 11, 25),  # Guru Nanak Jayanti (tentative)
    date(2026, 12, 25),  # Christmas
})

NSE_HOLIDAYS: frozenset[date] = NSE_HOLIDAYS_2026


def _parse_hhmm(time_str: str) -> time:
    """Parse 'HH:MM' string into a time object. Raises ValueError on bad input."""
    parts = time_str.split(':')
    if len(parts) != 2:
        raise ValueError(f"Expected HH:MM format, got: {time_str!r}")
    return time(int(parts[0]), int(parts[1]))


def now_ist() -> datetime:
    """Return the current datetime in IST with timezone info."""
    return datetime.now(IST)


def now_utc() -> datetime:
    """Return the current datetime in UTC with timezone info."""
    return datetime.now(UTC)


def today_ist() -> date:
    """Return the current date in IST."""
    return now_ist().date()


def to_ist(dt: datetime) -> datetime:
    """Convert any timezone-aware datetime to IST."""
    if dt.tzinfo is None:
        raise ValueError("Naive datetime passed to to_ist(). Localise first.")
    return dt.astimezone(IST)


def to_utc(dt: datetime) -> datetime:
    """Convert any timezone-aware datetime to UTC."""
    if dt.tzinfo is None:
        raise ValueError("Naive datetime passed to to_utc(). Localise first.")
    return dt.astimezone(UTC)


def localize_ist(dt: datetime) -> datetime:
    """Attach IST timezone to a naive datetime (assumes it represents IST time)."""
    if dt.tzinfo is not None:
        return dt.astimezone(IST)
    return IST.localize(dt)


def is_market_hours(at: Optional[datetime] = None) -> bool:
    """
    Return True if the given time (default: now) falls within NSE market hours
    (09:15–15:30 IST, Monday–Friday, non-holiday).
    """
    check = to_ist(at) if at else now_ist()
    if not is_trading_day(check.date()):
        return False
    current_time = check.time()
    return _parse_hhmm(MARKET_OPEN_TIME) <= current_time <= _parse_hhmm(MARKET_CLOSE_TIME)


def is_extended_monitoring_hours(at: Optional[datetime] = None) -> bool:
    """
    Return True if within the pre-market to post-market monitoring window
    (default 08:00–16:30 IST), on a trading day.
    """
    check = to_ist(at) if at else now_ist()
    if not is_trading_day(check.date()):
        return False
    current_time = check.time()
    return _parse_hhmm(PRE_MARKET_START) <= current_time <= _parse_hhmm(POST_MARKET_END)


def is_trading_day(check_date: Optional[date] = None) -> bool:
    """
    Return True if the given date (default: today IST) is an NSE trading day.
    Excludes weekends and known NSE holidays.
    """
    d = check_date if check_date is not None else today_ist()
    if d.weekday() >= 5:   # Saturday=5, Sunday=6
        return False
    return d not in NSE_HOLIDAYS


def next_trading_day(from_date: Optional[date] = None) -> date:
    """Return the next trading day after the given date (default: today)."""
    d = (from_date if from_date is not None else today_ist()) + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def format_ist(dt: datetime) -> str:
    """Format a datetime for human-readable display in IST."""
    return to_ist(dt).strftime('%d %b %Y %H:%M IST')


def format_date(d: date) -> str:
    """Format a date for display."""
    return d.strftime('%d %b %Y')