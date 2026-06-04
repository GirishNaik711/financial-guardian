"""
Central configuration module.
Loads all settings from environment variables via .env file.
Uses os.environ[] (not getenv) for required values — fails fast on missing secrets.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent

# Load .env — must exist in project root
_env_path = BASE_DIR / '.env'
if not _env_path.exists():
    raise FileNotFoundError(
        f".env file not found at {_env_path}. "
        "Copy .env.example to .env and fill in all values."
    )
load_dotenv(_env_path)


def _require(key: str) -> str:
    """Return env var value or raise a clear error if missing."""
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            "Check your .env file."
        )
    return val


def _optional(key: str, default: str = '') -> str:
    return os.getenv(key, default)


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        raise ValueError(f"Environment variable '{key}' must be an integer.")


def _float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        raise ValueError(f"Environment variable '{key}' must be a float.")


# ── Application 
APP_ENV: str = _optional('APP_ENV', 'development')
APP_NAME: str = _optional('APP_NAME', 'financial-guardian')
LOG_LEVEL: str = _optional('LOG_LEVEL', 'INFO').upper()
TIMEZONE: str = _optional('TIMEZONE', 'Asia/Kolkata')
IS_PRODUCTION: bool = APP_ENV == 'production'

# ── Database 
DATABASE_URL: str = _require('DATABASE_URL')
DATABASE_POOL_SIZE: int = _int('DATABASE_POOL_SIZE', 5)
DATABASE_MAX_OVERFLOW: int = _int('DATABASE_MAX_OVERFLOW', 10)

# ── Redis 
REDIS_URL: str = _require('REDIS_URL')

# ── Kite Connect 
KITE_API_KEY: str = _require('KITE_API_KEY')
KITE_API_SECRET: str = _require('KITE_API_SECRET')
KITE_ACCESS_TOKEN: str = _optional('KITE_ACCESS_TOKEN', '')
KITE_REQUEST_TOKEN: str = _optional('KITE_REQUEST_TOKEN', '')

# ── Groww 
GROWW_API_BASE_URL: str = _optional('GROWW_API_BASE_URL', 'https://groww.in/v1/api')
GROWW_AUTH_TOKEN: str = _require('GROWW_AUTH_TOKEN')

# ── Google Sheets 
GOOGLE_SHEETS_CREDENTIALS_PATH: str = _optional(
    'GOOGLE_SHEETS_CREDENTIALS_PATH',
    str(BASE_DIR / 'config' / 'google_service_account.json')
)
WATCHLIST_SHEET_ID: str = _require('WATCHLIST_SHEET_ID')
WATCHLIST_TAB_NAME: str = _optional('WATCHLIST_TAB_NAME', 'Watchlist')

# ── Slack 
SLACK_BOT_TOKEN: str = _require('SLACK_BOT_TOKEN')
SLACK_SIGNING_SECRET: str = _require('SLACK_SIGNING_SECRET')
SLACK_CHANNEL_MORNING: str = _require('SLACK_CHANNEL_MORNING')
SLACK_CHANNEL_EOD: str = _require('SLACK_CHANNEL_EOD')
SLACK_CHANNEL_ALERTS: str = _require('SLACK_CHANNEL_ALERTS')

# ── Perplexity 
PERPLEXITY_API_KEY: str = _require('PERPLEXITY_API_KEY')
PERPLEXITY_MODEL: str = _optional('PERPLEXITY_MODEL', 'sonar-pro')
PERPLEXITY_BASE_URL: str = _optional('PERPLEXITY_BASE_URL', 'https://api.perplexity.ai')

# ── StockInsights 
STOCKINSIGHTS_API_KEY: str = _require('STOCKINSIGHTS_API_KEY')
STOCKINSIGHTS_BASE_URL: str = _optional(
    'STOCKINSIGHTS_BASE_URL',
    'https://stockinsights-ai-main-95a26a0.zuplo.app/api/in/v0'
)

# ── NewsAPI 
NEWSAPI_KEY: str = _require('NEWSAPI_KEY')
NEWSAPI_BASE_URL: str = _optional('NEWSAPI_BASE_URL', 'https://newsapi.org/v2')

# ── Anthropic 
ANTHROPIC_API_KEY: str = _require('ANTHROPIC_API_KEY')
ANTHROPIC_MODEL: str = _optional('ANTHROPIC_MODEL', 'claude-opus-4-5')
ANTHROPIC_MAX_TOKENS: int = _int('ANTHROPIC_MAX_TOKENS', 4096)

# ── Briefing schedules (IST) 
MORNING_BRIEFING_TIME: str = _optional('MORNING_BRIEFING_TIME', '07:30')
EOD_WRAP_TIME: str = _optional('EOD_WRAP_TIME', '15:35')
HOLDINGS_SYNC_TIME: str = _optional('HOLDINGS_SYNC_TIME', '07:00')
EOD_HOLDINGS_SYNC_TIME: str = _optional('EOD_HOLDINGS_SYNC_TIME', '16:00')

# ── Alert thresholds 
EQUITY_DROP_ALERT_PCT: float = _float('EQUITY_DROP_ALERT_PCT', 8.0)
FUND_NAV_DROP_ALERT_PCT: float = _float('FUND_NAV_DROP_ALERT_PCT', 5.0)
INDIA_VIX_ALERT_THRESHOLD: float = _float('INDIA_VIX_ALERT_THRESHOLD', 25.0)
PROMOTER_PLEDGE_ALERT_PCT: float = _float('PROMOTER_PLEDGE_ALERT_PCT', 5.0)
ALERT_ACKNOWLEDGMENT_TIMEOUT_HOURS: int = _int('ALERT_ACKNOWLEDGMENT_TIMEOUT_HOURS', 2)

# ── Data pipeline intervals (minutes) 
NEWS_POLL_INTERVAL_MINUTES: int = _int('NEWS_POLL_INTERVAL_MINUTES', 240)
FILINGS_POLL_INTERVAL_MINUTES: int = _int('FILINGS_POLL_INTERVAL_MINUTES', 15)
NSE_RSS_POLL_INTERVAL_MINUTES: int = _int('NSE_RSS_POLL_INTERVAL_MINUTES', 30)
NEWSAPI_POLL_INTERVAL_MINUTES: int = _int('NEWSAPI_POLL_INTERVAL_MINUTES', 120)

# ── Market hours (IST) 
MARKET_OPEN_TIME: str = _optional('MARKET_OPEN_TIME', '09:15')
MARKET_CLOSE_TIME: str = _optional('MARKET_CLOSE_TIME', '15:30')
PRE_MARKET_START: str = _optional('PRE_MARKET_START', '08:00')
POST_MARKET_END: str = _optional('POST_MARKET_END', '16:30')

# ── Static external URLs 
AMFI_NAV_URL: str = 'https://www.amfiindia.com/spages/NAVAll.txt'

NSE_RSS_FEEDS: list[str] = [
    'https://www.nseindia.com/rss/corporate-announcement.xml',
    'https://www.nseindia.com/rss/board-meetings.xml',
]