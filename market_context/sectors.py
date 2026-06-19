"""
Sector performance tracker.

Identifies sectors the owner is exposed to via equity_holdings.sector,
then fetches performance for those sectors.
"""

from typing import Dict, List
from sqlalchemy import text
from db.connection import get_db
from market_context.nifty import fetch_sector_performance
from utils.logger import get_logger

logger = get_logger('sectors')


def get_held_sectors() -> List[str]:
    """Get list of unique sectors from active equity holdings."""
    with get_db() as db:
        result = db.execute(
            text("""
                SELECT DISTINCT sector
                FROM equity_holdings
                WHERE is_active = TRUE AND sector IS NOT NULL
            """)
        )
        return [row[0] for row in result]


def get_sector_context() -> Dict:
    """Build sector performance context for all held sectors."""
    held_sectors = get_held_sectors()

    if not held_sectors:
        logger.warning("No sector information available for held stocks")
        return {}

    logger.info(f"Fetching sector performance for: {held_sectors}")
    sector_data = fetch_sector_performance(held_sectors)

    for sector, data in sector_data.items():
        direction = "UP" if data['change_pct'] > 0 else "DOWN"
        logger.info(f"Sector {sector}: {direction} {abs(data['change_pct']):.2f}%")

    return sector_data