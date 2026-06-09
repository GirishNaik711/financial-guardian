"""
Groww API mutual fund holdings synchronizer.

Fetches current MF holdings from Groww API and upserts into
the fund_holdings table.

Fund type tagging:
    Groww returns scheme category and scheme name. Index funds
    are detected by keyword matching and tagged as 'index';
    everything else is tagged 'active'. This tag drives
    monitoring frequency in all subsequent phases.

Note:
    Groww's API is designed for their own app. Verify the base
    URL and endpoint paths against current Groww documentation
    before deployment.
"""

import requests
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy import text
from config.settings import GROWW_API_BASE_URL, GROWW_AUTH_TOKEN
from db.connection import get_db
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger('groww_sync')

# Case-insensitive keywords that identify index/passive funds
INDEX_FUND_KEYWORDS = [
    'index', 'nifty', 'sensex', 'bse', 'nse 500',
    'nifty 50', 'nifty next 50', 'nifty 100',
    'nifty midcap', 'nifty smallcap',
    'passive', 'etf', 'exchange traded',
]


def tag_fund_type(scheme_name: str, scheme_category: str = '') -> str:
    """
    Determine whether a fund is actively managed or an index fund.

    Args:
        scheme_name: Full scheme name from Groww API.
        scheme_category: Scheme category from Groww API.

    Returns:
        'index' if any index keyword is found, 'active' otherwise.
    """
    combined = (scheme_name + ' ' + scheme_category).lower()
    for keyword in INDEX_FUND_KEYWORDS:
        if keyword in combined:
            return 'index'
    return 'active'


def _groww_headers() -> Dict[str, str]:
    """Return authentication headers for Groww API."""
    return {
        'Authorization': f'Bearer {GROWW_AUTH_TOKEN}',
        'Content-Type':  'application/json',
        'Accept':        'application/json',
        'User-Agent':    'FinancialGuardian/1.0',
    }


@with_retry(max_attempts=3, delay_seconds=5.0)
def fetch_mf_holdings_from_groww() -> List[Dict]:
    """
    Fetch current mutual fund holdings from Groww API.

    Expected response shape:
        {"data": {"holdings": [ {...}, ... ]}}

    Falls back to root-level "holdings" key if nested path absent.

    Returns:
        List of raw holding dicts.

    Raises:
        requests.HTTPError if response status is not 2xx.
    """
    url = f"{GROWW_API_BASE_URL}/user/portfolio/v2/holdings"

    response = requests.get(url, headers=_groww_headers(), timeout=30)
    response.raise_for_status()

    data = response.json()
    holdings = (
        data.get('data', {}).get('holdings')
        or data.get('holdings')
        or []
    )

    logger.info(f"Fetched {len(holdings)} mutual fund holdings from Groww")
    return holdings


def parse_fund_holding(raw: Dict) -> Dict:
    """
    Map a raw Groww holding dict to the fund_holdings schema.
    """
    scheme_name = raw.get('schemeName', '')
    scheme_category = raw.get('schemeCategory', '')
    fund_type = tag_fund_type(scheme_name, scheme_category)

    units = float(raw.get('units') or 0)
    purchase_nav = float(raw.get('purchaseNav') or 0)
    current_nav = float(raw.get('currentNav') or 0)
    current_value = float(raw.get('currentValue') or 0)
    absolute_pnl = float(raw.get('absoluteReturns') or 0)
    pct_pnl = (
        (current_nav - purchase_nav) / purchase_nav * 100
        if purchase_nav > 0 else 0.0
    )

    return {
        'fund_code':          str(raw.get('schemeCode', '')),
        'fund_name':          scheme_name,
        'isin':               raw.get('isin'),
        'fund_house':         raw.get('amcName'),
        'fund_type':          fund_type,
        'benchmark_index':    raw.get('benchmarkName'),
        'units_held':         units,
        'purchase_nav':       purchase_nav,
        'current_nav':        current_nav,
        'current_value':      current_value,
        'absolute_pnl':       absolute_pnl,
        'pct_pnl':            pct_pnl,
        'expense_ratio':      None,  # Not returned by holdings endpoint
        'fund_manager_name':  raw.get('fundManagerName'),
        'last_nav_date':      datetime.utcnow().date(),
        'last_synced_at':     datetime.utcnow(),
        'is_active':          units > 0,
    }


