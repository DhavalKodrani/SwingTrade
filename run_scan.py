#!/usr/bin/env python3
"""
run_scan.py - execute ONE swing scan (one of the four daily runs).

Examples
--------
  python run_scan.py                          # full universe, current market state
  python run_scan.py --tickers AAPL,NVDA,AMD  # custom on-demand list
  python run_scan.py --force                   # ignore the 09:00-21:00 window guard
  python run_scan.py --limit 300               # scan only the first N of the universe

Writes: swing_report.html + docs/data/results.json, prints a CLI table.
Emails the dashboard if EMAIL_* env vars are set (optional, mirrors sisters).
"""

from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from swingscan.config import load_config
from swingscan.market_state import MarketState, market_state, in_active_window, now_in_tz
from swingscan import render
from swingscan.scanner import scan
from swingscan.universe import fetch_universe, parse_ticker_arg


def send_email(html: str, cfg) -> None:
    sender = os.environ.get("EMAIL_SENDER") or os.environ.get("EMAIL_ADDRESS")
    password = os.environ.get("EMAIL_PASSWORD")
    recipient = os.environ.get("EMAIL_RECIPIENT", sender)
    if not sender or not password:
        print("Email secrets not set - skipping email (report saved locally).")
        return
    server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Swing Scanner - {datetime.now():%d %b %Y %H:%M}"
    msg["From"], msg["To"] = sender, recipient
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL(server, port, context=ssl.create_default_context()) as s:
        s.login(sender, password)
        s.sendmail(sender, recipient, msg.as_string())
    print(f"Report emailed to {recipient}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="High-Probability Swing Trade Scanner - single run")
    ap.add_argument("--config", default=None, help="path to config.yaml")
    ap.add_argument("--tickers", default="", help="comma/space separated custom list")
    ap.add_argument("--force", action="store_true", help="ignore the active-window guard")
    ap.add_argument("--limit", type=int, default=0, help="cap universe size (debug/smoke test)")
    ap.add_argument("--no-email", action="store_true", help="never attempt to email")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    tz = cfg.schedule.timezone
    state = market_state(tz)

    # Active-window guard: the spec restricts operation to 09:00-21:00.
    if not args.force and not in_active_window(cfg.schedule):
        now = now_in_tz(tz).strftime("%H:%M %Z")
        print(f"Outside active window {cfg.schedule.window_start}-{cfg.schedule.window_end} "
              f"(now {now}). Use --force to override. Exiting.")
        return 0

    # Ticker selection: custom list, or full universe.
    custom = parse_ticker_arg(args.tickers)
    if custom:
        tickers = custom
        print(f"Custom scan: {len(tickers)} tickers - market state {state.value}")
    else:
        tickers = fetch_universe(cfg.universe.fallback_file, cfg.universe.max_tickers)
        if args.limit > 0:
            tickers = tickers[:args.limit]
        print(f"Full scan: {len(tickers)} tickers - market state {state.value}")

    results, scanned = scan(tickers, cfg, state=state)

    # ---- render all three views ----
    print(render.cli_table(results, scanned, state.value))
    render.write_html(render.build_html(results, scanned, state.value, cfg), cfg.output.report_html)
    render.write_json(render.to_json(results, scanned, state.value, cfg), cfg.output.results_json)
    print(f"\nSaved {cfg.output.report_html} and {cfg.output.results_json}")

    if not args.no_email:
        try:
            with open(cfg.output.report_html, "r", encoding="utf-8") as fh:
                send_email(fh.read(), cfg)
        except Exception as exc:  # noqa: BLE001 - email must never fail the scan
            print(f"Email step failed (non-fatal): {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
