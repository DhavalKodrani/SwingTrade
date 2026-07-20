"""
swingscan - High-Probability Swing Trade Scanner
================================================
A modular, long-only intraday-triggered swing screener that runs 4x/day inside
a 12-hour window across the full US-listed universe.

Layer separation:
  data layer   : universe.py, data.py
  signal layer : indicators.py, market_state.py, signals.py, backtest.py
  render layer : render.py
  orchestration: scanner.py  (entrypoints: run_scan.py, scheduler.py)
"""

__version__ = "0.1.0"
