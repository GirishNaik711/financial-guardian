"""
Financial Guardian — Application Entry Point.

Phase 1: Runs health check and exits.
Phase 7: Full APScheduler initialisation and daemon loop will be added here.
"""


import sys

from utils.logger import get_logger
from scheduler.health_check import run_all_checks

logger = get_logger('main')


def main() -> int:
    logger.info("=" * 60)
    logger.info("Financial Guardian — starting up")
    logger.info("=" * 60)

    result = run_all_checks()

    logger.info("Health check summary:")
    for component in result['components']:
        status = component['status'].upper()
        name = component['component']
        detail = component.get('detail', '')
        logger.info(f"  [{status:8s}] {name}  {detail}")

    if result['overall'] == 'healthy':
        logger.info("All systems operational. Ready for Phase 2.")
        return 0
    elif result['overall'] == 'degraded':
        logger.warning("System is degraded — non-critical issues detected. Review warnings above.")
        return 1
    else:
        logger.error("System is critical — one or more required components failed. Review errors above.")
        return 2


if __name__ == '__main__':
    sys.exit(main())