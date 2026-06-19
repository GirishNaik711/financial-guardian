"""
AMFI NAV data fetcher.

Source: https://www.amfiindia.com/spages/NAVAll.txt
Format: semicolon-separated, ISO-8859-1 encoded.
Updated daily after market close (~9pm IST).
"""

import requests
from datetime import datetime, date
from typing import Dict, List
from sqlalchemy import text
from config.settings import AMFI_NAV_URL
from db.connection import get_db
from data_pipeline.pipeline_runner import (
    get_active_fund_identifiers,
    log_job_start, log_job_complete, log_job_failed
)
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger('amfi')


@with_retry(max_attempts=3, delay_seconds=30.0)
def download_nav_file() -> str:
    """
    Download full AMFI NAV file.

    Returns:
        Raw text content (ISO-8859-1 decoded).
    """
    response = requests.get(
        AMFI_NAV_URL,
        timeout=60,
        headers={'User-Agent': 'FinancialGuardian/1.0'}
    )
    response.raise_for_status()
    content = response.content.decode('iso-8859-1')
    logger.info(f"Downloaded AMFI NAV file: {len(content)} bytes")
    return content


def parse_nav_file(content: str) -> Dict[str, Dict]:
    """
    Parse AMFI NAV file into dict keyed by scheme code.

    Line format (semicolon-separated):
        scheme_code; isin_div_payout; isin_growth; scheme_name; nav; date

    Returns:
        {scheme_code: {scheme_code, isin_growth, scheme_name, nav, nav_date}}
    """
    nav_data = {}

    for line in content.split('\n'):
        line = line.strip()
        if not line or ';' not in line:
            continue

        parts = line.split(';')
        if len(parts) < 6:
            continue

        try:
            scheme_code = parts[0].strip()
            if not scheme_code.isdigit():
                continue  # Skip header/section marker lines

            isin_growth = parts[2].strip() or parts[1].strip()
            scheme_name = parts[3].strip()
            nav = float(parts[4].strip())
            nav_date = datetime.strptime(parts[5].strip(), '%d-%b-%Y').date()

            nav_data[scheme_code] = {
                'scheme_code': scheme_code,
                'isin_growth': isin_growth,
                'scheme_name': scheme_name,
                'nav': nav,
                'nav_date': nav_date
            }

        except (ValueError, IndexError):
            continue

    logger.info(f"Parsed {len(nav_data)} NAV records from AMFI file")
    return nav_data


def _find_nav_record(
    db, fund_code: str, nav_data: Dict[str, Dict]
) -> Dict | None:
    """
    Resolve NAV record for a fund code.
    Tries direct scheme code match first, then falls back to ISIN match.
    """
    record = nav_data.get(fund_code)
    if record:
        return record

    # Fallback: match by ISIN stored in fund_holdings
    row = db.execute(
        text("SELECT isin FROM fund_holdings WHERE fund_code = :code"),
        {'code': fund_code}
    ).fetchone()

    if row and row[0]:
        isin = row[0]
        for rec in nav_data.values():
            if rec.get('isin_growth') == isin:
                return rec

    return None


def update_fund_navs(nav_data: Dict[str, Dict]) -> int:
    """
    Update current NAV for held funds and append to nav_history.

    Returns:
        Count of funds updated.
    """
    funds = get_active_fund_identifiers()

    if not funds:
        logger.warning("No active funds to update NAVs for")
        return 0

    updated_count = 0

    with get_db() as db:
        for fund in funds:
            fund_code = str(fund.get('fund_code', ''))
            nav_record = _find_nav_record(db, fund_code, nav_data)

            if not nav_record:
                logger.warning(f"No NAV found for fund_code: {fund_code}")
                continue

            nav_value = nav_record['nav']
            nav_date = nav_record['nav_date']

            db.execute(
                text("""
                    UPDATE fund_holdings
                    SET current_nav = :nav,
                        current_value = units_held * :nav,
                        absolute_pnl = units_held * (:nav - purchase_nav),
                        pct_pnl = ((:nav - purchase_nav) / purchase_nav * 100),
                        last_nav_date = :nav_date,
                        updated_at = NOW()
                    WHERE fund_code = :fund_code
                """),
                {'nav': nav_value, 'nav_date': nav_date, 'fund_code': fund_code}
            )

            db.execute(
                text("""
                    INSERT INTO nav_history (fund_code, nav_date, nav_value)
                    VALUES (:fund_code, :nav_date, :nav_value)
                    ON CONFLICT (fund_code, nav_date) DO UPDATE SET
                        nav_value = EXCLUDED.nav_value
                """),
                {'fund_code': fund_code, 'nav_date': nav_date, 'nav_value': nav_value}
            )

            updated_count += 1
            logger.debug(f"Updated NAV for {fund_code}: ₹{nav_value:.4f} on {nav_date}")

    logger.info(f"Updated NAV for {updated_count} funds")
    return updated_count


def run_nav_pipeline() -> Dict:
    """Main entry point for AMFI NAV pipeline."""
    job_id = log_job_start('amfi_nav')

    try:
        content = download_nav_file()
        nav_data = parse_nav_file(content)
        updated = update_fund_navs(nav_data)

        log_job_complete(job_id, updated)
        return {'status': 'success', 'funds_updated': updated}

    except Exception as e:
        logger.error(f"AMFI NAV pipeline failed: {e}")
        log_job_failed(job_id, str(e))
        return {'status': 'error', 'error': str(e)}