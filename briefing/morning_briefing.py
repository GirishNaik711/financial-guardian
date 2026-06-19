"""
Morning Briefing Orchestrator.

Coordinates: data retrieval -> Stage 1 parallel analysis (Haiku) ->
Stage 2 assembly -> Stage 3 synthesis (Opus) -> Slack delivery -> persist.

Schedule: 7:30am IST. Pre-requisites: holdings sync (7:00am) and
market context build (7:15am) must have already run.
"""

from datetime import datetime, timezone
from typing import Dict
from sqlalchemy import text

from briefing.data_fetcher import (
    get_active_equity_holdings, get_active_fund_holdings,
    get_recent_news_by_ticker, get_recent_news_by_fund,
    get_recent_filings_by_ticker, get_latest_market_context,
    get_unacknowledged_alerts
)
from briefing.llm_synthesizer import (
    run_parallel_holdings_analysis,
    assemble_briefing_skeleton,
    synthesize_morning_briefing
)
from briefing.citation_builder import process_briefing_citations
from holdings.portfolio import compute_portfolio_summary
from slack.client import post_to_channel, post_urgent_system_alert
from config import SLACK_CHANNEL_MORNING
from db.connection import get_db
from data_pipeline.pipeline_runner import log_job_start, log_job_complete, log_job_failed
from utils.logger import get_logger
from utils.date_utils import today_ist

logger = get_logger('morning_briefing')


def save_briefing_to_db(briefing_text: str, skeleton: Dict, slack_ts: str = None):
    """Persist the briefing to the briefings table."""
    with get_db() as db:
        db.execute(
            text("""
                INSERT INTO briefings (
                    briefing_type, briefing_date, content_markdown,
                    slack_message_ts, portfolio_value, portfolio_change_pct,
                    holdings_flagged, generated_at, sent_at
                ) VALUES (
                    'morning', :briefing_date, :content,
                    :slack_ts, :portfolio_value, :portfolio_change_pct,
                    :holdings_flagged, NOW(), NOW()
                )
            """),
            {
                'briefing_date': today_ist(),
                'content': briefing_text,
                'slack_ts': slack_ts,
                'portfolio_value': skeleton.get('portfolio_summary', {}).get('total_value'),
                'portfolio_change_pct': skeleton.get('portfolio_summary', {}).get('week_change_pct'),
                'holdings_flagged': (
                    skeleton.get('urgent_count', 0) + skeleton.get('attention_count', 0)
                )
            }
        )


def prepend_unacknowledged_alerts(briefing_text: str, unacked_alerts: list) -> str:
    """Prepend unacknowledged alert banner to briefing if needed."""
    if not unacked_alerts:
        return briefing_text

    alert_lines = ["⚠️ *UNACKNOWLEDGED ALERTS FROM YESTERDAY*"]
    for alert in unacked_alerts:
        fired_time = alert.get('fired_at', '')
        alert_lines.append(
            f"• *{alert.get('alert_type', 'Alert')}*: {alert.get('title', '')} "
            f"_(fired at {fired_time})_"
        )
    alert_lines.append("_React with ✅ in #urgent-alerts to acknowledge_\n")
    alert_lines.append("---\n")

    return '\n'.join(alert_lines) + briefing_text


def generate_and_send_morning_briefing() -> Dict:
    """
    Main entry point for morning briefing generation. Returns a dict with
    status, timing, and metadata.
    """
    job_id = log_job_start('morning_briefing')
    start_time = datetime.now(timezone.utc)

    logger.info("=== Morning Briefing Generation Started ===")

    try:
        logger.info("Fetching holdings and market data from database...")

        equity_holdings = get_active_equity_holdings()
        fund_holdings = get_active_fund_holdings()
        market_context = get_latest_market_context()
        portfolio_summary = compute_portfolio_summary()
        unacked_alerts = get_unacknowledged_alerts()

        news_by_ticker = get_recent_news_by_ticker(hours_back=48)
        news_by_fund = get_recent_news_by_fund(hours_back=168)
        filings_by_ticker = get_recent_filings_by_ticker(hours_back=24)

        logger.info(
            f"Data fetched: {len(equity_holdings)} equities, "
            f"{len(fund_holdings)} funds, "
            f"market context available: {bool(market_context)}"
        )

        if not equity_holdings and not fund_holdings:
            logger.warning("No holdings found — skipping briefing generation")
            log_job_complete(job_id, 0)
            return {'status': 'skipped', 'reason': 'no_holdings'}

        analyses = run_parallel_holdings_analysis(
            equity_holdings=equity_holdings,
            fund_holdings=fund_holdings,
            news_by_ticker=news_by_ticker,
            filings_by_ticker=filings_by_ticker,
            news_by_fund=news_by_fund,
            market_context=market_context
        )

        skeleton = assemble_briefing_skeleton(
            analyses=analyses,
            equity_holdings=equity_holdings,
            fund_holdings=fund_holdings,
            portfolio_summary=portfolio_summary,
            market_context=market_context,
            briefing_type='morning'
        )

        briefing_text = synthesize_morning_briefing(skeleton)
        briefing_text = process_briefing_citations(briefing_text)
        briefing_text = prepend_unacknowledged_alerts(briefing_text, unacked_alerts)

        footer = (
            f"\n\n_Generated at {datetime.now(timezone.utc).strftime('%H:%M UTC')} | "
            f"{len(equity_holdings) + len(fund_holdings)} holdings analyzed | "
            f"{skeleton['urgent_count'] + skeleton['attention_count']} flagged_"
        )
        briefing_text += footer

        logger.info("Posting morning briefing to Slack...")
        slack_result = post_to_channel(channel=SLACK_CHANNEL_MORNING, text=briefing_text)
        slack_ts = slack_result.get('ts') if slack_result else None

        save_briefing_to_db(briefing_text, skeleton, slack_ts)

        elapsed_total = (datetime.now(timezone.utc) - start_time).total_seconds()

        log_job_complete(job_id, len(equity_holdings) + len(fund_holdings))
        logger.info(f"=== Morning Briefing Complete: {elapsed_total:.1f}s total ===")

        return {
            'status': 'success',
            'elapsed_seconds': elapsed_total,
            'holdings_analyzed': len(equity_holdings) + len(fund_holdings),
            'urgent_count': skeleton['urgent_count'],
            'attention_count': skeleton['attention_count'],
            'slack_ts': slack_ts
        }

    except Exception as e:
        logger.error(f"Morning briefing generation failed: {e}", exc_info=True)
        log_job_failed(job_id, str(e))

        post_urgent_system_alert(f"🚨 Morning briefing generation failed: {str(e)[:200]}")

        return {'status': 'error', 'error': str(e)}