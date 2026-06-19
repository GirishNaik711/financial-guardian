"""
Pipeline runner utilities.
Shared functions used across all pipeline modules.
"""

from typing import List, Dict
from sqlalchemy import text
from db.connection import get_db
from utils.logger import get_logger

logger = get_logger('pipeline_runner')


def get_active_tickers() -> List[str]:
    """
    Get list of active equity ticker symbols from database.
    Includes holdings and watchlist stocks.
    """
    with get_db() as db:
        result = db.execute(
            text("""
                SELECT ticker FROM equity_holdings WHERE is_active = TRUE
                UNION
                SELECT identifier FROM watchlist
                WHERE is_active = TRUE AND item_type = 'stock'
            """)
        )
        tickers = [row[0] for row in result]

    logger.debug(f"Active tickers for pipeline: {tickers}")
    return tickers


def get_active_fund_identifiers() -> List[Dict]:
    """
    Get list of active fund codes and names from database.
    Returns dicts with fund_code and fund_name for flexible matching.
    """
    with get_db() as db:
        result = db.execute(
            text("""
                SELECT fund_code, fund_name, fund_house
                FROM fund_holdings WHERE is_active = TRUE
                UNION
                SELECT identifier, display_name, ''
                FROM watchlist
                WHERE is_active = TRUE AND item_type = 'fund'
            """)
        )
        funds = [dict(row._mapping) for row in result]

    return funds


def get_all_monitored_identifiers() -> Dict:
    """
    Get all identifiers being monitored.
    Returns dict with tickers list and funds list.
    """
    return {
        'tickers': get_active_tickers(),
        'funds': get_active_fund_identifiers()
    }


def load_alert_keywords() -> Dict[str, List[str]]:
    """Load alert keywords from config file."""
    import yaml
    from pathlib import Path

    keywords_path = Path(__file__).parent.parent / 'config' / 'alert_keywords.yaml'

    with open(keywords_path, 'r') as f:
        return yaml.safe_load(f)


def check_urgency(text_content: str) -> bool:
    """
    Check if text contains any critical alert keywords.
    Returns True if content should trigger an urgent alert.
    """
    keywords = load_alert_keywords()
    critical_keywords = keywords.get('critical', [])

    text_lower = text_content.lower()

    for keyword in critical_keywords:
        if keyword.lower() in text_lower:
            return True

    return False


def log_job_start(job_name: str) -> int:
    """Log job start and return job log ID."""
    with get_db() as db:
        result = db.execute(
            text("""
                INSERT INTO job_logs (job_name, status, started_at)
                VALUES (:job_name, 'started', NOW())
                RETURNING id
            """),
            {'job_name': job_name}
        )
        return result.fetchone()[0]


def log_job_complete(job_id: int, records_processed: int = 0):
    """Log job completion."""
    with get_db() as db:
        db.execute(
            text("""
                UPDATE job_logs
                SET status = 'completed',
                    completed_at = NOW(),
                    duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at)),
                    records_processed = :records
                WHERE id = :job_id
            """),
            {'records': records_processed, 'job_id': job_id}
        )


def log_job_failed(job_id: int, error_message: str):
    """Log job failure."""
    with get_db() as db:
        db.execute(
            text("""
                UPDATE job_logs
                SET status = 'failed',
                    completed_at = NOW(),
                    duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at)),
                    error_message = :error
                WHERE id = :job_id
            """),
            {'error': error_message[:1000], 'job_id': job_id}
        )