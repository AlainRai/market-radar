"""
MarketRadar — News Bot
=======================
Fetches news from multiple sources relevant to Saudi + global markets:
  - RSS feeds: Argaam, Reuters, Bloomberg, Google Finance
  - NewsAPI (if key provided)
  - Yahoo Finance news (via yfinance)

For each article, does quick sentiment pre-scoring
(Claude does the deep analysis in signal_bot).
"""

import os
import logging
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import requests
import feedparser
import yfinance as yf

from db import insert_news_batch

log = logging.getLogger(__name__)

# ── RSS Feed sources ──────────────────────────────────────────────────────────
RSS_FEEDS = [
    # Saudi market news
    {'url': 'https://www.argaam.com/en/rss/rss_feed_articles', 'source': 'Argaam'},
    {'url': 'https://feeds.reuters.com/reuters/businessNews', 'source': 'Reuters'},
    {'url': 'https://feeds.bloomberg.com/markets/news.rss', 'source': 'Bloomberg'},

    # Oil & energy (critical for Saudi stocks)
    {'url': 'https://feeds.reuters.com/reuters/energy', 'source': 'Reuters Energy'},

    # Global tech (for NVDA, MSFT, etc.)
    {'url': 'https://feeds.reuters.com/reuters/technologyNews', 'source': 'Reuters Tech'},
]

# Keywords that suggest a news item is about a specific Saudi stock
SAUDI_KEYWORD_MAP = {
    '2222.SR': ['aramco', 'saudi aramco', 'أرامكو'],
    '1120.SR': ['al rajhi', 'rajhi bank', 'الراجحي'],
    '2010.SR': ['sabic', 'سابك', 'petrochemical'],
    '1150.SR': ['alinma', 'الإنماء'],
    '7010.SR': ['stc', 'saudi telecom', 'الاتصالات السعودية'],
    '4030.SR': ['mouwasat', 'موارد'],
    '1050.SR': ['snb', 'saudi national bank', 'البنك الأهلي'],
}

GLOBAL_KEYWORD_MAP = {
    'NVDA':  ['nvidia', 'nvda', 'gpu', 'ai chip', 'h100', 'blackwell'],
    'MSFT':  ['microsoft', 'azure', 'msft', 'copilot', 'openai'],
    'TSLA':  ['tesla', 'tsla', 'elon musk', 'ev delivery'],
    'XOM':   ['exxon', 'xom', 'exxonmobil'],
    'BABA':  ['alibaba', 'baba', 'jack ma'],
    'AAPL':  ['apple', 'iphone', 'aapl', 'tim cook'],
    'META':  ['meta', 'facebook', 'instagram', 'zuckerberg'],
    'AMZN':  ['amazon', 'aws', 'amzn', 'bezos'],
}

ALL_KEYWORD_MAP = {**SAUDI_KEYWORD_MAP, **GLOBAL_KEYWORD_MAP}


def simple_sentiment(text: str) -> tuple[str, float]:
    """
    Fast keyword-based sentiment pre-scoring.
    Claude will do the real analysis — this is just a quick filter.
    Returns: ('positive'|'negative'|'neutral', score -1.0 to 1.0)
    """
    text = text.lower()
    positive_words = ['surge', 'rally', 'beat', 'record', 'growth', 'profit',
                      'upgrade', 'buy', 'strong', 'gain', 'rise', 'up', 'high',
                      'exceed', 'outperform', 'bullish', 'positive', 'success',
                      'deal', 'contract', 'win', 'expand', 'increase']
    negative_words = ['fall', 'drop', 'miss', 'loss', 'decline', 'down', 'cut',
                      'downgrade', 'sell', 'weak', 'concern', 'risk', 'warn',
                      'crisis', 'debt', 'bearish', 'negative', 'fail', 'layoff',
                      'lawsuit', 'fine', 'sanction', 'decrease', 'reduce']

    pos_count = sum(1 for w in positive_words if w in text)
    neg_count = sum(1 for w in negative_words if w in text)
    total = pos_count + neg_count

    if total == 0:
        return 'neutral', 0.0
    score = (pos_count - neg_count) / total
    if score > 0.1:
        return 'positive', round(score, 3)
    elif score < -0.1:
        return 'negative', round(score, 3)
    return 'neutral', round(score, 3)


def match_symbols(text: str) -> list[str]:
    """Find which stock symbols are mentioned in a news headline/description."""
    text = text.lower()
    matched = []
    for symbol, keywords in ALL_KEYWORD_MAP.items():
        if any(kw in text for kw in keywords):
            matched.append(symbol)
    return matched


