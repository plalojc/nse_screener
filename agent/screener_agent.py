
# ============================================================
# agent/screener_agent.py - Main orchestrator
# ============================================================
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from tabulate import tabulate
from colorama import Fore, Style, init

from data.database       import (init_db, save_signal,
                                  open_position, get_open_positions,
                                  save_breakout_logs,
                                  get_invalid_symbols, add_invalid_instrument)
from data.nse_bhavcopy_client import fetch_nse_instruments as fetch_bhavcopy_instruments
from data.nse_bhavcopy_client import load_ohlcv_bulk as load_bhavcopy_ohlcv_bulk
from data.nse_bhavcopy_client import get_bhavcopy_status, update_bhavcopy_cache
from analysis.breakout_scanner import (
    is_breakout,
    is_llm_watchlist_candidate,
    is_ma_pullback,
    is_stage1_watchlist,
    passes_breakout_prefilter,
    passes_stage1_prefilter,
)
from analysis.catalyst_news import (
    attach_best_catalyst,
    build_news_signal,
    fetch_and_store_catalysts,
    get_catalyst_map,
)
from analysis.technical import add_indicators
from analysis.grok_validator import validate_signals_grok_batch
from agent.portfolio_tracker   import check_exit_signals
from config import (LLM_FILL_TO_LIMIT, LLM_VALIDATION_LIMIT,
                    ENABLE_CATALYST_NEWS,
                    SCAN_SIGNAL_TYPES,
                    MAX_OPEN_POSITIONS, PROFIT_TARGET_PCT, STOP_LOSS_PCT,
                    ATR_SL_MULTIPLIER, TOP_PICKS_COUNT,
                    TOP_PICKS_MIN_SCORE, TOP_PICKS_MIN_VOL,
                    TOP_PICKS_RSI_MAX,
                    GROK_VALIDATOR_MODEL,
                    MAX_CATALYST_CANDIDATES)

init(autoreset=True)

IST = ZoneInfo("Asia/Kolkata")


def _flow(message: str) -> None:
    print(Fore.CYAN + f"[Flow] {message}", flush=True)


def _elapsed(start: float) -> str:
    return f"{time.perf_counter() - start:.1f}s"


def _validator_name() -> str:
    return "Grok"


def _rank_signal(sig: dict) -> tuple:
    """Built-in ranking before paid/remote LLM validation."""
    signal_type = str(sig.get("signal_type") or "").upper()
    stage = sig.get("stage")
    if signal_type == "BREAKOUT" and stage == "Stage2":
        priority = 50
    elif signal_type == "STAGE1":
        priority = 40
    elif signal_type == "BREAKOUT":
        priority = 35
    elif signal_type == "NEWS":
        priority = 32
    elif signal_type == "PULLBACK":
        priority = 30
    elif signal_type == "WATCHLIST" and stage == "Stage2":
        priority = 20
    elif signal_type == "WATCHLIST" and stage == "Stage1":
        priority = 15
    else:
        priority = 0
    stage_bonus = 2 if stage == "Stage2" else 0
    catalyst_score = sig.get("catalyst_score") or 0
    catalyst_confidence = sig.get("catalyst_confidence") or 0
    pattern_score = sig.get("pattern_score") or 0
    score = sig.get("swing_score") or sig.get("score") or 0
    vol_ratio = sig.get("vol_ratio") or 0
    rsi = sig.get("rsi") or 99
    rsi_penalty = abs(65 - rsi)
    risk = sig.get("entry_risk_pct") or 99
    extension = sig.get("ema20_extension_pct") or 99
    turnover = sig.get("turnover_cr") or 0
    return (
        priority,
        score + stage_bonus,
        catalyst_score,
        catalyst_confidence,
        pattern_score,
        -risk,
        -extension,
        turnover,
        vol_ratio,
        -rsi_penalty,
    )


