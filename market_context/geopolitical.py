"""
Geopolitical and macro news fetcher.

Reuses the Perplexity client pattern from Phase 3 with a
geopolitics-specific prompt.
"""

import requests
from datetime import datetime, timezone
from typing import Dict
from config import PERPLEXITY_API_KEY, PERPLEXITY_MODEL, PERPLEXITY_BASE_URL
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger('geopolitical')

GEOPOLITICAL_PROMPT = """Search for today's geopolitical and macro developments that could affect Indian financial markets.

Focus on:
1. Active conflicts and their effect on oil prices and supply chains (Middle East, Russia-Ukraine, any new escalations)
2. US-India trade relations, tariffs, or sanctions
3. China-India border or trade tensions
4. Global central bank decisions (Fed, ECB, Bank of Japan) from the last 48 hours
5. Commodity supply disruptions affecting India (oil, metals, semiconductors)
6. Major political events in top trading partners (US, China, Middle East)
7. Any IMF/World Bank warnings or reports about India or global economy

For each item, briefly explain the potential impact on Indian markets.
Keep response under 400 words.
Include source citations for all claims."""


@with_retry(max_attempts=3, delay_seconds=15.0)
def fetch_geopolitical_context() -> Dict:
    """
    Fetch geopolitical context using Perplexity API.

    Returns:
        Dict with content text and citations list.
    """
    url = f"{PERPLEXITY_BASE_URL}/chat/completions"

    headers = {
        'Authorization': f'Bearer {PERPLEXITY_API_KEY}',
        'Content-Type': 'application/json'
    }

    payload = {
        "model": PERPLEXITY_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a geopolitical analyst focused on events that affect "
                    "Indian financial markets. Be factual, concise, and cite sources."
                )
            },
            {
                "role": "user",
                "content": GEOPOLITICAL_PROMPT
            }
        ],
        "max_tokens": 600,
        "temperature": 0.1,
        "return_citations": True,
        "search_recency_filter": "day"
    }

    response = requests.post(url, headers=headers, json=payload, timeout=45)
    response.raise_for_status()

    data = response.json()
    content = data['choices'][0]['message']['content']
    citations = data.get('citations', [])

    logger.info(
        f"Geopolitical context fetched: {len(content)} chars, {len(citations)} citations"
    )

    return {
        'content': content,
        'citations': citations,
        'fetched_at': datetime.now(timezone.utc).isoformat()
    }