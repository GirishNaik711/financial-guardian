"""
LLM Briefing Synthesis Engine — Three-Stage Pipeline

Architecture:
    Stage 1: Parallel per-holding analysis (Claude Haiku)
    Stage 2: Pure-Python section assembly (no LLM)
    Stage 3: Single editorial synthesis (Claude Opus)

Model assignments:
    ANALYSIS_MODEL = claude-haiku-4-5-20251001
        Per-holding analysis, structured extraction. Cheap, fast.
    SYNTHESIS_MODEL = claude-opus-4-6
        Final briefing narrative writing, once per briefing cycle.

Parallelism:
    Stage 1 uses ThreadPoolExecutor(max_workers=10).
    Anthropic SDK is thread-safe; each call is fully independent.

Error handling:
    Per-call try/except in Stage 1 — failed holding analysis falls back
    to a safe default object, briefing continues with remaining holdings.
    Stage 3 failure retries once, then falls back to a raw-data summary.
"""

import anthropic
import concurrent.futures
import json
import time
from datetime import datetime, timezone
from typing import Dict, List
from config import ANTHROPIC_API_KEY
from utils.logger import get_logger

logger = get_logger('llm_synthesizer')

ANALYSIS_MODEL = 'claude-haiku-4-5-20251001'
SYNTHESIS_MODEL = 'claude-opus-4-6'

ANALYSIS_MAX_TOKENS = 400
SYNTHESIS_MAX_TOKENS = 3000

MAX_PARALLEL_WORKERS = 10

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ============================================================
# STAGE 1 — PER-HOLDING ANALYSIS (HAIKU, PARALLEL)
# ============================================================

EQUITY_ANALYSIS_SYSTEM = """You are a financial analyst assistant.
Your job is to analyze news and data for a single stock holding and
extract structured information. Be factual, precise, and concise.
Always respond with valid JSON only — no prose, no markdown, no explanation."""

EQUITY_ANALYSIS_PROMPT = """Analyze the following data for stock holding {ticker} and
return a JSON object with exactly these fields:

{{
  "ticker": "{ticker}",
  "holding_type": "equity",
  "urgency": "high|medium|low|none",
  "urgency_reason": "one sentence if urgency is high or medium, else null",
  "sentiment": "bullish|bearish|neutral",
  "key_developments": ["development 1", "development 2"],
  "price_note": "one sentence about price performance",
  "narrative": "2-3 sentence summary of what matters for this holding today",
  "citations": ["url1", "url2"],
  "needs_attention": true|false,
  "attention_reason": "why it needs attention, or null"
}}

HOLDING DATA:
Ticker: {ticker}
Company: {company_name}
Current Price: Rs{current_price}
Day Change: {day_change_pct}%
P&L Since Purchase: {pnl_pct}%
Sector: {sector}

RECENT NEWS (last 24-48 hours):
{news_text}

RECENT FILINGS (BSE/NSE):
{filings_text}

MARKET CONTEXT:
Market regime: {market_regime}
Nifty today: {nifty_change}%
India VIX: {india_vix}

Rules:
- urgency=high ONLY if there is a material regulatory action, management fraud,
  trading halt, or event that could cause >5% move
- urgency=medium if there is earnings result, analyst change, or notable corporate action
- urgency=low for routine news
- urgency=none if no significant news in the data provided
- needs_attention=true if the owner should read this before market open
- citations must be actual URLs from the news data, not fabricated
- If no news data is provided, set urgency=none and narrative to indicate no news found"""

FUND_ANALYSIS_PROMPT = """Analyze the following data for mutual fund holding and
return a JSON object with exactly these fields:

{{
  "fund_code": "{fund_code}",
  "holding_type": "{fund_type}_fund",
  "urgency": "high|medium|low|none",
  "urgency_reason": "one sentence if urgency is high or medium, else null",
  "nav_note": "one sentence about NAV performance vs benchmark",
  "key_developments": ["development 1"],
  "narrative": "2-3 sentence summary of what matters for this fund",
  "citations": ["url1"],
  "needs_attention": true|false,
  "attention_reason": "why it needs attention, or null",
  "benchmark_comparison": "outperforming|underperforming|tracking|unknown"
}}

FUND DATA:
Fund Name: {fund_name}
Fund Type: {fund_type}
Fund House: {fund_house}
Current NAV: Rs{current_nav}
Purchase NAV: Rs{purchase_nav}
P&L: {pnl_pct}%
Benchmark: {benchmark_index}
Fund Manager: {fund_manager}

RECENT NEWS:
{news_text}

Rules:
- urgency=high ONLY for fund manager change, AMC regulatory action, redemption suspension
- urgency=medium for significant underperformance (>2% vs benchmark over 1 month)
- urgency=low for routine news
- For index funds, urgency is almost always low unless the AMC itself has issues
- needs_attention=true only if there is something the owner should act on"""


