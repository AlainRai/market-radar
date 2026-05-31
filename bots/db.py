"""
MarketRadar — Database Helper
==============================
All Supabase read/write operations in one place.
"""

import os
import logging
from datetime import datetime, timezone
from supabase import create_client, Client

log = logging.getLogger(__name__)

_db_client = None

def get_db() -> Client:
    """Get (or create) the Supabase client."""
    global _db_client
    if _db_client is None:
        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_KEY')
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
        _db_client = create_client(url, key)
        log.info("Supabase client initialized")
    return _db_client


def get_active_stocks(db: Client) -> list[dict]:
    """Return all active stocks from the stocks table."""
    res = db.table('stocks').select('*').eq('is_active', True).execute()
    return res.data or []


def upsert_price_history(db: Client, symbol: str, ohlcv_rows: list[dict]):
    """Save daily OHLCV rows. Ignores duplicates (upsert on symbol+date)."""
    if not ohlcv_rows:
        return
    db.table('price_history').upsert(ohlcv_rows, on_conflict='symbol,date').execute()


def insert_signal(db: Client, signal_row: dict):
    """Insert one signal row."""
    db.table('signals').insert(signal_row).execute()


def insert_news_batch(db: Client, news_rows: list[dict]):
    """Insert news articles. Skips on conflict (url)."""
    if not news_rows:
        return
    db.schema('public').table('bot_runs').insert({...}).execute()


def get_recent_signals(db: Client, limit: int = 50) -> list[dict]:
    """Fetch most recent signals (for dashboard API)."""
    res = (db.table('signals')
             .select('*, stocks(name, name_ar, market, sector)')
             .order('created_at', desc=True)
             .limit(limit)
             .execute())
    return res.data or []


def get_latest_signal_per_stock(db: Client) -> list[dict]:
    """Get the most recent signal for each stock."""
    res = db.table('latest_signals').select('*').execute()
    return res.data or []


def log_bot_run(db: Client, run_type: str, status: str,
                stocks_processed: int = 0, duration_ms: int = 0,
                error_message: str = None):
    """Log one bot run to bot_runs table."""
    return db.schema('public').table('bot_runs').insert({
        'run_type': run_type,
        'status': status,
        'stocks_processed': stocks_processed,
        'duration_ms': duration_ms,
        'error_message': error_message
    }).execute()


def create_alert(db: Client, symbol: str, alert_type: str,
                 message: str, probability: int = None):
    """Record an alert in the alerts table."""
    db.table('alerts').insert({
        'symbol': symbol,
        'alert_type': alert_type,
        'message': message,
        'probability': probability
    }).execute()


def mark_alert_sent(db: Client, alert_id: int):
    db.table('alerts').update({'is_sent': True}).eq('id', alert_id).execute()