def fetch_rss_news() -> list[dict]:
    """Fetch and parse all RSS feeds."""
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    for feed_info in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info['url'])
            for entry in feed.entries[:20]:  # Max 20 per feed
                title = getattr(entry, 'title', '')
                summary = getattr(entry, 'summary', '')
                url = getattr(entry, 'link', '')
                published_raw = getattr(entry, 'published', None)

                if not title or not url:
                    continue

                full_text = f"{title} {summary}"
                sentiment, score = simple_sentiment(full_text)
                symbols = match_symbols(full_text)

                # Try to parse publish date
                published_at = None
                if published_raw:
                    try:
                        import email.utils
                        parsed = email.utils.parsedate_to_datetime(published_raw)
                        published_at = parsed.isoformat()
                    except Exception:
                        published_at = datetime.now(timezone.utc).isoformat()

                # Store one row per matched symbol, plus one general row if no match
                targets = symbols if symbols else [None]
                for symbol in targets:
                    articles.append({
                        'symbol': symbol,
                        'headline': title[:500],
                        'source': feed_info['source'],
                        'url': url,
                        'sentiment': sentiment,
                        'sentiment_score': score,
                        'published_at': published_at,
                    })
        except Exception as e:
            log.warning(f"  RSS fetch failed for {feed_info['source']}: {e}")

    return articles


def fetch_yfinance_news(symbols: list[str]) -> list[dict]:
    """Fetch news for each symbol via yfinance."""
    articles = []
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            news_items = ticker.news or []
            for item in news_items[:5]:  # Top 5 per stock
                title = item.get('title', '')
                url = item.get('link', '')
                if not title:
                    continue
                sentiment, score = simple_sentiment(title)
                articles.append({
                    'symbol': symbol,
                    'headline': title[:500],
                    'source': item.get('publisher', 'Yahoo Finance'),
                    'url': url,
                    'sentiment': sentiment,
                    'sentiment_score': score,
                    'published_at': datetime.fromtimestamp(
                        item.get('providerPublishTime', 0), tz=timezone.utc
                    ).isoformat() if item.get('providerPublishTime') else None,
                })
            time.sleep(0.3)
        except Exception as e:
            log.warning(f"  yfinance news failed for {symbol}: {e}")
    return articles


def fetch_newsapi(symbols: list[str], market: str = 'both') -> list[dict]:
    """Fetch from NewsAPI if key is configured."""
    api_key = os.getenv('NEWS_API_KEY')
    if not api_key:
        return []

    articles = []
    queries = ['Saudi stock market', 'Tadawul', 'TASI index', 'Saudi Aramco']

    for q in queries:
        try:
            url = 'https://newsapi.org/v2/everything?' + urlencode({
                'q': q,
                'language': 'en',
                'sortBy': 'publishedAt',
                'pageSize': 10,
                'apiKey': api_key,
            })
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                for item in res.json().get('articles', []):
                    title = item.get('title', '')
                    if not title or title == '[Removed]':
                        continue
                    full_text = f"{title} {item.get('description', '')}"
                    sentiment, score = simple_sentiment(full_text)
                    matched = match_symbols(full_text)
                    for symbol in (matched or [None]):
                        articles.append({
                            'symbol': symbol,
                            'headline': title[:500],
                            'source': item.get('source', {}).get('name', 'NewsAPI'),
                            'url': item.get('url', ''),
                            'sentiment': sentiment,
                            'sentiment_score': score,
                            'published_at': item.get('publishedAt'),
                        })
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"  NewsAPI query failed: {e}")

    return articles


def fetch_all_news(db) -> dict:
    """
    Fetch news from all sources.
    Returns dict: { symbol: [list of headline strings] }
    Also saves all articles to Supabase news table.
    """
    log.info("  Fetching news from RSS feeds...")
    all_articles = []

    rss_articles = fetch_rss_news()
    all_articles.extend(rss_articles)
    log.info(f"  RSS: {len(rss_articles)} articles")

    # yfinance news for global stocks
    global_symbols = ['NVDA', 'MSFT', 'TSLA', 'XOM', 'BABA', 'AAPL', 'META', 'AMZN']
    yf_articles = fetch_yfinance_news(global_symbols)
    all_articles.extend(yf_articles)
    log.info(f"  yfinance news: {len(yf_articles)} articles")

    # NewsAPI (if key configured)
    newsapi_articles = fetch_newsapi(global_symbols)
    all_articles.extend(newsapi_articles)
    if newsapi_articles:
        log.info(f"  NewsAPI: {len(newsapi_articles)} articles")

    # Remove duplicates by URL
    seen_urls = set()
    unique_articles = []
    for a in all_articles:
        url = a.get('url', '')
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_articles.append(a)

    # Save to Supabase
    if unique_articles:
        insert_news_batch(db, unique_articles)

    # Build per-symbol headline lists for the signal bot
    news_by_symbol: dict[str, list[str]] = {}
    for article in unique_articles:
        symbol = article.get('symbol')
        if symbol:
            if symbol not in news_by_symbol:
                news_by_symbol[symbol] = []
            news_by_symbol[symbol].append(article['headline'])

    log.info(f"  Total unique articles: {len(unique_articles)}")
    return news_by_symbol
