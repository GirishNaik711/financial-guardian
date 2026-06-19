"""
Perplexity API client for synthesized news with citations.

Model: sonar-pro
Endpoint: POST https://api.perplexity.ai/chat/completions
Runs every 4 hours for equity news; weekly for fund news.
"""

import time
import requests
from datetime import datetime
from typing import List, Dict, Tuple
from sqlalchemy import text
from config.settings import PERPLEXITY_API_KEY, PERPLEXITY_MODEL, PERPLEXITY_BASE_URL
from db.connection import get_db
from data_pipeline.pipeline_runner import (
    get_active_tickers, get_active_fund_identifiers,
    check_urgency, log_job_start, log_job_complete, log_job_failed
)
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger('perplexity')

REQUEST_DELAY_SECONDS = 2


def get_headers() -> Dict[str, str]:
    return {
        'Authorization': f'Bearer {PERPLEXITY_API_KEY}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }


def build_equity_news_prompt(ticker: str, company_name: str = '') -> str:
    name_part = f"({company_name})" if company_name else ""
    return f"""Search for recent news about {ticker} {name_part} listed on NSE India.

Focus on news from the last 24-48 hours only. Include:
1. Any earnings results, revenue figures, or financial updates
2. Regulatory actions, SEBI notices, or ED/IT department actions
3. Management changes (CEO, CFO, key executive changes)
4. Promoter activity (buying, selling, pledge changes)
5. Corporate actions (dividends, buybacks, rights issues, mergers)
6. Any significant business developments or contract wins/losses
7. Analyst upgrades or downgrades

If there is no significant news in the last 48 hours, clearly state that.
Provide a brief sentiment assessment: bullish, bearish, or neutral.
Keep your response concise — maximum 200 words.
Include source citations for all factual claims."""


def build_fund_news_prompt(fund_name: str, fund_house: str = '') -> str:
    return f"""Search for recent news about the mutual fund "{fund_name}" \
by {fund_house if fund_house else 'the fund house'} in India.

Focus on news from the last 7 days. Include:
1. Any fund manager changes
2. Fund performance vs benchmark
3. Significant AUM changes or large redemptions
4. Any regulatory actions against the fund or AMC
5. Change in fund investment strategy or mandate
6. Any news about the AMC (fund house) itself

If there is no significant news in the last 7 days, clearly state that.
Keep your response concise — maximum 150 words.
Include source citations for all factual claims."""


def build_macro_news_prompt() -> str:
    return """Search for today's most important financial news affecting Indian markets.

Include:
1. Nifty 50 and Sensex performance today
2. FII/DII net flow data if available
3. RBI or government policy announcements
4. US market moves overnight and their India impact
5. INR/USD exchange rate movement
6. Crude oil price movement
7. Any geopolitical developments affecting Indian markets
8. India VIX level

Keep your response structured and concise — maximum 300 words.
Include source citations for all data points."""


@with_retry(max_attempts=3, delay_seconds=15.0)
def query_perplexity(prompt: str) -> Tuple[str, List[str]]:
    """
    Query Perplexity sonar-pro with a prompt.

    Returns:
        (response_text, list_of_citation_urls)
    """
    url = f"{PERPLEXITY_BASE_URL}/chat/completions"

    payload = {
        "model": PERPLEXITY_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a financial news analyst specializing in Indian markets. "
                    "Always cite your sources. Be factual and concise. "
                    "If you cannot find recent information, say so clearly."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "max_tokens": 500,
        "temperature": 0.1,
        "return_citations": True,
        "search_recency_filter": "day"
    }

    response = requests.post(url, headers=get_headers(), json=payload, timeout=45)
    response.raise_for_status()

    data = response.json()
    content = data['choices'][0]['message']['content']
    citations = data.get('citations', [])

    return content, citations


def store_news_item(
    content: str,
    citations: List[str],
    related_tickers: List[str] = None,
    related_fund_codes: List[str] = None,
    source: str = 'perplexity'
) -> int:
    """
    Insert a news item into news_items table.

    Returns:
        ID of inserted record.
    """
    source_url = citations[0] if citations else None
    is_urgent = check_urgency(content)

    with get_db() as db:
        result = db.execute(
            text("""
                INSERT INTO news_items (
                    source, source_url, headline, summary,
                    related_tickers, related_fund_codes,
                    sentiment, is_urgent, published_at, fetched_at
                ) VALUES (
                    :source, :source_url, :headline, :summary,
                    :related_tickers, :related_fund_codes,
                    'unknown', :is_urgent, NOW(), NOW()
                )
                RETURNING id
            """),
            {
                'source': source,
                'source_url': source_url,
                'headline': content[:200],
                'summary': content,
                'related_tickers': related_tickers or [],
                'related_fund_codes': related_fund_codes or [],
                'is_urgent': is_urgent
            }
        )
        return result.fetchone()[0]


def run_equity_news_pipeline() -> Dict:
    """Fetch news for all active equity holdings via Perplexity."""
    job_id = log_job_start('perplexity_equity_news')

    try:
        tickers = get_active_tickers()

        if not tickers:
            log_job_complete(job_id, 0)
            return {'status': 'skipped', 'reason': 'no_active_tickers'}

        with get_db() as db:
            result = db.execute(
                text("""
                    SELECT ticker, company_name FROM equity_holdings
                    WHERE is_active = TRUE
                """)
            )
            ticker_names = {row[0]: row[1] or '' for row in result}

        stored_count = 0

        for ticker in tickers:
            try:
                company_name = ticker_names.get(ticker, '')
                prompt = build_equity_news_prompt(ticker, company_name)
                content, citations = query_perplexity(prompt)

                store_news_item(
                    content=content,
                    citations=citations,
                    related_tickers=[ticker]
                )
                stored_count += 1
                logger.debug(f"Fetched Perplexity news for {ticker}")
                time.sleep(REQUEST_DELAY_SECONDS)

            except Exception as e:
                logger.error(f"Failed to fetch Perplexity news for {ticker}: {e}")
                continue

        log_job_complete(job_id, stored_count)
        return {'status': 'success', 'count': stored_count}

    except Exception as e:
        logger.error(f"Perplexity equity news pipeline failed: {e}")
        log_job_failed(job_id, str(e))
        return {'status': 'error', 'error': str(e)}


def run_fund_news_pipeline() -> Dict:
    """Fetch news for all active mutual fund holdings via Perplexity."""
    job_id = log_job_start('perplexity_fund_news')

    try:
        funds = get_active_fund_identifiers()

        if not funds:
            log_job_complete(job_id, 0)
            return {'status': 'skipped', 'reason': 'no_active_funds'}

        stored_count = 0

        for fund in funds:
            try:
                fund_name = fund.get('fund_name') or fund.get('display_name', '')
                fund_house = fund.get('fund_house', '')
                fund_code = fund.get('fund_code') or fund.get('identifier', '')

                prompt = build_fund_news_prompt(fund_name, fund_house)
                content, citations = query_perplexity(prompt)

                store_news_item(
                    content=content,
                    citations=citations,
                    related_fund_codes=[fund_code]
                )
                stored_count += 1
                time.sleep(REQUEST_DELAY_SECONDS)

            except Exception as e:
                logger.error(f"Failed to fetch news for fund {fund}: {e}")
                continue

        log_job_complete(job_id, stored_count)
        return {'status': 'success', 'count': stored_count}

    except Exception as e:
        logger.error(f"Perplexity fund news pipeline failed: {e}")
        log_job_failed(job_id, str(e))
        return {'status': 'error', 'error': str(e)}


def fetch_macro_context_news() -> Dict:
    """
    Fetch macro/geopolitical context news.
    Called by both this pipeline and the market context layer (Phase 4).
    """
    try:
        prompt = build_macro_news_prompt()
        content, citations = query_perplexity(prompt)

        store_news_item(
            content=content,
            citations=citations,
            source='perplexity_macro'
        )

        return {
            'status': 'success',
            'content': content,
            'citations': citations
        }

    except Exception as e:
        logger.error(f"Failed to fetch macro context news: {e}")
        return {'status': 'error', 'error': str(e)}