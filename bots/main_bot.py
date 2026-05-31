"""
MarketRadar — Main Bot Orchestrator
====================================
Runs all bots in sequence:
  1. Fetch prices + technical indicators
  2. Fetch news headlines
  3. Call Claude API to generate signals
  4. Save everything to Supabase
  5. Trigger alerts if high-probability signals found

Run manually:  python main_bot.py
Scheduled:     GitHub Actions runs this every 30 min
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

from price_bot import fetch_all_prices
from news_bot import fetch_all_news
from signal_bot import generate_all_signals
from alert_bot import check_and_send_alerts
from db import get_db, log_bot_run

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)


def run_full_cycle():
    """One complete cycle: prices → news → signals → alerts."""
    start = time.time()
    log.info("=" * 50)
    log.info("MarketRadar bot cycle starting...")
    log.info(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    log.info("=" * 50)

    db = get_db()
    total_processed = 0
    errors = []

    # ── Step 1: Fetch prices ──────────────────────────────
    log.info("Step 1/4: Fetching stock prices...")
    try:
        price_data = fetch_all_prices(db)
        log.info(f"  ✓ Prices fetched for {len(price_data)} stocks")
    except Exception as e:
        log.error(f"  ✗ Price fetch failed: {e}")
        errors.append(f"price_fetch: {e}")
        price_data = {}

    # ── Step 2: Fetch news ────────────────────────────────
    log.info("Step 2/4: Fetching news headlines...")
    try:
        news_data = fetch_all_news(db)
        log.info(f"  ✓ News fetched: {sum(len(v) for v in news_data.values())} articles")
    except Exception as e:
        log.error(f"  ✗ News fetch failed: {e}")
        errors.append(f"news_fetch: {e}")
        news_data = {}

    # ── Step 3: Generate signals ──────────────────────────
    log.info("Step 3/4: Generating AI signals via Claude...")
    try:
        signals = generate_all_signals(db, price_data, news_data)
        total_processed = len(signals)
        log.info(f"  ✓ Signals generated for {total_processed} stocks")
        buy_count  = sum(1 for s in signals if s.get('signal') == 'buy')
        sell_count = sum(1 for s in signals if s.get('signal') == 'sell')
        watch_count = sum(1 for s in signals if s.get('signal') == 'watch')
        log.info(f"  → BUY: {buy_count}  SELL: {sell_count}  WATCH: {watch_count}")
    except Exception as e:
        log.error(f"  ✗ Signal generation failed: {e}")
        errors.append(f"signal_gen: {e}")
        signals = []

    # ── Step 4: Alerts ────────────────────────────────────
    log.info("Step 4/4: Checking alert conditions...")
    try:
        alerts_sent = check_and_send_alerts(db, signals)
        if alerts_sent:
            log.info(f"  ✓ Sent {len(alerts_sent)} alerts")
        else:
            log.info("  → No high-probability alerts triggered")
    except Exception as e:
        log.error(f"  ✗ Alert check failed: {e}")
        errors.append(f"alerts: {e}")

    # ── Log this run ──────────────────────────────────────
    duration_ms = int((time.time() - start) * 1000)
    status = 'error' if len(errors) == 4 else ('partial' if errors else 'success')
    log_bot_run(db, 'full_cycle', status, total_processed, duration_ms,
                '; '.join(errors) if errors else None)

    log.info("=" * 50)
    log.info(f"Cycle complete in {duration_ms/1000:.1f}s — status: {status.upper()}")
    if errors:
        log.warning(f"Errors: {errors}")
    log.info("=" * 50)

    return signals


if __name__ == '__main__':
    run_full_cycle()
