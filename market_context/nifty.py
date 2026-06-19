"""
Nifty 50 and Sensex market data fetcher.

Primary source: yfinance (^NSEI, ^BSESN, ^INDIAVIX). Free, no API key,
~15min delay on free tier — adequate for a monitoring (not trading) system.
"""

import yfinance as yf
from typing import Dict, List, Optional
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger('nifty')

NIFTY_50_TICKER = '^NSEI'
SENSEX_TICKER = '^BSESN'
INDIA_VIX_TICKER = '^INDIAVIX'

NIFTY_SECTOR_TICKERS = {
    'Information Technology': '^CNXIT',
    'Financial Services': '^NSEBANK',
    'FMCG': '^CNXFMCG',
    'Pharma': '^CNXPHARMA',
    'Auto': '^CNXAUTO',
    'Energy': '^CNXENERGY',
    'Metal': '^CNXMETAL',
    'Realty': '^CNXREALTY',
    'Media': '^CNXMEDIA',
}


@with_retry(max_attempts=3, delay_seconds=10.0)
def fetch_index_data(ticker_symbol: str, period: str = '5d') -> Optional[Dict]:
    """Fetch index data from Yahoo Finance using yfinance."""
    ticker = yf.Ticker(ticker_symbol)
    hist = ticker.history(period=period)

    if hist.empty:
        logger.warning(f"No data returned for {ticker_symbol}")
        return None

    current_close = float(hist['Close'].iloc[-1])
    previous_close = float(hist['Close'].iloc[-2]) if len(hist) > 1 else current_close

    change = current_close - previous_close
    change_pct = (change / previous_close * 100) if previous_close > 0 else 0

    return {
        'symbol': ticker_symbol,
        'current_value': round(current_close, 2),
        'previous_close': round(previous_close, 2),
        'change': round(change, 2),
        'change_pct': round(change_pct, 4),
        'period_high': round(float(hist['High'].max()), 2),
        'period_low': round(float(hist['Low'].min()), 2),
        'as_of': hist.index[-1].strftime('%Y-%m-%d')
    }


def fetch_nifty_data() -> Dict:
    """Fetch Nifty 50, Sensex, and India VIX data."""
    result = {}

    nifty = fetch_index_data(NIFTY_50_TICKER)
    if nifty:
        result['nifty_50'] = nifty
        logger.info(
            f"Nifty 50: {nifty['current_value']:,.2f} "
            f"({'+' if nifty['change_pct'] > 0 else ''}{nifty['change_pct']:.2f}%)"
        )

    sensex = fetch_index_data(SENSEX_TICKER)
    if sensex:
        result['sensex'] = sensex
        logger.info(f"Sensex: {sensex['current_value']:,.2f}")

    vix = fetch_index_data(INDIA_VIX_TICKER)
    if vix:
        result['india_vix'] = vix
        logger.info(f"India VIX: {vix['current_value']:.2f}")

    return result


def fetch_sector_performance(held_sectors: List[str]) -> Dict:
    """Fetch performance for sectors relevant to held stocks."""
    sector_data = {}

    for sector in held_sectors:
        ticker_symbol = NIFTY_SECTOR_TICKERS.get(sector)

        if not ticker_symbol:
            logger.debug(f"No sector ticker found for: {sector}")
            continue

        try:
            data = fetch_index_data(ticker_symbol)
            if data:
                sector_data[sector] = data
        except Exception as e:
            logger.warning(f"Failed to fetch sector data for {sector}: {e}")

    return sector_data


def classify_market_regime(
    nifty_change_pct: float,
    india_vix: float,
    fii_flow: float
) -> str:
    """
    Classify current market regime.

    Returns one of:
        'risk_on_trending', 'sideways_low_conviction',
        'risk_off_defensive', 'event_driven_volatile'
    """
    if india_vix > 25:
        return 'event_driven_volatile'

    if nifty_change_pct < -1.5 and fii_flow < 0:
        return 'risk_off_defensive'

    if -0.5 <= nifty_change_pct <= 0.5:
        return 'sideways_low_conviction'

    if nifty_change_pct > 0.5 and india_vix < 18:
        return 'risk_on_trending'

    return 'sideways_low_conviction'