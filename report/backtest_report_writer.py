"""
report/backtest_report_writer.py
=================================
Writes backtest validation results to an HTML file.

The report contains:
  1. A summary box  - win rate, total signals, avg gain/loss, expectancy
  2. A full results table sorted by outcome (WIN -> OPEN -> LOSS), then max_gain_pct desc
"""

from __future__ import annotations

from pathlib import Path


# == HTML page templates =======================================================

_PAGE_HEAD = """\
<html>
<head>
    <meta charset="UTF-8">
    <title>Backtest Validation - {signal_date}</title>
    <style>
        body  {{ font-family: Arial, sans-serif; font-size: 13px; margin: 20px; background:#f4f6f8; }}
        h2    {{ color: #2c3e50; margin-bottom: 4px; }}
        p.sub {{ color: #666; margin-top: 0; font-size: 12px; }}

        /* == Summary box ============================================= */
        .summary {{
            display: flex; flex-wrap: wrap; gap: 12px;
            margin: 16px 0;
        }}
        .card {{
            background: white; border-radius: 8px;
            border: 1px solid #ddd; padding: 12px 20px;
            min-width: 130px; text-align: center;
            box-shadow: 0 1px 4px rgba(0,0,0,.06);
        }}
        .card .val {{ font-size: 26px; font-weight: bold; margin:4px 0; }}
        .card .lbl {{ font-size: 11px; color: #888; text-transform: uppercase; }}
        .win  {{ color: #27ae60; }}
        .loss {{ color: #e74c3c; }}
        .open {{ color: #2980b9; }}
        .neutral {{ color: #555; }}

        /* == Table =================================================== */
        table {{ border-collapse: collapse; width: 100%; background: white;
                 border-radius: 8px; overflow: hidden;
                 box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
        th, td {{ border: 1px solid #e0e0e0; padding: 5px 8px; text-align: center; }}
        th     {{ background: #2c3e50; color: white; position: sticky; top: 0; font-size:12px; }}
        tr:hover {{ background: #eaf6fb; cursor: pointer; }}
        td.sym {{ font-weight: bold; cursor: pointer; }}
        td.reason {{ text-align: left; font-size: 11px; color: #444; max-width: 220px;
                     overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    </style>
    <script>
        function openChart(symbol) {{
            var url = "https://in.tradingview.com/chart/?symbol=NSE:" + symbol;
            window.open(url, symbol, "height=600,width=1200");
            return false;
        }}
    </script>
</head>
<body>
    <h2>&#x1F50D; Backtest Validation Report &ndash; Signal Date: {signal_date}</h2>
    <p class="sub">
        Forward window: <b>{forward_days} calendar days</b> after signal date &nbsp;|&nbsp;
        Outcome: <b>WIN</b> = 2R target hit first &nbsp;|&nbsp;
        <b>LOSS</b> = stop loss hit first &nbsp;|&nbsp;
        <b>OPEN</b> = neither triggered in window
    </p>

    <!-- SUMMARY CARDS -->
    <div class="summary">
        <div class="card">
            <div class="val neutral">{total}</div>
            <div class="lbl">Total Signals</div>
        </div>
        <div class="card">
            <div class="val win">{wins}</div>
            <div class="lbl">&#x2705; WIN</div>
        </div>
        <div class="card">
            <div class="val loss">{losses}</div>
            <div class="lbl">&#x274C; LOSS</div>
        </div>
        <div class="card">
            <div class="val open">{opens}</div>
            <div class="lbl">&#x23F3; OPEN</div>
        </div>
        <div class="card">
            <div class="val {wr_class}">{win_rate}%</div>
            <div class="lbl">Win Rate</div>
        </div>
        <div class="card">
            <div class="val win">+{avg_win}%</div>
            <div class="lbl">Avg Max Gain (wins)</div>
        </div>
        <div class="card">
            <div class="val loss">{avg_loss}%</div>
            <div class="lbl">Avg Max DD (losses)</div>
        </div>
        <div class="card">
            <div class="val {exp_class}">{expectancy}%</div>
            <div class="lbl">Expectancy</div>
        </div>
        <div class="card">
            <div class="val neutral">{avg_days}</div>
            <div class="lbl">Avg Days to Outcome</div>
        </div>
    </div>

    <!-- RESULTS TABLE -->
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Symbol</th>
                <th>Signal</th>
                <th>Stage</th>
                <th>Entry (&#8377;)</th>
                <th>Target (&#8377;)</th>
                <th>SL (&#8377;)</th>
                <th>RSI</th>
                <th>Vol</th>
                <th>Score</th>
                <th>Outcome</th>
                <th>Day</th>
                <th>Max Gain %</th>
                <th>Max DD %</th>
                <th>Final %</th>
                <th>Fwd Candles</th>
                <th>Reasons</th>
            </tr>
        </thead>
        <tbody>
"""

