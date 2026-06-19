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
  9. Score       - multi-factor score (colour-coded)
 10. LLM Verdict - CONFIRM / WEAK / REJECT / SKIPPED (colour-coded)
 11. LLM Conf    - LLM confidence 0-10
 12. AI Reasoning - short reasoning text from LLM
"""

from __future__ import annotations

import os
from datetime import date
from html import escape
from io import StringIO
from pathlib import Path

from config import (
    REPORT_INCLUDE_REJECTED,
    REPORT_INCLUDE_SKIPPED,
    REPORT_INCLUDE_WEAK,
    REPORT_SIGNAL_TYPES,
    TRADINGVIEW_CHART_ID,
)


# == HTML page templates =======================================================

_PAGE_HEAD = """\
<html>
<head>
    <meta charset="UTF-8">
    <title>NSE Breakout Report - {date}</title>
    <style>
        html, body {{ max-width:100%; overflow-x:hidden; }}
        body  {{ font-family: Arial, sans-serif; font-size: 12px; margin: 14px; color:#182230; background:#f8fafc; }}
        h2    {{ color: #26364a; font-size:20px; margin:0 0 14px; }}
        h3    {{ color:#111827; font-size:16px; margin:14px 0 10px; }}
        p     {{ color: #4b5563; margin-top: 0; }}
        table {{ border-collapse: collapse; width: 100%; background:white; box-shadow:0 1px 2px rgba(15,23,42,.06); }}
        th, td {{ border: 1px solid #d7dde5; padding: 5px 7px; text-align: center; line-height:1.25; }}
        th    {{ background: #2f3d4f; color: white; position: sticky; top: 0; font-size:12px; font-weight:700; }}
        td    {{ font-size:12px; }}
        tr:nth-child(even) {{ background: #fbfcfe; }}
        tr:hover {{ background: #eef8f3; cursor: pointer; }}
        td.symbol {{ font-weight:700; letter-spacing:0; }}
        td.reason {{ text-align: left; color: #3f4a5a; max-width: 260px; position:relative; }}
        .reasonPreview {{ display:block; max-width:250px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
        .reasonFull {{ display:none; position:fixed; right:16px; bottom:16px; z-index:20; width:min(420px, calc(100vw - 32px)); background:#111827; color:white; border-radius:4px; padding:9px 10px; box-shadow:0 10px 28px rgba(0,0,0,.25); line-height:1.35; text-align:left; }}
        td.reason:hover .reasonFull {{ display:block; }}
        td.newsReason:hover .reasonFull {{ display:none; }}
        .newsSummary {{ align-items:center; color:#7c2d12; cursor:pointer; display:flex; gap:7px; max-width:250px; min-height:22px; text-decoration:none; }}
        .newsSummary:hover .newsText {{ color:#9a3412; text-decoration:underline; }}
        .newsPill {{ background:#fff1e8; border:1px solid #fed7aa; border-radius:999px; color:#9a3412; flex:0 0 auto; font-size:10px; font-weight:700; padding:2px 6px; text-transform:uppercase; }}
        .newsText {{ display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
        td.slCell {{ min-width:48px; position:relative; width:52px; }}
        .slNo {{ display:inline-block; }}
        .watch-btn {{ align-items:center; background:#1f6f54; border:1px solid #145c42; border-radius:50%; color:white; cursor:pointer; display:none; font-size:16px; font-weight:700; height:24px; justify-content:center; left:50%; line-height:20px; padding:0; position:absolute; top:50%; transform:translate(-50%,-50%); width:24px; }}
        tr:hover .slCell .slNo {{ display:none; }}
        tr:hover .slCell .watch-btn {{ display:inline-flex; }}
        .watch-btn.added {{ background:#145c42; font-size:11px; width:42px; border-radius:12px; }}
        .modal-backdrop {{ display:none; position:fixed; inset:0; background:rgba(15,23,42,.48); z-index:1000; }}
        .modal {{ display:none; position:fixed; left:50%; top:50%; transform:translate(-50%,-50%); width:min(720px,92vw); max-height:82vh; overflow:hidden; background:white; border-radius:8px; box-shadow:0 24px 70px rgba(15,23,42,.34); z-index:1001; }}
        .modal header {{ background:#f8fafc; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:flex-start; gap:14px; padding:16px 18px; }}
        .modal h3 {{ margin:0; color:#17212f; font-size:17px; }}
        .modal .subtitle {{ color:#64748b; font-size:12px; margin-top:4px; }}
        .modal button.close {{ background:white; border:1px solid #cbd5e1; border-radius:4px; color:#334155; cursor:pointer; padding:5px 10px; }}
        .modal .body {{ color:#334155; line-height:1.5; max-height:calc(82vh - 74px); overflow:auto; padding:16px 18px 18px; }}
        .modalGrid {{ display:grid; gap:10px; grid-template-columns:repeat(3, minmax(0, 1fr)); margin-bottom:14px; }}
        .modalInfo {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:9px 10px; }}
        .modalInfo span {{ color:#64748b; display:block; font-size:11px; margin-bottom:3px; }}
        .modalInfo strong {{ color:#17212f; font-size:12px; }}
        .modalBlock {{ border-top:1px solid #e2e8f0; padding-top:12px; margin-top:12px; }}
        .modalBlock .label {{ color:#17212f; display:block; font-weight:700; margin-bottom:4px; }}
        .modal a {{ color:#1f6f54; font-weight:700; }}
        @media (max-width:900px) {{
            body {{ font-size:11px; margin:8px; }}
            h2 {{ font-size:17px; }}
            h3 {{ font-size:14px; }}
            p {{ font-size:11px; line-height:1.35; }}
            table {{ table-layout:fixed; }}
            th, td {{ font-size:11px; padding:4px 5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
            .modalGrid {{ grid-template-columns:1fr; }}
            table th:nth-child(8), table td:nth-child(8),
            table th:nth-child(11), table td:nth-child(11),
            table th:nth-child(12), table td:nth-child(12) {{ display:none; }}
            table th:nth-child(1), table td:nth-child(1) {{ width:26px; }}
            table th:nth-child(2), table td:nth-child(2) {{ width:30%; }}
            table th:nth-child(5), table td:nth-child(5) {{ width:72px; }}
            table th:nth-child(9), table td:nth-child(9) {{ width:48px; }}
            table th:nth-child(10), table td:nth-child(10) {{ width:86px; }}
            td.slCell {{ min-width:26px; width:26px; }}
            td.slCell .slNo {{ font-size:10px; }}
            .watch-btn {{ height:20px; width:20px; font-size:13px; }}
        }}
        @media (max-width:520px) {{
            body {{ margin:6px; }}
            table th:nth-child(3), table td:nth-child(3),
            table th:nth-child(4), table td:nth-child(4),
            table th:nth-child(6), table td:nth-child(6),
            table th:nth-child(7), table td:nth-child(7) {{ display:none; }}
            table th:nth-child(1), table td:nth-child(1) {{ width:24px; }}
            table th:nth-child(2), table td:nth-child(2) {{ width:31%; }}
            table th:nth-child(5), table td:nth-child(5) {{ width:70px; }}
            table th:nth-child(9), table td:nth-child(9) {{ width:46px; }}
            table th:nth-child(10), table td:nth-child(10) {{ width:82px; }}
            th, td {{ font-size:10.5px; padding:4px 3px; }}
            td.slCell {{ min-width:24px; width:24px; }}
            td.slCell .slNo {{ font-size:10px; }}
            .watch-btn {{ height:18px; width:18px; font-size:12px; }}
        }}
    </style>
    <script>
        function openChart(symbol) {{
            var base = "{tradingview_base}";
            var url = base + "?symbol=NSE:" + symbol;
            var left = (screen.width  / 2) - 600;
            var top  = (screen.height / 2) - 300;
            window.open(url, symbol, "height=600,width=1200,top=" + top + ",left=" + left);
            return false;
        }}
        var activeNewsModal = null;
        function showNewsDetail(id) {{
            document.getElementById("modal-backdrop").style.display = "block";
            document.getElementById(id).style.display = "block";
            activeNewsModal = id;
        }}
        function closeNewsDetail(id) {{
            var target = id || activeNewsModal;
            document.getElementById("modal-backdrop").style.display = "none";
            if (target) {{
                document.getElementById(target).style.display = "none";
            }}
            activeNewsModal = null;
        }}
        async function addToWatchlist(symbol, button) {{
            try {{
                var token = new URLSearchParams(window.location.search).get("token") || "";
                var response = await fetch("/api/watchlist", {{
                    method: "POST",
                    headers: {{
                        "Content-Type": "application/json",
                        "Authorization": token ? "Bearer " + token : ""
                    }},
                    body: JSON.stringify({{
                        symbol: symbol,
                        notes: "Added from report {date}",
                        target_price: null
                    }})
                }});
                var payload = await response.json();
                button.classList.add("added");
                button.textContent = payload && payload.created === false ? "Exists" : "Added";
            }} catch (err) {{
                button.textContent = "Failed";
            }}
        }}
    </script>
</head>
<body>
    <div id="modal-backdrop" class="modal-backdrop" onclick="closeNewsDetail()"></div>
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

def _allowed_report_verdicts(include_weak: bool | None = None) -> set[str]:
    verdicts = {"CONFIRM"}
    if REPORT_INCLUDE_WEAK if include_weak is None else include_weak:
        verdicts.add("WEAK")
    if REPORT_INCLUDE_REJECTED:
        verdicts.add("REJECT")
    if REPORT_INCLUDE_SKIPPED:
        verdicts.add("SKIPPED")
    return verdicts


def _is_report_signal(sig: dict, include_weak: bool | None = None) -> bool:
    signal_type = str(sig.get("signal_type") or "").upper()
    verdict = str(sig.get("llm_verdict") or "SKIPPED").upper()
    if REPORT_SIGNAL_TYPES and signal_type not in REPORT_SIGNAL_TYPES:
        return False
    return verdict in _allowed_report_verdicts(include_weak)


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
    "<td class=\"slCell\"><span class=\"slNo\">{sl}</span><button class=\"watch-btn\" title=\"Add {sym} to watchlist\" onclick=\"addToWatchlist('{sym}', this); event.stopPropagation();\">+</button></td>"
    "<td class=\"symbol\" onclick=\"openChart('{sym}')\" style=\"cursor:pointer\">{sym}</td>"
    "<td bgcolor=\"{sig_c}\">{sig}</td>"
    "<td bgcolor=\"{stg_c}\">{stg}</td>"
    "<td>{close}</td>"
    "<td bgcolor=\"{rsi_c}\">{rsi}</td>"
    "<td bgcolor=\"{vol_c}\">{vol}</td>"
    "<td>{atr}</td>"
    "<td bgcolor=\"{sc_c}\">{score}</td>"
    "<td bgcolor=\"{llm_c}\"><b>{llm_v}</b></td>"
    "<td>{llm_conf}</td>"
    "<td class=\"reason {reason_class}\"><span class=\"reasonPreview\">{reasoning_preview}</span><span class=\"reasonFull\">{reasoning_full}</span></td>"
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
    theme_raw = str(sig.get("catalyst_theme") or "").strip()
    mapping_raw = str(sig.get("catalyst_mapping_source") or "").strip()
    confidence_raw = str(sig.get("catalyst_confidence") or "").strip()
    theme = escape(theme_raw or "-")
    mapping_source = escape(mapping_raw or "-")
    confidence = escape(confidence_raw or "-")
    summary_raw = str(sig.get("catalyst_summary") or sig.get("reasons") or "-")
    reasoning_raw = str(sig.get("llm_reasoning") or "-")
    summary = escape(summary_raw)
    reasoning = escape(reasoning_raw)
    url = str(sig.get("catalyst_url") or "")
    url_html = f'<div class="modalBlock"><span class="label">Source link</span><a href="{escape(url)}" target="_blank">Open original catalyst</a></div>' if url else ""
    cell = (
        f'<span class="newsSummary" role="button" tabindex="0" title="Open catalyst details" '
        f'onclick="showNewsDetail(\'{modal_id}\'); event.stopPropagation();" '
        f'onkeydown="if(event.key===\'Enter\'||event.key===\' \'){{showNewsDetail(\'{modal_id}\'); event.stopPropagation(); event.preventDefault();}}">'
        f'<span class="newsPill">News</span><span class="newsText">{escape(_short_reason(summary_raw, 86))}</span></span>'
    )
    modal = (
        f'<div id="{modal_id}" class="modal">'
        f'<header><div><h3>{symbol} News Catalyst</h3>'
        f'<div class="subtitle">{escape(_short_reason(summary_raw, 110))}</div></div>'
        f'<button class="close" onclick="closeNewsDetail(\'{modal_id}\')">Close</button></header>'
        f'<div class="body">'
        f'<div class="modalGrid">'
        f'<div class="modalInfo"><span>Category</span><strong>{category}</strong></div>'
        f'<div class="modalInfo"><span>Source</span><strong>{source}</strong></div>'
        f'<div class="modalInfo"><span>Mapping confidence</span><strong>{confidence}</strong></div>'
        f'</div>'
        f'<div class="modalGrid">'
        f'<div class="modalInfo"><span>Theme</span><strong>{theme}</strong></div>'
        f'<div class="modalInfo"><span>Mapping source</span><strong>{mapping_source}</strong></div>'
        f'<div class="modalInfo"><span>Signal type</span><strong>News driven</strong></div>'
        f'</div>'
        f'<div class="modalBlock"><span class="label">Catalyst</span>{summary}</div>'
        f'<div class="modalBlock"><span class="label">AI view</span>{reasoning}</div>'
        f'{url_html}'
        f'</div></div>\n'
    )
    return cell, modal


def _short_reason(text: str, limit: int = 76) -> str:
    clean = " ".join(str(text or "-").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "..."


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
        llm_v = s.get("llm_verdict") or "SKIPPED"
        llm_conf = s.get("llm_confidence")
        full_reasoning_text = s.get("llm_reasoning") or s.get("catalyst_summary") or "-"
        reasoning_preview = escape(_short_reason(full_reasoning_text))
        reasoning_full = escape(str(full_reasoning_text or "-"))
        reason_class = ""
        if str(s.get("signal_type") or "").upper() == "NEWS":
            reasoning, modal = _news_detail_cell(s, f"news-modal-{title.replace(' ', '-').lower()}-{sl}")
            modals.append(modal)
            reasoning_preview = reasoning
            reasoning_full = escape(str(s.get("llm_reasoning") or s.get("catalyst_summary") or "-"))
            reason_class = "newsReason"

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
            score=score,
            sc_c=_score_color(score),
            llm_v=escape(str(llm_v)),
            llm_c=_llm_color(llm_v),
            llm_conf=f"{llm_conf}/10" if llm_conf is not None else "-",
            reason_class=reason_class,
            reasoning_preview=reasoning_preview,
            reasoning_full=reasoning_full,
        ))
    fh.write(_TABLE_FOOT)
    for modal in modals:
        fh.write(modal)


# == Public API ================================================================

def _tradingview_base(chart_id: str | None) -> str:
    clean = "".join(ch for ch in str(chart_id or "").strip() if ch.isalnum() or ch in {"_", "-"})
    if not clean:
        return "https://in.tradingview.com/chart/"
    return f"https://in.tradingview.com/chart/{clean}/"


def render(
    signals: list[dict],
    scan_date: str | None = None,
    raw_total: int | None = None,
    tradingview_chart_id: str | None = None,
    include_weak: bool | None = None,
) -> str:
    """Render signals to an HTML string."""
    report_date = scan_date or str(date.today())
    report_signals = [s for s in signals if _is_report_signal(s, include_weak)]
    sorted_sigs = sorted(report_signals, key=_report_sort_key)
    technical_sigs = [s for s in sorted_sigs if str(s.get("signal_type") or "").upper() != "NEWS"]
    news_sigs = [s for s in sorted_sigs if str(s.get("signal_type") or "").upper() == "NEWS"]

    fh = StringIO()
    fh.write(_PAGE_HEAD.format(
        date=report_date,
        total=len(sorted_sigs),
        raw_total=raw_total if raw_total is not None else len(signals),
        tradingview_base=_tradingview_base(tradingview_chart_id or TRADINGVIEW_CHART_ID),
    ))
    _write_signal_table(fh, "Technical Analysis Shares", technical_sigs)
    _write_signal_table(fh, "News Driven Shares", news_sigs)
    fh.write(_PAGE_FOOT)
    return fh.getvalue()


def write(signals: list[dict], output_dir: str, scan_date: str | None = None) -> Path:
    """Render signals to an HTML file. Kept for manual/export use only."""
    report_date = scan_date or str(date.today())
    out_path = Path(output_dir) / f"NSE-Breakout-{report_date}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(signals, report_date), encoding="utf-8")

    return out_path
