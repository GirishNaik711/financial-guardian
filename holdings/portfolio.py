"""
Portfolio aggregator and P&L calculator.

Reads all active holdings from Postgres and computes:
    - Total portfolio value (equities + funds + bonds)
    - Total absolute and percentage P&L
    - Week-on-week value change (requires price_snapshots / nav_history)
    - Best and worst performing holding

Does NOT call any external API — computes purely from DB state.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy import text
from db.connection import get_db
from utils.logger import get_logger
from utils.date_utils import today_ist

logger = get_logger('portfolio')


def get_equity_holdings_summary() -> List[Dict]:
    """Return all active equity holdings ordered by current value descending."""
    with get_db() as db:
        result = db.execute(
            text("""
                SELECT ticker, company_name, quantity, avg_buy_price,
                       current_price, current_value, absolute_pnl,
                       pct_pnl, sector, last_synced_at
                FROM equity_holdings
                WHERE is_active = TRUE
                ORDER BY current_value DESC NULLS LAST
            """)
        )
        return [dict(row._mapping) for row in result]


def get_fund_holdings_summary() -> List[Dict]:
    """Return all active fund holdings ordered by current value descending."""
    with get_db() as db:
        result = db.execute(
            text("""
                SELECT fund_code, fund_name, fund_type, fund_house,
                       units_held, purchase_nav, current_nav,
                       current_value, absolute_pnl, pct_pnl,
                       benchmark_index, fund_manager_name, last_synced_at
                FROM fund_holdings
                WHERE is_active = TRUE
                ORDER BY current_value DESC NULLS LAST
            """)
        )
        return [dict(row._mapping) for row in result]


def get_bond_holdings_summary() -> List[Dict]:
    """Return all active bond holdings."""
    with get_db() as db:
        result = db.execute(
            text("""
                SELECT issuer_name, instrument_name, face_value,
                       coupon_rate, maturity_date, current_value, quantity
                FROM bond_holdings
                WHERE is_active = TRUE
            """)
        )
        return [dict(row._mapping) for row in result]


def get_previous_portfolio_value(days_ago: int = 7) -> Optional[float]:
    """
    Estimate portfolio value N days ago using historical snapshots.

    Uses price_snapshots for equities and nav_history for funds.
    Returns None if no historical data is available yet (early in
    system life when the history tables are empty).

    Args:
        days_ago: How many calendar days back to look.

    Returns:
        Float value in INR, or None if data is unavailable.
    """
    target_date = today_ist() - timedelta(days=days_ago)

    with get_db() as db:
        equity_row = db.execute(
            text("""
                SELECT SUM(eh.quantity * ps.close_price) AS equity_value
                FROM equity_holdings eh
                JOIN price_snapshots ps ON eh.ticker = ps.ticker
                WHERE ps.snapshot_date = (
                    SELECT MAX(snapshot_date)
                    FROM price_snapshots
                    WHERE snapshot_date <= :target_date
                )
                AND eh.is_active = TRUE
            """),
            {'target_date': target_date},
        ).fetchone()

        fund_row = db.execute(
            text("""
                SELECT SUM(fh.units_held * nh.nav_value) AS fund_value
                FROM fund_holdings fh
                JOIN nav_history nh ON fh.fund_code = nh.fund_code
                WHERE nh.nav_date = (
                    SELECT MAX(nav_date)
                    FROM nav_history nh2
                    WHERE nh2.fund_code = fh.fund_code
                      AND nh2.nav_date <= :target_date
                )
                AND fh.is_active = TRUE
            """),
            {'target_date': target_date},
        ).fetchone()

    equity_value = float(equity_row[0] or 0) if equity_row else 0.0
    fund_value = float(fund_row[0] or 0) if fund_row else 0.0
    total = equity_value + fund_value

    return total if total > 0 else None


def compute_portfolio_summary() -> Dict:
    """
    Compute and return the complete portfolio summary.

    Returns a dict with:
        total_value         — total INR value across all asset types
        equity_value        — equities sub-total
        fund_value          — mutual funds sub-total
        bond_value          — bonds sub-total
        total_absolute_pnl  — total unrealized P&L (INR)
        total_pct_pnl       — total P&L as percentage of invested
        week_change_value   — INR change vs 7 days ago (None if no history)
        week_change_pct     — % change vs 7 days ago (None if no history)
        best_performer      — {name, type, pct_pnl} of top holding
        worst_performer     — {name, type, pct_pnl} of bottom holding
        equity_holdings     — list of equity holding dicts
        fund_holdings       — list of fund holding dicts
        bond_holdings       — list of bond holding dicts
        computed_at         — ISO timestamp
    """
    equities = get_equity_holdings_summary()
    funds = get_fund_holdings_summary()
    bonds = get_bond_holdings_summary()

    equity_value = sum(float(h.get('current_value') or 0) for h in equities)
    fund_value   = sum(float(h.get('current_value') or 0) for h in funds)
    bond_value   = sum(float(h.get('current_value') or 0) for h in bonds)
    total_value  = equity_value + fund_value + bond_value

    equity_pnl = sum(float(h.get('absolute_pnl') or 0) for h in equities)
    fund_pnl   = sum(float(h.get('absolute_pnl') or 0) for h in funds)
    total_pnl  = equity_pnl + fund_pnl

    total_invested = total_value - total_pnl
    total_pct_pnl  = (total_pnl / total_invested * 100) if total_invested > 0 else 0.0

    prev_value         = get_previous_portfolio_value(days_ago=7)
    week_change_value  = (total_value - prev_value) if prev_value is not None else None
    week_change_pct    = (week_change_value / prev_value * 100) if prev_value else None

    # Rank all holdings by pct_pnl for best/worst
    all_ranked: List[Dict] = []
    for h in equities:
        all_ranked.append({
            'name':    h.get('ticker', ''),
            'type':    'equity',
            'pct_pnl': float(h.get('pct_pnl') or 0),
        })
    for h in funds:
        all_ranked.append({
            'name':    h.get('fund_name', ''),
            'type':    'fund',
            'pct_pnl': float(h.get('pct_pnl') or 0),
        })

    best_performer  = max(all_ranked, key=lambda x: x['pct_pnl']) if all_ranked else None
    worst_performer = min(all_ranked, key=lambda x: x['pct_pnl']) if all_ranked else None

    return {
        'total_value':        round(total_value, 2),
        'equity_value':       round(equity_value, 2),
        'fund_value':         round(fund_value, 2),
        'bond_value':         round(bond_value, 2),
        'total_absolute_pnl': round(total_pnl, 2),
        'total_pct_pnl':      round(total_pct_pnl, 4),
        'week_change_value':  round(week_change_value, 2) if week_change_value is not None else None,
        'week_change_pct':    round(week_change_pct, 4) if week_change_pct is not None else None,
        'best_performer':     best_performer,
        'worst_performer':    worst_performer,
        'equity_holdings':    equities,
        'fund_holdings':      funds,
        'bond_holdings':      bonds,
        'computed_at':        datetime.utcnow().isoformat(),
    }