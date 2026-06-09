"""
Google Sheets watchlist synchronizer.

Reads the watchlist from a Google Sheet and syncs to the
watchlist table in Postgres.

Sheet structure (tab named 'Watchlist'):
    Column A: Type         — 'stock' or 'fund'
    Column B: Identifier   — NSE ticker or Groww fund code
    Column C: Name         — display name
    Column D: Notes        — owner notes
    Column E: Date Added   — YYYY-MM-DD or DD/MM/YYYY
    Column F: Active       — 'yes' or 'no'

Setup:
    1. Create a Google Cloud project and enable Sheets API.
    2. Create a service account and download JSON credentials to
       config/google_service_account.json.
    3. Share the sheet with the service account email (Viewer role).
    4. Set WATCHLIST_SHEET_ID in .env.
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy import text
from config.settings import (
    GOOGLE_SHEETS_CREDENTIALS_PATH,
    WATCHLIST_SHEET_ID,
    WATCHLIST_TAB_NAME,
)
from db.connection import get_db
from utils.logger import get_logger

logger = get_logger('watchlist')

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/drive.readonly',
]


def get_sheets_client() -> gspread.Client:
    """Initialize and return an authenticated Google Sheets client."""
    creds = Credentials.from_service_account_file(
        GOOGLE_SHEETS_CREDENTIALS_PATH,
        scopes=SCOPES,
    )
    return gspread.authorize(creds)


def fetch_watchlist_from_sheets() -> List[Dict]:
    """
    Fetch all rows from the Watchlist tab.

    Returns:
        List of dicts keyed by header row values.

    Raises:
        gspread.exceptions.APIError on auth or access failure.
    """
    client = get_sheets_client()
    spreadsheet = client.open_by_key(WATCHLIST_SHEET_ID)
    worksheet = spreadsheet.worksheet(WATCHLIST_TAB_NAME)
    records = worksheet.get_all_records()
    logger.info(f"Fetched {len(records)} rows from watchlist sheet")
    return records


def _parse_date(date_str: str) -> Optional[datetime]:
    """
    Try to parse a date string in YYYY-MM-DD or DD/MM/YYYY format.
    Returns None if parsing fails.
    """
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_watchlist_row(row: Dict) -> Optional[Dict]:
    """
    Parse a Google Sheets row dict into the watchlist schema.

    Returns None if the row is missing required fields or has
    an invalid item type.
    """
    # Normalise header names to lowercase for flexible matching
    r = {k.lower().strip(): str(v).strip() for k, v in row.items()}

    item_type = r.get('type', '').lower()
    identifier = r.get('identifier', '').strip()

    if not item_type or not identifier:
        return None

    if item_type not in ('stock', 'fund'):
        logger.warning(f"Skipping watchlist row — invalid type '{item_type}' for '{identifier}'")
        return None

    active_raw = r.get('active', 'yes').lower()
    is_active = active_raw in ('yes', 'true', '1', 'y')

    date_raw = r.get('date added') or r.get('date_added', '')
    parsed_date = _parse_date(date_raw) if date_raw else None

    return {
        'item_type':      item_type,
        'identifier':     identifier.upper() if item_type == 'stock' else identifier,
        'display_name':   r.get('name', identifier),
        'notes':          r.get('notes') or None,
        'date_added':     parsed_date,
        'is_active':      is_active,
        'last_synced_at': datetime.utcnow(),
    }


def sync_watchlist_to_db(items: List[Dict]) -> int:
    """
    Sync watchlist items to the database.

    Items no longer present in the sheet are deactivated.
    All current items are upserted.

    Returns:
        Total number of rows processed.
    """
    if not items:
        logger.warning("No watchlist items to sync")
        return 0

    current_identifiers = tuple(i['identifier'] for i in items)

    with get_db() as db:
        db.execute(
            text("""
                UPDATE watchlist
                SET is_active = FALSE, last_synced_at = NOW()
                WHERE identifier NOT IN :identifiers
            """),
            {'identifiers': current_identifiers},
        )

        for item in items:
            db.execute(
                text("""
                    INSERT INTO watchlist (
                        item_type, identifier, display_name, notes,
                        date_added, is_active, last_synced_at
                    ) VALUES (
                        :item_type, :identifier, :display_name, :notes,
                        :date_added, :is_active, :last_synced_at
                    )
                    ON CONFLICT (identifier) DO UPDATE SET
                        item_type      = EXCLUDED.item_type,
                        display_name   = EXCLUDED.display_name,
                        notes          = EXCLUDED.notes,
                        date_added     = COALESCE(EXCLUDED.date_added, watchlist.date_added),
                        is_active      = EXCLUDED.is_active,
                        last_synced_at = EXCLUDED.last_synced_at
                """),
                item,
            )

    active_count = sum(1 for i in items if i['is_active'])
    logger.info(f"Watchlist sync complete: {len(items)} total, {active_count} active")
    return len(items)


def sync_watchlist() -> Dict:
    """
    Main entry point for watchlist sync.

    Returns:
        Dict: {status, total_rows, valid_items, synced, synced_at} on success
              {status, error} on failure
    """
    logger.info("Starting watchlist sync from Google Sheets")

    try:
        raw_rows = fetch_watchlist_from_sheets()
        parsed = [parse_watchlist_row(r) for r in raw_rows]
        valid = [p for p in parsed if p is not None]
        count = sync_watchlist_to_db(valid)

        return {
            'status':      'success',
            'total_rows':  len(raw_rows),
            'valid_items': len(valid),
            'synced':      count,
            'synced_at':   datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Watchlist sync failed: {e}")
        return {'status': 'error', 'error': str(e)}