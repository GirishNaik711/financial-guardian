"""
Slack alert formatter and sender.
Posts to #urgent-alerts with consistent format and reaction-to-acknowledge prompt.
"""

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from typing import Optional
from config import SLACK_BOT_TOKEN, SLACK_CHANNEL_ALERTS
from utils.logger import get_logger
from utils.date_utils import now_ist, format_ist

logger = get_logger('slack_alerter')

_client = WebClient(token=SLACK_BOT_TOKEN)


def send_urgent_alert(
    title: str,
    message: str,
    source_url: str = None,
    related_identifier: str = None
) -> Optional[str]:
    """Send a formatted urgent alert to #urgent-alerts. Returns Slack ts or None."""
    timestamp = format_ist(now_ist())

    lines = [
        "🚨 *URGENT ALERT*",
        f"*{title}*",
        "",
        message,
        ""
    ]

    if source_url:
        lines.append(f"_Source: <{source_url}|View filing/article>_")

    lines.append(f"_Time: {timestamp}_")
    lines.append("_React with ✅ to acknowledge_")

    formatted_message = '\n'.join(lines)

    try:
        response = _client.chat_postMessage(
            channel=SLACK_CHANNEL_ALERTS,
            text=formatted_message,
            mrkdwn=True
        )
        ts = response.data.get('ts')
        logger.info(f"Urgent alert sent: {title[:50]} (ts: {ts})")
        return ts
    except SlackApiError as e:
        logger.error(f"Failed to send urgent alert: {e.response['error']}")
        return None


def send_system_health_alert(message: str) -> Optional[str]:
    """Send a system-level (non-financial) health alert."""
    try:
        response = _client.chat_postMessage(
            channel=SLACK_CHANNEL_ALERTS,
            text=f"🤖 *System Health Alert*\n{message}",
            mrkdwn=True
        )
        return response.data.get('ts')
    except SlackApiError as e:
        logger.error(f"Failed to send system health alert: {e.response['error']}")
        return None