"""
Citation builder for Slack message formatting.

Converts markdown links [Name](URL) (used by the LLM) into Slack's
<URL|Name> hyperlink format, and builds source attribution blocks.
"""

import re
from typing import List
from urllib.parse import urlparse

SOURCE_NAMES = {
    'economictimes.indiatimes.com': 'Economic Times',
    'moneycontrol.com': 'Moneycontrol',
    'bqprime.com': 'BQ Prime',
    'bloombergquint.com': 'Bloomberg Quint',
    'livemint.com': 'Mint',
    'business-standard.com': 'Business Standard',
    'financialexpress.com': 'Financial Express',
    'nseindia.com': 'NSE Filing',
    'bseindia.com': 'BSE Filing',
    'sebi.gov.in': 'SEBI',
    'rbi.org.in': 'RBI',
    'amfiindia.com': 'AMFI',
    'reuters.com': 'Reuters',
    'bloomberg.com': 'Bloomberg',
}


def get_source_name(url: str) -> str:
    """Extract a friendly source name from a URL."""
    try:
        domain = urlparse(url).netloc.lower().replace('www.', '')

        for key, name in SOURCE_NAMES.items():
            if key in domain:
                return name

        parts = domain.split('.')
        if len(parts) >= 2:
            return parts[-2].title()

        return 'Source'
    except Exception:
        return 'Source'


def markdown_to_slack_links(text: str) -> str:
    """Convert markdown links [Name](URL) to Slack format <URL|Name>."""
    pattern = r'\[([^\]]+)\]\(([^)]+)\)'

    def replace_link(match):
        name = match.group(1)
        url = match.group(2)
        if url.startswith('http'):
            return f'<{url}|{name}>'
        return name

    return re.sub(pattern, replace_link, text)


def format_citations_block(citations: List[str]) -> str:
    """Format a list of citation URLs as a Slack message block."""
    if not citations:
        return ''

    unique_citations = list(dict.fromkeys(citations))[:8]

    lines = ["\n_Sources:_"]
    for url in unique_citations:
        name = get_source_name(url)
        lines.append(f"• <{url}|{name}>")

    return '\n'.join(lines)


def process_briefing_citations(briefing_text: str) -> str:
    """Convert markdown links in a briefing to Slack hyperlink format."""
    return markdown_to_slack_links(briefing_text)