def _truncate_news_for_prompt(news_items: List[Dict], max_items: int = 3) -> str:
    """Format the most recent N news items for inclusion in the prompt."""
    if not news_items:
        return "No recent news found."

    sorted_items = sorted(
        news_items,
        key=lambda x: x.get('published_at') or datetime.min,
        reverse=True
    )[:max_items]

    lines = []
    for item in sorted_items:
        headline = (item.get('headline') or '')[:150]
        summary = (item.get('summary') or '')[:300]
        url = item.get('source_url', '')
        source = item.get('source', '')

        lines.append(f"[{source}] {headline}")
        if summary and summary != headline:
            lines.append(f"  {summary[:200]}")
        if url:
            lines.append(f"  Source: {url}")
        lines.append("")

    return '\n'.join(lines) if lines else "No recent news found."


def _truncate_filings_for_prompt(filings: List[Dict], max_items: int = 2) -> str:
    """Format the most recent N BSE/NSE filings for inclusion in the prompt."""
    if not filings:
        return "No recent exchange filings."

    sorted_filings = sorted(
        filings,
        key=lambda x: x.get('published_at') or datetime.min,
        reverse=True
    )[:max_items]

    lines = []
    for filing in sorted_filings:
        header = (filing.get('summary_header') or '')[:150]
        text_ = (filing.get('summary_text') or '')[:300]
        url = filing.get('source_url', '')
        filing_type = filing.get('announcement_type', '')

        lines.append(f"[{filing_type}] {header}")
        if text_:
            lines.append(f"  {text_[:200]}")
        if url:
            lines.append(f"  Source: {url}")
        lines.append("")

    return '\n'.join(lines) if lines else "No recent exchange filings."


def _parse_json_response(raw_text: str) -> Dict:
    """Parse a JSON object out of a Haiku response, stripping any markdown fences."""
    raw_text = raw_text.strip()
    if raw_text.startswith('```'):
        raw_text = raw_text.split('```')[1]
        if raw_text.startswith('json'):
            raw_text = raw_text[4:]
    return json.loads(raw_text)


def analyze_equity_holding(
    holding: Dict,
    news_items: List[Dict],
    filings: List[Dict],
    market_context: Dict
) -> Dict:
    """
    Stage 1: Analyze a single equity holding using Haiku.
    Called in parallel for all holdings. Falls back to a safe
    default dict on any error.
    """
    ticker = holding.get('ticker', 'UNKNOWN')

    try:
        news_text = _truncate_news_for_prompt(news_items)
        filings_text = _truncate_filings_for_prompt(filings)

        nifty_data = market_context.get('indices', {}).get('nifty_50', {})
        nifty_change = nifty_data.get('change_pct', 0)
        vix_data = market_context.get('indices', {}).get('india_vix', {})
        india_vix = vix_data.get('current_value', 15)

        prompt = EQUITY_ANALYSIS_PROMPT.format(
            ticker=ticker,
            company_name=holding.get('company_name') or ticker,
            current_price=holding.get('current_price', 0),
            day_change_pct=round(float(holding.get('pct_pnl') or 0), 2),
            pnl_pct=round(float(holding.get('pct_pnl') or 0), 2),
            sector=holding.get('sector') or 'Unknown',
            news_text=news_text,
            filings_text=filings_text,
            market_regime=market_context.get('market_regime', 'unknown'),
            nifty_change=nifty_change,
            india_vix=india_vix
        )

        response = _client.messages.create(
            model=ANALYSIS_MODEL,
            max_tokens=ANALYSIS_MAX_TOKENS,
            system=EQUITY_ANALYSIS_SYSTEM,
            messages=[{"role": "user", "content": prompt}]
        )

        analysis = _parse_json_response(response.content[0].text)

        logger.debug(
            f"Analyzed {ticker}: urgency={analysis.get('urgency')}, "
            f"needs_attention={analysis.get('needs_attention')}"
        )

        return analysis

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error analyzing {ticker}: {e}")
        return _fallback_equity_analysis(ticker, holding)

    except anthropic.RateLimitError:
        logger.warning(f"Rate limit hit analyzing {ticker}. Waiting 30s.")
        time.sleep(30)
        return _fallback_equity_analysis(ticker, holding)

    except Exception as e:
        logger.error(f"Error analyzing holding {ticker}: {e}")
        return _fallback_equity_analysis(ticker, holding)


