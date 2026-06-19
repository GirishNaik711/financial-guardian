"""
StockInsights.ai Announcements API client.

Fetches BSE/NSE corporate filings with AI-generated summaries
and sentiment tags for monitored holdings.

API: https://stockinsights-ai-main-95a26a0.zuplo.app/api/in/v0
Endpoint: GET /documents/announcement
Polling: Every 15 minutes during market hours.
"""

import requests
from datetime import datetime, timedelta
from typing import List, Dict
from sqlalchemy import text
from config.settings import STOCKINSIGHTS_API_KEY, STOCKINSIGHTS_BASE_URL
from db.connection import get_db
from data_pipeline.pipeline_runner import (
    get_active_tickers, check_urgency,
    log_job_start, log_job_complete, log_job_failed
)
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger('stockinsights')

BATCH_SIZE = 20


def get_headers() -> Dict[str, str]:
    return {
        'Authorization': f'Bearer {STOCKINSIGHTS_API_KEY}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }


def format_ticker_params(tickers: List[str]) -> str:
    """Format tickers as NSE:TICKER,NSE:TICKER2 for API."""
    return ','.join(f'NSE:{t}' for t in tickers)


@with_retry(max_attempts=3, delay_seconds=10.0)
def fetch_announcements(tickers: List[str], start_date: str, limit: int = 50) -> List[Dict]:
    """
    Fetch announcements from StockInsights API.

    Args:
        tickers: List of NSE ticker symbols.
        start_date: YYYY-MM-DD, fetch from this date.
        limit: Max results (default 50, max 100).

    Returns:
        List of raw announcement dicts.
    """
    if not tickers:
        return []

    url = f"{STOCKINSIGHTS_BASE_URL}/documents/announcement"
    params = {
        'tickers': format_ticker_params(tickers),
        'start_date': start_date,
        'limit': limit
    }

    response = requests.get(url, headers=get_headers(), params=params, timeout=30)
    response.raise_for_status()

    data = response.json()
    announcements = data.get('data', [])
    logger.info(
        f"StockInsights: fetched {len(announcements)} announcements "
        f"for {len(tickers)} tickers since {start_date}"
    )
    return announcements


def parse_announcement(raw: Dict) -> Dict:
    """Parse raw StockInsights announcement into corporate_filings schema."""
    insights = raw.get('ai_insights', {})
    summary_header = insights.get('summary_header', '')
    summary_text = insights.get('summary_text', '')
    full_text = f"{summary_header}\n\n{summary_text}".strip()

    is_urgent = check_urgency(full_text)

    published_at = None
    published_str = raw.get('published_date', '')
    if published_str:
        try:
            published_at = datetime.fromisoformat(published_str.replace('Z', '+00:00'))
        except ValueError:
            pass

    return {
        'filing_id': raw.get('id', ''),
        'ticker': raw.get('ticker', ''),
        'company_name': raw.get('company_name', ''),
        'exchange': 'NSE',
        'announcement_type': insights.get('announcement_type', ''),
        'summary_header': summary_header,
        'summary_text': summary_text,
        'sentiment': insights.get('sentiment', 'unknown'),
        'source_url': raw.get('source_link', ''),
        'published_at': published_at,
        'is_urgent': is_urgent,
        'fetched_at': datetime.utcnow(),
    }


def store_announcements(announcements: List[Dict]) -> int:
    """
    Upsert announcements into corporate_filings.
    Skips duplicates by filing_id.

    Returns:
        Count of newly inserted records.
    """
    if not announcements:
        return 0

    stored_count = 0

    with get_db() as db:
        for ann in announcements:
            result = db.execute(
                text("""
                    INSERT INTO corporate_filings (
                        filing_id, ticker, company_name, exchange,
                        announcement_type, summary_header, summary_text,
                        sentiment, source_url, published_at,
                        is_urgent, fetched_at
                    ) VALUES (
                        :filing_id, :ticker, :company_name, :exchange,
                        :announcement_type, :summary_header, :summary_text,
                        :sentiment, :source_url, :published_at,
                        :is_urgent, :fetched_at
                    )
                    ON CONFLICT (filing_id) DO NOTHING
                    RETURNING id
                """),
                ann
            )
            if result.rowcount > 0:
                stored_count += 1

    if stored_count > 0:
        urgent_count = sum(1 for a in announcements if a['is_urgent'])
        logger.info(f"Stored {stored_count} new filings ({urgent_count} urgent)")

    return stored_count


def run_filings_pipeline() -> Dict:
    """
    Fetch and store filings for all active tickers from the last 24 hours.
    Processes tickers in batches of 20.
    """
    job_id = log_job_start('stockinsights_filings')

    try:
        tickers = get_active_tickers()

        if not tickers:
            logger.warning("No active tickers — skipping filings pipeline")
            log_job_complete(job_id, 0)
            return {'status': 'skipped', 'reason': 'no_active_tickers'}

        start_date = (datetime.utcnow() - timedelta(hours=24)).strftime('%Y-%m-%d')
        all_announcements = []

        for i in range(0, len(tickers), BATCH_SIZE):
            batch = tickers[i:i + BATCH_SIZE]
            results = fetch_announcements(batch, start_date)
            all_announcements.extend(results)

        parsed = [parse_announcement(a) for a in all_announcements]
        stored = store_announcements(parsed)

        log_job_complete(job_id, stored)
        return {
            'status': 'success',
            'fetched': len(all_announcements),
            'stored': stored,
            'urgent': sum(1 for p in parsed if p['is_urgent'])
        }

    except Exception as e:
        logger.error(f"Filings pipeline failed: {e}")
        log_job_failed(job_id, str(e))
        return {'status': 'error', 'error': str(e)}