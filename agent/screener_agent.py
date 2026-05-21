
# ============================================================
# agent/screener_agent.py â€“ Main orchestrator
# ============================================================
import pandas as pd
from datetime import date, datetime, timedelta
from tabulate import tabulate
from colorama import Fore, Style, init

from data.database       import (init_db, save_ohlcv, save_signal,
                                  open_position, get_open_positions,
                                  ohlcv_latest_date, load_ohlcv,
                                  save_breakout_log, get_ohlcv_date_map,
                                  save_instruments,
                                  get_invalid_symbols, add_invalid_instrument)
from data.upstox_client  import fetch_historical as fetch_upstox_historical
from data.upstox_client  import fetch_nse_instruments as fetch_upstox_instruments
from data.nse_bhavcopy_client import fetch_historical as fetch_bhavcopy_historical
from data.nse_bhavcopy_client import fetch_nse_instruments as fetch_bhavcopy_instruments
from data.nse_bhavcopy_client import get_ohlcv_date_map as get_bhavcopy_date_map
from data.nse_bhavcopy_client import load_ohlcv as load_bhavcopy_ohlcv
from data.nse_bhavcopy_client import update_bhavcopy_cache
from analysis.breakout_scanner import is_breakout, is_ma_pullback
from analysis.news_fetcher     import fetch_and_store_news, get_news_for_symbol
from analysis.gemini_validator import validate_signals_gemini_direct
from agent.portfolio_tracker   import check_exit_signals
from config import (DATA_SOURCE, MAX_OPEN_POSITIONS, PROFIT_TARGET_PCT, STOP_LOSS_PCT,
                    ATR_SL_MULTIPLIER, TOP_PICKS_COUNT,
                    TOP_PICKS_MIN_SCORE, TOP_PICKS_MIN_VOL,
                    TOP_PICKS_RSI_MAX, REPORT_DIR,
                    GEMINI_VALIDATOR_MODEL)
from report.html_report_writer import write as write_html_report

init(autoreset=True)


def _using_bhavcopy() -> bool:
    return DATA_SOURCE == "nse_bhavcopy"


def _source_name() -> str:
    return "NSE Bhavcopy" if _using_bhavcopy() else "Upstox"


