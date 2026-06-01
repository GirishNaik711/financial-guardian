import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / '.env')

# Application
APP_ENV = os.getenv('APP_ENV', 'development')
APP_NAME = os.getenv('APP_NAME', 'financial-guardian')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
TIMEZONE = os.getenv('TIMEZONE', 'Asia/Kolkata')
IS_PRODUCTION = APP_ENV == 'production'

# Database
DATABASE_URL = os.environ['DATABASE_URL']  # Required — fails fast if missing
DATABASE_POOL_SIZE = int(os.getenv('DATABASE_POOL_SIZE', '5'))
DATABASE_MAX_OVERFLOW = int(os.getenv('DATABASE_MAX_OVERFLOW', '10'))

# Redis
REDIS_URL = os.environ['REDIS_URL']

# Kite Connect
KITE_API_KEY = os.environ['KITE_API_KEY']
KITE_API_SECRET = os.environ['KITE_API_SECRET']
KITE_ACCESS_TOKEN = os.getenv('KITE_ACCESS_TOKEN', '')

# Groww
GROWW_API_BASE_URL = os.getenv('GROWW_API_BASE_URL', 'https://groww.in/v1/api')
GROWW_AUTH_TOKEN = os.environ['GROWW_AUTH_TOKEN']

# Google Sheets
GOOGLE_SHEETS_CREDENTIALS_PATH = os.getenv(
    'GOOGLE_SHEETS_CREDENTIALS_PATH',
    str(BASE_DIR / 'config' / 'google_service_account.json')
)
WATCHLIST_SHEET_ID = os.environ['WATCHLIST_SHEET_ID']
WATCHLIST_TAB_NAME = os.getenv('WATCHLIST_TAB_NAME', 'Watchlist')

# Slack
SLACK_BOT_TOKEN = os.environ['SLACK_BOT_TOKEN']
SLACK_SIGNING_SECRET = os.environ['SLACK_SIGNING_SECRET']
SLACK_CHANNEL_MORNING = os.environ['SLACK_CHANNEL_MORNING']
SLACK_CHANNEL_EOD = os.environ['SLACK_CHANNEL_EOD']
SLACK_CHANNEL_ALERTS = os.environ['SLACK_CHANNEL_ALERTS']

# Perplexity
PERPLEXITY_API_KEY = os.environ['PERPLEXITY_API_KEY']
PERPLEXITY_MODEL = os.getenv('PERPLEXITY_MODEL', 'sonar-pro')
PERPLEXITY_BASE_URL = os.getenv('PERPLEXITY_BASE_URL', 'https://api.perplexity.ai')

# StockInsights
STOCKINSIGHTS_API_KEY = os.environ['STOCKINSIGHTS_API_KEY']
STOCKINSIGHTS_BASE_URL = os.getenv(
    'STOCKINSIGHTS_BASE_URL',
    'https://stockinsights-ai-main-95a26a0.zuplo.app/api/in/v0'
)

# NewsAPI
NEWSAPI_KEY = os.environ['NEWSAPI_KEY']
NEWSAPI_BASE_URL = os.getenv('NEWSAPI_BASE_URL', 'https://newsapi.org/v2')

# Anthropic
ANTHROPIC_API_KEY = os.environ['ANTHROPIC_API_KEY']
ANTHROPIC_MODEL = os.getenv('ANTHROPIC_MODEL', 'claude-opus-4-5')
ANTHROPIC_MAX_TOKENS = int(os.getenv('ANTHROPIC_MAX_TOKENS', '4096'))

# Briefing schedules (IST)
MORNING_BRIEFING_TIME = os.getenv('MORNING_BRIEFING_TIME', '07:30')
EOD_WRAP_TIME = os.getenv('EOD_WRAP_TIME', '15:35')
HOLDINGS_SYNC_TIME = os.getenv('HOLDINGS_SYNC_TIME', '07:00')
EOD_HOLDINGS_SYNC_TIME = os.getenv('EOD_HOLDINGS_SYNC_TIME', '16:00')

# Alert thresholds
EQUITY_DROP_ALERT_PCT = float(os.getenv('EQUITY_DROP_ALERT_PCT', '8.0'))
FUND_NAV_DROP_ALERT_PCT = float(os.getenv('FUND_NAV_DROP_ALERT_PCT', '5.0'))
INDIA_VIX_ALERT_THRESHOLD = float(os.getenv('INDIA_VIX_ALERT_THRESHOLD', '25.0'))
PROMOTER_PLEDGE_ALERT_PCT = float(os.getenv('PROMOTER_PLEDGE_ALERT_PCT', '5.0'))
ALERT_ACKNOWLEDGMENT_TIMEOUT_HOURS = int(
    os.getenv('ALERT_ACKNOWLEDGMENT_TIMEOUT_HOURS', '2')
)

# Data pipeline intervals (minutes)
NEWS_POLL_INTERVAL_MINUTES = int(os.getenv('NEWS_POLL_INTERVAL_MINUTES', '240'))
FILINGS_POLL_INTERVAL_MINUTES = int(os.getenv('FILINGS_POLL_INTERVAL_MINUTES', '15'))
NSE_RSS_POLL_INTERVAL_MINUTES = int(os.getenv('NSE_RSS_POLL_INTERVAL_MINUTES', '30'))
NEWSAPI_POLL_INTERVAL_MINUTES = int(os.getenv('NEWSAPI_POLL_INTERVAL_MINUTES', '120'))

# Market hours (IST)
MARKET_OPEN_TIME = os.getenv('MARKET_OPEN_TIME', '09:15')
MARKET_CLOSE_TIME = os.getenv('MARKET_CLOSE_TIME', '15:30')
PRE_MARKET_START = os.getenv('PRE_MARKET_START', '08:00')
POST_MARKET_END = os.getenv('POST_MARKET_END', '16:30')

# AMFI NAV URL
AMFI_NAV_URL = 'https://www.amfiindia.com/spages/NAVAll.txt'

# NSE RSS feeds
NSE_RSS_FEEDS = [
    'https://www.nseindia.com/rss/corporate-announcement.xml',
    'https://www.nseindia.com/rss/board-meetings.xml',
]