"""
Financial Guardian — application entry point.

Phase 1: health check only.
Phase 2: adds sync_all_holdings() for manual testing.
Full scheduler loop added in Phase 7.
"""

import sys
from utils.logger import get_logger
from scheduler.health_check import run_all_checks

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


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Financial Guardian')
    parser.add_argument(
        '--sync-holdings',
        action='store_true',
        help='Run full holdings sync (Phase 2 testing)',
    )
    args = parser.parse_args()

    if args.sync_holdings:
        sync_all_holdings()
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