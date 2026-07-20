"""
Signal logic (signal layer) - long-only swing setups.

Design principle: compute every indicator as a DataFrame COLUMN once, then
derive the entry conditions as boolean Series. The live decision reads the last
row; the backtest (backtest.py) reuses the identical boolean mask over history.
One definition of "a setup", two consumers - no drift between live and backtest.

The six gates (all required to be a candidate):
  1. UPTREND    EMA_fast > EMA_slow
  2. STRUCTURE  close > EMA_fast
  3. MOMENTUM   MACD line > signal AND histogram > 0
  4. RSI BAND   rsi_min <= RSI <= rsi_max      (momentum, not overbought)
  5. VOLUME     volume > vol_breakout * avg_volume
  6. BREAKOUT   close within `tolerance` of the prior N-day high

Each gate also contributes a graded 0-100 sub-score; the weighted sum is the
signal-strength score used for ranking.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from . import indicators as ind
from .market_state import MarketState


# --------------------------------------------------------------------------- #
# Data structure
# --------------------------------------------------------------------------- #
@dataclass
class TradeSetup:
    ticker: str
    market_state: str          # PRE / LIVE / POST / CLOSED
    entry: float               # trigger / recommended entry (live price)
    tp_price: float            # +tp_pct target
    sl_price: float            # -sl_pct stop
    tp_pct: float
    sl_pct: float
    rr_ratio: float            # reward : risk (e.g. 2.5)
    position_size: float       # base allocation (currency units)
    shares: float              # position_size / entry
    risk_amt: float            # position_size * sl_pct
    reward_amt: float          # position_size * tp_pct
    score: float               # 0-100 signal strength (ranking)
    prob_band: str             # human label derived from score
    emp_win_rate: float | None  # empirical TP-before-SL rate (may be None)
    emp_samples: int           # historical setups behind emp_win_rate
    # indicator snapshot (for transparency on the dashboard)
    rsi: float
    macd_hist: float
    ema_fast: float
    ema_slow: float
    vol_ratio: float
    atr_pct: float             # ATR as % of price (volatility context)
    asof: str                  # timestamp of the scan

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Indicator frame - single source of truth
# --------------------------------------------------------------------------- #
def build_frame(df: pd.DataFrame, sig) -> pd.DataFrame:
    """Attach all indicator columns and the boolean gate columns to a copy."""
    out = df.copy()
    close = out["Close"]

    out["EMA_FAST"] = ind.ema(close, sig.ema_fast)
    out["EMA_SLOW"] = ind.ema(close, sig.ema_slow)
    out["RSI"] = ind.rsi(close, sig.rsi_period)
    macd_line, macd_sig, hist = ind.macd(close, sig.macd_fast, sig.macd_slow, sig.macd_signal)
    out["MACD"] = macd_line
    out["MACD_SIG"] = macd_sig
    out["MACD_HIST"] = hist
    out["AVG_VOL"] = ind.avg_volume(out["Volume"], sig.vol_period)
    out["VOL_RATIO"] = out["Volume"] / out["AVG_VOL"]
    out["ATR"] = ind.atr(out, sig.atr_period)
    out["PRIOR_HIGH"] = ind.rolling_prior_high(out["High"], sig.breakout_lookback)

    # ---- boolean gates (vectorised; reused by the backtest) ----
    out["G_TREND"] = out["EMA_FAST"] > out["EMA_SLOW"]
    out["G_STRUCT"] = close > out["EMA_FAST"]
    out["G_MOMENTUM"] = (out["MACD"] > out["MACD_SIG"]) & (out["MACD_HIST"] > 0)
    out["G_RSI"] = (out["RSI"] >= sig.rsi_min) & (out["RSI"] <= sig.rsi_max)
    out["G_VOLUME"] = out["VOL_RATIO"] > sig.vol_breakout
    out["G_BREAKOUT"] = close >= (out["PRIOR_HIGH"] * (1.0 - sig.breakout_tolerance))

    out["SETUP"] = (
        out["G_TREND"] & out["G_STRUCT"] & out["G_MOMENTUM"]
        & out["G_RSI"] & out["G_VOLUME"] & out["G_BREAKOUT"]
    )
    return out


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _grade_row(row: pd.Series, sig) -> float:
    """
    Graded 0-100 composite. Weights sum to 100. Each component measures how
    STRONGLY (not just whether) a condition is met, so two candidates that both
    pass the gate still separate by quality.
    """
    # Trend strength: EMA_fast above EMA_slow, scaled by separation up to ~5%.
    sep = (row["EMA_FAST"] - row["EMA_SLOW"]) / row["EMA_SLOW"] if row["EMA_SLOW"] else 0.0
    trend = _clamp(sep / 0.05)

    # Structure: how far above EMA_fast, up to ~4% (too far = extended).
    dist = (row["Close"] - row["EMA_FAST"]) / row["EMA_FAST"] if row["EMA_FAST"] else 0.0
    struct = _clamp(dist / 0.04)

    # Momentum: MACD histogram normalised by price.
    mom = _clamp((row["MACD_HIST"] / row["Close"]) / 0.01) if row["Close"] else 0.0

    # RSI centring: best near the middle of the [min,max] band (~60 by default).
    center = (sig.rsi_min + sig.rsi_max) / 2.0
    half = (sig.rsi_max - sig.rsi_min) / 2.0
    rsi_q = 1.0 - _clamp(abs(row["RSI"] - center) / half) if half else 0.0

    # Volume conviction: ratio above the breakout threshold, up to ~3x.
    vr = row["VOL_RATIO"] if np.isfinite(row["VOL_RATIO"]) else 0.0
    vol = _clamp((vr - sig.vol_breakout) / (3.0 - sig.vol_breakout))

    # Breakout tightness: closer to / above prior high scores higher.
    if row["PRIOR_HIGH"] and np.isfinite(row["PRIOR_HIGH"]):
        brk = _clamp((row["Close"] / row["PRIOR_HIGH"] - (1 - sig.breakout_tolerance))
                     / (2 * sig.breakout_tolerance))
    else:
        brk = 0.0

    score = (
        trend * 20 + struct * 15 + mom * 20
        + rsi_q * 15 + vol * 20 + brk * 10
    )
    return round(float(score), 1)


def prob_band(score: float, risk_cfg) -> str:
    """Human label for the strength score. NOT a guaranteed win rate - the
    empirical rate is reported separately."""
    if score >= 80:
        return f"High (aim {int(risk_cfg.prob_target_low*100)}-{int(risk_cfg.prob_target_high*100)}%)"
    if score >= 68:
        return "Medium-High"
    if score >= 55:
        return "Medium"
    return "Low"


# --------------------------------------------------------------------------- #
# Live evaluation
# --------------------------------------------------------------------------- #
def evaluate(
    ticker: str,
    frame: pd.DataFrame,
    live_price: float,
    state: MarketState,
    cfg,
    asof: str,
) -> TradeSetup | None:
    """
    Turn a fully-built indicator frame + a live price into a TradeSetup, or None
    if the last bar isn't a qualifying setup or fails universe/liquidity filters.
    The empirical win-rate is filled in by the scanner (needs deeper history).
    """
    sig, risk, uni = cfg.signals, cfg.risk, cfg.universe
    if len(frame) < max(sig.ema_slow, sig.atr_period) + 5:
        return None

    last = frame.iloc[-1]
    if not bool(last["SETUP"]):
        return None

    # Universe filters (price floor/cap + liquidity), mirrors sister projects.
    if live_price < uni.min_price:
        return None
    if uni.max_price is not None and live_price > uni.max_price:
        return None
    avg_dollar_vol = float((frame["Close"] * frame["Volume"]).iloc[-uni_window(sig):].mean())
    if avg_dollar_vol < uni.min_avg_dollar_vol:
        return None

    score = _grade_row(last, sig)
    if score < sig.score_threshold:
        return None

    entry = float(live_price)
    tp = entry * (1.0 + risk.tp_pct)
    sl = entry * (1.0 - risk.sl_pct)
    atr_pct = float(last["ATR"] / entry * 100) if entry else float("nan")

    return TradeSetup(
        ticker=ticker,
        market_state=state.value,
        entry=round(entry, 4),
        tp_price=round(tp, 4),
        sl_price=round(sl, 4),
        tp_pct=risk.tp_pct,
        sl_pct=risk.sl_pct,
        rr_ratio=round(risk.tp_pct / risk.sl_pct, 2),
        position_size=float(risk.position_size),
        shares=round(risk.position_size / entry, 4) if entry else 0.0,
        risk_amt=round(risk.position_size * risk.sl_pct, 2),
        reward_amt=round(risk.position_size * risk.tp_pct, 2),
        score=score,
        prob_band=prob_band(score, risk),
        emp_win_rate=None,     # filled by scanner
        emp_samples=0,         # filled by scanner
        rsi=round(float(last["RSI"]), 1),
        macd_hist=round(float(last["MACD_HIST"]), 4),
        ema_fast=round(float(last["EMA_FAST"]), 2),
        ema_slow=round(float(last["EMA_SLOW"]), 2),
        vol_ratio=round(float(last["VOL_RATIO"]), 2) if np.isfinite(last["VOL_RATIO"]) else 0.0,
        atr_pct=round(atr_pct, 2) if not math.isnan(atr_pct) else 0.0,
        asof=asof,
    )


def uni_window(sig) -> int:
    """Bars used for the average-dollar-volume liquidity check."""
    return int(sig.vol_period)
