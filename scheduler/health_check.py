"""
System health check.
Verifies all external dependencies are reachable and operational.
Called at application startup and every 30 minutes by the scheduler.
"""

import json
from typing import Any

from utils.logger import get_logger
from db.connection import health_check as db_health_check, get_table_count

logger = get_logger('scheduler.health_check')

_EXPECTED_TABLE_COUNT = 12


def check_database() -> dict[str, Any]:
    """Verify PostgreSQL is reachable and the schema is applied."""
    if not db_health_check():
        return {'component': 'postgresql', 'status': 'error', 'detail': 'Connection failed'}

    count = get_table_count()
    if count < _EXPECTED_TABLE_COUNT:
        return {
            'component': 'postgresql',
            'status': 'warning',
            'detail': f'Expected {_EXPECTED_TABLE_COUNT} tables, found {count}. Run db/schema.sql.',
        }

    return {'component': 'postgresql', 'status': 'ok', 'detail': f'{count} tables present'}


def check_redis() -> dict[str, Any]:
    """Verify Redis is reachable and authenticated."""
    try:
        import redis as redis_lib
        from config.settings import REDIS_URL

        r = redis_lib.from_url(REDIS_URL, socket_connect_timeout=5)
        r.ping()
        return {'component': 'redis', 'status': 'ok'}
    except Exception as exc:
        return {'component': 'redis', 'status': 'error', 'detail': str(exc)}


def check_slack() -> dict[str, Any]:
    """Verify the Slack bot token is valid and the bot is reachable."""
    try:
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError
        from config.settings import SLACK_BOT_TOKEN

        client = WebClient(token=SLACK_BOT_TOKEN)
        response = client.auth_test()
        return {
            'component': 'slack',
            'status': 'ok',
            'detail': f"Connected as bot '{response['user']}' in workspace '{response['team']}'",
        }
    except Exception as exc:
        return {'component': 'slack', 'status': 'error', 'detail': str(exc)}


def check_kite() -> dict[str, Any]:
    """Verify the Kite API key is present and the SDK initialises."""
    try:
        from kiteconnect import KiteConnect
        from config.settings import KITE_API_KEY, KITE_ACCESS_TOKEN

        kite = KiteConnect(api_key=KITE_API_KEY)
        has_token = bool(KITE_ACCESS_TOKEN)
        return {
            'component': 'kite',
            'status': 'ok',
            'detail': f'API key present. Access token {"set" if has_token else "NOT SET — login required"}.',
        }
    except Exception as exc:
        return {'component': 'kite', 'status': 'error', 'detail': str(exc)}


def check_env_vars() -> dict[str, Any]:
    """Confirm all required environment variables are loaded without error."""
    try:
        import config.settings  # noqa: F401 — triggers validation at import time
        return {'component': 'env_vars', 'status': 'ok'}
    except EnvironmentError as exc:
        return {'component': 'env_vars', 'status': 'error', 'detail': str(exc)}


def run_all_checks() -> dict[str, Any]:
    """
    Execute all health checks.

    Returns:
        {
            'overall': 'healthy' | 'degraded' | 'critical',
            'components': [{ component, status, detail? }, ...]
        }
    """
    checks = [
        check_env_vars(),
        check_database(),
        check_redis(),
        check_slack(),
        check_kite(),
    ]

    statuses = {c['status'] for c in checks}

    if 'error' in statuses:
        overall = 'critical'
    elif 'warning' in statuses:
        overall = 'degraded'
    else:
        overall = 'healthy'

    result: dict[str, Any] = {'overall': overall, 'components': checks}

    if overall == 'healthy':
        logger.info("Health check passed — all components operational.")
    else:
        failed = [c for c in checks if c['status'] in ('error', 'warning')]
        logger.error(f"Health check result: {overall}. Issues: {failed}")

    return result


if __name__ == '__main__':
    print(json.dumps(run_all_checks(), indent=2))