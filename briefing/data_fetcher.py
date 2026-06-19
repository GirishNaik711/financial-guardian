"""
Briefing data fetcher.

Database-only reads — the interface between data populated by Phases
2/3/4 and the LLM synthesis pipeline. No external API calls here.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List
from sqlalchemy import text
from db.connection import get_db
from utils.logger import get_logger

logger = get_logger('briefing_data_fetcher')


def get_active_equity_holdings() -> List[Dict]:
    """Get all active equity holdings with current data."""
    with get_db() as db:
        result = db.execute(text("""
            SELECT ticker, company_name, quantity, avg_buy_price,
                   current_price, current_value, absolute_pnl,
                   pct_pnl, sector, last_synced_at
            FROM equity_holdings
            WHERE is_active = TRUE
            ORDER BY current_value DESC NULLS LAST
        """))
        return [dict(row._mapping) for row in result]


def get_active_fund_holdings() -> List[Dict]:
    """Get all active fund holdings with current data."""
    with get_db() as db:
        result = db.execute(text("""
            SELECT fund_code, fund_name, fund_type, fund_house,
                   units_held, purchase_nav, current_nav,
                   current_value, absolute_pnl, pct_pnl,
                   benchmark_index, fund_manager_name, last_synced_at
            FROM fund_holdings
            WHERE is_active = TRUE
            ORDER BY current_value DESC NULLS LAST
        """))
        return [dict(row._mapping) for row in result]


def get_recent_news_by_ticker(hours_back: int = 48) -> Dict[str, List[Dict]]:
    """Get recent news items grouped by ticker."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    with get_db() as db:
        result = db.execute(
            text("""
                SELECT id, source, source_url, headline, summary,
                       related_tickers, sentiment, is_urgent, published_at
                FROM news_items
                WHERE fetched_at > :cutoff
                  AND related_tickers IS NOT NULL
                  AND array_length(related_tickers, 1) > 0
                ORDER BY published_at DESC
            """),
            {'cutoff': cutoff}
        )
        rows = [dict(row._mapping) for row in result]

    by_ticker = {}
    for row in rows:
        for ticker in (row.get('related_tickers') or []):
            by_ticker.setdefault(ticker, []).append(row)

    return by_ticker


def get_recent_news_by_fund(hours_back: int = 168) -> Dict[str, List[Dict]]:
    """Get recent news items grouped by fund code (7-day default window)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    with get_db() as db:
        result = db.execute(
            text("""
                SELECT id, source, source_url, headline, summary,
                       related_fund_codes, sentiment, is_urgent, published_at
                FROM news_items
                WHERE fetched_at > :cutoff
                  AND related_fund_codes IS NOT NULL
                  AND array_length(related_fund_codes, 1) > 0
                ORDER BY published_at DESC
            """),
            {'cutoff': cutoff}
        )
        rows = [dict(row._mapping) for row in result]

    by_fund = {}
    for row in rows:
        for code in (row.get('related_fund_codes') or []):
            by_fund.setdefault(code, []).append(row)

    return by_fund


def get_recent_filings_by_ticker(hours_back: int = 24) -> Dict[str, List[Dict]]:
    """Get recent BSE/NSE filings grouped by ticker."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    with get_db() as db:
        result = db.execute(
            text("""
                SELECT filing_id, ticker, company_name, announcement_type,
                       summary_header, summary_text, sentiment,
                       source_url, published_at, is_urgent
                FROM corporate_filings
                WHERE fetched_at > :cutoff
                  AND ticker IS NOT NULL
                ORDER BY published_at DESC
            """),
            {'cutoff': cutoff}
        )
        rows = [dict(row._mapping) for row in result]

    by_ticker = {}
    for row in rows:
        ticker = row.get('ticker', '')
        if ticker:
            by_ticker.setdefault(ticker, []).append(row)

    return by_ticker


def get_latest_market_context() -> Dict:
    """Get the most recently stored market context. Empty dict if none."""
    with get_db() as db:
        result = db.execute(text("""
            SELECT * FROM market_context
            ORDER BY context_date DESC, context_time DESC
            LIMIT 1
        """)).fetchone()

        if result:
            row = dict(result._mapping)

            return {
                'market_date': str(row.get('context_date', '')),
                'indices': {
                    'nifty_50': {
                        'current_value': row.get('nifty_50_value'),
                        'change_pct': row.get('nifty_50_change_pct')
                    },
                    'sensex': {
                        'current_value': row.get('sensex_value'),
                        'change_pct': row.get('sensex_change_pct')
                    },
                    'india_vix': {
                        'current_value': row.get('india_vix')
                    }
                },
                'flows': {
                    'fii_net_cr': row.get('fii_net_flow_cr'),
                    'dii_net_cr': row.get('dii_net_flow_cr')
                },
                'global': {
                    'usd_inr': {'value': row.get('usd_inr')},
                    'crude_oil': {'value': row.get('crude_oil_usd')},
                    'sp500': {'change_pct': row.get('sp500_change_pct')},
                    'nasdaq': {'change_pct': row.get('nasdaq_change_pct')}
                },
                'market_regime': row.get('market_regime', 'unknown'),
                'key_alerts': [],
                'geopolitical': {
                    'content': row.get('geopolitical_summary', ''),
                    'citations': []
                }
            }

        logger.warning("No market context found in database")
        return {}


def get_unacknowledged_alerts() -> List[Dict]:
    """Get urgent alerts unacknowledged for over 2 hours, for the morning banner."""
    with get_db() as db:
        result = db.execute(text("""
            SELECT id, alert_type, title, message, source_url, fired_at
            FROM alerts
            WHERE is_acknowledged = FALSE
              AND severity = 'urgent'
              AND fired_at < NOW() - INTERVAL '2 hours'
            ORDER BY fired_at DESC
        """))
        return [dict(row._mapping) for row in result]