def analyze_fund_holding(
    holding: Dict,
    news_items: List[Dict],
    market_context: Dict
) -> Dict:
    """Stage 1: Analyze a single mutual fund holding using Haiku."""
    fund_code = holding.get('fund_code', 'UNKNOWN')
    fund_name = holding.get('fund_name') or fund_code

    try:
        news_text = _truncate_news_for_prompt(news_items)

        prompt = FUND_ANALYSIS_PROMPT.format(
            fund_code=fund_code,
            fund_name=fund_name,
            fund_type=holding.get('fund_type', 'active'),
            fund_house=holding.get('fund_house') or 'Unknown',
            current_nav=holding.get('current_nav', 0),
            purchase_nav=holding.get('purchase_nav', 0),
            pnl_pct=round(float(holding.get('pct_pnl') or 0), 2),
            benchmark_index=holding.get('benchmark_index') or 'Unknown',
            fund_manager=holding.get('fund_manager_name') or 'Unknown',
            news_text=news_text
        )

        response = _client.messages.create(
            model=ANALYSIS_MODEL,
            max_tokens=ANALYSIS_MAX_TOKENS,
            system=EQUITY_ANALYSIS_SYSTEM,
            messages=[{"role": "user", "content": prompt}]
        )

        analysis = _parse_json_response(response.content[0].text)
        logger.debug(f"Analyzed fund {fund_code}: urgency={analysis.get('urgency')}")
        return analysis

    except Exception as e:
        logger.error(f"Error analyzing fund {fund_code}: {e}")
        return _fallback_fund_analysis(fund_code, holding)


def _fallback_equity_analysis(ticker: str, holding: Dict) -> Dict:
    """Safe fallback object when equity analysis fails."""
    return {
        'ticker': ticker,
        'holding_type': 'equity',
        'urgency': 'none',
        'urgency_reason': None,
        'sentiment': 'neutral',
        'key_developments': [],
        'price_note': f"Price data available but analysis failed for {ticker}",
        'narrative': f"Analysis temporarily unavailable for {ticker}. Check manually.",
        'citations': [],
        'needs_attention': False,
        'attention_reason': None,
        '_analysis_failed': True
    }


def _fallback_fund_analysis(fund_code: str, holding: Dict) -> Dict:
    """Safe fallback object when fund analysis fails."""
    return {
        'fund_code': fund_code,
        'holding_type': 'fund',
        'urgency': 'none',
        'urgency_reason': None,
        'nav_note': 'NAV data available but analysis failed',
        'key_developments': [],
        'narrative': f"Analysis temporarily unavailable for {holding.get('fund_name', fund_code)}.",
        'citations': [],
        'needs_attention': False,
        'attention_reason': None,
        'benchmark_comparison': 'unknown',
        '_analysis_failed': True
    }


def run_parallel_holdings_analysis(
    equity_holdings: List[Dict],
    fund_holdings: List[Dict],
    news_by_ticker: Dict[str, List[Dict]],
    filings_by_ticker: Dict[str, List[Dict]],
    news_by_fund: Dict[str, List[Dict]],
    market_context: Dict
) -> Dict[str, Dict]:
    """
    Stage 1 orchestrator: run all holding analyses in parallel via
    ThreadPoolExecutor. Returns dict mapping identifier -> analysis result.
    """
    results = {}
    tasks = []

    for holding in equity_holdings:
        ticker = holding['ticker']
        tasks.append({
            'type': 'equity',
            'key': ticker,
            'holding': holding,
            'news': news_by_ticker.get(ticker, []),
            'filings': filings_by_ticker.get(ticker, []),
        })

    for holding in fund_holdings:
        fund_code = holding['fund_code']
        tasks.append({
            'type': 'fund',
            'key': fund_code,
            'holding': holding,
            'news': news_by_fund.get(fund_code, []),
        })

    if not tasks:
        logger.info("Stage 1: no holdings to analyze")
        return results

    logger.info(
        f"Stage 1: Running parallel analysis for {len(tasks)} holdings "
        f"using {ANALYSIS_MODEL}"
    )

    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(MAX_PARALLEL_WORKERS, len(tasks))
    ) as executor:

        future_to_key = {}

        for task in tasks:
            if task['type'] == 'equity':
                future = executor.submit(
                    analyze_equity_holding,
                    task['holding'], task['news'], task['filings'], market_context
                )
            else:
                future = executor.submit(
                    analyze_fund_holding,
                    task['holding'], task['news'], market_context
                )
            future_to_key[future] = task['key']

        for future in concurrent.futures.as_completed(future_to_key, timeout=120):
            key = future_to_key[future]
            try:
                results[key] = future.result()
            except Exception as e:
                logger.error(f"Future failed for {key}: {e}")
                results[key] = {'_analysis_failed': True, 'urgency': 'none'}

    elapsed = time.time() - start_time
    failed = sum(1 for r in results.values() if r.get('_analysis_failed'))

    logger.info(
        f"Stage 1 complete: {len(results)} analyses in {elapsed:.1f}s "
        f"({failed} failed, {len(results) - failed} succeeded)"
    )

    return results


