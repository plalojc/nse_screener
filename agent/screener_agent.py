
# ============================================================
# agent/screener_agent.py – Main orchestrator
# ============================================================
import pandas as pd
from datetime import date, datetime, timedelta
from tabulate import tabulate
from colorama import Fore, Style, init

from data.database       import (init_db, save_ohlcv, save_signal,
                                  open_position, get_open_positions,
                                  ohlcv_latest_date, load_ohlcv,
                                  save_breakout_log, get_ohlcv_date_map)
from data.upstox_client  import fetch_historical, fetch_nse_instruments
from analysis.breakout_scanner import is_breakout, is_ma_pullback
from analysis.news_fetcher     import fetch_and_store_news, get_news_for_symbol
from analysis.llm_validator    import validate_signals_batch
from agent.portfolio_tracker   import check_exit_signals
from config import (MAX_OPEN_POSITIONS, PROFIT_TARGET_PCT, STOP_LOSS_PCT,
                    ATR_SL_MULTIPLIER, LLM_API_KEY, LLM_PROVIDER, LLM_MODEL,
                    TOP_PICKS_COUNT, TOP_PICKS_MIN_SCORE,
                    TOP_PICKS_MIN_VOL, TOP_PICKS_RSI_MAX, REPORT_DIR)
from report.html_report_writer import write as write_html_report

init(autoreset=True)


# ── helpers ───────────────────────────────────────────────────────────────────

def _effective_scan_date(scan_date: str = None) -> str:
    """
    Return the effective 'to_date' for data fetching as 'YYYY-MM-DD'.
    If scan_date is given, snap it to the nearest past weekday.
    Otherwise use the most recent weekday before today.
    """
    if scan_date:
        d = datetime.strptime(scan_date, "%Y-%m-%d").date()
    else:
        d = date.today() - timedelta(days=1)
    while d.weekday() >= 5:          # skip Sat(5) / Sun(6)
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _get_ohlcv(symbol: str, target_date: str, scan_date: str = None) -> pd.DataFrame:
    """
    Return OHLCV for a symbol.
    ① If SQLite already has data up to target_date → load from cache (no API call).
    ② Otherwise download from Upstox, persist to SQLite, and return.
    """
    cached = ohlcv_latest_date(symbol)
    if cached and cached >= target_date:
        return load_ohlcv(symbol)           # cache hit

    # cache miss – download from Upstox
    df = fetch_historical(symbol, scan_date=scan_date)
    if not df.empty:
        save_ohlcv(symbol, df)
    return df


# ── main scan ─────────────────────────────────────────────────────────────────