def upsert_fund_holdings(holdings: List[Dict]) -> int:
    """
    Upsert fund holdings into fund_holdings table.

    - Existing fund_code → update all fields.
    - New fund_code → insert.
    - Previously held fund absent from current list → mark is_active = FALSE.

    Returns:
        Number of rows upserted.
    """
    if not holdings:
        logger.warning("No fund holdings to upsert")
        return 0

    current_codes = tuple(h['fund_code'] for h in holdings)

    with get_db() as db:
        db.execute(
            text("""
                UPDATE fund_holdings
                SET is_active = FALSE, updated_at = NOW()
                WHERE fund_code NOT IN :codes
                  AND is_active = TRUE
            """),
            {'codes': current_codes},
        )

        for holding in holdings:
            db.execute(
                text("""
                    INSERT INTO fund_holdings (
                        fund_code, fund_name, isin, fund_house, fund_type,
                        benchmark_index, units_held, purchase_nav, current_nav,
                        current_value, absolute_pnl, pct_pnl, expense_ratio,
                        fund_manager_name, last_nav_date, last_synced_at,
                        is_active, updated_at
                    ) VALUES (
                        :fund_code, :fund_name, :isin, :fund_house, :fund_type,
                        :benchmark_index, :units_held, :purchase_nav, :current_nav,
                        :current_value, :absolute_pnl, :pct_pnl, :expense_ratio,
                        :fund_manager_name, :last_nav_date, :last_synced_at,
                        :is_active, NOW()
                    )
                    ON CONFLICT (fund_code) DO UPDATE SET
                        fund_name           = EXCLUDED.fund_name,
                        fund_type           = EXCLUDED.fund_type,
                        benchmark_index     = COALESCE(EXCLUDED.benchmark_index,
                                                       fund_holdings.benchmark_index),
                        units_held          = EXCLUDED.units_held,
                        purchase_nav        = EXCLUDED.purchase_nav,
                        current_nav         = EXCLUDED.current_nav,
                        current_value       = EXCLUDED.current_value,
                        absolute_pnl        = EXCLUDED.absolute_pnl,
                        pct_pnl             = EXCLUDED.pct_pnl,
                        fund_manager_name   = COALESCE(EXCLUDED.fund_manager_name,
                                                       fund_holdings.fund_manager_name),
                        last_nav_date       = EXCLUDED.last_nav_date,
                        last_synced_at      = EXCLUDED.last_synced_at,
                        is_active           = EXCLUDED.is_active,
                        updated_at          = NOW()
                """),
                holding,
            )

    logger.info(f"Upserted {len(holdings)} fund holdings")
    return len(holdings)


def sync_groww_holdings() -> Dict:
    """
    Main entry point for Groww holdings sync.

    Returns:
        Dict: {status, count, active_managed, index_funds,
               fund_codes, synced_at} on success
              {status, error} on failure
    """
    logger.info("Starting Groww holdings sync")

    try:
        raw_holdings = fetch_mf_holdings_from_groww()
        parsed = [parse_fund_holding(h) for h in raw_holdings]
        count = upsert_fund_holdings(parsed)

        active_funds = [p for p in parsed if p['is_active']]
        index_count = sum(1 for p in active_funds if p['fund_type'] == 'index')
        active_count = sum(1 for p in active_funds if p['fund_type'] == 'active')

        result = {
            'status':         'success',
            'count':          count,
            'active_managed': active_count,
            'index_funds':    index_count,
            'fund_codes':     [p['fund_code'] for p in active_funds],
            'synced_at':      datetime.utcnow().isoformat(),
        }
        logger.info(
            f"Groww sync complete: {count} funds synced "
            f"({active_count} active, {index_count} index)"
        )
        return result

    except Exception as e:
        logger.error(f"Groww holdings sync failed: {e}")
        return {'status': 'error', 'error': str(e)}