# ============================================================
# STAGE 2 — PURE PYTHON SECTION ASSEMBLY (NO LLM)
# ============================================================

def assemble_briefing_skeleton(
    analyses: Dict[str, Dict],
    equity_holdings: List[Dict],
    fund_holdings: List[Dict],
    portfolio_summary: Dict,
    market_context: Dict,
    briefing_type: str = 'morning'
) -> Dict:
    """
    Stage 2: Assemble the briefing data skeleton from Stage 1 outputs.
    Pure Python — sorts, categorizes, and structures data into sections
    Stage 3 will write prose for.
    """
    urgent_items = []
    attention_items = []
    routine_items = []

    urgency_rank = {'high': 3, 'medium': 2, 'low': 1, 'none': 0}

    for identifier, analysis in analyses.items():
        urgency = analysis.get('urgency', 'none')
        needs_attention = analysis.get('needs_attention', False)

        item = {'identifier': identifier, 'analysis': analysis}

        if urgency == 'high':
            urgent_items.append(item)
        elif urgency == 'medium' or needs_attention:
            attention_items.append(item)
        else:
            routine_items.append(item)

    urgent_items.sort(
        key=lambda x: urgency_rank.get(x['analysis'].get('urgency', 'none'), 0),
        reverse=True
    )
    attention_items.sort(
        key=lambda x: x['analysis'].get('needs_attention', False), reverse=True
    )

    equity_performance = []
    for h in equity_holdings:
        ticker = h['ticker']
        equity_performance.append({
            'ticker': ticker,
            'current_price': h.get('current_price', 0),
            'pct_pnl': h.get('pct_pnl', 0),
            'current_value': h.get('current_value', 0),
            'analysis_narrative': analyses.get(ticker, {}).get('narrative', '')
        })
    equity_performance.sort(key=lambda x: abs(float(x.get('pct_pnl') or 0)), reverse=True)

    fund_summary = []
    for h in fund_holdings:
        fund_code = h['fund_code']
        fund_analysis = analyses.get(fund_code, {})
        fund_summary.append({
            'fund_name': h.get('fund_name', ''),
            'fund_type': h.get('fund_type', 'active'),
            'current_value': h.get('current_value', 0),
            'pct_pnl': h.get('pct_pnl', 0),
            'current_nav': h.get('current_nav', 0),
            'benchmark_index': h.get('benchmark_index', ''),
            'benchmark_comparison': fund_analysis.get('benchmark_comparison', 'unknown'),
            'analysis_narrative': fund_analysis.get('narrative', ''),
            'needs_attention': fund_analysis.get('needs_attention', False)
        })

    all_citations = []
    for analysis in analyses.values():
        for cite in analysis.get('citations', []) or []:
            if cite and cite not in all_citations:
                all_citations.append(cite)

    nifty_data = market_context.get('indices', {}).get('nifty_50', {})
    sensex_data = market_context.get('indices', {}).get('sensex', {})
    vix_data = market_context.get('indices', {}).get('india_vix', {})
    flows = market_context.get('flows', {})
    global_data = market_context.get('global', {})

    market_summary = {
        'nifty_value': nifty_data.get('current_value'),
        'nifty_change_pct': nifty_data.get('change_pct'),
        'sensex_value': sensex_data.get('current_value'),
        'sensex_change_pct': sensex_data.get('change_pct'),
        'india_vix': vix_data.get('current_value'),
        'fii_net_cr': flows.get('fii_net_cr'),
        'dii_net_cr': flows.get('dii_net_cr'),
        'usd_inr': global_data.get('usd_inr', {}).get('value'),
        'crude_oil': global_data.get('crude_oil', {}).get('value'),
        'sp500_change_pct': global_data.get('sp500', {}).get('change_pct'),
        'market_regime': market_context.get('market_regime', 'unknown'),
        'key_alerts': market_context.get('key_alerts', []),
        'geopolitical_summary': market_context.get('geopolitical', {}).get('content', ''),
        'geopolitical_citations': market_context.get('geopolitical', {}).get('citations', [])
    }

    skeleton = {
        'briefing_type': briefing_type,
        'generated_at': datetime.now(timezone.utc).isoformat(),

        'market_summary': market_summary,

        'portfolio_summary': {
            'total_value': portfolio_summary.get('total_value', 0),
            'total_pnl_pct': portfolio_summary.get('total_pct_pnl', 0),
            'total_pnl_abs': portfolio_summary.get('total_absolute_pnl', 0),
            'week_change_pct': portfolio_summary.get('week_change_pct'),
            'week_change_value': portfolio_summary.get('week_change_value'),
            'best_performer': portfolio_summary.get('best_performer'),
            'worst_performer': portfolio_summary.get('worst_performer'),
            'equity_value': portfolio_summary.get('equity_value', 0),
            'fund_value': portfolio_summary.get('fund_value', 0)
        },

        'urgent_items': urgent_items,
        'attention_items': attention_items,
        'routine_items': routine_items,
        'fund_summary': fund_summary,
        'equity_performance': equity_performance,
        'all_citations': all_citations,

        'total_holdings_analyzed': len(analyses),
        'urgent_count': len(urgent_items),
        'attention_count': len(attention_items),
        'routine_count': len(routine_items)
    }

    logger.info(
        f"Stage 2 assembly complete: {len(urgent_items)} urgent, "
        f"{len(attention_items)} need attention, {len(routine_items)} routine"
    )

    return skeleton


