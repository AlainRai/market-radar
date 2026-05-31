"""
MarketRadar — Signal Bot (AI Brain)
=====================================
Calls Claude API for each stock with:
  - Full technical indicator snapshot
  - Recent news headlines
  - Market context

Claude returns a structured signal:
  { signal, probability, target_price, stop_loss, rationale, confidence }

Saves each signal to Supabase.
"""

import os
import json
import logging
import time
from datetime import datetime, timezone

import anthropic

from db import get_active_stocks, insert_signal

log = logging.getLogger(__name__)

# Initialise Claude client
_claude = None
def get_claude():
    global _claude
    if _claude is None:
        _claude = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
    return _claude


# ── The core prompt sent to Claude for each stock ────────────────────────────
ANALYSIS_SYSTEM_PROMPT = """You are an expert quantitative analyst specialising in 
Saudi Tadawul and global equity markets. You analyse technical indicators and news 
to generate precise, actionable trading signals.

You must respond ONLY with a valid JSON object — no preamble, no explanation outside 
the JSON, no markdown backticks.

Your analysis must be objective, data-driven, and clearly explain your reasoning.
Conservative probability estimates are better than overconfident ones.
Always consider downside risk equally with upside potential."""


def build_analysis_prompt(symbol: str, stock_info: dict,
                           price_data: dict, news_headlines: list[str]) -> str:
    """Build the full prompt for Claude given all available data."""

    # Format technical indicators
    rsi = price_data.get('rsi')
    rsi_interp = ''
    if rsi is not None:
        if rsi > 70:   rsi_interp = '(overbought — caution)'
        elif rsi < 30: rsi_interp = '(oversold — potential bounce)'
        elif rsi > 55: rsi_interp = '(bullish momentum)'
        elif rsi < 45: rsi_interp = '(bearish momentum)'
        else:          rsi_interp = '(neutral)'

    ma50  = price_data.get('ma50')
    ma200 = price_data.get('ma200')
    price = price_data.get('current_price', 0)

    ma_position = ''
    if ma50 and ma200 and price:
        above50  = price > ma50
        above200 = price > ma200
        ma_position = f"Price is {'above' if above50 else 'below'} 50-MA and {'above' if above200 else 'below'} 200-MA."

    golden = '⚡ GOLDEN CROSS just triggered (50-MA crossed above 200-MA)' if price_data.get('golden_cross') else ''
    death  = '⚠️ DEATH CROSS just triggered (50-MA crossed below 200-MA)' if price_data.get('death_cross') else ''

    vol_ratio = price_data.get('volume_ratio')
    vol_note = ''
    if vol_ratio:
        if vol_ratio > 2.5:    vol_note = f'Volume is {vol_ratio:.1f}x average — VERY HIGH (strong institutional interest)'
        elif vol_ratio > 1.5:  vol_note = f'Volume is {vol_ratio:.1f}x average — elevated'
        elif vol_ratio < 0.5:  vol_note = f'Volume is {vol_ratio:.1f}x average — very low (low conviction)'
        else:                  vol_note = f'Volume is {vol_ratio:.1f}x average — normal'

    bb = price_data.get('bb_position')
    bb_note = ''
    if bb is not None:
        if bb > 0.9:   bb_note = 'Price near UPPER Bollinger Band (potential resistance / overbought)'
        elif bb < 0.1: bb_note = 'Price near LOWER Bollinger Band (potential support / oversold)'
        else:          bb_note = f'Price at {bb:.0%} of Bollinger Band range'

    news_section = ''
    if news_headlines:
        headlines_fmt = '\n'.join(f'  • {h}' for h in news_headlines[:8])
        news_section = f"""
RECENT NEWS ({len(news_headlines)} articles found):
{headlines_fmt}"""
    else:
        news_section = '\nRECENT NEWS: No specific news found in last 24 hours.'

    market = stock_info.get('market', 'global')
    sector = stock_info.get('sector', 'Unknown')
    name   = stock_info.get('name', symbol)

    return f"""Analyse this stock and generate a trading signal.

STOCK: {symbol} — {name}
MARKET: {market.upper()} | SECTOR: {sector}

CURRENT PRICE DATA:
  Price:        {price:.4f}
  Change today: {price_data.get('price_change_pct', 0):+.2f}%
  52-week high: {price_data.get('high_52w', 'N/A')}
  52-week low:  {price_data.get('low_52w', 'N/A')}

TECHNICAL INDICATORS:
  RSI (14):     {rsi} {rsi_interp}
  MACD:         {price_data.get('macd', 'N/A')}
  MACD Signal:  {price_data.get('macd_signal', 'N/A')}
  MACD Hist:    {price_data.get('macd_histogram', 'N/A')}
  50-day MA:    {ma50}
  200-day MA:   {ma200}
  {ma_position}
  {golden}
  {death}
  5-day trend:  {price_data.get('trend_5d', 'N/A')}% slope
  {vol_note}
  {bb_note}
{news_section}

Generate a signal. Respond with ONLY this JSON (no other text):
{{
  "signal": "buy" | "sell" | "watch",
  "probability": <integer 40-95, realistic probability of reaching target in 72 hours>,
  "target_price": <realistic price target>,
  "stop_loss": <price level where thesis is invalidated>,
  "rationale": "<2-3 sentence explanation combining technical + news context. Be specific about which indicators drove the decision.>",
  "confidence": "high" | "medium" | "low",
  "key_catalyst": "<the single most important factor behind this signal>",
  "risk_factor": "<the main risk that could invalidate this signal>"
}}"""


