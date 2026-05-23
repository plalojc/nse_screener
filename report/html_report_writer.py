"""
report/html_report_writer.py
============================
Writes the final list of qualifying signals to an HTML report file.

Sorted by score descending (highest-conviction first).

Columns rendered:
  1. SL          - serial number
  2. Symbol      - clickable (opens TradingView NSE chart)
  3. Signal      - BREAKOUT / PULLBACK
  4. Stage       - Stage1 / Stage2 / Stage3
  5. Close (Rs.)  - today's closing price
  6. RSI         - RSI-14 (colour-coded)
  7. Vol          - volume ratio vs 20-day avg (colour-coded)
  8. ATR14       - average true range (volatility context)
  9. Near High % - % below 52-week high (lower = stronger positioning)
 10. Score       - multi-factor score (colour-coded)
 11. LLM Verdict - CONFIRM / WEAK / REJECT / SKIPPED (colour-coded)
 12. LLM Conf    - LLM confidence 0-10
 13. AI Reasoning - short reasoning text from LLM
"""

from __future__ import annotations

import os
from datetime import date
from html import escape
from pathlib import Path

from config import (
    REPORT_INCLUDE_REJECTED,
    REPORT_INCLUDE_SKIPPED,
    REPORT_INCLUDE_WEAK,
    REPORT_SIGNAL_TYPES,
)


# == HTML page templates =======================================================

_PAGE_HEAD = """\
<html>
<head>
    <meta charset="UTF-8">
    <title>NSE Breakout Report - {date}</title>
    <style>
        body  {{ font-family: Arial, sans-serif; font-size: 13px; margin: 16px; }}
        h2    {{ color: #2c3e50; }}
        p     {{ color: #555; margin-top: 0; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ccc; padding: 5px 8px; text-align: center; }}
        th    {{ background: #2c3e50; color: white; position: sticky; top: 0; }}
        tr:nth-child(even) {{ background: #f9f9f9; }}
        tr:hover {{ background: #DAF7A6; cursor: pointer; }}
        td.reason {{ text-align: left; font-size: 11px; color: #444; max-width: 300px; }}
        .news-detail-btn {{ border:1px solid #c0392b; background:#fff5f3; color:#922b21; border-radius:4px; padding:2px 6px; font-size:11px; cursor:pointer; margin-right:6px; }}
        .modal-backdrop {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.35); z-index:1000; }}
        .modal {{ display:none; position:fixed; left:50%; top:50%; transform:translate(-50%,-50%); width:min(680px,92vw); background:white; border-radius:6px; box-shadow:0 18px 60px rgba(0,0,0,.25); z-index:1001; }}
        .modal header {{ padding:12px 16px; border-bottom:1px solid #ddd; display:flex; justify-content:space-between; align-items:center; }}
        .modal h3 {{ margin:0; color:#2c3e50; }}
        .modal button.close {{ border:0; background:#eee; border-radius:4px; padding:4px 8px; cursor:pointer; }}
        .modal .body {{ padding:14px 16px; line-height:1.45; color:#333; }}
        .modal .label {{ font-weight:bold; color:#555; }}
        .modal a {{ color:#1f618d; }}
    </style>
    <script>
        function openChart(symbol) {{
            var url = "https://in.tradingview.com/chart/?symbol=NSE:" + symbol;
            var left = (screen.width  / 2) - 600;
            var top  = (screen.height / 2) - 300;
            window.open(url, symbol, "height=600,width=1200,top=" + top + ",left=" + left);
            return false;
        }}
        function showNewsDetail(id) {{
            document.getElementById("modal-backdrop").style.display = "block";
            document.getElementById(id).style.display = "block";
        }}
        function closeNewsDetail(id) {{
            document.getElementById("modal-backdrop").style.display = "none";
            document.getElementById(id).style.display = "none";
        }}
    </script>
</head>
<body>
    <div id="modal-backdrop" class="modal-backdrop"></div>
    <h2>&#x1F4C8; NSE EQ Breakout Report &ndash; {date}</h2>
    <p>
        {total} recommended signal(s) shown from {raw_total} candidate(s) &nbsp;|&nbsp;
        Recommended first by local rank + LLM confidence &nbsp;|&nbsp;
        Click any symbol to open TradingView chart.
    </p>
"""

_TABLE_HEAD = """\
    <h3>{title}</h3>
    <table>
        <thead>
            <tr>
                <th>SL</th>
                <th>Symbol</th>
                <th>Signal</th>
                <th>Stage</th>
                <th>Close (&#8377;)</th>
                <th>RSI</th>
                <th>Vol</th>
                <th>ATR14</th>
                <th>Near High %</th>
                <th>Score</th>
                <th>LLM Verdict</th>
                <th>LLM Conf</th>
                <th>AI Reasoning</th>
            </tr>
        </thead>
        <tbody>
"""