# â”€â”€ helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _ensure_instruments(symbols: list):
    """
    Upsert a minimal instruments row for each symbol in a custom list.
    Used when the caller passes symbols directly (bypassing fetch_nse_instruments).
    Keeps the instruments table consistent so the ohlcv FK is always satisfied.
    """
    rows = []
    for sym in symbols:
        if _using_bhavcopy():
            rows.append({"symbol": sym, "instrument_key": sym, "name": sym})
        else:
            from data.upstox_client import get_instrument_key, get_instrument_name
            try:
                ikey = get_instrument_key(sym)
            except KeyError:
                ikey = ""
            rows.append({"symbol": sym, "instrument_key": ikey, "name": get_instrument_name(sym)})
    if rows:
        import pandas as pd
        save_instruments(pd.DataFrame(rows))


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
    â‘  If SQLite already has data up to target_date â†’ load from cache (no API call).
    â‘¡ Otherwise download from Upstox, persist to SQLite, and return.
    """
    cached = ohlcv_latest_date(symbol)
    if cached and cached >= target_date:
        return load_ohlcv(symbol)           # cache hit

    # cache miss - download from Upstox
    df = fetch_upstox_historical(symbol, scan_date=scan_date)
    if not df.empty:
        save_ohlcv(symbol, df)
    return df


# â”€â”€ main scan â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def run_daily_scan(symbols: list = None, scan_date: str = None,
                   force_refresh: bool = False) -> list:
    """
    Full daily scan:
    1. Check exit conditions on open positions
    2. Fetch news
    3. Screen the full NSE EQ universe (or a provided list) for breakouts
       â€“ Uses SQLite cache; only calls Upstox for symbols without up-to-date data.
       â€“ Pass force_refresh=True to bypass cache and re-download all OHLCV data.
    4. LLM validation of every signal
    5. Auto-open Stage2 positions for top signals
    """
    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + "   NSE BREAKOUT AGENT â€“ DAILY SCAN")
    print(Fore.CYAN + "=" * 60)

    target_date = _effective_scan_date(scan_date)
    print(Fore.CYAN + f"   Scan date : {target_date}")
    print(Fore.CYAN + f"   Data      : {_source_name()}")
    if force_refresh:
        print(Fore.YELLOW + "   Mode      : FORCE REFRESH (ignoring OHLCV cache)")

    init_db()

    if _using_bhavcopy():
        latest = update_bhavcopy_cache(scan_date=target_date)
        if not latest:
            print(Fore.RED + "  [ERROR] Could not load NSE Bhavcopy data. Aborting scan.")
            return []
        target_date = latest
        print(Fore.CYAN + f"   Bhavcopy  : using cached trading date {target_date}")

    # â”€â”€ Step 1 â€“ Exit check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print(Fore.YELLOW + "\n[1/5] Checking exit conditions...")
    exits = check_exit_signals()
    if exits:
        for e in exits:
            clr = Fore.GREEN if e["pnl_pct"] > 0 else Fore.RED
            print(clr + f"  EXIT {e['symbol']} | PnL: {e['pnl_pct']:+.2f}% | {e['reason']}")
    else:
        print("  No exits triggered.")

    # â”€â”€ Step 2 â€“ News â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print(Fore.YELLOW + "\n[2/5] Fetching market news...")
    n = fetch_and_store_news()
    print(f"  {n} new articles cached.")

    # â”€â”€ Step 3 â€“ Build universe â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Load blacklist once here â€” used to pre-filter the universe before the loop
    invalid_symbols = get_invalid_symbols()

    if symbols:
        raw_count = len(symbols)
        universe  = [s for s in symbols if s not in invalid_symbols]
        _ensure_instruments(universe)   # FK safety for custom symbols
        removed = raw_count - len(universe)
        print(Fore.YELLOW + f"\n[3/5] Scanning {len(universe)} provided symbols"
              + (f" ({removed} blacklisted removed)." if removed else "."))
    else:
        print(Fore.YELLOW + "\n[3/5] Loading NSE EQ universe...")
        instruments_df = fetch_bhavcopy_instruments() if _using_bhavcopy() else fetch_upstox_instruments()
        if instruments_df.empty:
            print(Fore.RED + "  [ERROR] Could not load NSE instruments. Aborting scan.")
            return []
        save_instruments(instruments_df)   # persist symbol/key/name to instruments table
        raw_count = len(instruments_df)
        universe  = [s for s in instruments_df["symbol"].tolist() if s not in invalid_symbols]
        print(f"  Universe: {len(universe)} NSE EQ instruments "
              f"({raw_count - len(universe)} blacklisted removed).")

    # â”€â”€ Step 3 â€“ Scan universe â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    signals     = []
    open_pos    = {p["symbol"] for p in get_open_positions()}
    total       = len(universe)
    downloaded  = 0
    cached_hits = 0
    skipped     = 0

    # Single query to load ALL cached dates at once (replaces ~1800 per-symbol queries)
    ohlcv_date_map = get_bhavcopy_date_map() if _using_bhavcopy() else get_ohlcv_date_map()

    for i, symbol in enumerate(universe, 1):
        if symbol in open_pos:
            skipped += 1
            continue

        print(f"  [{i:>4}/{total}] {symbol:<20} ", end="\r")

        cached = ohlcv_date_map.get(symbol)   # O(1) dict lookup, no DB call
        if not force_refresh and cached and cached >= target_date:
            df = load_bhavcopy_ohlcv(symbol) if _using_bhavcopy() else load_ohlcv(symbol)
            cached_hits += 1
        else:
            df = fetch_bhavcopy_historical(symbol, scan_date=target_date) if _using_bhavcopy() else fetch_upstox_historical(symbol, scan_date=scan_date)
            if not df.empty and not _using_bhavcopy():
                save_ohlcv(symbol, df)
                # Keep date map fresh so a later occurrence of the same symbol is correct
                ohlcv_date_map[symbol] = df["date"].iloc[-1] if hasattr(df["date"].iloc[-1], '__str__') else str(df["date"].iloc[-1])
                downloaded += 1
            elif not df.empty:
                downloaded += 1

        if df.empty:
            # Permanently blacklist symbols that never return data (delisted / suspended)
            add_invalid_instrument(symbol, "NO_DATA", "SCAN_EMPTY")
            invalid_symbols.add(symbol)   # update in-memory set for this run too
            continue

        for scanner in (is_breakout, is_ma_pullback):
            sig = scanner(df)
            if sig:
                sig["symbol"] = symbol
                sig["news"]   = get_news_for_symbol(symbol)
                signals.append(sig)

    print(f"\n  Done. Downloaded: {downloaded} | From cache: {cached_hits} | Skipped (open pos): {skipped}")

    signals.sort(key=lambda x: x["score"], reverse=True)

    # Step 4 - Gemini validation
    if signals:
        print(Fore.YELLOW + f"\n[4/5] Gemini validation ({len(signals)} signal(s))...")
        print(Fore.CYAN + f"      Model  : {GEMINI_VALIDATOR_MODEL}")
        print(Fore.CYAN + "      Source : Gemini + Google Search grounding")
        validate_signals_gemini_direct(signals, scan_date=target_date)

        for sig in signals:
            save_breakout_log(target_date, sig)
        print(f"  {len(signals)} signal(s) saved to breakout_log.")

    else:
        for sig in signals:
            sig["scan_date"] = target_date

    # â”€â”€ Step 5 â€“ Display & auto-enter top signals â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print(Fore.YELLOW + f"\n[5/5] Results: {len(signals)} breakout candidate(s) found.")
    if signals:
        # â”€â”€ Sort: CONFIRM first, then WEAK, then REJECT/SKIPPED; within each group by score â”€â”€
        _verdict_order = {"CONFIRM": 0, "WEAK": 1, "REJECT": 2, "SKIPPED": 3}
        signals.sort(key=lambda x: (
            _verdict_order.get(x.get("llm_verdict", "SKIPPED"), 3),
            -x["score"]
        ))

        # â”€â”€ LLM verdict summary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # â”€â”€ Candidate table (all signals, CONFIRM at top) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        print(Fore.CYAN + f"\n{'â”€'*20} BREAKOUT CANDIDATES {'â”€'*20}")
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
                f"â‚¹{s['close']}",
                s["rsi"],
                f"{s['vol_ratio']}x",
                s["score"],
                s["stage"],
                llm_display,
                s["reasons"][:45],
            ])
        headers = ["Type", "Symbol", "Price", "RSI", "Vol", "Score", "Stage", "LLM", "Reason"]
        print("\n" + tabulate(rows, headers=headers, tablefmt="fancy_grid"))

        # â”€â”€ Auto-enter new positions (Stage2 + CONFIRM/WEAK only) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
                      f"  [BUY #{new_entries}] {sig['symbol']:<15} @ â‚¹{bp} "
                      f"| Target â‚¹{tp} | SL â‚¹{sl} ({sl_method}) "
                      f"| LLM: {sig.get('llm_verdict','?')}")
                open_count = len(get_open_positions())

    # â”€â”€ TOP PICKS â€“ the final actionable shortlist â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _print_top_picks(signals, target_date)

    # â”€â”€ HTML Report â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if signals:
        try:
            html_path = write_html_report(signals, REPORT_DIR, target_date)
            print(Fore.CYAN + f"\n  ðŸ“„ HTML report saved â†’ {html_path}")
        except Exception as exc:
            print(Fore.YELLOW + f"  [WARN] Could not write HTML report: {exc}")

    return signals


# â”€â”€ Top Picks helper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _print_top_picks(signals: list, scan_date: str):
    """
    From all signals, filter down to the highest-conviction swing trade setups:
      â€¢ Stage2 (trending, not parabolic)
      â€¢ LLM verdict = CONFIRM  (or WEAK as fallback when no CONFIRMs exist)
      â€¢ Score >= TOP_PICKS_MIN_SCORE
      â€¢ Vol ratio >= TOP_PICKS_MIN_VOL
      â€¢ RSI <= TOP_PICKS_RSI_MAX  (not overbought)
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
    print(Fore.GREEN + f"  â˜…  TODAY'S TOP PICKS  â€”  {scan_date}  â˜…")
    print(Fore.GREEN + f"  (Stage2 | LLM CONFIRM | Scoreâ‰¥{TOP_PICKS_MIN_SCORE} | Volâ‰¥{TOP_PICKS_MIN_VOL}x | RSIâ‰¤{TOP_PICKS_RSI_MAX})")
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
        # Show pattern badges if detected
        pattern_badges = ""
        if s.get("vcp_detected"):
            pattern_badges += " [VCP]"
        if s.get("bull_flag_detected"):
            pattern_badges += " [FLAG]"

        print(verdict_colour +
              f"  #{rank}  {s['symbol']:<12}  â‚¹{bp:<9.2f}  "
              f"Score:{s['score']}  RSI:{s['rsi']:.0f}  Vol:{s['vol_ratio']:.1f}x  "
              f"Gemini:{s.get('llm_verdict')}({conf}/10){pattern_badges}")
        print(Style.RESET_ALL +
              f"      Entry â‚¹{bp:.2f}  â†’  Target â‚¹{tp:.2f}  â†’  SL â‚¹{sl:.2f}  "
              f"(Risk {rr}% | 2R reward)")
        if reasoning:
            print(f"      Reasoning: {reasoning[:100]}")
        print()

    print(Fore.GREEN + border + Style.RESET_ALL)
