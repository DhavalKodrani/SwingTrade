# High-Probability Swing Trade Scanner

The **third** system in the stock-screening family, alongside
[Stock_squeeze_screener](https://github.com/DhavalKodrani/Stock_squeeze_screener)
(daily + intraday squeeze) and
[supertrend-dashboard](https://github.com/DhavalKodrani/supertrend-dashboard)
(weekly Supertrend + 10 EMA). It scans the **same US-listed universe** but with a
different job: find **long-only swing setups**, run **exactly 4 times a day**
inside a **09:00–21:00** window, and report a fixed-risk trade plan for each.

> ⚠️ **Educational technical screen — not financial advice.** No indicator screen
> guarantees a win rate. See *"Honest probability"* below.

---

## What it does

- **4 runs/day** at strategic market inflection points (config `run_times`):
  `09:15` (pre-market), `11:00` (post-open), `15:30` (power hour), `19:00` (after-hours) — US/Eastern.
- **All market states** in-window: `PRE` / `LIVE` / `POST`, via extended-hours
  (`prepost`) intraday data. State is shown per candidate.
- **Long-only swing gate** on daily bars — six conditions, all required:
  1. Uptrend — EMA20 > EMA50
  2. Structure — price above EMA20
  3. Momentum — MACD > signal & histogram > 0
  4. RSI band — 50–72 (momentum, not overbought)
  5. Volume breakout — volume > 1.5× 20-day average
  6. Breakout — within 2% of the prior 20-day high
- **Fixed risk model** — R:R **1 : 2.5**: TP **+5%**, SL **−2%**, base allocation **500 units/trade**.
- **Three output views** — CLI table, `docs/data/results.json`, and a self-contained
  HTML dashboard (`swing_report.html`) with client-side filter/sort, published to GitHub Pages.

## Honest probability

Two separate numbers, deliberately:

| Column | Meaning |
|---|---|
| **Score (0–100)** | Heuristic signal-strength composite. **Ranking only.** |
| **Win% (n)** | **Empirical** rate at which the *identical* setup historically reached +5% before −2% within 15 trading days, over *n* past occurrences on that ticker. `n/a` = too few samples. |

The `75–80%` target in the spec is treated as a **filter aspiration** (it tunes the
score threshold), **not** a promise. The number you actually see is the backtested
hit-rate from each ticker's own history, biased conservatively (a bar that spans
both TP and SL counts as a loss).

## Architecture

```
swingscan/
  config.py        load config.yaml -> dotted namespace
  universe.py      NASDAQ Trader universe (same source as sister repos) + fallback   [data]
  data.py          batched yfinance daily + extended-hours intraday, retry/backoff   [data]
  indicators.py    EMA/SMA/RSI/MACD/ATR/volume - pure math, no TA lib                 [signal]
  market_state.py  PRE/LIVE/POST/CLOSED + active-window guard                         [signal]
  signals.py       TradeSetup dataclass, 6-gate setup, 0-100 score, trade math        [signal]
  backtest.py      empirical TP-before-SL win-rate over history                       [signal]
  scanner.py       orchestration: universe -> gate -> live price -> setup -> rank
  render.py        CLI / JSON / HTML dashboard                                        [render]
run_scan.py        one scan (one of the 4 daily runs)
scheduler.py       internal 4x/day loop scheduler (alt. to GitHub cron)
.github/workflows/swing_scan.yml   4x/day CI + Pages + issue alerts
```

The cheap batched **daily gate runs first**; the rate-limited **intraday call and
backtest run only for tickers that already passed**, so a full-universe scan makes
a few dozen intraday requests, not thousands.

## Usage

```bash
pip install -r requirements.txt

# one scan (respects the 09:00-21:00 window)
python run_scan.py

# smoke test: small custom list, ignore the window guard
python run_scan.py --tickers AAPL,NVDA,AMD,TSLA --force

# cap the universe while testing
python run_scan.py --limit 200 --force

# run as a long-lived 4x/day process
python scheduler.py                 # loop forever
python scheduler.py --dry-run        # print today's computed schedule
python scheduler.py --once-now       # single immediate run
```

All behaviour is tunable in [`config.yaml`](config.yaml) — window, run times,
risk %, indicator thresholds, backtest horizon, liquidity floor.

## Deployment (GitHub Actions)

`.github/workflows/swing_scan.yml` runs the 4 daily crons, publishes the dashboard
to GitHub Pages, commits `docs/data/results.json`, and opens a GitHub issue on
candidates (phone notification). Optional email via repo secrets
`EMAIL_SENDER`/`EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `EMAIL_RECIPIENT`,
`SMTP_SERVER`, `SMTP_PORT`.

> Cron is UTC and does not follow DST; the four UTC times match EDT, and the
> script re-checks the window/market state at runtime, so EST simply shifts the
> runs one ET hour earlier — still inside the window.
