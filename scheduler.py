
# ============================================================
# scheduler.py - APScheduler daily runner
# ============================================================
from apscheduler.schedulers.blocking import BlockingScheduler
from agent.screener_agent import run_daily_scan
from config import SCAN_TIME_IST

scheduler = BlockingScheduler(timezone="Asia/Kolkata")

@scheduler.scheduled_job("cron",
                          hour=int(SCAN_TIME_IST.split(":")[0]),
                          minute=int(SCAN_TIME_IST.split(":")[1]),
                          day_of_week="mon-fri")
def daily_job():
    run_daily_scan()

if __name__ == "__main__":
    print(f"Scheduler started. Scan runs at {SCAN_TIME_IST} IST (Mon-Fri).")
    scheduler.start()