_TABLE_FOOT = """\
        </tbody>
    </table>
"""

_PAGE_FOOT = """\
</body>
</html>
"""


# == Report filters ========================================================

def _allowed_report_verdicts() -> set[str]:
    verdicts = {"CONFIRM"}
    if REPORT_INCLUDE_WEAK:
        verdicts.add("WEAK")
    if REPORT_INCLUDE_REJECTED:
        verdicts.add("REJECT")
    if REPORT_INCLUDE_SKIPPED:
        verdicts.add("SKIPPED")
    return verdicts


def _is_report_signal(sig: dict) -> bool:
    signal_type = str(sig.get("signal_type") or "").upper()
    verdict = str(sig.get("llm_verdict") or "SKIPPED").upper()
    if REPORT_SIGNAL_TYPES and signal_type not in REPORT_SIGNAL_TYPES:
        return False
    return verdict in _allowed_report_verdicts()


def _report_sort_key(sig: dict) -> tuple:
    verdict_rank = {"CONFIRM": 0, "WEAK": 1, "SKIPPED": 2, "REJECT": 3}
    verdict = str(sig.get("llm_verdict") or "SKIPPED").upper()
    score = sig.get("swing_score") or sig.get("score") or 0
    confidence = sig.get("llm_confidence") or 0
    risk = sig.get("entry_risk_pct") or 99
    extension = sig.get("ema20_extension_pct") or 99
    turnover = sig.get("turnover_cr") or 0
    return (
        verdict_rank.get(verdict, 9),
        -score,
        -confidence,
        risk,
        extension,
        -turnover,
    )

_ROW = (
    "            <tr>"
    "<td>{sl}</td>"
    "<td onclick=\"openChart('{sym}')\" style=\"cursor:pointer;font-weight:bold\">{sym}</td>"
    "<td bgcolor=\"{sig_c}\">{sig}</td>"
    "<td bgcolor=\"{stg_c}\">{stg}</td>"
    "<td>{close}</td>"
    "<td bgcolor=\"{rsi_c}\">{rsi}</td>"
    "<td bgcolor=\"{vol_c}\">{vol}</td>"
    "<td>{atr}</td>"
    "<td>{near_high}</td>"
    "<td bgcolor=\"{sc_c}\">{score}</td>"
    "<td bgcolor=\"{llm_c}\"><b>{llm_v}</b></td>"
    "<td>{llm_conf}</td>"
    "<td class=\"reason\">{reasoning}</td>"
    "</tr>\n"
)


# == Colour helpers ============================================================

def _signal_color(signal_type: str) -> str:
    return {
        "BREAKOUT": "#A9DFBF",
        "PULLBACK": "#AED6F1",
        "STAGE1": "#FDEBD0",
        "WATCHLIST": "#EBDEF0",
        "NEWS": "#FADBD8",
    }.get(signal_type, "#FFFFFF")

def _stage_color(stage: str) -> str:
    return {"Stage2": "#A9DFBF", "Stage1": "#FDEBD0", "Stage3": "#F5CBA7"}.get(stage, "#FFFFFF")

def _rsi_color(rsi: float) -> str:
    if rsi is None:   return "#FFFFFF"
    if rsi >= 70:     return "#F5B7B1"   # overbought - caution
    if rsi >= 55:     return "#A9DFBF"   # ideal momentum zone
    return "#FDEBD0"                      # below momentum threshold

def _vol_color(vol: float) -> str:
    if vol is None:   return "#FFFFFF"
    if vol >= 2.0:    return "#A9DFBF"   # strong surge
    if vol >= 1.5:    return "#FDFDA0"   # moderate
    return "#FDEBD0"                      # weak

def _score_color(score: int) -> str:
    if score >= 13:   return "#239B56"   # dark green - very high conviction
    if score >= 10:   return "#A9DFBF"   # green
    if score >= 7:    return "#FDFDA0"   # yellow - qualifies, less strong
    return "#FDEBD0"

def _llm_color(verdict: str | None) -> str:
    return {
        "CONFIRM": "#A9DFBF",
        "WEAK":    "#FDFDA0",
        "REJECT":  "#F5B7B1",
        "SKIPPED": "#D5D8DC",
    }.get(verdict or "SKIPPED", "#FFFFFF")


