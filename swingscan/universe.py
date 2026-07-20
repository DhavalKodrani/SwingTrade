"""
Universe (data layer) - identical source to Stock_squeeze_screener and
supertrend-dashboard: all US-listed common stocks from the NASDAQ Trader symbol
directory, with tickers.txt as a fallback safety net.

Keeping the same source means all three systems scan the same names, so a
SwingTrade signal can be cross-referenced against the squeeze/supertrend views.
"""

from __future__ import annotations

import io
import os

import pandas as pd
import requests

NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


def fetch_universe(fallback_file: str = "tickers.txt", max_tickers: int = 8000) -> list[str]:
    """
    Return a sorted, de-duplicated list of clean US-listed common-stock symbols.
    Falls back to `fallback_file` if the live download fails.
    """
    tickers: set[str] = set()
    try:
        for url, sym_col in [(NASDAQ_LISTED, "Symbol"), (OTHER_LISTED, "ACT Symbol")]:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text), sep="|")
            df = df[df[sym_col].notna()]
            if "Test Issue" in df.columns:
                df = df[df["Test Issue"] == "N"]
            if "ETF" in df.columns:
                df = df[df["ETF"] == "N"]
            for sym in df[sym_col].astype(str):
                sym = sym.strip().upper()
                # keep plain common stock; skip warrants/units/preferreds/test rows
                if sym and sym.isalpha() and len(sym) <= 5:
                    tickers.add(sym)
        print(f"Universe: {len(tickers)} tickers from NASDAQ Trader")
    except Exception as exc:  # noqa: BLE001 - deliberately broad; we degrade gracefully
        print(f"Universe fetch failed ({exc}) - using fallback file '{fallback_file}'")
        tickers = _read_fallback(fallback_file)

    return sorted(tickers)[:max_tickers]


def _read_fallback(fallback_file: str) -> set[str]:
    if not os.path.exists(fallback_file):
        # try alongside the project root as well
        alt = os.path.join(os.path.dirname(os.path.dirname(__file__)), fallback_file)
        fallback_file = alt if os.path.exists(alt) else fallback_file
    out: set[str] = set()
    if os.path.exists(fallback_file):
        with open(fallback_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    out.add(line.upper())
    return out


def parse_ticker_arg(raw: str) -> list[str]:
    """Parse a comma/space separated custom ticker string into a clean list."""
    if not raw:
        return []
    parts = raw.replace(",", " ").split()
    seen, out = set(), []
    for p in parts:
        p = p.strip().upper()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out