def run_daily_scan(symbols: list = None, scan_date: str = None,
                   force_refresh: bool = False) -> list:
    """
    Full daily scan:
    1. Check exit conditions on open positions
    2. Fetch news
    3. Screen the full NSE EQ universe (or a provided list) for breakouts
       – Uses SQLite cache; only calls Upstox for symbols without up-to-date data.
       – Pass force_refresh=True to bypass cache and re-download all OHLCV data.
    4. LLM validation of every signal
    5. Auto-open Stage2 positions for top signals
    """
    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + "   NSE BREAKOUT AGENT – DAILY SCAN")
    print(Fore.CYAN + "=" * 60)

    target_date = _effective_scan_date(scan_date)
    print(Fore.CYAN + f"   Scan date : {target_date}")
    if force_refresh:
        print(Fore.YELLOW + "   Mode      : FORCE REFRESH (ignoring OHLCV cache)")

    init_db()

    # ── Step 1 – Exit check ───────────────────────────────────────────────────
    print(Fore.YELLOW + "\n[1/5] Checking exit conditions...")
    exits = check_exit_signals()
    if exits:
        for e in exits:
            clr = Fore.GREEN if e["pnl_pct"] > 0 else Fore.RED
            print(clr + f"  EXIT {e['symbol']} | PnL: {e['pnl_pct']:+.2f}% | {e['reason']}")
    else:
        print("  No exits triggered.")

    # ── Step 2 – News ─────────────────────────────────────────────────────────
    print(Fore.YELLOW + "\n[2/5] Fetching market news...")
    n = fetch_and_store_news()
    print(f"  {n} new articles cached.")

    # ── Step 3 – Build universe ───────────────────────────────────────────────
    if symbols:
        universe = symbols
        print(Fore.YELLOW + f"\n[3/5] Scanning {len(universe)} provided symbols...")
    else:
        print(Fore.YELLOW + "\n[3/5] Loading NSE EQ universe...")
        instruments_df = fetch_nse_instruments()
        if instruments_df.empty:
            print(Fore.RED + "  [ERROR] Could not load NSE instruments. Aborting scan.")
            return []
        universe = instruments_df["symbol"].tolist()
        print(f"  Universe: {len(universe)} NSE EQ instruments.")

    # ── Step 3 – Scan universe ────────────────────────────────────────────────
    signals     = []
    open_pos    = {p["symbol"] for p in get_open_positions()}
    total       = len(universe)
    downloaded  = 0
    cached_hits = 0
    skipped     = 0

    # Single query to load ALL cached dates at once (replaces ~1800 per-symbol queries)
    ohlcv_date_map = get_ohlcv_date_map()  # {symbol: latest_date_str}

    for i, symbol in enumerate(universe, 1):
        if symbol in open_pos:
            skipped += 1
            continue

        print(f"  [{i:>4}/{total}] {symbol:<20} ", end="\r")

        cached = ohlcv_date_map.get(symbol)   # O(1) dict lookup, no DB call
        if not force_refresh and cached and cached >= target_date:
            df = load_ohlcv(symbol)
            cached_hits += 1
        else:
            df = fetch_historical(symbol, scan_date=scan_date)
            if not df.empty:
                save_ohlcv(symbol, df)
                # Keep date map fresh so a later occurrence of the same symbol is correct
                ohlcv_date_map[symbol] = df["date"].iloc[-1] if hasattr(df["date"].iloc[-1], '__str__') else str(df["date"].iloc[-1])
                downloaded += 1

        if df.empty:
            continue

        for scanner in (is_breakout, is_ma_pullback):
            sig = scanner(df)
            if sig:
                sig["symbol"] = symbol
                sig["news"]   = get_news_for_symbol(symbol)
                signals.append(sig)

    print(f"\n  Done. Downloaded: {downloaded} | From cache: {cached_hits} | Skipped (open pos): {skipped}")

    signals.sort(key=lambda x: x["score"], reverse=True)

    # ── Step 4 – LLM Validation ────────────────────────────────────────────
    if signals:
        if LLM_API_KEY:
            print(Fore.YELLOW + f"\n[4/5] LLM validation ({len(signals)} signal(s))...")
            print(Fore.CYAN   + f"      Provider : {LLM_PROVIDER}  Model : {LLM_MODEL}")
            validate_signals_batch(signals, scan_date=target_date)
        else:
            print(Fore.RED + "\n[4/5] LLM validation SKIPPED.")
            print(Fore.RED + "      Reason: LLM_API_KEY is not set.")
            print(Fore.RED + "      Fix   : Add LLM_API_KEY=your_key to your .env file ")
            print(Fore.RED + "               (get a free key at https://console.groq.com/keys)")
            for sig in signals:
                sig["scan_date"]      = target_date
                sig["llm_verdict"]    = "SKIPPED"
                sig["llm_confidence"] = None
                sig["llm_reasoning"]  = "LLM_API_KEY not set"

        # Persist every signal to breakout_log (date-wise history)
        for sig in signals:
            save_breakout_log(target_date, sig)
        print(f"  {len(signals)} signal(s) saved to breakout_log.")
    else:
        for sig in signals:
            sig["scan_date"] = target_date

    # ── Step 5 – Display & auto-enter top signals ─────────────────────────
    print(Fore.YELLOW + f"\n[5/5] Results: {len(signals)} breakout candidate(s) found.")
    if signals:
        # ── Sort: CONFIRM first, then WEAK, then REJECT/SKIPPED; within each group by score ──
        _verdict_order = {"CONFIRM": 0, "WEAK": 1, "REJECT": 2, "SKIPPED": 3}
        signals.sort(key=lambda x: (
            _verdict_order.get(x.get("llm_verdict", "SKIPPED"), 3),
            -x["score"]
        ))

        # ── LLM verdict summary ──────────────────────────────────────────────
        from collections import Counter
        verdict_counts = Counter(s.get("llm_verdict", "SKIPPED") for s in signals)
        print(
            Fore.GREEN  + f"  CONFIRM : {verdict_counts.get('CONFIRM', 0)}"
            + Style.RESET_ALL + "  |  "
            + Fore.YELLOW + f"WEAK    : {verdict_counts.get('WEAK', 0)}"
            + Style.RESET_ALL + "  |  "
            + Fore.RED   + f"REJECT  : {verdict_counts.get('REJECT', 0)}"
            + Style.RESET_ALL + "  |  "
            + f"SKIPPED : {verdict_counts.get('SKIPPED', 0)}"
        )

        # ── Candidate table (all signals, CONFIRM at top) ────────────────────
        print(Fore.CYAN + f"\n{'─'*20} BREAKOUT CANDIDATES {'─'*20}")
        rows = []
        for s in signals:
            verdict = s.get("llm_verdict", "")
            conf    = s.get("llm_confidence")
            llm_col = verdict + (f"({conf}/10)" if conf else "")
            if verdict == "CONFIRM":
                llm_display = Fore.GREEN  + llm_col + Style.RESET_ALL
            elif verdict == "REJECT":
                llm_display = Fore.RED    + llm_col + Style.RESET_ALL
            elif verdict == "WEAK":
                llm_display = Fore.YELLOW + llm_col + Style.RESET_ALL
            else:
                llm_display = llm_col
            rows.append([
                s.get("signal_type", "BREAKOUT"),
                s["symbol"],
                f"₹{s['close']}",
                s["rsi"],
                f"{s['vol_ratio']}x",
                s["score"],
                s["stage"],
                llm_display,
                s["reasons"][:45],
            ])
        headers = ["Type", "Symbol", "Price", "RSI", "Vol", "Score", "Stage", "LLM", "Reason"]
        print("\n" + tabulate(rows, headers=headers, tablefmt="fancy_grid"))

        # ── Auto-enter new positions (Stage2 + CONFIRM/WEAK only) ────────────
        open_count  = len(get_open_positions())
        slots_free  = MAX_OPEN_POSITIONS - open_count
        new_entries = 0

        if slots_free > 0:
            for sig in signals:
                if open_count >= MAX_OPEN_POSITIONS:
                    break
                # Only enter Stage2; skip LLM REJECTs
                if sig["stage"] != "Stage2":
                    continue
                if sig.get("llm_verdict") == "REJECT":
                    continue

                bp  = sig["close"]
                atr = sig.get("atr14") or 0

                sl_atr   = round(bp - ATR_SL_MULTIPLIER * atr, 2) if atr > 0 else None
                sl_swing = round(sig["swing_low"] * 0.99, 2) if sig.get("swing_low") else None
                candidates = [x for x in [sl_atr, sl_swing] if x is not None and x < bp]
                sl = max(candidates) if candidates else round(bp * (1 - STOP_LOSS_PCT / 100), 2)

                risk_amount   = bp - sl
                tp            = round(bp + (risk_amount * 2), 2)
                trailing_stop = sl
                sl_method     = ("ATR" if sl == sl_atr else "SwingLow" if sl == sl_swing else "Fixed%")

                open_position(sig["symbol"], bp, tp, sl, trailing_stop)
                save_signal(sig["symbol"], "BUY", bp, sig["reasons"])
                new_entries += 1
                print(Fore.GREEN +
                      f"  [BUY #{new_entries}] {sig['symbol']:<15} @ ₹{bp} "
                      f"| Target ₹{tp} | SL ₹{sl} ({sl_method}) "
                      f"| LLM: {sig.get('llm_verdict','?')}")
                open_count = len(get_open_positions())

    # ── TOP PICKS – the final actionable shortlist ──────────────────────────
    _print_top_picks(signals, target_date)

    # ── HTML Report ──────────────────────────────────────────────────
    if signals:
        try:
            html_path = write_html_report(signals, REPORT_DIR, target_date)
            print(Fore.CYAN + f"\n  📄 HTML report saved → {html_path}")
        except Exception as exc:
            print(Fore.YELLOW + f"  [WARN] Could not write HTML report: {exc}")

    return signals


