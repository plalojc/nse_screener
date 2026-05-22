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
from pathlib import Path

from config import (
    ATR_SL_MULTIPLIER,
    STOP_LOSS_PCT,
    TOP_PICKS_COUNT,
    TOP_PICKS_MIN_SCORE,
    TOP_PICKS_MIN_VOL,
    TOP_PICKS_RSI_MAX,
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
        /* == Top Picks == */
        .top-picks {{ background:#f0fdf4; border:2px solid #27ae60; border-radius:8px; padding:14px 18px; margin-bottom:20px; }}
        .top-picks h3 {{ margin:0 0 4px 0; color:#1a6e36; font-size:15px; }}
        .top-picks .subtitle {{ margin:0 0 12px 0; color:#555; font-size:12px; }}
        .picks-grid {{ display:flex; flex-wrap:wrap; gap:12px; }}
        .pick-card {{ background:#fff; border:1px solid #a9dfbf; border-radius:6px; padding:10px 14px; min-width:260px; flex:1 1 260px; max-width:380px; }}
        .pick-header {{ display:flex; align-items:baseline; gap:8px; margin-bottom:4px; }}
        .pick-rank {{ font-size:16px; font-weight:bold; color:#27ae60; }}
        .pick-sym {{ font-size:15px; font-weight:bold; color:#2c3e50; cursor:pointer; text-decoration:underline dotted; }}
        .pick-price {{ font-size:13px; color:#555; }}
        .pick-verdict {{ margin-left:auto; font-size:12px; font-weight:bold; background:#27ae60; color:#fff; padding:2px 6px; border-radius:3px; white-space:nowrap; }}
        .pick-verdict.weak {{ background:#e67e22; }}
        .pick-setup {{ font-size:12px; margin:4px 0; color:#333; }}
        .pick-meta {{ font-size:11px; color:#666; margin:2px 0; }}
        .pick-reason {{ font-size:11px; color:#444; font-style:italic; margin-top:5px; border-top:1px solid #eee; padding-top:4px; }}
        .no-picks {{ color:#888; font-style:italic; font-size:13px; }}
    </style>
    <script>
        function openChart(symbol) {{
            var url = "https://in.tradingview.com/chart/?symbol=NSE:" + symbol;
            var left = (screen.width  / 2) - 600;
            var top  = (screen.height / 2) - 300;
            window.open(url, symbol, "height=600,width=1200,top=" + top + ",left=" + left);
            return false;
        }}
    </script>
</head>
<body>
    <h2>&#x1F4C8; NSE EQ Breakout Report &ndash; {date}</h2>
    <p>
        {total} signals &nbsp;|&nbsp;
        Sorted by Score descending &nbsp;|&nbsp;
        Click any symbol to open TradingView chart.
    </p>
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

_PAGE_FOOT = """\
        </tbody>
    </table>
</body>
</html>
"""


# == Top Picks helpers =====================================================

def _compute_sl_tp(sig: dict) -> tuple[float, float, float]:
    """Return (sl, tp, risk_pct) using ATR-based or swing-low or fallback SL."""
    close     = sig.get("close") or 0
    atr       = sig.get("atr14") or 0
    swing_low = sig.get("swing_low") or 0
    sl_atr    = round(close - ATR_SL_MULTIPLIER * atr, 2) if atr > 0 else None
    sl_swing  = round(swing_low * 0.99, 2) if swing_low else None
    cands     = [x for x in [sl_atr, sl_swing] if x is not None and x < close]
    sl        = max(cands) if cands else round(close * (1 - STOP_LOSS_PCT / 100), 2)
    risk      = close - sl
    tp        = round(close + risk * 2, 2)
    risk_pct  = round(risk / close * 100, 1) if close else 0
    return sl, tp, risk_pct


def _build_top_picks_html(signals: list, scan_date: str) -> str:
    """Return the Top Picks <div> block as an HTML string."""
    # Primary: Stage2 + CONFIRM + hard criteria
    picks = [
        s for s in signals
        if s.get("stage") == "Stage2"
        and s.get("llm_verdict") == "CONFIRM"
        and s.get("score", 0)     >= TOP_PICKS_MIN_SCORE
        and s.get("vol_ratio", 0) >= TOP_PICKS_MIN_VOL
        and s.get("rsi", 99)      <= TOP_PICKS_RSI_MAX
    ]
    # Fallback: relax to WEAK
    if not picks:
        picks = [
            s for s in signals
            if s.get("stage") == "Stage2"
            and s.get("llm_verdict") in ("CONFIRM", "WEAK")
            and s.get("score", 0)     >= TOP_PICKS_MIN_SCORE
            and s.get("vol_ratio", 0) >= TOP_PICKS_MIN_VOL
            and s.get("rsi", 99)      <= TOP_PICKS_RSI_MAX
        ]
    picks.sort(key=lambda x: (-(x.get("llm_confidence") or 0), -x.get("score", 0)))
    picks = picks[:TOP_PICKS_COUNT]

    verdict_label = "CONFIRM" if any(p.get("llm_verdict") == "CONFIRM" for p in picks) else "CONFIRM/WEAK"
    html = (
        f'    <div class="top-picks">\n'
        f'        <h3>&#9733; TODAY&#8217;S TOP PICKS &mdash; {scan_date}</h3>\n'
        f'        <p class="subtitle">Stage2 | LLM {verdict_label} | '
        f'Score&ge;{TOP_PICKS_MIN_SCORE} | Vol&ge;{TOP_PICKS_MIN_VOL}x | RSI&le;{TOP_PICKS_RSI_MAX}</p>\n'
    )

    if not picks:
        html += '        <p class="no-picks">No picks met all criteria today. Check WEAK signals in the table below.</p>\n'
        html += '    </div>\n'
        return html

    html += '        <div class="picks-grid">\n'
    for rank, s in enumerate(picks, 1):
        sym      = s.get("symbol", "?")
        close    = s.get("close") or 0
        score    = s.get("score", 0)
        rsi      = s.get("rsi")
        vol      = s.get("vol_ratio")
        conf     = s.get("llm_confidence")
        verdict  = s.get("llm_verdict", "WEAK")
        reason   = (s.get("llm_reasoning") or "")[:160]
        sl, tp, risk_pct = _compute_sl_tp(s)

        rsi_str  = f"{rsi:.0f}"  if rsi  is not None else "-"
        vol_str  = f"{vol:.1f}x" if vol  is not None else "-"
        conf_str = f"{conf}/10"  if conf is not None else "?"
        v_class  = "" if verdict == "CONFIRM" else " weak"

        html += (
            f'            <div class="pick-card">\n'
            f'                <div class="pick-header">\n'
            f'                    <span class="pick-rank">#{rank}</span>\n'
            f'                    <span class="pick-sym" onclick="openChart(\'{sym}\')">'
            f'{sym}</span>\n'
            f'                    <span class="pick-price">&nbsp;&#8377;{close:.2f}</span>\n'
            f'                    <span class="pick-verdict{v_class}">{verdict} ({conf_str})</span>\n'
            f'                </div>\n'
            f'                <div class="pick-meta">Score: {score} &nbsp;|&nbsp; RSI: {rsi_str} &nbsp;|&nbsp; Vol: {vol_str}</div>\n'
            f'                <div class="pick-setup">'
            f'Entry &#8377;{close:.2f} &rarr; Target &#8377;{tp:.2f} &rarr; SL &#8377;{sl:.2f} '
            f'(Risk {risk_pct}% | 2R reward)</div>\n'
            f'                <div class="pick-reason">{reason}</div>\n'
            f'            </div>\n'
        )

    html += '        </div>\n    </div>\n'
    return html

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
    return {"BREAKOUT": "#A9DFBF", "PULLBACK": "#AED6F1"}.get(signal_type, "#FFFFFF")

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

    # Sort by score DESC, then LLM confidence DESC
    sorted_sigs = sorted(
        signals,
        key=lambda s: (-(s.get("score") or 0), -(s.get("llm_confidence") or 0))
    )

    with open(out_path, "w", encoding="utf-8") as fh:
        # == Head ==============================================================
        fh.write(_PAGE_HEAD.format(date=report_date, total=len(sorted_sigs)))
        # == Top Picks banner ================================================
        fh.write(_build_top_picks_html(sorted_sigs, report_date))
        # == Rows ==============================================================
        for sl, s in enumerate(sorted_sigs, 1):
            close    = s.get("close")
            rsi      = s.get("rsi")
            vol      = s.get("vol_ratio")
            atr      = s.get("atr14")
            score    = s.get("score", 0)
            high_52w = s.get("high_52w")
            llm_v    = s.get("llm_verdict") or "SKIPPED"
            llm_conf = s.get("llm_confidence")
            reasoning = (s.get("llm_reasoning") or "")[:120]

            # Near High % = how far below the 52-week high (lower = more extended)
            if high_52w and close and high_52w > 0:
                near_high = f"{((high_52w - close) / high_52w * 100):.1f}%"
            else:
                near_high = "-"

            fh.write(_ROW.format(
                sl        = sl,
                sym       = s.get("symbol", "?"),
                sig       = s.get("signal_type", "?"),
                sig_c     = _signal_color(s.get("signal_type")),
                stg       = s.get("stage", "?"),
                stg_c     = _stage_color(s.get("stage")),
                close     = f"{close:.2f}" if close is not None else "-",
                rsi       = f"{rsi:.1f}"   if rsi   is not None else "-",
                rsi_c     = _rsi_color(rsi),
                vol       = f"{vol:.2f}x"  if vol   is not None else "-",
                vol_c     = _vol_color(vol),
                atr       = f"{atr:.2f}"   if atr   is not None else "-",
                near_high = near_high,
                score     = score,
                sc_c      = _score_color(score),
                llm_v     = llm_v,
                llm_c     = _llm_color(llm_v),
                llm_conf  = f"{llm_conf}/10" if llm_conf is not None else "-",
                reasoning = reasoning or "-",
            ))

        # == Foot ==============================================================
        fh.write(_PAGE_FOOT)

    return out_path