# ============================================================
# STAGE 3 — EDITORIAL SYNTHESIS (OPUS, SINGLE CALL)
# ============================================================

MORNING_BRIEFING_SYSTEM = """You are a personal financial analyst writing a daily morning briefing
for your client. Your client is a retail investor in Indian markets who wants clear,
actionable intelligence — not jargon, not fluff, not disclaimers.

Your briefing must:
- Be written in plain English, like a trusted advisor talking to a friend
- Lead with what matters most — urgency first
- Include specific numbers (prices, percentages, rupee amounts)
- Include source citations as [Source Name](URL) inline with claims
- Be honest about uncertainty — say "no significant news" when there isn't any
- Never give explicit buy/sell recommendations — say "this may need your attention" instead
- Use Rs symbol for rupee amounts

Format your response as a structured Slack message using these exact section headers:
🌅 MARKET PULSE
💼 YOUR PORTFOLIO
⚠️ NEEDS YOUR ATTENTION (only if there are items — omit section if nothing urgent)
✅ ALL CLEAR ON THESE
📊 MUTUAL FUNDS
📅 WEEK AHEAD

Do not add any other sections. Do not add disclaimers. Do not add a sign-off."""

EOD_BRIEFING_SYSTEM = """You are a personal financial analyst writing an end-of-day wrap
for your client. This is a brief, focused summary of what happened today.

Format using these exact section headers:
📈 TODAY'S PERFORMANCE
📰 NEWS THAT MATTERS
🔔 WATCH TOMORROW

Keep it short — this is a wrap, not a full briefing. Total length under 400 words."""


def _compact_skeleton(skeleton: Dict) -> Dict:
    """Remove verbose/empty fields from skeleton before sending to Opus."""
    compact = {}

    ms = skeleton.get('market_summary', {})
    compact['market'] = {k: v for k, v in ms.items() if v is not None and v != ''}

    compact['portfolio'] = skeleton.get('portfolio_summary', {})
    compact['urgent'] = skeleton.get('urgent_items', [])
    compact['attention'] = skeleton.get('attention_items', [])

    compact['routine'] = [
        {
            'identifier': item['identifier'],
            'narrative': item['analysis'].get('narrative', ''),
            'sentiment': item['analysis'].get('sentiment', 'neutral')
        }
        for item in skeleton.get('routine_items', [])
    ]

    compact['funds'] = skeleton.get('fund_summary', [])

    geo = skeleton.get('market_summary', {}).get('geopolitical_summary', '')
    compact['geopolitical'] = geo[:500] if geo else ''

    return compact


