"""
Indicators (signal layer, pure math - no external TA library).
Vectorised pandas/numpy implementations. RSI and ATR use Wilder's RMA
(ewm alpha=1/period), which matches TradingView, consistent with the ATR in
supertrend-dashboard.

Every function takes/returns pandas Series so they compose cleanly and can be
attached as DataFrame columns for the historical backtest.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI (RMA smoothing)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # when avg_loss == 0 the stock only rose -> RSI 100
    out = out.where(avg_loss != 0.0, 100.0)
    return out


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (macd_line, signal_line, histogram)."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range using Wilder's RMA (matches TradingView / supertrend)."""
    high, low, close = df["High"], df["Low"], df["Close"]
    hl = high - low
    hc = (high - close.shift()).abs()
    lc = (low - close.shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def avg_volume(volume: pd.Series, period: int = 20) -> pd.Series:
    return volume.rolling(period).mean()


def rolling_prior_high(high: pd.Series, lookback: int) -> pd.Series:
    """Highest high over the PRIOR `lookback` bars (excludes the current bar),
    so a fresh close above it is a genuine breakout, not self-reference."""
    return high.shift(1).rolling(lookback).max()