def _select_llm_candidates(signals: list[dict]) -> list[dict]:
    """
    Pick top unique symbols for LLM validation using quota buckets:
      - 60% technical: BREAKOUT / STAGE1 / PULLBACK
      - 30% news-driven: NEWS
      - 10% fallback/watchlist: WATCHLIST and anything left

    Unused quota is backfilled by the strongest remaining candidates, so the
    admin limit is still used as fully as possible.
    """
    if LLM_VALIDATION_LIMIT <= 0 or len(signals) <= LLM_VALIDATION_LIMIT:
        return signals

    def category(sig: dict) -> str:
        signal_type = str(sig.get("signal_type") or "").upper()
        if signal_type == "NEWS":
            return "news"
        if signal_type == "WATCHLIST":
            return "fallback"
        if signal_type in {"BREAKOUT", "STAGE1", "PULLBACK"}:
            return "technical"
        return "fallback"

    limit = LLM_VALIDATION_LIMIT
    quotas = {
        "technical": int(limit * 0.60),
        "news": int(limit * 0.30),
    }
    quotas["fallback"] = max(0, limit - quotas["technical"] - quotas["news"])

    selected_symbols = []
    selected_set = set()

    def add_from(candidates: list[dict], quota: int) -> int:
        added = 0
        for sig in sorted(candidates, key=_rank_signal, reverse=True):
            if added >= quota or len(selected_symbols) >= limit:
                break
            symbol = sig.get("symbol")
            if not symbol or symbol in selected_set:
                continue
            selected_symbols.append(symbol)
            selected_set.add(symbol)
            added += 1
        return added

    buckets = {"technical": [], "news": [], "fallback": []}
    for sig in signals:
        buckets[category(sig)].append(sig)

    add_from(buckets["technical"], quotas["technical"])
    add_from(buckets["news"], quotas["news"])
    add_from(buckets["fallback"], quotas["fallback"])

    remaining_slots = limit - len(selected_symbols)
    if remaining_slots > 0:
        remaining = [
            sig for sig in signals
            if sig.get("symbol") and sig.get("symbol") not in selected_set
        ]
        add_from(remaining, remaining_slots)

    for sig in signals:
        symbol = sig.get("symbol")
        if symbol and symbol not in selected_set and len(selected_symbols) < limit:
            selected_symbols.append(symbol)
            selected_set.add(symbol)
        if len(selected_symbols) >= limit:
            break

    return [sig for sig in signals if sig.get("symbol") in selected_set]


def _mark_llm_not_selected(signals: list[dict], scan_date: str) -> None:
    for sig in signals:
        sig["scan_date"] = scan_date
        sig["llm_verdict"] = "SKIPPED"
        sig["llm_confidence"] = 0
        sig["llm_reasoning"] = (
            f"Not sent to {_validator_name()}: outside top "
            f"{LLM_VALIDATION_LIMIT} rule-ranked stocks."
        )
        sig["panel_method"] = "LOCAL_RANK_SKIP"


def _effective_scan_date(scan_date: str = None) -> str:
    """
    Return the effective 'to_date' for data fetching as 'YYYY-MM-DD'.
    Automatically switches to today's date if run post-market (after 5 PM IST).
    """
    if scan_date:
        d = datetime.strptime(scan_date, "%Y-%m-%d").date()
    else:
        # Check current hour. If it's 5 PM (17:00) or later, look for today's file.
        # Otherwise, default to yesterday.
        now = datetime.now(IST)
        if now.hour >= 17:
            d = now.date()
        else:
            d = now.date() - timedelta(days=1)
            
    while d.weekday() >= 5:          # skip Sat(5) / Sun(6)
        d -= timedelta(days=1)
        
    return d.strftime("%Y-%m-%d")

# -----------------------------------------------------------

