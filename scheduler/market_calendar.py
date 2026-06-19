"""
Indian market trading calendar.

NSE holidays for 2026 are hardcoded and should be updated annually.
Source: NSE India official holiday calendar.
"""

from datetime import date, datetime, time, timedelta
import pytz
from utils.logger import get_logger

logger = get_logger('market_calendar')

IST = pytz.timezone('Asia/Kolkata')

NSE_HOLIDAYS_2026 = [
    date(2026, 1, 26),
    date(2026, 2, 26),
    date(2026, 3, 25),
    date(2026, 4, 2),
    date(2026, 4, 3),
    date(2026, 4, 14),
    date(2026, 5, 1),
    date(2026, 8, 15),
    date(2026, 8, 27),
    date(2026, 10, 2),
    date(2026, 10, 20),
    date(2026, 10, 21),
    date(2026, 11, 5),
    date(2026, 11, 25),
    date(2026, 12, 25),
]


def is_trading_day(check_date: date = None) -> bool:
    if check_date is None:
        check_date = datetime.now(IST).date()

    if check_date.weekday() >= 5:
        return False

    if check_date in NSE_HOLIDAYS_2026:
        return False

    return True


def is_market_hours_now() -> bool:
    now = datetime.now(IST)

    if not is_trading_day(now.date()):
        return False

    market_open = time(9, 15)
    market_close = time(15, 30)
    return market_open <= now.time() <= market_close


def is_pre_market_window() -> bool:
    now = datetime.now(IST)

    if not is_trading_day(now.date()):
        return False

    return time(7, 0) <= now.time() < time(9, 15)


def should_run_today(job_name: str) -> bool:
    """Most jobs run only on trading days; a few always run."""
    daily_always = ['health_check', 'auto_acknowledge_old_alerts']
    if job_name in daily_always:
        return True

    return is_trading_day()


def get_next_trading_day(from_date: date = None) -> date:
    if from_date is None:
        from_date = datetime.now(IST).date()

    check = from_date
    for _ in range(10):
        check = check + timedelta(days=1)
        if is_trading_day(check):
            return check

    return check