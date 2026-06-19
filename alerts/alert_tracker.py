"""
Alert acknowledgment tracker.

Acknowledgment paths for a personal single-user system (no Slack Events webhook):
    1. Manual: ack_all() or acknowledge_alert(id)
    2. Auto: alerts older than `hours_threshold` auto-acknowledged nightly

Morning briefing calls get_unacknowledged_alerts() to flag missed alerts.
"""

from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from db.connection import get_db
from utils.logger import get_logger

logger = get_logger('alert_tracker')


def get_unacknowledged_alerts(hours_back: int = 24) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    with get_db() as db:
        result = db.execute(
            text("""
                SELECT id, alert_type, title, message, source_url,
                       fired_at, related_ticker, related_fund_code
                FROM alerts
                WHERE is_acknowledged = FALSE
                  AND severity = 'urgent'
                  AND fired_at > :cutoff
                ORDER BY fired_at DESC
            """),
            {'cutoff': cutoff}
        )
        return [dict(row._mapping) for row in result]


def acknowledge_alert(alert_id: int):
    with get_db() as db:
        db.execute(
            text("""
                UPDATE alerts
                SET is_acknowledged = TRUE, acknowledged_at = NOW()
                WHERE id = :alert_id
            """),
            {'alert_id': alert_id}
        )
    logger.info(f"Alert {alert_id} acknowledged")


def auto_acknowledge_old_alerts(hours_threshold: int = 12) -> int:
    """Auto-acknowledge alerts older than threshold. Called nightly."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_threshold)

    with get_db() as db:
        result = db.execute(
            text("""
                UPDATE alerts
                SET is_acknowledged = TRUE, acknowledged_at = NOW()
                WHERE is_acknowledged = FALSE
                  AND fired_at < :cutoff
                RETURNING id
            """),
            {'cutoff': cutoff}
        )
        count = result.rowcount

    if count > 0:
        logger.info(f"Auto-acknowledged {count} old alerts")

    return count


def ack_all() -> int:
    """Acknowledge all pending alerts. Usage: python -c 'from alerts.alert_tracker import ack_all; ack_all()'"""
    with get_db() as db:
        result = db.execute(
            text("""
                UPDATE alerts
                SET is_acknowledged = TRUE, acknowledged_at = NOW()
                WHERE is_acknowledged = FALSE
                RETURNING id
            """)
        )
        count = result.rowcount

    logger.info(f"Acknowledged all {count} pending alerts")
    return count