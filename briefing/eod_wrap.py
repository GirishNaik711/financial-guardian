"""
End-of-Day Wrap Orchestrator.

Shorter pipeline than morning briefing — today-only news window,
equities only, single Opus call, posts to #eod-wrap.

Schedule: 3:35pm IST every trading day.
"""

from datetime import datetime, timezone
from typing import Dict
from sqlalchemy import text

from briefing.data_fetcher import (
    get_active_equity_holdings, get_active_fund_holdings,
    get_recent_news_by_ticker, get_recent_filings_by_ticker,
    get_latest_market_context
)
from briefing.llm_synthesizer import (
    run_parallel_holdings_analysis,
    assemble_briefing_skeleton,
    synthesize_eod_wrap
)
from briefing.citation_builder import process_briefing_citations
from slack.client import post_to_channel
from config import SLACK_CHANNEL_EOD
from db.connection import get_db
from data_pipeline.pipeline_runner import log_job_start, log_job_complete, log_job_failed
from utils.logger import get_logger
from utils.date_utils import today_ist

logger = get_logger('eod_wrap')


def generate_and_send_eod_wrap() -> Dict:
    """
    Main entry point for EOD wrap generation. Uses 8-hour news window
    (today only), equities only, shorter synthesis output.
    """
    job_id = log_job_start('eod_wrap')
    start_time = datetime.now(timezone.utc)

    logger.info("=== EOD Wrap Generation Started ===")

    try:
        equity_holdings = get_active_equity_holdings()
        fund_holdings = get_active_fund_holdings()
        market_context = get_latest_market_context()

        news_by_ticker = get_recent_news_by_ticker(hours_back=8)
        filings_by_ticker = get_recent_filings_by_ticker(hours_back=8)
        news_by_fund: Dict = {}

        analyses = run_parallel_holdings_analysis(
            equity_holdings=equity_holdings,
            fund_holdings=[],
            news_by_ticker=news_by_ticker,
            filings_by_ticker=filings_by_ticker,
            news_by_fund=news_by_fund,
            market_context=market_context
        )

        skeleton = assemble_briefing_skeleton(
            analyses=analyses,
            equity_holdings=equity_holdings,
            fund_holdings=fund_holdings,
            portfolio_summary={'total_value': 0},
            market_context=market_context,
            briefing_type='eod'
        )

        eod_text = synthesize_eod_wrap(skeleton)
        eod_text = process_briefing_citations(eod_text)

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        eod_text += f"\n\n_EOD wrap generated at {datetime.now(timezone.utc).strftime('%H:%M UTC')}_"

        slack_result = post_to_channel(channel=SLACK_CHANNEL_EOD, text=eod_text)

        with get_db() as db:
            db.execute(text("""
                INSERT INTO briefings (
                    briefing_type, briefing_date, content_markdown,
                    slack_message_ts, generated_at, sent_at
                ) VALUES (
                    'eod', :date, :content, :ts, NOW(), NOW()
                )
            """), {
                'date': today_ist(),
                'content': eod_text,
                'ts': slack_result.get('ts') if slack_result else None
            })

        log_job_complete(job_id, len(equity_holdings))
        logger.info(f"=== EOD Wrap Complete: {elapsed:.1f}s ===")

        return {'status': 'success', 'elapsed_seconds': elapsed}

    except Exception as e:
        logger.error(f"EOD wrap failed: {e}", exc_info=True)
        log_job_failed(job_id, str(e))
        return {'status': 'error', 'error': str(e)}