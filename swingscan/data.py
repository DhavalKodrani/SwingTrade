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


def _last_close(df) -> float | None:
    """Robustly pull the last non-null Close from a single-ticker download,
    tolerant of single-level OR MultiIndex columns and throttled/odd payloads."""
    if df is None or getattr(df, "empty", True):
        return None
    try:
        cols = df.columns
        if isinstance(cols, pd.MultiIndex):
            if "Close" in cols.get_level_values(-1):
                s = df.xs("Close", axis=1, level=-1)
            elif "Close" in cols.get_level_values(0):
                s = df.xs("Close", axis=1, level=0)
            else:
                return None
            if getattr(s, "ndim", 1) > 1:
                s = s.iloc[:, 0]
        else:
            if "Close" not in cols:
                return None
            s = df["Close"]
        s = s.dropna()
        return float(s.iloc[-1]) if not s.empty else None
    except Exception:  # noqa: BLE001 - never let a shape surprise crash a scan
        return None


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
    Last available traded price INCLUDING pre/post-market bars. During thin
    extended-hours sessions the intraday payload can be empty, so we fall back to
    the most recent DAILY close (a real, recent price) rather than returning None.
    Returns None only if both intraday and daily are unavailable.
    """
    # 1) intraday incl. pre/post
    for attempt in range(1, max_retries + 1):
        try:
            df = _download(ticker, period=period, interval=interval, prepost=prepost)
            price = _last_close(df)
            if price is not None:
                return price
            break  # empty/odd payload (not an error) -> use daily fallback
        except Exception as exc:  # noqa: BLE001
            wait = backoff * attempt
            print(f"  live price {ticker} attempt {attempt}/{max_retries} failed: "
                  f"{exc} (retry in {wait:.0f}s)")
            time.sleep(wait)

    # 2) daily-close fallback for thin/empty extended-hours sessions
    try:
        return _last_close(_download(ticker, period="5d", interval="1d"))
    except Exception:  # noqa: BLE001
        return None


def batched(seq: list[str], size: int):
    """Yield successive `size`-length chunks of `seq`."""
    for i in range(0, len(seq), size):
        yield seq[i:i + size]
