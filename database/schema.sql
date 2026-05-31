-- ============================================================
-- MarketRadar — Supabase Database Schema
-- Run this in: Supabase Dashboard > SQL Editor > New Query
-- ============================================================

-- 1. STOCKS — master list of tracked stocks
CREATE TABLE IF NOT EXISTS stocks (
  id            SERIAL PRIMARY KEY,
  symbol        TEXT NOT NULL UNIQUE,        -- e.g. '2222.SR' or 'NVDA'
  name          TEXT NOT NULL,               -- e.g. 'Saudi Aramco'
  name_ar       TEXT,                        -- Arabic name
  market        TEXT NOT NULL,               -- 'saudi' or 'global'
  sector        TEXT,
  is_active     BOOLEAN DEFAULT true,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 2. SIGNALS — AI-generated signals from each bot run
CREATE TABLE IF NOT EXISTS signals (
  id            SERIAL PRIMARY KEY,
  symbol        TEXT NOT NULL REFERENCES stocks(symbol),
  signal        TEXT NOT NULL CHECK (signal IN ('buy','sell','watch')),
  probability   INTEGER NOT NULL CHECK (probability BETWEEN 0 AND 100),
  price         NUMERIC(12,4),
  price_change  NUMERIC(8,4),               -- % change today
  target_price  NUMERIC(12,4),
  stop_loss     NUMERIC(12,4),
  rationale     TEXT,                        -- Claude's explanation
  confidence    TEXT CHECK (confidence IN ('high','medium','low')),
  -- Technical indicators snapshot
  rsi           NUMERIC(6,2),
  macd          NUMERIC(10,4),
  volume_ratio  NUMERIC(8,4),               -- vs 20-day avg
  ma50          NUMERIC(12,4),
  ma200         NUMERIC(12,4),
  -- News context
  news_sentiment TEXT CHECK (news_sentiment IN ('positive','negative','neutral')),
  news_count    INTEGER DEFAULT 0,
  top_headline  TEXT,
  -- Metadata
  bot_version   TEXT DEFAULT '1.0',
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 3. PRICE_HISTORY — daily OHLCV data
CREATE TABLE IF NOT EXISTS price_history (
  id            SERIAL PRIMARY KEY,
  symbol        TEXT NOT NULL REFERENCES stocks(symbol),
  date          DATE NOT NULL,
  open          NUMERIC(12,4),
  high          NUMERIC(12,4),
  low           NUMERIC(12,4),
  close         NUMERIC(12,4),
  volume        BIGINT,
  UNIQUE(symbol, date)
);

-- 4. NEWS — scraped news articles
CREATE TABLE IF NOT EXISTS news (
  id            SERIAL PRIMARY KEY,
  symbol        TEXT,                        -- NULL = market-wide news
  headline      TEXT NOT NULL,
  source        TEXT,
  url           TEXT,
  sentiment     TEXT CHECK (sentiment IN ('positive','negative','neutral')),
  sentiment_score NUMERIC(4,3),             -- -1.0 to 1.0
  published_at  TIMESTAMPTZ,
  fetched_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 5. BOT_RUNS — log every bot execution
CREATE TABLE IF NOT EXISTS bot_runs (
  id            SERIAL PRIMARY KEY,
  run_type      TEXT NOT NULL,              -- 'price_fetch', 'signal_gen', 'news_fetch'
  status        TEXT NOT NULL,             -- 'success', 'error', 'partial'
  stocks_processed INTEGER DEFAULT 0,
  duration_ms   INTEGER,
  error_message TEXT,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 6. ALERTS — triggered alerts log
CREATE TABLE IF NOT EXISTS alerts (
  id            SERIAL PRIMARY KEY,
  symbol        TEXT NOT NULL,
  alert_type    TEXT NOT NULL,             -- 'high_probability', 'price_target', 'volume_spike'
  message       TEXT NOT NULL,
  probability   INTEGER,
  is_sent       BOOLEAN DEFAULT false,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- INDEXES for fast dashboard queries
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_signals_symbol     ON signals(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_created    ON signals(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_signal     ON signals(signal);
CREATE INDEX IF NOT EXISTS idx_price_history_sym  ON price_history(symbol, date DESC);
CREATE INDEX IF NOT EXISTS idx_news_symbol        ON news(symbol);
CREATE INDEX IF NOT EXISTS idx_news_published     ON news(published_at DESC);

-- ============================================================
-- SEED DATA — Saudi + Global stocks to track
-- ============================================================
INSERT INTO stocks (symbol, name, name_ar, market, sector) VALUES
  ('2222.SR', 'Saudi Aramco',       'أرامكو السعودية',     'saudi', 'Energy'),
  ('1120.SR', 'Al Rajhi Bank',      'مصرف الراجحي',        'saudi', 'Banking'),
  ('2010.SR', 'SABIC',              'سابك',                 'saudi', 'Petrochemicals'),
  ('1150.SR', 'Alinma Bank',        'مصرف الإنماء',        'saudi', 'Banking'),
  ('7010.SR', 'STC',                'الاتصالات السعودية',  'saudi', 'Telecom'),
  ('4030.SR', 'Mouwasat Medical',   'موارد',                'saudi', 'Healthcare'),
  ('2380.SR', 'Petro Rabigh',       'بترو رابغ',            'saudi', 'Energy'),
  ('4200.SR', 'Aldawaa Medical',    'الدواء الطبية',        'saudi', 'Healthcare'),
  ('1050.SR', 'Saudi National Bank','البنك الأهلي',         'saudi', 'Banking'),
  ('4160.SR', 'Seera Group',        'سيرة',                 'saudi', 'Tourism'),
  ('NVDA',    'NVIDIA',             NULL,                   'global', 'Technology'),
  ('MSFT',    'Microsoft',          NULL,                   'global', 'Technology'),
  ('TSLA',    'Tesla',              NULL,                   'global', 'EV/Auto'),
  ('XOM',     'ExxonMobil',         NULL,                   'global', 'Energy'),
  ('BABA',    'Alibaba',            NULL,                   'global', 'Technology'),
  ('AAPL',    'Apple',              NULL,                   'global', 'Technology'),
  ('META',    'Meta Platforms',     NULL,                   'global', 'Technology'),
  ('AMZN',    'Amazon',             NULL,                   'global', 'Technology')
ON CONFLICT (symbol) DO NOTHING;

-- ============================================================
-- ROW LEVEL SECURITY (enable for production)
-- ============================================================
-- ALTER TABLE signals ENABLE ROW LEVEL SECURITY;
-- For now, allow all reads (your personal use)
-- When you add users, restrict per user_id

-- ============================================================
-- USEFUL VIEWS
-- ============================================================

-- Latest signal per stock (most recent run)
CREATE OR REPLACE VIEW latest_signals AS
SELECT DISTINCT ON (symbol)
  s.*,
  st.name,
  st.name_ar,
  st.market,
  st.sector
FROM signals s
JOIN stocks st ON st.symbol = s.symbol
ORDER BY symbol, created_at DESC;

-- Today's high-probability signals (> 70%)
CREATE OR REPLACE VIEW high_probability_signals AS
SELECT * FROM latest_signals
WHERE probability >= 70
  AND created_at > NOW() - INTERVAL '4 hours'
ORDER BY probability DESC;

SELECT 'Schema created successfully. Tables: stocks, signals, price_history, news, bot_runs, alerts' AS result;
