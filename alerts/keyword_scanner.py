"""
Keyword scanner for urgent content detection.
Used by data_pipeline (Phase 3) to flag news as is_urgent,
and by trigger_engine (Phase 6) to identify which keyword fired.
"""

import yaml
from pathlib import Path
from typing import Optional, List

_keywords_cache = None


def _load_keywords() -> dict:
    global _keywords_cache
    if _keywords_cache is None:
        path = Path(__file__).parent.parent / 'config' / 'alert_keywords.yaml'
        with open(path, 'r') as f:
            _keywords_cache = yaml.safe_load(f)
    return _keywords_cache


def scan_text_for_urgency(text: str) -> Optional[str]:
    """Return the first matched critical keyword found in text, or None."""
    if not text:
        return None

    keywords = _load_keywords()
    critical = keywords.get('critical', [])
    text_lower = text.lower()

    for keyword in critical:
        if keyword.lower() in text_lower:
            return keyword

    return None


def get_warning_keywords() -> List[str]:
    keywords = _load_keywords()
    return keywords.get('warning', [])


def scan_text_for_warnings(text: str) -> List[str]:
    if not text:
        return []

    keywords = get_warning_keywords()
    text_lower = text.lower()

    return [kw for kw in keywords if kw.lower() in text_lower]