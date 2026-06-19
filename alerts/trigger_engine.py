"""
Alert Trigger Engine.

Evaluates all defined trigger conditions against current data.
Fires immediate Slack alerts when thresholds are crossed.

Deduplication: Redis SET, key = alert_type + identifier + date, 24h TTL.
Run frequency: every 15 min during market hours (Phase 7 scheduler).

Coverage notes:
    - Promoter pledge % is regex-extracted from filing free text — fragile,
      validate against real StockInsights phrasing.
    - Nifty circuit breaker uses a 10% move heuristic — no real exchange
      circuit-breaker flag exists in market_context yet.
    - RBI emergency relies entirely on keyword_scanner matching "RBI emergency"
      in news text — no scheduled-RBI-dates calendar to diff against.
"""

import re
import redis as redis_lib
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from db.connection import get_db
from alerts.slack_alerter import send_urgent_alert
from alerts.keyword_scanner import scan_text_for_urgency
from data_pipeline.pipeline_runner import log_job_start, log_job_complete, log_job_failed
from config import (
    REDIS_URL,
    EQUITY_DROP_ALERT_PCT,
    FUND_NAV_DROP_ALERT_PCT,
    INDIA_VIX_ALERT_THRESHOLD,
    PROMOTER_PLEDGE_ALERT_PCT,
)
from utils.logger import get_logger
from utils.date_utils import today_ist

logger = get_logger('trigger_engine')

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)
DEDUP_TTL_SECONDS = 86400

_HALT_KEYWORDS = ['trading halt', 'trading suspended', 'circuit filter', 'halted']
_BOARD_ACTION_KEYWORDS = ['rights issue', 'merger', 'acquisition', 'fundraising', 'fund raising']
_PLEDGE_PCT_PATTERN = re.compile(r'pledg\w*[^.]{0,80}?(\d+(?:\.\d+)?)\s*%', re.IGNORECASE)


# ─── DEDUPLICATION ─────────────────────────────────────────────

def _dedup_key(alert_type: str, identifier: str) -> str:
    date_str = today_ist().isoformat()
    return f"alert_dedup:{date_str}:{alert_type}:{identifier}"


def _is_duplicate(alert_type: str, identifier: str) -> bool:
    return _redis.exists(_dedup_key(alert_type, identifier)) > 0


def _mark_fired(alert_type: str, identifier: str):
    _redis.setex(_dedup_key(alert_type, identifier), DEDUP_TTL_SECONDS, '1')


# ─── CORE FIRE FUNCTION ────────────────────────────────────────

def fire_alert(
    alert_type: str,
    title: str,
    message: str,
    severity: str = 'urgent',
    related_ticker: str = None,
    related_fund_code: str = None,
    source_url: str = None,
    deduplicate: bool = True
):
    identifier = related_ticker or related_fund_code or 'market'

    if deduplicate and _is_duplicate(alert_type, identifier):
        logger.debug(f"Skipping duplicate alert: {alert_type} for {identifier}")
        return

    slack_ts = send_urgent_alert(
        title=title,
        message=message,
        source_url=source_url,
        related_identifier=identifier
    )

    with get_db() as db:
        db.execute(
            text("""
                INSERT INTO alerts (
                    alert_type, severity, related_ticker,
                    related_fund_code, title, message,
                    source_url, slack_message_ts,
                    slack_channel, fired_at
                ) VALUES (
                    :alert_type, :severity, :related_ticker,
                    :related_fund_code, :title, :message,
                    :source_url, :slack_ts,
                    'urgent-alerts', NOW()
                )
            """),
            {
                'alert_type': alert_type,
                'severity': severity,
                'related_ticker': related_ticker,
                'related_fund_code': related_fund_code,
                'title': title[:200],
                'message': message[:1000],
                'source_url': source_url,
                'slack_ts': slack_ts
            }
        )

    if deduplicate:
        _mark_fired(alert_type, identifier)

    logger.info(f"Alert fired: {alert_type} for {identifier}")


# ─── SHARED HELPERS ────────────────────────────────────────────

def _recent_filings_for_held_tickers(minutes: int = 30) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    with get_db() as db:
        result = db.execute(
            text("""
                SELECT cf.*
                FROM corporate_filings cf
                JOIN equity_holdings eh ON cf.ticker = eh.ticker
                WHERE cf.fetched_at > :cutoff
                  AND eh.is_active = TRUE
                ORDER BY cf.published_at DESC
            """),
            {'cutoff': cutoff}
        )
        return [dict(row._mapping) for row in result]