# ── Top Picks helper ───────────────────────────────────────────────────────────

def _print_top_picks(signals: list, scan_date: str):
    """
    From all signals, filter down to the highest-conviction swing trade setups:
      • Stage2 (trending, not parabolic)
      • LLM verdict = CONFIRM  (or WEAK as fallback when no CONFIRMs exist)
      • Score >= TOP_PICKS_MIN_SCORE
      • Vol ratio >= TOP_PICKS_MIN_VOL
      • RSI <= TOP_PICKS_RSI_MAX  (not overbought)
    Ranked by: LLM confidence DESC then score DESC.
    """
    WIDTH = 62
    border = "=" * WIDTH

    # Primary filter: CONFIRM + all hard criteria
    picks = [
        s for s in signals
        if s.get("stage") == "Stage2"
        and s.get("llm_verdict") == "CONFIRM"
        and s.get("score", 0)     >= TOP_PICKS_MIN_SCORE
        and s.get("vol_ratio", 0) >= TOP_PICKS_MIN_VOL
        and s.get("rsi", 99)      <= TOP_PICKS_RSI_MAX
    ]

    # Fallback: if no CONFIRMs, relax to WEAK but keep all other filters
    if not picks:
        picks = [
            s for s in signals
            if s.get("stage") == "Stage2"
            and s.get("llm_verdict") in ("CONFIRM", "WEAK")
            and s.get("score", 0)     >= TOP_PICKS_MIN_SCORE
            and s.get("vol_ratio", 0) >= TOP_PICKS_MIN_VOL
            and s.get("rsi", 99)      <= TOP_PICKS_RSI_MAX
        ]

    # Sort: highest LLM confidence first, then score
    picks.sort(key=lambda x: (
        -(x.get("llm_confidence") or 0),
        -x.get("score", 0)
    ))
    picks = picks[:TOP_PICKS_COUNT]

    print(Fore.GREEN + "\n" + border)
    print(Fore.GREEN + f"  ★  TODAY'S TOP PICKS  —  {scan_date}  ★")
    print(Fore.GREEN + f"  (Stage2 | LLM CONFIRM | Score≥{TOP_PICKS_MIN_SCORE} | Vol≥{TOP_PICKS_MIN_VOL}x | RSI≤{TOP_PICKS_RSI_MAX})")
    print(Fore.GREEN + border + Style.RESET_ALL)

    if not picks:
        print(Fore.YELLOW + "  No picks met all criteria today.")
        print(Fore.YELLOW + "  Tip: check WEAK signals in the candidates table above.")
        print(Fore.GREEN + border + Style.RESET_ALL)
        return

    for rank, s in enumerate(picks, 1):
        bp       = s["close"]
        atr      = s.get("atr14") or 0
        sl_atr   = round(bp - ATR_SL_MULTIPLIER * atr, 2) if atr > 0 else None
        sl_swing = round(s["swing_low"] * 0.99, 2) if s.get("swing_low") else None
        cands    = [x for x in [sl_atr, sl_swing] if x is not None and x < bp]
        sl       = max(cands) if cands else round(bp * (1 - STOP_LOSS_PCT / 100), 2)
        risk     = bp - sl
        tp       = round(bp + risk * 2, 2)
        rr       = round(risk / bp * 100, 1)   # risk as % of price
        conf     = s.get("llm_confidence") or "?"
        reasoning = s.get("llm_reasoning") or ""

        verdict_colour = Fore.GREEN if s.get("llm_verdict") == "CONFIRM" else Fore.YELLOW
        print(verdict_colour +
              f"  #{rank}  {s['symbol']:<12}  ₹{bp:<9.2f}  "
              f"Score:{s['score']}  RSI:{s['rsi']:.0f}  Vol:{s['vol_ratio']:.1f}x  "
              f"LLM:{s.get('llm_verdict')}({conf}/10)")
        print(Style.RESET_ALL +
              f"      Entry ₹{bp:.2f}  →  Target ₹{tp:.2f}  →  SL ₹{sl:.2f}  "
              f"(Risk {rr}% | 2R reward)")
        if reasoning:
            print(f"      🧠 {reasoning[:80]}")
        print()

    print(Fore.GREEN + border + Style.RESET_ALL)
