"""
Macro economic data fetcher.

Fetches FII/DII net flows (NSE unofficial endpoint), USD/INR, crude oil
(Brent), and US market indices (S&P 500, Nasdaq) via yfinance.
"""

import requests
from typing import Dict
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger('macro')

USD_INR_TICKER = 'USDINR=X'
CRUDE_OIL_TICKER = 'BZ=F'  # Brent crude
SP500_TICKER = '^GSPC'
NASDAQ_TICKER = '^IXIC'

NSE_FII_DII_URL = 'https://www.nseindia.com/api/fiidiiTradeReact'

NSE_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nseindia.com/',
}


@with_retry(max_attempts=3, delay_seconds=15.0)
def fetch_fii_dii_flows() -> Dict:
    """
    Fetch FII and DII net flow data from NSE's unofficial JSON endpoint.

    Returns:
        Dict with fii_net_cr, dii_net_cr, date. Values are None on failure
        (caller/briefing layer must handle gracefully — this is a best-effort
        unofficial endpoint that can be blocked or change shape).
    """
    try:
        session = requests.Session()
        session.get('https://www.nseindia.com/', headers=NSE_HEADERS, timeout=10)

        response = session.get(NSE_FII_DII_URL, headers=NSE_HEADERS, timeout=15)
        response.raise_for_status()

        data = response.json()
        flow_data = data.get('data', [])

        result = {'fii_net_cr': None, 'dii_net_cr': None, 'date': None}

        for item in flow_data:
            category = item.get('category', '').upper()
            net_value_str = str(item.get('netValue', '0')).replace(',', '')

            try:
                net_value = float(net_value_str)
            except ValueError:
                net_value = 0

            if 'FII' in category or 'FPI' in category:
                result['fii_net_cr'] = net_value
                result['date'] = item.get('date', '')
            elif 'DII' in category:
                result['dii_net_cr'] = net_value

        if result['fii_net_cr'] is not None:
            logger.info(
                f"FII/DII flows — FII: Rs{result['fii_net_cr']:,.2f}Cr, "
                f"DII: Rs{result['dii_net_cr']:,.2f}Cr"
            )

        return result

    except Exception as e:
        logger.warning(f"NSE FII/DII fetch failed: {e}")
        return {'fii_net_cr': None, 'dii_net_cr': None, 'date': None}


def fetch_global_indicators() -> Dict:
    """Fetch USD/INR, crude oil, S&P 500, Nasdaq via yfinance."""
    import yfinance as yf

    result = {}

    tickers_to_fetch = {
        'usd_inr': USD_INR_TICKER,
        'crude_oil': CRUDE_OIL_TICKER,
        'sp500': SP500_TICKER,
        'nasdaq': NASDAQ_TICKER,
    }

    for key, ticker_symbol in tickers_to_fetch.items():
        try:
            ticker = yf.Ticker(ticker_symbol)
            hist = ticker.history(period='2d')

            if hist.empty:
                continue

            current = float(hist['Close'].iloc[-1])
            previous = float(hist['Close'].iloc[-2]) if len(hist) > 1 else current
            change_pct = ((current - previous) / previous * 100) if previous > 0 else 0

            result[key] = {
                'value': round(current, 4 if key == 'usd_inr' else 2),
                'change_pct': round(change_pct, 4)
            }

        except Exception as e:
            logger.warning(f"Failed to fetch {key} ({ticker_symbol}): {e}")

    if 'usd_inr' in result:
        logger.info(f"USD/INR: {result['usd_inr']['value']}")
    if 'crude_oil' in result:
        logger.info(f"Brent Crude: ${result['crude_oil']['value']}")

    return result