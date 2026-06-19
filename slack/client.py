"""
Slack SDK client wrapper. All Slack message posting goes through this
module. Splits messages exceeding Slack's ~40K char limit.
"""

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from typing import Dict, Optional
from config import SLACK_BOT_TOKEN, SLACK_CHANNEL_ALERTS
from utils.logger import get_logger
from utils.retry import with_retry

logger = get_logger('slack_client')

_client = WebClient(token=SLACK_BOT_TOKEN)

SLACK_MAX_LENGTH = 38000

SECTION_MARKERS = ['\n🌅', '\n💼', '\n⚠️', '\n✅', '\n📊', '\n📅', '\n📈', '\n📰']


@with_retry(max_attempts=3, delay_seconds=5.0)
def post_to_channel(channel: str, text: str) -> Optional[Dict]:
    """
    Post a message to a Slack channel, splitting into multiple messages
    if it exceeds Slack's length limit.
    """
    if not text:
        logger.warning(f"Empty text provided for channel {channel}")
        return None

    messages = [text] if len(text) <= SLACK_MAX_LENGTH else _split_message(text)

    if len(messages) > 1:
        logger.info(f"Message split into {len(messages)} parts (total {len(text)} chars)")

    last_response = None

    for message_part in messages:
        try:
            response = _client.chat_postMessage(
                channel=channel,
                text=message_part,
                mrkdwn=True
            )
            last_response = response.data

        except SlackApiError as e:
            logger.error(f"Slack API error posting to {channel}: {e.response['error']}")
            raise

    return last_response


def post_urgent_system_alert(message: str) -> Optional[Dict]:
    """Post a system-level urgent alert to #urgent-alerts."""
    return post_to_channel(channel=SLACK_CHANNEL_ALERTS, text=f"🤖 *System Alert*\n{message}")


def _split_message(text: str, max_length: int = SLACK_MAX_LENGTH) -> list:
    """Split a long message at natural break points (section headers, then newlines)."""
    if len(text) <= max_length:
        return [text]

    parts = []
    remaining = text

    while len(remaining) > max_length:
        split_pos = max_length

        found = False
        for marker in SECTION_MARKERS:
            pos = remaining.rfind(marker, max_length // 2, max_length)
            if pos > 0:
                split_pos = pos
                found = True
                break

        if not found:
            pos = remaining.rfind('\n', max_length // 2, max_length)
            if pos > 0:
                split_pos = pos

        parts.append(remaining[:split_pos])
        remaining = remaining[split_pos:]

    if remaining:
        parts.append(remaining)

    return parts