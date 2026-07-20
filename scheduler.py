#!/usr/bin/env python3
"""
scheduler.py - internal loop scheduler for the "exactly 4x/day" rule.

Use this when you want the scanner to run as a long-lived local process instead
of GitHub Actions cron (.github/workflows/swing_scan.yml is the production path).

Behaviour:
  * Reads the 4 run_times from config.yaml (local to schedule.timezone).
  * Sleeps until the next run_time, then executes one scan.
  * Never runs outside the 09:00-21:00 window (run_scan enforces this too).
  * Rolls over at midnight to the next day's schedule.

  python scheduler.py                 # run forever, 4x/day
  python scheduler.py --once-now       # run a single scan immediately then exit
  python scheduler.py --dry-run        # print the computed schedule and exit
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta

from swingscan.config import load_config
from swingscan.market_state import now_in_tz
from swingscan.market_state import _parse_hhmm  # internal helper reused intentionally
import run_scan


def _todays_run_datetimes(cfg, ref: datetime) -> list[datetime]:
    """The configured run_times as tz-aware datetimes on ref's date, sorted."""
    out = []
    for hhmm in cfg.schedule.run_times:
        t = _parse_hhmm(hhmm)
        out.append(ref.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0))
    return sorted(out)


def _next_run(cfg, now: datetime) -> datetime:
    """Next scheduled run at or after `now`, rolling to tomorrow if all passed."""
    today = _todays_run_datetimes(cfg, now)
    for dt in today:
        if dt >= now:
            return dt
    tomorrow = now + timedelta(days=1)
    return _todays_run_datetimes(cfg, tomorrow)[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="4x/day internal scheduler")
    ap.add_argument("--config", default=None)
    ap.add_argument("--once-now", action="store_true", help="run one scan now, then exit")
    ap.add_argument("--dry-run", action="store_true", help="print schedule and exit")
    ap.add_argument("--limit", type=int, default=0, help="cap universe (passed through)")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    tz = cfg.schedule.timezone

    if args.dry_run:
        now = now_in_tz(tz)
        runs = _todays_run_datetimes(cfg, now)
        print(f"Timezone: {tz} | window {cfg.schedule.window_start}-{cfg.schedule.window_end}")
        print("Today's runs:")
        for dt in runs:
            print(f"  {dt:%H:%M %Z}")
        print(f"Next run: {_next_run(cfg, now):%Y-%m-%d %H:%M %Z}")
        return 0

    scan_argv = ["--force"] + (["--limit", str(args.limit)] if args.limit else [])

    if args.once_now:
        print(f"[{now_in_tz(tz):%Y-%m-%d %H:%M %Z}] running one scan now...")
        return run_scan.main(scan_argv)

    print(f"Scheduler started. 4 runs/day in {tz}: {', '.join(cfg.schedule.run_times)}")
    while True:
        now = now_in_tz(tz)
        target = _next_run(cfg, now)
        wait_s = max(0.0, (target - now).total_seconds())
        print(f"[{now:%Y-%m-%d %H:%M %Z}] next run at {target:%Y-%m-%d %H:%M %Z} "
              f"(sleeping {wait_s/3600:.2f}h)")
        time.sleep(wait_s)
        try:
            print(f"[{now_in_tz(tz):%Y-%m-%d %H:%M %Z}] === scheduled scan ===")
            run_scan.main(scan_argv)
        except Exception as exc:  # noqa: BLE001 - a failed run must not kill the loop
            print(f"Scan raised (continuing): {exc}")
        # Nudge past the target minute so we don't double-fire within it.
        time.sleep(61)


if __name__ == "__main__":
    raise SystemExit(main())
