"""
Render layer - three views over the same results:
  cli_table()  : compact terminal table
  to_json()    : structured payload (dashboard data / API)
  build_html() : self-contained dashboard (GitHub Pages), client-side filter+sort

Mirrors the look and the client-side control pattern of supertrend-dashboard so
all three of your dashboards feel like one family.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import pandas as pd

from .signals import TradeSetup

STATE_COLORS = {"PRE": "#7c3aed", "LIVE": "#16a34a", "POST": "#0d9488", "CLOSED": "#6b7280"}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def cli_table(results: list[TradeSetup], scanned: int, state: str, top: int = 25) -> str:
    if not results:
        return f"\nNo qualifying swing setups ({scanned} scanned, market {state}).\n"
    rows = []
    header = (f"{'TICKER':<7}{'STATE':<7}{'ENTRY':>10}{'TP+5%':>10}{'SL-2%':>10}"
              f"{'SHARES':>9}{'SCORE':>7}{'WIN%':>7}{'N':>5}  BAND")
    rows.append(header)
    rows.append("-" * len(header))
    for r in results[:top]:
        win = f"{r.emp_win_rate*100:.0f}" if r.emp_win_rate is not None else "n/a"
        rows.append(
            f"{r.ticker:<7}{r.market_state:<7}{r.entry:>10.2f}{r.tp_price:>10.2f}"
            f"{r.sl_price:>10.2f}{r.shares:>9.2f}{r.score:>7.1f}{win:>7}"
            f"{r.emp_samples:>5}  {r.prob_band}"
        )
    footer = (f"\n{len(results)} candidate(s) / {scanned} scanned - market {state}. "
              f"WIN% = empirical TP-before-SL rate over N historical setups. "
              f"Technical screen, not financial advice.")
    return "\n".join(rows) + footer


# --------------------------------------------------------------------------- #
# JSON
# --------------------------------------------------------------------------- #
def to_json(results: list[TradeSetup], scanned: int, state: str, cfg) -> dict:
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "market_state": state,
        "scanned": scanned,
        "candidates": len(results),
        "risk": {
            "position_size": cfg.risk.position_size,
            "tp_pct": cfg.risk.tp_pct,
            "sl_pct": cfg.risk.sl_pct,
            "rr_ratio": round(cfg.risk.tp_pct / cfg.risk.sl_pct, 2),
        },
        "results": [r.to_dict() for r in results],
    }


def write_json(payload: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


# --------------------------------------------------------------------------- #
# HTML dashboard
# --------------------------------------------------------------------------- #
_VIEW_SCRIPT = """
<script>
function applyView() {
  var tbody = document.getElementById('rows');
  if (!tbody) return;
  var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr[data-ticker]'));
  var st = document.getElementById('filterState').value;
  var field = document.getElementById('sortField').value;
  var asc = document.getElementById('sortOrder').value === 'asc';
  var shown = 0;
  rows.forEach(function (r) {
    var visible = (st === 'ALL' || r.dataset.state === st);
    r.style.display = visible ? '' : 'none';
    if (visible) shown++;
  });
  rows.sort(function (a, b) {
    if (field === 'ticker') {
      var cmp = a.dataset.ticker.localeCompare(b.dataset.ticker);
      return asc ? cmp : -cmp;
    }
    var va = parseFloat(a.dataset[field]); var vb = parseFloat(b.dataset[field]);
    if (isNaN(va)) va = asc ? Infinity : -Infinity;
    if (isNaN(vb)) vb = asc ? Infinity : -Infinity;
    return asc ? va - vb : vb - va;
  });
  rows.forEach(function (r) { tbody.appendChild(r); });
  var c = document.getElementById('rowCount');
  if (c) c.textContent = shown + ' of ' + rows.length + ' rows';
}
</script>"""

_SELECT = ("padding:4px 8px;border:1px solid #cbd5e1;border-radius:6px;"
           "background:#fff;color:#334155;font-size:13px;")


def _controls() -> str:
    state_opts = "".join(f'<option value="{s}">{s}</option>' for s in STATE_COLORS)
    return f"""
    <div style="padding:0 24px 16px;display:flex;gap:16px;flex-wrap:wrap;align-items:center;
                font-size:13px;color:#334155;">
      <label>Market state:
        <select id="filterState" onchange="applyView()" style="{_SELECT}">
          <option value="ALL">All</option>{state_opts}
        </select>
      </label>
      <label>Sort by:
        <select id="sortField" onchange="applyView()" style="{_SELECT}">
          <option value="score">Score (default)</option>
          <option value="win">Empirical win %</option>
          <option value="ticker">Ticker</option>
          <option value="entry">Entry</option>
          <option value="vol">Volume x avg</option>
          <option value="rsi">RSI</option>
        </select>
      </label>
      <label>Order:
        <select id="sortOrder" onchange="applyView()" style="{_SELECT}">
          <option value="desc">Descending</option>
          <option value="asc">Ascending</option>
        </select>
      </label>
      <span id="rowCount" style="color:#94a3b8;"></span>
    </div>"""


def build_html(results: list[TradeSetup], scanned: int, state: str, cfg) -> str:
    ts = datetime.now().strftime("%A %d %B %Y, %H:%M")
    rr = round(cfg.risk.tp_pct / cfg.risk.sl_pct, 2)
    pos = cfg.risk.position_size

    if not results:
        body = ('<tr><td colspan="11" style="padding:16px;text-align:center;color:#64748b;">'
                'No qualifying setups this run.</td></tr>')
    else:
        cells = []
        for r in results[:cfg.output.max_rows]:
            col = STATE_COLORS.get(r.market_state, "#6b7280")
            win = f"{r.emp_win_rate*100:.0f}%" if r.emp_win_rate is not None else "n/a"
            win_sort = r.emp_win_rate if r.emp_win_rate is not None else ""
            cells.append(f"""
            <tr style="border-bottom:1px solid #e5e7eb;" data-ticker="{r.ticker}"
                data-state="{r.market_state}" data-score="{r.score}" data-win="{win_sort}"
                data-entry="{r.entry}" data-vol="{r.vol_ratio}" data-rsi="{r.rsi}">
              <td style="padding:8px 12px;font-weight:600;">{r.ticker}</td>
              <td style="padding:8px 12px;"><span style="background:{col};color:#fff;
                  border-radius:6px;padding:2px 10px;font-size:12px;">{r.market_state}</span></td>
              <td style="padding:8px 12px;">{r.entry:.2f}</td>
              <td style="padding:8px 12px;color:#16a34a;">{r.tp_price:.2f}</td>
              <td style="padding:8px 12px;color:#dc2626;">{r.sl_price:.2f}</td>
              <td style="padding:8px 12px;">{r.shares:.2f}</td>
              <td style="padding:8px 12px;">+{r.reward_amt:.0f} / -{r.risk_amt:.0f}</td>
              <td style="padding:8px 12px;font-weight:600;">{r.score:.1f}</td>
              <td style="padding:8px 12px;">{win} <span style="color:#94a3b8;">({r.emp_samples})</span></td>
              <td style="padding:8px 12px;color:#475569;">{r.prob_band}</td>
              <td style="padding:8px 12px;color:#64748b;">{r.rsi:.0f} / {r.vol_ratio:.1f}x</td>
            </tr>""")
        body = "".join(cells)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>High-Probability Swing Trade Scanner</title></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f8fafc;margin:0;padding:24px;">
  <div style="max-width:1040px;margin:auto;background:#fff;border-radius:12px;
              box-shadow:0 1px 4px rgba(0,0,0,.08);overflow:hidden;">
    <div style="background:#0f172a;color:#fff;padding:20px 24px;">
      <h1 style="margin:0;font-size:20px;">High-Probability Swing Trade Scanner</h1>
      <p style="margin:6px 0 0;color:#94a3b8;font-size:13px;">
        Generated {ts} - market state <b style="color:#fff;">{state}</b> -
        {scanned} tickers scanned - long-only - R:R 1:{rr} (TP +{cfg.risk.tp_pct*100:.0f}% /
        SL -{cfg.risk.sl_pct*100:.0f}%) - base {pos:.0f}/trade
      </p>
    </div>
    {_controls()}
    <div style="overflow-x:auto;">
    <table style="border-collapse:collapse;width:100%;font-size:14px;min-width:920px;">
      <thead>
        <tr style="background:#f1f5f9;text-align:left;color:#334155;">
          <th style="padding:10px 12px;">Ticker</th><th style="padding:10px 12px;">State</th>
          <th style="padding:10px 12px;">Entry</th><th style="padding:10px 12px;">TP +5%</th>
          <th style="padding:10px 12px;">SL -2%</th><th style="padding:10px 12px;">Shares</th>
          <th style="padding:10px 12px;">Rwd/Risk</th><th style="padding:10px 12px;">Score</th>
          <th style="padding:10px 12px;">Win% (n)</th><th style="padding:10px 12px;">Band</th>
          <th style="padding:10px 12px;">RSI / Vol</th>
        </tr>
      </thead>
      <tbody id="rows">{body}</tbody>
    </table>
    </div>
    <p style="padding:16px 24px;color:#94a3b8;font-size:12px;line-height:1.6;">
      <b>Score</b> = 0-100 signal-strength composite (ranking only). <b>Win%</b> = empirical rate
      at which the identical setup historically reached +{cfg.risk.tp_pct*100:.0f}% before
      -{cfg.risk.sl_pct*100:.0f}% within {cfg.backtest.hold_days} trading days, over <i>n</i> past
      occurrences (n/a = too few samples). A high score is <b>not</b> a guaranteed win rate.
      Educational technical screen only - <b>not financial advice</b>. Verify independently.
    </p>
  </div>
  {_VIEW_SCRIPT}
  <script>applyView();</script>
</body></html>"""


def write_html(html: str, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
