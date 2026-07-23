"""
History tracker (persistence layer).

Turns the point-in-time scanner into a tracker. Every run:
  * new candidates are recorded with their FIRST-triggered price + timestamp;
  * tickers already tracked keep their original trigger price and get a fresh
    current price (from this run's candidate, or a live fetch if it didn't
    re-trigger but is still OPEN);
  * we derive direction (UP/DOWN vs the trigger price), % change, and a sticky
    status: OPEN -> TP_HIT (peak reached +5%) or SL_HIT (trough hit -2%).

State lives in docs/data/history.json and is committed back to the repo by the
workflow (same pattern as Stock_squeeze_screener's ticker_state.json), so it
accumulates across the 4 daily runs.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from . import data as dl


def load_history(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload.get("entries", []) if isinstance(payload, dict) else list(payload)
    except Exception:  # noqa: BLE001 - a corrupt file must not kill the scan
        return []


def _fmt(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M %Z")


def _apply_price(h: dict, price: float, now: datetime, state: str) -> None:
    price = float(price)
    h["current_price"] = round(price, 4)
    h["last_at"] = _fmt(now)
    h["last_iso"] = now.isoformat()
    h["last_state"] = state
    h["peak"] = round(max(h.get("peak", price), price), 4)
    h["trough"] = round(min(h.get("trough", price), price), 4)
    first = h["first_price"]
    h["change_pct"] = round((price - first) / first * 100, 2) if first else 0.0
    h["direction"] = "UP" if price >= first else "DOWN"
    # Sticky terminal status: once TP/SL is hit it stays (first event wins,
    # because we evaluate run-by-run in time order).
    if h.get("status") not in ("TP_HIT", "SL_HIT"):
        if h["peak"] >= h["tp_price"]:
            h["status"] = "TP_HIT"
        elif h["trough"] <= h["sl_price"]:
            h["status"] = "SL_HIT"
        else:
            h["status"] = "OPEN"


def _new_entry(r, now: datetime, state: str) -> dict:
    return {
        "ticker": r.ticker,
        "first_price": r.entry,
        "first_at": _fmt(now),
        "first_iso": now.isoformat(),
        "first_state": r.market_state,
        "tp_price": r.tp_price,
        "sl_price": r.sl_price,
        "score": r.score,
        "current_price": r.entry,
        "last_at": _fmt(now),
        "last_iso": now.isoformat(),
        "last_state": state,
        "peak": r.entry,
        "trough": r.entry,
        "change_pct": 0.0,
        "direction": "UP",
        "status": "OPEN",
    }


def update_history(history: list[dict], results, cfg, now: datetime, state: str) -> list[dict]:
    """Upsert this run's candidates, refresh still-open tickers, prune, sort."""
    by_ticker = {h["ticker"]: h for h in history}
    seen_now: set[str] = set()

    for r in results:
        seen_now.add(r.ticker)
        if r.ticker in by_ticker:
            _apply_price(by_ticker[r.ticker], r.entry, now, state)
        else:
            entry = _new_entry(r, now, state)
            history.append(entry)
            by_ticker[r.ticker] = entry

    # Refresh tickers we still track that didn't re-trigger this run.
    d = cfg.data
    for h in history:
        if h["ticker"] in seen_now or h.get("status") in ("TP_HIT", "SL_HIT"):
            continue
        price = dl.fetch_live_price(
            h["ticker"], interval=d.intraday_interval, period=d.intraday_lookback,
            prepost=d.prepost, max_retries=d.max_retries, backoff=d.retry_backoff,
        )
        if price is not None:
            _apply_price(h, price, now, state)

    _prune(history, cfg, now)
    history.sort(key=lambda h: h.get("first_iso", ""), reverse=True)  # newest first
    return history


def _prune(history: list[dict], cfg, now: datetime) -> None:
    days = getattr(cfg.output, "history_retention_days", 120)
    cap = getattr(cfg.output, "history_max", 300)
    cutoff = now - timedelta(days=days)
    kept: list[dict] = []
    for h in history:
        if h.get("status") == "OPEN":
            kept.append(h)
            continue
        try:
            first = datetime.fromisoformat(h["first_iso"])
            if first.tzinfo is None and cutoff.tzinfo is not None:
                first = first.replace(tzinfo=cutoff.tzinfo)
            keep = first >= cutoff
        except Exception:  # noqa: BLE001 - keep anything we can't date
            keep = True
        if keep:
            kept.append(h)
    history[:] = kept[:cap]


def save_history(history: list[dict], path: str, now: datetime) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {"updated": now.isoformat(), "count": len(history), "entries": history}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
