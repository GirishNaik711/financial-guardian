"""
Kite Connect equity holdings synchronizer.

Fetches current holdings from Zerodha Kite Connect API and
upserts them into the equity_holdings table.

Authentication:
    Kite Connect uses a daily access token that must be refreshed.
    Token is managed externally and stored in .env as KITE_ACCESS_TOKEN.

Rate limits:
    Holdings endpoint: no documented limit; call no more than once/minute.
"""

from datetime import datetime
from typing import List, Dict, Optional
from kiteconnect import KiteConnect
from sqlalchemy import text
from config.settings import KITE_API_KEY, KITE_ACCESS_TOKEN
from db.connection import get_db
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger('kite_sync')

SECTOR_FALLBACK: Dict[str, str] = {
    'RELIANCE':    'Energy',
    'TCS':         'Information Technology',
    'HDFCBANK':    'Financial Services',
    'INFY':        'Information Technology',
    'ICICIBANK':   'Financial Services',
    'HINDUNILVR':  'FMCG',
    'ITC':         'FMCG',
    'SBIN':        'Financial Services',
    'BAJFINANCE':  'Financial Services',
    'KOTAKBANK':   'Financial Services',
}


def get_kite_client() -> KiteConnect:
    """
    Initialize and return an authenticated Kite Connect client.
    Raises ValueError if KITE_ACCESS_TOKEN is not set.
    """
    if not KITE_ACCESS_TOKEN:
        raise ValueError(
            "KITE_ACCESS_TOKEN not set in environment. "
            "Complete the daily token refresh before running."
        )
    kite = KiteConnect(api_key=KITE_API_KEY)
    kite.set_access_token(KITE_ACCESS_TOKEN)
    return kite


@with_retry(max_attempts=3, delay_seconds=5.0)
def fetch_holdings_from_kite() -> List[Dict]:
    """
    Fetch current holdings from Kite Connect API.

    Returns:
        List of raw holding dicts from Kite.
        Relevant fields: tradingsymbol, exchange, quantity,
        average_price, last_price, pnl, isin.

    Raises:
        Exception if API call fails after all retries.
    """
    kite = get_kite_client()
    holdings = kite.holdings()
    logger.info(f"Fetched {len(holdings)} holdings from Kite")
    return holdings


def parse_holding(raw: Dict) -> Dict:
    """
    Map a raw Kite holding dict to equity_holdings schema.

    Kite does not return the company full name — tradingsymbol
    is used as a fallback for company_name.
    """
    ticker = raw.get('tradingsymbol', '')
    avg_price = float(raw.get('average_price') or 0)
    last_price = float(raw.get('last_price') or 0)
    quantity = int(raw.get('quantity') or 0)

    current_value = last_price * quantity
    absolute_pnl = (last_price - avg_price) * quantity
    pct_pnl = ((last_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0

    return {
        'ticker':         ticker,
        'exchange':       raw.get('exchange', 'NSE'),
        'company_name':   raw.get('tradingsymbol', ticker),
        'quantity':       quantity,
        'avg_buy_price':  avg_price,
        'current_price':  last_price,
        'current_value':  current_value,
        'absolute_pnl':   absolute_pnl,
        'pct_pnl':        pct_pnl,
        'sector':         SECTOR_FALLBACK.get(ticker),
        'isin':           raw.get('isin'),
        'last_synced_at': datetime.utcnow(),
        'is_active':      quantity > 0,
    }


def upsert_equity_holdings(holdings: List[Dict]) -> int:
    """
    Upsert holdings into equity_holdings table.

    - Existing ticker → update all fields.
    - New ticker → insert.
    - Previously held ticker absent from current list → mark is_active = FALSE.

    Returns:
        Number of rows upserted.
    """
    if not holdings:
        logger.warning("No equity holdings to upsert")
        return 0

    current_tickers = tuple(h['ticker'] for h in holdings)

    with get_db() as db:
        # Mark holdings that are no longer held as inactive
        db.execute(
            text("""
                UPDATE equity_holdings
                SET is_active = FALSE, updated_at = NOW()
                WHERE ticker NOT IN :tickers
                  AND is_active = TRUE
            """),
            {'tickers': current_tickers},
        )

        for holding in holdings:
            db.execute(
                text("""
                    INSERT INTO equity_holdings (
                        ticker, exchange, company_name, quantity,
                        avg_buy_price, current_price, current_value,
                        absolute_pnl, pct_pnl, sector, isin,
                        last_synced_at, is_active, updated_at
                    ) VALUES (
                        :ticker, :exchange, :company_name, :quantity,
                        :avg_buy_price, :current_price, :current_value,
                        :absolute_pnl, :pct_pnl, :sector, :isin,
                        :last_synced_at, :is_active, NOW()
                    )
                    ON CONFLICT (ticker) DO UPDATE SET
                        exchange        = EXCLUDED.exchange,
                        quantity        = EXCLUDED.quantity,
                        avg_buy_price   = EXCLUDED.avg_buy_price,
                        current_price   = EXCLUDED.current_price,
                        current_value   = EXCLUDED.current_value,
                        absolute_pnl    = EXCLUDED.absolute_pnl,
                        pct_pnl         = EXCLUDED.pct_pnl,
                        sector          = COALESCE(EXCLUDED.sector, equity_holdings.sector),
                        isin            = COALESCE(EXCLUDED.isin, equity_holdings.isin),
                        last_synced_at  = EXCLUDED.last_synced_at,
                        is_active       = EXCLUDED.is_active,
                        updated_at      = NOW()
                """),
                holding,
            )

    logger.info(f"Upserted {len(holdings)} equity holdings")
    return len(holdings)


def sync_kite_holdings() -> Dict:
    """
    Main entry point for Kite holdings sync.
    Fetches, parses, and upserts all equity holdings.

    Returns:
        Dict: {status, count, tickers, synced_at} on success
              {status, error} on failure
    """
    logger.info("Starting Kite holdings sync")

    try:
        raw_holdings = fetch_holdings_from_kite()

        equity_only = [
            h for h in raw_holdings
            if h.get('exchange') in ('NSE', 'BSE')
        ]

        parsed = [parse_holding(h) for h in equity_only]
        count = upsert_equity_holdings(parsed)

        result = {
            'status':     'success',
            'count':      count,
            'tickers':    [p['ticker'] for p in parsed],
            'synced_at':  datetime.utcnow().isoformat(),
        }
        logger.info(f"Kite sync complete: {count} holdings synced")
        return result

    except Exception as e:
        logger.error(f"Kite holdings sync failed: {e}")
        return {'status': 'error', 'error': str(e)}