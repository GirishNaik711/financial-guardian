"""
Static bond holdings loader.

Loads bond holdings from config/bonds.yaml and upserts into
the bond_holdings table.

This is a stub for Wint Wealth bonds — no API integration.
Update config/bonds.yaml manually when bond holdings change.
Full replace strategy: clears existing rows and reloads from config.
"""

import yaml
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from sqlalchemy import text
from db.connection import get_db
from utils.logger import get_logger

logger = get_logger('bonds')

BONDS_CONFIG_PATH = Path(__file__).parent.parent / 'config' / 'bonds.yaml'


def load_bonds_from_config() -> List[Dict]:
    """
    Load raw bond entries from YAML config.

    Returns:
        List of raw bond dicts. Empty list if file not found.
    """
    if not BONDS_CONFIG_PATH.exists():
        logger.warning(f"Bonds config not found at {BONDS_CONFIG_PATH}")
        return []

    with open(BONDS_CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)

    bonds = config.get('bonds', [])
    logger.info(f"Loaded {len(bonds)} bonds from config")
    return bonds


def parse_bond(raw: Dict) -> Dict:
    """
    Map a raw bonds.yaml entry to the bond_holdings schema.
    """
    maturity_str = str(raw.get('maturity_date', '')).strip()
    maturity_date: Optional[datetime] = None
    if maturity_str:
        try:
            maturity_date = datetime.strptime(maturity_str, '%Y-%m-%d').date()
        except ValueError:
            logger.warning(f"Could not parse maturity_date: {maturity_str}")

    face_value = float(raw.get('face_value', 1000))

    return {
        'issuer_name':     raw.get('issuer_name', ''),
        'instrument_name': raw.get('instrument_name', ''),
        'isin':            raw.get('isin'),
        'face_value':      face_value,
        'coupon_rate':     float(raw.get('coupon_rate', 0)),
        'maturity_date':   maturity_date,
        'current_value':   float(raw.get('current_value', face_value)),
        'quantity':        int(raw.get('quantity', 1)),
        'is_active':       True,
        'updated_at':      datetime.utcnow(),
    }


def sync_bond_holdings() -> Dict:
    """
    Main entry point for bond holdings sync.

    Clears the bond_holdings table and reloads from config.
    Safe because bond data is manually curated and small.

    Returns:
        Dict: {status, count} on success
              {status, error} on failure
    """
    logger.info("Loading bond holdings from config")

    try:
        raw_bonds = load_bonds_from_config()

        if not raw_bonds:
            logger.info("No bond holdings in config — table cleared")
            with get_db() as db:
                db.execute(text("DELETE FROM bond_holdings"))
            return {'status': 'success', 'count': 0}

        parsed = [parse_bond(b) for b in raw_bonds]

        with get_db() as db:
            db.execute(text("DELETE FROM bond_holdings"))

            for bond in parsed:
                db.execute(
                    text("""
                        INSERT INTO bond_holdings (
                            issuer_name, instrument_name, isin,
                            face_value, coupon_rate, maturity_date,
                            current_value, quantity, is_active, updated_at
                        ) VALUES (
                            :issuer_name, :instrument_name, :isin,
                            :face_value, :coupon_rate, :maturity_date,
                            :current_value, :quantity, :is_active, :updated_at
                        )
                    """),
                    bond,
                )

        logger.info(f"Bond holdings sync complete: {len(parsed)} bonds loaded")
        return {'status': 'success', 'count': len(parsed)}

    except Exception as e:
        logger.error(f"Bond holdings sync failed: {e}")
        return {'status': 'error', 'error': str(e)}