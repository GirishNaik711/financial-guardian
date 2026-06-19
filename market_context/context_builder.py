"""
Market context builder — main orchestrator for Phase 4.

Assembles a complete market context dict by calling all sub-modules.
Consumed by Phase 5's LLM briefing layer.
"""

import json
from datetime import datetime, timezone
from typing import Dict, List
from sqlalchemy import text
from db.connection import get_db
from market_context.nifty import fetch_nifty_data, classify_market_regime
from market_context.macro import fetch_fii_dii_flows, fetch_global_indicators
from market_context.sectors import get_sector_context
from market_context.geopolitical import fetch_geopolitical_context
from data_pipeline.pipeline_runner import log_job_start, log_job_complete, log_job_failed
from utils.logger import get_logger
from utils.date_utils import today_ist, now_ist

logger = get_logger('context_builder')


def identify_key_alerts(context: Dict) -> List[str]:
    """Identify notable conditions from market context for briefing inclusion."""
    alerts = []

    vix_data = context.get('indices', {}).get('india_vix', {})
    vix_value = vix_data.get('current_value', 0) or 0
    if vix_value > 25:
        alerts.append(f"India VIX at {vix_value:.1f} — extreme caution")
    elif vix_value > 20:
        alerts.append(f"India VIX elevated at {vix_value:.1f} — market stress")

    nifty_data = context.get('indices', {}).get('nifty_50', {})
    nifty_change = nifty_data.get('change_pct', 0) or 0
    if abs(nifty_change) > 1.5:
        direction = "up" if nifty_change > 0 else "down"
        alerts.append(f"Nifty {direction} {abs(nifty_change):.1f}% today")

    fii_flow = context.get('flows', {}).get('fii_net_cr')
    if fii_flow is not None:
        if fii_flow > 2000:
            alerts.append(f"Strong FII buying: Rs{fii_flow:,.0f}Cr net inflow")
        elif fii_flow < -2000:
            alerts.append(f"Heavy FII selling: Rs{abs(fii_flow):,.0f}Cr net outflow")

    inr_data = context.get('global', {}).get('usd_inr', {})
    inr_change = inr_data.get('change_pct', 0) or 0
    if inr_change > 0.5:
        alerts.append(f"Rupee weakening: USD/INR change +{inr_change:.2f}%")

    crude_data = context.get('global', {}).get('crude_oil', {})
    crude_change = crude_data.get('change_pct', 0) or 0
    if crude_change > 3:
        alerts.append(f"Crude oil surge: +{crude_change:.1f}% — inflationary pressure")

    return alerts


def save_context_to_db(context: Dict):
    """Save market context snapshot to database."""
    indices = context.get('indices', {})
    flows = context.get('flows', {})
    global_data = context.get('global', {})

    with get_db() as db:
        db.execute(
            text("""
                INSERT INTO market_context (
                    context_date, context_time,
                    nifty_50_value, nifty_50_change_pct,
                    sensex_value, sensex_change_pct,
                    india_vix,
                    fii_net_flow_cr, dii_net_flow_cr,
                    usd_inr, crude_oil_usd,
                    sp500_change_pct, nasdaq_change_pct,
                    market_regime,
                    sector_performance,
                    geopolitical_summary,
                    raw_context_json
                ) VALUES (
                    :context_date, :context_time,
                    :nifty_50_value, :nifty_50_change_pct,
                    :sensex_value, :sensex_change_pct,
                    :india_vix,
                    :fii_net_flow_cr, :dii_net_flow_cr,
                    :usd_inr, :crude_oil_usd,
                    :sp500_change_pct, :nasdaq_change_pct,
                    :market_regime,
                    :sector_performance,
                    :geopolitical_summary,
                    :raw_context_json
                )
            """),
            {
                'context_date': today_ist(),
                'context_time': now_ist().time(),
                'nifty_50_value': indices.get('nifty_50', {}).get('current_value'),
                'nifty_50_change_pct': indices.get('nifty_50', {}).get('change_pct'),
                'sensex_value': indices.get('sensex', {}).get('current_value'),
                'sensex_change_pct': indices.get('sensex', {}).get('change_pct'),
                'india_vix': indices.get('india_vix', {}).get('current_value'),
                'fii_net_flow_cr': flows.get('fii_net_cr'),
                'dii_net_flow_cr': flows.get('dii_net_cr'),
                'usd_inr': global_data.get('usd_inr', {}).get('value'),
                'crude_oil_usd': global_data.get('crude_oil', {}).get('value'),
                'sp500_change_pct': global_data.get('sp500', {}).get('change_pct'),
                'nasdaq_change_pct': global_data.get('nasdaq', {}).get('change_pct'),
                'market_regime': context.get('market_regime', 'unknown'),
                'sector_performance': json.dumps(context.get('sectors', {})),
                'geopolitical_summary': context.get('geopolitical', {}).get('content', ''),
                'raw_context_json': json.dumps(context, default=str)
            }
        )


def build_market_context() -> Dict:
    """
    Main entry point — builds complete market context.

    Called every morning before briefing generation, and before EOD wrap.
    Always returns a usable dict (degrades to minimal context on failure
    so the briefing layer can still proceed).
    """
    job_id = log_job_start('build_market_context')
    logger.info("Building market context...")

    try:
        context = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'market_date': today_ist().isoformat()
        }

        logger.info("Fetching index data...")
        indices = fetch_nifty_data()
        context['indices'] = indices

        logger.info("Fetching FII/DII flows...")
        flows = fetch_fii_dii_flows()
        context['flows'] = flows

        logger.info("Fetching global indicators...")
        global_data = fetch_global_indicators()
        context['global'] = global_data

        logger.info("Fetching sector performance...")
        sectors = get_sector_context()
        context['sectors'] = sectors

        logger.info("Fetching geopolitical context...")
        geopolitical = fetch_geopolitical_context()
        context['geopolitical'] = geopolitical

        nifty_change = indices.get('nifty_50', {}).get('change_pct', 0) or 0
        vix_level = indices.get('india_vix', {}).get('current_value', 15) or 15
        fii_flow = flows.get('fii_net_cr', 0) or 0

        regime = classify_market_regime(nifty_change, vix_level, fii_flow)
        context['market_regime'] = regime
        logger.info(f"Market regime classified as: {regime}")

        context['key_alerts'] = identify_key_alerts(context)

        save_context_to_db(context)

        log_job_complete(job_id)
        logger.info("Market context built successfully")

        return context

    except Exception as e:
        logger.error(f"Market context build failed: {e}")
        log_job_failed(job_id, str(e))

        return {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'market_date': today_ist().isoformat(),
            'indices': {},
            'flows': {},
            'global': {},
            'sectors': {},
            'geopolitical': {'content': 'Market context unavailable', 'citations': []},
            'market_regime': 'unknown',
            'key_alerts': ['Market context data unavailable — check system logs'],
            'error': str(e)
        }


def get_latest_context_from_db() -> Dict:
    """Retrieve the most recently stored market context from database."""
    with get_db() as db:
        result = db.execute(
            text("""
                SELECT * FROM market_context
                ORDER BY context_date DESC, context_time DESC
                LIMIT 1
            """)
        ).fetchone()

        if result:
            return dict(result._mapping)

        return {}