def parse_claude_response(response_text: str) -> dict | None:
    """Parse Claude's JSON response, handling any formatting issues."""
    # Strip any accidental markdown backticks
    text = response_text.strip()
    if text.startswith('```'):
        lines = text.split('\n')
        text = '\n'.join(lines[1:-1] if lines[-1] == '```' else lines[1:])

    try:
        data = json.loads(text)
        # Validate required fields
        assert data.get('signal') in ('buy', 'sell', 'watch')
        assert isinstance(data.get('probability'), (int, float))
        assert isinstance(data.get('target_price'), (int, float))
        return data
    except (json.JSONDecodeError, AssertionError, KeyError) as e:
        log.warning(f"  JSON parse failed: {e} | Response: {text[:200]}")
        return None


def generate_signal_for_stock(symbol: str, stock_info: dict,
                               price_data: dict, news_headlines: list[str]) -> dict | None:
    """Call Claude API for one stock and return parsed signal."""
    claude = get_claude()
    prompt = build_analysis_prompt(symbol, stock_info, price_data, news_headlines)

    try:
        response = claude.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=600,
            system=ANALYSIS_SYSTEM_PROMPT,
            messages=[{'role': 'user', 'content': prompt}]
        )
        raw = response.content[0].text
        signal = parse_claude_response(raw)

        if signal:
            log.info(f"  {symbol}: {signal['signal'].upper()} "
                     f"prob={signal['probability']}% "
                     f"target={signal['target_price']} "
                     f"conf={signal['confidence']}")
        return signal

    except anthropic.RateLimitError:
        log.warning(f"  Rate limited on {symbol} — waiting 20s")
        time.sleep(20)
        return None
    except Exception as e:
        log.error(f"  Claude API error for {symbol}: {e}")
        return None


def generate_all_signals(db, price_data: dict, news_data: dict) -> list[dict]:
    """
    Generate signals for all stocks where we have price data.
    Saves each signal to Supabase.
    Returns list of all generated signal dicts.
    """
    stocks = {s['symbol']: s for s in get_active_stocks(db)}
    generated = []
    now = datetime.now(timezone.utc).isoformat()

    for symbol, pdata in price_data.items():
        stock_info = stocks.get(symbol, {'name': symbol, 'market': 'global', 'sector': 'Unknown'})
        headlines  = news_data.get(symbol, [])

        log.info(f"  Analysing {symbol} ({len(headlines)} news items)...")
        signal = generate_signal_for_stock(symbol, stock_info, pdata, headlines)

        if not signal:
            continue

        # Build the database row
        row = {
            'symbol':          symbol,
            'signal':          signal['signal'],
            'probability':     int(signal['probability']),
            'price':           pdata.get('current_price'),
            'price_change':    pdata.get('price_change_pct'),
            'target_price':    signal.get('target_price'),
            'stop_loss':       signal.get('stop_loss'),
            'rationale':       signal.get('rationale', ''),
            'confidence':      signal.get('confidence', 'medium'),
            'rsi':             pdata.get('rsi'),
            'macd':            pdata.get('macd'),
            'volume_ratio':    pdata.get('volume_ratio'),
            'ma50':            pdata.get('ma50'),
            'ma200':           pdata.get('ma200'),
            'news_sentiment':  'positive' if any(
                                h.lower().count('surge') + h.lower().count('beat') > 0
                                for h in headlines) else 'neutral',
            'news_count':      len(headlines),
            'top_headline':    headlines[0][:300] if headlines else None,
            'bot_version':     '1.0',
        }

        insert_signal(db, row)

        # Attach metadata for alert checking
        signal['_symbol']     = symbol
        signal['_price']      = pdata.get('current_price')
        signal['_name']       = stock_info.get('name', symbol)
        generated.append(signal)

        # Polite pause between Claude calls (avoid rate limits)
        time.sleep(1.5)

    log.info(f"  Generated {len(generated)} signals")
    return generated
