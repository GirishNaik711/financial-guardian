def job_price_snapshot():
        """Save EOD price snapshot for P&L tracking."""
        from db.connection import get_db
        from sqlalchemy import text
        from utils.date_utils import today_ist

        with get_db() as db:
            db.execute(text("""
                INSERT INTO price_snapshots (ticker, snapshot_date, close_price)
                SELECT ticker, :today, current_price
                FROM equity_holdings
                WHERE is_active = TRUE AND current_price IS NOT NULL
                ON CONFLICT (ticker, snapshot_date) DO UPDATE SET
                    close_price = EXCLUDED.close_price
            """), {'today': today_ist()})
        logger.info("EOD price snapshot saved")