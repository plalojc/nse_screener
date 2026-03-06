
# ============================================================
# main.py – Entry point (manual or scheduled run)
# ============================================================
import argparse
from data.database        import init_db
from agent.screener_agent import run_daily_scan
from agent.portfolio_tracker import print_portfolio


def main():
    parser = argparse.ArgumentParser(description="NSE Breakout Agent")
    parser.add_argument("command", nargs="?", default="scan",
                        choices=["scan", "portfolio", "schedule", "log", "backtest", "auth"],
                        help="Command to run (default: scan)")
    parser.add_argument("--date", default=None, metavar="YYYY-MM-DD",
                        help="Override scan date, e.g. --date 2026-02-27")
    parser.add_argument("--days", type=int, default=30, metavar="N",
                        help="Days of breakout history to show with 'log' command (default: 30)")
    parser.add_argument("--force-refresh", action="store_true",
                        help="Bypass OHLCV cache and re-download all data from Upstox")
    args = parser.parse_args()

    init_db()

    if args.command == "scan":
        # Auto-route to backtest when a past date is given
        if args.date:
            from datetime import date as _date
            given = _date.fromisoformat(args.date)
            today = _date.today()
            if given < today:
                print(f"  [INFO] {args.date} is a past date → running backtest automatically.")
                print(f"         (Use 'python main.py backtest --date {args.date}' to skip this message)\n")
                _run_backtest(args.date, args.days)
                return
        run_daily_scan(scan_date=args.date, force_refresh=args.force_refresh)
    elif args.command == "portfolio":
        print_portfolio()
    elif args.command == "schedule":
        from scheduler import scheduler
        scheduler.start()
    elif args.command == "log":
        _print_breakout_log(args.days)
    elif args.command == "backtest":
        _run_backtest(args.date, args.days)
    elif args.command == "auth":
        from auth.upstox_auth import refresh_token
        refresh_token()


def _print_breakout_log(days: int):
    """Print the date-wise breakout log with LLM verdicts."""
    from data.database import get_breakout_log
    from tabulate import tabulate
    from colorama import Fore, Style, init
    init(autoreset=True)

    df = get_breakout_log(days=days)
    if df.empty:
        print(f"No breakout signals in the last {days} days.")
        return

    print(Fore.CYAN + f"\n── Breakout Log – last {days} days ({len(df)} signals) ─────")
    rows = []
    for _, r in df.iterrows():
        verdict = str(r.get("llm_verdict") or "")
        conf    = r.get("llm_confidence")
        llm_col = verdict + (f"({conf}/10)" if conf else "")
        if verdict == "CONFIRM":
            llm_col = Fore.GREEN  + llm_col + Style.RESET_ALL
        elif verdict == "REJECT":
            llm_col = Fore.RED    + llm_col + Style.RESET_ALL
        elif verdict == "WEAK":
            llm_col = Fore.YELLOW + llm_col + Style.RESET_ALL
        rows.append([
            r["scan_date"], r["symbol"], r["signal_type"],
            f"₹{r['close']}", r["rsi"], f"{r['vol_ratio']}x",
            r["score"], r["stage"], llm_col,
            str(r.get("llm_reasoning") or "")[:50],
        ])
    headers = ["Date", "Symbol", "Type", "Price", "RSI", "Vol",
               "Score", "Stage", "LLM", "LLM Reasoning"]
    print(tabulate(rows, headers=headers, tablefmt="fancy_grid"))


def _run_backtest(signal_date: str | None, forward_days: int):
    """Run backtesting validation for a given past signal date."""
    from colorama import Fore, Style, init
    init(autoreset=True)

    if not signal_date:
        print(Fore.RED + "  [ERROR] --date YYYY-MM-DD is required for the backtest command.")
        print(         "  Example: python main.py backtest --date 2026-02-01 --days 30")
        return

    from analysis.backtester        import run_backtest
    from report.backtest_report_writer import write as write_backtest_report
    from config import REPORT_DIR

    print(Fore.CYAN + f"\n{'─'*20} BACKTEST {'─'*31}")
    print(f"  Signal date  : {signal_date}")
    print(f"  Forward days : {forward_days}")
    print(f"  Data source  : local SQLite DB only (no API calls)\n")

    results = run_backtest(signal_date, forward_days=forward_days)

    if not results:
        print(Fore.YELLOW + "  No signals found for that date in the local DB.")
        print(             "  Make sure data for that date has been cached (run a scan first).")
        return

    # ── Console summary ────────────────────────────────────────────────────
    wins   = sum(1 for r in results if r["outcome"] == "WIN")
    losses = sum(1 for r in results if r["outcome"] == "LOSS")
    opens  = sum(1 for r in results if r["outcome"] == "OPEN")
    total  = len(results)
    win_rate = round(wins / total * 100, 1) if total else 0

    print(Fore.CYAN + f"\n{'─'*20} BACKTEST SUMMARY {'─'*22}")
    print(f"  Total signals : {total}")
    color = Fore.GREEN if win_rate >= 50 else Fore.YELLOW if win_rate >= 35 else Fore.RED
    print(color + f"  Win Rate      : {win_rate}%  ({wins} WIN / {losses} LOSS / {opens} OPEN)")

    if wins:
        avg_gain = round(sum(r["max_gain_pct"] for r in results if r["outcome"] == "WIN") / wins, 2)
        print(Fore.GREEN + f"  Avg max gain  : +{avg_gain}% (on winning trades)")
    if losses:
        avg_dd = round(sum(r["max_dd_pct"] for r in results if r["outcome"] == "LOSS") / losses, 2)
        print(Fore.RED   + f"  Avg max DD    : {avg_dd}% (on losing trades)")

    # ── Write HTML report ──────────────────────────────────────────────────
    try:
        html_path = write_backtest_report(results, REPORT_DIR, signal_date, forward_days)
        print(Fore.CYAN + f"\n  📄 Backtest report saved → {html_path}")
    except Exception as exc:
        print(Fore.YELLOW + f"  [WARN] Could not write HTML report: {exc}")


if __name__ == "__main__":
    main()

