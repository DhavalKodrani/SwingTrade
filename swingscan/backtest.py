"""
Empirical win-rate (signal layer).

This is the honest core of the "probability" claim. Instead of asserting a
75-80% win rate, we REPLAY the exact same long entry rule over the ticker's own
history and measure how often the trade would have hit +tp_pct before -sl_pct
within `hold_days`. The reported probability is therefore grounded in that
ticker's real price behaviour, and always carries its sample size.

Conflict rule: if a single day's range spans both the TP and the SL, we cannot
know which was touched first from daily bars, so we conservatively count it as a
LOSS (`intrabar_conflict: sl_first`). This biases the estimate downward, which
is the safe direction for a screener.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def empirical_win_rate(
    df: pd.DataFrame,
    setup_mask: pd.Series,
    tp_pct: float,
    sl_pct: float,
    hold_days: int,
    min_samples: int,
    sl_first_on_conflict: bool = True,
) -> tuple[float | None, int, int]:
    """
    Parameters
    ----------
    df         : daily OHLCV with a Rangeable DatetimeIndex.
    setup_mask : boolean Series (same index) - True where the entry rule fired.
    Returns (win_rate | None, wins, total). None when total < min_samples.
    """
    high = df["High"].to_numpy()
    low = df["Low"].to_numpy()
    close = df["Close"].to_numpy()
    mask = setup_mask.to_numpy()
    n = len(df)

    wins = 0
    total = 0
    # Don't evaluate the final `hold_days` bars - not enough forward data.
    last_eval = n - hold_days
    for i in range(last_eval):
        if not mask[i]:
            continue
        entry = close[i]
        if not np.isfinite(entry) or entry <= 0:
            continue
        tp = entry * (1.0 + tp_pct)
        sl = entry * (1.0 - sl_pct)

        outcome = None
        for j in range(i + 1, min(i + 1 + hold_days, n)):
            hit_tp = high[j] >= tp
            hit_sl = low[j] <= sl
            if hit_tp and hit_sl:
                outcome = False if sl_first_on_conflict else True
                break
            if hit_tp:
                outcome = True
                break
            if hit_sl:
                outcome = False
                break
        # No touch within the window -> resolve by final price vs entry.
        if outcome is None:
            end = min(i + hold_days, n - 1)
            outcome = close[end] >= entry

        total += 1
        wins += 1 if outcome else 0

    if total < min_samples:
        return None, wins, total
    return wins / total, wins, total
