"""
Market-state detection and the active-window guard.

State is derived from the wall clock in the configured timezone (default
America/New_York), which cleanly separates the US trading sessions:

    04:00 - 09:30 ET  -> PRE   (pre-market)
    09:30 - 16:00 ET  -> LIVE  (regular trading hours)
    16:00 - 20:00 ET  -> POST  (after-hours)
    otherwise / wknd  -> CLOSED

The 09:00-21:00 scan window straddles PRE -> LIVE -> POST, which is exactly the
span the scanner is required to cover.
"""

from __future__ import annotations

from datetime import datetime, time
from enum import Enum
from zoneinfo import ZoneInfo


class MarketState(str, Enum):
    PRE = "PRE"
    LIVE = "LIVE"
    POST = "POST"
    CLOSED = "CLOSED"


# Session boundaries in the configured (US Eastern) local time.
_PRE_OPEN = time(4, 0)
_RTH_OPEN = time(9, 30)
_RTH_CLOSE = time(16, 0)
_POST_CLOSE = time(20, 0)


def now_in_tz(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def market_state(tz_name: str, at: datetime | None = None) -> MarketState:
    """Return the US market session for `at` (defaults to now) in `tz_name`."""
    at = at or now_in_tz(tz_name)
    # Monday=0 .. Sunday=6 ; markets closed on weekends.
    if at.weekday() >= 5:
        return MarketState.CLOSED
    t = at.timetz().replace(tzinfo=None)
    if _PRE_OPEN <= t < _RTH_OPEN:
        return MarketState.PRE
    if _RTH_OPEN <= t < _RTH_CLOSE:
        return MarketState.LIVE
    if _RTH_CLOSE <= t < _POST_CLOSE:
        return MarketState.POST
    return MarketState.CLOSED


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def in_active_window(cfg_schedule, at: datetime | None = None) -> bool:
    """True if `at` falls inside the configured [window_start, window_end]."""
    tz = cfg_schedule.timezone
    at = at or now_in_tz(tz)
    start = _parse_hhmm(cfg_schedule.window_start)
    end = _parse_hhmm(cfg_schedule.window_end)
    t = at.timetz().replace(tzinfo=None)
    return start <= t <= end
