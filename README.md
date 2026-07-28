# Sniper Strategy Bot

Python implementation of a first-pass sniper-style forex spread betting bot for IG.

It is designed to start safely:

- `DEMO` environment by default
- `DRY_RUN=true` by default
- explicit spread filter before entries
- one open position per market direction check
- ATR-based stop and target distances

## Why Python

IG exposes REST and streaming APIs over HTTP/JSON. Python is the most practical first language for this bot because it has strong HTTP tooling, data analysis libraries when we add backtesting, and simple deployment paths for scheduled workers.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Edit `.env` with your IG demo API key, username, password, account id if needed, and the forex EPICs you want to trade.

## Run once

```bash
set -a
source .env
set +a
sniper-bot --once
```

## Run continuously

```bash
set -a
source .env
set +a
sniper-bot
```

## Backtest CSV Data

Download 5-minute candles from IG first:

```bash
sniper-download-prices CS.D.EURUSD.MINI.IP --resolution MINUTE_5 --points 1000 --out data/eurusd_5m.csv
```

Then backtest the CSV:

```bash
sniper-backtest data/EURUSD_5m.csv \
  --spread 0.0001 \
  --trades-out backtest-results/eurusd_trades.csv \
  --summary-out backtest-results/eurusd_summary.json
```

The CSV needs `timestamp`, `open`, `high`, `low`, and `close` columns. `volume` and `spread` are optional.

The backtester uses the same indicator entry logic as the live bot:

- enter on the signal candle close after EMA 9/21 crosses
- calculate SL as ATR(14) * `STOP_ATR_MULTIPLE`
- calculate TP1-TP5 as 1R through 5R
- exit on the configured attached target via `BROKER_TARGET_INDEX`, or on SL
- if SL and TP are both touched in one candle, count SL first for conservative results

## Strategy

The first version is intentionally conservative and configurable:

- fresh signal candles are detected from EMA 9/21 crossovers
- retests are tracked when price pulls back into the EMA 9/21 ribbon after a signal
- a 7-factor bull/bear dashboard scores VWAP, RSI, MACD, EMA trend, ADX, volume candle direction, and 5m RSI
- ATR(14) * `STOP_ATR_MULTIPLE` defines the stop and five R-multiple take-profit distances
- the broker order attaches one configurable TP level via `BROKER_TARGET_INDEX`
- optional spread filtering can be enabled with `USE_SPREAD_FILTER=true`
- `DEFAULT_SIZE` is the spread-bet stake in GBP per point, defaulting to `10`
- take profits close 50% at TP1, 25% at TP2, and 25% at TP3 by default

Execution uses the indicator's scores as a safety filter: long entries require `BULL SCORE > MIN_BULL_SCORE_LONG`, and short entries require Bear Score to dominate Bull Score when `REQUIRE_SHORT_BEAR_DOMINANCE=true`.

This is a foundation, not financial advice. Validate in IG demo, add backtests, and review every EPIC's margin, minimum size, expiry, and dealing rules before risking capital.

## IG Diagnostics

Check which gateway and credentials the app is using without printing secrets:

```bash
sniper-check-ig --epic CS.D.EURUSD.MINI.IP
```

If IG returns `error.security.api-key-invalid`, revoke the exposed/old key, create a fresh key in the matching Demo or Live API Keys tab, and make sure `IG_ENV` matches that key.

## Hosting Later

The backtester can write `backtest-results/*.json` summaries. A public website should read those generated summaries, never `.env`, API keys, or raw broker tokens.

## Results API

Start the local API:

```bash
sniper-api --host 127.0.0.1 --port 8000
```

Public-safe endpoints:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/results?name=eurusd
curl http://127.0.0.1:8000/api/trades?name=eurusd
```

Refresh data and rerun a backtest:

```bash
curl -X POST http://127.0.0.1:8000/api/backtests/run \
  -H 'Content-Type: application/json' \
  -d '{"name":"eurusd","epic":"CS.D.EURUSD.MINI.IP","resolution":"MINUTE_5","points":1000}'
```

Before hosting publicly, set `API_ADMIN_TOKEN` and require `Authorization: Bearer <token>` for refresh calls.