def run_daily_scan(symbols: list = None, scan_date: str = None,
                   force_refresh: bool = False) -> list:
    """
    Full daily scan:
    1. Check exit conditions on open positions
    2. Screen the full NSE EQ universe (or a provided list) for breakouts
       - Uses NSE Bhavcopy cache; downloads missing Bhavcopy files as needed.
       - Pass force_refresh=True to refresh the latest Bhavcopy file.
    4. LLM validation of top rule-ranked signals only
    5. Auto-open Stage2 positions for top signals
    """
    scan_started = time.perf_counter()
    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + "   NSE BREAKOUT AGENT - DAILY SCAN")
    print(Fore.CYAN + "=" * 60)

    target_date = _effective_scan_date(scan_date)
    requested_target_date = target_date
    print(Fore.CYAN + f"   Scan date : {target_date}")
    print(Fore.CYAN + "   Data      : NSE Bhavcopy")
    print(Fore.CYAN + f"   Signals   : {', '.join(sorted(SCAN_SIGNAL_TYPES)) or 'BREAKOUT'}")
    print(Fore.CYAN + f"   Validator : {_validator_name()}")
    if LLM_FILL_TO_LIMIT and LLM_VALIDATION_LIMIT > 0:
        print(Fore.CYAN + f"   LLM fill  : target top {LLM_VALIDATION_LIMIT} with NEWS/WATCHLIST fill")
    if force_refresh:
        print(Fore.YELLOW + "   Mode      : FORCE REFRESH (ignoring OHLCV cache)")

    init_db()

    phase_started = time.perf_counter()
    _flow("Phase bhavcopy-cache started")
    latest = update_bhavcopy_cache(scan_date=target_date, force_refresh=force_refresh)
    if not latest:
        print(Fore.RED + "   [ERROR] Could not load NSE Bhavcopy data. Aborting scan.")
        return []
    if scan_date and latest != requested_target_date:
        status = get_bhavcopy_status(requested_target_date) or {}
        detail = status.get("message") or "No failure detail recorded."
        raise RuntimeError(
            f"Bhavcopy is not available for requested scan date {requested_target_date}. "
            f"Latest available trading date is {latest}; scan was not run for an older date. "
            f"Download detail: {detail}"
        )
    target_date = latest
    print(Fore.CYAN + f"   Bhavcopy  : using cached trading date {target_date}")
    _flow(f"Phase bhavcopy-cache completed in {_elapsed(phase_started)}")

    # 
    phase_started = time.perf_counter()
    _flow("Phase exit-check started")
    print(Fore.YELLOW + "\n[1/5] Checking exit conditions...")
    exits = check_exit_signals()
    if exits:
        for e in exits:
            clr = Fore.GREEN if e["pnl_pct"] > 0 else Fore.RED
            print(clr + f"  EXIT {e['symbol']} | PnL: {e['pnl_pct']:+.2f}% | {e['reason']}")
    else:
        print("  No exits triggered.")
    _flow(f"Phase exit-check completed in {_elapsed(phase_started)} | exits={len(exits)}")

    # Load blacklist once here - used to pre-filter the universe before the loop
    phase_started = time.perf_counter()
    _flow("Phase universe-load started")
    invalid_symbols = get_invalid_symbols()

    if symbols:
        raw_count = len(symbols)
        universe  = [s for s in symbols if s not in invalid_symbols]
        removed = raw_count - len(universe)
        print(Fore.YELLOW + f"\n[3/5] Scanning {len(universe)} provided symbols"
              + (f" ({removed} blacklisted removed)." if removed else "."))
    else:
        print(Fore.YELLOW + "\n[3/5] Loading NSE EQ universe...")
        instruments_df = fetch_bhavcopy_instruments()
        if instruments_df.empty:
            print(Fore.RED + "  [ERROR] Could not load NSE instruments. Aborting scan.")
            return []
        raw_count = len(instruments_df)
        universe  = [s for s in instruments_df["symbol"].tolist() if s not in invalid_symbols]
        print(f"  Universe: {len(universe)} NSE EQ instruments "
              f"({raw_count - len(universe)} blacklisted removed).")
    _flow(f"Phase universe-load completed in {_elapsed(phase_started)} | universe={len(universe)}")

    catalyst_map = {}
    if ENABLE_CATALYST_NEWS:
        phase_started = time.perf_counter()
        _flow("Phase catalyst-fetch started")
        print(Fore.YELLOW + "\n[2b] Fetching catalyst/news events...")
        catalyst_rows = fetch_and_store_catalysts(target_date, universe)
        catalyst_map = get_catalyst_map(target_date)
        print(
            f"  Catalyst events cached/updated: {catalyst_rows} "
            f"| Symbols with catalysts: {len(catalyst_map)}"
        )
        _flow(
            f"Phase catalyst-fetch completed in {_elapsed(phase_started)} "
            f"| rows={catalyst_rows} symbols={len(catalyst_map)}"
        )

    # == Step 3: Scan universe =============================================
    signals     = []
    open_pos    = {p["symbol"] for p in get_open_positions()}
    total       = len(universe)
    skipped     = 0

    scan_universe = [s for s in universe if s not in open_pos]
    skipped = total - len(scan_universe)
    print(f"  Loading OHLCV cache for {len(scan_universe)} scan symbol(s)...")
    phase_started = time.perf_counter()
    _flow(f"Phase ohlcv-bulk-load started | symbols={len(scan_universe)}")
    ohlcv_by_symbol = load_bhavcopy_ohlcv_bulk(scan_universe, upto_date=target_date)
    _flow(
        f"Phase ohlcv-bulk-load completed in {_elapsed(phase_started)} "
        f"| loaded={len(ohlcv_by_symbol)}"
    )
    use_breakout = not SCAN_SIGNAL_TYPES or "BREAKOUT" in SCAN_SIGNAL_TYPES
    use_pullback = "PULLBACK" in SCAN_SIGNAL_TYPES
    use_stage1 = "STAGE1" in SCAN_SIGNAL_TYPES
    scanners = []
    if use_breakout:
        scanners.append(is_breakout)
    if use_pullback:
        scanners.append(is_ma_pullback)
    if use_stage1:
        scanners.append(is_stage1_watchlist)
    if not scanners:
        print(Fore.YELLOW + "  [WARN] SCAN_SIGNAL_TYPES matched no known scanners; using BREAKOUT.")
        use_breakout = True
        scanners.append(is_breakout)
    prefiltered = 0
    news_fill_candidates = []
    watchlist_fill_candidates = []
    indicator_count = 0

    phase_started = time.perf_counter()
    _flow(f"Phase technical-scan started | symbols={len(scan_universe)}")
    for i, symbol in enumerate(universe, 1):
        if symbol in open_pos:
            continue

        print(f"  [{i:>4}/{total}] {symbol:<20} ", end="\r")

        df = ohlcv_by_symbol.get(symbol)

        if df is None or df.empty:
            # Permanently blacklist symbols that never return data (delisted / suspended)
            add_invalid_instrument(symbol, "NO_DATA", "SCAN_EMPTY")
            invalid_symbols.add(symbol)   # update in-memory set for this run too
            continue

        should_prefilter = (
            not LLM_FILL_TO_LIMIT
            and not use_pullback
            and (use_breakout or use_stage1)
        )
        if should_prefilter:
            passes_any_prefilter = (
                (use_breakout and passes_breakout_prefilter(df))
                or (use_stage1 and passes_stage1_prefilter(df))
            )
        else:
            passes_any_prefilter = True
        if not passes_any_prefilter:
            prefiltered += 1
            continue

        df = add_indicators(df)
        indicator_count += 1
        symbol_has_signal = False
        for scanner in scanners:
            sig = scanner(df)
            if sig:
                sig["symbol"] = symbol
                if symbol in catalyst_map:
                    sig = attach_best_catalyst(sig, catalyst_map[symbol])
                signals.append(sig)
                symbol_has_signal = True

        if LLM_FILL_TO_LIMIT and LLM_VALIDATION_LIMIT > 0 and not symbol_has_signal:
            sig = None
            if symbol in catalyst_map:
                sig = build_news_signal(symbol, df, catalyst_map[symbol])
            if sig is None:
                sig = is_llm_watchlist_candidate(df)
            if sig:
                sig["symbol"] = symbol
                if sig.get("signal_type") == "WATCHLIST":
                    watchlist_fill_candidates.append(sig)
                elif sig.get("signal_type") == "NEWS":
                    news_fill_candidates.append(sig)
                else:
                    signals.append(sig)

    _flow(
        f"Phase technical-scan completed in {_elapsed(phase_started)} "
        f"| indicators={indicator_count}/{len(scan_universe)} "
        f"signals={len(signals)} news_fill={len(news_fill_candidates)} "
        f"watchlist_fill={len(watchlist_fill_candidates)} prefiltered={prefiltered}"
    )

    news_fill_candidates.sort(key=_rank_signal, reverse=True)
    if MAX_CATALYST_CANDIDATES > 0:
        news_fill_candidates = news_fill_candidates[:MAX_CATALYST_CANDIDATES]
    watchlist_fill_candidates.sort(key=_rank_signal, reverse=True)
    signals.extend(news_fill_candidates)
    signals.extend(watchlist_fill_candidates)

    print(
        f"\n  Done. Loaded from cache: {len(ohlcv_by_symbol)} "
        f"| Prefiltered: {prefiltered} | News fill: {len(news_fill_candidates)} "
        f"| Watchlist fill: {len(watchlist_fill_candidates)} "
        f"| Skipped (open pos): {skipped}"
    )

    signals.sort(key=_rank_signal, reverse=True)

    # Step 4 - LLM validation
    if signals:
        llm_candidates = _select_llm_candidates(signals)
        llm_candidate_ids = {id(sig) for sig in llm_candidates}
        skipped_llm = [sig for sig in signals if id(sig) not in llm_candidate_ids]
        _mark_llm_not_selected(skipped_llm, target_date)

        limit_text = "all" if LLM_VALIDATION_LIMIT <= 0 else f"top {LLM_VALIDATION_LIMIT}"
        print(
            Fore.CYAN
            + f"  LLM gate : sending {len(llm_candidates)}/{len(signals)} signal row(s) "
            + f"({limit_text} unique stocks by local rank)"
        )

        print(Fore.YELLOW + f"\n[4/5] Grok batch validation ({len(llm_candidates)} signal(s))...")
        print(Fore.CYAN + f"      Model  : {GROK_VALIDATOR_MODEL}")
        print(Fore.CYAN + "      Source : Grok web/X-aware batch analysis")
        phase_started = time.perf_counter()
        _flow(f"Phase llm-validation started | provider=grok candidates={len(llm_candidates)}")
        validate_signals_grok_batch(llm_candidates, scan_date=target_date)
        _flow(f"Phase llm-validation completed in {_elapsed(phase_started)}")

        phase_started = time.perf_counter()
        _flow(f"Phase save-breakout-log started | rows={len(signals)}")
        save_breakout_logs(target_date, signals)
        _flow(f"Phase save-breakout-log completed in {_elapsed(phase_started)}")
        print(
            f"  {len(signals)} signal(s) saved to breakout_log "
            f"({len(skipped_llm)} skipped before LLM)."
        )

    else:
        for sig in signals:
            sig["scan_date"] = target_date

    # == Step 5: Display and auto-enter top signals ========================
    phase_started = time.perf_counter()
    _flow("Phase results started")
    print(Fore.YELLOW + f"\n[5/5] Results: {len(signals)} signal candidate(s) found.")
    if signals:
        # Sort: CONFIRM first, then WEAK, then REJECT/SKIPPED; within each group by score.
        _verdict_order = {"CONFIRM": 0, "WEAK": 1, "REJECT": 2, "SKIPPED": 3}
        signals.sort(key=lambda x: (
            _verdict_order.get(x.get("llm_verdict", "SKIPPED"), 3),
            -x["score"]
        ))

        # LLM verdict summary.
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
        
        print(Fore.CYAN + f"\n{'=='*20} SIGNAL CANDIDATES {'=='*20}")
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
                f"Rs.{s['close']}",
                s["rsi"],
                f"{s['vol_ratio']}x",
                s["score"],
                s["stage"],
                llm_display,
                s["reasons"][:45],
            ])
        headers = ["Type", "Symbol", "Price", "RSI", "Vol", "Score", "Stage", "LLM", "Reason"]
        print("\n" + tabulate(rows, headers=headers, tablefmt="grid"))

        # Auto-enter new positions (Stage2 + CONFIRM/WEAK only) 
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
                      f"  [BUY #{new_entries}] {sig['symbol']:<15} @ Rs.{bp} "
                      f"| Target Rs.{tp} | SL Rs.{sl} ({sl_method}) "
                      f"| LLM: {sig.get('llm_verdict','?')}")
                open_count = len(get_open_positions())

    # == TOP PICKS: the final actionable shortlist =========================
    _print_top_picks(signals, target_date)
    _flow(f"Phase results completed in {_elapsed(phase_started)}")
    _flow(f"Daily scan completed in {_elapsed(scan_started)} | signals={len(signals)}")

    return signals


