"""
Render layer - three views over the same results:
  cli_table()  : compact terminal table
  to_json()    : structured payload (dashboard data / API)
  build_html() : self-contained tabbed dashboard (GitHub Pages)

The dashboard has two tabs:
  Current  - this run's ranked swing candidates (filter/sort).
  History  - every tracked trigger: first price vs current, a green up / red
             down change column, and TP/SL-hit status.

Ticker names on BOTH tabs link to TradingView. Mirrors the look and client-side
control pattern of supertrend-dashboard so all three dashboards feel like family.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from .signals import TradeSetup

STATE_COLORS = {"PRE": "#7c3aed", "LIVE": "#16a34a", "POST": "#0d9488", "CLOSED": "#6b7280"}
STATUS_META = {
    "OPEN": ("Open", "#6b7280"),
    "TP_HIT": ("TP hit ✓", "#16a34a"),
    "SL_HIT": ("SL hit ✗", "#dc2626"),
}


def _tv(ticker: str) -> str:
    """TradingView hyperlink for a ticker (opens in a new tab)."""
    return (f'<a href="https://www.tradingview.com/symbols/{ticker}/" target="_blank" '
            f'rel="noopener" style="color:#2563eb;text-decoration:none;font-weight:600;">'
            f'{ticker}↗</a>')


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
_STYLE = """
<style>
  .tabbar { display:flex; gap:4px; padding:0 24px; border-bottom:1px solid #e5e7eb; }
  .tab { padding:10px 18px; cursor:pointer; border:none; background:none; font-size:14px;
         color:#64748b; border-bottom:2px solid transparent; font-weight:600; }
  .tab.active { color:#0f172a; border-bottom-color:#2563eb; }
  .sel { padding:4px 8px; border:1px solid #cbd5e1; border-radius:6px; background:#fff;
         color:#334155; font-size:13px; }
  table { border-collapse:collapse; width:100%; font-size:14px; }
  th { padding:10px 12px; background:#f1f5f9; text-align:left; color:#334155; }
  td { padding:8px 12px; border-bottom:1px solid #e5e7eb; }
  .wrap { overflow-x:auto; }
</style>"""

_SCRIPT = """
<script>
function showTab(name) {
  document.getElementById('panel-current').style.display = name === 'current' ? '' : 'none';
  document.getElementById('panel-history').style.display = name === 'history' ? '' : 'none';
  document.getElementById('btn-current').className = 'tab' + (name === 'current' ? ' active' : '');
  document.getElementById('btn-history').className = 'tab' + (name === 'history' ? ' active' : '');
}
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
var histState = { field: null, asc: true };
function sortHist(field, type) {
  var tb = document.getElementById('histrows');
  if (!tb) return;
  var rows = Array.prototype.slice.call(tb.querySelectorAll('tr'));
  if (histState.field === field) { histState.asc = !histState.asc; }
  else { histState.field = field; histState.asc = true; }
  var asc = histState.asc;
  rows.sort(function (a, b) {
    var va = a.dataset[field], vb = b.dataset[field];
    if (type === 'num') {
      va = parseFloat(va); vb = parseFloat(vb);
      if (isNaN(va)) va = asc ? Infinity : -Infinity;
      if (isNaN(vb)) vb = asc ? Infinity : -Infinity;
      return asc ? va - vb : vb - va;
    }
    va = va || ''; vb = vb || '';
    var cmp = va.localeCompare(vb);
    return asc ? cmp : -cmp;
  });
  rows.forEach(function (r) { tb.appendChild(r); });
}
</script>"""


def _current_controls() -> str:
    state_opts = "".join(f'<option value="{s}">{s}</option>' for s in STATE_COLORS)
    return f"""
    <div style="padding:16px 24px 12px;display:flex;gap:16px;flex-wrap:wrap;align-items:center;
                font-size:13px;color:#334155;">
      <label>Market state:
        <select id="filterState" onchange="applyView()" class="sel">
          <option value="ALL">All</option>{state_opts}
        </select>
      </label>
      <label>Sort by:
        <select id="sortField" onchange="applyView()" class="sel">
          <option value="score">Score (default)</option>
          <option value="win">Empirical win %</option>
          <option value="ticker">Ticker</option>
          <option value="entry">Entry</option>
          <option value="vol">Volume x avg</option>
          <option value="rsi">RSI</option>
        </select>
      </label>
      <label>Order:
        <select id="sortOrder" onchange="applyView()" class="sel">
          <option value="desc">Descending</option>
          <option value="asc">Ascending</option>
        </select>
      </label>
      <span id="rowCount" style="color:#94a3b8;"></span>
    </div>"""


def _current_table(results: list[TradeSetup], first_seen: dict, cfg) -> str:
    if not results:
        return ('<div class="wrap"><table><tbody><tr><td colspan="12" '
                'style="text-align:center;color:#64748b;padding:16px;">'
                'No qualifying setups this run.</td></tr></tbody></table></div>')
    rows = []
    for r in results[:cfg.output.max_rows]:
        col = STATE_COLORS.get(r.market_state, "#6b7280")
        win = f"{r.emp_win_rate*100:.0f}%" if r.emp_win_rate is not None else "n/a"
        win_sort = r.emp_win_rate if r.emp_win_rate is not None else ""
        # When this signal FIRST triggered (from history); falls back to this scan.
        trig_at, trig_iso = first_seen.get(r.ticker, (r.asof, r.asof))
        rows.append(f"""
          <tr data-ticker="{r.ticker}" data-state="{r.market_state}" data-score="{r.score}"
              data-win="{win_sort}" data-entry="{r.entry}" data-vol="{r.vol_ratio}" data-rsi="{r.rsi}"
              data-trig="{trig_iso}">
            <td>{_tv(r.ticker)}</td>
            <td><span style="background:{col};color:#fff;border-radius:6px;padding:2px 10px;
                font-size:12px;">{r.market_state}</span></td>
            <td style="color:#475569;white-space:nowrap;">{trig_at}</td>
            <td>{r.entry:.2f}</td>
            <td style="color:#16a34a;">{r.tp_price:.2f}</td>
            <td style="color:#dc2626;">{r.sl_price:.2f}</td>
            <td>{r.shares:.2f}</td>
            <td>+{r.reward_amt:.0f} / -{r.risk_amt:.0f}</td>
            <td style="font-weight:600;">{r.score:.1f}</td>
            <td>{win} <span style="color:#94a3b8;">({r.emp_samples})</span></td>
            <td style="color:#475569;">{r.prob_band}</td>
            <td style="color:#64748b;">{r.rsi:.0f} / {r.vol_ratio:.1f}x</td>
          </tr>""")
    return f"""
      <div class="wrap">
      <table style="min-width:1020px;">
        <thead><tr>
          <th>Ticker</th><th>State</th><th>Triggered</th><th>Entry</th><th>TP +5%</th><th>SL -2%</th>
          <th>Shares</th><th>Rwd/Risk</th><th>Score</th><th>Win% (n)</th><th>Band</th><th>RSI / Vol</th>
        </tr></thead>
        <tbody id="rows">{''.join(rows)}</tbody>
      </table>
      </div>"""


_STATUS_RANK = {"OPEN": 0, "TP_HIT": 1, "SL_HIT": 2}


def _history_table(history: list[dict]) -> str:
    if not history:
        return ('<div class="wrap"><table><tbody><tr><td colspan="8" '
                'style="text-align:center;color:#64748b;padding:16px;">'
                'No tracked triggers yet - history builds up as scans run.</td></tr></tbody></table></div>')
    rows = []
    for h in history:
        up = h.get("direction") == "UP"
        arrow, acol = ("▲", "#16a34a") if up else ("▼", "#dc2626")
        chg = h.get("change_pct", 0.0)
        status = h.get("status", "OPEN")
        label, scol = STATUS_META.get(status, ("Open", "#6b7280"))
        state_col = STATE_COLORS.get(h.get("first_state", "CLOSED"), "#6b7280")
        cur = h.get("current_price", h["first_price"])
        rows.append(f"""
          <tr data-ticker="{h['ticker']}" data-firstts="{h.get('first_iso','')}"
              data-first="{h['first_price']}" data-current="{cur}" data-change="{chg}"
              data-statusrank="{_STATUS_RANK.get(status, 0)}" data-tp="{h.get('tp_price',0)}"
              data-sl="{h.get('sl_price',0)}" data-lastts="{h.get('last_iso','')}">
            <td>{_tv(h['ticker'])}</td>
            <td>{h['first_price']:.2f}
                <span style="color:#94a3b8;font-size:12px;">{h.get('first_at','')}</span>
                <span style="background:{state_col};color:#fff;border-radius:5px;padding:1px 6px;
                    font-size:11px;margin-left:4px;">{h.get('first_state','')}</span></td>
            <td style="font-weight:600;">{cur:.2f}</td>
            <td style="color:{acol};font-weight:600;white-space:nowrap;">{arrow}&nbsp;{chg:+.2f}%</td>
            <td><span style="background:{scol};color:#fff;border-radius:6px;padding:2px 10px;
                font-size:12px;">{label}</span></td>
            <td style="color:#16a34a;">{h.get('tp_price',0):.2f}</td>
            <td style="color:#dc2626;">{h.get('sl_price',0):.2f}</td>
            <td style="color:#64748b;">{h.get('last_at','')}</td>
          </tr>""")
    def th(label, field, typ):
        return (f'<th onclick="sortHist(\'{field}\',\'{typ}\')" style="cursor:pointer;'
                f'user-select:none;white-space:nowrap;" title="Sort by {label}">'
                f'{label} <span style="color:#94a3b8;font-size:11px;">⇅</span></th>')
    header = "".join([
        th("Ticker", "ticker", "txt"), th("Triggered @ (first)", "firstts", "txt"),
        th("Current", "current", "num"), th("Change", "change", "num"),
        th("Status", "statusrank", "num"), th("TP +5%", "tp", "num"),
        th("SL -2%", "sl", "num"), th("Last seen", "lastts", "txt"),
    ])
    return f"""
      <div class="wrap">
      <table style="min-width:880px;">
        <thead><tr>{header}</tr></thead>
        <tbody id="histrows">{''.join(rows)}</tbody>
      </table>
      </div>"""


def build_html(results: list[TradeSetup], history: list[dict], scanned: int, state: str, cfg) -> str:
    ts = datetime.now().strftime("%A %d %B %Y, %H:%M")
    rr = round(cfg.risk.tp_pct / cfg.risk.sl_pct, 2)
    pos = cfg.risk.position_size
    n_hist = len(history)
    open_hist = sum(1 for h in history if h.get("status") == "OPEN")
    # When each ticker FIRST triggered, for the Current tab's Triggered column.
    first_seen = {h["ticker"]: (h.get("first_at", ""), h.get("first_iso", "")) for h in history}

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>High-Probability Swing Trade Scanner</title>{_STYLE}</head>
<body style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f8fafc;margin:0;padding:24px;">
  <div style="max-width:1060px;margin:auto;background:#fff;border-radius:12px;
              box-shadow:0 1px 4px rgba(0,0,0,.08);overflow:hidden;">
    <div style="background:#0f172a;color:#fff;padding:20px 24px;">
      <h1 style="margin:0;font-size:20px;">High-Probability Swing Trade Scanner</h1>
      <p style="margin:6px 0 0;color:#94a3b8;font-size:13px;">
        Generated {ts} - market state <b style="color:#fff;">{state}</b> -
        {scanned} tickers scanned - long-only - R:R 1:{rr} (TP +{cfg.risk.tp_pct*100:.0f}% /
        SL -{cfg.risk.sl_pct*100:.0f}%) - base {pos:.0f}/trade
      </p>
    </div>

    <div class="tabbar">
      <button id="btn-current" class="tab active" onclick="showTab('current')">Current setups ({len(results)})</button>
      <button id="btn-history" class="tab" onclick="showTab('history')">History ({n_hist} tracked - {open_hist} open)</button>
    </div>

    <div id="panel-current">
      {_current_controls()}
      {_current_table(results, first_seen, cfg)}
    </div>

    <div id="panel-history" style="display:none;">
      <p style="padding:16px 24px 4px;color:#64748b;font-size:13px;">
        First-triggered price vs current. <span style="color:#16a34a;">▲</span> green = up from
        trigger, <span style="color:#dc2626;">▼</span> red = down. Status turns to
        <b style="color:#16a34a;">TP hit</b> once +{cfg.risk.tp_pct*100:.0f}% was reached, or
        <b style="color:#dc2626;">SL hit</b> at -{cfg.risk.sl_pct*100:.0f}%.
      </p>
      {_history_table(history)}
    </div>

    <p style="padding:16px 24px;color:#94a3b8;font-size:12px;line-height:1.6;">
      <b>Score</b> = 0-100 signal-strength composite (ranking only). <b>Win%</b> = empirical rate at
      which the identical setup historically reached +{cfg.risk.tp_pct*100:.0f}% before
      -{cfg.risk.sl_pct*100:.0f}% within {cfg.backtest.hold_days} trading days, over <i>n</i> past
      occurrences (n/a = too few samples). Ticker names link to TradingView. A high score is
      <b>not</b> a guaranteed win rate. Educational technical screen only -
      <b>not financial advice</b>. Verify independently.
    </p>
  </div>
  {_SCRIPT}
  <script>showTab('current'); applyView();</script>
</body></html>"""


def write_html(html: str, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
