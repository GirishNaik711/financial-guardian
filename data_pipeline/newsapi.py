"""
NewsAPI client for breaking Indian financial headlines.

Endpoint: https://newsapi.org/v2/
Free tier: 100 requests/day — sufficient at our 2-hour polling interval (~12 req/day).
"""

import time
import requests
from datetime import datetime, timedelta
from typing import List, Dict
from sqlalchemy import text
from config.settings import NEWSAPI_KEY, NEWSAPI_BASE_URL
from db.connection import get_db
from data_pipeline.pipeline_runner import (
    get_active_tickers, check_urgency,
    log_job_start, log_job_complete, log_job_failed
)
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger('newsapi')

# Cap per-ticker company search to conserve free tier quota.
MAX_TICKER_SEARCHES = 10


def get_params_base() -> Dict:
    return {'apiKey': NEWSAPI_KEY}


@with_retry(max_attempts=3, delay_seconds=10.0)
def fetch_top_india_business_headlines() -> List[Dict]:
    """
    Fetch top business headlines from India (macro context).
    Uses /top-headlines with country=in, category=business.
    """
    url = f"{NEWSAPI_BASE_URL}/top-headlines"
    params = {
        **get_params_base(),
        'country': 'in',
        'category': 'business',
        'pageSize': 20,
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()

    articles = response.json().get('articles', [])
    logger.info(f"NewsAPI: fetched {len(articles)} India business headlines")
    return articles


@with_retry(max_attempts=3, delay_seconds=10.0)
def fetch_company_news(query: str, from_date: str) -> List[Dict]:
    """
    Fetch news for a specific company from /everything endpoint.

    Args:
        query: Company name or ticker.
        from_date: YYYY-MM-DD.

    Returns:
        List of article dicts.
    """
    url = f"{NEWSAPI_BASE_URL}/everything"
    params = {
        **get_params_base(),
        'q': f'"{query}" India stock NSE',
        'language': 'en',
        'sortBy': 'publishedAt',
        'from': from_date,
        'pageSize': 5,
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    return response.json().get('articles', [])


def parse_article(article: Dict) -> Dict:
    """Parse NewsAPI article dict into news_items schema."""
    published_at = None
    published_str = article.get('publishedAt', '')
    if published_str:
        try:
            published_at = datetime.fromisoformat(
                published_str.replace('Z', '+00:00')
            )
        except ValueError:
            pass

    content = article.get('description') or article.get('title', '')

    return {
        'source': article.get('source', {}).get('name', 'NewsAPI'),
        'source_url': article.get('url', ''),
        'headline': (article.get('title') or '')[:200],
        'summary': content,
        'is_urgent': check_urgency(content),
        'published_at': published_at,
        'fetched_at': datetime.utcnow(),
    }


def store_articles(
    articles: List[Dict],
    related_tickers: List[str] = None,
    related_fund_codes: List[str] = None
) -> int:
    """
    Store parsed articles in news_items, deduplicating by source_url.

    Returns:
        Count of newly inserted records.
    """
    if not articles:
        return 0

    stored = 0

    with get_db() as db:
        for article in articles:
            source_url = article.get('source_url', '')

            if not source_url:
                continue

            existing = db.execute(
                text("SELECT id FROM news_items WHERE source_url = :url"),
                {'url': source_url}
            ).fetchone()

            if existing:
                continue

            db.execute(
                text("""
                    INSERT INTO news_items (
                        source, source_url, headline, summary,
                        related_tickers, related_fund_codes,
                        sentiment, is_urgent, published_at, fetched_at
                    ) VALUES (
                        :source, :source_url, :headline, :summary,
                        :related_tickers, :related_fund_codes,
                        'unknown', :is_urgent, :published_at, :fetched_at
                    )
                """),
                {
                    **article,
                    'related_tickers': related_tickers or [],
                    'related_fund_codes': related_fund_codes or []
                }
            )
            stored += 1

    return stored


def run_newsapi_pipeline() -> Dict:
    """
    Main pipeline entry point.
    1. Fetch top India business headlines.
    2. Fetch company-specific news for held tickers (capped at MAX_TICKER_SEARCHES).
    """
    job_id = log_job_start('newsapi_pipeline')

    try:
        total_stored = 0
        from_date = (datetime.utcnow() - timedelta(hours=24)).strftime('%Y-%m-%d')

        # --- Top India business headlines ---
        headlines = fetch_top_india_business_headlines()
        parsed_headlines = [parse_article(a) for a in headlines]
        stored = store_articles(parsed_headlines)
        total_stored += stored
        logger.info(f"NewsAPI: stored {stored} India business headlines")

        # --- Company-specific news ---
        tickers = get_active_tickers()

        with get_db() as db:
            result = db.execute(
                text("""
                    SELECT ticker, company_name FROM equity_holdings
                    WHERE is_active = TRUE AND company_name IS NOT NULL
                """)
            )
            ticker_names = {row[0]: row[1] for row in result}

        for ticker in tickers[:MAX_TICKER_SEARCHES]:
            query = ticker_names.get(ticker, ticker)
            try:
                articles = fetch_company_news(query, from_date)
                parsed = [parse_article(a) for a in articles]
                stored = store_articles(parsed, related_tickers=[ticker])
                total_stored += stored
                time.sleep(1)

            except Exception as e:
                logger.error(f"NewsAPI failed for {ticker}: {e}")
                continue

        log_job_complete(job_id, total_stored)
        return {'status': 'success', 'stored': total_stored}

    except Exception as e:
        logger.error(f"NewsAPI pipeline failed: {e}")
        log_job_failed(job_id, str(e))
        return {'status': 'error', 'error': str(e)}