def _compact_skeleton_eod(skeleton: Dict) -> Dict:
    """Compact skeleton specifically for EOD wrap — focus on performance."""
    return {
        'performance': skeleton.get('equity_performance', [])[:10],
        'urgent': skeleton.get('urgent_items', []),
        'attention': skeleton.get('attention_items', []),
        'market': {
            'nifty_change_pct': skeleton.get('market_summary', {}).get('nifty_change_pct'),
            'india_vix': skeleton.get('market_summary', {}).get('india_vix'),
            'fii_net_cr': skeleton.get('market_summary', {}).get('fii_net_cr')
        }
    }


def synthesize_morning_briefing(skeleton: Dict, _is_retry: bool = False) -> str:
    """Stage 3: Write the morning briefing narrative using Claude Opus."""
    logger.info(f"Stage 3: Synthesizing morning briefing using {SYNTHESIS_MODEL}")

    compact = _compact_skeleton(skeleton)
    skeleton_json = json.dumps(compact, indent=None, default=str)

    if len(skeleton_json) > 8000:
        compact['routine'] = compact.get('routine', [])[:3]
        skeleton_json = json.dumps(compact, indent=None, default=str)
        logger.warning("Skeleton trimmed to fit token budget")

    try:
        response = _client.messages.create(
            model=SYNTHESIS_MODEL,
            max_tokens=SYNTHESIS_MAX_TOKENS,
            system=MORNING_BRIEFING_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Write the morning briefing based on this data:\n\n{skeleton_json}"
            }]
        )

        briefing_text = response.content[0].text.strip()

        logger.info(
            f"Stage 3 complete: {len(briefing_text)} chars, "
            f"~{response.usage.output_tokens} tokens output"
        )

        return briefing_text

    except anthropic.RateLimitError:
        if _is_retry:
            logger.error("Opus rate limit hit again on retry. Falling back.")
            return _fallback_briefing_text(skeleton)
        logger.error("Opus rate limit hit during synthesis. Waiting 60s.")
        time.sleep(60)
        return synthesize_morning_briefing(skeleton, _is_retry=True)

    except Exception as e:
        logger.error(f"Stage 3 synthesis failed: {e}")
        return _fallback_briefing_text(skeleton)


def synthesize_eod_wrap(skeleton: Dict) -> str:
    """Stage 3: Write the EOD wrap using Claude Opus. Shorter output."""
    logger.info(f"Stage 3: Synthesizing EOD wrap using {SYNTHESIS_MODEL}")

    compact = _compact_skeleton_eod(skeleton)
    skeleton_json = json.dumps(compact, indent=None, default=str)

    try:
        response = _client.messages.create(
            model=SYNTHESIS_MODEL,
            max_tokens=1500,
            system=EOD_BRIEFING_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Write the end-of-day wrap based on this data:\n\n{skeleton_json}"
            }]
        )
        return response.content[0].text.strip()

    except Exception as e:
        logger.error(f"EOD synthesis failed: {e}")
        return _fallback_eod_text(skeleton)


def _fallback_briefing_text(skeleton: Dict) -> str:
    """Emergency fallback briefing when Opus synthesis fails."""
    portfolio = skeleton.get('portfolio_summary', {})
    lines = [
        "🛡️ *Financial Guardian — Morning Briefing*",
        "_(LLM synthesis failed — raw data summary)_\n",
        "💼 *PORTFOLIO*",
        f"Total value: Rs{float(portfolio.get('total_value') or 0):,.2f}",
        f"P&L: {float(portfolio.get('total_pnl_pct') or 0):.2f}%\n",
    ]

    urgent = skeleton.get('urgent_items', [])
    if urgent:
        lines.append("⚠️ *URGENT ITEMS*")
        for item in urgent:
            lines.append(f"• {item['identifier']}: {item['analysis'].get('urgency_reason', '')}")

    lines.append("\n_Check system logs for synthesis error details._")
    return '\n'.join(lines)


def _fallback_eod_text(skeleton: Dict) -> str:
    """Emergency fallback EOD wrap."""
    lines = ["📈 *EOD Wrap — data summary (synthesis failed)*\n"]
    for perf in skeleton.get('equity_performance', [])[:5]:
        change = float(perf.get('pct_pnl') or 0)
        arrow = "▲" if change > 0 else "▼"
        lines.append(f"• {perf['ticker']}: {arrow} {abs(change):.2f}%")
    return '\n'.join(lines)