# == Top Picks helper =======================================================

def _print_top_picks(signals: list, scan_date: str):
    """
    From all signals, filter down to the highest-conviction swing trade setups:
      - Stage2 (trending, not parabolic)
      - LLM verdict = CONFIRM  (or WEAK as fallback when no CONFIRMs exist)
      - Score >= TOP_PICKS_MIN_SCORE
      - Vol ratio >= TOP_PICKS_MIN_VOL
      - RSI <= TOP_PICKS_RSI_MAX  (not overbought)
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
    print(Fore.GREEN + f"  * TODAY'S TOP PICKS - {scan_date} *")
    print(Fore.GREEN + f"  (Stage2 | LLM CONFIRM | Score>={TOP_PICKS_MIN_SCORE} | Vol>={TOP_PICKS_MIN_VOL}x | RSI<={TOP_PICKS_RSI_MAX})")
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
              f"  #{rank}  {s['symbol']:<12}  Rs.{bp:<9.2f}  "
              f"Score:{s['score']}  RSI:{s['rsi']:.0f}  Vol:{s['vol_ratio']:.1f}x  "
              f"{_validator_name()}:{s.get('llm_verdict')}({conf}/10){pattern_badges}")
        print(Style.RESET_ALL +
              f"      Entry Rs.{bp:.2f}  ->  Target Rs.{tp:.2f}  ->  SL Rs.{sl:.2f}  "
              f"(Risk {rr}% | 2R reward)")
        if reasoning:
            print(f"      Reasoning: {reasoning[:100]}")
        print()

    print(Fore.GREEN + border + Style.RESET_ALL)
