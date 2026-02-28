
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
                        choices=["scan", "portfolio", "schedule", "log"],
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
        run_daily_scan(scan_date=args.date, force_refresh=args.force_refresh)
    elif args.command == "portfolio":
        print_portfolio()
    elif args.command == "schedule":
        from scheduler import scheduler
        scheduler.start()
    elif args.command == "log":
        _print_breakout_log(args.days)


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


if __name__ == "__main__":
    main()