def _news_detail_cell(sig: dict, modal_id: str) -> tuple[str, str]:
    symbol = escape(str(sig.get("symbol") or "?"))
    category = escape(str(sig.get("catalyst_category") or "NEWS"))
    source = escape(str(sig.get("catalyst_source") or "Catalyst"))
    theme = escape(str(sig.get("catalyst_theme") or "-"))
    mapping_source = escape(str(sig.get("catalyst_mapping_source") or "-"))
    confidence = escape(str(sig.get("catalyst_confidence") or "-"))
    summary = escape(str(sig.get("catalyst_summary") or sig.get("reasons") or "-"))
    reasoning = escape(str(sig.get("llm_reasoning") or "-"))
    url = str(sig.get("catalyst_url") or "")
    url_html = f'<p><span class="label">Link:</span> <a href="{escape(url)}" target="_blank">Open source</a></p>' if url else ""
    cell = (
        f'<button class="news-detail-btn" onclick="showNewsDetail(\'{modal_id}\'); event.stopPropagation();">'
        f'Details</button>{summary[:90]}'
    )
    modal = (
        f'<div id="{modal_id}" class="modal">'
        f'<header><h3>{symbol} News Catalyst</h3>'
        f'<button class="close" onclick="closeNewsDetail(\'{modal_id}\')">Close</button></header>'
        f'<div class="body">'
        f'<p><span class="label">Category:</span> {category}</p>'
        f'<p><span class="label">Source:</span> {source}</p>'
        f'<p><span class="label">Theme map:</span> {theme} / {mapping_source} / confidence {confidence}</p>'
        f'<p><span class="label">Catalyst:</span> {summary}</p>'
        f'<p><span class="label">LLM view:</span> {reasoning}</p>'
        f'{url_html}'
        f'</div></div>\n'
    )
    return cell, modal


def _write_signal_table(fh, title: str, rows: list[dict]) -> None:
    if not rows:
        return
    fh.write(_TABLE_HEAD.format(title=escape(title)))
    modals = []
    for sl, s in enumerate(rows, 1):
        close = s.get("close")
        rsi = s.get("rsi")
        vol = s.get("vol_ratio")
        atr = s.get("atr14")
        score = s.get("score", 0)
        high_52w = s.get("high_52w")
        llm_v = s.get("llm_verdict") or "SKIPPED"
        llm_conf = s.get("llm_confidence")
        reasoning = escape((s.get("llm_reasoning") or s.get("catalyst_summary") or "")[:120] or "-")
        if str(s.get("signal_type") or "").upper() == "NEWS":
            reasoning, modal = _news_detail_cell(s, f"news-modal-{title.replace(' ', '-').lower()}-{sl}")
            modals.append(modal)

        if high_52w and close and high_52w > 0:
            near_high = f"{((high_52w - close) / high_52w * 100):.1f}%"
        else:
            near_high = "-"

        fh.write(_ROW.format(
            sl=sl,
            sym=escape(str(s.get("symbol", "?"))),
            sig=escape(str(s.get("signal_type", "?"))),
            sig_c=_signal_color(s.get("signal_type")),
            stg=escape(str(s.get("stage", "?"))),
            stg_c=_stage_color(s.get("stage")),
            close=f"{close:.2f}" if close is not None else "-",
            rsi=f"{rsi:.1f}" if rsi is not None else "-",
            rsi_c=_rsi_color(rsi),
            vol=f"{vol:.2f}x" if vol is not None else "-",
            vol_c=_vol_color(vol),
            atr=f"{atr:.2f}" if atr is not None else "-",
            near_high=near_high,
            score=score,
            sc_c=_score_color(score),
            llm_v=escape(str(llm_v)),
            llm_c=_llm_color(llm_v),
            llm_conf=f"{llm_conf}/10" if llm_conf is not None else "-",
            reasoning=reasoning,
        ))
    fh.write(_TABLE_FOOT)
    for modal in modals:
        fh.write(modal)


# == Public API ================================================================

def write(signals: list[dict], output_dir: str, scan_date: str | None = None) -> Path:
    """
    Render *signals* to an HTML file in *output_dir*.

    Parameters
    ----------
    signals    : list of signal dicts produced by the screener (after LLM enrichment)
    output_dir : directory path (created automatically if missing)
    scan_date  : optional YYYY-MM-DD string; today's date used when omitted

    Returns
    -------
    Path of the written HTML file.
    """
    report_date = scan_date or str(date.today())
    out_path    = Path(output_dir) / f"NSE-Breakout-{report_date}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    report_signals = [s for s in signals if _is_report_signal(s)]
    sorted_sigs = sorted(report_signals, key=_report_sort_key)
    technical_sigs = [s for s in sorted_sigs if str(s.get("signal_type") or "").upper() != "NEWS"]
    news_sigs = [s for s in sorted_sigs if str(s.get("signal_type") or "").upper() == "NEWS"]

    with open(out_path, "w", encoding="utf-8") as fh:
        # == Head ==============================================================
        fh.write(_PAGE_HEAD.format(
            date=report_date,
            total=len(sorted_sigs),
            raw_total=len(signals),
        ))
        _write_signal_table(fh, "Technical Analysis Shares", technical_sigs)
        _write_signal_table(fh, "News Driven Shares", news_sigs)
        fh.write(_PAGE_FOOT)

    return out_path