_PAGE_FOOT = """\
        </tbody>
    </table>
    <p class="sub" style="margin-top:12px;">
        Generated by NSE Breakout Agent &nbsp;|&nbsp;
        All outcomes determined from cached local OHLCV data only &nbsp;|&nbsp;
        Past performance does not guarantee future results.
    </p>
</body>
</html>
"""

_ROW = (
    "            <tr>"
    "<td>{sl}</td>"
    "<td class=\"sym\" onclick=\"openChart('{sym}')\">{sym}</td>"
    "<td bgcolor=\"{sig_c}\">{sig}</td>"
    "<td bgcolor=\"{stg_c}\">{stg}</td>"
    "<td>&#8377;{entry:.2f}</td>"
    "<td>&#8377;{tp:.2f}</td>"
    "<td>&#8377;{stop:.2f}</td>"
    "<td bgcolor=\"{rsi_c}\">{rsi}</td>"
    "<td bgcolor=\"{vol_c}\">{vol}x</td>"
    "<td bgcolor=\"{sc_c}\">{score}</td>"
    "<td bgcolor=\"{out_c}\"><b>{outcome}</b></td>"
    "<td>{day}</td>"
    "<td bgcolor=\"{mg_c}\">{max_gain:+.2f}%</td>"
    "<td bgcolor=\"{dd_c}\">{max_dd:+.2f}%</td>"
    "<td bgcolor=\"{fp_c}\">{final_pct:+.2f}%</td>"
    "<td>{fwd}</td>"
    "<td class=\"reason\">{reasons}</td>"
    "</tr>\n"
)

# == Colour helpers ============================================================

def _signal_color(v):  return {"BREAKOUT":"#A9DFBF","PULLBACK":"#AED6F1"}.get(v,"#FFF")
def _stage_color(v):   return {"Stage2":"#A9DFBF","Stage1":"#FDEBD0","Stage3":"#F5CBA7"}.get(v,"#FFF")
def _rsi_color(v):
    if v is None: return "#FFF"
    if v >= 70:   return "#F5B7B1"
    if v >= 55:   return "#A9DFBF"
    return "#FDEBD0"
def _vol_color(v):
    if v is None: return "#FFF"
    if v >= 2.0:  return "#A9DFBF"
    if v >= 1.5:  return "#FDFDA0"
    return "#FDEBD0"
def _score_color(v):
    if v >= 13: return "#239B56"
    if v >= 10: return "#A9DFBF"
    if v >= 7:  return "#FDFDA0"
    return "#FDEBD0"
def _outcome_color(v): return {"WIN":"#A9DFBF","LOSS":"#F5B7B1","OPEN":"#AED6F1"}.get(v,"#FFF")
def _pct_color(v):
    if v is None:  return "#FFF"
    if v > 3:      return "#A9DFBF"
    if v < -2:     return "#F5B7B1"
    return "#FFF"


# == Summary helpers ===========================================================

