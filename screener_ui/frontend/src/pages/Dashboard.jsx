import { useEffect, useState } from "react";
import { CalendarClock, Play } from "lucide-react";
import { API_BASE, api, getAccessToken } from "../api.js";
import { Metric } from "../components/Metric.jsx";
import { Notice } from "../components/Notice.jsx";
import { PageTitle } from "../components/PageTitle.jsx";
import { Progress } from "../components/Progress.jsx";
import { DbRefreshButton } from "../components/RefreshButton.jsx";
import { useAppData } from "../context/AppDataContext.jsx";
import { useCachedLoad } from "../hooks/useCachedLoad.js";
import { money } from "../utils/format.js";

function todayInputValue() {
  const now = new Date();
  const tzOffsetMs = now.getTimezoneOffset() * 60 * 1000;
  return new Date(now.getTime() - tzOffsetMs).toISOString().slice(0, 10);
}

export function Dashboard({ user }) {
  const dashboardLoader = () => api("/api/dashboard");
  const { refreshKey } = useAppData();
  const { data, error, loading, refresh } = useCachedLoad("dashboard", dashboardLoader, []);
  const [job, setJob] = useState(null);
  const [scanDate, setScanDate] = useState(todayInputValue);
  const [forceRefresh, setForceRefresh] = useState(false);
  const [scheduler, setScheduler] = useState({ enabled: false, time: "08:20" });
  const [busyAction, setBusyAction] = useState("");

  useEffect(() => {
    if (data?.scheduler) setScheduler(data.scheduler);
  }, [data]);

  useEffect(() => {
    if (!job?.id || ["success", "failed", "expired"].includes(job.status)) return;
    const source = new EventSource(`${API_BASE}/api/scan/jobs/${job.id}/events?token=${encodeURIComponent(getAccessToken())}`);
    source.addEventListener("snapshot", (event) => {
      const next = JSON.parse(event.data);
      setJob(next);
      if (["success", "failed", "expired"].includes(next.status)) {
        source.close();
        refresh();
        refreshKey("reports", () => api("/api/reports")).catch(() => {});
      }
    });
    source.onerror = () => source.close();
    return () => source.close();
  }, [job?.id]);

  useEffect(() => {
    const activeJob = job?.id ? job : data?.latest_job;
    if (!activeJob?.id || ["success", "failed", "skipped", "expired"].includes(activeJob.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await api(`/api/scan/jobs/${activeJob.id}`);
        setJob(next);
        if (["success", "failed", "expired"].includes(next.status)) {
          refresh();
          refreshKey("reports", () => api("/api/reports")).catch(() => {});
        }
      } catch {
        setJob({
          id: activeJob.id,
          status: "expired",
          progress: 0,
          message: "Scan job expired after server restart. Start a new scan if needed.",
        });
      }
    }, 120000);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status, data?.latest_job?.id, data?.latest_job?.status]);

  async function runScan() {
    setBusyAction("scan");
    try {
      const next = await api("/api/scan/run", {
        method: "POST",
        body: JSON.stringify({
          scan_date: scanDate || null,
          force_refresh: forceRefresh
        })
      });
      setJob(next);
      if (next.status === "skipped") {
        refresh();
        refreshKey("reports", () => api("/api/reports")).catch(() => {});
      }
    } finally {
      setBusyAction("");
    }
  }

  async function saveSchedule() {
    setBusyAction("schedule");
    try {
      const next = await api("/api/scheduler", {
        method: "PUT",
        body: JSON.stringify(scheduler)
      });
      setScheduler(next);
      refresh();
    } finally {
      setBusyAction("");
    }
  }

  const holdings = data?.holdings || {};
  const isAdmin = Boolean(user?.is_admin || data?.is_admin);
  return (
    <section>
      <PageTitle title="Dashboard" action={<DbRefreshButton cacheKey="dashboard" endpoint="/api/dashboard" disabled={loading} />} />
      {error && <Notice tone="danger">{error}</Notice>}
      <div className="metricGrid">
        <Metric label="Reports" value={loading ? "-" : data?.reports_count ?? 0} />
        <Metric label="Watchlist" value={loading ? "-" : data?.watchlist_count ?? 0} />
        <Metric label="Invested" value={money(holdings.invested_amount)} />
        <Metric
          label="P/L"
          value={money(holdings.profit_loss)}
          tone={(holdings.profit_loss || 0) >= 0 ? "gain" : "loss"}
        />
      </div>

      {isAdmin && (
      <div className="twoCol">
        <div className="panel">
          <div className="panelHeader">
            <h2>Scanner</h2>
            <button onClick={runScan} disabled={job?.status === "running" || busyAction === "scan"}>
              <Play size={16} />{busyAction === "scan" ? "Starting..." : "Run Scan"}
            </button>
          </div>
          <div className="formGrid">
            <label>
              Scan date
              <input type="date" value={scanDate} onChange={(e) => setScanDate(e.target.value)} />
            </label>
            <label className="checkLine">
              <input
                type="checkbox"
                checked={forceRefresh}
                onChange={(e) => setForceRefresh(e.target.checked)}
              />
              Force refresh
            </label>
          </div>
          <Progress job={job || data?.latest_job} />
        </div>

        <div className="panel">
            <div className="panelHeader">
              <h2>Schedule</h2>
              <button onClick={saveSchedule} disabled={busyAction === "schedule"}><CalendarClock size={16} />{busyAction === "schedule" ? "Saving..." : "Save"}</button>
            </div>
            <div className="formGrid">
              <label>
                Time
                <input
                  type="time"
                  value={scheduler.time || "08:20"}
                  onChange={(e) => setScheduler({ ...scheduler, time: e.target.value })}
                />
              </label>
              <label className="checkLine">
                <input
                  type="checkbox"
                  checked={Boolean(scheduler.enabled)}
                  onChange={(e) => setScheduler({ ...scheduler, enabled: e.target.checked })}
                />
                Enabled
              </label>
            </div>
            <div className="scheduleMeta">
              <span>Next run</span>
              <strong>{scheduler.next_run_time || "-"}</strong>
            </div>
            <div className="scheduleMeta">
              <span>Latest report</span>
              <strong>{data?.latest_report?.filename || "-"}</strong>
            </div>
          </div>
      </div>
      )}
    </section>
  );
}
