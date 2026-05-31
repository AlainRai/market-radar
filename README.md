# MarketRadar — AI Stock Signal Platform

## Quick Start (3 steps)

### 1. Open SETUP-WIZARD.html in your browser
Paste your API keys → it generates all config files for you.

### 2. Run the bot once manually
```
cd bots
pip install -r requirements.txt
python main_bot.py
```

### 3. Push to GitHub → auto-deploys on Vercel
```
git add .
git commit -m "deploy"
git push
```

## File Structure
```
market-radar/
├── SETUP-WIZARD.html        ← Start here
├── bots/
│   ├── main_bot.py          ← Master orchestrator
│   ├── price_bot.py         ← Fetches stock prices + technical indicators
│   ├── news_bot.py          ← Scrapes news from Reuters, Argaam, etc.
│   ├── signal_bot.py        ← Calls Claude AI to generate signals
│   ├── alert_bot.py         ← Sends email alerts
│   ├── db.py                ← All Supabase operations
│   ├── requirements.txt     ← Python dependencies
│   └── .env                 ← YOUR KEYS (created by wizard, never commit)
├── dashboard/
│   └── index.html           ← Live dashboard (deploy to Vercel)
├── database/
│   └── schema.sql           ← Run once in Supabase SQL Editor
└── .github/
    └── workflows/
        └── market-bot.yml   ← Runs bots every 30 min automatically
```

## What each bot does
- **price_bot**: Fetches live prices via yfinance. Computes RSI, MACD, MA crossovers, volume ratio, Bollinger Bands.
- **news_bot**: Scrapes RSS feeds (Reuters, Bloomberg, Argaam) + yfinance news. Matches headlines to stock symbols.
- **signal_bot**: Calls Claude API with all data → gets BUY/SELL/WATCH + probability % + rationale.
- **alert_bot**: If probability ≥ 75%, sends formatted HTML email to your inbox.
