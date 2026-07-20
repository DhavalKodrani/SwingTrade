"""
Data layer - yfinance fetching with the same reliability pattern as the sister
projects: batched downloads, retry with linear backoff, graceful handling of
empty payloads (common during thin extended-hours sessions).

Two products:
  fetch_daily_batch()   -> {ticker: daily OHLCV DataFrame}  (swing indicators)
  fetch_live_price()    -> float | None  (last trade incl. pre/post-market)

The daily gate runs first and cheap; the intraday call is made ONLY for the
handful of tickers that already passed, which keeps us well under rate limits
even when scanning thousands of names.
"""

from __future__ import annotations

import time

import pandas as pd
import yfinance as yf


def _download(tickers, **kwargs):
    """Thin wrapper so all yfinance calls share one signature/log point."""
    return yf.download(
        tickers,
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
        **kwargs,
    )


def fetch_daily_batch(
    batch: list[str],
    period: str,
    max_retries: int = 3,
    backoff: float = 5.0,
) -> dict[str, pd.DataFrame]:
    """Download daily bars for a batch, retrying on transient failures.
    Returns {ticker: cleaned DataFrame}; tickers with no data are omitted."""
    data = None
    for attempt in range(1, max_retries + 1):
        try:
            data = _download(batch, period=period, interval="1d")
            break
        except Exception as exc:  # noqa: BLE001
            wait = backoff * attempt
            print(f"  daily batch attempt {attempt}/{max_retries} failed: {exc} "
                  f"(retry in {wait:.0f}s)")
            time.sleep(wait)
    if data is None or data.empty:
        return {}

    out: dict[str, pd.DataFrame] = {}
    multi = len(batch) > 1
    for tkr in batch:
        try:
            df = data[tkr].dropna() if multi else data.dropna()
            if not df.empty:
                out[tkr] = df
        except Exception:  # noqa: BLE001 - a single bad symbol never kills the batch
            continue
    return out


def fetch_live_price(
    ticker: str,
    interval: str,
    period: str,
    prepost: bool = True,
    max_retries: int = 3,
    backoff: float = 5.0,
) -> float | None:
    """
    Last available traded price INCLUDING pre/post-market bars. Returns None if
    extended-hours data is empty so the caller can fall back to the daily close.
    """
    for attempt in range(1, max_retries + 1):
        try:
            df = _download(ticker, period=period, interval=interval, prepost=prepost)
            if df is None or df.empty:
                return None
            close = df["Close"].dropna()
            if close.empty:
                return None
            return float(close.iloc[-1])
        except Exception as exc:  # noqa: BLE001
            wait = backoff * attempt
            print(f"  live price {ticker} attempt {attempt}/{max_retries} failed: "
                  f"{exc} (retry in {wait:.0f}s)")
            time.sleep(wait)
    return None


def batched(seq: list[str], size: int):
    """Yield successive `size`-length chunks of `seq`."""
    for i in range(0, len(seq), size):
        yield seq[i:i + size]
