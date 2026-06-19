"""
NSE RSS feed poller.

Feeds:
    Corporate announcements: https://www.nseindia.com/rss/corporate-announcement.xml
    Board meetings:          https://www.nseindia.com/rss/board-meetings.xml

NSE feeds can be intermittently unavailable; StockInsights is the primary
filings source. NSE RSS is a supplementary signal.
"""

import feedparser
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import List, Dict, Optional
from sqlalchemy import text
from config.settings import NSE_RSS_FEEDS
from db.connection import get_db
from data_pipeline.pipeline_runner import (
    get_active_tickers, check_urgency,
    log_job_start, log_job_complete, log_job_failed
)
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger('nse_rss')


@with_retry(max_attempts=3, delay_seconds=30.0)
def fetch_rss_feed(url: str) -> List:
    """
    Fetch and parse an RSS feed URL.

    Returns:
        List of feed entry objects from feedparser.
    """
    feed = feedparser.parse(url)

    if feed.bozo:
        logger.warning(f"RSS parse warning for {url}: {feed.bozo_exception}")

    logger.debug(f"Fetched {len(feed.entries)} entries from {url}")
    return feed.entries


def extract_ticker_from_entry(title: str, description: str) -> Optional[str]:
    """
    Check if any active ticker appears in the entry title or description.

    Returns:
        Matched ticker symbol or None.
    """
    active_tickers = get_active_tickers()
    combined = (title + ' ' + description).upper()

    for ticker in active_tickers:
        if ticker.upper() in combined:
            return ticker

    return None


def parse_rss_entry(entry) -> Optional[Dict]:
    """
    Parse a feedparser entry into corporate_filings schema.

    Returns:
        Parsed dict or None if entry lacks a unique identifier.
    """
    title = getattr(entry, 'title', '') or ''
    summary = (
        getattr(entry, 'summary', '') or
        getattr(entry, 'description', '') or
        ''
    )
    link = getattr(entry, 'link', '') or ''

    published_at = None
    pub_date = getattr(entry, 'published', None)
    if pub_date:
        try:
            published_at = parsedate_to_datetime(pub_date)
        except Exception:
            pass

    ticker = extract_ticker_from_entry(title, summary)

    guid = (
        getattr(entry, 'id', None) or
        getattr(entry, 'guid', None) or
        link
    )
    if not guid:
        return None

    full_text = f"{title} {summary}"
    is_urgent = check_urgency(full_text)

    return {
        'filing_id': f"nse_rss_{abs(hash(guid))}",
        'ticker': ticker,
        'company_name': None,
        'exchange': 'NSE',
        'announcement_type': 'RSS Announcement',
        'summary_header': title[:200],
        'summary_text': summary,
        'sentiment': 'unknown',
        'source_url': link,
        'published_at': published_at,
        'is_urgent': is_urgent,
        'fetched_at': datetime.utcnow(),
    }


def store_rss_filings(filings: List[Dict]) -> int:
    """
    Insert RSS filings into corporate_filings.
    Deduplicates by filing_id.

    Returns:
        Count of newly inserted records.
    """
    if not filings:
        return 0

    stored = 0

    with get_db() as db:
        for filing in filings:
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
                filing
            )
            if result.rowcount > 0:
                stored += 1

    return stored


def run_nse_rss_pipeline() -> Dict:
    """Main entry point for NSE RSS pipeline."""
    job_id = log_job_start('nse_rss_pipeline')

    try:
        total_stored = 0

        for feed_url in NSE_RSS_FEEDS:
            try:
                entries = fetch_rss_feed(feed_url)
                parsed = [parse_rss_entry(e) for e in entries]
                valid = [p for p in parsed if p is not None]
                stored = store_rss_filings(valid)
                total_stored += stored

                logger.info(
                    f"RSS {feed_url}: {len(entries)} entries, "
                    f"{len(valid)} parsed, {stored} new stored"
                )

            except Exception as e:
                logger.error(f"RSS feed failed for {feed_url}: {e}")
                continue

        log_job_complete(job_id, total_stored)
        return {'status': 'success', 'stored': total_stored}

    except Exception as e:
        logger.error(f"NSE RSS pipeline failed: {e}")
        log_job_failed(job_id, str(e))
        return {'status': 'error', 'error': str(e)}