def _recent_text_for_active_funds(hours: int = 1) -> list:
    """Recent news items joined to active funds by simple name containment."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    with get_db() as db:
        funds = db.execute(text("""
            SELECT fund_code, fund_name, fund_house, fund_type
            FROM fund_holdings WHERE is_active = TRUE
        """)).fetchall()
        news = db.execute(
            text("""
                SELECT headline, summary, source_url, fetched_at
                FROM news_items WHERE fetched_at > :cutoff
            """),
            {'cutoff': cutoff}
        ).fetchall()

    results = []
    for n in news:
        blob = f"{n.headline} {n.summary}".lower()
        for f in funds:
            if f.fund_name and f.fund_name.lower() in blob:
                results.append({
                    'fund_code': f.fund_code,
                    'fund_name': f.fund_name,
                    'fund_house': f.fund_house,
                    'fund_type': f.fund_type,
                    'headline': n.headline,
                    'summary': n.summary,
                    'source_url': n.source_url
                })
    return results


# ─── EQUITY TRIGGERS ─────────────────────────────────────────

def check_equity_price_drops():
    with get_db() as db:
        result = db.execute(text("""
            SELECT
                eh.ticker,
                eh.company_name,
                eh.current_price,
                ps.close_price as prev_close,
                ((eh.current_price - ps.close_price) / ps.close_price * 100) as day_change_pct
            FROM equity_holdings eh
            JOIN price_snapshots ps ON eh.ticker = ps.ticker
            WHERE eh.is_active = TRUE
              AND ps.snapshot_date = (
                  SELECT MAX(snapshot_date) - 1
                  FROM price_snapshots
                  WHERE ticker = eh.ticker
              )
              AND eh.current_price IS NOT NULL
              AND ps.close_price > 0
        """))
        holdings = [dict(row._mapping) for row in result]

    for h in holdings:
        day_change = float(h.get('day_change_pct') or 0)

        if day_change <= -EQUITY_DROP_ALERT_PCT:
            ticker = h['ticker']
            fire_alert(
                alert_type='equity_price_drop',
                title=f"{ticker} down {abs(day_change):.1f}% today",
                message=(
                    f"*{h.get('company_name', ticker)}* ({ticker}) has dropped "
                    f"{abs(day_change):.1f}% today. "
                    f"Current price: ₹{h.get('current_price', 0):,.2f}. "
                    f"Previous close: ₹{h.get('prev_close', 0):,.2f}."
                ),
                related_ticker=ticker
            )


def check_urgent_filings():
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)

    with get_db() as db:
        result = db.execute(
            text("""
                SELECT cf.*, eh.company_name as held_company_name
                FROM corporate_filings cf
                JOIN equity_holdings eh ON cf.ticker = eh.ticker
                WHERE cf.is_urgent = TRUE
                  AND cf.fetched_at > :cutoff
                  AND eh.is_active = TRUE
                ORDER BY cf.published_at DESC
            """),
            {'cutoff': cutoff}
        )
        urgent_filings = [dict(row._mapping) for row in result]

    for filing in urgent_filings:
        ticker = filing.get('ticker', '')
        filing_id = filing.get('filing_id', '')

        fire_alert(
            alert_type=f'urgent_filing_{filing_id}',
            title=f"Urgent filing: {ticker} — {filing.get('announcement_type', '')}",
            message=(
                f"*{filing.get('summary_header', '')}*\n"
                f"{(filing.get('summary_text') or '')[:300]}"
            ),
            related_ticker=ticker,
            source_url=filing.get('source_url'),
            deduplicate=True
        )


def check_news_keyword_triggers():
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)

    with get_db() as db:
        result = db.execute(
            text("""
                SELECT ni.*
                FROM news_items ni
                WHERE ni.fetched_at > :cutoff
                  AND ni.is_urgent = TRUE
                ORDER BY ni.published_at DESC
            """),
            {'cutoff': cutoff}
        )
        urgent_news = [dict(row._mapping) for row in result]

    for item in urgent_news:
        headline = item.get('headline', '') or ''
        summary = item.get('summary', '') or ''

        tickers = item.get('related_tickers') or []
        fund_codes = item.get('related_fund_codes') or []

        identifier = tickers[0] if tickers else (fund_codes[0] if fund_codes else 'market')

        matched_keyword = scan_text_for_urgency(headline + ' ' + summary)

        if matched_keyword:
            fire_alert(
                alert_type=f'news_keyword_{matched_keyword.replace(" ", "_")}',
                title=f"⚠️ Urgent news: {identifier} — {matched_keyword}",
                message=f"*{headline}*\n{summary[:300]}",
                related_ticker=tickers[0] if tickers else None,
                related_fund_code=fund_codes[0] if fund_codes else None,
                source_url=item.get('source_url'),
                deduplicate=True
            )


def check_trading_halts():
    """Detect trading halt/suspension language in recent filings, regardless of is_urgent flag."""
    for filing in _recent_filings_for_held_tickers():
        text_blob = f"{filing.get('announcement_type', '')} {filing.get('summary_text', '')}".lower()
        if any(kw in text_blob for kw in _HALT_KEYWORDS):
            ticker = filing.get('ticker', '')
            fire_alert(
                alert_type='equity_trading_halt',
                title=f"Trading halt: {ticker}",
                message=(
                    f"*{filing.get('summary_header', '')}*\n"
                    f"{(filing.get('summary_text') or '')[:300]}"
                ),
                related_ticker=ticker,
                source_url=filing.get('source_url')
            )


def check_promoter_pledge_increases():
    """Extract pledge % from filing text and fire if it exceeds threshold."""
    for filing in _recent_filings_for_held_tickers():
        summary = filing.get('summary_text') or ''
        header = filing.get('summary_header') or ''
        match = _PLEDGE_PCT_PATTERN.search(summary) or _PLEDGE_PCT_PATTERN.search(header)
        if not match:
            continue

        pct = float(match.group(1))
        if pct >= PROMOTER_PLEDGE_ALERT_PCT:
            ticker = filing.get('ticker', '')
            fire_alert(
                alert_type='promoter_pledge_increase',
                title=f"Promoter pledge increase: {ticker} ({pct:.1f}%)",
                message=(
                    f"*{header}*\n{summary[:300]}\n\n"
                    f"Detected pledge figure: {pct:.1f}%, crossing the "
                    f"{PROMOTER_PLEDGE_ALERT_PCT}% threshold."
                ),
                related_ticker=ticker,
                source_url=filing.get('source_url')
            )


def check_board_meeting_announcements():
    """Board meetings to consider fundraising, rights issue, merger, or acquisition."""
    for filing in _recent_filings_for_held_tickers():
        text_blob = f"{filing.get('announcement_type', '')} {filing.get('summary_text', '')}".lower()
        if 'board meeting' in text_blob and any(kw in text_blob for kw in _BOARD_ACTION_KEYWORDS):
            ticker = filing.get('ticker', '')
            fire_alert(
                alert_type='board_meeting_corporate_action',
                title=f"Board meeting on corporate action: {ticker}",
                message=(
                    f"*{filing.get('summary_header', '')}*\n"
                    f"{(filing.get('summary_text') or '')[:300]}"
                ),
                related_ticker=ticker,
                severity='warning',
                source_url=filing.get('source_url')
            )


def check_insider_trading_disclosures():
    for filing in _recent_filings_for_held_tickers():
        announcement_type = (filing.get('announcement_type') or '').lower()
        summary_text = (filing.get('summary_text') or '').lower()
        if 'insider trading' in announcement_type or 'insider trading' in summary_text:
            ticker = filing.get('ticker', '')
            fire_alert(
                alert_type='insider_trading_disclosure',
                title=f"Insider trading disclosure: {ticker}",
                message=(
                    f"*{filing.get('summary_header', '')}*\n"
                    f"{(filing.get('summary_text') or '')[:300]}"
                ),
                related_ticker=ticker,
                source_url=filing.get('source_url')
            )


# ─── FUND TRIGGERS ────────────────────────────────────────────

def check_fund_nav_drops():
    with get_db() as db:
        result = db.execute(text("""
            SELECT
                fh.fund_code, fh.fund_name,
                fh.current_nav,
                nh_prev.nav_value as prev_nav,
                ((fh.current_nav - nh_prev.nav_value) / nh_prev.nav_value * 100)
                    as nav_change_pct
            FROM fund_holdings fh
            JOIN nav_history nh_prev ON fh.fund_code = nh_prev.fund_code
            WHERE fh.is_active = TRUE
              AND nh_prev.nav_date = (
                  SELECT MAX(nav_date) - 1
                  FROM nav_history
                  WHERE fund_code = fh.fund_code
              )
              AND fh.current_nav IS NOT NULL
        """))
        funds = [dict(row._mapping) for row in result]

    for fund in funds:
        nav_change = float(fund.get('nav_change_pct') or 0)

        if nav_change <= -FUND_NAV_DROP_ALERT_PCT:
            fund_code = fund['fund_code']
            fire_alert(
                alert_type='fund_nav_drop',
                title=f"Fund NAV drop: {fund.get('fund_name', fund_code)}",
                message=(
                    f"*{fund.get('fund_name', fund_code)}* NAV dropped "
                    f"{abs(nav_change):.2f}% today. "
                    f"Current NAV: ₹{fund.get('current_nav', 0):.4f}. "
                    f"This is an unusual single-day movement — check for any "
                    f"fund-specific news."
                ),
                related_fund_code=fund_code
            )


def check_fund_manager_changes():
    for item in _recent_text_for_active_funds():
        if item['fund_type'] != 'active':
            continue
        blob = f"{item['headline']} {item['summary']}".lower()
        if 'fund manager' in blob and any(kw in blob for kw in ['change', 'resign', 'appointed', 'new manager']):
            fire_alert(
                alert_type='fund_manager_change',
                title=f"Fund manager change: {item['fund_name']}",
                message=f"*{item['headline']}*\n{item['summary'][:300]}",
                related_fund_code=item['fund_code'],
                source_url=item['source_url']
            )


def check_fund_redemption_suspensions():
    for item in _recent_text_for_active_funds():
        blob = f"{item['headline']} {item['summary']}".lower()
        if 'redemption' in blob and 'suspend' in blob:
            fire_alert(
                alert_type='fund_redemption_suspension',
                title=f"Redemption suspension: {item['fund_name']}",
                message=f"*{item['headline']}*\n{item['summary'][:300]}",
                related_fund_code=item['fund_code'],
                source_url=item['source_url']
            )


def check_amc_sebi_action():
    for item in _recent_text_for_active_funds():
        blob = f"{item['headline']} {item['summary']}".lower()
        if item['fund_house'] and item['fund_house'].lower() in blob and 'sebi' in blob:
            fire_alert(
                alert_type='amc_sebi_action',
                title=f"SEBI action — {item['fund_house']}",
                message=f"*{item['headline']}*\n{item['summary'][:300]}",
                related_fund_code=item['fund_code'],
                source_url=item['source_url']
            )


# ─── MARKET TRIGGERS ──────────────────────────────────────────

def check_india_vix_threshold():
    with get_db() as db:
        result = db.execute(text("""
            SELECT india_vix FROM market_context
            ORDER BY context_date DESC, context_time DESC
            LIMIT 1
        """)).fetchone()

    if not result or result[0] is None:
        return

    vix_value = float(result[0])

    if vix_value >= INDIA_VIX_ALERT_THRESHOLD:
        fire_alert(
            alert_type='india_vix_threshold',
            title=f"India VIX at {vix_value:.1f} — extreme market fear",
            message=(
                f"India VIX has reached *{vix_value:.1f}*, crossing the "
                f"{INDIA_VIX_ALERT_THRESHOLD} threshold. "
                f"This signals significant market uncertainty. "
                f"Consider reviewing open positions and reducing exposure."
            ),
            severity='urgent',
            deduplicate=True
        )


def check_nifty_circuit_breaker():
    """
    No explicit circuit-breaker flag exists in market_context yet.
    Proxy: an index-wide move of 10%+ intraday corresponds to the lowest
    NSE circuit breaker tier. Treat as a conservative trigger pending a
    real circuit-breaker data source.
    """
    with get_db() as db:
        result = db.execute(text("""
            SELECT nifty_50_change_pct FROM market_context
            ORDER BY context_date DESC, context_time DESC
            LIMIT 1
        """)).fetchone()

    if not result or result[0] is None:
        return

    change_pct = float(result[0])

    if abs(change_pct) >= 10.0:
        fire_alert(
            alert_type='nifty_circuit_breaker',
            title=f"Nifty 50 move of {change_pct:.1f}% — possible circuit breaker",
            message=(
                f"Nifty 50 has moved *{change_pct:.1f}%*, consistent with a "
                f"market-wide circuit filter event. Verify directly with NSE."
            ),
            severity='urgent',
            deduplicate=True
        )


# ─── MAIN ORCHESTRATOR ────────────────────────────────────────

def run_all_trigger_checks():
    job_name = 'alert_trigger_checks'
    job_id = log_job_start(job_name)
    logger.debug("Running alert trigger checks...")

    checks = [
        ('equity_price_drops', check_equity_price_drops),
        ('urgent_filings', check_urgent_filings),
        ('news_keywords', check_news_keyword_triggers),
        ('trading_halts', check_trading_halts),
        ('promoter_pledge', check_promoter_pledge_increases),
        ('board_meetings', check_board_meeting_announcements),
        ('insider_trading', check_insider_trading_disclosures),
        ('fund_nav_drops', check_fund_nav_drops),
        ('fund_manager_changes', check_fund_manager_changes),
        ('fund_redemption_suspensions', check_fund_redemption_suspensions),
        ('amc_sebi_action', check_amc_sebi_action),
        ('india_vix', check_india_vix_threshold),
        ('nifty_circuit_breaker', check_nifty_circuit_breaker),
    ]

    results = {}
    any_failed = False

    for check_name, check_fn in checks:
        try:
            check_fn()
            results[check_name] = 'ok'
        except Exception as e:
            logger.error(f"Alert check failed — {check_name}: {e}")
            results[check_name] = f'error: {e}'
            any_failed = True

    if any_failed:
        log_job_failed(job_id, job_name, "One or more trigger checks failed")
    else:
        log_job_complete(job_id, job_name, records_processed=len(checks))

    return results