def _compute_summary(results: list[dict]) -> dict:
    total  = len(results)
    wins   = [r for r in results if r["outcome"] == "WIN"]
    losses = [r for r in results if r["outcome"] == "LOSS"]
    opens  = [r for r in results if r["outcome"] == "OPEN"]

    win_rate = round(len(wins) / total * 100, 1) if total else 0.0
    avg_win  = round(sum(r["max_gain_pct"] for r in wins)   / len(wins),  2) if wins   else 0.0
    avg_loss = round(sum(r["max_dd_pct"]  for r in losses)  / len(losses), 2) if losses else 0.0

    # Simple expectancy: (win_rate * avg_win) + ((1-win_rate) * avg_loss)
    wr = win_rate / 100
    expectancy = round(wr * avg_win + (1 - wr) * avg_loss, 2)

    # Average days to outcome (wins + losses only)
    decided = [r for r in results if r["outcome_day"] is not None]
    avg_days = round(sum(r["outcome_day"] for r in decided) / len(decided), 1) if decided else "-"

    return {
        "total":      total,
        "wins":       len(wins),
        "losses":     len(losses),
        "opens":      len(opens),
        "win_rate":   win_rate,
        "avg_win":    avg_win,
        "avg_loss":   avg_loss,
        "expectancy": expectancy,
        "avg_days":   avg_days,
        "wr_class":   "win" if win_rate >= 50 else "loss",
        "exp_class":  "win" if expectancy >= 0 else "loss",
    }


# == Public API ================================================================

def write(
    results: list[dict],
    output_dir: str,
    signal_date: str,
    forward_days: int = 30,
) -> Path:
    """
    Render backtest *results* to an HTML validation report.

    Parameters
    ----------
    results      : list of dicts from backtester.run_backtest()
    output_dir   : directory to write the file into (created if missing)
    signal_date  : "YYYY-MM-DD" string used in the filename and header
    forward_days : the forward window used during the backtest run

    Returns
    -------
    Path of the written HTML file.
    """
    out_path = Path(output_dir) / f"Backtest-{signal_date}-fwd{forward_days}d.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Sort: WIN first -> OPEN -> LOSS, then max_gain_pct desc within each group
    order = {"WIN": 0, "OPEN": 1, "LOSS": 2}
    sorted_results = sorted(
        results,
        key=lambda r: (order.get(r["outcome"], 9), -r.get("max_gain_pct", 0))
    )

    summary = _compute_summary(results)

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(_PAGE_HEAD.format(
            signal_date  = signal_date,
            forward_days = forward_days,
            **summary,
        ))

        for sl, r in enumerate(sorted_results, 1):
            rsi = r.get("rsi")
            vol = r.get("vol_ratio")
            fh.write(_ROW.format(
                sl       = sl,
                sym      = r.get("symbol", "?"),
                sig      = r.get("signal_type", "?"),
                sig_c    = _signal_color(r.get("signal_type")),
                stg      = r.get("stage", "?"),
                stg_c    = _stage_color(r.get("stage")),
                entry    = r["entry_price"],
                tp       = r["target_price"],
                stop     = r["stop_loss"],
                rsi      = f"{rsi:.1f}" if rsi is not None else "-",
                rsi_c    = _rsi_color(rsi),
                vol      = f"{vol:.2f}" if vol is not None else "-",
                vol_c    = _vol_color(vol),
                score    = r.get("score", 0),
                sc_c     = _score_color(r.get("score", 0)),
                outcome  = r["outcome"],
                out_c    = _outcome_color(r["outcome"]),
                day      = r["outcome_day"] if r["outcome_day"] else "-",
                max_gain = r.get("max_gain_pct", 0),
                mg_c     = _pct_color(r.get("max_gain_pct", 0)),
                max_dd   = r.get("max_dd_pct", 0),
                dd_c     = _pct_color(r.get("max_dd_pct", 0)),
                final_pct = r.get("final_pct", 0),
                fp_c     = _pct_color(r.get("final_pct", 0)),
                fwd      = r.get("fwd_candles_available", 0),
                reasons  = (r.get("reasons") or "")[:100],
            ))

        fh.write(_PAGE_FOOT)

    return out_path
