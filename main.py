"""
Financial Guardian — application entry point.

Phase 1: health check only.
Phase 2: adds sync_all_holdings() for manual testing.
Full scheduler loop added in Phase 7.
"""

import sys
from utils.logger import get_logger
from scheduler.health_check import run_all_checks
from data_pipeline.stockinsights import run_filings_pipeline
from data_pipeline.perplexity import run_equity_news_pipeline, run_fund_news_pipeline
from data_pipeline.newsapi import run_newsapi_pipeline
from data_pipeline.amfi import run_nav_pipeline
from data_pipeline.nse_rss import run_nse_rss_pipeline
from market_context.context_builder import build_market_context



logger = get_logger('main')


def sync_all_holdings():
    """
    Sync all holdings sources and compute portfolio summary.
    Called manually for Phase 2 testing; will be scheduler-driven in Phase 7.
    """
    from holdings.kite_sync import sync_kite_holdings
    from holdings.groww_sync import sync_groww_holdings
    from holdings.watchlist import sync_watchlist
    from holdings.bonds import sync_bond_holdings
    from holdings.portfolio import compute_portfolio_summary

    logger.info("=== Starting full holdings sync ===")

    results = {
        'kite':      sync_kite_holdings(),
        'groww':     sync_groww_holdings(),
        'watchlist': sync_watchlist(),
        'bonds':     sync_bond_holdings(),
    }

    for source, result in results.items():
        status = result.get('status', 'unknown')
        logger.info(f"  {source}: {status}")

    logger.info("=== Computing portfolio summary ===")
    portfolio = compute_portfolio_summary()

    logger.info(f"Portfolio total value  : ₹{portfolio['total_value']:,.2f}")
    logger.info(f"Total P&L              : ₹{portfolio['total_absolute_pnl']:,.2f} "
                f"({portfolio['total_pct_pnl']:.2f}%)")
    if portfolio['best_performer']:
        bp = portfolio['best_performer']
        logger.info(f"Best performer         : {bp['name']} ({bp['pct_pnl']:.2f}%)")
    if portfolio['worst_performer']:
        wp = portfolio['worst_performer']
        logger.info(f"Worst performer        : {wp['name']} ({wp['pct_pnl']:.2f}%)")

    return results, portfolio


def run_pipeline():
    """Run all data pipeline sources once. Used for Phase 3 testing."""
    logger.info("=== Running Data Pipeline ===")

    results = {}

    logger.info("Running StockInsights filings pipeline...")
    results['stockinsights'] = run_filings_pipeline()
    logger.info(f"StockInsights: {results['stockinsights']}")

    logger.info("Running NewsAPI pipeline...")
    results['newsapi'] = run_newsapi_pipeline()
    logger.info(f"NewsAPI: {results['newsapi']}")

    logger.info("Running AMFI NAV pipeline...")
    results['amfi'] = run_nav_pipeline()
    logger.info(f"AMFI: {results['amfi']}")

    logger.info("Running NSE RSS pipeline...")
    results['nse_rss'] = run_nse_rss_pipeline()
    logger.info(f"NSE RSS: {results['nse_rss']}")

    logger.info("Running Perplexity equity news pipeline...")
    results['perplexity_equity'] = run_equity_news_pipeline()
    logger.info(f"Perplexity equity: {results['perplexity_equity']}")

    logger.info("Running Perplexity fund news pipeline...")
    results['perplexity_funds'] = run_fund_news_pipeline()
    logger.info(f"Perplexity funds: {results['perplexity_funds']}")

    success = all(r.get('status') in ('success', 'skipped') for r in results.values())
    logger.info(f"=== Pipeline complete — {'ALL OK' if success else 'SOME FAILURES'} ===")
    return results

def run_market_context():
    """Build and persist the market context snapshot."""
    context = build_market_context()
    print(f"Market date: {context['market_date']}")
    print(f"Market regime: {context['market_regime']}")
    print(f"Key alerts: {context.get('key_alerts', [])}")
    return context

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Financial Guardian')
    parser.add_argument(
        '--sync-holdings',
        action='store_true',
        help='Run full holdings sync (Phase 2 testing)',
    )
    parser.add_argument('--pipeline', action='store_true', help='Run data pipeline once')
    parser.add_argument(
    '--market-context',
    action='store_true',
    help='Build and store the market context snapshot'
    )

    args = parser.parse_args()

    if args.sync_holdings:
        sync_all_holdings()
        sys.exit(0)

    if args.pipeline:
        run_pipeline()
        sys.exit(0)

    if args.market_context:
        run_market_context()
        sys.exit(0)


    # Default: run health checks (Phase 1 behaviour)
    logger.info("Financial Guardian starting — running health checks")
    report = run_all_checks()

    print("\n=== Health Check Report ===")
    for component, info in report['components'].items():
        status_icon = '✅' if info['status'] == 'ok' else '❌'
        print(f"  {status_icon} {component:<20} {info['status']}")
        if info.get('detail'):
            print(f"       {info['detail']}")

    print(f"\nOverall: {report['overall'].upper()}")

    exit_codes = {'healthy': 0, 'degraded': 1, 'critical': 2}
    sys.exit(exit_codes.get(report['overall'], 2))