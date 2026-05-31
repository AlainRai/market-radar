from __future__ import annotations
"""
MarketRadar — Price Bot
========================
Fetches current prices and computes technical indicators
for all active stocks using yfinance (free, no API key needed).

Technical indicators computed:
  - RSI (14-day)
  - MACD + signal line
  - 50-day and 200-day moving averages
  - Volume ratio (today vs 20-day average)
  - Bollinger Bands position
  - Daily % change
"""

import logging
from datetime import datetime, date, timezone

import yfinance as yf
import pandas as pd
import numpy as np

try:
    import ta
    HAS_TA = True
except ImportError:
    HAS_TA = False

from db import get_active_stocks, upsert_price_history

log = logging.getLogger(__name__)

# How many days of history to fetch (for indicator calculation)
HISTORY_DAYS = '6mo'


def compute_rsi(close: pd.Series, period: int = 14) -> float:
    """Relative Strength Index."""
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 2) if not np.isnan(val) else None


def compute_macd(close: pd.Series) -> dict:
    """MACD (12,26,9)."""
    if len(close) < 35:
        return {'macd': None, 'signal': None, 'histogram': None}
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return {
        'macd': round(float(macd.iloc[-1]), 4),
        'signal': round(float(signal.iloc[-1]), 4),
        'histogram': round(float(hist.iloc[-1]), 4)
    }


def compute_moving_averages(close: pd.Series) -> dict:
    """50-day and 200-day simple moving averages."""
    result = {'ma50': None, 'ma200': None, 'golden_cross': False, 'death_cross': False}
    if len(close) >= 50:
        ma50 = close.rolling(50).mean()
        result['ma50'] = round(float(ma50.iloc[-1]), 4)
    if len(close) >= 200:
        ma200 = close.rolling(200).mean()
        result['ma200'] = round(float(ma200.iloc[-1]), 4)
    if result['ma50'] and result['ma200']:
        prev_ma50 = close.rolling(50).mean().iloc[-2]
        prev_ma200 = close.rolling(200).mean().iloc[-2]
        result['golden_cross'] = (prev_ma50 < prev_ma200 and
                                   result['ma50'] > result['ma200'])
        result['death_cross']  = (prev_ma50 > prev_ma200 and
                                   result['ma50'] < result['ma200'])
    return result


def compute_volume_ratio(volume: pd.Series) -> float:
    """Today's volume vs 20-day average."""
    if len(volume) < 21:
        return None
    avg = volume.rolling(20).mean().iloc[-2]
    today = volume.iloc[-1]
    if avg and avg > 0:
        return round(float(today / avg), 3)
    return None

from typing import Optional

def fetch_stock_data(symbol: str) -> Optional[dict]:
    """
    Fetch full price history + compute all technical indicators for one stock.
    Returns a dict ready to pass to the signal bot.
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=HISTORY_DAYS)

        if hist.empty or len(hist) < 5:
            log.warning(f"  No data returned for {symbol}")
            return None

        close  = hist['Close']
        volume = hist['Volume']
        current_price = float(close.iloc[-1])
        prev_price    = float(close.iloc[-2]) if len(close) > 1 else current_price
        price_change  = round(((current_price - prev_price) / prev_price) * 100, 4)

        rsi  = compute_rsi(close)
        macd = compute_macd(close)
        mas  = compute_moving_averages(close)
        vol_ratio = compute_volume_ratio(volume)

        # 52-week high/low
        high_52w = round(float(close.tail(252).max()), 4)
        low_52w  = round(float(close.tail(252).min()), 4)

        # Bollinger Band position (where is price between lower and upper band?)
        bb_period = 20
        if len(close) >= bb_period:
            rolling_mean = close.rolling(bb_period).mean()
            rolling_std  = close.rolling(bb_period).std()
            bb_upper = rolling_mean + (2 * rolling_std)
            bb_lower = rolling_mean - (2 * rolling_std)
            bb_range = float(bb_upper.iloc[-1] - bb_lower.iloc[-1])
            if bb_range > 0:
                bb_position = round((current_price - float(bb_lower.iloc[-1])) / bb_range, 3)
            else:
                bb_position = 0.5
        else:
            bb_position = None

        # Recent price trend (5-day slope, normalised)
        if len(close) >= 5:
            recent_5 = close.tail(5).values
            x = np.arange(5)
            slope = np.polyfit(x, recent_5, 1)[0]
            trend_5d = round(float(slope / current_price * 100), 4)
        else:
            trend_5d = None

        # Build OHLCV rows for storage
        ohlcv_rows = []
        for idx, row in hist.tail(30).iterrows():
            ohlcv_rows.append({
                'symbol': symbol,
                'date': idx.date().isoformat(),
                'open': round(float(row['Open']), 4),
                'high': round(float(row['High']), 4),
                'low':  round(float(row['Low']),  4),
                'close': round(float(row['Close']), 4),
                'volume': int(row['Volume'])
            })

        return {
            'symbol': symbol,
            'current_price': current_price,
            'price_change_pct': price_change,
            'high_52w': high_52w,
            'low_52w': low_52w,
            'rsi': rsi,
            'macd': macd['macd'],
            'macd_signal': macd['signal'],
            'macd_histogram': macd['histogram'],
            'ma50': mas['ma50'],
            'ma200': mas['ma200'],
            'golden_cross': mas['golden_cross'],
            'death_cross': mas['death_cross'],
            'volume_ratio': vol_ratio,
            'bb_position': bb_position,     # 0=at lower band, 1=at upper band
            'trend_5d': trend_5d,
            'ohlcv_rows': ohlcv_rows,
        }

    except Exception as e:
        log.error(f"  Error fetching {symbol}: {e}")
        return None


def fetch_all_prices(db) -> dict:
    """
    Fetch price data for all active stocks.
    Returns dict: { symbol: price_data_dict }
    Saves OHLCV history to Supabase.
    """
    stocks = get_active_stocks(db)
    price_data = {}

    log.info(f"  Fetching prices for {len(stocks)} stocks...")

    for stock in stocks:
        symbol = stock['symbol']
        log.info(f"  → {symbol}...")
        data = fetch_stock_data(symbol)

        if data:
            price_data[symbol] = data
            # Save price history
            upsert_price_history(db, symbol, data.pop('ohlcv_rows', []))
            log.info(f"    Price: {data['current_price']:.2f}  "
                     f"RSI: {data['rsi']}  "
                     f"Change: {data['price_change_pct']:+.2f}%")

        # Rate limit: yfinance doesn't need it but be polite
        import time; time.sleep(0.5)

    log.info(f"  Price fetch complete: {len(price_data)}/{len(stocks)} succeeded")
    return price_data
