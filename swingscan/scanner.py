"""
Scanner (orchestration).

Pipeline:
  universe -> [batched daily fetch] -> build indicator frame -> daily gate
           -> (only for survivors) live price incl. pre/post
           -> TradeSetup + empirical win-rate -> ranked results

The expensive per-ticker work (intraday call + backtest) happens ONLY for names
that already passed the cheap batched daily gate, so a full-universe scan makes
a few dozen intraday calls, not thousands.
"""

from __future__ import annotations

import time
from datetime import datetime

import pandas as pd

from . import data as datalayer
from . import signals as sg
from .backtest import empirical_win_rate
from .market_state import MarketState, market_state, now_in_tz


def scan(
    tickers: list[str],
    cfg,
    state: MarketState | None = None,
    progress_every: int = 1,
) -> tuple[list[sg.TradeSetup], int]:
    """Run one full scan. Returns (ranked setups, tickers_scanned)."""
    dcfg, sig, bt = cfg.data, cfg.signals, cfg.backtest
    tz = cfg.schedule.timezone
    state = state or market_state(tz)
    asof = now_in_tz(tz).strftime("%Y-%m-%d %H:%M %Z")

    results: list[sg.TradeSetup] = []
    scanned = 0
    batches = list(datalayer.batched(tickers, dcfg.batch_size))

    for bi, batch in enumerate(batches, 1):
        frames = datalayer.fetch_daily_batch(
            batch, period=dcfg.backtest_lookback,
            max_retries=dcfg.max_retries, backoff=dcfg.retry_backoff,
        )
        for tkr, df in frames.items():
            scanned += 1
            setup = _evaluate_one(tkr, df, state, cfg, asof)
            if setup is not None:
                results.append(setup)
        if bi % progress_every == 0:
            print(f"batch {bi}/{len(batches)} done - {len(results)} candidates so far")
        time.sleep(dcfg.batch_pause)

    # Rank: score desc, then empirical win-rate desc (None treated as -1).
    results.sort(key=lambda s: (s.score, s.emp_win_rate if s.emp_win_rate is not None else -1),
                 reverse=True)
    return results, scanned


def _evaluate_one(tkr, df, state, cfg, asof) -> sg.TradeSetup | None:
    """Daily gate -> live price -> setup -> backtest. None if it drops out."""
    dcfg, bt = cfg.data, cfg.backtest
    try:
        frame = sg.build_frame(df, cfg.signals)
    except Exception:  # noqa: BLE001 - one malformed frame never stops the scan
        return None

    # Cheap gate on the last daily bar before spending an intraday call.
    if not bool(frame["SETUP"].iloc[-1]):
        return None

    # Live price incl. pre/post; fall back to last daily close if extended-hours
    # data is empty (thin sessions) so we still produce a valid trigger.
    live = datalayer.fetch_live_price(
        tkr, interval=dcfg.intraday_interval, period=dcfg.intraday_lookback,
        prepost=dcfg.prepost, max_retries=dcfg.max_retries, backoff=dcfg.retry_backoff,
    )
    if live is None:
        live = float(frame["Close"].iloc[-1])

    setup = sg.evaluate(tkr, frame, live, state, cfg, asof)
    if setup is None:
        return None

    # Empirical win-rate from this ticker's own history (same setup mask).
    rate, wins, total = empirical_win_rate(
        frame, frame["SETUP"],
        tp_pct=cfg.risk.tp_pct, sl_pct=cfg.risk.sl_pct,
        hold_days=bt.hold_days, min_samples=bt.min_samples,
        sl_first_on_conflict=(bt.intrabar_conflict == "sl_first"),
    )
    setup.emp_win_rate = round(rate, 3) if rate is not None else None
    setup.emp_samples = total
    return setup


def results_to_frame(results: list[sg.TradeSetup]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()
    return pd.DataFrame([r.to_dict() for r in results])
